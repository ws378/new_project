import math
import tkinter as tk
from typing import Optional, List, Tuple
from .base_tool import BaseTool
from ..models.coverage_path import CoveragePathNode, point_in_polygon, resample_polyline, make_path_nodes
from ..controllers.commands.path_command import PathSnapshotCommand
from ..utils.room_identity import area_room_id, valid_area_room_ids


def _update_path_selection_status(controller, point):
    if not controller:
        return
    statusbar = getattr(controller, 'statusbar_left', None)
    if not statusbar and hasattr(controller, 'winfo_toplevel'):
        top = controller.winfo_toplevel()
        statusbar = getattr(top, 'statusbar_left', None)
    if statusbar is None or point is None:
        return
    statusbar.config(
        text=(
            f"Path point selected: room={point.room}, path_id={point.id}, "
            f"world=({point.x:.3f}, {point.y:.3f}), pixel=({point.u:.1f}, {point.v:.1f})"
        )
    )


def _path_panel(controller):
    sidebar = getattr(controller, "sidebar", None)
    return getattr(sidebar, "path_panel", None)


def _area_id_at_world_point(canvas, wx: float, wy: float) -> Optional[int]:
    annotations = getattr(canvas, "annotations", None)
    if not annotations or not getattr(annotations, "area_labels", None):
        return None
    for area in sorted(annotations.area_labels, key=area_room_id):
        if area.polygon and point_in_polygon((wx, wy), area.polygon):
            return area_room_id(area)
    return None


def _selected_area_room_id(canvas) -> Optional[int]:
    if getattr(canvas, "selected_type", None) != "area_labels":
        return None
    selected = getattr(canvas, "selected_item", None)
    if selected is None:
        return None
    return area_room_id(selected)


def _valid_manual_room_id(canvas, room_id: int) -> Optional[int]:
    room_id = int(room_id)
    if room_id <= 0:
        return None
    annotations = getattr(canvas, "annotations", None)
    if not annotations:
        return None
    if room_id not in valid_area_room_ids(getattr(annotations, "area_labels", [])):
        return None
    return room_id


def _notify_room_inference_failed(controller) -> None:
    statusbar = getattr(controller, "statusbar_left", None)
    if statusbar is None and hasattr(controller, "winfo_toplevel"):
        statusbar = getattr(controller.winfo_toplevel(), "statusbar_left", None)
    if statusbar is not None:
        statusbar.config(
            text="Path drawing cancelled: no valid Room ID was inferred from selected area, geometry, or Room ID field."
        )


def _infer_room_from_sampled_world_points(
    canvas,
    sampled_world: List[Tuple[float, float]],
    fallback_room: int,
) -> int:
    selected_room_id = _selected_area_room_id(canvas)
    if selected_room_id is not None:
        return selected_room_id

    area_hits = {}
    for wx, wy in sampled_world:
        area_id = _area_id_at_world_point(canvas, wx, wy)
        if area_id is None:
            continue
        area_hits[area_id] = area_hits.get(area_id, 0) + 1

    if not area_hits:
        return _valid_manual_room_id(canvas, int(fallback_room)) or 0
    return min(area_hits.items(), key=lambda item: (-item[1], item[0]))[0]



