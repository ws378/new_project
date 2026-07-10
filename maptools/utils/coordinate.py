from typing import Tuple
import math

class CoordinateTransformer:
    """
    坐标转换工具类
    负责 Screen (屏幕) <-> Canvas (画布) <-> Pixel (图像像素) <-> World (物理世界) 之间的转换
    """
    def __init__(self, map_data, canvas):
        self.map_data = map_data
        self.canvas = canvas

    def screen_to_canvas(self, sx, sy) -> Tuple[float, float]:
        """屏幕坐标 -> 画布坐标 (考虑滚动条)"""
        return self.canvas.canvasx(sx), self.canvas.canvasy(sy)

    def canvas_to_pixel(self, cx, cy) -> Tuple[float, float]:
        """画布坐标 -> 图像像素坐标 (考虑缩放和平移)"""
        if self.canvas.zoom_level == 0: return 0, 0
        px = (cx - self.canvas.pan_offset_x) / self.canvas.zoom_level
        py = (cy - self.canvas.pan_offset_y) / self.canvas.zoom_level
        return px, py

    def pixel_to_world(self, px, py) -> Tuple[float, float]:
        """图像像素坐标 -> 世界坐标 (ROS坐标系)"""
        if not self.map_data or not self.map_data.metadata:
            return 0.0, 0.0

        meta = self.map_data.metadata
        res = meta.resolution
        origin_x, origin_y = meta.origin[0], meta.origin[1]
        height = self.map_data.height

        # ROS PGM坐标系: (0,0)在左下角 (如果origin是左下角的话)
        # 但PGM图片 (0,0) 在左上角
        # 通常 ROS map_server 处理方式:
        # world_x = origin_x + (pixel_x + 0.5) * resolution
        # world_y = origin_y + (height - pixel_y - 0.5) * resolution

        wx = origin_x + px * res
        wy = origin_y + (height - py) * res
        return wx, wy

    def world_to_pixel(self, wx, wy) -> Tuple[float, float]:
        """世界坐标 -> 图像像素坐标"""
        if not self.map_data or not self.map_data.metadata:
            return 0.0, 0.0

        meta = self.map_data.metadata
        res = meta.resolution
        origin_x, origin_y = meta.origin[0], meta.origin[1]
        height = self.map_data.height

        px = (wx - origin_x) / res
        py = height - (wy - origin_y) / res
        return px, py

    def pixel_to_canvas(self, px, py) -> Tuple[float, float]:
        """图像像素坐标 -> 画布坐标"""
        cx = px * self.canvas.zoom_level + self.canvas.pan_offset_x
        cy = py * self.canvas.zoom_level + self.canvas.pan_offset_y
        return cx, cy

    def world_to_canvas(self, wx, wy) -> Tuple[float, float]:
        """世界坐标 -> 画布坐标 (直接用于绘图)"""
        px, py = self.world_to_pixel(wx, wy)
        return self.pixel_to_canvas(px, py)

    def canvas_to_world(self, cx, cy) -> Tuple[float, float]:
        """画布坐标 -> 世界坐标 (用于处理鼠标点击)"""
        px, py = self.canvas_to_pixel(cx, cy)
        return self.pixel_to_world(px, py)
