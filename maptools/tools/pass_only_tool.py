import math
from .base_tool import BaseTool
from .vector_tools import PolygonTool
from ..controllers.commands.annotation_command import AddAnnotationCommand

class PassOnlyTool(PolygonTool):
    name = "pass_only"
    cursor = "crosshair"

    def _update_preview(self, current_canvas_pos=None):
        self.canvas.delete("tool_preview")

        if not self.points:
            return

        # 每次从世界坐标实时转换，确保缩放后跟随
        draw_points = self._world_points_to_canvas()
        if current_canvas_pos:
            draw_points.append(current_canvas_pos)

        if len(draw_points) >= 2:
            self.canvas.create_line(draw_points, fill="#FFD700", width=2, tags="tool_preview") # Gold/Yellow color
            # 如果要封闭预览
            if len(draw_points) >= 3:
                 self.canvas.create_polygon(draw_points, outline="#FFD700", fill="", dash=(4, 4), tags="tool_preview")

        # 绘制已确定的点
        confirmed_canvas = self._world_points_to_canvas()
        for p in confirmed_canvas:
            self.canvas.create_oval(p[0]-3, p[1]-3, p[0]+3, p[1]+3, fill="#FFD700", tags="tool_preview")

    def finish(self):
        """完成绘制"""
        if len(self.points) >= 3:
            # points 已经是世界坐标，直接使用
            world_points = list(self.points)

            # 使用Command提交
            if self.canvas.annotations and self.controller and hasattr(self.controller, 'command_manager'):
                cmd = AddAnnotationCommand(
                    self.canvas.annotations,
                    'pass_only',
                    world_points,
                    refresh_cb=self.canvas.refresh
                )
                self.controller.command_manager.execute(cmd)
                print(f"Added pass only zone with {len(world_points)} points via Command")

        self.reset()
        self.canvas.refresh()
