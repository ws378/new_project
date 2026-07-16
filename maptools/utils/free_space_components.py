from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import cv2
import numpy as np

from ..models.annotations import Annotations
from ..models.map_data import MapData

FREE_SPACE_COMPONENT_COLOR_RGB: Tuple[int, int, int] = (144, 238, 144)
FREE_SPACE_COMPONENT_COLOR_HEX = "#90ee90"


@dataclass(frozen=True)
class FreeSpaceComponentStat:
    component_id: int
    pixel_count: int
    area_m2: float
    bbox_px: Tuple[int, int, int, int]
    suggested_no_coverage: bool = False


@dataclass(frozen=True)
class FreeSpaceComponentsResult:
    obstacle_mask: np.ndarray
    repaired_obstacle_mask: np.ndarray
    free_mask: np.ndarray
    component_labels: np.ndarray
    component_color_lut: np.ndarray
    component_stats: Dict[int, FreeSpaceComponentStat]
    repair_radius_m: float
    repair_kernel_px: int
    small_component_threshold_m2: float
    total_component_count: int

    def stat_for_label(self, component_id: int) -> FreeSpaceComponentStat | None:
        return self.component_stats.get(int(component_id))


def _world_to_image_pixel(wx: float, wy: float, resolution: float, origin_x: float, origin_y: float, map_height: int) -> Tuple[int, int]:
    px = int(round((wx - origin_x) / resolution))
    py = int(round(map_height - (wy - origin_y) / resolution))
    return px, py


def image_pixel_to_world(px: int, py: int, resolution: float, origin_x: float, origin_y: float, map_height: int) -> Tuple[float, float]:
    wx = origin_x + float(px) * resolution
    wy = origin_y + float(map_height - py) * resolution
    return wx, wy


def _draw_constraint_obstacles(mask: np.ndarray, map_data: MapData, annotations: Annotations) -> None:
    if map_data.metadata is None:
        return
    resolution = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])
    height = int(map_data.height)

    def iter_segments(constraint_type: str, *, closed: bool | None = None):
        iterator = getattr(annotations, "iter_constraint_segments", None)
        if callable(iterator):
            yield from iterator(constraint_type, closed=closed)

    for segment in iter_segments("forbidden_zone", closed=True):
        if len(segment.points) < 3:
            continue
        pts = np.array(
            [_world_to_image_pixel(float(wx), float(wy), resolution, origin_x, origin_y, height) for wx, wy in segment.points],
            dtype=np.int32,
        ).reshape((-1, 1, 2))
        cv2.fillPoly(mask, [pts], 255)

    for segment in iter_segments("virtual_wall", closed=False):
        if len(segment.points) < 2:
            continue
        pts = [
            _world_to_image_pixel(float(wx), float(wy), resolution, origin_x, origin_y, height)
            for wx, wy in segment.points
        ]
        for start, end in zip(pts, pts[1:]):
            cv2.line(mask, start, end, 255, thickness=3)

    iter_regions = getattr(annotations, "iter_derived_constraint_regions", None)
    decode_region_mask = getattr(annotations, "decode_derived_constraint_region_mask", None)
    if callable(iter_regions) and callable(decode_region_mask):
        for region in iter_regions("forbidden_zone"):
            x, y, width, height = (int(value) for value in region.bbox_px)
            if width <= 0 or height <= 0:
                continue
            region_mask = decode_region_mask(region)
            if region_mask.size == 0:
                continue
            x0 = max(0, x)
            y0 = max(0, y)
            x1 = min(mask.shape[1], x + width)
            y1 = min(mask.shape[0], y + height)
            if x1 <= x0 or y1 <= y0:
                continue
            region_x0 = x0 - x
            region_y0 = y0 - y
            region_x1 = region_x0 + (x1 - x0)
            region_y1 = region_y0 + (y1 - y0)
            roi = mask[y0:y1, x0:x1]
            roi_region = region_mask[region_y0:region_y1, region_x0:region_x1]
            roi[roi_region > 0] = 255


def build_obstacle_semantic_mask(map_data: MapData, annotations: Annotations) -> np.ndarray:
    display = np.array(map_data.get_display_image(), copy=False)
    obstacle_mask = np.where(display > 250, 0, 255).astype(np.uint8)
    _draw_constraint_obstacles(obstacle_mask, map_data, annotations)
    return obstacle_mask


