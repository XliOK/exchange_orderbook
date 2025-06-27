# -*- coding: utf-8 -*-
"""
修复的订单簿准确性测试
主要修复：
1. 错误处理和日志输出
2. 订单簿初始化问题
3. 市场数据获取和解析
4. 比较逻辑的完善
"""

import time
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import logging
import traceback

# 假设这些模块在你的项目中可用
from orderbook.core.axob import AXOB, AX_SIGNAL
from orderbook.messages.axsbe_order import axsbe_order
from orderbook.messages.axsbe_exe import axsbe_exe
from orderbook.messages.axsbe_snap_stock import axsbe_snap_stock
from orderbook.messages.axsbe_base import SecurityIDSource_SZSE, SecurityIDSource_SSE, INSTRUMENT_TYPE, TPM

class MarketDataFetcher:
    """市场数据获取器 - 修复版"""
    
    def __init__(self):
        self.logger = logging.getLogger("MarketDataFetcher")
        
    def get_realtime_quote_sina(self, symbol: str) -> Dict:
        """从新浪财经获取实时行情 - 增强错误处理"""
        url = f"http://hq.sinajs.cn/list={symbol}"
        headers = {
            'Referer': 'http://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        try:
            self.logger.debug(f"正在获取 {symbol} 的新浪行情数据...")
            response = requests.get(url, headers=headers, timeout=10)
            response.encoding = 'gbk'
            
            if response.status_code == 200:
                data = response.text.strip()
                self.logger.debug(f"新浪返回数据: {data[:100]}...")
                
                if data and 'var hq_str_' in data:
                    # 解析数据
                    content = data.split('="')[1].split('";')[0]
                    fields = content.split(',')
                    
                    self.logger.debug(f"解析到 {len(fields)} 个字段")
                    
                    if len(fields) >= 32:
                        try:
                            result = {
                                'name': fields[0],
                                'open': float(fields[1]) if fields[1] else 0.0,
                                'pre_close': float(fields[2]) if fields[2] else 0.0,
                                'current': float(fields[3]) if fields[3] else 0.0,
                                'high': float(fields[4]) if fields[4] else 0.0,
                                'low': float(fields[5]) if fields[5] else 0.0,
                                'bid': float(fields[6]) if fields[6] else 0.0,
                                'ask': float(fields[7]) if fields[7] else 0.0,
                                'volume': int(float(fields[8])) if fields[8] else 0,
                                'amount': float(fields[9]) if fields[9] else 0.0,
                                # 五档买卖盘
                                'bid1_volume': int(float(fields[10])) if fields[10] else 0,
                                'bid1': float(fields[11]) if fields[11] else 0.0,
                                'bid2_volume': int(float(fields[12])) if fields[12] else 0,
                                'bid2': float(fields[13]) if fields[13] else 0.0,
                                'bid3_volume': int(float(fields[14])) if fields[14] else 0,
                                'bid3': float(fields[15]) if fields[15] else 0.0,
                                'bid4_volume': int(float(fields[16])) if fields[16] else 0,
                                'bid4': float(fields[17]) if fields[17] else 0.0,
                                'bid5_volume': int(float(fields[18])) if fields[18] else 0,
                                'bid5': float(fields[19]) if fields[19] else 0.0,
                                'ask1_volume': int(float(fields[20])) if fields[20] else 0,
                                'ask1': float(fields[21]) if fields[21] else 0.0,
                                'ask2_volume': int(float(fields[22])) if fields[22] else 0,
                                'ask2': float(fields[23]) if fields[23] else 0.0,
                                'ask3_volume': int(float(fields[24])) if fields[24] else 0,
                                'ask3': float(fields[25]) if fields[25] else 0.0,
                                'ask4_volume': int(float(fields[26])) if fields[26] else 0,
                                'ask4': float(fields[27]) if fields[27] else 0.0,
                                'ask5_volume': int(float(fields[28])) if fields[28] else 0,
                                'ask5': float(fields[29]) if fields[29] else 0.0,
                                'date': fields[30] if len(fields) > 30 else '',
                                'time': fields[31] if len(fields) > 31 else '',
                            }
                            
                            self.logger.info(f"成功获取 {symbol} 行情: 现价={result['current']}, 成交量={result['volume']}")
                            return result
                            
                        except (ValueError, IndexError) as e:
                            self.logger.error(f"解析新浪行情数据失败: {e}")
                            self.logger.debug(f"原始字段: {fields}")
                    else:
                        self.logger.warning(f"新浪返回字段数不足: {len(fields)}")
                else:
                    self.logger.warning(f"新浪返回数据格式不正确: {data}")
            else:
                self.logger.error(f"新浪API请求失败，状态码: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            self.logger.error(f"获取新浪行情网络错误: {e}")
        except Exception as e:
            self.logger.error(f"获取新浪行情未知错误: {e}")
            self.logger.debug(traceback.format_exc())
        
        return None
    
    def get_level2_snapshot_simulation(self, symbol: str) -> Dict:
        """模拟Level2快照数据 - 增强版"""
        self.logger.info(f"正在获取 {symbol} 的Level2快照数据...")
        
        # 尝试新浪数据源
        sina_data = self.get_realtime_quote_sina(symbol)
        
        if sina_data and sina_data['current'] > 0:  # 确保有有效数据
            # 构造快照格式
            snapshot = {
                'symbol': symbol,
                'timestamp': f"{sina_data['date']} {sina_data['time']}" if sina_data['date'] else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'pre_close': sina_data['pre_close'],
                'open': sina_data['open'],
                'high': sina_data['high'],
                'low': sina_data['low'],
                'last': sina_data['current'],
                'volume': sina_data['volume'],
                'amount': sina_data['amount'],
                'bid_levels': [],
                'ask_levels': []
            }
            
            # 构建买卖盘数据
            for i in range(1, 6):
                bid_price = sina_data.get(f'bid{i}', 0)
                bid_volume = sina_data.get(f'bid{i}_volume', 0)
                ask_price = sina_data.get(f'ask{i}', 0)
                ask_volume = sina_data.get(f'ask{i}_volume', 0)
                
                if bid_price > 0 and bid_volume > 0:
                    snapshot['bid_levels'].append({
                        'price': bid_price,
                        'volume': bid_volume
                    })
                    
                if ask_price > 0 and ask_volume > 0:
                    snapshot['ask_levels'].append({
                        'price': ask_price,
                        'volume': ask_volume
                    })
            
            self.logger.info(f"成功构造快照: {len(snapshot['bid_levels'])}买档, {len(snapshot['ask_levels'])}卖档")
            return snapshot
        else:
            self.logger.error(f"无法获取 {symbol} 的有效市场数据")
            return None


class OrderBookAccuracyTest:
    """订单簿准确性测试 - 修复版"""
    
    def __init__(self):
        self.logger = logging.getLogger("OrderBookAccuracyTest")
        self.data_fetcher = MarketDataFetcher()
        self.test_results = []
        
    def create_orderbook(self, symbol: str) -> AXOB:
        """创建订单簿 - 增强错误处理"""
        try:
            self.logger.info(f"正在为 {symbol} 创建订单簿...")
            
            # 判断市场
            if symbol.startswith('sh'):
                security_id = int(symbol[2:])
                source = SecurityIDSource_SSE
                self.logger.debug(f"识别为上交所股票: {security_id}")
            else:  # sz
                security_id = int(symbol[2:])
                source = SecurityIDSource_SZSE
                self.logger.debug(f"识别为深交所股票: {security_id}")
                
            # 创建订单簿实例
            ob = AXOB(security_id, source, INSTRUMENT_TYPE.STOCK)
            self.logger.debug("订单簿实例创建成功")
            
            # 获取市场数据并初始化常量
            market_data = self.data_fetcher.get_realtime_quote_sina(symbol)
            if market_data and market_data['pre_close'] > 0:
                self.logger.info(f"使用实时市场数据初始化订单簿: 昨收={market_data['pre_close']}")
                
                ob.constantValue_ready = True
                
                # 根据交易所类型设置价格精度
                if source == SecurityIDSource_SZSE:
                    # 深交所：内部使用2位小数精度
                    ob.PrevClosePx = int(market_data['pre_close'] * 100)
                    
                    # 设置涨跌停价格 - 修正快照价格精度
                    if str(security_id).startswith('300'):
                        # 创业板 20%
                        up_limit_raw = market_data['pre_close'] * 1.2
                        dn_limit_raw = market_data['pre_close'] * 0.8
                    else:
                        # 主板/中小板 10%
                        up_limit_raw = market_data['pre_close'] * 1.1
                        dn_limit_raw = market_data['pre_close'] * 0.9
                    
                    # 深交所快照价格使用4位小数精度（不是6位）
                    ob.UpLimitPx = int(up_limit_raw * 10000)  # 快照格式：4位小数
                    ob.DnLimitPx = int(dn_limit_raw * 10000)
                    ob.UpLimitPrice = int(up_limit_raw * 100)  # 内部：2位小数
                    ob.DnLimitPrice = int(dn_limit_raw * 100)
                    
                else:
                    # 上交所：3位小数精度
                    ob.PrevClosePx = int(market_data['pre_close'] * 1000)
                    
                    # 设置涨跌停价格
                    if str(security_id).startswith('688'):
                        # 科创板 20%
                        up_limit_raw = market_data['pre_close'] * 1.2
                        dn_limit_raw = market_data['pre_close'] * 0.8
                    else:
                        # 主板 10%
                        up_limit_raw = market_data['pre_close'] * 1.1
                        dn_limit_raw = market_data['pre_close'] * 0.9
                    
                    ob.UpLimitPx = int(up_limit_raw * 1000)
                    ob.DnLimitPx = int(dn_limit_raw * 1000)
                    ob.UpLimitPrice = ob.UpLimitPx
                    ob.DnLimitPrice = ob.DnLimitPx
                
                # 设置日期和渠道号
                ob.YYMMDD = int(datetime.now().strftime('%Y%m%d'))
                ob.ChannelNo = 2000 if source == SecurityIDSource_SZSE else 6
                
                self.logger.info(f"订单簿初始化完成: 昨收={ob.PrevClosePx}, 涨停={ob.UpLimitPrice}, 跌停={ob.DnLimitPrice}")
                
            else:
                self.logger.warning(f"无法获取 {symbol} 的实时数据，使用默认参数")
                # 使用默认参数
                ob.constantValue_ready = True
                ob.PrevClosePx = 1000  # 默认10.00元
                ob.UpLimitPx = 1100 if source == SecurityIDSource_SZSE else 11000
                ob.DnLimitPx = 900 if source == SecurityIDSource_SZSE else 9000
                ob.UpLimitPrice = 1100 if source == SecurityIDSource_SZSE else 11000
                ob.DnLimitPrice = 900 if source == SecurityIDSource_SZSE else 9000
                ob.YYMMDD = int(datetime.now().strftime('%Y%m%d'))
                ob.ChannelNo = 2000 if source == SecurityIDSource_SZSE else 6
                
            return ob
            
        except Exception as e:
            self.logger.error(f"创建订单簿失败: {e}")
            self.logger.debug(traceback.format_exc())
            raise
    
    def simulate_orders_from_snapshot(self, ob: AXOB, snapshot: Dict):
        """从快照数据模拟订单 - 修复版"""
        try:
            self.logger.info(f"正在为 {snapshot['symbol']} 模拟订单...")
            
            # 设置交易阶段
            current_time = datetime.now()
            if 9 <= current_time.hour < 15:  # 交易时间内
                ob.onMsg(AX_SIGNAL.AMTRADING_BGN)
                self.logger.debug("设置为上午连续竞价阶段")
            
            seq_num = 1
            
            # 生成时间戳
            if ob.SecurityIDSource == SecurityIDSource_SZSE:
                timestamp = int(current_time.strftime('%Y%m%d%H%M%S')) * 1000 + current_time.microsecond // 1000
            else:
                timestamp = int(current_time.strftime('%H%M%S')) * 100 + (current_time.microsecond // 10000)
            
            # 模拟买单
            for i, bid_level in enumerate(snapshot['bid_levels']):
                if bid_level['price'] <= 0 or bid_level['volume'] <= 0:
                    continue
                    
                order = axsbe_order(ob.SecurityIDSource)
                order.SecurityID = ob.SecurityID
                order.ApplSeqNum = seq_num
                
                # 设置价格和数量
                if ob.SecurityIDSource == SecurityIDSource_SZSE:
                    price_raw = int(bid_level['price'] * 10000)
                    order.Price = (price_raw // 100) * 100  # 确保是100的倍数
                    order.OrderQty = int(bid_level['volume'] * 100)
                    order.Side = ord('1')  # 买入
                    order.OrdType = ord('2')  # 限价
                else:
                    order.Price = int(bid_level['price'] * 1000)
                    order.OrderQty = int(bid_level['volume'] * 1000)
                    order.Side = ord('B')  # 买入
                    order.OrdType = ord('A')  # 新增
                
                order.TransactTime = timestamp
                
                self.logger.debug(f"添加买单 {i+1}: 价格={order.Price}, 数量={order.OrderQty}")
                ob.onMsg(order)
                seq_num += 1
            
            # 模拟卖单
            for i, ask_level in enumerate(snapshot['ask_levels']):
                if ask_level['price'] <= 0 or ask_level['volume'] <= 0:
                    continue
                    
                order = axsbe_order(ob.SecurityIDSource)
                order.SecurityID = ob.SecurityID
                order.ApplSeqNum = seq_num
                
                # 设置价格和数量
                if ob.SecurityIDSource == SecurityIDSource_SZSE:
                    price_raw = int(ask_level['price'] * 10000)
                    order.Price = (price_raw // 100) * 100
                    order.OrderQty = int(ask_level['volume'] * 100)
                    order.Side = ord('2')  # 卖出
                    order.OrdType = ord('2')  # 限价
                else:
                    order.Price = int(ask_level['price'] * 1000)
                    order.OrderQty = int(ask_level['volume'] * 1000)
                    order.Side = ord('S')  # 卖出
                    order.OrdType = ord('A')  # 新增
                
                order.TransactTime = timestamp
                
                self.logger.debug(f"添加卖单 {i+1}: 价格={order.Price}, 数量={order.OrderQty}")
                ob.onMsg(order)
                seq_num += 1
            
            self.logger.info(f"订单模拟完成，共添加 {seq_num-1} 笔订单")
            
        except Exception as e:
            self.logger.error(f"模拟订单失败: {e}")
            self.logger.debug(traceback.format_exc())
            raise
    
    def print_orderbook_details(self, ob: AXOB, symbol: str):
        """打印订单簿详细信息"""
        print(f"\n{'='*60}")
        print(f"📖 订单簿详情 - {symbol}")
        print(f"{'='*60}")
        
        # 基本信息
        print(f"交易所: {'深交所' if ob.SecurityIDSource == SecurityIDSource_SZSE else '上交所'}")
        print(f"证券代码: {ob.SecurityID}")
        print(f"昨收价: {ob.PrevClosePx / (100 if ob.SecurityIDSource == SecurityIDSource_SZSE else 1000):.2f}")
        print(f"涨停价: {ob.UpLimitPrice / (100 if ob.SecurityIDSource == SecurityIDSource_SZSE else 1000):.2f}")
        print(f"跌停价: {ob.DnLimitPrice / (100 if ob.SecurityIDSource == SecurityIDSource_SZSE else 1000):.2f}")
        
        # 生成快照
        snapshot = ob.genTradingSnap()
        if not snapshot:
            print("❌ 无法生成订单簿快照")
            return
            
        # 打印买卖盘
        print(f"\n📊 订单簿五档行情:")
        print(f"{'档位':<4} {'卖量':<12} {'卖价':<8} {'  ':<4} {'买价':<8} {'买量':<12}")
        print("-" * 60)
        
        # 确定精度转换
        if ob.SecurityIDSource == SecurityIDSource_SZSE:
            price_divisor = 10000  # 深交所4位小数
            qty_divisor = 100      # 深交所2位小数
        else:
            price_divisor = 1000   # 上交所3位小数
            qty_divisor = 1000     # 上交所3位小数
        
        # 从卖5到卖1倒序打印
        for i in range(4, -1, -1):
            ask_price = snapshot.ask[i].Price / price_divisor if snapshot.ask[i].Qty > 0 else 0
            ask_qty = snapshot.ask[i].Qty / qty_divisor if snapshot.ask[i].Qty > 0 else 0
            
            ask_price_str = f"{ask_price:.2f}" if ask_price > 0 else "--"
            ask_qty_str = f"{ask_qty:,.0f}" if ask_qty > 0 else "--"
            
            print(f"卖{i+1:<2} {ask_qty_str:<12} {ask_price_str:<8}")
        
        print("-" * 60)
        
        # 从买1到买5正序打印
        for i in range(5):
            bid_price = snapshot.bid[i].Price / price_divisor if snapshot.bid[i].Qty > 0 else 0
            bid_qty = snapshot.bid[i].Qty / qty_divisor if snapshot.bid[i].Qty > 0 else 0
            
            bid_price_str = f"{bid_price:.2f}" if bid_price > 0 else "--"
            bid_qty_str = f"{bid_qty:,.0f}" if bid_qty > 0 else "--"
            
            print(f"买{i+1:<2} {'--':<12} {'--':<8} {'  ':<4} {bid_price_str:<8} {bid_qty_str:<12}")
        
        # 统计信息
        print(f"\n📈 统计信息:")
        print(f"总成交笔数: {snapshot.NumTrades}")
        print(f"总成交量: {snapshot.TotalVolumeTrade:,}")
        print(f"总成交额: {snapshot.TotalValueTrade:,}")
        
        if snapshot.LastPx > 0:
            last_price = snapshot.LastPx / price_divisor
            print(f"最新价: {last_price:.2f}")
        
        if snapshot.OpenPx > 0:
            open_price = snapshot.OpenPx / price_divisor
            print(f"开盘价: {open_price:.2f}")
            
        if snapshot.HighPx > 0:
            high_price = snapshot.HighPx / price_divisor
            print(f"最高价: {high_price:.2f}")
            
        if snapshot.LowPx > 0:
            low_price = snapshot.LowPx / price_divisor
            print(f"最低价: {low_price:.2f}")
        
        # 加权信息
        if snapshot.BidWeightSize > 0:
            bid_avg_price = snapshot.BidWeightPx / price_divisor
            bid_total_qty = snapshot.BidWeightSize / qty_divisor
            print(f"买方加权价: {bid_avg_price:.3f} (总量: {bid_total_qty:,.0f})")
            
        if snapshot.AskWeightSize > 0:
            ask_avg_price = snapshot.AskWeightPx / price_divisor  
            ask_total_qty = snapshot.AskWeightSize / qty_divisor
            print(f"卖方加权价: {ask_avg_price:.3f} (总量: {ask_total_qty:,.0f})")
        
        print(f"{'='*60}")

    def compare_orderbook_with_market(self, ob: AXOB, market_snapshot: Dict) -> Dict:
        """比较订单簿与市场数据 - 修复版"""
        try:
            self.logger.info(f"正在比较 {market_snapshot['symbol']} 的订单簿与市场数据...")
            
            # 生成订单簿快照
            ob_snapshot = ob.genTradingSnap()
            
            if not ob_snapshot:
                return {
                    'success': False, 
                    'error': '无法生成订单簿快照',
                    'symbol': market_snapshot['symbol']
                }
            
            # 比较结果
            comparison = {
                'success': True,
                'symbol': market_snapshot['symbol'],
                'timestamp': market_snapshot['timestamp'],
                'price_match': {},
                'volume_match': {},
                'errors': [],
                'match_rate': 0.0,
                'total_errors': 0
            }
            
            # 比较买盘
            self.logger.debug(f"比较买盘: 市场有{len(market_snapshot['bid_levels'])}档")
            for i, market_bid in enumerate(market_snapshot['bid_levels'][:5]):
                level_key = f'bid{i+1}'
                
                if i < len(ob_snapshot.bid) and ob_snapshot.bid[i].Qty > 0:
                    # 修复精度转换问题
                    if ob.SecurityIDSource == SecurityIDSource_SZSE:
                        # 深交所：快照价格实际是4位小数格式，不是6位
                        ob_price = ob_snapshot.bid[i].Price / 10000  # 修正：4位小数
                        ob_volume = ob_snapshot.bid[i].Qty / 100  # 2位小数
                    else:
                        ob_price = ob_snapshot.bid[i].Price / 1000  # 3位小数
                        ob_volume = ob_snapshot.bid[i].Qty / 1000  # 3位小数
                    
                    price_diff = abs(ob_price - market_bid['price'])
                    volume_diff = abs(ob_volume - market_bid['volume'])
                    
                    comparison['price_match'][level_key] = {
                        'market': market_bid['price'],
                        'orderbook': ob_price,
                        'diff': price_diff,
                        'match': price_diff < 0.01
                    }
                    
                    comparison['volume_match'][level_key] = {
                        'market': market_bid['volume'],
                        'orderbook': ob_volume,
                        'diff': volume_diff,
                        'match': volume_diff < 100
                    }
                    
                    if not comparison['price_match'][level_key]['match']:
                        comparison['errors'].append(f"买{i+1}价格不匹配: 市场={market_bid['price']:.2f}, 订单簿={ob_price:.2f}")
                    if not comparison['volume_match'][level_key]['match']:
                        comparison['errors'].append(f"买{i+1}数量不匹配: 市场={market_bid['volume']}, 订单簿={ob_volume}")
                        
                else:
                    comparison['price_match'][level_key] = {
                        'market': market_bid['price'],
                        'orderbook': 0.0,
                        'diff': market_bid['price'],
                        'match': False
                    }
                    comparison['volume_match'][level_key] = {
                        'market': market_bid['volume'],
                        'orderbook': 0,
                        'diff': market_bid['volume'],
                        'match': False
                    }
                    comparison['errors'].append(f"买{i+1}档位缺失")
            
            # 比较卖盘
            self.logger.debug(f"比较卖盘: 市场有{len(market_snapshot['ask_levels'])}档")
            for i, market_ask in enumerate(market_snapshot['ask_levels'][:5]):
                level_key = f'ask{i+1}'
                
                if i < len(ob_snapshot.ask) and ob_snapshot.ask[i].Qty > 0:
                    # 修复精度转换问题
                    if ob.SecurityIDSource == SecurityIDSource_SZSE:
                        # 深交所：快照价格实际是4位小数格式，不是6位
                        ob_price = ob_snapshot.ask[i].Price / 10000  # 修正：4位小数
                        ob_volume = ob_snapshot.ask[i].Qty / 100  # 2位小数
                    else:
                        ob_price = ob_snapshot.ask[i].Price / 1000  # 3位小数
                        ob_volume = ob_snapshot.ask[i].Qty / 1000  # 3位小数
                    
                    price_diff = abs(ob_price - market_ask['price'])
                    volume_diff = abs(ob_volume - market_ask['volume'])
                    
                    comparison['price_match'][level_key] = {
                        'market': market_ask['price'],
                        'orderbook': ob_price,
                        'diff': price_diff,
                        'match': price_diff < 0.01
                    }
                    
                    comparison['volume_match'][level_key] = {
                        'market': market_ask['volume'],
                        'orderbook': ob_volume,
                        'diff': volume_diff,
                        'match': volume_diff < 100
                    }
                    
                    if not comparison['price_match'][level_key]['match']:
                        comparison['errors'].append(f"卖{i+1}价格不匹配: 市场={market_ask['price']:.2f}, 订单簿={ob_price:.2f}")
                    if not comparison['volume_match'][level_key]['match']:
                        comparison['errors'].append(f"卖{i+1}数量不匹配: 市场={market_ask['volume']}, 订单簿={ob_volume}")
                        
                else:
                    comparison['price_match'][level_key] = {
                        'market': market_ask['price'],
                        'orderbook': 0.0,
                        'diff': market_ask['price'],
                        'match': False
                    }
                    comparison['volume_match'][level_key] = {
                        'market': market_ask['volume'],
                        'orderbook': 0,
                        'diff': market_ask['volume'],
                        'match': False
                    }
                    comparison['errors'].append(f"卖{i+1}档位缺失")
            
            # 计算成功率
            total_comparisons = len(comparison['price_match']) + len(comparison['volume_match'])
            if total_comparisons > 0:
                matched_count = sum(1 for v in comparison['price_match'].values() if v['match'])
                matched_count += sum(1 for v in comparison['volume_match'].values() if v['match'])
                comparison['match_rate'] = matched_count / total_comparisons
            
            comparison['total_errors'] = len(comparison['errors'])
            comparison['success'] = comparison['total_errors'] == 0
            
            self.logger.info(f"比较完成: 成功率={comparison['match_rate']:.2%}, 错误数={comparison['total_errors']}")
            
            return comparison
            
        except Exception as e:
            self.logger.error(f"比较订单簿失败: {e}")
            self.logger.debug(traceback.format_exc())
            return {
                'success': False,
                'error': f'比较过程出错: {str(e)}',
                'symbol': market_snapshot.get('symbol', 'Unknown')
            }
    
    def test_single_stock(self, symbol: str) -> Dict:
        """测试单只股票 - 增强版"""
        self.logger.info(f"开始测试股票: {symbol}")
        
        try:
            # 获取市场数据
            market_snapshot = self.data_fetcher.get_level2_snapshot_simulation(symbol)
            if not market_snapshot:
                return {
                    'success': False, 
                    'error': '无法获取市场数据',
                    'symbol': symbol
                }
            
            # 验证市场数据
            if not market_snapshot['bid_levels'] and not market_snapshot['ask_levels']:
                return {
                    'success': False,
                    'error': '市场数据中无有效的买卖盘',
                    'symbol': symbol
                }
            
            # 创建订单簿
            ob = self.create_orderbook(symbol)
            
            # 模拟订单
            self.simulate_orders_from_snapshot(ob, market_snapshot)
            
            # 打印订单簿详情
            self.print_orderbook_details(ob, symbol)
            
            # 比较结果
            comparison = self.compare_orderbook_with_market(ob, market_snapshot)
            
            # 记录结果
            self.test_results.append(comparison)
            
            return comparison
            
        except Exception as e:
            self.logger.error(f"测试 {symbol} 时发生错误: {e}")
            self.logger.debug(traceback.format_exc())
            error_result = {
                'success': False,
                'error': f'测试过程出错: {str(e)}',
                'symbol': symbol
            }
            self.test_results.append(error_result)
            return error_result
    
    def test_multiple_stocks(self, symbols: List[str], interval: int = 3):
        """测试多只股票 - 增强版"""
        self.logger.info(f"开始批量测试 {len(symbols)} 只股票...")
        
        for i, symbol in enumerate(symbols):
            try:
                self.logger.info(f"进度: {i+1}/{len(symbols)} - 测试 {symbol}")
                
                result = self.test_single_stock(symbol)
                
                if result['success']:
                    self.logger.info(f"[OK] {symbol} 测试通过，匹配率: {result.get('match_rate', 0):.2%}")
                else:
                    self.logger.warning(f"[FAIL] {symbol} 测试失败: {result.get('error', '未知错误')}")
                    if 'errors' in result and result['errors']:
                        for error in result['errors'][:3]:  # 只显示前3个错误
                            self.logger.warning(f"  - {error}")
                        if len(result['errors']) > 3:
                            self.logger.warning(f"  - ... 还有 {len(result['errors'])-3} 个错误")
                
                # 输出价格对比摘要
                if 'price_match' in result and result['price_match']:
                    matched_prices = sum(1 for v in result['price_match'].values() if v['match'])
                    total_prices = len(result['price_match'])
                    self.logger.info(f"  价格匹配: {matched_prices}/{total_prices}")
                
                # 间隔时间
                if i < len(symbols) - 1:  # 最后一个不需要等待
                    time.sleep(interval)
                    
            except Exception as e:
                self.logger.error(f"测试 {symbol} 时发生严重错误: {e}")
    
    def generate_report(self) -> str:
        """生成详细测试报告"""
        if not self.test_results:
            return "没有测试结果"
        
        total = len(self.test_results)
        success = sum(1 for r in self.test_results if r.get('success', False))
        
        # 计算平均匹配率
        valid_results = [r for r in self.test_results if r.get('success', False) and 'match_rate' in r]
        avg_match_rate = sum(r['match_rate'] for r in valid_results) / len(valid_results) if valid_results else 0
        
        report = f"""
订单簿准确性测试报告 (修复版)
================================
测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
测试总数: {total}
成功数量: {success}
失败数量: {total - success}
成功率: {success/total*100:.2f}%
平均匹配率: {avg_match_rate*100:.2f}%

详细结果:
--------"""
        
        for result in self.test_results:
            symbol = result.get('symbol', 'Unknown')
            if result.get('success', False):
                match_rate = result.get('match_rate', 0)
                report += f"\n[OK] {symbol}: 成功 (匹配率: {match_rate*100:.2f}%)"
            else:
                error = result.get('error', '未知错误')
                report += f"\n[FAIL] {symbol}: 失败 - {error}"
                
                # 显示具体错误
                if 'errors' in result and result['errors']:
                    for error_detail in result['errors'][:5]:  # 最多显示5个错误
                        report += f"\n    - {error_detail}"
                    if len(result['errors']) > 5:
                        report += f"\n    - ... 还有 {len(result['errors'])-5} 个错误"
        
        return report


def setup_logging():
    """设置详细的日志配置 - 修复编码问题"""
    import sys
    
    # 修复Windows编码问题
    if sys.platform.startswith('win'):
        try:
            import codecs
            # 只在需要时设置编码
            if hasattr(sys.stdout, 'buffer'):
                sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
            if hasattr(sys.stderr, 'buffer'):
                sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)
        except (AttributeError, ImportError):
            # 如果设置失败，继续使用默认编码
            pass
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                f'orderbook_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log', 
                encoding='utf-8'
            )
        ]
    )
    
    # 设置特定模块的日志级别
    logging.getLogger("MarketDataFetcher").setLevel(logging.DEBUG)
    logging.getLogger("OrderBookAccuracyTest").setLevel(logging.DEBUG)


def run_accuracy_test():
    """运行准确性测试 - 修复版"""
    # 设置日志
    setup_logging()
    logger = logging.getLogger("MainTest")
    
    logger.info("开始订单簿准确性测试...")
    print("开始订单簿准确性测试...")
    print("=" * 60)
    
    # 检查交易时间
    current_time = datetime.now()
    if current_time.weekday() >= 5:  # 周末
        print("[WARN] 当前为非交易日，数据可能不是最新的")
        logger.warning("当前为非交易日")
    elif current_time.hour < 9 or current_time.hour >= 15:
        print("⚠️  警告: 当前为非交易时间，数据可能不是最新的")
        logger.warning("当前为非交易时间")
    else:
        print(f"[OK] 当前为交易时间，数据应该是最新的")
        logger.info("当前为交易时间")
    
    # 创建测试器
    tester = OrderBookAccuracyTest()
    
    # 测试股票列表 - 选择活跃度较高的股票
    test_symbols = [
        'sh600000',  # 浦发银行
        'sh600036',  # 招商银行  
        'sz000001',  # 平安银行
        'sz000002',  # 万科A
        'sz300059',  # 东方财富（创业板）
        # 'sh688111',  # 金山办公（科创板）- 暂时注释，科创板数据可能不稳定
    ]
    
    try:
        # 运行测试
        tester.test_multiple_stocks(test_symbols, interval=2)
        
        # 生成报告
        report = tester.generate_report()
        print("\n" + "="*60)
        print(report)
        
        # 保存报告
        report_file = f"orderbook_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"\n📄 测试报告已保存到: {report_file}")
        logger.info(f"测试报告已保存到: {report_file}")
        
        # 输出简要统计
        total_tests = len(tester.test_results)
        success_tests = sum(1 for r in tester.test_results if r.get('success', False))
        
        print(f"\n📊 测试统计:")
        print(f"   总测试数: {total_tests}")
        print(f"   成功数: {success_tests}")
        print(f"   失败数: {total_tests - success_tests}")
        print(f"   成功率: {success_tests/total_tests*100:.1f}%" if total_tests > 0 else "   成功率: 0%")
        
    except Exception as e:
        logger.error(f"测试过程中发生严重错误: {e}")
        logger.debug(traceback.format_exc())
        print(f"❌ 测试过程中发生严重错误: {e}")


def test_single_stock_detailed(symbol: str):
    """详细测试单只股票 - 用于调试"""
    # 移除重复的setup_logging调用，避免编码冲突
    logger = logging.getLogger("DetailedTest")
    
    logger.info(f"开始详细测试股票: {symbol}")
    print(f"开始详细测试股票: {symbol}")
    print("-" * 40)
    
    tester = OrderBookAccuracyTest()
    
    try:
        # 1. 获取市场数据
        print("1. 获取市场数据...")
        market_data = tester.data_fetcher.get_level2_snapshot_simulation(symbol)
        
        if market_data:
            print(f"   ✓ 成功获取市场数据")
            print(f"   现价: {market_data['last']}")
            print(f"   买盘档数: {len(market_data['bid_levels'])}")
            print(f"   卖盘档数: {len(market_data['ask_levels'])}")
            
            if market_data['bid_levels']:
                print(f"   买一: {market_data['bid_levels'][0]['price']} x {market_data['bid_levels'][0]['volume']}")
            if market_data['ask_levels']:
                print(f"   卖一: {market_data['ask_levels'][0]['price']} x {market_data['ask_levels'][0]['volume']}")
        else:
            print("   ❌ 无法获取市场数据")
            return
        
        # 2. 创建订单簿
        print("\n2. 创建订单簿...")
        ob = tester.create_orderbook(symbol)
        print(f"   ✓ 订单簿创建成功")
        print(f"   交易所: {'深交所' if ob.SecurityIDSource == SecurityIDSource_SZSE else '上交所'}")
        print(f"   昨收价: {ob.PrevClosePx}")
        print(f"   涨停价: {ob.UpLimitPrice}")
        print(f"   跌停价: {ob.DnLimitPrice}")
        
        # 3. 模拟订单
        print("\n3. 模拟订单...")
        tester.simulate_orders_from_snapshot(ob, market_data)
        print("   ✓ 订单模拟完成")
        
        # 4. 打印订单簿详情
        print("\n4. 订单簿详情...")
        tester.print_orderbook_details(ob, symbol)
        
        # 5. 生成快照并比较
        print("\n5. 生成快照并比较...")
        result = tester.compare_orderbook_with_market(ob, market_data)
        
        if result['success']:
            print(f"   ✓ 测试成功! 匹配率: {result['match_rate']:.2%}")
        else:
            print(f"   ❌ 测试失败: {result.get('error', '未知错误')}")
            if 'errors' in result:
                print("   详细错误:")
                for error in result['errors']:
                    print(f"     - {error}")
        
        # 5. 详细对比输出
        if 'price_match' in result:
            print("\n6. 详细价格对比:")
            for level, match_info in result['price_match'].items():
                status = "✓" if match_info['match'] else "❌"
                print(f"   {level}: 市场={match_info['market']:.3f}, "
                      f"订单簿={match_info['orderbook']:.3f}, "
                      f"差异={match_info['diff']:.4f} {status}")
        
    except Exception as e:
        logger.error(f"详细测试失败: {e}")
        logger.debug(traceback.format_exc())
        print(f"❌ 详细测试失败: {e}")


if __name__ == "__main__":
    # 运行完整测试
    run_accuracy_test()
    
    # 详细测试单只股票，取消注释下面的代码查看订单簿详情
    print("\n" + "="*60)
    print("🔍 详细测试示例 - 深交所股票")
    test_single_stock_detailed('sz000001')
    
    print("\n" + "="*60) 
    print("🔍 详细测试示例 - 上交所股票")
    test_single_stock_detailed('sh600000')