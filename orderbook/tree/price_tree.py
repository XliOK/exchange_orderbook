# 简化的树结构，直接使用 Python 的 dict 和排序
class SimplifiedPriceTree:
    """
    使用 Python dict 实现的价格树，利用内置的排序功能
    适用于订单簿的价格档位管理
    """
    def __init__(self, is_bid=True):
        self.levels = {}  # price -> level_node
        self.is_bid = is_bid
        self._sorted_prices = []
        self._needs_sort = False
    
    def insert(self, price, qty):
        """插入或更新价格档位"""
        if price in self.levels:
            self.levels[price].qty += qty
        else:
            self.levels[price] = level_node(price, qty, 0)
            self._needs_sort = True
    
    def remove(self, price, qty):
        """减少价格档位数量"""
        if price not in self.levels:
            return
            
        self.levels[price].qty -= qty
        if self.levels[price].qty <= 0:
            del self.levels[price]
            self._needs_sort = True
    
    def get_best(self):
        """获取最优价格和数量"""
        if not self.levels:
            return 0, 0
            
        if self._needs_sort:
            self._update_sorted_prices()
            
        if self.is_bid:
            price = self._sorted_prices[-1]  # 最高价
        else:
            price = self._sorted_prices[0]   # 最低价
            
        return price, self.levels[price].qty
    
    def get_levels(self, n=10):
        """获取前n档价格"""
        if self._needs_sort:
            self._update_sorted_prices()
            
        result = []
        if self.is_bid:
            prices = self._sorted_prices[-n:][::-1]  # 从高到低
        else:
            prices = self._sorted_prices[:n]  # 从低到高
            
        for price in prices:
            result.append((price, self.levels[price].qty))
            
        # 补齐空档
        while len(result) < n:
            result.append((0, 0))
            
        return result
    
    def _update_sorted_prices(self):
        """更新排序后的价格列表"""
        self._sorted_prices = sorted(self.levels.keys())
        self._needs_sort = False
    
    def clear(self):
        """清空所有价格档位"""
        self.levels.clear()
        self._sorted_prices.clear()
        self._needs_sort = False

# 优化后的 AXOB 中使用简化树
class AXOB:
    def __init__(self, SecurityID, SecurityIDSource, instrument_type):
        # ... 其他初始化代码 ...
        
        # 使用简化的价格树替代 AVL/RB 树
        self.bid_tree = SimplifiedPriceTree(is_bid=True)
        self.ask_tree = SimplifiedPriceTree(is_bid=False)
        
        # 直接使用 dict 存储订单
        self.order_map = {}
        
    def insertOrder(self, order: ob_order):
        """简化的订单插入"""
        self.order_map[order.applSeqNum] = order
        
        if order.side == SIDE.BID:
            self.bid_tree.insert(order.price, order.qty)
            self.BidWeightSize += order.qty
            self.BidWeightValue += order.price * order.qty
        else:
            self.ask_tree.insert(order.price, order.qty)
            self.AskWeightSize += order.qty
            self.AskWeightValue += order.price * order.qty
        
        # 更新最优价格缓存
        self._updateBestPrices()
    
    def removeOrder(self, price, qty, side):
        """简化的订单移除"""
        if side == SIDE.BID:
            self.bid_tree.remove(price, qty)
            self.BidWeightSize -= qty
            self.BidWeightValue -= price * qty
        else:
            self.ask_tree.remove(price, qty)
            self.AskWeightSize -= qty
            self.AskWeightValue -= price * qty
        
        self._updateBestPrices()
    
    def _updateBestPrices(self):
        """更新最优价格"""
        self.bid_max_level_price, self.bid_max_level_qty = self.bid_tree.get_best()
        self.ask_min_level_price, self.ask_min_level_qty = self.ask_tree.get_best()