def build_forbidden_zone_mask(map_data: MapData, annotations: Annotations) -> np.ndarray:
    """只包含禁行区 (forbidden_zone) 的 mask，不包含地图障碍物。"""
    if map_data.metadata is None:
        raise ValueError("map data is not loaded")
    h = int(map_data.height)
    w = int(map_data.width)
    mask = np.zeros((h, w), dtype=np.uint8)
    resolution = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])

    def iter_segments(constraint_type: str, *, closed: bool | None = None):
        iterator = getattr(annotations, "iter_constraint_segments", None)
        if callable(iterator):
            yield from iterator(constraint_type, closed=closed)

    for segment in iter_segments("forbidden_zone", closed=True):
        if len(segment.points) < 3:
            continue
        pts = np.array(
            [_world_to_image_pixel(float(wx), float(wy), resolution, origin_x, origin_y, h) for wx, wy in segment.points],
            dtype=np.int32,
        ).reshape((-1, 1, 2))
        cv2.fillPoly(mask, [pts], 255)

    return mask


def derive_repair_kernel_px(repair_radius_m: float, resolution_m_per_px: float) -> int:
    radius = max(float(repair_radius_m), 0.0)
    resolution = max(float(resolution_m_per_px), 1e-9)
    if radius <= 0.0:
        return 0
    return max(1, int(np.ceil(radius / resolution)))


def repair_obstacle_connectivity(obstacle_mask: np.ndarray, *, repair_radius_m: float, resolution_m_per_px: float) -> tuple[np.ndarray, int]:
    kernel_px = derive_repair_kernel_px(repair_radius_m, resolution_m_per_px)
    if kernel_px <= 0:
        return obstacle_mask.copy(), 0
    kernel_size = kernel_px * 2 + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    repaired = cv2.morphologyEx(obstacle_mask, cv2.MORPH_CLOSE, kernel)
    return repaired, kernel_px


def _component_color(_component_id: int) -> Tuple[int, int, int]:
    # 自由连通区分析层统一使用浅绿色，不再按 component 自动分配颜色。
    return FREE_SPACE_COMPONENT_COLOR_RGB


def _build_component_color_lut(component_stats: Dict[int, FreeSpaceComponentStat]) -> np.ndarray:
    if not component_stats:
        return np.zeros((1, 4), dtype=np.uint8)
    lut = np.zeros((max(component_stats) + 1, 4), dtype=np.uint8)
    for component_id in component_stats:
        color = _component_color(component_id)
        lut[int(component_id), 0] = color[0]
        lut[int(component_id), 1] = color[1]
        lut[int(component_id), 2] = color[2]
        lut[int(component_id), 3] = 96
    return lut


