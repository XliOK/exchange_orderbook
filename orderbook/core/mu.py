# -*- coding: utf-8 -*-

from orderbook.core.axob import AXOB, AX_SIGNAL
from orderbook.messages.axsbe_base import TPM, SecurityIDSource_SSE, SecurityIDSource_SZSE
from orderbook.messages import axsbe_order, axsbe_exe, axsbe_snap_stock, axsbe_status
import logging

class MU:
    """管理多个AXOB的优化版本"""
    __slots__ = ['axobs', 'SecurityIDSource', 'channel_map', 'msg_nb', 'logger']
    def __init__(self, SecurityID_list, SecurityIDSource, instrument_type):
        # 直接使用字典存储
        self.axobs = {sid: AXOB(sid, SecurityIDSource, instrument_type) 
                    for sid in SecurityID_list}
        
        self.SecurityIDSource = SecurityIDSource
        self.channel_map = {}  # ChannelID -> {'TPM': ?, 'sids': set()}
        self.msg_nb = 0
        
        # 设置日志
        self.logger = logging.getLogger(f'mu-{SecurityID_list[0]:06d}...')
        g_logger = logging.getLogger('main')
        self.logger.setLevel(g_logger.getEffectiveLevel())
        for h in g_logger.handlers:
            self.logger.addHandler(h)
        
        # 添加日志方法引用
        self.DBG = self.logger.debug
        self.INFO = self.logger.info
        self.WARN = self.logger.warning
        self.ERR = self.logger.error
    
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
    
    def _is_opencall_start(self, msg):
        """开盘集合竞价开始"""
        msg_type = type(msg)
        if msg_type in (axsbe_order, axsbe_exe):
            return True
        if msg_type == axsbe_status:
            return msg.TradingPhaseMarket == TPM.OpenCall
        if msg_type == axsbe_snap_stock:
            return msg.HHMMSSms >= 91500000 or msg.TradingPhaseMarket == TPM.OpenCall
        return False
    
    def _is_opencall_end(self, msg):
        """开盘集合竞价结束"""
        msg_type = type(msg)
        if msg_type == axsbe_exe:
            return msg.TradingPhaseMarket == TPM.PreTradingBreaking
        if msg_type == axsbe_status:
            return msg.TradingPhaseMarket == TPM.ContinuousAutomaticMatching
        if msg_type == axsbe_snap_stock:
            return msg.HHMMSSms >= 92515000
        return False
    
    def _is_amtrading_start(self, msg):
        """上午连续竞价开始"""
        msg_type = type(msg)
        if msg_type in (axsbe_order, axsbe_exe):
            return msg.TradingPhaseMarket == TPM.AMTrading
        if msg_type == axsbe_snap_stock:
            return msg.HHMMSSms >= 93000000
        return False
    
    def _is_amtrading_end(self, msg):
        """上午连续竞价结束"""
        return type(msg) == axsbe_snap_stock and msg.HHMMSSms >= 113015000
    
    def _is_pmtrading_start(self, msg):
        """下午连续竞价开始"""
        msg_type = type(msg)
        return msg_type in (axsbe_order, axsbe_exe) or \
               (msg_type == axsbe_snap_stock and msg.HHMMSSms >= 130000000)
    
    def _is_pmtrading_end(self, msg):
        """下午连续竞价结束"""
        msg_type = type(msg)
        if msg_type in (axsbe_order, axsbe_exe):
            return msg.TradingPhaseMarket == TPM.CloseCall
        if msg_type == axsbe_snap_stock:
            return msg.HHMMSSms >= 145715000
        return False
    
    def _is_closecall_end(self, msg):
        """收盘集合竞价结束"""
        msg_type = type(msg)
        if msg_type == axsbe_exe:
            return msg.TradingPhaseMarket == TPM.Ending
        if msg_type == axsbe_status:
            return msg.TradingPhaseMarket == TPM.Closing
        if msg_type == axsbe_snap_stock:
            return msg.HHMMSSms >= 150015000
        return False

    def _check_phase_transition(self, msg, channel, channel_no):
        """优化的阶段转换检查"""
        old_phase = channel['TPM']
        
        # 使用查找表优化阶段转换
        transitions = {
            TPM.Starting: (TPM.OpenCall, self._is_opencall_start, AX_SIGNAL.OPENCALL_BGN),
            TPM.OpenCall: (TPM.PreTradingBreaking, self._is_opencall_end, AX_SIGNAL.OPENCALL_END),
            TPM.PreTradingBreaking: (TPM.AMTrading, self._is_amtrading_start, AX_SIGNAL.AMTRADING_BGN),
            TPM.AMTrading: (TPM.Breaking, self._is_amtrading_end, AX_SIGNAL.AMTRADING_END),
            TPM.Breaking: (TPM.PMTrading, self._is_pmtrading_start, AX_SIGNAL.PMTRADING_BGN),
            TPM.PMTrading: (TPM.CloseCall, self._is_pmtrading_end, AX_SIGNAL.PMTRADING_END),
            TPM.CloseCall: (TPM.Ending, self._is_closecall_end, AX_SIGNAL.ALL_END),
        }
        
        if old_phase in transitions:
            new_phase, check_func, signal = transitions[old_phase]
            if check_func(msg):
                self.logger.info(f'Channel {channel_no} {old_phase} -> {new_phase}')
                channel['TPM'] = new_phase
                
                # 批量发送信号
                for sid in channel['sids']:
                    self.axobs[sid].onMsg(signal)
    
    def onMsg(self, msg):
        """优化的消息处理"""
        # 快速过滤
        sid = getattr(msg, 'SecurityID', None)
        if sid is None or sid not in self.axobs:
            return
        
        # 获取消息类型和通道号
        msg_type = type(msg)
        channel_no = self._get_channel_no(msg, msg_type)
        
        # 初始化通道信息
        if channel_no not in self.channel_map:
            self.channel_map[channel_no] = {
                'TPM': TPM.Starting,
                'sids': set()
            }
        
        channel = self.channel_map[channel_no]
        channel['sids'].add(sid)
        
        # 检查交易阶段转换
        if msg_type in (axsbe_order, axsbe_exe, axsbe_snap_stock, axsbe_status):
            self._check_phase_transition(msg, channel, channel_no)
        
        # 转发消息
        self.axobs[sid].onMsg(msg)
        self.msg_nb += 1
    
    def _get_channel_no(self, msg, msg_type):
        """快速获取通道号"""
        if self.SecurityIDSource == SecurityIDSource_SZSE:
            if msg_type in (axsbe_order, axsbe_exe):
                return msg.ChannelNo - 2000
            elif msg_type == axsbe_snap_stock:
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
    
    def _is_freeze(self, axob):
        """判断是否在冻结阶段"""
        tpm = axob.TradingPhaseMarket
        return (tpm == TPM.Starting or 
                tpm == TPM.PreTradingBreaking or 
                tpm == TPM.Breaking or 
                tpm >= TPM.Ending)
    
    def are_you_ok(self):
        """检查状态"""
        ng_list = []
        for sid, axob in self.axobs.items():
            if self._is_freeze(axob) and not axob.are_you_ok():
                ng_list.append(sid)
        
        if ng_list:
            self.logger.error(f'NG count={len(ng_list)}, list={ng_list}')
        
        return len(ng_list) == 0
    
    @property
    def TradingPhaseMarket(self):
        """获取最晚的交易阶段"""
        phases = [ch['TPM'] for ch in self.channel_map.values() if ch['TPM'] <= TPM.Ending]
        return max(phases) if phases else TPM.Starting
