from abc import ABC, abstractmethod
from typing import List

class Command(ABC):
    """命令基类"""

    @abstractmethod
    def execute(self):
        """执行命令"""
        pass

    @abstractmethod
    def undo(self):
        """撤销命令"""
        pass

class CommandManager:
    """命令管理器，负责管理撤销/重做栈"""

    def __init__(self, max_history=50):
        self.undo_stack: List[Command] = []
        self.redo_stack: List[Command] = []
        self.max_history = max_history

    def execute(self, cmd: Command):
        """执行新命令"""
        cmd.execute()
        self.undo_stack.append(cmd)
        self.redo_stack.clear() # 清空重做栈

        # 限制栈大小
        if len(self.undo_stack) > self.max_history:
            self.undo_stack.pop(0)

        print(f"Command executed: {cmd.__class__.__name__}. Stack size: {len(self.undo_stack)}")

    def undo(self):
        """撤销上一步"""
        if not self.undo_stack:
            return

        cmd = self.undo_stack.pop()
        cmd.undo()
        self.redo_stack.append(cmd)
        print(f"Undo: {cmd.__class__.__name__}")

    def redo(self):
        """重做上一步"""
        if not self.redo_stack:
            return

        cmd = self.redo_stack.pop()
        cmd.execute()
        self.undo_stack.append(cmd)
        print(f"Redo: {cmd.__class__.__name__}")

    def can_undo(self):
        return len(self.undo_stack) > 0

    def can_redo(self):
        return len(self.redo_stack) > 0
