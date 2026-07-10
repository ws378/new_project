from ..tools.base_tool import BaseTool

class ToolManager:
    """
    管理工具状态和切换
    """
    def __init__(self, canvas, command_manager=None):
        self.canvas = canvas
        self.command_manager = command_manager
        self.tools = {}
        self.current_tool = None

        # 绑定Canvas事件，转发给当前工具

        # 注意：这里只绑定左键操作，中键/滚轮由Canvas自己处理用于导航
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_move)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
    def register_tool(self, tool_class, controller=None):
        """注册一个工具类"""

        # controller通常是MainWindow实例，方便工具访问其他组件
        tool = tool_class(self.canvas, controller)
        self.tools[tool.name] = tool
        print(f"Registered tool: {tool.name}")

    def set_tool(self, tool_name):
        """切换当前工具"""
        if tool_name not in self.tools:
            print(f"Tool not found: {tool_name}")
            return

        if self.current_tool:
            self.current_tool.deactivate()

        self.current_tool = self.tools[tool_name]
        self.current_tool.activate()
        print(f"Switched to tool: {tool_name}")

    def get_tool(self, tool_name):
        return self.tools.get(tool_name)

    # --- 事件分发 ---

    def _on_press(self, event):
        # 如果 Canvas 处于取点模式，优先交给取点处理
        if getattr(self.canvas, '_pick_start_mode', False):
            self.canvas._on_left_click(event)
            return
        if self.current_tool:
            self.current_tool.on_press(event)

    def _on_drag(self, event):
        if self.current_tool:
            self.current_tool.on_drag(event)

    def _on_release(self, event):
        if self.current_tool:
            self.current_tool.on_release(event)

    def _on_move(self, event):
        if self.current_tool:
            self.current_tool.on_move(event)
        if hasattr(self.canvas, "handle_motion"):
            self.canvas.handle_motion(event)

    def _on_double_click(self, event):
        if self.current_tool and hasattr(self.current_tool, 'on_double_click'):
            self.current_tool.on_double_click(event)

    def handle_key_press(self, event):
        if self.current_tool and hasattr(self.current_tool, 'on_key_press'):
            self.current_tool.on_key_press(event)
