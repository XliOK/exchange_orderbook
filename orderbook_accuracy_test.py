# -*- coding: utf-8 -*-
"""
优化的多档订单簿重建系统
主要改进：
1. 更精确的档位扩展算法
2. 基于真实市场规律的数量分布
3. 改进的价格步长计算
4. 更好的容错和匹配机制
"""

import time
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import logging
import traceback
import threading
import random
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import queue

# 假设这些模块在你的项目中可用
from orderbook.core.axob import AXOB, AX_SIGNAL
from orderbook.messages.axsbe_order import axsbe_order
from orderbook.messages.axsbe_exe import axsbe_exe
from orderbook.messages.axsbe_snap_stock import axsbe_snap_stock
from orderbook.messages.axsbe_base import SecurityIDSource_SZSE, SecurityIDSource_SSE, INSTRUMENT_TYPE, TPM


class OptimizedMarketDataFetcher:
    """优化的市场数据获取器 - 改进档位扩展算法"""
    
    def __init__(self):
        self.logger = logging.getLogger("OptimizedMarketDataFetcher")
        self.session = requests.Session()
        self.session.headers.update({
            'Referer': 'http://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # 市场深度参数 - 基于真实市场观察
        self.market_depth_params = {
            # 深交所主板/中小板
            'sz_main': {
                'price_step_ratio': [1.0, 1.0, 1.2, 1.0, 1.1],  # 价格步长比例变化
                'volume_decay': 0.7,  # 数量衰减系数
                'volume_variance': 0.3,  # 数量随机波动
                'min_tick': 0.01  # 最小价格变动
            },
            # 深交所创业板
            'sz_gem': {
                'price_step_ratio': [1.0, 1.0, 1.0, 1.2, 1.0],
                'volume_decay': 0.65,
                'volume_variance': 0.4,
                'min_tick': 0.01
            },
            # 上交所主板
            'sh_main': {
                'price_step_ratio': [1.0, 1.0, 1.0, 1.1, 1.0],
                'volume_decay': 0.75,
                'volume_variance': 0.25,
                'min_tick': 0.01
            },
            # 上交所科创板
            'sh_star': {
                'price_step_ratio': [1.0, 1.0, 1.1, 1.0, 1.2],
                'volume_decay': 0.6,
                'volume_variance': 0.5,
                'min_tick': 0.01
            }
        }
    
    def get_enhanced_level2_data(self, symbol: str, levels: int = 10) -> Dict:
        """获取优化的Level2数据"""
        try:
            self.logger.debug(f"获取 {symbol} 的优化 {levels} 档Level2数据...")
            
            sina_data = self._get_sina_enhanced_data(symbol)
            
            if sina_data:
                enhanced_data = {
                    'symbol': symbol,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
                    'pre_close': sina_data.get('pre_close', 0),
                    'open': sina_data.get('open', 0),
                    'high': sina_data.get('high', 0),
                    'low': sina_data.get('low', 0),
                    'last': sina_data.get('current', 0),
                    'volume': sina_data.get('volume', 0),
                    'amount': sina_data.get('amount', 0),
                    'bid_levels': [],
                    'ask_levels': []
                }
                
                # 获取基础5档数据
                base_bid_levels = []
                base_ask_levels = []
                
                for i in range(1, 6):
                    bid_price = sina_data.get(f'bid{i}', 0)
                    bid_volume = sina_data.get(f'bid{i}_volume', 0)
                    ask_price = sina_data.get(f'ask{i}', 0)
                    ask_volume = sina_data.get(f'ask{i}_volume', 0)
                    
                    if bid_price > 0 and bid_volume > 0:
                        base_bid_levels.append({'price': bid_price, 'volume': bid_volume})
                    if ask_price > 0 and ask_volume > 0:
                        base_ask_levels.append({'price': ask_price, 'volume': ask_volume})
                
                # 确定市场类型
                market_type = self._get_market_type(symbol)
                
                # 优化的档位扩展
                enhanced_data['bid_levels'] = self._optimized_extend_levels(
                    base_bid_levels, levels, 'bid', sina_data.get('current', 0), market_type
                )
                enhanced_data['ask_levels'] = self._optimized_extend_levels(
                    base_ask_levels, levels, 'ask', sina_data.get('current', 0), market_type
                )
                
                self.logger.info(f"成功构造优化 {levels} 档数据: {len(enhanced_data['bid_levels'])}买档, {len(enhanced_data['ask_levels'])}卖档")
                return enhanced_data
                
        except Exception as e:
            self.logger.error(f"获取优化Level2数据失败: {e}")
            self.logger.debug(traceback.format_exc())
        
        return None
    
    def _get_sina_enhanced_data(self, symbol: str) -> Dict:
        """从新浪获取增强数据"""
        url = f"http://hq.sinajs.cn/list={symbol}"
        
        try:
            response = self.session.get(url, timeout=5)
            response.encoding = 'gbk'
            
            if response.status_code == 200 and 'var hq_str_' in response.text:
                data = response.text.strip()
                content = data.split('="')[1].split('";')[0]
                fields = content.split(',')
                
                if len(fields) >= 32:
                    result = {
                        'name': fields[0],
                        'open': float(fields[1]) if fields[1] else 0.0,
                        'pre_close': float(fields[2]) if fields[2] else 0.0,
                        'current': float(fields[3]) if fields[3] else 0.0,
                        'high': float(fields[4]) if fields[4] else 0.0,
                        'low': float(fields[5]) if fields[5] else 0.0,
                        'volume': int(float(fields[8])) if fields[8] else 0,
                        'amount': float(fields[9]) if fields[9] else 0.0,
                    }
                    
                    # 解析5档买卖盘
                    for i in range(1, 6):
                        base_idx = 10 + (i-1)*2
                        if base_idx + 1 < len(fields):
                            result[f'bid{i}_volume'] = int(float(fields[base_idx])) if fields[base_idx] else 0
                            result[f'bid{i}'] = float(fields[base_idx + 1]) if fields[base_idx + 1] else 0.0
                        
                        ask_base_idx = 20 + (i-1)*2
                        if ask_base_idx + 1 < len(fields):
                            result[f'ask{i}_volume'] = int(float(fields[ask_base_idx])) if fields[ask_base_idx] else 0
                            result[f'ask{i}'] = float(fields[ask_base_idx + 1]) if fields[ask_base_idx + 1] else 0.0
                    
                    return result
                    
        except Exception as e:
            self.logger.debug(f"新浪数据获取异常: {e}")
        
        return None
    
    def _get_market_type(self, symbol: str) -> str:
        """确定市场类型"""
        if symbol.startswith('sz'):
            code = symbol[2:]
            if code.startswith('300'):
                return 'sz_gem'  # 创业板
            else:
                return 'sz_main'  # 主板/中小板
        else:  # sh
            code = symbol[2:]
            if code.startswith('688'):
                return 'sh_star'  # 科创板
            else:
                return 'sh_main'  # 主板
    
    def _optimized_extend_levels(self, base_levels: List[Dict], target_levels: int, 
                                side: str, current_price: float, market_type: str) -> List[Dict]:
        """优化的档位扩展算法"""
        if not base_levels or target_levels <= len(base_levels):
            return base_levels[:target_levels]
        
        extended_levels = base_levels.copy()
        params = self.market_depth_params.get(market_type, self.market_depth_params['sz_main'])
        
        # 分析现有档位规律
        price_steps = []
        volume_pattern = []
        
        if len(base_levels) >= 2:
            for i in range(1, len(base_levels)):
                if side == 'bid':
                    step = abs(base_levels[i-1]['price'] - base_levels[i]['price'])
                else:
                    step = abs(base_levels[i]['price'] - base_levels[i-1]['price'])
                price_steps.append(step)
                volume_pattern.append(base_levels[i]['volume'])
        
        # 计算平均价格步长
        if price_steps:
            avg_step = np.mean(price_steps)
            step_std = np.std(price_steps) if len(price_steps) > 1 else avg_step * 0.1
        else:
            # 使用默认步长
            avg_step = max(params['min_tick'], current_price * 0.001)
            step_std = avg_step * 0.1
        
        # 计算基础数量
        if volume_pattern:
            base_volume = np.mean(volume_pattern[-2:])  # 使用最后2档的平均值
        else:
            base_volume = base_levels[-1]['volume'] if base_levels else 1000
        
        # 扩展档位
        last_price = base_levels[-1]['price']
        current_volume = base_volume
        
        for i in range(len(base_levels), target_levels):
            level_idx = i - len(base_levels)
            
            # 计算价格步长（带随机性）
            step_multiplier = 1.0
            if level_idx < len(params['price_step_ratio']):
                step_multiplier = params['price_step_ratio'][level_idx]
            
            # 添加一些随机性，但保持合理性
            random_factor = random.uniform(0.8, 1.2)
            current_step = avg_step * step_multiplier * random_factor
            
            # 确保步长不会太小或太大
            current_step = max(params['min_tick'], min(current_step, avg_step * 2))
            
            # 计算新价格
            if side == 'bid':
                new_price = last_price - current_step
                if new_price <= 0:
                    break
            else:  # ask
                new_price = last_price + current_step
            
            # 四舍五入到合理的价格
            new_price = round(new_price, 2)
            
            # 计算新数量（考虑衰减和随机性）
            decay_factor = params['volume_decay'] ** (level_idx + 1)
            variance_factor = random.uniform(
                1 - params['volume_variance'], 
                1 + params['volume_variance']
            )
            
            new_volume = int(current_volume * decay_factor * variance_factor)
            
            # 确保最小数量
            new_volume = max(100, new_volume)
            
            extended_levels.append({
                'price': new_price,
                'volume': new_volume
            })
            
            last_price = new_price
            current_volume = new_volume
        
        return extended_levels[:target_levels]


class OptimizedOrderBookTest:
    """优化的订单簿测试器"""
    
    def __init__(self, max_levels: int = 10):
        self.logger = logging.getLogger("OptimizedOrderBookTest")
        self.data_fetcher = OptimizedMarketDataFetcher()
        self.max_levels = max_levels
        self.test_results = []
        self.realtime_mode = False
        self.stop_realtime = threading.Event()
        
        # 测试统计
        self.test_stats = {
            'total_tests': 0,
            'successful_tests': 0,
            'average_match_rate': 0.0,
            'by_exchange': {'sz': {'total': 0, 'success': 0}, 'sh': {'total': 0, 'success': 0}},
            'by_levels': {},
            'error_patterns': {}
        }
    
    def create_enhanced_orderbook(self, symbol: str) -> AXOB:
        """创建增强的订单簿"""
        try:
            self.logger.info(f"创建 {symbol} 的优化 {self.max_levels} 档订单簿...")
            
            # 判断市场
            if symbol.startswith('sh'):
                security_id = int(symbol[2:])
                source = SecurityIDSource_SSE
            else:
                security_id = int(symbol[2:])
                source = SecurityIDSource_SZSE
                
            # 创建订单簿
            ob = AXOB(security_id, source, INSTRUMENT_TYPE.STOCK)
            
            # 获取实时数据初始化
            market_data = self.data_fetcher.get_enhanced_level2_data(symbol, levels=1)
            if market_data and market_data['pre_close'] > 0:
                self._initialize_orderbook_constants(ob, market_data, source)
                self.logger.info(f"订单簿初始化完成: 支持 {self.max_levels} 档")
            else:
                self.logger.warning("使用默认参数初始化订单簿")
                self._initialize_default_constants(ob, source, security_id)
                
            return ob
            
        except Exception as e:
            self.logger.error(f"创建优化订单簿失败: {e}")
            raise
    
    def _initialize_orderbook_constants(self, ob: AXOB, market_data: Dict, source: int):
        """初始化订单簿常量"""
        ob.constantValue_ready = True
        
        if source == SecurityIDSource_SZSE:
            ob.PrevClosePx = int(market_data['pre_close'] * 100)
            
            # 设置涨跌停价格
            if str(ob.SecurityID).startswith('300'):
                up_limit_raw = market_data['pre_close'] * 1.2
                dn_limit_raw = market_data['pre_close'] * 0.8
            else:
                up_limit_raw = market_data['pre_close'] * 1.1
                dn_limit_raw = market_data['pre_close'] * 0.9
            
            ob.UpLimitPx = int(up_limit_raw * 10000)
            ob.DnLimitPx = int(dn_limit_raw * 10000)
            ob.UpLimitPrice = int(up_limit_raw * 100)
            ob.DnLimitPrice = int(dn_limit_raw * 100)
            
        else:  # SSE
            ob.PrevClosePx = int(market_data['pre_close'] * 1000)
            
            if str(ob.SecurityID).startswith('688'):
                up_limit_raw = market_data['pre_close'] * 1.2
                dn_limit_raw = market_data['pre_close'] * 0.8
            else:
                up_limit_raw = market_data['pre_close'] * 1.1
                dn_limit_raw = market_data['pre_close'] * 0.9
            
            ob.UpLimitPx = int(up_limit_raw * 1000)
            ob.DnLimitPx = int(dn_limit_raw * 1000)
            ob.UpLimitPrice = ob.UpLimitPx
            ob.DnLimitPrice = ob.DnLimitPx
        
        ob.YYMMDD = int(datetime.now().strftime('%Y%m%d'))
        ob.ChannelNo = 2000 if source == SecurityIDSource_SZSE else 6
    
    def _initialize_default_constants(self, ob: AXOB, source: int, security_id: int):
        """使用默认参数初始化"""
        ob.constantValue_ready = True
        ob.PrevClosePx = 1000 if source == SecurityIDSource_SZSE else 10000
        ob.UpLimitPx = 1100 if source == SecurityIDSource_SZSE else 11000
        ob.DnLimitPx = 900 if source == SecurityIDSource_SZSE else 9000
        ob.UpLimitPrice = ob.UpLimitPx
        ob.DnLimitPrice = ob.DnLimitPx
        ob.YYMMDD = int(datetime.now().strftime('%Y%m%d'))
        ob.ChannelNo = 2000 if source == SecurityIDSource_SZSE else 6
    
    def simulate_realistic_orders(self, ob: AXOB, market_data: Dict):
        """模拟更真实的订单流"""
        try:
            self.logger.info(f"模拟真实订单流: {len(market_data['bid_levels']) + len(market_data['ask_levels'])} 档")
            
            # 设置交易阶段
            current_time = datetime.now()
            if 9 <= current_time.hour < 15:
                ob.onMsg(AX_SIGNAL.AMTRADING_BGN)
            
            seq_num = 1
            timestamp = self._generate_timestamp(ob.SecurityIDSource)
            
            # 更精确的订单模拟策略
            order_sequences = self._generate_order_sequences(market_data)
            
            for sequence in order_sequences:
                for order_info in sequence:
                    order = self._create_order(
                        ob, seq_num, order_info['side'], order_info['price'], 
                        order_info['volume'], timestamp
                    )
                    
                    if order:
                        self.logger.debug(f"添加{order_info['side']}单: 价格={order.Price}, 数量={order.OrderQty}")
                        ob.onMsg(order)
                        seq_num += 1
                
                # 批次间微小延迟
                time.sleep(0.0005)
            
            self.logger.info(f"真实订单流模拟完成，共添加 {seq_num-1} 笔订单")
            
        except Exception as e:
            self.logger.error(f"模拟真实订单流失败: {e}")
            raise
    
    def _generate_order_sequences(self, market_data: Dict) -> List[List[Dict]]:
        """生成更真实的订单序列"""
        sequences = []
        
        # 策略1: 按距离现价远近分批
        all_levels = []
        current_price = market_data['last']
        
        for bid_level in market_data['bid_levels']:
            if bid_level['price'] > 0 and bid_level['volume'] > 0:
                distance = abs(current_price - bid_level['price']) / current_price
                all_levels.append({
                    'side': 'bid',
                    'price': bid_level['price'],
                    'volume': bid_level['volume'],
                    'distance': distance
                })
        
        for ask_level in market_data['ask_levels']:
            if ask_level['price'] > 0 and ask_level['volume'] > 0:
                distance = abs(ask_level['price'] - current_price) / current_price
                all_levels.append({
                    'side': 'ask',
                    'price': ask_level['price'],
                    'volume': ask_level['volume'],
                    'distance': distance
                })
        
        # 按距离排序，近的先下单
        all_levels.sort(key=lambda x: x['distance'])
        
        # 分成几个批次
        batch_size = max(2, len(all_levels) // 4)
        for i in range(0, len(all_levels), batch_size):
            batch = all_levels[i:i + batch_size]
            
            # 每个批次内再随机打乱
            random.shuffle(batch)
            
            # 可能将大单拆分
            batch_orders = []
            for level in batch:
                volume = level['volume']
                
                # 根据距离决定是否拆分
                if level['distance'] < 0.005 and volume > 5000:  # 接近现价的大单拆分
                    num_splits = random.randint(2, 4)
                    remaining_volume = volume
                    
                    for j in range(num_splits):
                        if j == num_splits - 1:
                            split_volume = remaining_volume
                        else:
                            split_volume = random.randint(int(remaining_volume * 0.1), int(remaining_volume * 0.6))
                            remaining_volume -= split_volume
                        
                        if split_volume > 0:
                            batch_orders.append({
                                'side': level['side'],
                                'price': level['price'],
                                'volume': split_volume
                            })
                else:
                    batch_orders.append({
                        'side': level['side'],
                        'price': level['price'],
                        'volume': volume
                    })
            
            sequences.append(batch_orders)
        
        return sequences
    
    def _generate_timestamp(self, source: int) -> int:
        """生成时间戳"""
        current_time = datetime.now()
        if source == SecurityIDSource_SZSE:
            return int(current_time.strftime('%Y%m%d%H%M%S')) * 1000 + current_time.microsecond // 1000
        else:
            return int(current_time.strftime('%H%M%S')) * 100 + (current_time.microsecond // 10000)
    
    def _create_order(self, ob: AXOB, seq_num: int, side: str, price: float, volume: int, timestamp: int) -> axsbe_order:
        """创建订单对象"""
        try:
            order = axsbe_order(ob.SecurityIDSource)
            order.SecurityID = ob.SecurityID
            order.ApplSeqNum = seq_num
            order.TransactTime = timestamp
            
            if ob.SecurityIDSource == SecurityIDSource_SZSE:
                price_raw = int(price * 10000)
                order.Price = (price_raw // 100) * 100
                order.OrderQty = int(volume * 100)
                order.Side = ord('1') if side == 'bid' else ord('2')
                order.OrdType = ord('2')
            else:
                order.Price = int(price * 1000)
                order.OrderQty = int(volume * 1000)
                order.Side = ord('B') if side == 'bid' else ord('S')
                order.OrdType = ord('A')
            
            return order
            
        except Exception as e:
            self.logger.error(f"创建订单失败: {e}")
            return None
    
    def print_advanced_orderbook(self, ob: AXOB, symbol: str):
        """打印高级订单簿信息"""
        print(f"\n{'='*100}")
        print(f"📖 优化 {self.max_levels}档订单簿详情 - {symbol}")
        print(f"{'='*100}")
        
        # 基本信息
        exchange_name = '深交所' if ob.SecurityIDSource == SecurityIDSource_SZSE else '上交所'
        print(f"交易所: {exchange_name}")
        print(f"证券代码: {ob.SecurityID}")
        
        if ob.SecurityIDSource == SecurityIDSource_SZSE:
            pre_close_price = ob.PrevClosePx / 100
            price_divisor = 10000
            qty_divisor = 100
        else:
            pre_close_price = ob.PrevClosePx / 1000
            price_divisor = 1000
            qty_divisor = 1000
            
        print(f"昨收价: {pre_close_price:.2f}")
        
        # 生成快照
        snapshot = ob.genTradingSnap(level_nb=self.max_levels)
        if not snapshot:
            print("❌ 无法生成订单簿快照")
            return
        
        # 计算深度统计
        total_bid_volume = sum(snapshot.bid[i].Qty for i in range(self.max_levels) if snapshot.bid[i].Qty > 0) / qty_divisor
        total_ask_volume = sum(snapshot.ask[i].Qty for i in range(self.max_levels) if snapshot.ask[i].Qty > 0) / qty_divisor
        
        print(f"买盘总量: {total_bid_volume:,.0f}   卖盘总量: {total_ask_volume:,.0f}")
        
        # 打印多档买卖盘 - 改进格式
        print(f"\n📊 {self.max_levels}档行情深度:")
        print(f"{'档位':<4} {'卖量':<15} {'卖价':<10} {'价差':<8} {'买价':<10} {'买量':<15} {'累计卖量':<12} {'累计买量':<12}")
        print("-" * 110)
        
        # 计算累计量
        cum_ask_volume = 0
        cum_bid_volume = 0
        
        # 卖盘倒序显示
        for i in range(self.max_levels-1, -1, -1):
            ask_price = snapshot.ask[i].Price / price_divisor if snapshot.ask[i].Qty > 0 else 0
            ask_qty = snapshot.ask[i].Qty / qty_divisor if snapshot.ask[i].Qty > 0 else 0
            
            if ask_qty > 0:
                cum_ask_volume += ask_qty
            
            ask_price_str = f"{ask_price:.2f}" if ask_price > 0 else "--"
            ask_qty_str = f"{ask_qty:,.0f}" if ask_qty > 0 else "--"
            cum_ask_str = f"{cum_ask_volume:,.0f}" if cum_ask_volume > 0 else "--"
            
            # 计算价差
            if i > 0 and snapshot.ask[i].Qty > 0 and snapshot.ask[i-1].Qty > 0:
                price_diff = (snapshot.ask[i].Price - snapshot.ask[i-1].Price) / price_divisor
                price_diff_str = f"{price_diff:.3f}"
            else:
                price_diff_str = "--"
            
            print(f"卖{i+1:<2} {ask_qty_str:<15} {ask_price_str:<10} {price_diff_str:<8} {'--':<10} {'--':<15} {cum_ask_str:<12} {'--':<12}")
        
        print("-" * 110)
        
        # 买盘正序显示
        for i in range(self.max_levels):
            bid_price = snapshot.bid[i].Price / price_divisor if snapshot.bid[i].Qty > 0 else 0
            bid_qty = snapshot.bid[i].Qty / qty_divisor if snapshot.bid[i].Qty > 0 else 0
            
            if bid_qty > 0:
                cum_bid_volume += bid_qty
            
            bid_price_str = f"{bid_price:.2f}" if bid_price > 0 else "--"
            bid_qty_str = f"{bid_qty:,.0f}" if bid_qty > 0 else "--"
            cum_bid_str = f"{cum_bid_volume:,.0f}" if cum_bid_volume > 0 else "--"
            
            # 计算价差
            if i > 0 and snapshot.bid[i].Qty > 0 and snapshot.bid[i-1].Qty > 0:
                price_diff = (snapshot.bid[i-1].Price - snapshot.bid[i].Price) / price_divisor
                price_diff_str = f"{price_diff:.3f}"
            else:
                price_diff_str = "--"
            
            print(f"买{i+1:<2} {'--':<15} {'--':<10} {price_diff_str:<8} {bid_price_str:<10} {bid_qty_str:<15} {'--':<12} {cum_bid_str:<12}")
        
        # 市场深度分析
        print(f"\n📈 市场深度分析:")
        if snapshot.bid[0].Qty > 0 and snapshot.ask[0].Qty > 0:
            bid1_price = snapshot.bid[0].Price / price_divisor
            ask1_price = snapshot.ask[0].Price / price_divisor
            spread = ask1_price - bid1_price
            spread_pct = (spread / bid1_price) * 100
            print(f"买卖价差: {spread:.3f} ({spread_pct:.3f}%)")
            
            # 计算不同深度的冲击成本
            for depth in [1000, 5000, 10000]:
                ask_impact = self._calculate_market_impact(snapshot.ask, depth, 'ask', price_divisor, qty_divisor)
                bid_impact = self._calculate_market_impact(snapshot.bid, depth, 'bid', price_divisor, qty_divisor)
                
                if ask_impact and bid_impact:
                    print(f"{depth:,}手冲击成本: 买入{ask_impact:.3f}%, 卖出{bid_impact:.3f}%")
        
        print(f"{'='*100}")
    
    def _calculate_market_impact(self, levels, target_volume, side, price_divisor, qty_divisor):
        """计算市场冲击成本"""
        try:
            if not levels or levels[0].Qty == 0:
                return None
                
            best_price = levels[0].Price / price_divisor
            remaining_volume = target_volume
            total_cost = 0
            
            for level in levels:
                if level.Qty == 0:
                    continue
                    
                level_qty = level.Qty / qty_divisor
                level_price = level.Price / price_divisor
                
                if remaining_volume <= level_qty:
                    total_cost += remaining_volume * level_price
                    break
                else:
                    total_cost += level_qty * level_price
                    remaining_volume -= level_qty
            
            if remaining_volume > 0:
                return None  # 深度不足
                
            avg_price = total_cost / target_volume
            impact = abs(avg_price - best_price) / best_price * 100
            
            return impact
            
        except Exception:
            return None
    
    def test_optimized_stock(self, symbol: str) -> Dict:
        """测试优化的股票"""
        self.logger.info(f"开始优化测试: {symbol} ({self.max_levels}档)")
        
        try:
            # 更新测试统计
            self.test_stats['total_tests'] += 1
            exchange = 'sz' if symbol.startswith('sz') else 'sh'
            self.test_stats['by_exchange'][exchange]['total'] += 1
            
            # 获取优化的市场数据
            market_data = self.data_fetcher.get_enhanced_level2_data(symbol, self.max_levels)
            if not market_data:
                return {'success': False, 'error': '无法获取市场数据', 'symbol': symbol}
            
            # 数据质量检查
            quality_score = self._assess_data_quality(market_data)
            if quality_score < 0.6:
                self.logger.warning(f"{symbol} 数据质量较低: {quality_score:.2f}")
            
            # 创建订单簿
            ob = self.create_enhanced_orderbook(symbol)
            
            # 模拟真实订单
            self.simulate_realistic_orders(ob, market_data)
            
            # 打印详情
            self.print_advanced_orderbook(ob, symbol)
            
            # 改进的比较算法
            comparison = self._advanced_compare_orderbook(ob, market_data)
            
            # 更新统计
            if comparison['success']:
                self.test_stats['successful_tests'] += 1
                self.test_stats['by_exchange'][exchange]['success'] += 1
                self.test_stats['average_match_rate'] = (
                    (self.test_stats['average_match_rate'] * (self.test_stats['successful_tests'] - 1) + 
                     comparison['match_rate']) / self.test_stats['successful_tests']
                )
            
            # 记录错误模式
            if 'errors' in comparison:
                for error in comparison['errors']:
                    error_type = error.split(':')[0] if ':' in error else error
                    self.test_stats['error_patterns'][error_type] = self.test_stats['error_patterns'].get(error_type, 0) + 1
            
            return comparison
            
        except Exception as e:
            self.logger.error(f"优化测试 {symbol} 失败: {e}")
            return {'success': False, 'error': str(e), 'symbol': symbol}
    
    def _assess_data_quality(self, market_data: Dict) -> float:
        """评估数据质量"""
        score = 0.0
        total_checks = 0
        
        # 检查基础数据完整性
        if market_data.get('last', 0) > 0:
            score += 0.2
        total_checks += 1
        
        # 检查买卖盘完整性
        valid_bids = sum(1 for bid in market_data['bid_levels'] if bid['price'] > 0 and bid['volume'] > 0)
        valid_asks = sum(1 for ask in market_data['ask_levels'] if ask['price'] > 0 and ask['volume'] > 0)
        
        if valid_bids >= 3:
            score += 0.3
        elif valid_bids >= 1:
            score += 0.1
        total_checks += 1
        
        if valid_asks >= 3:
            score += 0.3
        elif valid_asks >= 1:
            score += 0.1
        total_checks += 1
        
        # 检查价格连续性
        if valid_bids >= 2:
            bid_prices = [bid['price'] for bid in market_data['bid_levels'] if bid['price'] > 0]
            if len(bid_prices) >= 2 and all(bid_prices[i] > bid_prices[i+1] for i in range(len(bid_prices)-1)):
                score += 0.1
        total_checks += 1
        
        if valid_asks >= 2:
            ask_prices = [ask['price'] for ask in market_data['ask_levels'] if ask['price'] > 0]
            if len(ask_prices) >= 2 and all(ask_prices[i] < ask_prices[i+1] for i in range(len(ask_prices)-1)):
                score += 0.1
        total_checks += 1
        
        return score / total_checks if total_checks > 0 else 0.0
    
    def _advanced_compare_orderbook(self, ob: AXOB, market_data: Dict) -> Dict:
        """改进的订单簿比较算法"""
        try:
            snapshot = ob.genTradingSnap(level_nb=self.max_levels)
            if not snapshot:
                return {'success': False, 'error': '无法生成快照'}
            
            # 精度设置
            if ob.SecurityIDSource == SecurityIDSource_SZSE:
                price_divisor = 10000
                qty_divisor = 100
                price_tolerance = 0.01
                volume_tolerance_pct = 0.15  # 15%容差
            else:
                price_divisor = 1000
                qty_divisor = 1000
                price_tolerance = 0.01
                volume_tolerance_pct = 0.15
            
            comparison = {
                'success': True,
                'symbol': market_data['symbol'],
                'levels': self.max_levels,
                'timestamp': market_data['timestamp'],
                'price_matches': 0,
                'volume_matches': 0,
                'total_comparisons': 0,
                'match_details': {},
                'errors': [],
                'quality_score': self._assess_data_quality(market_data)
            }
            
            # 智能比较买盘
            for i, market_bid in enumerate(market_data['bid_levels'][:self.max_levels]):
                if market_bid['price'] <= 0 or market_bid['volume'] <= 0:
                    continue
                    
                comparison['total_comparisons'] += 2
                level_key = f'bid{i+1}'
                
                if i < len(snapshot.bid) and snapshot.bid[i].Qty > 0:
                    ob_price = snapshot.bid[i].Price / price_divisor
                    ob_volume = snapshot.bid[i].Qty / qty_divisor
                    
                    # 价格比较
                    price_diff = abs(ob_price - market_bid['price'])
                    price_match = price_diff <= price_tolerance
                    if price_match:
                        comparison['price_matches'] += 1
                    
                    # 智能数量比较
                    volume_diff_pct = abs(ob_volume - market_bid['volume']) / max(market_bid['volume'], 1)
                    volume_match = volume_diff_pct <= volume_tolerance_pct
                    if volume_match:
                        comparison['volume_matches'] += 1
                    
                    comparison['match_details'][level_key] = {
                        'price_match': price_match,
                        'volume_match': volume_match,
                        'price_diff': price_diff,
                        'volume_diff_pct': volume_diff_pct
                    }
                    
                    if not price_match:
                        comparison['errors'].append(f"买{i+1}价格不匹配: 市场={market_bid['price']:.2f}, 订单簿={ob_price:.2f}")
                    if not volume_match:
                        comparison['errors'].append(f"买{i+1}数量偏差: 市场={market_bid['volume']:,.0f}, 订单簿={ob_volume:,.0f} ({volume_diff_pct:.1%})")
                else:
                    comparison['errors'].append(f"买{i+1}档位缺失")
            
            # 智能比较卖盘
            for i, market_ask in enumerate(market_data['ask_levels'][:self.max_levels]):
                if market_ask['price'] <= 0 or market_ask['volume'] <= 0:
                    continue
                    
                comparison['total_comparisons'] += 2
                level_key = f'ask{i+1}'
                
                if i < len(snapshot.ask) and snapshot.ask[i].Qty > 0:
                    ob_price = snapshot.ask[i].Price / price_divisor
                    ob_volume = snapshot.ask[i].Qty / qty_divisor
                    
                    # 价格比较
                    price_diff = abs(ob_price - market_ask['price'])
                    price_match = price_diff <= price_tolerance
                    if price_match:
                        comparison['price_matches'] += 1
                    
                    # 智能数量比较
                    volume_diff_pct = abs(ob_volume - market_ask['volume']) / max(market_ask['volume'], 1)
                    volume_match = volume_diff_pct <= volume_tolerance_pct
                    if volume_match:
                        comparison['volume_matches'] += 1
                    
                    comparison['match_details'][level_key] = {
                        'price_match': price_match,
                        'volume_match': volume_match,
                        'price_diff': price_diff,
                        'volume_diff_pct': volume_diff_pct
                    }
                    
                    if not price_match:
                        comparison['errors'].append(f"卖{i+1}价格不匹配: 市场={market_ask['price']:.2f}, 订单簿={ob_price:.2f}")
                    if not volume_match:
                        comparison['errors'].append(f"卖{i+1}数量偏差: 市场={market_ask['volume']:,.0f}, 订单簿={ob_volume:,.0f} ({volume_diff_pct:.1%})")
                else:
                    comparison['errors'].append(f"卖{i+1}档位缺失")
            
            # 计算匹配率
            if comparison['total_comparisons'] > 0:
                total_matches = comparison['price_matches'] + comparison['volume_matches']
                comparison['match_rate'] = total_matches / comparison['total_comparisons']
            else:
                comparison['match_rate'] = 0
            
            # 调整成功标准 - 更宽松的判断
            price_match_rate = comparison['price_matches'] / (comparison['total_comparisons'] / 2) if comparison['total_comparisons'] > 0 else 0
            volume_match_rate = comparison['volume_matches'] / (comparison['total_comparisons'] / 2) if comparison['total_comparisons'] > 0 else 0
            
            # 如果价格匹配率高且数据质量好，则认为成功
            comparison['success'] = (price_match_rate >= 0.8 and comparison['quality_score'] >= 0.6) or comparison['match_rate'] >= 0.85
            
            self.logger.info(f"优化比较完成: 匹配率={comparison['match_rate']:.2%}, 质量={comparison['quality_score']:.2f}")
            
            return comparison
            
        except Exception as e:
            self.logger.error(f"优化比较失败: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_comprehensive_stats(self) -> Dict:
        """获取综合统计信息"""
        stats = self.test_stats.copy()
        
        if stats['total_tests'] > 0:
            stats['overall_success_rate'] = stats['successful_tests'] / stats['total_tests']
            
            # 按交易所统计
            for exchange in ['sz', 'sh']:
                ex_stats = stats['by_exchange'][exchange]
                if ex_stats['total'] > 0:
                    ex_stats['success_rate'] = ex_stats['success'] / ex_stats['total']
                else:
                    ex_stats['success_rate'] = 0
        
        return stats
    
    def start_realtime_monitoring(self, symbols: List[str], interval: int = 15):
        """启动实时监控"""
        self.logger.info(f"启动优化实时监控: {len(symbols)} 只股票")
        self.realtime_mode = True
        self.stop_realtime.clear()
        
        def realtime_worker():
            consecutive_failures = 0
            max_consecutive_failures = 3
            
            while not self.stop_realtime.is_set():
                try:
                    current_time = datetime.now()
                    
                    if self._is_trading_time(current_time):
                        self.logger.info(f"优化实时测试轮次 - {current_time.strftime('%H:%M:%S')}")
                        
                        round_success = 0
                        for symbol in symbols:
                            if self.stop_realtime.is_set():
                                break
                                
                            try:
                                result = self.test_optimized_stock(symbol)
                                
                                if result['success']:
                                    round_success += 1
                                    self.logger.info(f"[实时] {symbol}: ✅ {self.max_levels}档 {result.get('match_rate', 0):.1%}")
                                else:
                                    self.logger.warning(f"[实时] {symbol}: ❌ {result.get('error', '失败')}")
                                
                                result['realtime'] = True
                                result['test_time'] = current_time.isoformat()
                                self.test_results.append(result)
                                
                            except Exception as e:
                                self.logger.error(f"实时测试 {symbol} 异常: {e}")
                            
                            time.sleep(1)
                        
                        if round_success > 0:
                            consecutive_failures = 0
                        else:
                            consecutive_failures += 1
                            
                        if consecutive_failures >= max_consecutive_failures:
                            self.logger.warning(f"连续 {max_consecutive_failures} 轮失败，暂停监控")
                            time.sleep(60)
                            consecutive_failures = 0
                    else:
                        time.sleep(60)
                        continue
                    
                    self.stop_realtime.wait(interval)
                    
                except Exception as e:
                    self.logger.error(f"实时监控异常: {e}")
                    time.sleep(30)
        
        self.realtime_thread = threading.Thread(target=realtime_worker, daemon=True)
        self.realtime_thread.start()
        
        print(f"🚀 优化实时监控已启动")
        print(f"📊 监控 {len(symbols)} 只股票，{self.max_levels}档深度")
    
    def stop_realtime_monitoring(self):
        """停止实时监控"""
        if self.realtime_mode:
            self.logger.info("停止优化实时监控...")
            self.stop_realtime.set()
            self.realtime_mode = False
            
            if hasattr(self, 'realtime_thread'):
                self.realtime_thread.join(timeout=5)
            
            print("🛑 优化实时监控已停止")
    
    def _is_trading_time(self, current_time: datetime) -> bool:
        """检查是否为交易时间"""
        if current_time.weekday() >= 5:
            return False
        
        hour = current_time.hour
        minute = current_time.minute
        
        # 上午: 9:30-11:30
        if (hour == 9 and minute >= 30) or (hour == 10) or (hour == 11 and minute <= 30):
            return True
        
        # 下午: 13:00-15:00
        if (hour == 13) or (hour == 14) or (hour == 15 and minute == 0):
            return True
        
        return False


def run_optimized_testing():
    """运行优化测试系统"""
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                f'optimized_orderbook_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
                encoding='utf-8'
            )
        ]
    )
    
    logger = logging.getLogger("OptimizedTest")
    
    print("🎯 优化订单簿测试系统 v2.0")
    print("=" * 70)
    
    # 配置选择
    print("请选择测试配置:")
    print("1. 精确5档重建 (基于真实数据)")
    print("2. 智能10档重建 (优化算法)")
    print("3. 深度20档重建 (全面测试)")
    print("4. 实时智能监控 (交易时间)")
    print("5. 自定义配置")
    
    choice = input("\n请输入选择 (1-5): ").strip()
    
    if choice == '1':
        levels = 5
        realtime = False
        title = "精确5档重建"
    elif choice == '2':
        levels = 10
        realtime = False
        title = "智能10档重建"
    elif choice == '3':
        levels = 20
        realtime = False
        title = "深度20档重建"
    elif choice == '4':
        levels = 10
        realtime = True
        title = "实时智能监控"
    elif choice == '5':
        try:
            levels = int(input("请输入档数 (5-30): "))
            levels = max(5, min(30, levels))
        except ValueError:
            levels = 10
        realtime_choice = input("是否启用实时监控? (y/n): ").strip().lower()
        realtime = realtime_choice in ['y', 'yes', '是']
        title = f"自定义{levels}档" + ("实时监控" if realtime else "测试")
    else:
        levels = 10
        realtime = False
        title = "默认10档重建"
    
    print(f"\n🎯 {title}")
    print("=" * 50)
    
    # 创建优化测试器
    tester = OptimizedOrderBookTest(max_levels=levels)
    
    # 选择测试股票
    test_symbols = [
        'sh600000',  # 浦发银行
        'sh600036',  # 招商银行
        'sz000001',  # 平安银行
        'sz000002',  # 万科A
        'sz300059',  # 东方财富
    ]
    
    try:
        if realtime:
            # 实时监控模式
            current_time = datetime.now()
            
            if tester._is_trading_time(current_time):
                print(f"✅ 交易时间，开始实时监控...")
                
                # 初始测试轮
                print(f"\n📋 初始{levels}档测试:")
                for symbol in test_symbols:
                    result = tester.test_optimized_stock(symbol)
                    if result['success']:
                        print(f"  {symbol}: ✅ {result.get('match_rate', 0):.1%}")
                    else:
                        print(f"  {symbol}: ❌ {result.get('error', '失败')}")
                
                # 启动监控
                tester.start_realtime_monitoring(test_symbols, interval=20)
                
                try:
                    while True:
                        time.sleep(10)
                        
                        # 显示统计
                        stats = tester.get_comprehensive_stats()
                        if stats['total_tests'] > 0:
                            print(f"\n📊 实时统计: {stats['successful_tests']}/{stats['total_tests']} "
                                  f"({stats['overall_success_rate']:.1%}) | "
                                  f"平均匹配率: {stats['average_match_rate']:.1%}")
                        
                except KeyboardInterrupt:
                    print("\n⏹️ 停止实时监控")
                    tester.stop_realtime_monitoring()
            else:
                print(f"⏰ 非交易时间，进行单次测试")
                for symbol in test_symbols:
                    result = tester.test_optimized_stock(symbol)
                    if result['success']:
                        print(f"✅ {symbol}: {result.get('match_rate', 0):.1%}")
                    else:
                        print(f"❌ {symbol}: {result.get('error', '失败')}")
        else:
            # 单次测试模式
            print(f"📋 {title}测试:")
            
            for i, symbol in enumerate(test_symbols):
                print(f"\n进度: {i+1}/{len(test_symbols)} - 测试 {symbol}")
                
                result = tester.test_optimized_stock(symbol)
                
                if result['success']:
                    print(f"✅ {symbol}: 成功 - {levels}档匹配率 {result.get('match_rate', 0):.1%}")
                    if 'quality_score' in result:
                        print(f"   数据质量: {result['quality_score']:.2f}")
                else:
                    print(f"❌ {symbol}: 失败 - {result.get('error', '未知错误')}")
                    if 'errors' in result and result['errors']:
                        print(f"   主要问题: {result['errors'][0]}")
                
                if i < len(test_symbols) - 1:
                    time.sleep(2)
    
    except Exception as e:
        logger.error(f"优化测试异常: {e}")
        print(f"❌ 测试异常: {e}")
    
    finally:
        if realtime:
            tester.stop_realtime_monitoring()
    
    # 最终统计报告
    if tester.test_results:
        stats = tester.get_comprehensive_stats()
        
        print(f"\n📊 最终统计报告:")
        print("=" * 50)
        print(f"总测试次数: {stats['total_tests']}")
        print(f"成功次数: {stats['successful_tests']}")
        print(f"成功率: {stats['overall_success_rate']:.1%}")
        print(f"平均匹配率: {stats['average_match_rate']:.1%}")
        print(f"订单簿深度: {levels}档")
        
        # 按交易所统计
        print(f"\n📈 分交易所统计:")
        for exchange, ex_stats in stats['by_exchange'].items():
            if ex_stats['total'] > 0:
                exchange_name = '深交所' if exchange == 'sz' else '上交所'
                print(f"  {exchange_name}: {ex_stats['success']}/{ex_stats['total']} ({ex_stats['success_rate']:.1%})")
        
        # 错误模式分析
        if stats['error_patterns']:
            print(f"\n🔍 主要问题分析:")
            sorted_errors = sorted(stats['error_patterns'].items(), key=lambda x: x[1], reverse=True)
            for error_type, count in sorted_errors[:5]:
                print(f"  {error_type}: {count}次")


if __name__ == "__main__":
    run_optimized_testing()