def expand_area_label_polygons(
    map_data: MapData,
    annotations: Annotations,
    *,
    step_size: int = 1,
    simplify_epsilon_px: float = 1.5,
) -> List[List[Tuple[float, float]]]:
    """将所有房间填满其所在的 free 连通分量。

    每个房间在其所在的 free 连通分量内扩张到占据全部空间。
    同一分量内有多个房间时，用同步迭代膨胀公平划分。

    step_size: 每次迭代扩张的像素数 (默认 1)。

    返回: List[new_polygon_world_coords]，与 area_labels 一一对应。
    """
    if map_data.metadata is None:
        raise ValueError("map data is not loaded")
    if not annotations.area_labels:
        return []

    obstacle_mask = build_obstacle_semantic_mask(map_data, annotations)
    resolution = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])
    height = int(map_data.height)
    h, w = obstacle_mask.shape[:2]

    # 1. 为每个房间画种子区域
    seeds = np.full((h, w), -1, dtype=np.int32)
    valid = []
    for i, label in enumerate(annotations.area_labels):
        if len(label.polygon) < 3:
            valid.append(False)
            continue

        pts = np.array([
            _world_to_image_pixel(float(wx), float(wy), resolution, origin_x, origin_y, height)
            for wx, wy in label.polygon
        ], dtype=np.int32).reshape((-1, 1, 2))
        pts[:, :, 0] = np.clip(pts[:, :, 0], 0, w - 1)
        pts[:, :, 1] = np.clip(pts[:, :, 1], 0, h - 1)

        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask, [pts], 1)
        mask[obstacle_mask > 0] = 0

        if cv2.countNonZero(mask) == 0:
            cx = int(np.clip(np.mean(pts[:, :, 0]), 0, w - 1))
            cy = int(np.clip(np.mean(pts[:, :, 1]), 0, h - 1))
            seed = None
            for r in range(1, max(w, h)):
                y0, y1 = max(0, cy - r), min(h, cy + r + 1)
                x0, x1 = max(0, cx - r), min(w, cx + r + 1)
                ring = obstacle_mask[y0:y1, x0:x1] == 0
                if np.any(ring):
                    free_ys, free_xs = np.where(ring)
                    seed = (free_xs[0] + x0, free_ys[0] + y0)
                    break
            if seed is None:
                valid.append(False)
                continue
            mask = np.zeros((h, w), dtype=np.uint8)
            mask[seed[1], seed[0]] = 1

        seeds[mask > 0] = i
        valid.append(True)

    # 2. 连通分量分析
    free_mask = (obstacle_mask == 0).astype(np.uint8)
    num_components, component_labels = cv2.connectedComponents(free_mask, connectivity=8)

    # 每个分量包含哪些房间
    comp_rooms: dict[int, list[int]] = {}
    for i in range(len(annotations.area_labels)):
        if not valid[i]:
            continue
        ys, xs = np.where(seeds == i)
        if len(ys) == 0:
            continue
        comp_id = component_labels[ys[0], xs[0]]
        comp_rooms.setdefault(comp_id, []).append(i)

    # 3. 分配：同一分量内多个房间做逐层同步扩张，单个房间直接全占
    assignment = np.full((h, w), -1, dtype=np.int32)

    for comp_id, room_ids in comp_rooms.items():
        comp_mask = (component_labels == comp_id).astype(np.uint8)
        if len(room_ids) == 1:
            i = room_ids[0]
            m = (seeds == i).astype(np.uint8)
            m[comp_mask == 0] = 0
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            while True:
                d = cv2.dilate(m, kernel, iterations=step_size)
                new_p = d & ~m & comp_mask & (assignment == -1)
                if np.count_nonzero(new_p) == 0:
                    break
                assignment[new_p > 0] = i
                m[new_p > 0] = 1
        else:
            masks = {}
            for i in room_ids:
                m = (seeds == i).astype(np.uint8)
                m[comp_mask == 0] = 0
                if np.count_nonzero(m) > 0:
                    masks[i] = m
            if not masks:
                continue
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            while True:
                progress = False
                for i, m in masks.items():
                    d = cv2.dilate(m, kernel, iterations=step_size)
                    new_p = d & ~m & comp_mask & (assignment == -1)
                    if np.count_nonzero(new_p) == 0:
                        continue
                    assignment[new_p > 0] = i
                    m[new_p > 0] = 1
                    progress = True
                if not progress:
                    break
            # fallback: tiny leftover gaps
            left = comp_mask & (assignment == -1).astype(np.uint8)
            if np.count_nonzero(left) > 0:
                best = np.full(left.shape, 2e9, dtype=np.float32)
                for i, m in masks.items():
                    dist = cv2.distanceTransform(m, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
                    nearer = (dist < best) & (left > 0)
                    assignment[nearer] = i
                    best[nearer] = dist[nearer]

    # 4. 提取轮廓
    results: List[List[Tuple[float, float]]] = []
    for i, label in enumerate(annotations.area_labels):
        if not valid[i]:
            results.append(label.polygon)
            continue

        region_mask = (assignment == i).astype(np.uint8) * 255
        contours, _ = cv2.findContours(region_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            results.append(label.polygon)
            continue

        contour = max(contours, key=cv2.contourArea)
        orig_contour = contour
        if float(simplify_epsilon_px) > 0.0:
            contour = cv2.approxPolyDP(contour, epsilon=float(simplify_epsilon_px), closed=True)
        if contour.shape[0] < 3:
            contour = orig_contour
        if contour.shape[0] < 3:
            results.append(label.polygon)
            continue

        polygon: List[Tuple[float, float]] = []
        for pt in contour.reshape((-1, 2)):
            polygon.append(
                image_pixel_to_world(int(pt[0]), int(pt[1]), resolution, origin_x, origin_y, height)
            )
        results.append(polygon)

    return results


def expand_area_labels_by_contour(
    map_data: MapData,
    annotations: Annotations,
    *,
    contour_gap: float = 0.2,
    max_expand: float = 2.0,
) -> List[List[Tuple[float, float]]]:
    """等高线扩展法：每个区域标签沿等高线逐层向外扩张，直到边界或相邻标签。

    1) 将现有 polygon 转成像素种子（不擦除障碍物像素——区域标签本身就是障碍物标签）
    2) 用障碍物距离变换作为等高线
    3) 逐层同步扩张（各房间在当前等高线带内同步抢占相邻像素）
    4) 提取新 polygon 返回

    返回 new_polygons_world，与 area_labels 一一对应。
    """
    if map_data.metadata is None:
        raise ValueError("map data is not loaded")

    obstacle_mask = build_obstacle_semantic_mask(map_data, annotations)
    resolution = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])
    height = int(map_data.height)
    h, w = obstacle_mask.shape[:2]

    # 栅格化种子：不擦除障碍物像素（区域标签就是障碍物标签）
    assignment = np.full((h, w), -1, dtype=np.int32)
    for i, label in enumerate(annotations.area_labels):
        if len(label.polygon) < 3:
            continue
        pts = np.array([
            _world_to_image_pixel(float(wx), float(wy), resolution, origin_x, origin_y, height)
            for wx, wy in label.polygon
        ], dtype=np.int32).reshape((-1, 1, 2))
        pts[:, :, 0] = np.clip(pts[:, :, 0], 0, w - 1)
        pts[:, :, 1] = np.clip(pts[:, :, 1], 0, h - 1)
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask, [pts], 1)
        assignment[mask > 0] = i

    free_mask = (obstacle_mask == 0).astype(np.uint8)
    free_mask[:1, :] = 0
    free_mask[-1:, :] = 0
    free_mask[:, :1] = 0
    free_mask[:, -1:] = 0

    if cv2.countNonZero(free_mask) == 0:
        return [list(lab.polygon) for lab in annotations.area_labels]

    dist = cv2.distanceTransform(free_mask, cv2.DIST_L2, 5)

    max_px = int(round(max_expand / resolution))
    gap_px = max(1, int(round(contour_gap / resolution)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    # occupied = 障碍物、地图边界、已被房间抢占的像素
    occupied = (obstacle_mask > 0).astype(np.uint8)
    occupied[:1, :] = 1
    occupied[-1:, :] = 1
    occupied[:, :1] = 1
    occupied[:, -1:] = 1

    # step 1: 将种子从障碍物像素扩展到相邻的自由像素（距离障碍物0→1）
    for i in range(len(annotations.area_labels)):
        if len(annotations.area_labels[i].polygon) < 3:
            continue
        if not (assignment == i).any():
            continue
        room_mask = (assignment == i).astype(np.uint8)
        dilated = cv2.dilate(room_mask, kernel, iterations=1)
        new_pixels = dilated & (~room_mask) & (~occupied)
        if cv2.countNonZero(new_pixels) > 0:
            assignment[new_pixels > 0] = i
            occupied[new_pixels > 0] = 1

    # step 2: 按等高线间距逐层扩张
    for d_px in range(gap_px, max_px + 1, gap_px):
        # 当前层：距离障碍物在 [d_px, d_px+gap_px) 范围内的自由像素
        upper = d_px + gap_px
        band = ((dist >= d_px) & (dist < upper)).astype(np.uint8)
        band[occupied > 0] = 0
        if cv2.countNonZero(band) == 0:
            continue

        progress = False
        for i in range(len(annotations.area_labels)):
            if len(annotations.area_labels[i].polygon) < 3:
                continue
            if not (assignment == i).any():
                continue
            room_mask = (assignment == i).astype(np.uint8)
            # 扩张 gap_px 像素，以覆盖整个当前等高线层
            dilated = cv2.dilate(room_mask, kernel, iterations=gap_px)
            new_pixels = dilated & band
            if cv2.countNonZero(new_pixels) > 0:
                assignment[new_pixels > 0] = i
                occupied[new_pixels > 0] = 1
                band[new_pixels > 0] = 0
                progress = True

        if not progress:
            break

    # 提取新 polygon
    results: List[List[Tuple[float, float]]] = []
    for i, label in enumerate(annotations.area_labels):
        if len(label.polygon) < 3:
            results.append(label.polygon)
            continue
        region_mask = (assignment == i).astype(np.uint8) * 255
        if cv2.countNonZero(region_mask) == 0:
            results.append(label.polygon)
            continue
        contours, _ = cv2.findContours(region_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            results.append(label.polygon)
            continue
        contour = max(contours, key=cv2.contourArea)
        contour = cv2.approxPolyDP(contour, epsilon=1.5, closed=True)
        if contour.shape[0] < 3:
            results.append(label.polygon)
            continue
        polygon = []
        for pt in contour[:, 0, :]:
            wx = origin_x + float(pt[0]) * resolution
            wy = origin_y + float(height - pt[1]) * resolution
            polygon.append((wx, wy))
        results.append(polygon)

    return results


def analyze_free_space_components(
    map_data: MapData,
    annotations: Annotations,
    *,
    repair_radius_m: float,
    small_component_threshold_m2: float = 1000.0,
) -> FreeSpaceComponentsResult:
    if map_data.metadata is None or map_data.width <= 0 or map_data.height <= 0:
        raise ValueError("map data is not loaded")

    obstacle_mask = build_obstacle_semantic_mask(map_data, annotations)
    repaired_obstacle_mask, kernel_px = repair_obstacle_connectivity(
        obstacle_mask,
        repair_radius_m=repair_radius_m,
        resolution_m_per_px=float(map_data.metadata.resolution),
    )
    free_mask = np.where(repaired_obstacle_mask > 0, 0, 255).astype(np.uint8)

    component_count, labels, stats, _ = cv2.connectedComponentsWithStats((free_mask > 0).astype(np.uint8), connectivity=8)
    component_stats: Dict[int, FreeSpaceComponentStat] = {}
    area_per_pixel = float(map_data.metadata.resolution) ** 2
    for component_id in range(1, int(component_count)):
        x = int(stats[component_id, cv2.CC_STAT_LEFT])
        y = int(stats[component_id, cv2.CC_STAT_TOP])
        w = int(stats[component_id, cv2.CC_STAT_WIDTH])
        h = int(stats[component_id, cv2.CC_STAT_HEIGHT])
        pixel_count = int(stats[component_id, cv2.CC_STAT_AREA])
        area_m2 = pixel_count * area_per_pixel
        component_stats[component_id] = FreeSpaceComponentStat(
            component_id=component_id,
            pixel_count=pixel_count,
            area_m2=area_m2,
            bbox_px=(x, y, w, h),
            suggested_no_coverage=area_m2 <= float(small_component_threshold_m2),
        )

    color_lut = _build_component_color_lut(component_stats)
    return FreeSpaceComponentsResult(
        obstacle_mask=obstacle_mask,
        repaired_obstacle_mask=repaired_obstacle_mask,
        free_mask=free_mask,
        component_labels=labels,
        component_color_lut=color_lut,
        component_stats=component_stats,
        repair_radius_m=float(repair_radius_m),
        repair_kernel_px=kernel_px,
        small_component_threshold_m2=float(small_component_threshold_m2),
        total_component_count=len(component_stats),
    )


def extract_component_bbox_mask(
    result: FreeSpaceComponentsResult,
    component_id: int,
) -> tuple[tuple[int, int, int, int], np.ndarray] | None:
    labels = np.asarray(result.component_labels)
    stat = result.stat_for_label(component_id)
    if stat is None:
        return None
    x0, y0, width, height = (int(value) for value in stat.bbox_px)
    if width <= 0 or height <= 0:
        return None
    x1 = x0 + width
    y1 = y0 + height
    if x0 < 0 or y0 < 0 or x1 > labels.shape[1] or y1 > labels.shape[0]:
        return None
    component_window = labels[y0:y1, x0:x1]
    component_mask = np.where(component_window == int(component_id), 255, 0).astype(np.uint8)
    if int(np.count_nonzero(component_mask)) == 0:
        return None
    return (x0, y0, width, height), component_mask


def extract_component_polygon_world(
    map_data: MapData,
    result: FreeSpaceComponentsResult,
    component_id: int,
    *,
    simplify_epsilon_px: float = 1.5,
) -> List[Tuple[float, float]]:
    extracted = extract_component_bbox_mask(result, component_id)
    if extracted is None:
        return []
    (x0, y0, _width, _height), component_mask = extracted
    contours, _ = cv2.findContours(component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    contour = max(contours, key=cv2.contourArea)
    original_contour = contour
    if float(simplify_epsilon_px) > 0.0:
        contour = cv2.approxPolyDP(contour, epsilon=float(simplify_epsilon_px), closed=True)
    if contour.shape[0] < 3:
        contour = original_contour
    if contour.shape[0] < 3:
        return []
    resolution = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])
    height = int(map_data.height)
    polygon: List[Tuple[float, float]] = []
    for point in contour.reshape((-1, 2)):
        polygon.append(
            image_pixel_to_world(
                int(point[0]) + x0,
                int(point[1]) + y0,
                resolution,
                origin_x,
                origin_y,
                height,
            )
        )
    return polygon
