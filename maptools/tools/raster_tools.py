from .base_tool import BaseTool
from ..controllers.commands.brush_command import BrushCommand

class BrushTool(BaseTool):
    name = "brush"
    cursor = "dot"

    REFRESH_INTERVAL_MS = 16  # ~60fps

    def __init__(self, canvas, controller):
        super().__init__(canvas, controller)
        self.radius = 5
        self.value = 0  # 0 = Obstacle (Black)
        self.before_layer = None
        self._refresh_pending = False
        self._refresh_timer = None

    def _paint(self, event):
        if not self.canvas.map_data:
            return

        # 获取鼠标在Canvas上的坐标
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        # 转换为图像坐标
        px, py = self.canvas.canvas_to_image(cx, cy)

        # 应用编辑 (立即写入数据，保持笔画连续性)
        self.canvas.map_data.apply_brush(px, py, self.radius, self.value)

        # 标记需要刷新，由定时器统一处理
        self._refresh_pending = True

    def _schedule_refresh(self):
        """启动定时刷新循环"""
        if self._refresh_timer is not None:
            return
        self._do_throttled_refresh()

    def _do_throttled_refresh(self):
        """定时器回调：如果有脏数据则刷新显示"""
        if self._refresh_pending:
            self._refresh_pending = False
            self.canvas.refresh_image_only()
        self._refresh_timer = self.canvas.after(
            self.REFRESH_INTERVAL_MS, self._do_throttled_refresh
        )

    def _stop_refresh_timer(self):
        """停止定时刷新循环"""
        if self._refresh_timer is not None:
            self.canvas.after_cancel(self._refresh_timer)
            self._refresh_timer = None
        self._refresh_pending = False

    def on_press(self, event):
        if not self.canvas.map_data: return
        # 记录操作前的状态 (快照)
        if self.canvas.map_data.edit_layer is not None:
            self.before_layer = self.canvas.map_data.edit_layer.copy()

        self._schedule_refresh()
        self._paint(event)

    def on_drag(self, event):
        self._paint(event)

    def on_release(self, event):
        self._stop_refresh_timer()

        # 最终完整刷新，确保干净状态
        self.canvas.refresh()

        # 记录操作后的状态并提交命令
        if self.canvas.map_data and self.before_layer is not None:
            after_layer = self.canvas.map_data.edit_layer.copy()

            # 创建并提交命令
            if self.controller and hasattr(self.controller, 'command_manager') and self.controller.command_manager:
                cmd = BrushCommand(
                    self.canvas.map_data,
                    self.before_layer,
                    after_layer,
                    refresh_cb=self.canvas.refresh
                )
                self.controller.command_manager.execute(cmd)

            self.before_layer = None


class EraserTool(BrushTool):
    name = "eraser"
    cursor = "circle"

    def __init__(self, canvas, controller):
        super().__init__(canvas, controller)
        self.value = 254  # 254 = Free (White)


class StraightLineTool(BaseTool):
    """直线绘制工具：按下起点，拖拽预览，释放画线"""
    name = "straight_line"
    cursor = "crosshair"

    def __init__(self, canvas, controller):
        super().__init__(canvas, controller)
        self.radius = 5
        self.value = 0  # 0 = Obstacle (Black)
        self.before_layer = None
        self.start_canvas = None  # (cx, cy) 起点Canvas坐标
        self.is_dragging = False

    def on_press(self, event):
        if not self.canvas.map_data:
            return
        # 记录操作前的状态
        if self.canvas.map_data.edit_layer is not None:
            self.before_layer = self.canvas.map_data.edit_layer.copy()

        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        self.start_canvas = (cx, cy)
        self.is_dragging = True

    def on_drag(self, event):
        if not self.is_dragging or not self.start_canvas:
            return

        current_x = self.canvas.canvasx(event.x)
        current_y = self.canvas.canvasy(event.y)

        # 显示预览线
        self.canvas.delete("tool_preview")
        self.canvas.create_line(
            self.start_canvas[0], self.start_canvas[1],
            current_x, current_y,
            fill="red", width=max(1, self.radius * 2 * self.canvas.zoom_level),
            tags="tool_preview"
        )

    def on_release(self, event):
        if not self.is_dragging or not self.start_canvas:
            return

        self.canvas.delete("tool_preview")

        if self.canvas.map_data:
            end_cx = self.canvas.canvasx(event.x)
            end_cy = self.canvas.canvasy(event.y)

            # 转换为图像像素坐标
            x0, y0 = self.canvas.canvas_to_image(*self.start_canvas)
            x1, y1 = self.canvas.canvas_to_image(end_cx, end_cy)

            # 在edit_layer上画直线
            self.canvas.map_data.apply_line(x0, y0, x1, y1, self.radius, self.value)
            self.canvas.refresh()

            # 提交undo/redo命令
            if self.before_layer is not None:
                after_layer = self.canvas.map_data.edit_layer.copy()
                if self.controller and hasattr(self.controller, 'command_manager') and self.controller.command_manager:
                    cmd = BrushCommand(
                        self.canvas.map_data,
                        self.before_layer,
                        after_layer,
                        refresh_cb=self.canvas.refresh
                    )
                    self.controller.command_manager.execute(cmd)

        self.before_layer = None
        self.start_canvas = None
        self.is_dragging = False
