# -*- coding: utf-8 -*-

from orderbook.messages import axsbe_base
from orderbook.messages.axsbe_base import INSTRUMENT_TYPE, SecurityIDSource_SSE, SecurityIDSource_SZSE
from enum import Enum

#### 交易所板块子类型
class MARKET_SUBTYPE(Enum):
    SZSE_STK_MB  =  0   #深交所主板
    SZSE_STK_SME =  1   #深交所中小板
    SZSE_STK_GEM =  2   #深交所创业板
    SZSE_STK_B   =  3   #深交所B股
    SZSE_KZZ     =  4   #深交所可转债
    SZSE_OTHERS  =  5   #深交所其它
    SSE          =  6   #上交所

def market_subtype(SecurityIDSource, SecurityID):
    """获取市场子类型"""
    if SecurityIDSource == SecurityIDSource_SZSE:
        if SecurityID <= 1999:
            return MARKET_SUBTYPE.SZSE_STK_MB
        elif SecurityID < 4999:
            return MARKET_SUBTYPE.SZSE_STK_SME
        elif 300000 <= SecurityID < 309999:
            return MARKET_SUBTYPE.SZSE_STK_GEM
        elif 200000 <= SecurityID < 209999:
            return MARKET_SUBTYPE.SZSE_STK_B
        elif 120000 <= SecurityID < 129999:
            return MARKET_SUBTYPE.SZSE_KZZ
        else:
            return MARKET_SUBTYPE.SZSE_OTHERS
    else:
        return MARKET_SUBTYPE.SSE

# 原始数据精度常量
PRICE_SZSE_INCR_PRECISION = 10000
PRICE_SZSE_SNAP_PRECISION = 10000
PRICE_SZSE_SNAP_PRECLOSE_PRECISION = 10000
QTY_SZSE_PRECISION = 100
TOTALVALUETRADE_SZSE_PRECISION = 10000

PRICE_SSE_PRECISION = 1000
QTY_SSE_PRECISION = 1000
TOTALVALUETRADE_SSE_PRECISION = 100000

ORDER_PRICE_OVERFLOW = 0x7fffffff

# 创业板价格笼子范围
CYB_cage_upper = lambda x: x+1 if x<=24 else (x*102 + 50) // 100
CYB_cage_lower = lambda x: x-1 if x<=25 else (x*98 + 50) // 100

# 创业板有效竞价范围
CYB_match_upper = lambda x: (x*110 + 50) // 100
CYB_match_lower = lambda x: (x*90 + 50) // 100

def bitSizeOf(i: int):
    """计算整数的位数"""
    return i.bit_length() if i > 0 else 0

def isTPMfreeze(x):
    """判断是否处于冻结阶段"""
    return (x.TradingPhaseMarket == axsbe_base.TPM.Starting or
            x.TradingPhaseMarket == axsbe_base.TPM.PreTradingBreaking or
            x.TradingPhaseMarket == axsbe_base.TPM.Breaking or
            x.TradingPhaseMarket >= axsbe_base.TPM.Ending)