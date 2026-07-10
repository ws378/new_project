import math
import copy
from .base_tool import BaseTool
from ..controllers.commands.update_annotation_command import UpdateAnnotationCommand
from ..controllers.commands.delete_annotation_command import DeleteAnnotationCommand
from ..utils.room_identity import area_room_id

class SelectTool(BaseTool):
    """
    选择工具：允许点击选中、整体拖动、顶点编辑以及删除各种矢量标注
    """
    name = "select"
    cursor = "arrow"

    def __init__(self, canvas, controller):
        super().__init__(canvas, controller)
        self.mode = 'idle' # 'idle', 'moving_item', 'editing_vertex'
        self.active_vertex_idx = -1
        
        # 拖拽相关
        self.drag_start_world = None
        self.original_state = None

    def activate(self):
        super().activate()
        # Ensure we have focus to capture keypresses
        self.canvas.focus_set()

    def deactivate(self):
        self._clear_selection()
        super().deactivate()

    def on_press(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        additive = bool(getattr(event, "state", 0) & 0x0001 or getattr(event, "state", 0) & 0x0004)
        
        # 1. 如果已有选中对象，先尝试判定是否点中了它的顶点控制柄
        if self.canvas.selected_item and not additive:
            hit_vertex = self._hit_test_vertex(cx, cy)
            if hit_vertex != -1:
                self.mode = 'editing_vertex'
                self.active_vertex_idx = hit_vertex
                self._record_original_state()
                return

        # 2. 否则，执行全局碰撞检测，看看点中了哪个大对象
        hit_item, hit_type = self.canvas.hit_test_all(cx, cy)
        
        if hit_item:
            if additive and hit_type == "constraint_segments":
                selected = {
                    str(segment.id)
                    for segment in self.canvas.get_selected_constraint_segments()
                }
                if str(hit_item.id) in selected:
                    selected.remove(str(hit_item.id))
                else:
                    selected.add(str(hit_item.id))
                self.canvas.selected_item = hit_item
                self.canvas.selected_type = hit_type
                self.canvas.selected_constraint_segment_ids = selected
                self.mode = 'idle'
                self.drag_start_world = None
                self.original_state = None
                self.canvas.refresh()
                return
            # 选中新对象 (或者再次点中原对象准备移动)
            if self.canvas.selected_item != hit_item:
                self.canvas.selected_item = hit_item
                self.canvas.selected_type = hit_type
            self._sync_selected_area_room_to_panel(hit_item, hit_type)
            if hit_type == "constraint_segments":
                self.canvas.selected_constraint_segment_ids = {str(hit_item.id)}
            else:
                self.canvas.selected_constraint_segment_ids = set()
                
            self.mode = 'moving_item'
            if self.canvas.coord_transformer:
                self.drag_start_world = self.canvas.coord_transformer.canvas_to_world(cx, cy)
            self._record_original_state()
            self.canvas.focus_set() # request focus for Delete key
        else:
            # 点空了，取消选择
            self._clear_selection()
            
        self.canvas.refresh()

    def _sync_selected_area_room_to_panel(self, hit_item, hit_type):
        if hit_type != "area_labels":
            return
        sidebar = getattr(self.controller, "sidebar", None)
        path_panel = getattr(sidebar, "path_panel", None)
        if path_panel is not None and hasattr(path_panel, "set_draw_room"):
            path_panel.set_draw_room(area_room_id(hit_item))

    def on_drag(self, event):
        if self.mode == 'idle' or not self.canvas.selected_item:
            return

        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        if not self.canvas.coord_transformer:
            return
            
        wx, wy = self.canvas.coord_transformer.canvas_to_world(cx, cy)

        if self.mode == 'editing_vertex':
            # 只修改被拖拽的那一个顶点
            self._update_vertex_position(wx, wy)
            
        elif self.mode == 'moving_item':
            # 整体平移
            if self.drag_start_world and self.original_state:
                dx = wx - self.drag_start_world[0]
                dy = wy - self.drag_start_world[1]
                self._translate_item(dx, dy)
                
        self.canvas.refresh()

    def on_release(self, event):
        if self.mode in ('editing_vertex', 'moving_item') and self.canvas.selected_item:
            # 创建命令以支持撤销
            cmd = UpdateAnnotationCommand(
                self.canvas.selected_item,
                self.original_state,
                self._get_current_state(),
                refresh_cb=self.canvas.refresh,
                annotations=self.canvas.annotations,
            )
            # Only execute if something actually changed
            if str(self.original_state) != str(self._get_current_state()):
                if self.controller and hasattr(self.controller, 'command_manager'):
                    self.controller.command_manager.execute(cmd)
            
        self.mode = 'idle'
        self.active_vertex_idx = -1
        self.drag_start_world = None
        self.original_state = None

    def on_key_press(self, event):
        """处理快捷键 (如 Delete)"""
        # Delete on Win/Linux is often keysym 'Delete', Mac is 'BackSpace' or 'Delete'
        if event.keysym in ('Delete', 'BackSpace') and self.canvas.selected_item:
            item = self.canvas.selected_item
            item_type = self.canvas.selected_type
            
            # 使用Command删除
            if self.controller and hasattr(self.controller, 'command_manager') and self.canvas.annotations:
                cmd = DeleteAnnotationCommand(
                    self.canvas.annotations,
                    item_type,
                    item,
                    refresh_cb=lambda: (self._clear_selection(), self.canvas.refresh())
                )
                self.controller.command_manager.execute(cmd)

    def _clear_selection(self):
        self.canvas.selected_item = None
        self.canvas.selected_type = None
        self.canvas.selected_constraint_segment_ids = set()
        self.mode = 'idle'
        self.canvas.refresh()

    def _hit_test_vertex(self, cx, cy, tolerance=8):
        """检测坐标 (cx, cy) 是否在大约 tolerance 像素距离内击中了选区的某个顶点"""
        item = self.canvas.selected_item
        if not item or not self.canvas.coord_transformer:
            return -1

        pts = self._get_item_points_world(item)
        for i, (wx, wy) in enumerate(pts):
            px, py = self.canvas.coord_transformer.world_to_canvas(wx, wy)
            if math.hypot(cx - px, cy - py) <= tolerance:
                return i
        return -1

    def _get_item_points_world(self, item):
        """把对象的顶点统一提取为世界坐标列表返回"""
        if hasattr(item, 'polygon'):
            return item.polygon
        elif hasattr(item, 'points'):
            return item.points
        elif hasattr(item, 'start') and hasattr(item, 'end'):
            return [item.start, item.end]
        elif hasattr(item, 'position'):
            return [item.position] # 只有一个中心点
        return []

    def _record_original_state(self):
        """记录拖拽前的顶点状态"""
        self.original_state = copy.deepcopy(self._get_current_state())

    def _get_current_state(self):
        item = self.canvas.selected_item
        if hasattr(item, 'polygon'):
            return item.polygon
        elif hasattr(item, 'points'):
            return item.points
        elif hasattr(item, 'start') and hasattr(item, 'end'):
            return (item.start, item.end)
        elif hasattr(item, 'position'):
            return (item.position, item.orientation)
        return None

    def _update_vertex_position(self, wx, wy):
        """修改指定顶点的世界坐标"""
        item = self.canvas.selected_item
        idx = self.active_vertex_idx
        if hasattr(item, 'polygon'):
            item.polygon[idx] = (wx, wy)
        elif hasattr(item, 'points'):
            item.points[idx] = (wx, wy)
        elif hasattr(item, 'start') and hasattr(item, 'end'):
            if idx == 0:
                item.start = (wx, wy)
            else:
                item.end = (wx, wy)
        elif hasattr(item, 'position'):
             item.position = (wx, wy)
             
    def _translate_item(self, dx, dy):
        """整体平移"""
        item = self.canvas.selected_item
        if hasattr(item, 'polygon'):
            new_poly = []
            for (ox, oy) in self.original_state:
                new_poly.append((ox + dx, oy + dy))
            item.polygon = new_poly
        elif hasattr(item, 'points'):
            new_points = []
            for (ox, oy) in self.original_state:
                new_points.append((ox + dx, oy + dy))
            item.points = new_points
        elif hasattr(item, 'start') and hasattr(item, 'end'):
            s_wx, s_wy = self.original_state[0]
            e_wx, e_wy = self.original_state[1]
            item.start = (s_wx + dx, s_wy + dy)
            item.end = (e_wx + dx, e_wy + dy)
        elif hasattr(item, 'position'):
             p_wx, p_wy = self.original_state[0]
             item.position = (p_wx + dx, p_wy + dy)
