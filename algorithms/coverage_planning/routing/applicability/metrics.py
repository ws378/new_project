from __future__ import annotations

import math

import cv2
import numpy as np

from ...contracts import ApplicabilityMetrics


def compute_applicability_metrics(room_map: np.ndarray,
                                  resolution: float = 0.05) -> ApplicabilityMetrics:
    """Compute lightweight scene metrics before planner selection.

    Args:
        room_map: binary map (0=obstacle, >0=free)
        resolution: map resolution in m/px (default 0.05)
    """

    if room_map is None or room_map.size == 0:
        return ApplicabilityMetrics()

    free_mask = np.asarray(room_map) > 0
    free_area = int(np.count_nonzero(free_mask))
    if free_area < 9:
        return ApplicabilityMetrics()

    rows, cols = np.where(free_mask)
    height = int(rows.max() - rows.min() + 1)
    width = int(cols.max() - cols.min() + 1)
    short_side = max(1, min(width, height))
    long_side = max(width, height)
    aspect_ratio = float(long_side) / float(short_side)

    distance = cv2.distanceTransform(
        free_mask.astype(np.uint8),
        cv2.DIST_L2,
        3,
    )
    clearance_values = distance[free_mask]
    mean_clearance_px = float(np.mean(clearance_values)) if clearance_values.size else 0.0
    std_clearance = float(np.std(clearance_values)) if clearance_values.size else 0.0
    width_variation = std_clearance / max(mean_clearance_px, 1e-6)
    narrow_passage_ratio = float(np.mean(clearance_values < resolution)) if clearance_values.size else 1.0

    component_count, _ = cv2.connectedComponents(free_mask.astype(np.uint8), connectivity=8)
    connected_free_components = max(0, int(component_count) - 1)

    open_space_score = max(0.0, 1.0 - min(aspect_ratio / 4.0, 1.0))
    mixed_scene_score = 1.0 if connected_free_components > 1 else min(width_variation, 1.0)

    skeleton_to_free_area_ratio = 1.0 / max(math.sqrt(float(free_area)), 1.0)

    obstacle_count = 0
    if free_area >= 100:
        try:
            contours, hierarchy = cv2.findContours(
                free_mask.astype(np.uint8), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
            )
            if hierarchy is not None:
                h_arr = hierarchy[0]
                # 仅统计 level-1（父轮廓无父轮廓 = 最外层自由空间内部的空洞 = 障碍物）
                # 最小面积 40px ≈ 0.1m²（0.05m/px），滤除传感器噪声
                min_obstacle_area_px = 40.0
                obstacle_count = sum(
                    1 for i, h in enumerate(h_arr)
                    if h[3] >= 0 and h_arr[int(h[3])][3] < 0
                    and cv2.contourArea(contours[i]) >= min_obstacle_area_px
                )
        except Exception:
            obstacle_count = 0

    return ApplicabilityMetrics(
        skeleton_pixel_count=0,
        free_area_pixel_count=free_area,
        skeleton_to_free_area_ratio=skeleton_to_free_area_ratio,
        width_variation_score=width_variation,
        junction_candidate_count=0,
        open_space_score=open_space_score,
        mixed_scene_score=mixed_scene_score,
        obstacle_count=obstacle_count,
        mean_clearance_px=mean_clearance_px,
        narrow_passage_ratio=narrow_passage_ratio,
    )

