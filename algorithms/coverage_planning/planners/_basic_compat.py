from __future__ import annotations

import math
from typing import List, Optional, Tuple

import cv2
import numpy as np

PI = math.pi
PI_2_INV = 1.0 / (2.0 * PI)


class _Histogram:
    """加权直方图, 用于计算地图主方向 (与 region_basic 一致)"""

    def __init__(self, lower: float, upper: float, bins: int):
        self.lower = lower
        self.upper = upper
        self.bins = bins
        self.range_inv = 1.0 / (upper - lower)
        self.data = [0.0] * bins
        self.raw_data: List[List[Tuple[float, float]]] = [[] for _ in range(bins)]

    def add(self, val: float, weight: float = 1.0):
        b = int((val - self.lower) * self.range_inv * self.bins)
        b = max(0, min(self.bins - 1, b))
        self.data[b] += weight
        self.raw_data[b].append((val, weight))

    def max_bin_precise_val(self) -> float:
        max_bin = int(np.argmax(self.data))
        entries = self.raw_data[max_bin]
        if not entries:
            return 0.0
        s = sum(v * w for v, w in entries)
        ws = sum(w for _, w in entries)
        return s / ws if ws != 0 else 0.0


def compute_main_direction(
    room_map: np.ndarray,
    map_resolution: float,
) -> float:
    """Canny + HoughLinesP + 加权直方图 计算地图主方向 (与 region_basic 一致)"""
    res_inv = 1.0 / map_resolution

    edges = cv2.Canny(room_map, 50, 150, apertureSize=3)

    lines = None
    min_line_length = 1.0
    while min_line_length > 0.1:
        min_len_px = min_line_length * res_inv
        max_gap_px = 1.5 * min_line_length * res_inv
        lines = cv2.HoughLinesP(
            edges, 1, PI / 180, int(min_len_px),
            minLineLength=min_len_px,
            maxLineGap=max_gap_px,
        )
        if lines is not None and len(lines) >= 4:
            break
        min_line_length -= 0.2

    if lines is None or len(lines) == 0:
        return 0.0

    hist = _Histogram(0.0, PI, 36)
    for line in lines:
        x1, y1, x2, y2 = line[0]
        dx = float(x2 - x1)
        dy = float(y2 - y1)
        length = math.sqrt(dx * dx + dy * dy)
        if length > 0:
            direction = math.atan2(dy, dx)
            while direction < 0:
                direction += PI
            while direction > PI:
                direction -= PI
            hist.add(direction, length)

    return hist.max_bin_precise_val()


def get_min_max_coords(room_map: np.ndarray) -> Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]]]:
    """返回自由空间的包围盒 (与 region_basic _get_min_max_coords 一致)"""
    free = np.where(room_map > 0)
    if len(free[0]) == 0:
        return None, None
    min_x = int(free[1].min())
    max_x = int(free[1].max())
    min_y = int(free[0].min())
    max_y = int(free[0].max())
    return (min_x, min_y), (max_x, max_y)


def compute_rotation_matrix(
    room_map: np.ndarray,
    map_resolution: float,
) -> Tuple[np.ndarray, Tuple[int, int]]:
    """以自由空间质心为旋转中心, 计算仿射变换矩阵和输出尺寸 (与 region_basic 一致)"""
    angle = compute_main_direction(room_map, map_resolution)

    min_r, max_r = get_min_max_coords(room_map)
    if min_r is None:
        cx, cy = room_map.shape[1] / 2.0, room_map.shape[0] / 2.0
    else:
        cx = 0.5 * (min_r[0] + max_r[0])
        cy = 0.5 * (min_r[1] + max_r[1])

    center = (cx, cy)
    angle_deg = math.degrees(angle)

    R = cv2.getRotationMatrix2D(center, angle_deg, 1.0)

    h, w = room_map.shape[:2]
    cos_a = abs(R[0, 0])
    sin_a = abs(R[0, 1])
    new_w = int(h * sin_a + w * cos_a)
    new_h = int(h * cos_a + w * sin_a)

    R[0, 2] += 0.5 * new_w - center[0]
    R[1, 2] += 0.5 * new_h - center[1]

    return R, (new_w, new_h)


