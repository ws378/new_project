from tkinter import messagebox, simpledialog
from .vector_tools import PolygonTool
from ..controllers.commands.annotation_command import AddAnnotationCommand
from ..utils.room_identity import valid_area_room_ids


class AreaLabelTool(PolygonTool):
    name = "area_label"
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
            self.canvas.create_line(draw_points, fill="#4CAF50", width=2, tags="tool_preview")
            if len(draw_points) >= 3:
                self.canvas.create_polygon(draw_points, outline="#4CAF50", fill="", dash=(4, 4), tags="tool_preview")

        # 绘制已确定的点
        confirmed_canvas = self._world_points_to_canvas()
        for p in confirmed_canvas:
            self.canvas.create_oval(p[0]-3, p[1]-3, p[0]+3, p[1]+3, fill="#4CAF50", tags="tool_preview")

    def finish(self):
        """完成绘制"""
        if len(self.points) >= 3:
            room_id = simpledialog.askinteger("Area Label", "Enter Room ID:", parent=self.canvas, minvalue=1)
            if room_id is None:
                # User cancelled, discard polygon
                self.reset()
                self.canvas.refresh()
                return
            if self.canvas.annotations and int(room_id) in valid_area_room_ids(self.canvas.annotations.area_labels):
                messagebox.showerror("Area Label", f"Room ID {room_id} already exists")
                self.reset()
                self.canvas.refresh()
                return

            # points 已经是世界坐标，直接使用
            world_points = list(self.points)

            # Submit via Command
            if self.canvas.annotations and self.controller and hasattr(self.controller, 'command_manager'):
                cmd = AddAnnotationCommand(
                    self.canvas.annotations,
                    'area_label',
                    {'polygon': world_points, 'name': str(room_id), 'area_id': int(room_id)},
                    refresh_cb=self.canvas.refresh
                )
                self.controller.command_manager.execute(cmd)
                print(f"Added area room_id={room_id} with {len(world_points)} points via Command")

        self.reset()
        self.canvas.refresh()
