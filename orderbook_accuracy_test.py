# -*- coding: utf-8 -*-
"""
5档订单簿正确性验证系统
专注于验证订单簿引擎对真实5档数据的处理准确性
去除扩展算法，直接使用真实数据进行测试
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

# 假设这些模块在你的项目中可用
from orderbook.core.axob import AXOB, AX_SIGNAL
from orderbook.messages.axsbe_order import axsbe_order
from orderbook.messages.axsbe_exe import axsbe_exe
from orderbook.messages.axsbe_snap_stock import axsbe_snap_stock
from orderbook.messages.axsbe_base import SecurityIDSource_SZSE, SecurityIDSource_SSE, INSTRUMENT_TYPE, TPM


class RealDataFetcher:
    """真实5档数据获取器 - 不进行扩展"""
    
    def __init__(self):
        self.logger = logging.getLogger("RealDataFetcher")
        self.session = requests.Session()
        self.session.headers.update({
            'Referer': 'http://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def get_real_level5_data(self, symbol: str) -> Dict:
        """获取真实5档数据，不进行任何扩展"""
        try:
            self.logger.debug(f"获取 {symbol} 的真实5档数据...")
            
            sina_data = self._get_sina_data(symbol)
            
            if sina_data:
                real_data = {
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
                
                # 获取真实5档数据，不进行扩展
                for i in range(1, 6):
                    bid_price = sina_data.get(f'bid{i}', 0)
                    bid_volume = sina_data.get(f'bid{i}_volume', 0)
                    ask_price = sina_data.get(f'ask{i}', 0)
                    ask_volume = sina_data.get(f'ask{i}_volume', 0)
                    
                    # 只添加有效的档位
                    if bid_price > 0 and bid_volume > 0:
                        real_data['bid_levels'].append({'price': bid_price, 'volume': bid_volume})
                    if ask_price > 0 and ask_volume > 0:
                        real_data['ask_levels'].append({'price': ask_price, 'volume': ask_volume})
                
                self.logger.info(f"获取真实数据: {len(real_data['bid_levels'])}买档, {len(real_data['ask_levels'])}卖档")
                return real_data
                
        except Exception as e:
            self.logger.error(f"获取真实数据失败: {e}")
            self.logger.debug(traceback.format_exc())
        
        return None
    
    def _get_sina_data(self, symbol: str) -> Dict:
        """从新浪获取原始数据"""
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


class OrderBookValidator:
    """5档订单簿验证器"""
    
    def __init__(self):
        self.logger = logging.getLogger("OrderBookValidator")
        self.data_fetcher = RealDataFetcher()
        self.test_results = []
        
        # 测试统计
        self.test_stats = {
            'total_tests': 0,
            'successful_tests': 0,
            'price_accuracy': 0.0,
            'volume_accuracy': 0.0,
            'by_exchange': {'sz': {'total': 0, 'success': 0}, 'sh': {'total': 0, 'success': 0}},
            'error_patterns': {}
        }
    
    def create_orderbook(self, symbol: str) -> AXOB:
        """创建标准订单簿"""
        try:
            self.logger.info(f"创建 {symbol} 的5档订单簿...")
            
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
            market_data = self.data_fetcher.get_real_level5_data(symbol)
            if market_data and market_data['pre_close'] > 0:
                self._initialize_orderbook_constants(ob, market_data, source)
                self.logger.info(f"订单簿初始化完成")
            else:
                self.logger.warning("使用默认参数初始化订单簿")
                self._initialize_default_constants(ob, source, security_id)
                
            return ob
            
        except Exception as e:
            self.logger.error(f"创建订单簿失败: {e}")
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
    
    def simulate_simple_orders(self, ob: AXOB, market_data: Dict):
        """模拟简单的订单流 - 直接按档位添加订单"""
        try:
            self.logger.info(f"模拟简单订单流: {len(market_data['bid_levels']) + len(market_data['ask_levels'])} 档")
            
            # 设置交易阶段
            current_time = datetime.now()
            if 9 <= current_time.hour < 15:
                ob.onMsg(AX_SIGNAL.AMTRADING_BGN)
            
            seq_num = 1
            timestamp = self._generate_timestamp(ob.SecurityIDSource)
            
            # 简单策略：直接按价格顺序添加订单，不进行复杂拆分
            all_orders = []
            
            # 买盘订单（从高价到低价）
            for bid_level in market_data['bid_levels']:
                if bid_level['price'] > 0 and bid_level['volume'] > 0:
                    all_orders.append({
                        'side': 'bid',
                        'price': bid_level['price'],
                        'volume': bid_level['volume'],
                        'priority': 1000 - bid_level['price']  # 价格越高优先级越高
                    })
            
            # 卖盘订单（从低价到高价）
            for ask_level in market_data['ask_levels']:
                if ask_level['price'] > 0 and ask_level['volume'] > 0:
                    all_orders.append({
                        'side': 'ask',
                        'price': ask_level['price'],
                        'volume': ask_level['volume'],
                        'priority': ask_level['price']  # 价格越低优先级越高
                    })
            
            # 按优先级排序
            all_orders.sort(key=lambda x: x['priority'])
            
            # 添加订单
            for order_info in all_orders:
                order = self._create_order(
                    ob, seq_num, order_info['side'], order_info['price'], 
                    order_info['volume'], timestamp
                )
                
                if order:
                    self.logger.debug(f"添加{order_info['side']}单: 价格={order.Price}, 数量={order.OrderQty}")
                    ob.onMsg(order)
                    seq_num += 1
                    time.sleep(0.001)  # 微小延迟
            
            self.logger.info(f"简单订单流模拟完成，共添加 {seq_num-1} 笔订单")
            
        except Exception as e:
            self.logger.error(f"模拟订单流失败: {e}")
            raise
    
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
    
    def print_orderbook_comparison(self, ob: AXOB, market_data: Dict, symbol: str):
        """打印订单簿与市场数据的对比"""
        print(f"\n{'='*80}")
        print(f"📖 5档订单簿验证 - {symbol}")
        print(f"{'='*80}")
        
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
        snapshot = ob.genTradingSnap(level_nb=5)
        if not snapshot:
            print("❌ 无法生成订单簿快照")
            return
        
        # 对比显示
        print(f"\n📊 5档数据对比:")
        print(f"{'档位':<4} {'市场卖价':<10} {'市场卖量':<12} {'订单簿卖价':<12} {'订单簿卖量':<14} {'价格匹配':<8} {'数量匹配':<8}")
        print("-" * 90)
        
        # 卖盘对比（倒序显示）
        for i in range(4, -1, -1):  # 卖5到卖1
            market_ask = market_data['ask_levels'][i] if i < len(market_data['ask_levels']) else {'price': 0, 'volume': 0}
            ob_ask_price = snapshot.ask[i].Price / price_divisor if snapshot.ask[i].Qty > 0 else 0
            ob_ask_qty = snapshot.ask[i].Qty / qty_divisor if snapshot.ask[i].Qty > 0 else 0
            
            market_price_str = f"{market_ask['price']:.2f}" if market_ask['price'] > 0 else "--"
            market_qty_str = f"{market_ask['volume']:,.0f}" if market_ask['volume'] > 0 else "--"
            ob_price_str = f"{ob_ask_price:.2f}" if ob_ask_price > 0 else "--"
            ob_qty_str = f"{ob_ask_qty:,.0f}" if ob_ask_qty > 0 else "--"
            
            # 匹配检查
            price_match = "✅" if abs(market_ask['price'] - ob_ask_price) <= 0.01 else "❌"
            qty_diff_pct = abs(market_ask['volume'] - ob_ask_qty) / max(market_ask['volume'], 1) if market_ask['volume'] > 0 else 1
            qty_match = "✅" if qty_diff_pct <= 0.05 else "❌"  # 5%容差
            
            print(f"卖{i+1:<2} {market_price_str:<10} {market_qty_str:<12} {ob_price_str:<12} {ob_qty_str:<14} {price_match:<8} {qty_match:<8}")
        
        print("-" * 90)
        
        # 买盘对比（正序显示）
        for i in range(5):  # 买1到买5
            market_bid = market_data['bid_levels'][i] if i < len(market_data['bid_levels']) else {'price': 0, 'volume': 0}
            ob_bid_price = snapshot.bid[i].Price / price_divisor if snapshot.bid[i].Qty > 0 else 0
            ob_bid_qty = snapshot.bid[i].Qty / qty_divisor if snapshot.bid[i].Qty > 0 else 0
            
            market_price_str = f"{market_bid['price']:.2f}" if market_bid['price'] > 0 else "--"
            market_qty_str = f"{market_bid['volume']:,.0f}" if market_bid['volume'] > 0 else "--"
            ob_price_str = f"{ob_bid_price:.2f}" if ob_bid_price > 0 else "--"
            ob_qty_str = f"{ob_bid_qty:,.0f}" if ob_bid_qty > 0 else "--"
            
            # 匹配检查
            price_match = "✅" if abs(market_bid['price'] - ob_bid_price) <= 0.01 else "❌"
            qty_diff_pct = abs(market_bid['volume'] - ob_bid_qty) / max(market_bid['volume'], 1) if market_bid['volume'] > 0 else 1
            qty_match = "✅" if qty_diff_pct <= 0.05 else "❌"  # 5%容差
            
            print(f"买{i+1:<2} {market_price_str:<10} {market_qty_str:<12} {ob_price_str:<12} {ob_qty_str:<14} {price_match:<8} {qty_match:<8}")
        
        print(f"{'='*80}")
    
    def validate_5level_orderbook(self, symbol: str) -> Dict:
        """验证5档订单簿的准确性"""
        self.logger.info(f"开始5档验证: {symbol}")
        
        try:
            # 更新测试统计
            self.test_stats['total_tests'] += 1
            exchange = 'sz' if symbol.startswith('sz') else 'sh'
            self.test_stats['by_exchange'][exchange]['total'] += 1
            
            # 获取真实5档数据
            market_data = self.data_fetcher.get_real_level5_data(symbol)
            if not market_data:
                return {'success': False, 'error': '无法获取市场数据', 'symbol': symbol}
            
            # 数据质量检查
            if len(market_data['bid_levels']) < 3 or len(market_data['ask_levels']) < 3:
                return {'success': False, 'error': '数据不完整', 'symbol': symbol}
            
            # 创建订单簿
            ob = self.create_orderbook(symbol)
            
            # 模拟简单订单
            self.simulate_simple_orders(ob, market_data)
            
            # 打印对比
            self.print_orderbook_comparison(ob, market_data, symbol)
            
            # 精确比较
            comparison = self._precise_compare_5levels(ob, market_data)
            
            # 更新统计
            if comparison['success']:
                self.test_stats['successful_tests'] += 1
                self.test_stats['by_exchange'][exchange]['success'] += 1
                self.test_stats['price_accuracy'] = (
                    (self.test_stats['price_accuracy'] * (self.test_stats['successful_tests'] - 1) + 
                     comparison['price_accuracy']) / self.test_stats['successful_tests']
                )
                self.test_stats['volume_accuracy'] = (
                    (self.test_stats['volume_accuracy'] * (self.test_stats['successful_tests'] - 1) + 
                     comparison['volume_accuracy']) / self.test_stats['successful_tests']
                )
            
            return comparison
            
        except Exception as e:
            self.logger.error(f"5档验证 {symbol} 失败: {e}")
            return {'success': False, 'error': str(e), 'symbol': symbol}
    
    def _precise_compare_5levels(self, ob: AXOB, market_data: Dict) -> Dict:
        """精确比较5档数据"""
        try:
            snapshot = ob.genTradingSnap(level_nb=5)
            if not snapshot:
                return {'success': False, 'error': '无法生成快照'}
            
            # 精度设置
            if ob.SecurityIDSource == SecurityIDSource_SZSE:
                price_divisor = 10000
                qty_divisor = 100
                price_tolerance = 0.01
                volume_tolerance_pct = 0.05  # 5%容差
            else:
                price_divisor = 1000
                qty_divisor = 1000
                price_tolerance = 0.01
                volume_tolerance_pct = 0.05
            
            comparison = {
                'success': True,
                'symbol': market_data['symbol'],
                'timestamp': market_data['timestamp'],
                'price_matches': 0,
                'volume_matches': 0,
                'total_comparisons': 0,
                'errors': [],
                'price_accuracy': 0.0,
                'volume_accuracy': 0.0
            }
            
            total_price_checks = 0
            total_volume_checks = 0
            
            # 比较买盘
            for i, market_bid in enumerate(market_data['bid_levels'][:5]):
                if market_bid['price'] <= 0 or market_bid['volume'] <= 0:
                    continue
                
                total_price_checks += 1
                total_volume_checks += 1
                
                if i < len(snapshot.bid) and snapshot.bid[i].Qty > 0:
                    ob_price = snapshot.bid[i].Price / price_divisor
                    ob_volume = snapshot.bid[i].Qty / qty_divisor
                    
                    # 价格比较
                    price_diff = abs(ob_price - market_bid['price'])
                    if price_diff <= price_tolerance:
                        comparison['price_matches'] += 1
                    else:
                        comparison['errors'].append(f"买{i+1}价格偏差: 市场={market_bid['price']:.2f}, 订单簿={ob_price:.2f}")
                    
                    # 数量比较
                    volume_diff_pct = abs(ob_volume - market_bid['volume']) / max(market_bid['volume'], 1)
                    if volume_diff_pct <= volume_tolerance_pct:
                        comparison['volume_matches'] += 1
                    else:
                        comparison['errors'].append(f"买{i+1}数量偏差: 市场={market_bid['volume']:,.0f}, 订单簿={ob_volume:,.0f} ({volume_diff_pct:.1%})")
                else:
                    comparison['errors'].append(f"买{i+1}档位缺失")
            
            # 比较卖盘
            for i, market_ask in enumerate(market_data['ask_levels'][:5]):
                if market_ask['price'] <= 0 or market_ask['volume'] <= 0:
                    continue
                
                total_price_checks += 1
                total_volume_checks += 1
                
                if i < len(snapshot.ask) and snapshot.ask[i].Qty > 0:
                    ob_price = snapshot.ask[i].Price / price_divisor
                    ob_volume = snapshot.ask[i].Qty / qty_divisor
                    
                    # 价格比较
                    price_diff = abs(ob_price - market_ask['price'])
                    if price_diff <= price_tolerance:
                        comparison['price_matches'] += 1
                    else:
                        comparison['errors'].append(f"卖{i+1}价格偏差: 市场={market_ask['price']:.2f}, 订单簿={ob_price:.2f}")
                    
                    # 数量比较
                    volume_diff_pct = abs(ob_volume - market_ask['volume']) / max(market_ask['volume'], 1)
                    if volume_diff_pct <= volume_tolerance_pct:
                        comparison['volume_matches'] += 1
                    else:
                        comparison['errors'].append(f"卖{i+1}数量偏差: 市场={market_ask['volume']:,.0f}, 订单簿={ob_volume:,.0f} ({volume_diff_pct:.1%})")
                else:
                    comparison['errors'].append(f"卖{i+1}档位缺失")
            
            # 计算准确率
            comparison['price_accuracy'] = comparison['price_matches'] / total_price_checks if total_price_checks > 0 else 0
            comparison['volume_accuracy'] = comparison['volume_matches'] / total_volume_checks if total_volume_checks > 0 else 0
            
            # 成功标准：价格100%准确，数量95%准确
            comparison['success'] = (comparison['price_accuracy'] >= 0.99 and 
                                   comparison['volume_accuracy'] >= 0.95)
            
            self.logger.info(f"5档比较完成: 价格准确率={comparison['price_accuracy']:.1%}, 数量准确率={comparison['volume_accuracy']:.1%}")
            
            return comparison
            
        except Exception as e:
            self.logger.error(f"5档比较失败: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
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


def run_5level_validation():
    """运行5档验证系统"""
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                f'5level_validation_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
                encoding='utf-8'
            )
        ]
    )
    
    logger = logging.getLogger("5LevelValidation")
    
    print("🎯 5档订单簿正确性验证系统")
    print("=" * 60)
    print("📝 测试说明:")
    print("   - 直接使用真实5档数据，不进行扩展")
    print("   - 验证订单簿引擎的基础功能正确性")
    print("   - 价格要求100%匹配，数量允许5%误差")
    print("=" * 60)
    
    # 创建验证器
    validator = OrderBookValidator()
    
    # 选择测试股票
    test_symbols = [
        'sh600000',  # 浦发银行
        'sh600036',  # 招商银行
        'sz000001',  # 平安银行
        'sz000002',  # 万科A
        'sz300059',  # 东方财富
    ]
    
    print(f"\n📋 开始5档验证测试:")
    print(f"   测试股票: {len(test_symbols)} 只")
    print(f"   测试模式: 真实数据验证")
    
    try:
        for i, symbol in enumerate(test_symbols):
            print(f"\n{'='*60}")
            print(f"进度: {i+1}/{len(test_symbols)} - 验证 {symbol}")
            print(f"{'='*60}")
            
            result = validator.validate_5level_orderbook(symbol)
            
            if result['success']:
                print(f"\n✅ {symbol}: 验证通过")
                print(f"   价格准确率: {result.get('price_accuracy', 0):.1%}")
                print(f"   数量准确率: {result.get('volume_accuracy', 0):.1%}")
            else:
                print(f"\n❌ {symbol}: 验证失败")
                print(f"   失败原因: {result.get('error', '未知错误')}")
                if 'errors' in result and result['errors']:
                    print(f"   详细问题:")
                    for error in result['errors'][:3]:  # 只显示前3个错误
                        print(f"     - {error}")
                    if len(result['errors']) > 3:
                        print(f"     - ... 还有 {len(result['errors'])-3} 个问题")
            
            if i < len(test_symbols) - 1:
                print(f"\n⏳ 等待2秒后继续...")
                time.sleep(2)
    
    except Exception as e:
        logger.error(f"验证过程异常: {e}")
        print(f"❌ 验证异常: {e}")
    
    # 最终统计报告
    stats = validator.get_stats()
    
    print(f"\n{'='*60}")
    print(f"📊 5档验证统计报告")
    print(f"{'='*60}")
    print(f"总验证次数: {stats['total_tests']}")
    print(f"通过次数: {stats['successful_tests']}")
    print(f"通过率: {stats.get('overall_success_rate', 0):.1%}")
    
    if stats['successful_tests'] > 0:
        print(f"平均价格准确率: {stats['price_accuracy']:.1%}")
        print(f"平均数量准确率: {stats['volume_accuracy']:.1%}")
    
    # 按交易所统计
    print(f"\n📈 分交易所统计:")
    for exchange, ex_stats in stats['by_exchange'].items():
        if ex_stats['total'] > 0:
            exchange_name = '深交所' if exchange == 'sz' else '上交所'
            print(f"  {exchange_name}: {ex_stats['success']}/{ex_stats['total']} ({ex_stats.get('success_rate', 0):.1%})")
    
    # 结论和建议
    print(f"\n💡 测试结论:")
    if stats.get('overall_success_rate', 0) >= 0.8:
        print("  ✅ 订单簿引擎5档功能基本正确")
        print("  💡 建议: 可以进一步测试更复杂的订单场景")
    elif stats.get('overall_success_rate', 0) >= 0.5:
        print("  ⚠️  订单簿引擎存在一些问题")
        print("  💡 建议: 检查订单处理和价格计算逻辑")
    else:
        print("  ❌ 订单簿引擎存在严重问题")
        print("  💡 建议: 全面检查引擎实现")
    
    print(f"\n📝 测试说明:")
    print("  - 本测试使用真实5档数据，验证订单簿基础功能")
    print("  - 价格要求精确匹配（±0.01容差）")
    print("  - 数量允许5%误差（考虑订单拆分等因素）")
    print("  - 测试结果反映订单簿引擎的基本正确性")


if __name__ == "__main__":
    run_5level_validation()