# 简化的消息基类，合并多个消息类的功能
from dataclasses import dataclass, field
from typing import Optional, Dict
import struct

@dataclass
class Message:
    """统一的消息类，使用 dataclass 简化代码"""
    SecurityIDSource: int
    MsgType: int
    SecurityID: int
    ChannelNo: int
    ApplSeqNum: int = 0
    TransactTime: int = 0
    
    # Order fields
    Price: Optional[int] = None
    OrderQty: Optional[int] = None
    Side: Optional[int] = None
    OrdType: Optional[int] = None
    OrderNo: Optional[int] = None
    
    # Execution fields
    BidApplSeqNum: Optional[int] = None
    OfferApplSeqNum: Optional[int] = None
    LastPx: Optional[int] = None
    LastQty: Optional[int] = None
    ExecType: Optional[int] = None
    
    # Snapshot fields
    NumTrades: Optional[int] = None
    TotalVolumeTrade: Optional[int] = None
    TotalValueTrade: Optional[int] = None
    bid_levels: Dict = field(default_factory=dict)
    ask_levels: Dict = field(default_factory=dict)
    
    @property
    def is_order(self):
        return self.MsgType in [192, 65, 68]
    
    @property
    def is_execution(self):
        return self.MsgType in [191, 84]
    
    @property
    def is_snapshot(self):
        return self.MsgType in [111, 211, 38]
    
    @property
    def TradingPhaseMarket(self):
        """根据时间戳计算交易阶段"""
        t = self.HHMMSSms
        if t < 91500000:
            return TPM.Starting
        elif t < 92500000:
            return TPM.OpenCall
        elif t < 93000000:
            return TPM.PreTradingBreaking
        elif t < 113000000:
            return TPM.AMTrading