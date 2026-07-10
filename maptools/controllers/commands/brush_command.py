from ..command_manager import Command
import numpy as np

class BrushCommand(Command):
    """
    处理栅格编辑(画笔/橡皮擦)的撤销重做
    策略：只保存受影响区域的Bounding Box差异，而非整个编辑层副本
    """
    def __init__(self, map_data, before_layer, after_layer, refresh_cb=None):
        self.map_data = map_data
        self.refresh_cb = refresh_cb

        # 计算差异区域的bounding box，只存储变化的部分
        diff_mask = before_layer != after_layer
        if diff_mask.any():
            rows = np.any(diff_mask, axis=1)
            cols = np.any(diff_mask, axis=0)
            y_min, y_max = np.where(rows)[0][[0, -1]]
            x_min, x_max = np.where(cols)[0][[0, -1]]
            # 存储bounding box坐标和区域数据
            self.bbox = (int(y_min), int(y_max) + 1, int(x_min), int(x_max) + 1)
            self.before_region = before_layer[y_min:y_max+1, x_min:x_max+1].copy()
            self.after_region = after_layer[y_min:y_max+1, x_min:x_max+1].copy()
        else:
            self.bbox = None
            self.before_region = None
            self.after_region = None

    def execute(self):
        """Redo"""
        if self.bbox is not None and self.after_region is not None:
            y0, y1, x0, x1 = self.bbox
            self.map_data.edit_layer[y0:y1, x0:x1] = self.after_region.copy()
            self.map_data._display_dirty = True
            if self.refresh_cb:
                self.refresh_cb()

    def undo(self):
        """Undo"""
        if self.bbox is not None and self.before_region is not None:
            y0, y1, x0, x1 = self.bbox
            self.map_data.edit_layer[y0:y1, x0:x1] = self.before_region.copy()
            self.map_data._display_dirty = True
            if self.refresh_cb:
                self.refresh_cb()
