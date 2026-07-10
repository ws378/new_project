from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


DEFAULT_MAJORITY_RADIUS_M = 0.25
DEFAULT_BOUNDARY_BAND_M = 0.35
DEFAULT_OBSTACLE_THRESHOLD = 0.5


@dataclass(frozen=True)
class BoundarySmoothingResult:
    original_free_mask: np.ndarray
    smoothed_free_mask: np.ndarray
    boundary_band: np.ndarray
    delta_add: np.ndarray
    delta_remove: np.ndarray
    debug_info: dict[str, Any]


def normalize_mask(mask: np.ndarray) -> np.ndarray:
    return np.where(np.asarray(mask) > 0, 255, 0).astype(np.uint8)


def kernel_size_from_meters(length_m: float, resolution_m_per_px: float) -> int:
    radius_px = max(1, int(round(float(length_m) / float(resolution_m_per_px))))
    return max(3, radius_px * 2 + 1)


def disk_kernel_from_radius_m(radius_m: float, resolution_m_per_px: float) -> np.ndarray:
    radius_px = max(1, int(round(float(radius_m) / float(resolution_m_per_px))))
    yy, xx = np.ogrid[-radius_px : radius_px + 1, -radius_px : radius_px + 1]
    return np.where((xx * xx + yy * yy) <= radius_px * radius_px, 1.0, 0.0).astype(np.float32)


def boundary_band_mask(free_mask: np.ndarray, band_m: float, resolution_m_per_px: float) -> np.ndarray:
    free01 = np.where(free_mask > 0, 1, 0).astype(np.uint8)
    obstacle01 = np.where(free01 > 0, 0, 1).astype(np.uint8)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (kernel_size_from_meters(band_m, resolution_m_per_px),) * 2,
    )
    free_edge_side = cv2.dilate(obstacle01, kernel, iterations=1) & free01
    obstacle_edge_side = cv2.dilate(free01, kernel, iterations=1) & obstacle01
    return np.where((free_edge_side | obstacle_edge_side) > 0, 255, 0).astype(np.uint8)


def connected_component_count(mask: np.ndarray) -> int:
    num_labels, _labels = cv2.connectedComponents(np.where(mask > 0, 1, 0).astype(np.uint8), 8)
    return max(0, int(num_labels) - 1)


def apply_majority_smoothing(
    free_mask: np.ndarray,
    region_mask: np.ndarray,
    resolution_m_per_px: float,
    *,
    majority_radius_m: float = DEFAULT_MAJORITY_RADIUS_M,
    boundary_band_m: float = DEFAULT_BOUNDARY_BAND_M,
    obstacle_threshold: float = DEFAULT_OBSTACLE_THRESHOLD,
) -> BoundarySmoothingResult:
    free = normalize_mask(free_mask)
    region = normalize_mask(region_mask)
    band = boundary_band_mask(free, boundary_band_m, resolution_m_per_px)

    free01 = np.where(free > 0, 1.0, 0.0).astype(np.float32)
    region01 = np.where(region > 0, 1.0, 0.0).astype(np.float32)
    obstacle01 = np.where((region > 0) & (free == 0), 1.0, 0.0).astype(np.float32)
    kernel = disk_kernel_from_radius_m(majority_radius_m, resolution_m_per_px)
    obstacle_count = cv2.filter2D(obstacle01, cv2.CV_32F, kernel, borderType=cv2.BORDER_CONSTANT)
    valid_count = cv2.filter2D(region01, cv2.CV_32F, kernel, borderType=cv2.BORDER_CONSTANT)
    obstacle_ratio = np.divide(
        obstacle_count,
        valid_count,
        out=np.zeros_like(obstacle_count, dtype=np.float32),
        where=valid_count > 0,
    )
    majority_obstacle = obstacle_ratio > float(obstacle_threshold)
    can_update = (band > 0) & (region > 0)
    smoothed = np.where(
        can_update,
        np.where(majority_obstacle, 0, 255),
        np.where(free01 > 0, 255, 0),
    ).astype(np.uint8)
    smoothed = np.where((smoothed > 0) & (region > 0), 255, 0).astype(np.uint8)

    before_cc = connected_component_count(free)
    after_cc = connected_component_count(smoothed)
    accepted = before_cc == after_cc
    if not accepted:
        smoothed = free.copy()
        after_cc = before_cc

    delta_add = np.where((smoothed > 0) & (free == 0), 255, 0).astype(np.uint8)
    delta_remove = np.where((free > 0) & (smoothed == 0), 255, 0).astype(np.uint8)
    radius_px = int(round(float(majority_radius_m) / float(resolution_m_per_px)))
    debug_info = {
        "enabled": True,
        "method": "boundary_band_majority",
        "accepted": bool(accepted),
        "rejection_reason": None if accepted else "free_component_count_changed",
        "majority_radius_m": float(majority_radius_m),
        "majority_radius_px": int(radius_px),
        "boundary_band_m": float(boundary_band_m),
        "obstacle_threshold": float(obstacle_threshold),
        "kernel_pixel_count": int(np.count_nonzero(kernel)),
        "boundary_band_pixel_count": int(np.count_nonzero(band)),
        "free_component_count_before": int(before_cc),
        "free_component_count_after": int(after_cc),
        "delta_add_pixel_count": int(np.count_nonzero(delta_add)),
        "delta_remove_pixel_count": int(np.count_nonzero(delta_remove)),
        "updated_pixel_count": int(np.count_nonzero((smoothed > 0) != (free > 0))),
    }
    return BoundarySmoothingResult(
        original_free_mask=free,
        smoothed_free_mask=smoothed,
        boundary_band=band,
        delta_add=delta_add,
        delta_remove=delta_remove,
        debug_info=debug_info,
    )
