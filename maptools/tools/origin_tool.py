from .base_tool import BaseTool
from ..controllers.commands.transform_command import TransformCommand

class OriginTool(BaseTool):
    name = "origin"
    cursor = "target"

    def __init__(self, canvas, controller):
        super().__init__(canvas, controller)

    def on_press(self, event):
        # 捕获状态
        mgr = self.canvas.coverage_path_manager
        path_nodes = list(mgr.nodes) if mgr else None
        before_state = TransformCommand.capture_state(self.canvas.map_data, self.canvas.annotations, path_nodes)

        # 获取点击点的世界坐标
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        wx, wy = self.canvas.coord_transformer.canvas_to_world(cx, cy)

        # 设置新原点
        # 逻辑：我们将点击点设为新的 (0,0)
        # 这意味着原来的 (0,0) 现在的坐标变成了 (-wx, -wy)
        # MapData.origin 存储的是 "map origin in world coords".
        # If we want clicked point P(wx, wy) to be new (0,0).
        # It means we shift the whole world so that P becomes 0.
        # Actually, in ROS map, 'origin' is the world pose of the (0,0) pixel.
        # So if we change origin, we change the coordinate system.

        # Let's say we want the point under mouse to be (0,0).
        # Current world pos of mouse: P_old.
        # We want P_new = (0,0).
        # This implies a translation of -P_old.
        # So new_origin = old_origin - P_old ? No.

        # Correct logic:
        # pixel P corresponds to world W_old.
        # We want pixel P to correspond to world (0,0).
        # Formula: W = origin + P * res
        # We want: 0 = new_origin + P * res
        # So: new_origin = - P * res
        #
        # Let's calculate P first.
        px, py = self.canvas.coord_transformer.canvas_to_pixel(cx, cy)

        # ROS Origin logic:
        # origin_x = world_x_of_pixel_0
        # world_x_of_pixel_P = origin_x + P * res
        # We want world_x_of_pixel_P = 0
        # 0 = new_origin_x + P * res
        # new_origin_x = - P * res

        # Y axis (ROS y up, image y down):
        # world_y = origin_y + (height - py) * res
        # 0 = new_origin_y + (height - py) * res
        # new_origin_y = - (height - py) * res

        res = self.canvas.map_data.metadata.resolution
        h = self.canvas.map_data.height

        new_ox = - px * res
        new_oy = - (h - py) * res

        # Update MapData
        self.canvas.map_data.set_origin(new_ox, new_oy)

        # Update Annotations
        # All existing annotations are defined in OLD world frame.
        # We just CHANGED the world frame definition (origin).
        # So the physical location of annotations relative to the map image SHOULD NOT CHANGE.
        # BUT, their coordinate values MUST CHANGE because the coordinate system changed.

        # Wait, Annotations store coordinates.
        # If we change the map origin, the grid stays same, but the coordinate system shifts.
        # A point at pixel (100,100) was (x1, y1). Now it is (x2, y2).
        # The annotation at pixel (100,100) should now have coord (x2, y2).
        #
        # Shift delta = new_origin - old_origin.
        # new_coord = old_coord + delta?
        # Let's see:
        # W_old = origin_old + offset
        # W_new = origin_new + offset
        # So W_new - W_old = origin_new - origin_old
        # W_new = W_old + (origin_new - origin_old)

        old_ox, old_oy, _ = before_state["origin"]
        dx = new_ox - old_ox
        dy = new_oy - old_oy

        # Update all annotations by adding (dx, dy)
        self._shift_annotations(dx, dy)

        # Capture after state
        after_state = TransformCommand.capture_state(self.canvas.map_data, self.canvas.annotations, path_nodes)

        # Submit command
        if self.controller and hasattr(self.controller, 'command_manager'):
            cmd = TransformCommand(
                self.canvas.map_data,
                self.canvas.annotations,
                before_state,
                after_state,
                refresh_cb=self.canvas.refresh,
                path_manager=mgr,
            )
            self.controller.command_manager.execute(cmd)

        self.canvas.refresh()
        print(f"Set new origin at pixel ({px}, {py}). New Origin: ({new_ox:.2f}, {new_oy:.2f})")

        # Switch back to pan tool after setting
        if self.controller and hasattr(self.controller, 'tool_manager'):
            self.controller.tool_manager.set_tool("pan")

    def _shift_annotations(self, dx, dy):
        """Shift all annotations by (dx, dy)"""
        anns = self.canvas.annotations

        for z in anns.forbidden_zones:
            z.polygon = [(x+dx, y+dy) for x, y in z.polygon]

        for w in anns.virtual_walls:
            w.start = (w.start[0]+dx, w.start[1]+dy)
            w.end = (w.end[0]+dx, w.end[1]+dy)

        for s in anns.stations:
            s.position = (s.position[0]+dx, s.position[1]+dy)

        # Shift coverage path nodes (world coords)
        mgr = self.canvas.coverage_path_manager
        if mgr and mgr.nodes:
            res = self.canvas.map_data.metadata.resolution
            new_ox, new_oy, _ = self.canvas.map_data.metadata.origin
            map_h = self.canvas.map_data.height
            for p in mgr.nodes:
                p.x += dx
                p.y += dy
                p.u = (p.x - new_ox) / res
                p.v = map_h - (p.y - new_oy) / res
            mgr.rebuild_spatial()

        # Shift area labels
        for area in anns.area_labels:
            if area.polygon:
                area.polygon = [(x+dx, y+dy) for x, y in area.polygon]
