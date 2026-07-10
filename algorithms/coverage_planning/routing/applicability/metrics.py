from __future__ import annotations

import math

import cv2
import numpy as np

from ...contracts import ApplicabilityMetrics


def compute_applicability_metrics(room_map: np.ndarray) -> ApplicabilityMetrics:
    """Compute lightweight scene metrics before planner selection."""

    if room_map is None or room_map.size == 0:
        return ApplicabilityMetrics()

    free_mask = np.asarray(room_map) > 0
    free_area = int(np.count_nonzero(free_mask))
    if free_area <= 0:
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
    mean_clearance = float(np.mean(clearance_values)) if clearance_values.size else 0.0
    std_clearance = float(np.std(clearance_values)) if clearance_values.size else 0.0
    width_variation = std_clearance / max(mean_clearance, 1e-6)

    component_count, _ = cv2.connectedComponents(free_mask.astype(np.uint8), connectivity=8)
    connected_free_components = max(0, int(component_count) - 1)

    # This is a cheap open-space proxy. Full room segmentation is deliberately
    # not a precondition for routing.
    open_space_score = max(0.0, 1.0 - min(aspect_ratio / 4.0, 1.0))
    mixed_scene_score = 1.0 if connected_free_components > 1 else min(width_variation, 1.0)

    # Skeleton extraction is intentionally not performed in this lightweight
    # preflight. The ratio still carries useful shape information via aspect.
    skeleton_to_free_area_ratio = 1.0 / max(math.sqrt(float(free_area)), 1.0)

    return ApplicabilityMetrics(
        skeleton_pixel_count=0,
        free_area_pixel_count=free_area,
        skeleton_to_free_area_ratio=skeleton_to_free_area_ratio,
        width_variation_score=width_variation,
        junction_candidate_count=0,
        open_space_score=open_space_score,
        mixed_scene_score=mixed_scene_score,
    )

