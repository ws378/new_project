"""正式覆盖路径轻量质量守卫。

该模块只消费正式 planner 已有输入输出，不重新预处理、不改路径。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np

Point = tuple[float, float]
SHELF_QUALITY_GUARD_NOTE = (
    "仅作为 shelfAware 质量守卫；不应用 turn_cost 研究后处理，不改变正式路径。"
)


@dataclass(frozen=True)
class PathQualityGuardConfig:
    coverage_width_m: float
    resolution_m_per_px: float
    min_coverage_ratio: float = 0.90
    long_jump_factor: float = 4.0
    infeasible_clearance_factor: float = 0.35


@dataclass(frozen=True)
class PathQualityGuardResult:
    status: str
    passed: bool
    warnings: tuple[str, ...]
    coverage_width_px: int
    point_count: int
    coverage_ratio: float
    long_jump_count: int
    max_segment_px: float
    infeasible_segment_count: int
    max_infeasible_segment_px: float
    total_turn_angle_deg: float
    length_px: float

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "passed": bool(self.passed),
            "warnings": [str(item) for item in self.warnings],
            "coverage_width_px": int(self.coverage_width_px),
            "point_count": int(self.point_count),
            "coverage_ratio": float(self.coverage_ratio),
            "long_jump_count": int(self.long_jump_count),
            "max_segment_px": float(self.max_segment_px),
            "infeasible_segment_count": int(self.infeasible_segment_count),
            "max_infeasible_segment_px": float(self.max_infeasible_segment_px),
            "total_turn_angle_deg": float(self.total_turn_angle_deg),
            "length_px": float(self.length_px),
        }


def _segment_lengths(points: Sequence[Point]) -> list[float]:
    return [
        float(math.hypot(float(curr[0]) - float(prev[0]), float(curr[1]) - float(prev[1])))
        for prev, curr in zip(points, points[1:])
    ]


def _turn_angle_deg(a: Point, b: Point, c: Point) -> float:
    incoming = (float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))
    outgoing = (float(c[0]) - float(b[0]), float(c[1]) - float(b[1]))
    in_norm = math.hypot(*incoming)
    out_norm = math.hypot(*outgoing)
    if in_norm <= 1e-9 or out_norm <= 1e-9:
        return 0.0
    dot = (incoming[0] * outgoing[0] + incoming[1] * outgoing[1]) / (in_norm * out_norm)
    dot = max(-1.0, min(1.0, dot))
    return float(math.degrees(math.acos(dot)))


def _total_turn_angle_deg(points: Sequence[Point]) -> float:
    return float(sum(_turn_angle_deg(a, b, c) for a, b, c in zip(points, points[1:], points[2:])))


def _rasterize_path(shape: tuple[int, int], points: Sequence[Point], coverage_width_px: int) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    if not points:
        return mask
    radius = max(1, int(round(float(coverage_width_px) * 0.5)))
    thickness = max(1, int(round(float(coverage_width_px))))
    pixel_points = [(int(round(x)), int(round(y))) for x, y in points]
    for point in pixel_points:
        cv2.circle(mask, point, radius, 255, -1, cv2.LINE_AA)
    for start, end in zip(pixel_points, pixel_points[1:]):
        cv2.line(mask, start, end, 255, thickness, cv2.LINE_AA)
    return mask


def _quality_guard_roi(free_mask: np.ndarray, points: Sequence[Point], margin_px: int) -> tuple[np.ndarray, tuple[Point, ...]]:
    free = np.asarray(free_mask) > 0
    rows, cols = np.where(free)
    if len(rows) == 0:
        return free.astype(np.uint8), tuple(points)
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    left = min(int(cols.min()), int(math.floor(min(xs))) if xs else int(cols.min()))
    right = max(int(cols.max()), int(math.ceil(max(xs))) if xs else int(cols.max()))
    top = min(int(rows.min()), int(math.floor(min(ys))) if ys else int(rows.min()))
    bottom = max(int(rows.max()), int(math.ceil(max(ys))) if ys else int(rows.max()))
    margin = max(1, int(margin_px))
    left = max(0, left - margin)
    top = max(0, top - margin)
    right = min(free.shape[1] - 1, right + margin)
    bottom = min(free.shape[0] - 1, bottom + margin)
    cropped_free = free[top:bottom + 1, left:right + 1]
    cropped_points = tuple((float(x) - float(left), float(y) - float(top)) for x, y in points)
    return cropped_free.astype(np.uint8), cropped_points


def _segment_is_free(free_mask: np.ndarray, start: Point, end: Point, *, clearance_px: int) -> bool:
    free = np.asarray(free_mask) > 0
    height, width = free.shape[:2]
    sx, sy = int(round(start[0])), int(round(start[1]))
    ex, ey = int(round(end[0])), int(round(end[1]))
    margin = max(1, int(clearance_px)) + 1
    left = max(0, min(sx, ex) - margin)
    right = min(width, max(sx, ex) + margin + 1)
    top = max(0, min(sy, ey) - margin)
    bottom = min(height, max(sy, ey) + margin + 1)
    if left >= right or top >= bottom:
        return False
    segment = np.zeros((bottom - top, right - left), dtype=np.uint8)
    cv2.line(
        segment,
        (sx - left, sy - top),
        (ex - left, ey - top),
        255,
        max(1, int(clearance_px)),
        cv2.LINE_AA,
    )
    return not bool(np.any((segment > 0) & ~free[top:bottom, left:right]))


def evaluate_path_quality_guard(
    free_mask: np.ndarray,
    path_pixels: Sequence[Sequence[float]],
    config: PathQualityGuardConfig,
) -> PathQualityGuardResult:
    if float(config.coverage_width_m) <= 0.0:
        raise ValueError("coverage_width_m must be positive")
    if float(config.resolution_m_per_px) <= 0.0:
        raise ValueError("resolution_m_per_px must be positive")
    if not 0.0 <= float(config.min_coverage_ratio) <= 1.0:
        raise ValueError("min_coverage_ratio must be in [0, 1]")
    if float(config.long_jump_factor) <= 0.0:
        raise ValueError("long_jump_factor must be positive")
    if float(config.infeasible_clearance_factor) <= 0.0:
        raise ValueError("infeasible_clearance_factor must be positive")

    points: tuple[Point, ...] = tuple((float(point[0]), float(point[1])) for point in path_pixels)
    coverage_width_px = max(1, int(round(float(config.coverage_width_m) / float(config.resolution_m_per_px))))
    free = np.asarray(free_mask) > 0
    free_pixels = int(np.count_nonzero(free))
    clearance_px = max(1, int(round(float(coverage_width_px) * float(config.infeasible_clearance_factor))))
    roi_free, roi_points = _quality_guard_roi(
        free,
        points,
        margin_px=max(int(coverage_width_px), int(clearance_px)) + 2,
    )
    roi_free_bool = np.asarray(roi_free) > 0
    coverage = _rasterize_path(roi_free_bool.shape, roi_points, coverage_width_px)
    covered_free_pixels = int(np.count_nonzero((coverage > 0) & roi_free_bool))
    coverage_ratio = float(covered_free_pixels / free_pixels) if free_pixels > 0 else 0.0
    lengths = _segment_lengths(points)
    long_jump_threshold = float(coverage_width_px) * float(config.long_jump_factor)
    infeasible_lengths = [
        length
        for length, start, end in zip(lengths, roi_points, roi_points[1:])
        if not _segment_is_free(roi_free_bool, start, end, clearance_px=clearance_px)
    ]
    warnings: list[str] = []
    if len(points) < 2:
        warnings.append("path_too_short")
    if coverage_ratio < float(config.min_coverage_ratio):
        warnings.append("coverage_ratio_below_threshold")
    long_jump_count = int(sum(1 for length in lengths if length > long_jump_threshold))
    if long_jump_count > 0:
        warnings.append("long_jump_detected")
    if infeasible_lengths:
        warnings.append("infeasible_segment_detected")
    status = "pass" if not warnings else "warn"
    return PathQualityGuardResult(
        status=status,
        passed=not warnings,
        warnings=tuple(warnings),
        coverage_width_px=coverage_width_px,
        point_count=len(points),
        coverage_ratio=coverage_ratio,
        long_jump_count=long_jump_count,
        max_segment_px=float(max(lengths) if lengths else 0.0),
        infeasible_segment_count=len(infeasible_lengths),
        max_infeasible_segment_px=float(max(infeasible_lengths) if infeasible_lengths else 0.0),
        total_turn_angle_deg=_total_turn_angle_deg(points),
        length_px=float(sum(lengths)),
    )


def build_shelf_quality_guard_meta(
    *,
    enabled: bool,
    effective_map: np.ndarray,
    path_pixels: Sequence[Sequence[float]],
    coverage_width_m: float,
    map_resolution: float,
    min_coverage_ratio: float,
) -> dict[str, object]:
    if not enabled:
        return {"enabled": False, "reason": "disabled_by_config"}
    result = evaluate_path_quality_guard(
        effective_map,
        path_pixels,
        PathQualityGuardConfig(
            coverage_width_m=float(coverage_width_m),
            resolution_m_per_px=float(map_resolution),
            min_coverage_ratio=float(min_coverage_ratio),
        ),
    )
    payload = result.to_dict()
    payload["enabled"] = True
    payload["formal_planner_migration"] = SHELF_QUALITY_GUARD_NOTE
    return payload


def shelf_quality_guard_warnings(meta: dict[str, object]) -> tuple[str, ...]:
    return tuple(
        f"shelf_quality_guard:{item}"
        for item in meta.get("warnings", [])
    )
