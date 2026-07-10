"""已有覆盖路径的局部轨迹线间距均匀化实验工具。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import cv2
import numpy as np

from algorithms.turn_cost_coverage_research.src.diagnostics.path_diagnostics import (
    LaneSpacingMetrics,
    LaneSpacingWindow,
    diagnose_lane_balance,
    diagnose_lane_spacing,
    group_lane_spacing_windows,
)
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import (
    Point,
    path_metrics,
    segment_is_free,
)


@dataclass(frozen=True)
class LaneBalanceConfig:
    coverage_width_px: int
    resolution_m_per_px: float
    max_coverage_drop_ratio: float = 0.002
    max_shift_factor: float = 0.75
    bbox_margin_factor: float = 2.0
    min_window_issue_count: int = 5
    max_windows: int = 3
    max_parallel_angle_deg: float = 12.0
    min_segment_length_factor: float = 0.5
    lane_cluster_factor: float = 0.35
    min_lane_segment_count: int = 1
    min_improvement_dense_count: int = 10
    max_over_sparse_increase: int = 0
    max_total_turn_increase_ratio: float = 0.02
    max_length_increase_ratio: float = 0.02
    long_jump_factor: float = 4.0


@dataclass(frozen=True)
class LaneBalanceWindowResult:
    window_id: int
    kind: str
    status: str
    reason: str
    lane_count: int
    shifted_point_count: int
    max_abs_shift_px: float
    before_over_dense_count: int
    after_over_dense_count: int
    before_median_spacing_px: float
    after_median_spacing_px: float
    bbox_xyxy: tuple[float, float, float, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": int(self.window_id),
            "kind": self.kind,
            "status": self.status,
            "reason": self.reason,
            "lane_count": int(self.lane_count),
            "shifted_point_count": int(self.shifted_point_count),
            "max_abs_shift_px": float(self.max_abs_shift_px),
            "before_over_dense_count": int(self.before_over_dense_count),
            "after_over_dense_count": int(self.after_over_dense_count),
            "before_median_spacing_px": float(self.before_median_spacing_px),
            "after_median_spacing_px": float(self.after_median_spacing_px),
            "bbox_xyxy": [float(value) for value in self.bbox_xyxy],
        }


@dataclass(frozen=True)
class LaneBalanceResult:
    points: tuple[Point, ...]
    accepted_window_count: int
    rejected_window_count: int
    before_metrics: dict[str, Any]
    after_metrics: dict[str, Any]
    before_lane_spacing: dict[str, Any]
    after_lane_spacing: dict[str, Any]
    before_lane_balance: dict[str, Any]
    after_lane_balance: dict[str, Any]
    window_results: tuple[LaneBalanceWindowResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_window_count": int(self.accepted_window_count),
            "rejected_window_count": int(self.rejected_window_count),
            "before_metrics": self.before_metrics,
            "after_metrics": self.after_metrics,
            "before_lane_spacing": self.before_lane_spacing,
            "after_lane_spacing": self.after_lane_spacing,
            "before_lane_balance": self.before_lane_balance,
            "after_lane_balance": self.after_lane_balance,
            "window_results": [result.to_dict() for result in self.window_results],
        }


@dataclass(frozen=True)
class _SegmentSample:
    index: int
    start_index: int
    end_index: int
    midpoint: Point
    angle: float
    length: float
    lateral: float


@dataclass(frozen=True)
class _LaneCluster:
    segment_indices: tuple[int, ...]
    point_indices: tuple[int, ...]
    lateral: float
    length: float


def _axis_angle_diff_rad(a: float, b: float) -> float:
    diff = abs((float(a) - float(b)) % math.pi)
    return min(diff, math.pi - diff)


def _segment_angle(start: Point, end: Point) -> float:
    return math.atan2(float(end[1] - start[1]), float(end[0] - start[0])) % math.pi


def _dominant_axis(samples: Sequence[tuple[float, float]]) -> float:
    if not samples:
        return 0.0
    sin_sum = 0.0
    cos_sum = 0.0
    for angle, weight in samples:
        sin_sum += math.sin(2.0 * float(angle)) * float(weight)
        cos_sum += math.cos(2.0 * float(angle)) * float(weight)
    return (0.5 * math.atan2(sin_sum, cos_sum)) % math.pi


def _expanded_bbox(window: LaneSpacingWindow, margin_px: float) -> tuple[float, float, float, float]:
    min_x, min_y, max_x, max_y = window.bbox_xyxy
    return (
        float(min_x) - float(margin_px),
        float(min_y) - float(margin_px),
        float(max_x) + float(margin_px),
        float(max_y) + float(margin_px),
    )


def _point_in_bbox(point: Point, bbox: tuple[float, float, float, float]) -> bool:
    return bbox[0] <= float(point[0]) <= bbox[2] and bbox[1] <= float(point[1]) <= bbox[3]


def _collect_parallel_segments(
    points: Sequence[Point],
    window: LaneSpacingWindow,
    config: LaneBalanceConfig,
) -> tuple[tuple[_SegmentSample, ...], tuple[float, float], tuple[float, float, float, float]]:
    margin = float(config.coverage_width_px) * float(config.bbox_margin_factor)
    bbox = _expanded_bbox(window, margin)
    min_length = float(config.coverage_width_px) * float(config.min_segment_length_factor)
    raw: list[tuple[int, int, int, Point, float, float]] = []
    for index, (start, end) in enumerate(zip(points, points[1:])):
        midpoint = ((float(start[0]) + float(end[0])) * 0.5, (float(start[1]) + float(end[1])) * 0.5)
        if not _point_in_bbox(midpoint, bbox):
            continue
        length = math.hypot(float(end[0] - start[0]), float(end[1] - start[1]))
        if length < min_length:
            continue
        raw.append((index, index, index + 1, midpoint, _segment_angle(start, end), length))
    dominant = _dominant_axis([(item[4], item[5]) for item in raw])
    max_angle = math.radians(float(config.max_parallel_angle_deg))
    normal = (-math.sin(dominant), math.cos(dominant))
    samples: list[_SegmentSample] = []
    for index, start_index, end_index, midpoint, angle, length in raw:
        if _axis_angle_diff_rad(angle, dominant) > max_angle:
            continue
        lateral = float(midpoint[0]) * normal[0] + float(midpoint[1]) * normal[1]
        samples.append(
            _SegmentSample(
                index=index,
                start_index=start_index,
                end_index=end_index,
                midpoint=midpoint,
                angle=angle,
                length=length,
                lateral=lateral,
            )
        )
    return tuple(samples), normal, bbox


def _cluster_lanes(samples: Sequence[_SegmentSample], config: LaneBalanceConfig) -> tuple[_LaneCluster, ...]:
    if not samples:
        return ()
    threshold = float(config.coverage_width_px) * float(config.lane_cluster_factor)
    ordered = sorted(samples, key=lambda sample: sample.lateral)
    groups: list[list[_SegmentSample]] = []
    for sample in ordered:
        if not groups or abs(float(sample.lateral) - float(np.mean([item.lateral for item in groups[-1]]))) > threshold:
            groups.append([sample])
        else:
            groups[-1].append(sample)
    clusters: list[_LaneCluster] = []
    for group in groups:
        if len(group) < int(config.min_lane_segment_count):
            continue
        point_indices = sorted({item.start_index for item in group} | {item.end_index for item in group})
        clusters.append(
            _LaneCluster(
                segment_indices=tuple(item.index for item in group),
                point_indices=tuple(point_indices),
                lateral=float(np.average([item.lateral for item in group], weights=[max(item.length, 1e-6) for item in group])),
                length=float(sum(item.length for item in group)),
            )
        )
    return tuple(sorted(clusters, key=lambda cluster: cluster.lateral))


def _candidate_shift_map(
    lanes: Sequence[_LaneCluster],
    normal: tuple[float, float],
    config: LaneBalanceConfig,
) -> tuple[dict[int, tuple[float, float]], float]:
    if len(lanes) < 3:
        return {}, 0.0
    first = float(lanes[0].lateral)
    last = float(lanes[-1].lateral)
    if abs(last - first) <= 1e-6:
        return {}, 0.0
    max_shift = float(config.coverage_width_px) * float(config.max_shift_factor)
    target_positions = np.linspace(first, last, num=len(lanes))
    point_shifts: dict[int, list[tuple[float, float]]] = {}
    max_abs_shift = 0.0
    for lane, target in zip(lanes, target_positions):
        delta = float(target) - float(lane.lateral)
        delta = max(-max_shift, min(max_shift, delta))
        if abs(delta) <= 1e-6:
            continue
        max_abs_shift = max(max_abs_shift, abs(delta))
        shift = (normal[0] * delta, normal[1] * delta)
        for point_index in lane.point_indices:
            point_shifts.setdefault(point_index, []).append(shift)
    averaged: dict[int, tuple[float, float]] = {}
    for point_index, shifts in point_shifts.items():
        averaged[point_index] = (
            float(np.mean([shift[0] for shift in shifts])),
            float(np.mean([shift[1] for shift in shifts])),
        )
    return averaged, max_abs_shift


def _apply_shift_map(points: Sequence[Point], shift_map: dict[int, tuple[float, float]]) -> tuple[Point, ...]:
    shifted: list[Point] = []
    for index, point in enumerate(points):
        shift = shift_map.get(index)
        if shift is None:
            shifted.append((float(point[0]), float(point[1])))
            continue
        shifted.append((float(point[0]) + float(shift[0]), float(point[1]) + float(shift[1])))
    return tuple(shifted)


def _filter_collision_safe_shifts(
    points: Sequence[Point],
    shift_map: dict[int, tuple[float, float]],
    free_mask: np.ndarray,
    coverage_width_px: int,
) -> dict[int, tuple[float, float]]:
    safe_shift_map = dict(shift_map)
    changed = True
    while changed and safe_shift_map:
        changed = False
        candidate = _apply_shift_map(points, safe_shift_map)
        unsafe_points: set[int] = set()
        clearance = max(1, int(round(float(coverage_width_px) * 0.35)))
        for point_index in safe_shift_map:
            affected_segments = []
            if point_index > 0:
                affected_segments.append(point_index - 1)
            if point_index < len(points) - 1:
                affected_segments.append(point_index)
            for segment_index in affected_segments:
                before_free = segment_is_free(
                    free_mask,
                    points[segment_index],
                    points[segment_index + 1],
                    clearance_px=clearance,
                )
                after_free = segment_is_free(
                    free_mask,
                    candidate[segment_index],
                    candidate[segment_index + 1],
                    clearance_px=clearance,
                )
                if before_free and not after_free:
                    unsafe_points.add(point_index)
                    break
        if unsafe_points:
            changed = True
            for point_index in unsafe_points:
                safe_shift_map.pop(point_index, None)
    return safe_shift_map


def _changed_segments_do_not_add_collision(
    before_points: Sequence[Point],
    after_points: Sequence[Point],
    changed_point_indices: set[int],
    free_mask: np.ndarray,
    coverage_width_px: int,
) -> bool:
    clearance = max(1, int(round(float(coverage_width_px) * 0.35)))
    affected_segments: set[int] = set()
    for point_index in changed_point_indices:
        if point_index > 0:
            affected_segments.add(point_index - 1)
        if point_index < len(before_points) - 1:
            affected_segments.add(point_index)
    for segment_index in affected_segments:
        before_free = segment_is_free(
            free_mask,
            before_points[segment_index],
            before_points[segment_index + 1],
            clearance_px=clearance,
        )
        after_free = segment_is_free(
            free_mask,
            after_points[segment_index],
            after_points[segment_index + 1],
            clearance_px=clearance,
        )
        if before_free and not after_free:
            return False
    return True


def _draw_lane_balance_overlay(
    free_mask: np.ndarray,
    before_points: Sequence[Point],
    after_points: Sequence[Point],
    windows: Sequence[LaneBalanceWindowResult],
    out_path: str,
) -> None:
    image = cv2.cvtColor(np.where(np.asarray(free_mask) > 0, 245, 25).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    before_pixel_points = [(int(round(x)), int(round(y))) for x, y in before_points]
    after_pixel_points = [(int(round(x)), int(round(y))) for x, y in after_points]
    for start, end in zip(before_pixel_points, before_pixel_points[1:]):
        cv2.line(image, start, end, (190, 190, 190), 1, cv2.LINE_AA)
    for start, end in zip(after_pixel_points, after_pixel_points[1:]):
        cv2.line(image, start, end, (0, 150, 255), 1, cv2.LINE_AA)
    for window in windows:
        min_x, min_y, max_x, max_y = window.bbox_xyxy
        color = (0, 180, 0) if window.status == "accepted" else (0, 0, 220)
        cv2.rectangle(
            image,
            (int(round(min_x)), int(round(min_y))),
            (int(round(max_x)), int(round(max_y))),
            color,
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            image,
            f"{window.window_id}:{window.status}",
            (int(round(min_x)), int(round(min_y)) - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )
    cv2.imwrite(out_path, image)


def balance_lane_spacing(
    points: Sequence[Point],
    free_mask: np.ndarray,
    config: LaneBalanceConfig,
    *,
    overlay_path: str | None = None,
) -> LaneBalanceResult:
    current = tuple((float(x), float(y)) for x, y in points)
    before_metrics = path_metrics(
        current,
        free_mask,
        coverage_width_px=config.coverage_width_px,
        long_jump_factor=config.long_jump_factor,
    )
    before_lane_spacing = diagnose_lane_spacing(
        current,
        coverage_width_px=config.coverage_width_px,
        resolution_m_per_px=config.resolution_m_per_px,
    )
    before_lane_balance = diagnose_lane_balance(
        current,
        coverage_width_px=config.coverage_width_px,
        resolution_m_per_px=config.resolution_m_per_px,
    )
    windows = group_lane_spacing_windows(
        before_lane_spacing,
        merge_radius_px=float(config.coverage_width_px) * 3.0,
        min_issue_count=int(config.min_window_issue_count),
    )
    selected_windows = sorted(
        [window for window in windows if window.kind == "over_dense"],
        key=lambda window: window.issue_count,
        reverse=True,
    )[: int(config.max_windows)]

    results: list[LaneBalanceWindowResult] = []
    accepted = 0
    rejected = 0
    for window in selected_windows:
        samples, normal, bbox = _collect_parallel_segments(current, window, config)
        lanes = _cluster_lanes(samples, config)
        shift_map, max_abs_shift = _candidate_shift_map(lanes, normal, config)
        shift_map = _filter_collision_safe_shifts(current, shift_map, free_mask, config.coverage_width_px)
        if not shift_map:
            rejected += 1
            results.append(
                LaneBalanceWindowResult(
                    window_id=window.window_id,
                    kind=window.kind,
                    status="rejected",
                    reason="insufficient_lane_structure",
                    lane_count=len(lanes),
                    shifted_point_count=0,
                    max_abs_shift_px=0.0,
                    before_over_dense_count=before_lane_spacing.over_dense_count,
                    after_over_dense_count=before_lane_spacing.over_dense_count,
                    before_median_spacing_px=before_lane_spacing.median_nearest_spacing_px,
                    after_median_spacing_px=before_lane_spacing.median_nearest_spacing_px,
                    bbox_xyxy=bbox,
                )
            )
            continue

        candidate = _apply_shift_map(current, shift_map)
        if not _changed_segments_do_not_add_collision(
            current,
            candidate,
            set(shift_map.keys()),
            free_mask,
            config.coverage_width_px,
        ):
            rejected += 1
            results.append(
                LaneBalanceWindowResult(
                    window_id=window.window_id,
                    kind=window.kind,
                    status="rejected",
                    reason="candidate_segment_collision",
                    lane_count=len(lanes),
                    shifted_point_count=len(shift_map),
                    max_abs_shift_px=max_abs_shift,
                    before_over_dense_count=before_lane_spacing.over_dense_count,
                    after_over_dense_count=before_lane_spacing.over_dense_count,
                    before_median_spacing_px=before_lane_spacing.median_nearest_spacing_px,
                    after_median_spacing_px=before_lane_spacing.median_nearest_spacing_px,
                    bbox_xyxy=bbox,
                )
            )
            continue

        candidate_metrics = path_metrics(
            candidate,
            free_mask,
            coverage_width_px=config.coverage_width_px,
            long_jump_factor=config.long_jump_factor,
        )
        if candidate_metrics.coverage_ratio < before_metrics.coverage_ratio - float(config.max_coverage_drop_ratio):
            rejected += 1
            results.append(
                LaneBalanceWindowResult(
                    window_id=window.window_id,
                    kind=window.kind,
                    status="rejected",
                    reason="coverage_drop_exceeds_threshold",
                    lane_count=len(lanes),
                    shifted_point_count=len(shift_map),
                    max_abs_shift_px=max_abs_shift,
                    before_over_dense_count=before_lane_spacing.over_dense_count,
                    after_over_dense_count=before_lane_spacing.over_dense_count,
                    before_median_spacing_px=before_lane_spacing.median_nearest_spacing_px,
                    after_median_spacing_px=before_lane_spacing.median_nearest_spacing_px,
                    bbox_xyxy=bbox,
                )
            )
            continue
        if candidate_metrics.long_jump_count > before_metrics.long_jump_count:
            rejected += 1
            results.append(
                LaneBalanceWindowResult(
                    window_id=window.window_id,
                    kind=window.kind,
                    status="rejected",
                    reason="long_jump_count_increased",
                    lane_count=len(lanes),
                    shifted_point_count=len(shift_map),
                    max_abs_shift_px=max_abs_shift,
                    before_over_dense_count=before_lane_spacing.over_dense_count,
                    after_over_dense_count=before_lane_spacing.over_dense_count,
                    before_median_spacing_px=before_lane_spacing.median_nearest_spacing_px,
                    after_median_spacing_px=before_lane_spacing.median_nearest_spacing_px,
                    bbox_xyxy=bbox,
                )
            )
            continue

        candidate_lane_spacing = diagnose_lane_spacing(
            candidate,
            coverage_width_px=config.coverage_width_px,
            resolution_m_per_px=config.resolution_m_per_px,
        )
        candidate_lane_balance = diagnose_lane_balance(
            candidate,
            coverage_width_px=config.coverage_width_px,
            resolution_m_per_px=config.resolution_m_per_px,
        )
        dense_improvement = int(before_lane_spacing.over_dense_count) - int(candidate_lane_spacing.over_dense_count)
        sparse_increase = int(candidate_lane_spacing.over_sparse_count) - int(before_lane_spacing.over_sparse_count)
        median_improvement = abs(float(before_lane_spacing.median_nearest_spacing_px) - float(config.coverage_width_px)) - abs(
            float(candidate_lane_spacing.median_nearest_spacing_px) - float(config.coverage_width_px)
        )
        balance_improved = (
            int(candidate_lane_balance.imbalanced_count) < int(before_lane_balance.imbalanced_count)
            or float(candidate_lane_balance.max_imbalance_px) < float(before_lane_balance.max_imbalance_px)
        )
        if not balance_improved and dense_improvement < int(config.min_improvement_dense_count):
            rejected += 1
            results.append(
                LaneBalanceWindowResult(
                    window_id=window.window_id,
                    kind=window.kind,
                    status="rejected",
                    reason="lane_balance_not_improved",
                    lane_count=len(lanes),
                    shifted_point_count=len(shift_map),
                    max_abs_shift_px=max_abs_shift,
                    before_over_dense_count=before_lane_spacing.over_dense_count,
                    after_over_dense_count=candidate_lane_spacing.over_dense_count,
                    before_median_spacing_px=before_lane_spacing.median_nearest_spacing_px,
                    after_median_spacing_px=candidate_lane_spacing.median_nearest_spacing_px,
                    bbox_xyxy=bbox,
                )
            )
            continue
        if sparse_increase > int(config.max_over_sparse_increase):
            rejected += 1
            results.append(
                LaneBalanceWindowResult(
                    window_id=window.window_id,
                    kind=window.kind,
                    status="rejected",
                    reason="over_sparse_count_increased",
                    lane_count=len(lanes),
                    shifted_point_count=len(shift_map),
                    max_abs_shift_px=max_abs_shift,
                    before_over_dense_count=before_lane_spacing.over_dense_count,
                    after_over_dense_count=candidate_lane_spacing.over_dense_count,
                    before_median_spacing_px=before_lane_spacing.median_nearest_spacing_px,
                    after_median_spacing_px=candidate_lane_spacing.median_nearest_spacing_px,
                    bbox_xyxy=bbox,
                )
            )
            continue
        if candidate_metrics.total_turn_angle_deg > before_metrics.total_turn_angle_deg * (1.0 + float(config.max_total_turn_increase_ratio)):
            rejected += 1
            results.append(
                LaneBalanceWindowResult(
                    window_id=window.window_id,
                    kind=window.kind,
                    status="rejected",
                    reason="total_turn_increase_exceeds_threshold",
                    lane_count=len(lanes),
                    shifted_point_count=len(shift_map),
                    max_abs_shift_px=max_abs_shift,
                    before_over_dense_count=before_lane_spacing.over_dense_count,
                    after_over_dense_count=candidate_lane_spacing.over_dense_count,
                    before_median_spacing_px=before_lane_spacing.median_nearest_spacing_px,
                    after_median_spacing_px=candidate_lane_spacing.median_nearest_spacing_px,
                    bbox_xyxy=bbox,
                )
            )
            continue
        if candidate_metrics.length_px > before_metrics.length_px * (1.0 + float(config.max_length_increase_ratio)):
            rejected += 1
            results.append(
                LaneBalanceWindowResult(
                    window_id=window.window_id,
                    kind=window.kind,
                    status="rejected",
                    reason="path_length_increase_exceeds_threshold",
                    lane_count=len(lanes),
                    shifted_point_count=len(shift_map),
                    max_abs_shift_px=max_abs_shift,
                    before_over_dense_count=before_lane_spacing.over_dense_count,
                    after_over_dense_count=candidate_lane_spacing.over_dense_count,
                    before_median_spacing_px=before_lane_spacing.median_nearest_spacing_px,
                    after_median_spacing_px=candidate_lane_spacing.median_nearest_spacing_px,
                    bbox_xyxy=bbox,
                )
            )
            continue
        if dense_improvement < int(config.min_improvement_dense_count) and median_improvement <= 0.0:
            rejected += 1
            results.append(
                LaneBalanceWindowResult(
                    window_id=window.window_id,
                    kind=window.kind,
                    status="rejected",
                    reason="lane_spacing_not_improved",
                    lane_count=len(lanes),
                    shifted_point_count=len(shift_map),
                    max_abs_shift_px=max_abs_shift,
                    before_over_dense_count=before_lane_spacing.over_dense_count,
                    after_over_dense_count=candidate_lane_spacing.over_dense_count,
                    before_median_spacing_px=before_lane_spacing.median_nearest_spacing_px,
                    after_median_spacing_px=candidate_lane_spacing.median_nearest_spacing_px,
                    bbox_xyxy=bbox,
                )
            )
            continue

        current = candidate
        accepted += 1
        results.append(
            LaneBalanceWindowResult(
                window_id=window.window_id,
                kind=window.kind,
                status="accepted",
                reason="accepted_by_quality_guard",
                lane_count=len(lanes),
                shifted_point_count=len(shift_map),
                max_abs_shift_px=max_abs_shift,
                before_over_dense_count=before_lane_spacing.over_dense_count,
                after_over_dense_count=candidate_lane_spacing.over_dense_count,
                before_median_spacing_px=before_lane_spacing.median_nearest_spacing_px,
                after_median_spacing_px=candidate_lane_spacing.median_nearest_spacing_px,
                bbox_xyxy=bbox,
            )
        )
        before_metrics = candidate_metrics
        before_lane_spacing = candidate_lane_spacing
        before_lane_balance = candidate_lane_balance

    after_metrics = path_metrics(
        current,
        free_mask,
        coverage_width_px=config.coverage_width_px,
        long_jump_factor=config.long_jump_factor,
    )
    after_lane_spacing = diagnose_lane_spacing(
        current,
        coverage_width_px=config.coverage_width_px,
        resolution_m_per_px=config.resolution_m_per_px,
    )
    after_lane_balance = diagnose_lane_balance(
        current,
        coverage_width_px=config.coverage_width_px,
        resolution_m_per_px=config.resolution_m_per_px,
    )
    if overlay_path is not None:
        _draw_lane_balance_overlay(free_mask, points, current, results, overlay_path)
    return LaneBalanceResult(
        points=current,
        accepted_window_count=accepted,
        rejected_window_count=rejected,
        before_metrics=path_metrics(points, free_mask, coverage_width_px=config.coverage_width_px).to_dict(),
        after_metrics=after_metrics.to_dict(),
        before_lane_spacing=diagnose_lane_spacing(
            points,
            coverage_width_px=config.coverage_width_px,
            resolution_m_per_px=config.resolution_m_per_px,
        ).to_dict(),
        after_lane_spacing=after_lane_spacing.to_dict(),
        before_lane_balance=diagnose_lane_balance(
            points,
            coverage_width_px=config.coverage_width_px,
            resolution_m_per_px=config.resolution_m_per_px,
        ).to_dict(),
        after_lane_balance=after_lane_balance.to_dict(),
        window_results=tuple(results),
    )