def rotate_room_auto(
    room_map: np.ndarray,
    map_resolution: float,
) -> Tuple[np.ndarray, Tuple[int, int], np.ndarray]:
    """旋转地图至主方向对齐 (与 region_basic _rotate_room_auto 一致)"""
    R, (new_w, new_h) = compute_rotation_matrix(room_map, map_resolution)
    rotated = cv2.warpAffine(room_map, R, (new_w, new_h), flags=cv2.INTER_AREA)
    _, rotated = cv2.threshold(rotated, 127, 255, cv2.THRESH_BINARY)
    return R, (new_w, new_h), rotated


def transform_path_back(
    fov_path: List[Tuple[float, float]],
    R: np.ndarray,
) -> List[Tuple[float, float]]:
    """将旋转坐标系下的路径变换回原始坐标系 (与 region_basic _transform_path_back 一致)"""
    if not fov_path:
        return []
    pts = np.array(fov_path, dtype=np.float32).reshape(1, -1, 2)
    R_inv = cv2.invertAffineTransform(R)
    transformed = cv2.transform(pts, R_inv)[0]
    return [(float(p[0]), float(p[1])) for p in transformed]


def complete_cell_test(
    room_map: np.ndarray,
    cx: int, cy: int,
    cell_size: int,
) -> Tuple[bool, int, int]:
    """检测网格单元是否包含可达空间, 用距离变换找最佳中心 (与 region_basic _complete_cell_test 一致)"""
    h, w = room_map.shape[:2]
    if 0 <= cy < h and 0 <= cx < w:
        if room_map[cy, cx] == 255:
            return True, cx, cy

    half = cell_size // 2
    upper = half - 1 if cell_size % 2 == 0 else half

    x0 = max(0, cx - half)
    x1 = min(w, cx + upper + 1)
    y0 = max(0, cy - half)
    y1 = min(h, cy + upper + 1)

    if x1 <= x0 or y1 <= y0:
        return False, cx, cy

    cell = room_map[y0:y1, x0:x1]
    accessible = np.where(cell == 255)
    if len(accessible[0]) == 0:
        return False, cx, cy

    cell_bin = np.zeros_like(cell)
    cell_bin[cell == 255] = 255
    dist = cv2.distanceTransform(cell_bin, cv2.DIST_L2, 5)
    max_dist = dist.max()

    candidates = np.argwhere(dist == max_dist)
    best_dy, best_dx = candidates[0]
    best_sq_dist = (best_dx - half) ** 2 + (best_dy - half) ** 2
    for dy_off, dx_off in candidates[1:]:
        sq = (dx_off - half) ** 2 + (dy_off - half) ** 2
        if sq < best_sq_dist:
            best_sq_dist = sq
            best_dx, best_dy = dx_off, dy_off

    new_cx = x0 + int(best_dx)
    new_cy = y0 + int(best_dy)
    return True, new_cx, new_cy


def pixels_to_world(
    original_path_px: List[Tuple[float, float]],
    map_resolution: float,
    map_origin: Tuple[float, float],
    map_h: int,
) -> List[Tuple[float, float, float]]:
    """像素坐标 → 世界坐标, 含 Y 轴翻转和朝向计算 (与 region_basic plan() 一致)"""
    path = []
    for i, (px, py) in enumerate(original_path_px):
        wx = px * map_resolution + map_origin[0]
        wy = (map_h - py) * map_resolution + map_origin[1]
        if i < len(original_path_px) - 1:
            nx, ny = original_path_px[i + 1]
            theta = math.atan2(-(ny - py), nx - px)
        elif i > 0:
            prev_x, prev_y = original_path_px[i - 1]
            theta = math.atan2(-(py - prev_y), px - prev_x)
        else:
            theta = 0.0
        path.append((wx, wy, theta))
    return path
