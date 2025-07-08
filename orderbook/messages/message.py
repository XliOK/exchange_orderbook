# 在 orderbook/messages/unified_message.py 中
from dataclasses import dataclass
from typing import Optional
from enum import IntEnum

class MsgType(IntEnum):
    ORDER = 192
    EXECUTION = 191
    SNAPSHOT = 111
    HEARTBEAT = 1

@dataclass(slots=True)  # 使用 slots 减少内存占用
class Message:
    """统一的消息类"""
    # 必需字段
    SecurityIDSource: int
    MsgType: int
    SecurityID: int
    ChannelNo: int
    ApplSeqNum: int
    TransactTime: int
    
    # 可选字段 - 使用默认值避免 Optional
    Price: int = 0
    OrderQty: int = 0
    Side: int = 0
    OrdType: int = 0
    
    # 执行字段
    BidApplSeqNum: int = 0
    OfferApplSeqNum: int = 0
    LastPx: int = 0
    LastQty: int = 0
    ExecType: int = 0
    
    # 快照字段
    NumTrades: int = 0
    TotalVolumeTrade: int = 0
    TotalValueTrade: int = 0
    
    @property
    def is_order(self) -> bool:
        return self.MsgType == MsgType.ORDER
    
    @property
    def is_execution(self) -> bool:
        return self.MsgType == MsgType.EXECUTION
    
    @property
    def is_snapshot(self) -> bool:
        return self.MsgType == MsgType.SNAPSHOT
    
    @property
    def HHMMSSms(self) -> int:
        """优化的时间戳处理"""
        if self.SecurityIDSource == 102:  # SZSE
            return self.TransactTime % 1000000000
        else:  # SSE
            return self.TransactTime * (10 if self.is_order or self.is_execution else 1000)
    
    @property
    def TradingPhaseMarket(self) -> int:
        """根据时间戳快速计算交易阶段"""
        t = self.HHMMSSms
        
        # 使用二分查找优化
        if t < 91500000: return 0  # Starting
        if t < 92500000: return 1  # OpenCall
        if t < 93000000: return 2  # PreTradingBreaking
        if t < 113000000: return 3  # AMTrading
        if t < 130000000: return 4  # Breaking
        if t < 145700000: return 5  # PMTrading
        if t < 150000000: return 6  # CloseCall
        return 9  # Ending