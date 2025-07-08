# -*- coding: utf-8 -*-

from orderbook.core.axob import AXOB, AX_SIGNAL
from orderbook.messages.axsbe_base import TPM, SecurityIDSource_SSE, SecurityIDSource_SZSE
from orderbook.utils.msg_util import *

import logging

class MU:
    """管理多个AXOB的优化版本"""
    
    def __init__(self, SecurityID_list, SecurityIDSource, instrument_type, load_data=None):
        if load_data is not None:
            self.load(load_data)
        else:
            # 使用字典直接存储 AXOB 实例
            self.axobs = {sid: AXOB(sid, SecurityIDSource, instrument_type) 
                         for sid in SecurityID_list}
            
            self.SecurityIDSource = SecurityIDSource
            self.channel_map = {}  # ChannelID -> {'TPM': ?, 'SecurityID_list': []}
            
            # 简化的统计信息
            self.msg_nb = 0
            self.stats = {
                'order_map_max': 0,
                'level_tree_max': 0,
            }
            
        self._setup_logger(SecurityID_list)
    
    def _setup_logger(self, SecurityID_list):
        """设置日志"""
        import logging
        self.logger = logging.getLogger(f'mu-{SecurityID_list[0]:06d}...')
        g_logger = logging.getLogger('main')
        self.logger.setLevel(g_logger.getEffectiveLevel())
        for h in g_logger.handlers:
            self.logger.addHandler(h)
        
        self.DBG = self.logger.debug
        self.INFO = self.logger.info
        self.WARN = self.logger.warning
        self.ERR = self.logger.error
    
    def onMsg(self, msg):
        """优化的消息处理"""
        # 快速过滤无关消息
        if msg.SecurityID not in self.axobs:
            return
        
        # 获取通道号
        channel_no = self._get_channel_no(msg)
        
        # 更新通道信息
        if channel_no not in self.channel_map:
            self.channel_map[channel_no] = {
                'TPM': TPM.Starting,
                'SecurityID_list': []
            }
        
        channel = self.channel_map[channel_no]
        if msg.SecurityID not in channel['SecurityID_list']:
            channel['SecurityID_list'].append(msg.SecurityID)
        
        # 处理交易阶段转换
        if channel['SecurityID_list']:
            self._handle_phase_transition(msg, channel)
        
        # 转发消息到对应的 AXOB
        self.axobs[msg.SecurityID].onMsg(msg)
        
        # 更新统计
        self.msg_nb += 1
        self._update_stats()
    
    def _get_channel_no(self, msg):
        """获取统一的通道号"""
        if self.SecurityIDSource == SecurityIDSource_SZSE:
            if isinstance(msg, (axsbe_order, axsbe_exe)):
                return msg.ChannelNo - 2000
            elif isinstance(msg, axsbe_snap_stock):
                return msg.ChannelNo - 1000
        return 0
    
    def _handle_phase_transition(self, msg, channel):
        """处理交易阶段转换"""
        old_phase = channel['TPM']
        new_phase = None
        signal = None
        
        # 检查阶段转换条件
        transitions = [
            (TPM.Starting, TPM.OpenCall, self._check_opencall_start, AX_SIGNAL.OPENCALL_BGN),
            (TPM.OpenCall, TPM.PreTradingBreaking, self._check_opencall_end, AX_SIGNAL.OPENCALL_END),
            (TPM.PreTradingBreaking, TPM.AMTrading, self._check_amtrading_start, AX_SIGNAL.AMTRADING_BGN),
            (TPM.AMTrading, TPM.Breaking, self._check_amtrading_end, AX_SIGNAL.AMTRADING_END),
            (TPM.Breaking, TPM.PMTrading, self._check_pmtrading_start, AX_SIGNAL.PMTRADING_BGN),
            (TPM.PMTrading, TPM.CloseCall, self._check_pmtrading_end, AX_SIGNAL.PMTRADING_END),
            (TPM.CloseCall, TPM.Ending, self._check_closecall_end, AX_SIGNAL.ALL_END),
        ]
        
        for from_phase, to_phase, check_func, sig in transitions:
            if old_phase == from_phase and check_func(msg):
                new_phase = to_phase
                signal = sig
                break
        
        # 应用阶段转换
        if new_phase is not None:
            self.INFO(f'Channel {self._get_channel_no(msg)} {old_phase} -> {new_phase}')
            channel['TPM'] = new_phase
            
            # 向所有相关 AXOB 发送信号
            for sid in channel['SecurityID_list']:
                self.axobs[sid].onMsg(signal)
    
    def _check_opencall_start(self, msg):
        """检查是否进入开盘集合竞价"""
        return (isinstance(msg, (axsbe_order, axsbe_exe)) or
                (isinstance(msg, axsbe_status) and msg.TradingPhaseMarket == TPM.OpenCall) or
                (isinstance(msg, axsbe_snap_stock) and 
                 (msg.HHMMSSms >= 91500000 or msg.TradingPhaseMarket == TPM.OpenCall)))
    
    def _check_opencall_end(self, msg):
        """检查是否结束开盘集合竞价"""
        return ((isinstance(msg, axsbe_exe) and msg.TradingPhaseMarket == TPM.PreTradingBreaking) or
                (isinstance(msg, axsbe_status) and msg.TradingPhaseMarket == TPM.ContinuousAutomaticMatching) or
                (isinstance(msg, axsbe_snap_stock) and msg.HHMMSSms >= 92515000))
    
    def _check_amtrading_start(self, msg):
        """检查是否进入上午连续竞价"""
        return ((isinstance(msg, (axsbe_order, axsbe_exe)) and msg.TradingPhaseMarket == TPM.AMTrading) or
                (isinstance(msg, axsbe_snap_stock) and msg.HHMMSSms >= 93000000))
    
    def _check_amtrading_end(self, msg):
        """检查是否结束上午连续竞价"""
        return isinstance(msg, axsbe_snap_stock) and msg.HHMMSSms >= 113015000
    
    def _check_pmtrading_start(self, msg):
        """检查是否进入下午连续竞价"""
        return (isinstance(msg, (axsbe_order, axsbe_exe)) or
                (isinstance(msg, axsbe_snap_stock) and msg.HHMMSSms >= 130000000))
    
    def _check_pmtrading_end(self, msg):
        """检查是否结束下午连续竞价"""
        return ((isinstance(msg, (axsbe_order, axsbe_exe)) and msg.TradingPhaseMarket == TPM.CloseCall) or
                (isinstance(msg, axsbe_snap_stock) and msg.HHMMSSms >= 145715000))
    
    def _check_closecall_end(self, msg):
        """检查是否结束收盘集合竞价"""
        return ((isinstance(msg, axsbe_exe) and msg.TradingPhaseMarket == TPM.Ending) or
                (isinstance(msg, axsbe_status) and msg.TradingPhaseMarket == TPM.Closing) or
                (isinstance(msg, axsbe_snap_stock) and msg.HHMMSSms >= 150015000))
    
    def _update_stats(self):
        """更新统计信息"""
        total_orders = sum(len(axob.order_map) for axob in self.axobs.values())
        total_levels = sum(len(axob.bid_level_tree) + len(axob.ask_level_tree) 
                          for axob in self.axobs.values())
        
        self.stats['order_map_max'] = max(self.stats['order_map_max'], total_orders)
        self.stats['level_tree_max'] = max(self.stats['level_tree_max'], total_levels)
    
    def are_you_ok(self):
        """检查所有 AXOB 状态"""
        ng_list = []
        for sid, axob in self.axobs.items():
            if isTPMfreeze(axob) and not axob.are_you_ok():
                ng_list.append(sid)
        
        if ng_list:
            self.ERR(f'NG count={len(ng_list)}, list={ng_list}')
        
        return len(ng_list) == 0
    
    @property
    def TradingPhaseMarket(self):
        """获取最晚的交易阶段"""
        return max((ch['TPM'] for ch in self.channel_map.values() 
                   if ch['TPM'] <= TPM.Ending), default=TPM.Starting)
