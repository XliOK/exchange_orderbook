from collections import deque


class SimpleStack:
    """优化的栈实现，使用 deque 提高性能"""
    
    __slots__ = ['_stack', 'max_size', 'push_count', 'pop_count']
    
    def __init__(self):
        self._stack = deque()
        self.max_size = 0
        self.push_count = 0
        self.pop_count = 0
    
    def is_empty(self):
        """判断是否为空"""
        return len(self._stack) == 0
    
    def push(self, item):
        """压栈"""
        self._stack.append(item)
        self.push_count += 1
        current_size = len(self._stack)
        if current_size > self.max_size:
            self.max_size = current_size
    
    def pop(self):
        """弹栈"""
        if self._stack:
            self.pop_count += 1
            return self._stack.pop()
        return None
    
    def top(self):
        """查看栈顶元素"""
        if self._stack:
            return self._stack[-1]
        return None
    
    def clear(self):
        """清空栈"""
        self._stack.clear()
        self.max_size = 0
        self.push_count = 0
        self.pop_count = 0
    
    def __len__(self):
        """返回栈大小"""
        return len(self._stack)
    
    def __bool__(self):
        """支持 if stack: 语法"""
        return len(self._stack) > 0
