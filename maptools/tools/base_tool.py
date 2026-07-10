from abc import ABC, abstractmethod

class BaseTool(ABC):
    """
    所有工具的基类
    """
    name = "base"
    cursor = "arrow"

    def __init__(self, canvas, controller):
        """
        :param canvas: MapCanvas实例
        :param controller: 通常是ToolManager或MainWindow，用于访问全局状态
        """
        self.canvas = canvas
        self.controller = controller

    def activate(self):
        """工具激活时调用"""
        self.canvas.config(cursor=self.cursor)
        self.canvas.focus_set()

    def deactivate(self):
        """工具停用时调用"""
        pass

    def on_press(self, event):
        """鼠标左键按下"""
        pass

    def on_drag(self, event):
        """鼠标左键拖动"""
        pass

    def on_release(self, event):
        """鼠标左键释放"""
        pass

    def on_move(self, event):
        """鼠标移动 (无按键)"""
        pass
