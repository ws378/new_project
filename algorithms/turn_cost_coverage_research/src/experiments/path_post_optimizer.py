"""已有覆盖路径的 turn-cost 后处理实验工具。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np

Point = tuple[float, float]


@dataclass(frozen=True)
class PathMetrics:
    point_count: int
    length_px: float
    total_turn_angle_deg: float
    max_segment_px: float
    long_jump_count: int
    coverage_ratio: float
    covered_free_pixels: int
    free_pixels: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "point_count": int(self.point_count),
            "length_px": float(self.length_px),
            "total_turn_angle_deg": float(self.total_turn_angle_deg),
            "max_segment_px": float(self.max_segment_px),
            "long_jump_count": int(self.long_jump_count),
            "coverage_ratio": float(self.coverage_ratio),
            "covered_free_pixels": int(self.covered_free_pixels),
            "free_pixels": int(self.free_pixels),
        }


@dataclass(frozen=True)
class SimplifyConfig:
    coverage_width_px: int
    max_coverage_drop_ratio: float = 0.002
    min_turn_improvement_deg: float = 5.0
    max_shortcut_factor: float = 2.5
    long_jump_factor: float = 4.0
    allow_long_jump_increase: bool = False


@dataclass(frozen=True)
class SimplifyResult:
    points: tuple[Point, ...]
    before: PathMetrics
    after: PathMetrics
    removed_point_count: int
    accepted_shortcut_count: int
    rejected_by_collision_count: int
    rejected_by_coverage_count: int
    rejected_by_jump_count: int
    rejected_by_score_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "removed_point_count": int(self.removed_point_count),
            "accepted_shortcut_count": int(self.accepted_shortcut_count),
            "rejected_by_collision_count": int(self.rejected_by_collision_count),
            "rejected_by_coverage_count": int(self.rejected_by_coverage_count),
            "rejected_by_jump_count": int(self.rejected_by_jump_count),
            "rejected_by_score_count": int(self.rejected_by_score_count),
        }


def normalize_points(points: Sequence[Sequence[float]]) -> tuple[Point, ...]:
    normalized: list[Point] = []
    for index, point in enumerate(points):
        if len(point) < 2:
            raise ValueError(f"path point at index {index} has fewer than 2 coordinates")
        normalized.append((float(point[0]), float(point[1])))
    return tuple(normalized)


def path_length_px(points: Sequence[Point]) -> float:
    if len(points) < 2:
        return 0.0
    return float(sum(math.hypot(curr[0] - prev[0], curr[1] - prev[1]) for prev, curr in zip(points, points[1:])))


def _segment_lengths(points: Sequence[Point]) -> list[float]:
    return [float(math.hypot(curr[0] - prev[0], curr[1] - prev[1])) for prev, curr in zip(points, points[1:])]


def turn_angle_deg(a: Point, b: Point, c: Point) -> float:
    incoming = (float(b[0] - a[0]), float(b[1] - a[1]))
    outgoing = (float(c[0] - b[0]), float(c[1] - b[1]))
    norm_in = math.hypot(*incoming)
    norm_out = math.hypot(*outgoing)
    if norm_in <= 1e-9 or norm_out <= 1e-9:
        return 0.0
    dot = (incoming[0] * outgoing[0] + incoming[1] * outgoing[1]) / (norm_in * norm_out)
    dot = max(-1.0, min(1.0, dot))
    return float(math.degrees(math.acos(dot)))


def total_turn_angle_deg(points: Sequence[Point]) -> float:
    if len(points) < 3:
        return 0.0
    return float(sum(turn_angle_deg(a, b, c) for a, b, c in zip(points, points[1:], points[2:])))


def rasterize_path_coverage(shape: tuple[int, int], points: Sequence[Point], coverage_width_px: int) -> np.ndarray:
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


def path_metrics(points: Sequence[Point], free_mask: np.ndarray, *, coverage_width_px: int, long_jump_factor: float = 4.0) -> PathMetrics:
    free = np.asarray(free_mask) > 0
    coverage = rasterize_path_coverage(free.shape, points, coverage_width_px)
    covered_free_pixels = int(np.count_nonzero((coverage > 0) & free))
    free_pixels = int(np.count_nonzero(free))
    segment_lengths = _segment_lengths(points)
    long_jump_threshold_px = float(coverage_width_px) * float(long_jump_factor)
    return PathMetrics(
        point_count=int(len(points)),
        length_px=path_length_px(points),
        total_turn_angle_deg=total_turn_angle_deg(points),
        max_segment_px=float(max(segment_lengths) if segment_lengths else 0.0),
        long_jump_count=int(sum(1 for length in segment_lengths if length > long_jump_threshold_px)),
        coverage_ratio=float(covered_free_pixels / free_pixels) if free_pixels > 0 else 0.0,
        covered_free_pixels=covered_free_pixels,
        free_pixels=free_pixels,
    )


def segment_is_free(free_mask: np.ndarray, start: Point, end: Point, *, clearance_px: int) -> bool:
    shape = np.asarray(free_mask).shape[:2]
    segment = np.zeros(shape, dtype=np.uint8)
    thickness = max(1, int(clearance_px))
    cv2.line(
        segment,
        (int(round(start[0])), int(round(start[1]))),
        (int(round(end[0])), int(round(end[1]))),
        255,
        thickness,
        cv2.LINE_AA,
    )
    free = np.asarray(free_mask) > 0
    return not bool(np.any((segment > 0) & ~free))


def local_turn_before(points: Sequence[Point], index: int) -> float:
    total = 0.0
    for pivot in (index - 1, index, index + 1):
        if 0 < pivot < len(points) - 1:
            total += turn_angle_deg(points[pivot - 1], points[pivot], points[pivot + 1])
    return float(total)


def local_turn_after(points: Sequence[Point], index: int) -> float:
    candidate = tuple(points[:index]) + tuple(points[index + 1 :])
    total = 0.0
    for pivot in (index - 1, index):
        if 0 < pivot < len(candidate) - 1:
            total += turn_angle_deg(candidate[pivot - 1], candidate[pivot], candidate[pivot + 1])
    return float(total)


def simplify_path_turn_cost(
    points: Sequence[Point],
    free_mask: np.ndarray,
    config: SimplifyConfig,
) -> SimplifyResult:
    if len(points) < 3:
        before = path_metrics(points, free_mask, coverage_width_px=config.coverage_width_px)
        return SimplifyResult(tuple(points), before, before, 0, 0, 0, 0, 0, 0)

    current = list(points)
    before_metrics = path_metrics(
        current,
        free_mask,
        coverage_width_px=config.coverage_width_px,
        long_jump_factor=config.long_jump_factor,
    )
    baseline_coverage = before_metrics.coverage_ratio
    accepted = 0
    rejected_collision = 0
    rejected_coverage = 0
    rejected_jump = 0
    rejected_score = 0
    index = 1
    while index < len(current) - 1:
        prev_point = current[index - 1]
        point = current[index]
        next_point = current[index + 1]
        direct_len = path_length_px((prev_point, next_point))
        old_len = path_length_px((prev_point, point, next_point))
        if direct_len > old_len * float(config.max_shortcut_factor):
            rejected_score += 1
            index += 1
            continue
        if not segment_is_free(
            free_mask,
            prev_point,
            next_point,
            clearance_px=max(1, int(round(float(config.coverage_width_px) * 0.35))),
        ):
            rejected_collision += 1
            index += 1
            continue
        turn_improvement = local_turn_before(current, index) - local_turn_after(current, index)
        length_improvement = old_len - direct_len
        if turn_improvement < float(config.min_turn_improvement_deg) and length_improvement <= 0.0:
            rejected_score += 1
            index += 1
            continue
        candidate = current[:index] + current[index + 1 :]
        candidate_metrics = path_metrics(
            candidate,
            free_mask,
            coverage_width_px=config.coverage_width_px,
            long_jump_factor=config.long_jump_factor,
        )
        if baseline_coverage - candidate_metrics.coverage_ratio > float(config.max_coverage_drop_ratio):
            rejected_coverage += 1
            index += 1
            continue
        if not bool(config.allow_long_jump_increase):
            if candidate_metrics.long_jump_count > before_metrics.long_jump_count:
                rejected_jump += 1
                index += 1
                continue
            if candidate_metrics.max_segment_px > before_metrics.max_segment_px + 1e-6:
                rejected_jump += 1
                index += 1
                continue
        current = candidate
        accepted += 1
        index = max(1, index - 1)

    after_metrics = path_metrics(
        current,
        free_mask,
        coverage_width_px=config.coverage_width_px,
        long_jump_factor=config.long_jump_factor,
    )
    return SimplifyResult(
        points=tuple(current),
        before=before_metrics,
        after=after_metrics,
        removed_point_count=int(len(points) - len(current)),
        accepted_shortcut_count=int(accepted),
        rejected_by_collision_count=int(rejected_collision),
        rejected_by_coverage_count=int(rejected_coverage),
        rejected_by_jump_count=int(rejected_jump),
        rejected_by_score_count=int(rejected_score),
    )
