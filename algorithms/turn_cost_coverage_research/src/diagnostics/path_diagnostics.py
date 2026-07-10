"""已有覆盖路径的长跳跃与转角诊断工具。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import cv2
import numpy as np

Point = tuple[float, float]


def path_length_px(points: Sequence[Point]) -> float:
    """按相邻路径点欧氏距离累加路径长度，单位为像素。"""

    total = 0.0
    for start, end in zip(points, points[1:]):
        total += float(math.hypot(float(end[0]) - float(start[0]), float(end[1]) - float(start[1])))
    return total


def turn_angle_deg(previous: Point, current: Point, next_point: Point) -> float:
    """计算三点折线在 current 处的转角，直行为 0 度，掉头接近 180 度。"""

    v1 = (float(current[0]) - float(previous[0]), float(current[1]) - float(previous[1]))
    v2 = (float(next_point[0]) - float(current[0]), float(next_point[1]) - float(current[1]))
    norm1 = math.hypot(v1[0], v1[1])
    norm2 = math.hypot(v2[0], v2[1])
    if norm1 <= 1e-9 or norm2 <= 1e-9:
        return 0.0
    cosine = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (norm1 * norm2)))
    return float(math.degrees(math.acos(cosine)))


def rasterize_path_coverage(shape: tuple[int, int], points: Sequence[Point], coverage_width_px: int) -> np.ndarray:
    """把路径按覆盖宽度栅格化为 bool mask。"""

    coverage = np.zeros(shape, dtype=np.uint8)
    if not points:
        return coverage.astype(bool)
    radius = max(0, int(round(float(coverage_width_px) / 2.0)))
    thickness = max(1, int(round(float(coverage_width_px))))
    rounded = [(int(round(x)), int(round(y))) for x, y in points]
    for x, y in rounded:
        cv2.circle(coverage, (x, y), radius, 1, -1)
    for start, end in zip(rounded, rounded[1:]):
        cv2.line(coverage, start, end, 1, thickness)
    return coverage.astype(bool)


def segment_is_free(free_mask: np.ndarray, start: Point, end: Point, *, clearance_px: int = 0) -> bool:
    """检查线段及可选 clearance 栅格是否都落在 free_mask 内。"""

    if free_mask.size == 0:
        return False
    segment = np.zeros(free_mask.shape, dtype=np.uint8)
    p0 = (int(round(float(start[0]))), int(round(float(start[1]))))
    p1 = (int(round(float(end[0]))), int(round(float(end[1]))))
    cv2.line(segment, p0, p1, 1, 1)
    if int(clearance_px) > 0:
        kernel_size = int(clearance_px) * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        segment = cv2.dilate(segment, kernel)
    covered = segment.astype(bool)
    if not np.any(covered):
        return False
    return bool(np.all(free_mask.astype(bool)[covered]))


@dataclass(frozen=True)
class SegmentIssue:
    start_index: int
    end_index: int
    start: Point
    end: Point
    length_px: float
    length_m: float
    threshold_px: float
    kind: str
    semantic_start: dict[str, Any] | None = None
    semantic_end: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_index": int(self.start_index),
            "end_index": int(self.end_index),
            "start": [float(self.start[0]), float(self.start[1])],
            "end": [float(self.end[0]), float(self.end[1])],
            "length_px": float(self.length_px),
            "length_m": float(self.length_m),
            "threshold_px": float(self.threshold_px),
            "kind": self.kind,
            "semantic_start": self.semantic_start,
            "semantic_end": self.semantic_end,
        }


@dataclass(frozen=True)
class TurnIssue:
    index: int
    point: Point
    angle_deg: float
    window_turn_deg: float
    semantic: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": int(self.index),
            "point": [float(self.point[0]), float(self.point[1])],
            "angle_deg": float(self.angle_deg),
            "window_turn_deg": float(self.window_turn_deg),
            "semantic": self.semantic,
        }


@dataclass(frozen=True)
class PathDiagnosticResult:
    point_count: int
    length_px: float
    length_m: float
    total_turn_angle_deg: float
    long_jump_threshold_px: float
    long_jump_threshold_m: float
    long_jumps: tuple[SegmentIssue, ...]
    turn_hotspots: tuple[TurnIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "point_count": int(self.point_count),
            "length_px": float(self.length_px),
            "length_m": float(self.length_m),
            "total_turn_angle_deg": float(self.total_turn_angle_deg),
            "long_jump_threshold_px": float(self.long_jump_threshold_px),
            "long_jump_threshold_m": float(self.long_jump_threshold_m),
            "long_jump_count": int(len(self.long_jumps)),
            "turn_hotspot_count": int(len(self.turn_hotspots)),
            "long_jumps": [issue.to_dict() for issue in self.long_jumps],
            "turn_hotspots": [issue.to_dict() for issue in self.turn_hotspots],
        }


@dataclass(frozen=True)
class LocalQualityMetrics:
    coverage_ratio: float
    uncovered_component_count: int
    uncovered_component_area_px: int
    largest_uncovered_component_area_px: int
    narrow_free_pixel_count: int
    narrow_covered_pixel_count: int
    narrow_coverage_ratio: float
    repeated_coverage_pixel_count: int
    repeated_coverage_ratio: float
    over_dense_coverage_pixel_count: int
    over_dense_coverage_ratio: float
    infeasible_segment_count: int
    max_infeasible_segment_length_px: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage_ratio": float(self.coverage_ratio),
            "uncovered_component_count": int(self.uncovered_component_count),
            "uncovered_component_area_px": int(self.uncovered_component_area_px),
            "largest_uncovered_component_area_px": int(self.largest_uncovered_component_area_px),
            "narrow_free_pixel_count": int(self.narrow_free_pixel_count),
            "narrow_covered_pixel_count": int(self.narrow_covered_pixel_count),
            "narrow_coverage_ratio": float(self.narrow_coverage_ratio),
            "repeated_coverage_pixel_count": int(self.repeated_coverage_pixel_count),
            "repeated_coverage_ratio": float(self.repeated_coverage_ratio),
            "over_dense_coverage_pixel_count": int(self.over_dense_coverage_pixel_count),
            "over_dense_coverage_ratio": float(self.over_dense_coverage_ratio),
            "infeasible_segment_count": int(self.infeasible_segment_count),
            "max_infeasible_segment_length_px": float(self.max_infeasible_segment_length_px),
        }


@dataclass(frozen=True)
class LaneSpacingIssue:
    segment_index: int
    midpoint: Point
    nearest_spacing_px: float
    nearest_spacing_m: float
    target_spacing_px: float
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_index": int(self.segment_index),
            "midpoint": [float(self.midpoint[0]), float(self.midpoint[1])],
            "nearest_spacing_px": float(self.nearest_spacing_px),
            "nearest_spacing_m": float(self.nearest_spacing_m),
            "target_spacing_px": float(self.target_spacing_px),
            "kind": self.kind,
        }


@dataclass(frozen=True)
class LaneSpacingMetrics:
    evaluated_segment_count: int
    neighbor_found_count: int
    target_spacing_px: float
    min_allowed_spacing_px: float
    max_allowed_spacing_px: float
    mean_nearest_spacing_px: float
    median_nearest_spacing_px: float
    min_nearest_spacing_px: float
    max_nearest_spacing_px: float
    over_dense_count: int
    over_sparse_count: int
    issues: tuple[LaneSpacingIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluated_segment_count": int(self.evaluated_segment_count),
            "neighbor_found_count": int(self.neighbor_found_count),
            "target_spacing_px": float(self.target_spacing_px),
            "min_allowed_spacing_px": float(self.min_allowed_spacing_px),
            "max_allowed_spacing_px": float(self.max_allowed_spacing_px),
            "mean_nearest_spacing_px": float(self.mean_nearest_spacing_px),
            "median_nearest_spacing_px": float(self.median_nearest_spacing_px),
            "min_nearest_spacing_px": float(self.min_nearest_spacing_px),
            "max_nearest_spacing_px": float(self.max_nearest_spacing_px),
            "over_dense_count": int(self.over_dense_count),
            "over_sparse_count": int(self.over_sparse_count),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class LaneSpacingWindow:
    window_id: int
    kind: str
    issue_count: int
    bbox_xyxy: tuple[float, float, float, float]
    centroid: Point
    mean_spacing_px: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": int(self.window_id),
            "kind": self.kind,
            "issue_count": int(self.issue_count),
            "bbox_xyxy": [float(value) for value in self.bbox_xyxy],
            "centroid": [float(self.centroid[0]), float(self.centroid[1])],
            "mean_spacing_px": float(self.mean_spacing_px),
        }


@dataclass(frozen=True)
class LaneBalanceIssue:
    segment_index: int
    midpoint: Point
    left_spacing_px: float | None
    right_spacing_px: float | None
    imbalance_px: float | None
    target_spacing_px: float
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_index": int(self.segment_index),
            "midpoint": [float(self.midpoint[0]), float(self.midpoint[1])],
            "left_spacing_px": None if self.left_spacing_px is None else float(self.left_spacing_px),
            "right_spacing_px": None if self.right_spacing_px is None else float(self.right_spacing_px),
            "imbalance_px": None if self.imbalance_px is None else float(self.imbalance_px),
            "target_spacing_px": float(self.target_spacing_px),
            "kind": self.kind,
        }


@dataclass(frozen=True)
class LaneBalanceMetrics:
    evaluated_segment_count: int
    both_side_neighbor_count: int
    missing_left_count: int
    missing_right_count: int
    target_spacing_px: float
    imbalance_threshold_px: float
    mean_imbalance_px: float
    median_imbalance_px: float
    max_imbalance_px: float
    imbalanced_count: int
    issues: tuple[LaneBalanceIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluated_segment_count": int(self.evaluated_segment_count),
            "both_side_neighbor_count": int(self.both_side_neighbor_count),
            "missing_left_count": int(self.missing_left_count),
            "missing_right_count": int(self.missing_right_count),
            "target_spacing_px": float(self.target_spacing_px),
            "imbalance_threshold_px": float(self.imbalance_threshold_px),
            "mean_imbalance_px": float(self.mean_imbalance_px),
            "median_imbalance_px": float(self.median_imbalance_px),
            "max_imbalance_px": float(self.max_imbalance_px),
            "imbalanced_count": int(self.imbalanced_count),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class LaneBalanceWindow:
    window_id: int
    kind: str
    issue_count: int
    bbox_xyxy: tuple[float, float, float, float]
    centroid: Point
    mean_imbalance_px: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": int(self.window_id),
            "kind": self.kind,
            "issue_count": int(self.issue_count),
            "bbox_xyxy": [float(value) for value in self.bbox_xyxy],
            "centroid": [float(self.centroid[0]), float(self.centroid[1])],
            "mean_imbalance_px": None if self.mean_imbalance_px is None else float(self.mean_imbalance_px),
        }


@dataclass(frozen=True)
class LaneIssueWindow:
    window_id: int
    spacing_window_id: int
    balance_window_id: int
    spacing_kind: str
    balance_kind: str
    issue_count_score: int
    bbox_xyxy: tuple[float, float, float, float]
    centroid: Point
    overlap_area_px: float
    spacing_mean_px: float
    balance_mean_imbalance_px: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": int(self.window_id),
            "spacing_window_id": int(self.spacing_window_id),
            "balance_window_id": int(self.balance_window_id),
            "spacing_kind": self.spacing_kind,
            "balance_kind": self.balance_kind,
            "issue_count_score": int(self.issue_count_score),
            "bbox_xyxy": [float(value) for value in self.bbox_xyxy],
            "centroid": [float(self.centroid[0]), float(self.centroid[1])],
            "overlap_area_px": float(self.overlap_area_px),
            "spacing_mean_px": float(self.spacing_mean_px),
            "balance_mean_imbalance_px": (
                None if self.balance_mean_imbalance_px is None else float(self.balance_mean_imbalance_px)
            ),
        }


@dataclass(frozen=True)
class SegmentCrossingIssue:
    first_segment_index: int
    second_segment_index: int
    point: Point
    crossing_angle_deg: float
    first_length_px: float
    second_length_px: float
    first_turn_nearby_deg: float
    second_turn_nearby_deg: float
    kind: str
    risk_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_segment_index": int(self.first_segment_index),
            "second_segment_index": int(self.second_segment_index),
            "point": [float(self.point[0]), float(self.point[1])],
            "crossing_angle_deg": float(self.crossing_angle_deg),
            "first_length_px": float(self.first_length_px),
            "second_length_px": float(self.second_length_px),
            "first_turn_nearby_deg": float(self.first_turn_nearby_deg),
            "second_turn_nearby_deg": float(self.second_turn_nearby_deg),
            "kind": self.kind,
            "risk_score": float(self.risk_score),
        }


@dataclass(frozen=True)
class SegmentCrossingMetrics:
    evaluated_segment_count: int
    crossing_count: int
    high_risk_crossing_count: int
    connector_like_crossing_count: int
    mean_crossing_angle_deg: float
    issues: tuple[SegmentCrossingIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluated_segment_count": int(self.evaluated_segment_count),
            "crossing_count": int(self.crossing_count),
            "high_risk_crossing_count": int(self.high_risk_crossing_count),
            "connector_like_crossing_count": int(self.connector_like_crossing_count),
            "mean_crossing_angle_deg": float(self.mean_crossing_angle_deg),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class SegmentCrossingWindow:
    window_id: int
    issue_count: int
    high_risk_count: int
    bbox_xyxy: tuple[float, float, float, float]
    centroid: Point
    mean_risk_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": int(self.window_id),
            "issue_count": int(self.issue_count),
            "high_risk_count": int(self.high_risk_count),
            "bbox_xyxy": [float(value) for value in self.bbox_xyxy],
            "centroid": [float(self.centroid[0]), float(self.centroid[1])],
            "mean_risk_score": float(self.mean_risk_score),
        }


@dataclass(frozen=True)
class PathStrokeCutBoundary:
    after_segment_index: int
    before_point_index: int
    after_point_index: int
    point: Point
    reasons: tuple[str, ...]
    segment_length_px: float
    turn_deg: float | None
    window_turn_deg: float | None
    crossing_count: int
    high_risk_crossing_count: int
    connector_like_crossing_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "after_segment_index": int(self.after_segment_index),
            "before_point_index": int(self.before_point_index),
            "after_point_index": int(self.after_point_index),
            "point": [float(self.point[0]), float(self.point[1])],
            "reasons": list(self.reasons),
            "segment_length_px": float(self.segment_length_px),
            "turn_deg": None if self.turn_deg is None else float(self.turn_deg),
            "window_turn_deg": None if self.window_turn_deg is None else float(self.window_turn_deg),
            "crossing_count": int(self.crossing_count),
            "high_risk_crossing_count": int(self.high_risk_crossing_count),
            "connector_like_crossing_count": int(self.connector_like_crossing_count),
        }


@dataclass(frozen=True)
class PathStrokeQuality:
    stroke_id: int
    start_segment_index: int
    end_segment_index: int
    start_point_index: int
    end_point_index: int
    point_count: int
    length_px: float
    total_turn_deg: float
    mean_turn_deg: float
    max_turn_deg: float
    crossing_count: int
    high_risk_crossing_count: int
    connector_like_crossing_count: int
    lane_spacing_issue_count: int
    lane_balance_issue_count: int
    endpoint_crossing_count: int
    interior_crossing_count: int
    infeasible_segment_count: int
    max_infeasible_segment_length_px: float
    segment_type: str
    problem_location: str
    action_label: str
    classification: str
    score: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stroke_id": int(self.stroke_id),
            "start_segment_index": int(self.start_segment_index),
            "end_segment_index": int(self.end_segment_index),
            "start_point_index": int(self.start_point_index),
            "end_point_index": int(self.end_point_index),
            "point_count": int(self.point_count),
            "length_px": float(self.length_px),
            "total_turn_deg": float(self.total_turn_deg),
            "mean_turn_deg": float(self.mean_turn_deg),
            "max_turn_deg": float(self.max_turn_deg),
            "crossing_count": int(self.crossing_count),
            "high_risk_crossing_count": int(self.high_risk_crossing_count),
            "connector_like_crossing_count": int(self.connector_like_crossing_count),
            "lane_spacing_issue_count": int(self.lane_spacing_issue_count),
            "lane_balance_issue_count": int(self.lane_balance_issue_count),
            "endpoint_crossing_count": int(self.endpoint_crossing_count),
            "interior_crossing_count": int(self.interior_crossing_count),
            "infeasible_segment_count": int(self.infeasible_segment_count),
            "max_infeasible_segment_length_px": float(self.max_infeasible_segment_length_px),
            "segment_type": self.segment_type,
            "problem_location": self.problem_location,
            "action_label": self.action_label,
            "classification": self.classification,
            "score": float(self.score),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class PathStrokeQualityMetrics:
    stroke_count: int
    good_count: int
    bad_count: int
    uncertain_count: int
    good_length_ratio: float
    bad_length_ratio: float
    action_label_counts: dict[str, int]
    segment_type_counts: dict[str, int]
    cut_boundaries: tuple[PathStrokeCutBoundary, ...]
    strokes: tuple[PathStrokeQuality, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stroke_count": int(self.stroke_count),
            "good_count": int(self.good_count),
            "bad_count": int(self.bad_count),
            "uncertain_count": int(self.uncertain_count),
            "good_length_ratio": float(self.good_length_ratio),
            "bad_length_ratio": float(self.bad_length_ratio),
            "action_label_counts": dict(self.action_label_counts),
            "segment_type_counts": dict(self.segment_type_counts),
            "cut_boundary_count": int(len(self.cut_boundaries)),
            "cut_boundaries": [boundary.to_dict() for boundary in self.cut_boundaries],
            "strokes": [stroke.to_dict() for stroke in self.strokes],
        }


def _bbox_intersection_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    min_x = max(float(a[0]), float(b[0]))
    min_y = max(float(a[1]), float(b[1]))
    max_x = min(float(a[2]), float(b[2]))
    max_y = min(float(a[3]), float(b[3]))
    if max_x <= min_x or max_y <= min_y:
        return 0.0
    return float((max_x - min_x) * (max_y - min_y))


def _bbox_intersection(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    min_x = max(float(a[0]), float(b[0]))
    min_y = max(float(a[1]), float(b[1]))
    max_x = min(float(a[2]), float(b[2]))
    max_y = min(float(a[3]), float(b[3]))
    if max_x <= min_x or max_y <= min_y:
        return None
    return (min_x, min_y, max_x, max_y)


def select_lane_issue_windows(
    spacing_windows: Sequence[LaneSpacingWindow],
    balance_windows: Sequence[LaneBalanceWindow],
    *,
    centroid_merge_radius_px: float,
    max_windows: int = 10,
) -> tuple[LaneIssueWindow, ...]:
    selected: list[LaneIssueWindow] = []
    for spacing in spacing_windows:
        if spacing.kind != "over_dense":
            continue
        for balance in balance_windows:
            overlap = _bbox_intersection_area(spacing.bbox_xyxy, balance.bbox_xyxy)
            centroid_dist = math.hypot(
                float(spacing.centroid[0] - balance.centroid[0]),
                float(spacing.centroid[1] - balance.centroid[1]),
            )
            if overlap <= 0.0 and centroid_dist > float(centroid_merge_radius_px):
                continue
            intersection_bbox = _bbox_intersection(spacing.bbox_xyxy, balance.bbox_xyxy)
            if intersection_bbox is not None:
                bbox = intersection_bbox
            else:
                bbox = (
                    min(float(spacing.bbox_xyxy[0]), float(balance.bbox_xyxy[0])),
                    min(float(spacing.bbox_xyxy[1]), float(balance.bbox_xyxy[1])),
                    max(float(spacing.bbox_xyxy[2]), float(balance.bbox_xyxy[2])),
                    max(float(spacing.bbox_xyxy[3]), float(balance.bbox_xyxy[3])),
                )
            score = int(spacing.issue_count) + int(balance.issue_count)
            selected.append(
                LaneIssueWindow(
                    window_id=0,
                    spacing_window_id=spacing.window_id,
                    balance_window_id=balance.window_id,
                    spacing_kind=spacing.kind,
                    balance_kind=balance.kind,
                    issue_count_score=score,
                    bbox_xyxy=bbox,
                    centroid=(
                        float((spacing.centroid[0] + balance.centroid[0]) * 0.5),
                        float((spacing.centroid[1] + balance.centroid[1]) * 0.5),
                    ),
                    overlap_area_px=overlap,
                    spacing_mean_px=spacing.mean_spacing_px,
                    balance_mean_imbalance_px=balance.mean_imbalance_px,
                )
            )
    selected.sort(key=lambda item: (item.issue_count_score, item.overlap_area_px), reverse=True)
    return tuple(
        LaneIssueWindow(
            window_id=index,
            spacing_window_id=item.spacing_window_id,
            balance_window_id=item.balance_window_id,
            spacing_kind=item.spacing_kind,
            balance_kind=item.balance_kind,
            issue_count_score=item.issue_count_score,
            bbox_xyxy=item.bbox_xyxy,
            centroid=item.centroid,
            overlap_area_px=item.overlap_area_px,
            spacing_mean_px=item.spacing_mean_px,
            balance_mean_imbalance_px=item.balance_mean_imbalance_px,
        )
        for index, item in enumerate(selected[: int(max_windows)], start=1)
    )


def group_lane_spacing_windows(
    lane_spacing: LaneSpacingMetrics,
    *,
    merge_radius_px: float,
    min_issue_count: int = 3,
) -> tuple[LaneSpacingWindow, ...]:
    windows: list[LaneSpacingWindow] = []
    next_id = 1
    for kind in ("over_dense", "over_sparse"):
        issues = [issue for issue in lane_spacing.issues if issue.kind == kind]
        visited: set[int] = set()
        for start_index, _ in enumerate(issues):
            if start_index in visited:
                continue
            stack = [start_index]
            visited.add(start_index)
            component: list[LaneSpacingIssue] = []
            while stack:
                current_index = stack.pop()
                current = issues[current_index]
                component.append(current)
                for other_index, other in enumerate(issues):
                    if other_index in visited:
                        continue
                    if math.hypot(
                        float(other.midpoint[0] - current.midpoint[0]),
                        float(other.midpoint[1] - current.midpoint[1]),
                    ) <= float(merge_radius_px):
                        visited.add(other_index)
                        stack.append(other_index)
            if len(component) < int(min_issue_count):
                continue
            xs = [float(issue.midpoint[0]) for issue in component]
            ys = [float(issue.midpoint[1]) for issue in component]
            spacings = [float(issue.nearest_spacing_px) for issue in component]
            windows.append(
                LaneSpacingWindow(
                    window_id=next_id,
                    kind=kind,
                    issue_count=len(component),
                    bbox_xyxy=(min(xs), min(ys), max(xs), max(ys)),
                    centroid=(float(np.mean(xs)), float(np.mean(ys))),
                    mean_spacing_px=float(np.mean(spacings)),
                )
            )
            next_id += 1
    return tuple(windows)


def _segment_intersection(
    a0: Point,
    a1: Point,
    b0: Point,
    b1: Point,
    *,
    eps: float = 1e-9,
) -> Point | None:
    ax = float(a1[0] - a0[0])
    ay = float(a1[1] - a0[1])
    bx = float(b1[0] - b0[0])
    by = float(b1[1] - b0[1])
    denom = ax * by - ay * bx
    if abs(denom) <= eps:
        return None
    cx = float(b0[0] - a0[0])
    cy = float(b0[1] - a0[1])
    t = (cx * by - cy * bx) / denom
    u = (cx * ay - cy * ax) / denom
    # 端点相接通常是正常路径连接；只统计两个 segment 内部相交。
    if t <= eps or t >= 1.0 - eps or u <= eps or u >= 1.0 - eps:
        return None
    return (float(a0[0] + t * ax), float(a0[1] + t * ay))


def _segment_axis_deg(start: Point, end: Point) -> float:
    return float(math.degrees(math.atan2(float(end[1] - start[1]), float(end[0] - start[0]))) % 180.0)


def _axis_angle_distance_deg(a: float, b: float) -> float:
    diff = abs(float(a) - float(b)) % 180.0
    return float(min(diff, 180.0 - diff))


def _nearby_turn(points: Sequence[Point], segment_index: int) -> float:
    candidates: list[float] = []
    # segment_index 使用 1-based，与诊断 summary 对齐；相邻转角 pivot 为 segment 起点/终点。
    for pivot in (int(segment_index) - 1, int(segment_index)):
        if pivot <= 0 or pivot >= len(points) - 1:
            continue
        candidates.append(turn_angle_deg(points[pivot - 1], points[pivot], points[pivot + 1]))
    return float(max(candidates) if candidates else 0.0)


def diagnose_segment_crossings(
    points: Sequence[Point],
    *,
    coverage_width_px: int,
    min_segment_length_factor: float = 0.5,
    adjacent_skip: int = 1,
    connector_length_factor: float = 1.5,
    turn_hotspot_angle_deg: float = 70.0,
    high_risk_score: float = 2.0,
) -> SegmentCrossingMetrics:
    """诊断非相邻线段交叉。

    该诊断不要求交叉为零，而是把长 connector、急转附近、交叉角度大的交叉标为高风险。
    """

    min_segment_length = float(coverage_width_px) * float(min_segment_length_factor)
    connector_length = float(coverage_width_px) * float(connector_length_factor)
    segments: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(zip(points, points[1:]), start=1):
        length = path_length_px((start, end))
        if length < min_segment_length:
            continue
        segments.append(
            {
                "index": int(index),
                "start": start,
                "end": end,
                "length": float(length),
                "axis": _segment_axis_deg(start, end),
                "turn": _nearby_turn(points, index),
            }
        )

    issues: list[SegmentCrossingIssue] = []
    for i, first in enumerate(segments):
        for second in segments[i + 1:]:
            if abs(int(first["index"]) - int(second["index"])) <= int(adjacent_skip):
                continue
            point = _segment_intersection(first["start"], first["end"], second["start"], second["end"])
            if point is None:
                continue
            angle = _axis_angle_distance_deg(float(first["axis"]), float(second["axis"]))
            first_connector_like = float(first["length"]) >= connector_length
            second_connector_like = float(second["length"]) >= connector_length
            turn_nearby = max(float(first["turn"]), float(second["turn"]))
            connector_score = float(first_connector_like) + float(second_connector_like)
            turn_score = 1.0 if turn_nearby >= float(turn_hotspot_angle_deg) else 0.0
            angle_score = 1.0 if angle >= 35.0 else 0.0
            risk_score = connector_score + turn_score + angle_score
            if risk_score >= float(high_risk_score):
                kind = "high_risk"
            elif connector_score > 0.0:
                kind = "connector_like"
            else:
                kind = "ordinary"
            issues.append(
                SegmentCrossingIssue(
                    first_segment_index=int(first["index"]),
                    second_segment_index=int(second["index"]),
                    point=point,
                    crossing_angle_deg=angle,
                    first_length_px=float(first["length"]),
                    second_length_px=float(second["length"]),
                    first_turn_nearby_deg=float(first["turn"]),
                    second_turn_nearby_deg=float(second["turn"]),
                    kind=kind,
                    risk_score=risk_score,
                )
            )

    angles = np.asarray([issue.crossing_angle_deg for issue in issues], dtype=np.float32)
    return SegmentCrossingMetrics(
        evaluated_segment_count=len(segments),
        crossing_count=len(issues),
        high_risk_crossing_count=sum(1 for issue in issues if issue.kind == "high_risk"),
        connector_like_crossing_count=sum(1 for issue in issues if issue.kind in {"high_risk", "connector_like"}),
        mean_crossing_angle_deg=float(np.mean(angles)) if len(angles) else 0.0,
        issues=tuple(issues),
    )


def group_segment_crossing_windows(
    crossings: SegmentCrossingMetrics,
    *,
    merge_radius_px: float,
    min_issue_count: int = 2,
    max_windows: int = 10,
) -> tuple[SegmentCrossingWindow, ...]:
    issues = list(crossings.issues)
    visited: set[int] = set()
    windows: list[SegmentCrossingWindow] = []
    for start_index, _ in enumerate(issues):
        if start_index in visited:
            continue
        stack = [start_index]
        visited.add(start_index)
        component: list[SegmentCrossingIssue] = []
        while stack:
            current_index = stack.pop()
            current = issues[current_index]
            component.append(current)
            for other_index, other in enumerate(issues):
                if other_index in visited:
                    continue
                if math.hypot(
                    float(other.point[0] - current.point[0]),
                    float(other.point[1] - current.point[1]),
                ) <= float(merge_radius_px):
                    visited.add(other_index)
                    stack.append(other_index)
        if len(component) < int(min_issue_count):
            continue
        xs = [float(issue.point[0]) for issue in component]
        ys = [float(issue.point[1]) for issue in component]
        risks = [float(issue.risk_score) for issue in component]
        windows.append(
            SegmentCrossingWindow(
                window_id=0,
                issue_count=len(component),
                high_risk_count=sum(1 for issue in component if issue.kind == "high_risk"),
                bbox_xyxy=(min(xs), min(ys), max(xs), max(ys)),
                centroid=(float(np.mean(xs)), float(np.mean(ys))),
                mean_risk_score=float(np.mean(risks)),
            )
        )
    windows.sort(key=lambda item: (item.high_risk_count, item.issue_count, item.mean_risk_score), reverse=True)
    return tuple(
        SegmentCrossingWindow(
            window_id=index,
            issue_count=window.issue_count,
            high_risk_count=window.high_risk_count,
            bbox_xyxy=window.bbox_xyxy,
            centroid=window.centroid,
            mean_risk_score=window.mean_risk_score,
        )
        for index, window in enumerate(windows[: int(max_windows)], start=1)
    )


def _segment_count_map_from_crossings(crossings: SegmentCrossingMetrics) -> dict[int, dict[str, int]]:
    result: dict[int, dict[str, int]] = {}
    for issue in crossings.issues:
        for segment_index in (issue.first_segment_index, issue.second_segment_index):
            bucket = result.setdefault(
                int(segment_index),
                {"crossing": 0, "high_risk": 0, "connector_like": 0},
            )
            bucket["crossing"] += 1
            if issue.kind == "high_risk":
                bucket["high_risk"] += 1
            if issue.kind in {"high_risk", "connector_like"}:
                bucket["connector_like"] += 1
    return result


def _stroke_crossing_location_counts(
    crossings: SegmentCrossingMetrics,
    *,
    start_segment: int,
    end_segment: int,
    endpoint_margin_segments: int = 3,
) -> tuple[int, int]:
    endpoint_count = 0
    interior_count = 0
    start_segment = int(start_segment)
    end_segment = int(end_segment)
    endpoint_margin_segments = max(1, int(endpoint_margin_segments))
    for issue in crossings.issues:
        touched = [
            index
            for index in (int(issue.first_segment_index), int(issue.second_segment_index))
            if start_segment <= index <= end_segment
        ]
        if not touched:
            continue
        if all(
            index - start_segment < endpoint_margin_segments or end_segment - index < endpoint_margin_segments
            for index in touched
        ):
            endpoint_count += 1
        else:
            interior_count += 1
    return endpoint_count, interior_count


def _classify_stroke_type_and_action(
    *,
    length: float,
    coverage_width_px: int,
    point_count: int,
    total_turn: float,
    mean_turn: float,
    max_turn: float,
    crossing_count: int,
    high_risk_count: int,
    connector_like_count: int,
    endpoint_crossing_count: int,
    interior_crossing_count: int,
    infeasible_segment_count: int,
    max_infeasible_segment_length: float,
    spacing_count: int,
    balance_count: int,
) -> tuple[str, str, str, str, float, tuple[str, ...]]:
    reasons: list[str] = []
    score = 0.0
    coverage_width = float(max(1, int(coverage_width_px)))
    segment_count = max(1, int(point_count) - 1)
    long_enough = float(length) >= coverage_width * 2.0
    enough_points_for_core = int(point_count) >= 6
    very_short = float(length) < coverage_width * 1.25 or int(point_count) <= 2
    low_turn = float(total_turn) <= 60.0 and float(mean_turn) <= 20.0 and float(max_turn) <= 80.0
    smooth_body = long_enough and enough_points_for_core and float(mean_turn) <= 20.0 and float(max_turn) <= 80.0
    lane_issue_count = int(spacing_count) + int(balance_count)
    endpoint_only_problem = int(endpoint_crossing_count) > 0 and int(interior_crossing_count) == 0
    interior_problem = int(interior_crossing_count) > 0
    has_infeasible = int(infeasible_segment_count) > 0
    infeasible_segment_ratio = float(infeasible_segment_count) / float(segment_count)

    if smooth_body:
        segment_type = "coverage_core"
        reasons.append("coverage_core_shape")
        score += 4.0
    elif very_short:
        segment_type = "fragment"
        reasons.append("short_or_sparse_fragment")
        score -= 2.0
    elif int(connector_like_count) > 0 or float(max_turn) >= 100.0:
        segment_type = "connector"
        reasons.append("connector_like_shape")
        score -= 1.0
    elif int(crossing_count) >= 2 or float(total_turn) >= 90.0:
        segment_type = "junction_transition"
        reasons.append("junction_like_transition")
    else:
        segment_type = "coverage_core"
        reasons.append("weak_coverage_core_shape")
        score += 1.0

    if has_infeasible:
        problem_location = "whole_segment"
        reasons.append("infeasible_segment")
    elif endpoint_only_problem:
        problem_location = "endpoint"
        reasons.append("endpoint_problem")
    elif interior_problem:
        problem_location = "interior"
        reasons.append("interior_problem")
    elif int(crossing_count) > 0 or lane_issue_count > 0 or float(total_turn) > 60.0:
        problem_location = "whole_segment"
        reasons.append("whole_segment_problem")
    else:
        problem_location = "none"
        reasons.append("no_obvious_problem")

    if low_turn:
        score += 2.0
        reasons.append("low_turn")
    if int(crossing_count) == 0:
        score += 1.0
        reasons.append("no_crossing")
    if lane_issue_count <= 2:
        score += 0.5
        reasons.append("few_lane_issues")
    if int(high_risk_count) > 0:
        score -= 1.0
        reasons.append("high_risk_crossing_present")
    if int(interior_crossing_count) >= 2:
        score -= 2.0
        reasons.append("interior_crossing_cluster")
    if lane_issue_count >= 5:
        score -= 0.75
        reasons.append("many_lane_issues")
    if float(total_turn) > 135.0 or float(max_turn) > 110.0:
        score -= 1.5
        reasons.append("high_turn")
    if has_infeasible:
        if smooth_body and infeasible_segment_ratio <= 0.15:
            score -= 2.0
            reasons.append("local_infeasible_on_smooth_core")
        else:
            score -= 5.0
            reasons.append("infeasible_hard_downgrade")

    if has_infeasible:
        severe_infeasible = (
            float(max_infeasible_segment_length) >= coverage_width * 2.0
            or infeasible_segment_ratio >= 0.25
            or (not smooth_body and int(infeasible_segment_count) >= 2)
        )
        if severe_infeasible:
            action_label = "unsafe_bad"
            classification = "bad"
            reasons.append("severe_infeasible")
        elif smooth_body:
            action_label = "local_fix_candidate"
            classification = "uncertain"
            reasons.append("protect_smooth_core_with_local_issue")
        else:
            action_label = "optimize_candidate"
            classification = "uncertain"
    elif segment_type == "coverage_core":
        if problem_location == "none":
            action_label = "keep"
            classification = "good"
        elif problem_location == "endpoint":
            action_label = "endpoint_fix_candidate"
            classification = "good"
        elif int(interior_crossing_count) <= 1 and float(max_turn) <= 100.0:
            action_label = "local_fix_candidate"
            classification = "uncertain"
        else:
            action_label = "optimize_candidate"
            classification = "uncertain"
    elif segment_type == "junction_transition":
        if int(high_risk_count) >= 3 or float(max_turn) > 130.0:
            action_label = "optimize_candidate"
            classification = "uncertain"
        else:
            action_label = "local_fix_candidate"
            classification = "uncertain"
    elif segment_type == "connector":
        risky_short_connector = int(high_risk_count) >= 1 and (
            float(total_turn) >= 75.0 or int(point_count) <= 4 or float(length) <= coverage_width * 4.0
        )
        if int(high_risk_count) >= 2 or float(max_turn) > 130.0 or risky_short_connector:
            action_label = "unsafe_bad"
            classification = "bad"
            if risky_short_connector:
                reasons.append("risky_short_connector")
        else:
            action_label = "optimize_candidate"
            classification = "uncertain"
    else:
        if int(crossing_count) > 0 or float(max_turn) > 100.0:
            action_label = "unsafe_bad"
            classification = "bad"
        else:
            action_label = "optimize_candidate"
            classification = "uncertain"

    return segment_type, problem_location, action_label, classification, score, tuple(reasons)


def diagnose_path_strokes(
    points: Sequence[Point],
    *,
    coverage_width_px: int,
    crossings: SegmentCrossingMetrics,
    lane_spacing: LaneSpacingMetrics,
    lane_balance: LaneBalanceMetrics,
    free_mask: np.ndarray | None = None,
    split_turn_deg: float = 70.0,
    split_turn_delta_deg: float = 30.0,
    split_window_turn_deg: float = 30.0,
    split_window_point_count: int = 7,
    long_jump_factor: float = 4.0,
    split_high_risk_crossings: int = 2,
    split_connector_like_crossings: int = 3,
    good_min_length_factor: float = 4.0,
    bad_short_length_factor: float = 1.5,
) -> PathStrokeQualityMetrics:
    """先按路径连续性截断，再对每个 stroke 做只读分层。

    截断只使用长跳跃、急转、连续转角突变、窗口级方向突变和高风险/connector-like
    交叉这些结构性信号；lane spacing / lane balance 只参与后续质量解释，
    不作为切分边界，避免把连续 coverage core 因局部线距问题切得过碎。
    """

    if len(points) < 2:
        return PathStrokeQualityMetrics(0, 0, 0, 0, 0.0, 0.0, tuple(), tuple())

    segment_lengths = {
        index: path_length_px((start, end))
        for index, (start, end) in enumerate(zip(points, points[1:]), start=1)
    }
    crossing_counts = _segment_count_map_from_crossings(crossings)
    split_segments: list[tuple[int, int]] = []
    cut_boundaries: list[PathStrokeCutBoundary] = []
    stroke_start = 1
    long_jump_threshold = float(coverage_width_px) * float(long_jump_factor)
    pivot_turns: dict[int, float] = {
        pivot: turn_angle_deg(points[pivot - 1], points[pivot], points[pivot + 1])
        for pivot in range(1, len(points) - 1)
    }
    window_radius = max(1, int(split_window_point_count) // 2)
    window_turns: dict[int, float] = {}
    for pivot in range(window_radius, len(points) - window_radius):
        window_turns[pivot] = turn_angle_deg(
            points[pivot - window_radius],
            points[pivot],
            points[pivot + window_radius],
        )
    for segment_index in range(1, len(points)):
        length = float(segment_lengths[segment_index])
        reasons: list[str] = []
        if length > long_jump_threshold:
            reasons.append("long_jump")
        turn = pivot_turns.get(segment_index)
        if turn is not None:
            if turn >= float(split_turn_deg):
                reasons.append("sharp_turn")
            previous_turn = pivot_turns.get(segment_index - 1)
            if previous_turn is not None and abs(float(turn) - float(previous_turn)) >= float(split_turn_delta_deg):
                reasons.append("turn_delta")
        window_turn = window_turns.get(segment_index)
        if window_turn is not None and window_turn >= float(split_window_turn_deg):
            reasons.append("window_turn")
        segment_crossing = crossing_counts.get(segment_index, {})
        crossing_count = int(segment_crossing.get("crossing", 0))
        high_risk_count = int(segment_crossing.get("high_risk", 0))
        connector_like_count = int(segment_crossing.get("connector_like", 0))
        if high_risk_count >= int(split_high_risk_crossings):
            reasons.append("high_risk_crossing")
        elif connector_like_count >= int(split_connector_like_crossings):
            reasons.append("connector_like_crossing_cluster")
        if reasons and segment_index < len(points) - 1:
            split_segments.append((stroke_start, segment_index))
            cut_boundaries.append(
                PathStrokeCutBoundary(
                    after_segment_index=int(segment_index),
                    before_point_index=int(segment_index - 1),
                    after_point_index=int(segment_index),
                    point=points[segment_index],
                    reasons=tuple(reasons),
                    segment_length_px=length,
                    turn_deg=turn,
                    window_turn_deg=window_turn,
                    crossing_count=crossing_count,
                    high_risk_crossing_count=high_risk_count,
                    connector_like_crossing_count=connector_like_count,
                )
            )
            stroke_start = segment_index + 1
    if stroke_start <= len(points) - 1:
        split_segments.append((stroke_start, len(points) - 1))

    spacing_segments = {int(issue.segment_index) for issue in lane_spacing.issues}
    balance_segments = {int(issue.segment_index) for issue in lane_balance.issues}
    good_min_length = float(coverage_width_px) * float(good_min_length_factor)
    bad_short_length = float(coverage_width_px) * float(bad_short_length_factor)
    strokes: list[PathStrokeQuality] = []
    total_path_length = path_length_px(points)

    for stroke_id, (start_segment, end_segment) in enumerate(split_segments, start=1):
        segment_range = range(int(start_segment), int(end_segment) + 1)
        length = float(sum(segment_lengths[index] for index in segment_range))
        turns = [
            turn_angle_deg(points[pivot - 1], points[pivot], points[pivot + 1])
            for pivot in range(int(start_segment), int(end_segment))
            if 0 < pivot < len(points) - 1
        ]
        total_turn = float(sum(turns))
        mean_turn = float(np.mean(turns)) if turns else 0.0
        max_turn = float(max(turns) if turns else 0.0)
        crossing_count = sum(crossing_counts.get(index, {}).get("crossing", 0) for index in segment_range)
        high_risk_count = sum(crossing_counts.get(index, {}).get("high_risk", 0) for index in segment_range)
        connector_like_count = sum(crossing_counts.get(index, {}).get("connector_like", 0) for index in segment_range)
        spacing_count = sum(1 for index in segment_range if index in spacing_segments)
        balance_count = sum(1 for index in segment_range if index in balance_segments)

        endpoint_crossing_count, interior_crossing_count = _stroke_crossing_location_counts(
            crossings,
            start_segment=int(start_segment),
            end_segment=int(end_segment),
        )
        infeasible_lengths: list[float] = []
        if free_mask is not None:
            clearance = max(1, int(round(float(coverage_width_px) * 0.35)))
            for index in segment_range:
                start = points[index - 1]
                end = points[index]
                if not segment_is_free(free_mask, start, end, clearance_px=clearance):
                    infeasible_lengths.append(float(segment_lengths[index]))
        infeasible_count = len(infeasible_lengths)
        max_infeasible_length = float(max(infeasible_lengths) if infeasible_lengths else 0.0)
        segment_type, problem_location, action_label, classification, score, reasons = _classify_stroke_type_and_action(
            length=length,
            coverage_width_px=coverage_width_px,
            point_count=int(end_segment - start_segment + 2),
            total_turn=total_turn,
            mean_turn=mean_turn,
            max_turn=max_turn,
            crossing_count=int(crossing_count),
            high_risk_count=int(high_risk_count),
            connector_like_count=int(connector_like_count),
            endpoint_crossing_count=int(endpoint_crossing_count),
            interior_crossing_count=int(interior_crossing_count),
            infeasible_segment_count=int(infeasible_count),
            max_infeasible_segment_length=max_infeasible_length,
            spacing_count=int(spacing_count),
            balance_count=int(balance_count),
        )

        strokes.append(
            PathStrokeQuality(
                stroke_id=stroke_id,
                start_segment_index=int(start_segment),
                end_segment_index=int(end_segment),
                start_point_index=int(start_segment - 1),
                end_point_index=int(end_segment),
                point_count=int(end_segment - start_segment + 2),
                length_px=length,
                total_turn_deg=total_turn,
                mean_turn_deg=mean_turn,
                max_turn_deg=max_turn,
                crossing_count=int(crossing_count),
                high_risk_crossing_count=int(high_risk_count),
                connector_like_crossing_count=int(connector_like_count),
                lane_spacing_issue_count=int(spacing_count),
                lane_balance_issue_count=int(balance_count),
                endpoint_crossing_count=int(endpoint_crossing_count),
                interior_crossing_count=int(interior_crossing_count),
                infeasible_segment_count=int(infeasible_count),
                max_infeasible_segment_length_px=max_infeasible_length,
                segment_type=segment_type,
                problem_location=problem_location,
                action_label=action_label,
                classification=classification,
                score=score,
                reasons=tuple(reasons),
            )
        )

    good_length = sum(stroke.length_px for stroke in strokes if stroke.classification == "good")
    bad_length = sum(stroke.length_px for stroke in strokes if stroke.classification == "bad")
    action_label_counts = {label: sum(1 for stroke in strokes if stroke.action_label == label) for label in sorted({stroke.action_label for stroke in strokes})}
    segment_type_counts = {label: sum(1 for stroke in strokes if stroke.segment_type == label) for label in sorted({stroke.segment_type for stroke in strokes})}
    return PathStrokeQualityMetrics(
        stroke_count=len(strokes),
        good_count=sum(1 for stroke in strokes if stroke.classification == "good"),
        bad_count=sum(1 for stroke in strokes if stroke.classification == "bad"),
        uncertain_count=sum(1 for stroke in strokes if stroke.classification == "uncertain"),
        good_length_ratio=float(good_length / total_path_length) if total_path_length > 0.0 else 0.0,
        bad_length_ratio=float(bad_length / total_path_length) if total_path_length > 0.0 else 0.0,
        action_label_counts=action_label_counts,
        segment_type_counts=segment_type_counts,
        cut_boundaries=tuple(cut_boundaries),
        strokes=tuple(strokes),
    )


def group_lane_balance_windows(
    lane_balance: LaneBalanceMetrics,
    *,
    merge_radius_px: float,
    min_issue_count: int = 3,
) -> tuple[LaneBalanceWindow, ...]:
    windows: list[LaneBalanceWindow] = []
    next_id = 1
    for kind in ("imbalanced", "missing_left", "missing_right"):
        issues = [issue for issue in lane_balance.issues if issue.kind == kind]
        visited: set[int] = set()
        for start_index, _ in enumerate(issues):
            if start_index in visited:
                continue
            stack = [start_index]
            visited.add(start_index)
            component: list[LaneBalanceIssue] = []
            while stack:
                current_index = stack.pop()
                current = issues[current_index]
                component.append(current)
                for other_index, other in enumerate(issues):
                    if other_index in visited:
                        continue
                    if math.hypot(
                        float(other.midpoint[0] - current.midpoint[0]),
                        float(other.midpoint[1] - current.midpoint[1]),
                    ) <= float(merge_radius_px):
                        visited.add(other_index)
                        stack.append(other_index)
            if len(component) < int(min_issue_count):
                continue
            xs = [float(issue.midpoint[0]) for issue in component]
            ys = [float(issue.midpoint[1]) for issue in component]
            imbalances = [float(issue.imbalance_px) for issue in component if issue.imbalance_px is not None]
            windows.append(
                LaneBalanceWindow(
                    window_id=next_id,
                    kind=kind,
                    issue_count=len(component),
                    bbox_xyxy=(min(xs), min(ys), max(xs), max(ys)),
                    centroid=(float(np.mean(xs)), float(np.mean(ys))),
                    mean_imbalance_px=float(np.mean(imbalances)) if imbalances else None,
                )
            )
            next_id += 1
    return tuple(windows)


def semantic_by_baseline_index(semantic_payload: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    if not semantic_payload:
        return {}
    annotated_path = semantic_payload.get("annotated_path", [])
    if not isinstance(annotated_path, list):
        return {}
    result: dict[int, dict[str, Any]] = {}
    for item in annotated_path:
        if not isinstance(item, dict):
            continue
        baseline_index = item.get("baseline_index")
        if baseline_index is None:
            continue
        result[int(baseline_index)] = {
            "node_role": item.get("node_role"),
            "primary_space_type": item.get("primary_space_type"),
            "primary_territory_label": item.get("primary_territory_label"),
            "primary_junction_id": item.get("primary_junction_id"),
            "coverage_obligation": item.get("coverage_obligation"),
            "connectivity_value": item.get("connectivity_value"),
        }
    return result


def _window_turn(points: Sequence[Point], index: int, radius: int) -> float:
    start = max(1, int(index) - int(radius))
    end = min(len(points) - 1, int(index) + int(radius))
    return float(sum(turn_angle_deg(points[pivot - 1], points[pivot], points[pivot + 1]) for pivot in range(start, end)))


def diagnose_path(
    points: Sequence[Point],
    *,
    resolution_m_per_px: float,
    coverage_width_px: int,
    long_jump_factor: float = 4.0,
    turn_hotspot_angle_deg: float = 70.0,
    turn_hotspot_window_radius: int = 2,
    semantic_index: dict[int, dict[str, Any]] | None = None,
) -> PathDiagnosticResult:
    semantics = semantic_index or {}
    threshold_px = float(coverage_width_px) * float(long_jump_factor)
    long_jumps: list[SegmentIssue] = []
    for zero_index, (start, end) in enumerate(zip(points, points[1:])):
        length_px = path_length_px((start, end))
        if length_px <= threshold_px:
            continue
        baseline_start = zero_index + 1
        baseline_end = zero_index + 2
        long_jumps.append(
            SegmentIssue(
                start_index=baseline_start,
                end_index=baseline_end,
                start=start,
                end=end,
                length_px=length_px,
                length_m=length_px * float(resolution_m_per_px),
                threshold_px=threshold_px,
                kind="long_jump",
                semantic_start=semantics.get(baseline_start),
                semantic_end=semantics.get(baseline_end),
            )
        )

    turn_hotspots: list[TurnIssue] = []
    for zero_index in range(1, len(points) - 1):
        angle = turn_angle_deg(points[zero_index - 1], points[zero_index], points[zero_index + 1])
        if angle < float(turn_hotspot_angle_deg):
            continue
        baseline_index = zero_index + 1
        turn_hotspots.append(
            TurnIssue(
                index=baseline_index,
                point=points[zero_index],
                angle_deg=angle,
                window_turn_deg=_window_turn(points, zero_index, int(turn_hotspot_window_radius)),
                semantic=semantics.get(baseline_index),
            )
        )

    total_turn = float(sum(turn_angle_deg(a, b, c) for a, b, c in zip(points, points[1:], points[2:])))
    length_px = path_length_px(points)
    return PathDiagnosticResult(
        point_count=len(points),
        length_px=length_px,
        length_m=length_px * float(resolution_m_per_px),
        total_turn_angle_deg=total_turn,
        long_jump_threshold_px=threshold_px,
        long_jump_threshold_m=threshold_px * float(resolution_m_per_px),
        long_jumps=tuple(long_jumps),
        turn_hotspots=tuple(turn_hotspots),
    )


def _axis_angle_diff_rad(a: float, b: float) -> float:
    diff = abs((float(a) - float(b)) % math.pi)
    return min(diff, math.pi - diff)


def diagnose_lane_spacing(
    points: Sequence[Point],
    *,
    coverage_width_px: int,
    resolution_m_per_px: float,
    min_spacing_factor: float = 0.65,
    max_spacing_factor: float = 1.35,
    max_parallel_angle_deg: float = 12.0,
    min_segment_length_factor: float = 0.5,
    longitudinal_window_factor: float = 4.0,
    search_radius_factor: float = 3.0,
    same_lane_lateral_factor: float = 0.25,
) -> LaneSpacingMetrics:
    target = float(coverage_width_px)
    min_allowed = target * float(min_spacing_factor)
    max_allowed = target * float(max_spacing_factor)
    min_segment_length = target * float(min_segment_length_factor)
    longitudinal_window = target * float(longitudinal_window_factor)
    search_radius = target * float(search_radius_factor)
    same_lane_lateral = target * float(same_lane_lateral_factor)
    max_angle = math.radians(float(max_parallel_angle_deg))

    segments: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(zip(points, points[1:]), start=1):
        dx = float(end[0] - start[0])
        dy = float(end[1] - start[1])
        length = math.hypot(dx, dy)
        if length < min_segment_length:
            continue
        tx = dx / length
        ty = dy / length
        angle = math.atan2(ty, tx) % math.pi
        segments.append(
            {
                "index": index,
                "mid": ((float(start[0]) + float(end[0])) * 0.5, (float(start[1]) + float(end[1])) * 0.5),
                "tangent": (tx, ty),
                "normal": (-ty, tx),
                "angle": angle,
            }
        )

    nearest_values: list[float] = []
    issues: list[LaneSpacingIssue] = []
    for segment in segments:
        mid = segment["mid"]
        tangent = segment["tangent"]
        normal = segment["normal"]
        nearest = float("inf")
        for other in segments:
            if int(other["index"]) == int(segment["index"]):
                continue
            if _axis_angle_diff_rad(float(segment["angle"]), float(other["angle"])) > max_angle:
                continue
            delta = (float(other["mid"][0] - mid[0]), float(other["mid"][1] - mid[1]))
            longitudinal = abs(delta[0] * tangent[0] + delta[1] * tangent[1])
            lateral = abs(delta[0] * normal[0] + delta[1] * normal[1])
            if lateral <= same_lane_lateral or lateral > search_radius:
                continue
            if longitudinal > longitudinal_window:
                continue
            nearest = min(nearest, lateral)
        if not math.isfinite(nearest):
            continue
        nearest_values.append(float(nearest))
        if nearest < min_allowed:
            issues.append(
                LaneSpacingIssue(
                    segment_index=int(segment["index"]),
                    midpoint=mid,
                    nearest_spacing_px=nearest,
                    nearest_spacing_m=nearest * float(resolution_m_per_px),
                    target_spacing_px=target,
                    kind="over_dense",
                )
            )
        elif nearest > max_allowed:
            issues.append(
                LaneSpacingIssue(
                    segment_index=int(segment["index"]),
                    midpoint=mid,
                    nearest_spacing_px=nearest,
                    nearest_spacing_m=nearest * float(resolution_m_per_px),
                    target_spacing_px=target,
                    kind="over_sparse",
                )
            )

    values = np.asarray(nearest_values, dtype=np.float32)
    return LaneSpacingMetrics(
        evaluated_segment_count=len(segments),
        neighbor_found_count=len(nearest_values),
        target_spacing_px=target,
        min_allowed_spacing_px=min_allowed,
        max_allowed_spacing_px=max_allowed,
        mean_nearest_spacing_px=float(np.mean(values)) if len(values) else 0.0,
        median_nearest_spacing_px=float(np.median(values)) if len(values) else 0.0,
        min_nearest_spacing_px=float(np.min(values)) if len(values) else 0.0,
        max_nearest_spacing_px=float(np.max(values)) if len(values) else 0.0,
        over_dense_count=sum(1 for issue in issues if issue.kind == "over_dense"),
        over_sparse_count=sum(1 for issue in issues if issue.kind == "over_sparse"),
        issues=tuple(issues),
    )


def diagnose_lane_balance(
    points: Sequence[Point],
    *,
    coverage_width_px: int,
    resolution_m_per_px: float,
    max_parallel_angle_deg: float = 12.0,
    min_segment_length_factor: float = 0.5,
    longitudinal_window_factor: float = 4.0,
    search_radius_factor: float = 3.0,
    same_lane_lateral_factor: float = 0.25,
    imbalance_factor: float = 0.5,
) -> LaneBalanceMetrics:
    _ = resolution_m_per_px
    target = float(coverage_width_px)
    min_segment_length = target * float(min_segment_length_factor)
    longitudinal_window = target * float(longitudinal_window_factor)
    search_radius = target * float(search_radius_factor)
    same_lane_lateral = target * float(same_lane_lateral_factor)
    max_angle = math.radians(float(max_parallel_angle_deg))
    imbalance_threshold = target * float(imbalance_factor)

    segments: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(zip(points, points[1:]), start=1):
        dx = float(end[0] - start[0])
        dy = float(end[1] - start[1])
        length = math.hypot(dx, dy)
        if length < min_segment_length:
            continue
        tx = dx / length
        ty = dy / length
        angle = math.atan2(ty, tx) % math.pi
        segments.append(
            {
                "index": index,
                "mid": ((float(start[0]) + float(end[0])) * 0.5, (float(start[1]) + float(end[1])) * 0.5),
                "tangent": (tx, ty),
                "normal": (-ty, tx),
                "angle": angle,
            }
        )

    imbalances: list[float] = []
    issues: list[LaneBalanceIssue] = []
    both_side_count = 0
    missing_left_count = 0
    missing_right_count = 0
    for segment in segments:
        mid = segment["mid"]
        tangent = segment["tangent"]
        normal = segment["normal"]
        left: float | None = None
        right: float | None = None
        for other in segments:
            if int(other["index"]) == int(segment["index"]):
                continue
            if _axis_angle_diff_rad(float(segment["angle"]), float(other["angle"])) > max_angle:
                continue
            delta = (float(other["mid"][0] - mid[0]), float(other["mid"][1] - mid[1]))
            longitudinal = abs(delta[0] * tangent[0] + delta[1] * tangent[1])
            signed_lateral = delta[0] * normal[0] + delta[1] * normal[1]
            lateral = abs(signed_lateral)
            if lateral <= same_lane_lateral or lateral > search_radius:
                continue
            if longitudinal > longitudinal_window:
                continue
            if signed_lateral > 0.0:
                left = lateral if left is None else min(left, lateral)
            else:
                right = lateral if right is None else min(right, lateral)
        if left is None and right is None:
            continue
        if left is None:
            missing_left_count += 1
            issues.append(
                LaneBalanceIssue(
                    segment_index=int(segment["index"]),
                    midpoint=mid,
                    left_spacing_px=None,
                    right_spacing_px=right,
                    imbalance_px=None,
                    target_spacing_px=target,
                    kind="missing_left",
                )
            )
            continue
        if right is None:
            missing_right_count += 1
            issues.append(
                LaneBalanceIssue(
                    segment_index=int(segment["index"]),
                    midpoint=mid,
                    left_spacing_px=left,
                    right_spacing_px=None,
                    imbalance_px=None,
                    target_spacing_px=target,
                    kind="missing_right",
                )
            )
            continue
        both_side_count += 1
        imbalance = abs(float(left) - float(right))
        imbalances.append(imbalance)
        if imbalance > imbalance_threshold:
            issues.append(
                LaneBalanceIssue(
                    segment_index=int(segment["index"]),
                    midpoint=mid,
                    left_spacing_px=left,
                    right_spacing_px=right,
                    imbalance_px=imbalance,
                    target_spacing_px=target,
                    kind="imbalanced",
                )
            )

    values = np.asarray(imbalances, dtype=np.float32)
    return LaneBalanceMetrics(
        evaluated_segment_count=len(segments),
        both_side_neighbor_count=both_side_count,
        missing_left_count=missing_left_count,
        missing_right_count=missing_right_count,
        target_spacing_px=target,
        imbalance_threshold_px=imbalance_threshold,
        mean_imbalance_px=float(np.mean(values)) if len(values) else 0.0,
        median_imbalance_px=float(np.median(values)) if len(values) else 0.0,
        max_imbalance_px=float(np.max(values)) if len(values) else 0.0,
        imbalanced_count=sum(1 for issue in issues if issue.kind == "imbalanced"),
        issues=tuple(issues),
    )


def rasterize_path_visit_count(shape: tuple[int, int], points: Sequence[Point], coverage_width_px: int) -> np.ndarray:
    visits = np.zeros(shape, dtype=np.uint16)
    if not points:
        return visits
    thickness = max(1, int(round(float(coverage_width_px))))
    radius = max(1, int(round(float(coverage_width_px) * 0.5)))
    pixel_points = [(int(round(x)), int(round(y))) for x, y in points]
    for point in pixel_points:
        layer = np.zeros(shape, dtype=np.uint8)
        cv2.circle(layer, point, radius, 1, -1, cv2.LINE_8)
        visits += layer.astype(np.uint16)
    for start, end in zip(pixel_points, pixel_points[1:]):
        layer = np.zeros(shape, dtype=np.uint8)
        cv2.line(layer, start, end, 1, thickness, cv2.LINE_8)
        visits += layer.astype(np.uint16)
    return visits


def diagnose_local_quality(
    points: Sequence[Point],
    free_mask: np.ndarray,
    *,
    coverage_width_px: int,
    uncovered_min_area_px: int | None = None,
    narrow_distance_factor: float = 1.0,
    repeated_visit_threshold: int = 2,
    over_dense_visit_threshold: int = 4,
) -> LocalQualityMetrics:
    free = np.asarray(free_mask) > 0
    free_pixels = int(np.count_nonzero(free))
    coverage = rasterize_path_coverage(free.shape, points, coverage_width_px)
    covered = (coverage > 0) & free
    uncovered = free & ~covered
    min_area = int(uncovered_min_area_px if uncovered_min_area_px is not None else max(1, int(coverage_width_px) ** 2))

    component_count = 0
    component_area = 0
    largest_component = 0
    label_count, labels, stats, _ = cv2.connectedComponentsWithStats(uncovered.astype(np.uint8), connectivity=8)
    for label in range(1, label_count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        component_count += 1
        component_area += area
        largest_component = max(largest_component, area)

    distance = cv2.distanceTransform(free.astype(np.uint8), cv2.DIST_L2, 3)
    narrow_mask = free & (distance > 0.0) & (distance <= float(coverage_width_px) * float(narrow_distance_factor))
    narrow_pixels = int(np.count_nonzero(narrow_mask))
    narrow_covered = int(np.count_nonzero(narrow_mask & covered))

    visits = rasterize_path_visit_count(free.shape, points, coverage_width_px)
    repeated = free & (visits >= int(repeated_visit_threshold))
    over_dense = free & (visits >= int(over_dense_visit_threshold))

    infeasible_lengths: list[float] = []
    clearance = max(1, int(round(float(coverage_width_px) * 0.35)))
    for start, end in zip(points, points[1:]):
        if not segment_is_free(free_mask, start, end, clearance_px=clearance):
            infeasible_lengths.append(path_length_px((start, end)))

    return LocalQualityMetrics(
        coverage_ratio=float(np.count_nonzero(covered) / free_pixels) if free_pixels else 0.0,
        uncovered_component_count=component_count,
        uncovered_component_area_px=component_area,
        largest_uncovered_component_area_px=largest_component,
        narrow_free_pixel_count=narrow_pixels,
        narrow_covered_pixel_count=narrow_covered,
        narrow_coverage_ratio=float(narrow_covered / narrow_pixels) if narrow_pixels else 0.0,
        repeated_coverage_pixel_count=int(np.count_nonzero(repeated)),
        repeated_coverage_ratio=float(np.count_nonzero(repeated) / free_pixels) if free_pixels else 0.0,
        over_dense_coverage_pixel_count=int(np.count_nonzero(over_dense)),
        over_dense_coverage_ratio=float(np.count_nonzero(over_dense) / free_pixels) if free_pixels else 0.0,
        infeasible_segment_count=len(infeasible_lengths),
        max_infeasible_segment_length_px=float(max(infeasible_lengths) if infeasible_lengths else 0.0),
    )


def draw_path_diagnostic_overlay(
    free_mask: np.ndarray,
    points: Sequence[Point],
    diagnostics: PathDiagnosticResult,
    out_path: str,
) -> None:
    image = cv2.cvtColor(np.where(free_mask > 0, 245, 25).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    pixel_points = [(int(round(x)), int(round(y))) for x, y in points]
    for start, end in zip(pixel_points, pixel_points[1:]):
        cv2.line(image, start, end, (170, 170, 170), 1, cv2.LINE_AA)
    for issue in diagnostics.long_jumps:
        start = (int(round(issue.start[0])), int(round(issue.start[1])))
        end = (int(round(issue.end[0])), int(round(issue.end[1])))
        cv2.line(image, start, end, (0, 0, 255), 3, cv2.LINE_AA)
        mid = (int(round((issue.start[0] + issue.end[0]) * 0.5)), int(round((issue.start[1] + issue.end[1]) * 0.5)))
        cv2.putText(image, str(issue.start_index), mid, cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2, cv2.LINE_AA)
    for issue in diagnostics.turn_hotspots:
        point = (int(round(issue.point[0])), int(round(issue.point[1])))
        cv2.circle(image, point, 5, (0, 165, 255), -1, cv2.LINE_AA)
    if pixel_points:
        cv2.circle(image, pixel_points[0], 7, (0, 180, 0), -1, cv2.LINE_AA)
        cv2.circle(image, pixel_points[-1], 7, (255, 0, 0), -1, cv2.LINE_AA)
    cv2.imwrite(out_path, image)


def draw_local_quality_overlay(
    free_mask: np.ndarray,
    points: Sequence[Point],
    *,
    coverage_width_px: int,
    out_path: str,
) -> None:
    free = np.asarray(free_mask) > 0
    coverage = rasterize_path_coverage(free.shape, points, coverage_width_px)
    covered = (coverage > 0) & free
    uncovered = free & ~covered
    visits = rasterize_path_visit_count(free.shape, points, coverage_width_px)
    image = np.zeros((*free.shape, 3), dtype=np.uint8)
    image[free] = (235, 235, 235)
    image[covered] = (90, 150, 210)
    image[uncovered] = (40, 40, 230)
    image[free & (visits >= 2)] = (80, 180, 220)
    image[free & (visits >= 4)] = (0, 120, 255)
    pixel_points = [(int(round(x)), int(round(y))) for x, y in points]
    for start, end in zip(pixel_points, pixel_points[1:]):
        cv2.line(image, start, end, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.imwrite(out_path, image)


def draw_lane_spacing_overlay(
    free_mask: np.ndarray,
    points: Sequence[Point],
    lane_spacing: LaneSpacingMetrics,
    *,
    out_path: str,
) -> None:
    image = cv2.cvtColor(np.where(np.asarray(free_mask) > 0, 245, 25).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    pixel_points = [(int(round(x)), int(round(y))) for x, y in points]
    for start, end in zip(pixel_points, pixel_points[1:]):
        cv2.line(image, start, end, (190, 190, 190), 1, cv2.LINE_AA)
    for issue in lane_spacing.issues:
        point = (int(round(issue.midpoint[0])), int(round(issue.midpoint[1])))
        color = (0, 0, 255) if issue.kind == "over_dense" else (255, 0, 0)
        cv2.circle(image, point, 5, color, -1, cv2.LINE_AA)
    cv2.imwrite(out_path, image)


def draw_lane_balance_overlay(
    free_mask: np.ndarray,
    points: Sequence[Point],
    lane_balance: LaneBalanceMetrics,
    *,
    out_path: str,
) -> None:
    image = cv2.cvtColor(np.where(np.asarray(free_mask) > 0, 245, 25).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    pixel_points = [(int(round(x)), int(round(y))) for x, y in points]
    for start, end in zip(pixel_points, pixel_points[1:]):
        cv2.line(image, start, end, (190, 190, 190), 1, cv2.LINE_AA)
    for issue in lane_balance.issues:
        point = (int(round(issue.midpoint[0])), int(round(issue.midpoint[1])))
        if issue.kind == "imbalanced":
            color = (0, 0, 255)
        elif issue.kind == "missing_left":
            color = (255, 0, 0)
        else:
            color = (0, 165, 255)
        cv2.circle(image, point, 5, color, -1, cv2.LINE_AA)
    cv2.imwrite(out_path, image)


def draw_segment_crossing_overlay(
    free_mask: np.ndarray,
    points: Sequence[Point],
    crossings: SegmentCrossingMetrics,
    *,
    out_path: str,
) -> None:
    image = cv2.cvtColor(np.where(np.asarray(free_mask) > 0, 245, 25).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    pixel_points = [(int(round(x)), int(round(y))) for x, y in points]
    for start, end in zip(pixel_points, pixel_points[1:]):
        cv2.line(image, start, end, (185, 185, 185), 1, cv2.LINE_AA)
    for issue in crossings.issues:
        point = (int(round(issue.point[0])), int(round(issue.point[1])))
        if issue.kind == "high_risk":
            color = (0, 0, 255)
            radius = 6
        elif issue.kind == "connector_like":
            color = (0, 165, 255)
            radius = 5
        else:
            color = (255, 0, 0)
            radius = 4
        cv2.circle(image, point, radius, color, -1, cv2.LINE_AA)
    cv2.imwrite(out_path, image)


def draw_path_stroke_quality_overlay(
    free_mask: np.ndarray,
    points: Sequence[Point],
    stroke_quality: PathStrokeQualityMetrics,
    *,
    out_path: str,
) -> None:
    image = cv2.cvtColor(np.where(np.asarray(free_mask) > 0, 245, 25).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    pixel_points = [(int(round(x)), int(round(y))) for x, y in points]
    colors = {
        "keep": (40, 170, 40),
        "endpoint_fix_candidate": (80, 210, 120),
        "local_fix_candidate": (0, 180, 255),
        "optimize_candidate": (0, 120, 255),
        "unsafe_bad": (0, 0, 255),
    }
    for stroke in stroke_quality.strokes:
        color = colors.get(stroke.action_label, (160, 160, 160))
        thickness = 2 if stroke.action_label == "keep" else 3
        start = max(0, int(stroke.start_segment_index) - 1)
        end = min(len(pixel_points) - 1, int(stroke.end_segment_index))
        for index in range(start, end):
            cv2.line(image, pixel_points[index], pixel_points[index + 1], color, thickness, cv2.LINE_AA)
        if start < len(pixel_points):
            cv2.putText(
                image,
                str(stroke.stroke_id),
                pixel_points[start],
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                color,
                1,
                cv2.LINE_AA,
            )
    cv2.imwrite(out_path, image)


def draw_path_stroke_segments_overlay(
    free_mask: np.ndarray,
    points: Sequence[Point],
    stroke_quality: PathStrokeQualityMetrics,
    *,
    out_path: str,
) -> None:
    """只显示路径截断结果，不叠加 good/bad/uncertain 质量判断。"""

    image = cv2.cvtColor(np.where(np.asarray(free_mask) > 0, 245, 25).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    pixel_points = [(int(round(x)), int(round(y))) for x, y in points]
    palette = [
        (230, 25, 75),
        (60, 180, 75),
        (255, 225, 25),
        (0, 130, 200),
        (245, 130, 48),
        (145, 30, 180),
        (70, 240, 240),
        (240, 50, 230),
        (210, 245, 60),
        (250, 190, 190),
        (0, 128, 128),
        (230, 190, 255),
        (170, 110, 40),
        (255, 250, 200),
        (128, 0, 0),
        (170, 255, 195),
        (0, 0, 128),
    ]
    for stroke in stroke_quality.strokes:
        color = palette[(int(stroke.stroke_id) - 1) % len(palette)]
        start = max(0, int(stroke.start_segment_index) - 1)
        end = min(len(pixel_points) - 1, int(stroke.end_segment_index))
        for index in range(start, end):
            cv2.line(image, pixel_points[index], pixel_points[index + 1], color, 3, cv2.LINE_AA)
        if 0 <= start < len(pixel_points):
            cv2.circle(image, pixel_points[start], 3, color, -1, cv2.LINE_AA)
    cv2.imwrite(out_path, image)
