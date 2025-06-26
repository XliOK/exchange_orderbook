# -*- coding: utf-8 -*-
"""
使用免费第三方API测试订单簿准确性
支持的数据源：
1. 新浪财经 - 实时行情
2. 腾讯财经 - 实时行情
3. 东方财富 - 实时行情
4. Akshare - 综合数据接口
"""

import time
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import logging
import akshare as ak  # pip install akshare

from orderbook.core.axob import AXOB, AX_SIGNAL
from orderbook.messages.axsbe_order import axsbe_order
from orderbook.messages.axsbe_exe import axsbe_exe
from orderbook.messages.axsbe_snap_stock import axsbe_snap_stock
from orderbook.messages.axsbe_base import SecurityIDSource_SZSE, SecurityIDSource_SSE, INSTRUMENT_TYPE, TPM
class MarketDataFetcher:
    """市场数据获取器"""
    
    def __init__(self):
        self.logger = logging.getLogger("MarketDataFetcher")
        
    def get_realtime_quote_sina(self, symbol: str) -> Dict:
        """
        从新浪财经获取实时行情
        symbol: 股票代码，如 sh600000, sz000001
        """
        url = f"http://hq.sinajs.cn/list={symbol}"
        headers = {
            'Referer': 'http://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=5)
            response.encoding = 'gbk'
            
            if response.status_code == 200:
                data = response.text.strip()
                if data and 'var hq_str_' in data:
                    # 解析数据
                    content = data.split('="')[1].split('";')[0]
                    fields = content.split(',')
                    
                    if len(fields) >= 32:
                        return {
                            'name': fields[0],
                            'open': float(fields[1]),
                            'pre_close': float(fields[2]),
                            'current': float(fields[3]),
                            'high': float(fields[4]),
                            'low': float(fields[5]),
                            'bid': float(fields[6]),
                            'ask': float(fields[7]),
                            'volume': int(fields[8]),
                            'amount': float(fields[9]),
                            # 五档买卖盘
                            'bid1_volume': int(fields[10]),
                            'bid1': float(fields[11]),
                            'bid2_volume': int(fields[12]),
                            'bid2': float(fields[13]),
                            'bid3_volume': int(fields[14]),
                            'bid3': float(fields[15]),
                            'bid4_volume': int(fields[16]),
                            'bid4': float(fields[17]),
                            'bid5_volume': int(fields[18]),
                            'bid5': float(fields[19]),
                            'ask1_volume': int(fields[20]),
                            'ask1': float(fields[21]),
                            'ask2_volume': int(fields[22]),
                            'ask2': float(fields[23]),
                            'ask3_volume': int(fields[24]),
                            'ask3': float(fields[25]),
                            'ask4_volume': int(fields[26]),
                            'ask4': float(fields[27]),
                            'ask5_volume': int(fields[28]),
                            'ask5': float(fields[29]),
                            'date': fields[30],
                            'time': fields[31],
                        }
        except Exception as e:
            self.logger.error(f"获取新浪行情失败: {e}")
        
        return None
    
    def get_realtime_quote_tencent(self, symbol: str) -> Dict:
        """
        从腾讯财经获取实时行情
        symbol: 股票代码，如 sh600000, sz000001
        """
        url = f"http://qt.gtimg.cn/q={symbol}"
        
        try:
            response = requests.get(url, timeout=5)
            response.encoding = 'gbk'
            
            if response.status_code == 200:
                data = response.text.strip()
                if data:
                    # 解析数据
                    content = data.split('~')
                    if len(content) >= 45:
                        return {
                            'name': content[1],
                            'code': content[2],
                            'current': float(content[3]),
                            'pre_close': float(content[4]),
                            'open': float(content[5]),
                            'volume': int(content[6]) * 100,  # 手转股
                            'bid': float(content[9]),
                            'ask': float(content[10]),
                            'amount': float(content[37]),
                            'high': float(content[33]),
                            'low': float(content[34]),
                            # 五档买卖盘
                            'bid1': float(content[9]),
                            'bid1_volume': int(content[10]) * 100,
                            'bid2': float(content[11]),
                            'bid2_volume': int(content[12]) * 100,
                            'bid3': float(content[13]),
                            'bid3_volume': int(content[14]) * 100,
                            'bid4': float(content[15]),
                            'bid4_volume': int(content[16]) * 100,
                            'bid5': float(content[17]),
                            'bid5_volume': int(content[18]) * 100,
                            'ask1': float(content[19]),
                            'ask1_volume': int(content[20]) * 100,
                            'ask2': float(content[21]),
                            'ask2_volume': int(content[22]) * 100,
                            'ask3': float(content[23]),
                            'ask3_volume': int(content[24]) * 100,
                            'ask4': float(content[25]),
                            'ask4_volume': int(content[26]) * 100,
                            'ask5': float(content[27]),
                            'ask5_volume': int(content[28]) * 100,
                            'date': content[30],
                            'time': content[31],
                        }
        except Exception as e:
            self.logger.error(f"获取腾讯行情失败: {e}")
        
        return None
    
    def get_tick_data_akshare(self, symbol: str, trade_date: str) -> pd.DataFrame:
        """
        使用akshare获取历史分笔数据
        symbol: 股票代码，如 000001
        trade_date: 交易日期，如 20231225
        """
        try:
            # 获取历史分笔数据
            df = ak.stock_zh_a_tick_tx(symbol=symbol, trade_date=trade_date)
            return df
        except Exception as e:
            self.logger.error(f"获取akshare分笔数据失败: {e}")
            return pd.DataFrame()
    
    def get_level2_snapshot_simulation(self, symbol: str) -> Dict:
        """
        模拟Level2快照数据（基于免费接口的5档数据）
        实际项目中可以接入付费的Level2数据
        """
        # 尝试多个数据源
        sina_data = self.get_realtime_quote_sina(symbol)
        
        if sina_data:
            # 构造快照格式
            snapshot = {
                'symbol': symbol,
                'timestamp': f"{sina_data['date']} {sina_data['time']}",
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
                if sina_data[f'bid{i}'] > 0:
                    snapshot['bid_levels'].append({
                        'price': sina_data[f'bid{i}'],
                        'volume': sina_data[f'bid{i}_volume']
                    })
                if sina_data[f'ask{i}'] > 0:
                    snapshot['ask_levels'].append({
                        'price': sina_data[f'ask{i}'],
                        'volume': sina_data[f'ask{i}_volume']
                    })
            
            return snapshot
        
        return None


class OrderBookAccuracyTest:
    """订单簿准确性测试"""
    
    def __init__(self):
        self.logger = logging.getLogger("OrderBookAccuracyTest")
        self.data_fetcher = MarketDataFetcher()
        self.test_results = []
        
    def create_orderbook(self, symbol: str) -> AXOB:
        """创建订单簿"""
        # 判断市场
        if symbol.startswith('sh'):
            security_id = int(symbol[2:])
            source = SecurityIDSource_SSE
        else:  # sz
            security_id = int(symbol[2:])
            source = SecurityIDSource_SZSE
            
        ob = AXOB(security_id, source, INSTRUMENT_TYPE.STOCK)
        
        # 初始化常量（从实时数据获取）
        market_data = self.data_fetcher.get_realtime_quote_sina(symbol)
        if market_data:
            ob.constantValue_ready = True
            ob.PrevClosePx = int(market_data['pre_close'] * 100)
            
            # 计算涨跌停价
            if symbol.startswith('sz300') or symbol.startswith('sh688'):
                # 创业板/科创板 20%
                ob.UpLimitPx = int(ob.PrevClosePx * 1.2)
                ob.DnLimitPx = int(ob.PrevClosePx * 0.8)
            else:
                # 主板 10%
                ob.UpLimitPx = int(ob.PrevClosePx * 1.1)
                ob.DnLimitPx = int(ob.PrevClosePx * 0.9)
                
            ob.UpLimitPrice = ob.UpLimitPx
            ob.DnLimitPrice = ob.DnLimitPx
            ob.YYMMDD = int(datetime.now().strftime('%Y%m%d'))
            
        return ob
    
    def simulate_orders_from_snapshot(self, ob: AXOB, snapshot: Dict):
        """从快照数据模拟订单"""
        # 设置交易阶段
        current_time = datetime.now()
        if current_time.hour < 9 or (current_time.hour == 9 and current_time.minute < 15):
            ob.TradingPhaseMarket = TPM.Starting
        elif current_time.hour == 9 and current_time.minute < 25:
            ob.TradingPhaseMarket = TPM.OpenCall
        elif current_time.hour == 9 and current_time.minute < 30:
            ob.TradingPhaseMarket = TPM.PreTradingBreaking
        elif (current_time.hour < 11 or (current_time.hour == 11 and current_time.minute < 30)):
            ob.TradingPhaseMarket = TPM.AMTrading
        elif current_time.hour < 13:
            ob.TradingPhaseMarket = TPM.Breaking
        elif current_time.hour < 14 or (current_time.hour == 14 and current_time.minute < 57):
            ob.TradingPhaseMarket = TPM.PMTrading
        elif current_time.hour == 14 and current_time.minute < 15:
            ob.TradingPhaseMarket = TPM.CloseCall
        else:
            ob.TradingPhaseMarket = TPM.Ending
            
        # 模拟买单
        seq_num = 1
        for i, bid_level in enumerate(snapshot['bid_levels']):
            order = axsbe_order(ob.SecurityIDSource)
            order.SecurityID = ob.SecurityID
            order.ApplSeqNum = seq_num
            order.Price = int(bid_level['price'] * 100)
            order.OrderQty = int(bid_level['volume'])
            order.setSide("买入")
            order.setType("限价")
            order.TransactTime = int(current_time.strftime('%Y%m%d%H%M%S%f')[:-3])
            order.TradingPhaseMarket = ob.TradingPhaseMarket
            
            ob.onMsg(order)
            seq_num += 1
            
        # 模拟卖单
        for i, ask_level in enumerate(snapshot['ask_levels']):
            order = axsbe_order(ob.SecurityIDSource)
            order.SecurityID = ob.SecurityID
            order.ApplSeqNum = seq_num
            order.Price = int(ask_level['price'] * 100)
            order.OrderQty = int(ask_level['volume'])
            order.setSide("卖出")
            order.setType("限价")
            order.TransactTime = int(current_time.strftime('%Y%m%d%H%M%S%f')[:-3])
            order.TradingPhaseMarket = ob.TradingPhaseMarket
            
            ob.onMsg(order)
            seq_num += 1
    
    def compare_orderbook_with_market(self, ob: AXOB, market_snapshot: Dict) -> Dict:
        """比较订单簿与市场数据"""
        # 生成订单簿快照
        ob_snapshot = ob.genSnap()
        
        if not ob_snapshot:
            return {'success': False, 'error': '无法生成订单簿快照'}
        
        # 比较结果
        comparison = {
            'success': True,
            'symbol': market_snapshot['symbol'],
            'timestamp': market_snapshot['timestamp'],
            'price_match': {},
            'volume_match': {},
            'errors': []
        }
        
        # 比较买盘
        for i, market_bid in enumerate(market_snapshot['bid_levels'][:5]):
            if i < len(ob_snapshot.bid):
                ob_price = ob_snapshot.bid[i].Price / 1000000  # 转换精度
                ob_volume = ob_snapshot.bid[i].Qty / 100
                
                price_diff = abs(ob_price - market_bid['price'])
                volume_diff = abs(ob_volume - market_bid['volume'])
                
                comparison['price_match'][f'bid{i+1}'] = {
                    'market': market_bid['price'],
                    'orderbook': ob_price,
                    'diff': price_diff,
                    'match': price_diff < 0.01
                }
                
                comparison['volume_match'][f'bid{i+1}'] = {
                    'market': market_bid['volume'],
                    'orderbook': ob_volume,
                    'diff': volume_diff,
                    'match': volume_diff < 100  # 允许1手误差
                }
                
                if not comparison['price_match'][f'bid{i+1}']['match']:
                    comparison['errors'].append(f"买{i+1}价格不匹配")
                if not comparison['volume_match'][f'bid{i+1}']['match']:
                    comparison['errors'].append(f"买{i+1}数量不匹配")
        
        # 比较卖盘
        for i, market_ask in enumerate(market_snapshot['ask_levels'][:5]):
            if i < len(ob_snapshot.ask):
                ob_price = ob_snapshot.ask[i].Price / 1000000
                ob_volume = ob_snapshot.ask[i].Qty / 100
                
                price_diff = abs(ob_price - market_ask['price'])
                volume_diff = abs(ob_volume - market_ask['volume'])
                
                comparison['price_match'][f'ask{i+1}'] = {
                    'market': market_ask['price'],
                    'orderbook': ob_price,
                    'diff': price_diff,
                    'match': price_diff < 0.01
                }
                
                comparison['volume_match'][f'ask{i+1}'] = {
                    'market': market_ask['volume'],
                    'orderbook': ob_volume,
                    'diff': volume_diff,
                    'match': volume_diff < 100
                }
                
                if not comparison['price_match'][f'ask{i+1}']['match']:
                    comparison['errors'].append(f"卖{i+1}价格不匹配")
                if not comparison['volume_match'][f'ask{i+1}']['match']:
                    comparison['errors'].append(f"卖{i+1}数量不匹配")
        
        comparison['success'] = len(comparison['errors']) == 0
        return comparison
    
    def test_single_stock(self, symbol: str) -> Dict:
        """测试单只股票"""
        self.logger.info(f"开始测试股票: {symbol}")
        
        # 获取市场数据
        market_snapshot = self.data_fetcher.get_level2_snapshot_simulation(symbol)
        if not market_snapshot:
            return {'success': False, 'error': '无法获取市场数据'}
        
        # 创建订单簿
        ob = self.create_orderbook(symbol)
        
        # 模拟订单
        self.simulate_orders_from_snapshot(ob, market_snapshot)
        
        # 比较结果
        comparison = self.compare_orderbook_with_market(ob, market_snapshot)
        
        # 记录结果
        self.test_results.append(comparison)
        
        return comparison
    
    def test_multiple_stocks(self, symbols: List[str], interval: int = 5):
        """测试多只股票"""
        for symbol in symbols:
            try:
                result = self.test_single_stock(symbol)
                
                if result['success']:
                    self.logger.info(f"{symbol} 测试通过")
                else:
                    self.logger.warning(f"{symbol} 测试失败: {result.get('errors', [])}")
                
                # 输出详细对比
                if 'price_match' in result:
                    print(f"\n{symbol} 价格对比:")
                    for level, match_info in result['price_match'].items():
                        status = "✓" if match_info['match'] else "✗"
                        print(f"  {level}: 市场={match_info['market']:.2f}, "
                              f"订单簿={match_info['orderbook']:.2f}, "
                              f"差异={match_info['diff']:.3f} {status}")
                
                # 间隔时间，避免请求过快
                time.sleep(interval)
                
            except Exception as e:
                self.logger.error(f"测试 {symbol} 时发生错误: {e}")
                
    def generate_report(self) -> str:
        """生成测试报告"""
        if not self.test_results:
            return "没有测试结果"
        
        total = len(self.test_results)
        success = sum(1 for r in self.test_results if r['success'])
        
        report = f"""
订单簿准确性测试报告
====================
测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
测试总数: {total}
成功数量: {success}
失败数量: {total - success}
成功率: {success/total*100:.2f}%

详细结果:
"""
        
        for result in self.test_results:
            if not result['success']:
                report += f"\n{result.get('symbol', 'Unknown')}:"
                for error in result.get('errors', []):
                    report += f"\n  - {error}"
        
        return report


def run_accuracy_test():
    """运行准确性测试"""
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 创建测试器
    tester = OrderBookAccuracyTest()
    
    # 测试股票列表
    test_symbols = [
        'sh600000',  # 浦发银行
        'sh600036',  # 招商银行
        'sz000001',  # 平安银行
        'sz000002',  # 万科A
        'sz300059',  # 东方财富（创业板）
        'sh688111',  # 金山办公（科创板）
    ]
    
    print("开始订单簿准确性测试...")
    print("=" * 60)
    
    # 检查是否在交易时间
    current_time = datetime.now()
    if current_time.weekday() >= 5:  # 周末
        print("警告: 当前为非交易日，数据可能不是最新的")
    elif current_time.hour < 9 or current_time.hour >= 15:
        print("警告: 当前为非交易时间，数据可能不是最新的")
    
    # 运行测试
    tester.test_multiple_stocks(test_symbols)
    
    # 生成报告
    report = tester.generate_report()
    print(report)
    
    # 保存报告
    report_file = f"orderbook_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n测试报告已保存到: {report_file}")


def test_with_historical_ticks():
    """使用历史分笔数据测试"""
    # 使用akshare获取历史数据进行回测
    fetcher = MarketDataFetcher()
    
    # 获取某只股票的历史分笔数据
    symbol = "000001"
    trade_date = "20231220"  # 使用最近的交易日
    
    print(f"获取 {symbol} 在 {trade_date} 的历史分笔数据...")
    tick_data = fetcher.get_tick_data_akshare(symbol, trade_date)
    
    if not tick_data.empty:
        print(f"获取到 {len(tick_data)} 条分笔数据")
        print(tick_data.head())
        
        # TODO: 将分笔数据转换为订单和成交，重建订单簿
        # 这需要更复杂的逻辑来解析分笔数据
    else:
        print("未能获取历史分笔数据")


if __name__ == "__main__":
    # 运行实时准确性测试
    run_accuracy_test()
    
    # 如果需要测试历史数据
    # test_with_historical_ticks()