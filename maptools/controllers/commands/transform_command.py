from ..command_manager import Command
import copy
from PIL import Image

class TransformCommand(Command):
    """
    处理地图变换(旋转/原点平移)的撤销重做
    策略：保存变换前后的元数据和标注数据的深拷贝
    对于图像数据：
    - 如果是原点平移，图像不变，只存元数据
    - 如果是旋转，图像改变，需要保存图像快照 (内存开销较大，但操作频率低)
    """
    def __init__(self, map_data, annotations, before_state, after_state, refresh_cb=None):
        self.map_data = map_data
        self.annotations = annotations
        self.before_state = before_state
        self.after_state = after_state
        self.refresh_cb = refresh_cb

    @staticmethod
    def capture_state(map_data, annotations):
        """捕获当前状态快照"""
        state = {
            "origin": copy.deepcopy(map_data.metadata.origin),
            "width": map_data.width,
            "height": map_data.height,
            "base_image": map_data.base_image.copy() if map_data.base_image else None,
            "edit_layer": map_data.edit_layer.copy() if map_data.edit_layer is not None else None,
            "grid_map": map_data.grid_map.copy() if map_data.grid_map is not None else None,
            # Annotations state
            "constraint_segments": copy.deepcopy(annotations.constraint_segments),
            "stations": copy.deepcopy(annotations.stations),
            "area_labels": copy.deepcopy(annotations.area_labels),
            "_next_area_id": copy.deepcopy(annotations._next_area_id),
        }
        return state

    def _restore_state(self, state):
        # 1. Restore MapData
        self.map_data.metadata.origin = state["origin"]
        self.map_data.width = state["width"]
        self.map_data.height = state["height"]
        self.map_data.base_image = state["base_image"]
        self.map_data.edit_layer = state["edit_layer"]
        self.map_data.grid_map = state["grid_map"]
        self.map_data._display_dirty = True
        self.map_data._display_cache = None

        # 2. Restore Annotations
        self.annotations.constraint_segments = copy.deepcopy(state["constraint_segments"])
        self.annotations.sync_constraint_views()
        self.annotations.stations = copy.deepcopy(state["stations"])
        self.annotations.area_labels = copy.deepcopy(state["area_labels"])
        self.annotations._next_area_id = copy.deepcopy(state["_next_area_id"])

        if self.refresh_cb:
            self.refresh_cb()

    def execute(self):
        """Redo"""
        self._restore_state(self.after_state)

    def undo(self):
        """Undo"""
        self._restore_state(self.before_state)
