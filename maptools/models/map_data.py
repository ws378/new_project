import os
import yaml
import numpy as np
import cv2
import math
from PIL import Image
from dataclasses import dataclass
from typing import Tuple, Optional

ROTATE_INTERPOLATION_MODES = {
    "nearest": cv2.INTER_NEAREST,
    "smooth": cv2.INTER_LINEAR,
}

@dataclass
class MapMetadata:
    image_path: str
    resolution: float           # 米/像素
    origin: Tuple[float, float, float]  # [x, y, yaw]
    negate: int
    occupied_thresh: float
    free_thresh: float
    mode: str = "trinary"

class MapData:
    """管理地图数据"""

    def __init__(self):
        self.metadata: Optional[MapMetadata] = None
        self.base_image: Optional[Image.Image] = None  # PIL Image for display
        self.grid_map: Optional[np.ndarray] = None     # Numpy array for processing
        self.edit_layer: Optional[np.ndarray] = None   # Editing layer
        self.yaml_path: str = ""
        self.width: int = 0
        self.height: int = 0
        self.change_stamp: int = 0

        # Display image cache
        self._display_cache: Optional[Image.Image] = None
        self._display_dirty: bool = True

    def load(self, yaml_path: str) -> bool:
        """加载YAML和对应的图像文件"""
        if not os.path.exists(yaml_path):
            print(f"Error: YAML file not found: {yaml_path}")
            return False

        try:
            with open(yaml_path, 'r') as f:
                data = yaml.safe_load(f)

            # 解析元数据
            self.metadata = MapMetadata(
                image_path=data.get('image', ''),
                resolution=float(data.get('resolution', 0.05)),
                origin=tuple(data.get('origin', [0.0, 0.0, 0.0])),
                negate=int(data.get('negate', 0)),
                occupied_thresh=float(data.get('occupied_thresh', 0.65)),
                free_thresh=float(data.get('free_thresh', 0.25)),
                mode=data.get('mode', 'trinary')
            )
            self.yaml_path = yaml_path

            # 加载图像
            map_dir = os.path.dirname(yaml_path)
            image_abs_path = os.path.join(map_dir, self.metadata.image_path)

            if not os.path.exists(image_abs_path):
                if os.path.exists(self.metadata.image_path):
                    image_abs_path = self.metadata.image_path
                else:
                    print(f"Error: Image file not found: {image_abs_path}")
                    return False

            # 使用PIL加载图像
            self.base_image = Image.open(image_abs_path).convert('L') # 转为灰度
            self.width, self.height = self.base_image.size

            # 转为numpy数组用于后续处理
            self.grid_map = np.array(self.base_image)

            # 初始化编辑层 (255=未修改)
            self.edit_layer = np.full_like(self.grid_map, 255)
            self._display_dirty = True
            self._display_cache = None
            self.change_stamp += 1

            print(f"Map loaded: {self.width}x{self.height}, res={self.metadata.resolution}")
            return True

        except Exception as e:
            print(f"Error loading map: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_display_image(self) -> Image.Image:
        """获取用于显示的PIL图像 (合并Base + Edit), with caching"""
        if self.base_image is None:
            return None

        if self.edit_layer is None:
            return self.base_image

        if not self._display_dirty and self._display_cache is not None:
            return self._display_cache

        display_data = self.grid_map.copy()
        mask = self.edit_layer != 255
        display_data[mask] = self.edit_layer[mask]

        self._display_cache = Image.fromarray(display_data)
        self._display_dirty = False
        return self._display_cache

    def get_display_image_region(self, x0: int, y0: int, x1: int, y1: int) -> Image.Image:
        """获取指定区域的显示图像 (避免全图copy)"""
        if self.base_image is None:
            return None

        # Clamp to image bounds
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(self.width, x1)
        y1 = min(self.height, y1)

        if x1 <= x0 or y1 <= y0:
            return None

        region = self.grid_map[y0:y1, x0:x1].copy()
        if self.edit_layer is not None:
            edit_region = self.edit_layer[y0:y1, x0:x1]
            mask = edit_region != 255
            region[mask] = edit_region[mask]

        return Image.fromarray(region)

    def apply_brush(self, cx: int, cy: int, radius: int, value: int):
        """应用画笔"""
        if self.edit_layer is None:
            return
        self._display_dirty = True
        self.change_stamp += 1

        y, x = np.ogrid[-radius: radius+1, -radius: radius+1]
        mask = x*x + y*y <= radius*radius

        y_min = max(0, cy - radius)
        y_max = min(self.height, cy + radius + 1)
        x_min = max(0, cx - radius)
        x_max = min(self.width, cx + radius + 1)

        mask_y_min = max(0, -(cy - radius))
        mask_y_max = mask.shape[0] - max(0, (cy + radius + 1) - self.height)
        mask_x_min = max(0, -(cx - radius))
        mask_x_max = mask.shape[1] - max(0, (cx + radius + 1) - self.width)

        local_mask = mask[mask_y_min:mask_y_max, mask_x_min:mask_x_max]
        roi = self.edit_layer[y_min:y_max, x_min:x_max]
        roi[local_mask] = value

    def apply_line(self, x0: int, y0: int, x1: int, y1: int, radius: int, value: int):
        """沿直线绘制，使用圆形画笔"""
        if self.edit_layer is None:
            return
        self._display_dirty = True
        self.change_stamp += 1

        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        steps = max(dx, dy, 1)

        for i in range(steps + 1):
            t = i / steps
            cx = int(x0 + (x1 - x0) * t)
            cy = int(y0 + (y1 - y0) * t)
            self.apply_brush(cx, cy, radius, value)

    def crop(self, x0: int, y0: int, x1: int, y1: int) -> bool:
        """裁剪地图到给定像素矩形 [x0:x1, y0:y1)."""
        if self.base_image is None or self.grid_map is None or not self.metadata:
            return False

        x0 = max(0, min(int(x0), self.width))
        y0 = max(0, min(int(y0), self.height))
        x1 = max(0, min(int(x1), self.width))
        y1 = max(0, min(int(y1), self.height))

        if x1 <= x0 or y1 <= y0:
            return False

        old_height = self.height
        res = self.metadata.resolution
        old_origin_x, old_origin_y, old_yaw = self.metadata.origin

        cropped_base = self.grid_map[y0:y1, x0:x1].copy()
        cropped_edit = None
        if self.edit_layer is not None:
            cropped_edit = self.edit_layer[y0:y1, x0:x1].copy()

        self.base_image = Image.fromarray(cropped_base)
        self.grid_map = cropped_base
        self.edit_layer = cropped_edit
        self.width = x1 - x0
        self.height = y1 - y0
        self._display_dirty = True
        self._display_cache = None
        self.change_stamp += 1

        new_origin_x = old_origin_x + x0 * res
        new_origin_y = old_origin_y + (old_height - y1) * res
        self.metadata.origin = (new_origin_x, new_origin_y, old_yaw)
        return True

    def rotate(self, angle_deg: float, interpolation_mode: str = "nearest"):
        """旋转地图"""
        if self.base_image is None or not self.metadata:
            return

        interpolation_flag = ROTATE_INTERPOLATION_MODES.get(interpolation_mode, cv2.INTER_NEAREST)

        img_base = np.array(self.base_image)
        img_edit = None
        if self.edit_layer is not None:
            img_edit = self.edit_layer

        h, w = img_base.shape[:2]
        center = (w / 2, h / 2)

        M = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
        cos_val = np.abs(M[0, 0])
        sin_val = np.abs(M[0, 1])
        new_w = int((h * sin_val) + (w * cos_val))
        new_h = int((h * cos_val) + (w * sin_val))

        M[0, 2] += (new_w / 2) - center[0]
        M[1, 2] += (new_h / 2) - center[1]

        new_img_base = cv2.warpAffine(
            img_base,
            M,
            (new_w, new_h),
            flags=interpolation_flag,
            borderValue=205
        )

        new_img_edit = None
        if img_edit is not None:
            new_img_edit = cv2.warpAffine(img_edit, M, (new_w, new_h), borderValue=255, flags=cv2.INTER_NEAREST)

        # 更新 Origin
        res = self.metadata.resolution
        old_origin = self.metadata.origin

        cx_old = w / 2.0
        cy_old = h / 2.0

        center_wx = old_origin[0] + cx_old * res
        center_wy = old_origin[1] + (h - cy_old) * res

        cx_new = new_w / 2.0
        cy_new = new_h / 2.0

        new_origin_x = center_wx - cx_new * res
        new_origin_y = center_wy - (new_h - cy_new) * res

        self.base_image = Image.fromarray(new_img_base)
        self.grid_map = new_img_base
        self.edit_layer = new_img_edit
        self.width = new_w
        self.height = new_h
        self._display_dirty = True
        self._display_cache = None
        self.change_stamp += 1

        self.metadata.origin = (new_origin_x, new_origin_y, 0.0)
        print(f"Map rotated {angle_deg}°. New size: {new_w}x{new_h}.")

    def set_origin(self, wx: float, wy: float):
        """设置新的原点坐标"""
        if self.metadata:
            old_yaw = self.metadata.origin[2]
            self.metadata.origin = (wx, wy, old_yaw)

    def get_world_bounds(self) -> Optional[Tuple[float, float, float, float]]:
        """返回当前地图的世界坐标边界 (min_x, max_x, min_y, max_y)."""
        if not self.metadata:
            return None

        origin_x, origin_y, _ = self.metadata.origin
        res = self.metadata.resolution
        max_x = origin_x + self.width * res
        max_y = origin_y + self.height * res
        return origin_x, max_x, origin_y, max_y
