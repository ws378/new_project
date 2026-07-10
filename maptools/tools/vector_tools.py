import math
from .base_tool import BaseTool
from ..controllers.commands.annotation_command import AddAnnotationCommand

class PolygonTool(BaseTool):
    name = "polygon"
    cursor = "crosshair"

    def __init__(self, canvas, controller):
        super().__init__(canvas, controller)
        self.points = [] # List of (world_x, world_y) - 存储世界坐标以支持缩放跟随
        self.temp_id = None

    def on_press(self, event):
        # 左键点击添加点 (转换为世界坐标存储)
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        if self.canvas.coord_transformer:
            wx, wy = self.canvas.coord_transformer.canvas_to_world(cx, cy)
            self.points.append((wx, wy))
        self._update_preview()

    def on_move(self, event):
        # 移动时显示预览线
        if not self.points:
            return

        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        self._update_preview(current_canvas_pos=(cx, cy))

    def _world_points_to_canvas(self):
        """将世界坐标点列表转换为 canvas 坐标"""
        canvas_pts = []
        if self.canvas.coord_transformer:
            for wx, wy in self.points:
                cx, cy = self.canvas.coord_transformer.world_to_canvas(wx, wy)
                canvas_pts.append((cx, cy))
        return canvas_pts

    def _update_preview(self, current_canvas_pos=None):
        self.canvas.delete("tool_preview")

        if not self.points:
            return

        # 每次从世界坐标实时转换，确保缩放后跟随
        draw_points = self._world_points_to_canvas()
        if current_canvas_pos:
            draw_points.append(current_canvas_pos)

        if len(draw_points) >= 2:
            self.canvas.create_line(draw_points, fill="red", width=2, tags="tool_preview")
            # 如果要封闭预览
            if len(draw_points) >= 3:
                 self.canvas.create_polygon(draw_points, outline="red", fill="", dash=(4, 4), tags="tool_preview")

        # 绘制已确定的点 (不含鼠标跟随点)
        confirmed_canvas = self._world_points_to_canvas()
        for p in confirmed_canvas:
            self.canvas.create_oval(p[0]-3, p[1]-3, p[0]+3, p[1]+3, fill="red", tags="tool_preview")

    def finish(self):
        """完成绘制"""
        if len(self.points) >= 3:
            # points 已经是世界坐标，直接使用
            world_points = list(self.points)

            # 使用Command提交
            if self.canvas.annotations and self.controller and hasattr(self.controller, 'command_manager'):
                cmd = AddAnnotationCommand(
                    self.canvas.annotations,
                    'forbidden',
                    world_points,
                    refresh_cb=self.canvas.refresh
                )
                self.controller.command_manager.execute(cmd)
        self.reset()
        self.canvas.refresh()

    def reset(self):
        self.points = []
        self.canvas.delete("tool_preview")

    def on_double_click(self, event):
        # 双击结束
        self.finish()

    def on_key_press(self, event):
        if event.keysym == 'Escape':
            self.reset()
            self.canvas.refresh()

class LineTool(BaseTool):
    name = "line"
    cursor = "crosshair"

    def __init__(self, canvas, controller):
        super().__init__(canvas, controller)
        self.start_pos = None # (cx, cy)
        self.is_dragging = False

    def on_press(self, event):
        self.start_pos = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        self.is_dragging = True

    def on_drag(self, event):
        if not self.is_dragging:
            return

        current_x = self.canvas.canvasx(event.x)
        current_y = self.canvas.canvasy(event.y)

        self.canvas.delete("tool_preview")
        self.canvas.create_line(self.start_pos[0], self.start_pos[1],
                               current_x, current_y,
                               fill="blue", width=3, dash=(5, 3), tags="tool_preview")

    def on_release(self, event):
        if not self.is_dragging:
            return

        end_x = self.canvas.canvasx(event.x)
        end_y = self.canvas.canvasy(event.y)

        # 转换为世界坐标
        if self.canvas.coord_transformer and self.canvas.annotations:
            wx1, wy1 = self.canvas.coord_transformer.canvas_to_world(*self.start_pos)
            wx2, wy2 = self.canvas.coord_transformer.canvas_to_world(end_x, end_y)

            # 只有长度足够才添加
            dist = math.hypot(wx1-wx2, wy1-wy2)
            if dist > 0.1: # 大于10cm
                # 使用Command提交
                if self.controller and hasattr(self.controller, 'command_manager'):
                    cmd = AddAnnotationCommand(
                        self.canvas.annotations,
                        'virtual_wall',
                        ((wx1, wy1), (wx2, wy2)),
                        refresh_cb=self.canvas.refresh
                    )
                    self.controller.command_manager.execute(cmd)
                    print(f"Added virtual wall via Command: {dist:.2f}m")

        self.is_dragging = False
        self.canvas.delete("tool_preview")
        self.canvas.refresh()

    def on_key_press(self, event):
        if event.keysym == 'Escape' and self.is_dragging:
            self.is_dragging = False
            self.start_pos = None
            self.canvas.delete("tool_preview")
            self.canvas.refresh()


class StationTool(BaseTool):
    name = "station"
    cursor = "crosshair"

    def __init__(self, canvas, controller):
        super().__init__(canvas, controller)
        self.position = None # (cx, cy)
        self.is_dragging = False

    def on_press(self, event):
        self.position = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        self.is_dragging = True

    def on_drag(self, event):
        if not self.is_dragging:
            return

        # 拖拽设置方向
        current_x = self.canvas.canvasx(event.x)
        current_y = self.canvas.canvasy(event.y)

        self.canvas.delete("tool_preview")

        # 画点
        r = 5
        cx, cy = self.position
        self.canvas.create_oval(cx-r, cy-r, cx+r, cy+r, fill="green", tags="tool_preview")

        # 画箭头
        self.canvas.create_line(cx, cy, current_x, current_y,
                               fill="lime", width=2, arrow="last", tags="tool_preview")

    def on_release(self, event):
        if not self.is_dragging:
            return

        # 计算方向
        cx, cy = self.position
        end_x = self.canvas.canvasx(event.x)
        end_y = self.canvas.canvasy(event.y)

        # Canvas坐标系Y轴向下，atan2返回的是屏幕坐标系的角度
        # 0 is right, pi/2 is down
        canvas_angle = math.atan2(end_y - cy, end_x - cx)

        # 转换为ROS世界坐标系角度 (Y轴翻转)
        # 0 is right, pi/2 is up
        # So ros_angle = -canvas_angle
        ros_angle = -canvas_angle

        # 转换为世界坐标
        if self.canvas.coord_transformer and self.canvas.annotations:
            wx, wy = self.canvas.coord_transformer.canvas_to_world(cx, cy)

            # 使用Command提交
            if self.controller and hasattr(self.controller, 'command_manager'):
                cmd = AddAnnotationCommand(
                    self.canvas.annotations,
                    'station',
                    ((wx, wy), ros_angle),
                    refresh_cb=self.canvas.refresh
                )
                self.controller.command_manager.execute(cmd)
                print(f"Added station via Command at ({wx:.2f}, {wy:.2f})")

        self.is_dragging = False
        self.canvas.delete("tool_preview")
        self.canvas.refresh()

    def on_key_press(self, event):
        if event.keysym == 'Escape' and self.is_dragging:
            self.is_dragging = False
            self.position = None
            self.canvas.delete("tool_preview")
            self.canvas.refresh()