class PathSelectTool(BaseTool):
    """
    单选/多选路径点，并支持拖拽移动选中点。
    """
    name = "path_select"
    cursor = "arrow"

    def __init__(self, canvas, controller):
        super().__init__(canvas, controller)
        self.drag_start_canvas: Optional[Tuple[float, float]] = None
        self.is_dragging = False
        self.drag_point_id: Optional[int] = None

    def on_press(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        manager = self.canvas.coverage_path_manager
        
        if not manager or not manager.nodes:
            self.drag_point_id = None
            return

        # 转换为图像像素坐标
        u, v = self.canvas.canvas_to_image(cx, cy)
        
        # 屏幕容差转换为像素级容差
        px_tol = 10.0 / max(0.1, self.canvas.zoom_level)

        # 空间查询
        candidates = manager.spatial.query_nearby(u, v, px_tol + 50) # 50 is SPATIAL_GRID_CELL
        
        best_pid = None
        best_dist = float('inf')

        # 精确的 Canvas 投影距离检测
        for p in candidates:
            pcx, pcy = self.canvas.image_to_canvas(p.u, p.v)
            dist = math.hypot(cx - pcx, cy - pcy)
            if dist <= 10.0 and dist < best_dist:  # 10.0 pixels tolerance on screen
                best_pid = p.id
                best_dist = dist

        if best_pid is not None:
            if best_pid in manager.selection:
                # 点击了已选中的点，准备拖拽全部选中点
                self.drag_point_id = best_pid
            else:
                # 重新单选
                manager.selection = {best_pid}
                self.drag_point_id = best_pid
                
            panel = _path_panel(self.controller)
            if panel is not None and hasattr(panel, "populate_form"):
                panel.populate_form(best_pid)
            _update_path_selection_status(self.controller, manager.nodes[best_pid])
            self.canvas.refresh()
        else:
            # 点击空白处，取消选择
            if manager.selection:
                manager.selection.clear()
                self.canvas.refresh()
            self.drag_point_id = None

        self.drag_start_canvas = (cx, cy)
        self.is_dragging = True

    def on_drag(self, event):
        if not self.is_dragging or self.drag_point_id is None or not self.drag_start_canvas:
            return

        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        
        manager = self.canvas.coverage_path_manager
        if not manager:
            return

        # 推入 undo 快照 (只在开始拖拽的第一帧推入一次)
        if not hasattr(self, '_drag_undo_pushed'):
            self._old_nodes_snapshot = manager.duplicate_nodes()
            self._drag_undo_pushed = True

        # 计算增量
        dx_canvas = cx - self.drag_start_canvas[0]
        dy_canvas = cy - self.drag_start_canvas[1]
        
        if abs(dx_canvas) < 0.1 and abs(dy_canvas) < 0.1:
            return

        # Canvas 位移 -> 世界位移
        if not self.canvas.coord_transformer:
            return

        # Note: canvas_to_world gives (wx, wy), but we need the delta
        # Since transformations might include origin shifts, calculate worlds explicitly
        wx1, wy1 = self.canvas.coord_transformer.canvas_to_world(*self.drag_start_canvas)
        wx2, wy2 = self.canvas.coord_transformer.canvas_to_world(cx, cy)
        
        dwx = wx2 - wx1
        dwy = wy2 - wy1

        for pid in manager.selection:
            if 0 <= pid < len(manager.nodes):
                p = manager.nodes[pid]
                p.x += dwx
                p.y += dwy
                # 重算 UV
                res = self.canvas.map_data.metadata.resolution
                origin_x, origin_y, _ = self.canvas.map_data.metadata.origin
                map_height = self.canvas.map_data.height
                
                p.u = (p.x - origin_x) / res
                p.v = map_height - (p.y - origin_y) / res

        self.drag_start_canvas = (cx, cy)
        
        # 拖拽时只重绘覆盖路径，避免重绘底图导致卡顿
        # 这里为了简化，先调用完整 refresh，如果是瓶颈再优化
        manager.rebuild_spatial()
        self.canvas.refresh()

        if len(manager.selection) == 1:
            panel = _path_panel(self.controller)
            if panel is not None and hasattr(panel, "populate_form"):
                panel.populate_form(next(iter(manager.selection)))
            _update_path_selection_status(self.controller, manager.nodes[next(iter(manager.selection))])
            _update_path_selection_status(self.controller, manager.nodes[next(iter(manager.selection))])

    def on_release(self, event):
        self.is_dragging = False
        self.drag_point_id = None
        self.drag_start_canvas = None
        
        if hasattr(self, '_drag_undo_pushed'):
            manager = self.canvas.coverage_path_manager
            if manager:
                manager.renumber_nodes() # Update distances based on new coords
                
                # Push the command
                if self.controller and hasattr(self.controller, 'command_manager'):
                    new_nodes_snapshot = manager.duplicate_nodes()
                    cmd = PathSnapshotCommand(
                        manager,
                        self._old_nodes_snapshot,
                        new_nodes_snapshot,
                        refresh_cb=self.canvas.refresh
                    )
                    # Skip execute() since we already manipulated the nodes live
                    self.controller.command_manager.execute(cmd)
                    
                self.canvas.refresh()
            del self._drag_undo_pushed
            del self._old_nodes_snapshot

    def on_key_press(self, event):
        if event.keysym not in ('Delete', 'BackSpace'):
            return

        manager = self.canvas.coverage_path_manager
        if not manager or not manager.selection:
            return

        old_nodes_snapshot = manager.duplicate_nodes()
        manager.nodes = [p for p in manager.nodes if p.id not in manager.selection]
        manager.selection.clear()
        manager.renumber_nodes()

        if self.controller and hasattr(self.controller, 'command_manager'):
            cmd = PathSnapshotCommand(
                manager,
                old_nodes_snapshot,
                manager.duplicate_nodes(),
                refresh_cb=self.canvas.refresh
            )
            self.controller.command_manager.execute(cmd)

        self.canvas.refresh()
        panel = _path_panel(self.controller)
        if panel is not None and hasattr(panel, "refresh_info"):
            panel.refresh_info()


class PathPolygonSelectTool(BaseTool):
    """
    多边形框选路径点
    """
    name = "path_polygon"
    cursor = "crosshair"

    def __init__(self, canvas, controller):
        super().__init__(canvas, controller)
        self.polygon_vertices_canvas: List[Tuple[float, float]] = []

    def on_press(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        self.polygon_vertices_canvas.append((cx, cy))
        self._update_preview()

    def on_move(self, event):
        if not self.polygon_vertices_canvas:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        self._update_preview(current_canvas_pos=(cx, cy))

    def _update_preview(self, current_canvas_pos=None):
        self.canvas.delete("tool_preview")
        if not self.polygon_vertices_canvas:
            return

        draw_points = list(self.polygon_vertices_canvas)
        if current_canvas_pos:
            draw_points.append(current_canvas_pos)

        if len(draw_points) >= 2:
            self.canvas.create_line(draw_points, fill="cyan", width=2, dash=(4,4), tags="tool_preview")
            if len(draw_points) >= 3:
                self.canvas.create_polygon(draw_points, outline="cyan", fill="", dash=(4, 4), tags="tool_preview")

        for p in self.polygon_vertices_canvas:
            self.canvas.create_oval(p[0]-3, p[1]-3, p[0]+3, p[1]+3, fill="cyan", tags="tool_preview")

    def on_double_click(self, event):
        self._finalize_selection()

    def _finalize_selection(self):
        manager = self.canvas.coverage_path_manager
        if not manager or len(self.polygon_vertices_canvas) < 3:
            self.reset()
            return

        selected = []
        for p in manager.nodes:
            # 投影到 Canvas 进行匹配
            pcx, pcy = self.canvas.image_to_canvas(p.u, p.v)
            if point_in_polygon((pcx, pcy), self.polygon_vertices_canvas):
                selected.append(p.id)

        manager.selection = set(selected)
        self.reset()
        self.canvas.refresh()
        
        if len(manager.selection) == 1:
            panel = _path_panel(self.controller)
            if panel is not None and hasattr(panel, "populate_form"):
                panel.populate_form(next(iter(manager.selection)))
        elif len(manager.selection) > 1:
            panel = _path_panel(self.controller)
            if panel is not None and hasattr(panel, "refresh_info"):
                panel.refresh_info()

    def on_key_press(self, event):
        if event.keysym in ('Escape', 'Return'):
            if event.keysym == 'Return':
                self._finalize_selection()
            else:
                self.reset()
                self.canvas.refresh()

    def reset(self):
        self.polygon_vertices_canvas.clear()
        self.canvas.delete("tool_preview")


class PathAddTool(BaseTool):
    """
    点击添加单个路径点。如果选中了某个点，则插在选中点之后，并继承其 room/segment。
    否则添加到路径末尾。
    """
    name = "path_add"
    cursor = "crosshair"

    def on_press(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        manager = self.canvas.coverage_path_manager
        
        if not manager or not self.canvas.coord_transformer:
            return

        u, v = self.canvas.canvas_to_image(cx, cy)
        wx, wy = self.canvas.coord_transformer.canvas_to_world(cx, cy)
        
        room = 0
        segment = 0
        yaw = 0.0
        insert_idx = len(manager.nodes)
        
        if manager.selection:
            pid = min(manager.selection)
            insert_idx = pid + 1
            ref = manager.nodes[pid]
            room, segment, yaw = ref.room, ref.segment, ref.yaw
        else:
            area_id = _area_id_at_world_point(self.canvas, wx, wy)
            if area_id is not None:
                room = area_id
            panel = _path_panel(self.controller)
            if panel is not None:
                if room == 0 and hasattr(panel, "get_draw_room"):
                    room = _valid_manual_room_id(self.canvas, panel.get_draw_room()) or 0
                if hasattr(panel, "get_draw_segment"):
                    segment = panel.get_draw_segment()
        if room == 0:
            _notify_room_inference_failed(self.controller)
            return
            
        old_nodes_snapshot = manager.duplicate_nodes()
        
        new_node = CoveragePathNode(
            id=insert_idx, room=room, segment=segment,
            x=wx, y=wy, yaw=yaw, u=u, v=v,
            acc_dist=0.0, room_dist=0.0, seg_dist=0.0
        )
        
        manager.nodes.insert(insert_idx, new_node)
        manager.renumber_nodes()
        manager.selection = {insert_idx}
        
        if self.controller and hasattr(self.controller, 'command_manager'):
            cmd = PathSnapshotCommand(
                manager,
                old_nodes_snapshot,
                manager.duplicate_nodes(),
                refresh_cb=self.canvas.refresh
            )
            self.controller.command_manager.execute(cmd)
        
        panel = _path_panel(self.controller)
        if panel is not None and hasattr(panel, "populate_form"):
            panel.populate_form(insert_idx)
        _update_path_selection_status(self.controller, manager.nodes[insert_idx])
        self.canvas.refresh()


class PathDrawTool(BaseTool):
    """
    鼠标拖拽手绘路径，松开后基于指定 interval 等距重采样。
    """
    name = "path_draw"
    cursor = "pencil"

    def __init__(self, canvas, controller):
        super().__init__(canvas, controller)
        self.raw_points_canvas: List[Tuple[float, float]] = []
        self.is_drawing = False

    def on_press(self, event):
        self.is_drawing = True
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        self.raw_points_canvas = [(cx, cy)]
        
    def on_drag(self, event):
        if not self.is_drawing:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        self.raw_points_canvas.append((cx, cy))
        
        # 实时绘制预览线段
        if len(self.raw_points_canvas) >= 2:
            p1 = self.raw_points_canvas[-2]
            p2 = self.raw_points_canvas[-1]
            self.canvas.create_line(p1[0], p1[1], p2[0], p2[1], fill="magenta", width=2, tags="tool_preview")

    def on_release(self, event):
        if not self.is_drawing:
            return
        self.is_drawing = False
        manager = self.canvas.coverage_path_manager
        
        if not manager or not self.canvas.coord_transformer or len(self.raw_points_canvas) < 2:
            self.reset()
            return
            
        # 从 UI 获取参数 (Phase 5 将实现 Sidebar 面板)
        # 这里先提供默认值兜底
        interval = 0.5
        room = 0
        segment = 0
        
        panel = _path_panel(self.controller)
        if panel is not None:
            if hasattr(panel, "get_draw_interval"):
                interval = panel.get_draw_interval()
            if hasattr(panel, "get_draw_room"):
                room = panel.get_draw_room()
            if hasattr(panel, "get_draw_segment"):
                segment = panel.get_draw_segment()

        # Canvas坐标 -> 世界坐标
        world_pts = []
        for cx, cy in self.raw_points_canvas:
            wx, wy = self.canvas.coord_transformer.canvas_to_world(cx, cy)
            world_pts.append((wx, wy))
            
        # 重采样
        sampled = resample_polyline(world_pts, interval)
        if not sampled:
            self.reset()
            return
        room = _infer_room_from_sampled_world_points(self.canvas, sampled, room)
        if room == 0:
            _notify_room_inference_failed(self.controller)
            self.reset()
            return

        # 转换为节点
        new_nodes = make_path_nodes(sampled, room, segment, self.canvas.map_data)
        
        # 插入到管理器
        old_nodes_snapshot = manager.duplicate_nodes()
        
        insert_idx = len(manager.nodes)
        if manager.selection:
            insert_idx = max(manager.selection) + 1
            
        for node in new_nodes:
            manager.nodes.insert(insert_idx, node)
            insert_idx += 1
            
        manager.renumber_nodes()
        # 选中新加的最后一个点
        manager.selection = {insert_idx - 1}
        
        if self.controller and hasattr(self.controller, 'command_manager'):
            cmd = PathSnapshotCommand(
                manager,
                old_nodes_snapshot,
                manager.duplicate_nodes(),
                refresh_cb=self.canvas.refresh
            )
            self.controller.command_manager.execute(cmd)
        
        self.reset()
        self.canvas.refresh()

    def reset(self):
        self.is_drawing = False
        self.raw_points_canvas.clear()
        self.canvas.delete("tool_preview")
        
    def on_key_press(self, event):
        if event.keysym == 'Escape':
            self.reset()
            self.canvas.refresh()


class PathLineTool(BaseTool):
    """
    多次点击绘制多段直线，双击最后一点结束，随后在整个折线段上应用等距重采样。
    """
    name = "path_line"
    cursor = "crosshair"

    def __init__(self, canvas, controller):
        super().__init__(canvas, controller)
        self.vertices_canvas: List[Tuple[float, float]] = []

    def on_press(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        self.vertices_canvas.append((cx, cy))
        self._update_preview()

    def on_move(self, event):
        if not self.vertices_canvas:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        self._update_preview(current_canvas_pos=(cx, cy))

    def _update_preview(self, current_canvas_pos=None):
        self.canvas.delete("tool_preview")
        if not self.vertices_canvas:
            return

        draw_points = list(self.vertices_canvas)
        if current_canvas_pos:
            draw_points.append(current_canvas_pos)

        if len(draw_points) >= 2:
            self.canvas.create_line(draw_points, fill="orange", width=2, tags="tool_preview")
            
        for p in self.vertices_canvas:
            self.canvas.create_oval(p[0]-3, p[1]-3, p[0]+3, p[1]+3, fill="orange", tags="tool_preview")

    def on_double_click(self, event):
        # on_press always fires before double click, so the last point is already added
        self._finalize_line()

    def _finalize_line(self):
        manager = self.canvas.coverage_path_manager
        if not manager or not self.canvas.coord_transformer or len(self.vertices_canvas) < 2:
            self.reset()
            return
            
        interval = 0.5
        room = 0
        segment = 0
        
        panel = _path_panel(self.controller)
        if panel is not None:
            if hasattr(panel, "get_draw_interval"):
                interval = panel.get_draw_interval()
            if hasattr(panel, "get_draw_room"):
                room = panel.get_draw_room()
            if hasattr(panel, "get_draw_segment"):
                segment = panel.get_draw_segment()

        world_pts = []
        for cx, cy in self.vertices_canvas:
            wx, wy = self.canvas.coord_transformer.canvas_to_world(cx, cy)
            world_pts.append((wx, wy))
            
        sampled = resample_polyline(world_pts, interval)
        if not sampled:
            self.reset()
            return
        room = _infer_room_from_sampled_world_points(self.canvas, sampled, room)
        if room == 0:
            _notify_room_inference_failed(self.controller)
            self.reset()
            return

        new_nodes = make_path_nodes(sampled, room, segment, self.canvas.map_data)
        
        old_nodes_snapshot = manager.duplicate_nodes()
        
        insert_idx = len(manager.nodes)
        if manager.selection:
            insert_idx = max(manager.selection) + 1
            
        for node in new_nodes:
            manager.nodes.insert(insert_idx, node)
            insert_idx += 1
            
        manager.renumber_nodes()
        manager.selection = {insert_idx - 1}
        
        if self.controller and hasattr(self.controller, 'command_manager'):
            cmd = PathSnapshotCommand(
                manager,
                old_nodes_snapshot,
                manager.duplicate_nodes(),
                refresh_cb=self.canvas.refresh
            )
            self.controller.command_manager.execute(cmd)
        
        self.reset()
        self.canvas.refresh()

    def on_key_press(self, event):
        if event.keysym in ('Escape', 'Return'):
            if event.keysym == 'Return':
                self._finalize_line()
            else:
                self.reset()
                self.canvas.refresh()

    def reset(self):
        self.vertices_canvas.clear()
        self.canvas.delete("tool_preview")
