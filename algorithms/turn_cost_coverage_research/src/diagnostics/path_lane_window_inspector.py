"""局部轨迹线异常窗口的只读结构检查工具。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import Point


@dataclass(frozen=True)
class LaneWindowFragment:
    start_segment_index: int
    end_segment_index: int
    segment_count: int
    point_indices: tuple[int, ...]
    length_px: float
    stroke_ids: tuple[int, ...] = ()
    segment_types: tuple[str, ...] = ()
    action_labels: tuple[str, ...] = ()
    move_source_counts: dict[str, int] | None = None
    edge_role_counts: dict[str, int] | None = None
    fragment_role: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_segment_index": int(self.start_segment_index),
            "end_segment_index": int(self.end_segment_index),
            "segment_count": int(self.segment_count),
            "point_indices": [int(value) for value in self.point_indices],
            "length_px": float(self.length_px),
            "stroke_ids": [int(value) for value in self.stroke_ids],
            "segment_types": [str(value) for value in self.segment_types],
            "action_labels": [str(value) for value in self.action_labels],
            "move_source_counts": dict(self.move_source_counts or {}),
            "edge_role_counts": dict(self.edge_role_counts or {}),
            "fragment_role": self.fragment_role,
        }


@dataclass(frozen=True)
class LaneWindowLane:
    lane_id: int
    segment_indices: tuple[int, ...]
    point_indices: tuple[int, ...]
    lateral_px: float
    length_px: float
    point_count: int
    fragment_count: int
    fragments: tuple[LaneWindowFragment, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane_id": int(self.lane_id),
            "segment_indices": [int(value) for value in self.segment_indices],
            "point_indices": [int(value) for value in self.point_indices],
            "lateral_px": float(self.lateral_px),
            "length_px": float(self.length_px),
            "point_count": int(self.point_count),
            "fragment_count": int(self.fragment_count),
            "fragments": [fragment.to_dict() for fragment in self.fragments],
        }


@dataclass(frozen=True)
class LaneWindowInspection:
    window_id: int
    bbox_xyxy: tuple[float, float, float, float]
    dominant_axis_deg: float
    segment_count: int
    lane_count: int
    gap_count: int
    min_gap_px: float
    max_gap_px: float
    median_gap_px: float
    over_dense_gap_count: int
    over_sparse_gap_count: int
    fragmented_lane_count: int
    max_lane_fragment_count: int
    rebuild_readiness: str
    recommended_action: str
    reasons: tuple[str, ...]
    lanes: tuple[LaneWindowLane, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": int(self.window_id),
            "bbox_xyxy": [float(value) for value in self.bbox_xyxy],
            "dominant_axis_deg": float(self.dominant_axis_deg),
            "segment_count": int(self.segment_count),
            "lane_count": int(self.lane_count),
            "gap_count": int(self.gap_count),
            "min_gap_px": float(self.min_gap_px),
            "max_gap_px": float(self.max_gap_px),
            "median_gap_px": float(self.median_gap_px),
            "over_dense_gap_count": int(self.over_dense_gap_count),
            "over_sparse_gap_count": int(self.over_sparse_gap_count),
            "fragmented_lane_count": int(self.fragmented_lane_count),
            "max_lane_fragment_count": int(self.max_lane_fragment_count),
            "rebuild_readiness": self.rebuild_readiness,
            "recommended_action": self.recommended_action,
            "reasons": [str(value) for value in self.reasons],
            "lanes": [lane.to_dict() for lane in self.lanes],
        }


@dataclass(frozen=True)
class _Segment:
    index: int
    start_index: int
    end_index: int
    midpoint: Point
    angle: float
    lateral: float
    length: float


def _axis_angle_diff_rad(a: float, b: float) -> float:
    diff = abs((float(a) - float(b)) % math.pi)
    return min(diff, math.pi - diff)


def _dominant_axis(segments: Sequence[tuple[float, float]]) -> float:
    if not segments:
        return 0.0
    sin_sum = 0.0
    cos_sum = 0.0
    for angle, weight in segments:
        sin_sum += math.sin(2.0 * float(angle)) * float(weight)
        cos_sum += math.cos(2.0 * float(angle)) * float(weight)
    return (0.5 * math.atan2(sin_sum, cos_sum)) % math.pi


def _point_in_bbox(point: Point, bbox: tuple[float, float, float, float]) -> bool:
    return bbox[0] <= float(point[0]) <= bbox[2] and bbox[1] <= float(point[1]) <= bbox[3]


def _count_values(values: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return counts


def _fragment_role(
    *,
    segment_types: Sequence[str],
    move_sources: Sequence[str],
    edge_roles: Sequence[str],
) -> str:
    source_set = {str(value) for value in move_sources}
    role_set = {str(value) for value in edge_roles}
    type_set = {str(value) for value in segment_types}
    if source_set & {"global_fallback", "revisit_bridge", "turn_aware_reconnect"}:
        return "connector_or_transfer"
    if role_set & {"fallback_transfer", "revisit_bridge", "local_reconnect_bridge"}:
        return "connector_or_transfer"
    if type_set == {"coverage_core"} and (not role_set or role_set <= {"coverage_lane"}):
        return "coverage_core"
    if len(type_set | role_set | source_set) > 1:
        return "mixed"
    return "unknown"


def _segment_annotation_maps(
    *,
    stroke_segments: Sequence[dict[str, Any]],
    segment_sources: Sequence[dict[str, Any]],
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    stroke_by_segment: dict[int, dict[str, Any]] = {}
    for stroke in stroke_segments:
        try:
            start = int(stroke.get("start_segment_index"))
            end = int(stroke.get("end_segment_index"))
        except (TypeError, ValueError):
            continue
        for segment_index in range(start, end + 1):
            stroke_by_segment[segment_index] = stroke
    source_by_segment: dict[int, dict[str, Any]] = {}
    for item in segment_sources:
        try:
            source_by_segment[int(item.get("segment_index"))] = item
        except (TypeError, ValueError):
            continue
    return stroke_by_segment, source_by_segment


def _lane_fragments(
    group: Sequence[_Segment],
    *,
    stroke_by_segment: dict[int, dict[str, Any]],
    source_by_segment: dict[int, dict[str, Any]],
) -> tuple[LaneWindowFragment, ...]:
    ordered = sorted(group, key=lambda item: item.index)
    if not ordered:
        return ()
    runs: list[list[_Segment]] = [[ordered[0]]]
    for segment in ordered[1:]:
        if int(segment.index) == int(runs[-1][-1].index) + 1:
            runs[-1].append(segment)
        else:
            runs.append([segment])
    fragments: list[LaneWindowFragment] = []
    for run in runs:
        point_indices = sorted({item.start_index for item in run} | {item.end_index for item in run})
        segment_indices = [int(item.index) for item in run]
        strokes = [stroke_by_segment[index] for index in segment_indices if index in stroke_by_segment]
        sources = [source_by_segment[index] for index in segment_indices if index in source_by_segment]
        stroke_ids = sorted({int(stroke.get("stroke_id")) for stroke in strokes if stroke.get("stroke_id") is not None})
        segment_types = sorted({str(stroke.get("segment_type")) for stroke in strokes if stroke.get("segment_type")})
        action_labels = sorted({str(stroke.get("action_label")) for stroke in strokes if stroke.get("action_label")})
        move_sources = [str(item.get("move_source", "unknown")) for item in sources]
        edge_roles = [str(item.get("edge_role", "unknown")) for item in sources]
        fragments.append(
            LaneWindowFragment(
                start_segment_index=int(run[0].index),
                end_segment_index=int(run[-1].index),
                segment_count=len(run),
                point_indices=tuple(point_indices),
                length_px=float(sum(item.length for item in run)),
                stroke_ids=tuple(stroke_ids),
                segment_types=tuple(segment_types),
                action_labels=tuple(action_labels),
                move_source_counts=_count_values(move_sources),
                edge_role_counts=_count_values(edge_roles),
                fragment_role=_fragment_role(
                    segment_types=segment_types,
                    move_sources=move_sources,
                    edge_roles=edge_roles,
                ),
            )
        )
    return tuple(fragments)


def _classify_rebuild_readiness(
    *,
    lane_count: int,
    gap_count: int,
    over_dense_gap_count: int,
    over_sparse_gap_count: int,
    fragmented_lane_count: int,
    max_lane_fragment_count: int,
) -> tuple[str, str, tuple[str, ...]]:
    reasons: list[str] = []
    if fragmented_lane_count > 0:
        reasons.append("fragmented_lanes_present")
    if lane_count < 3:
        reasons.append("lane_count_less_than_3")
        return "not_ready", "insufficient_lane_family", tuple(reasons)
    if gap_count <= 0:
        reasons.append("no_lateral_gap")
        return "not_ready", "insufficient_lane_family", tuple(reasons)
    if max_lane_fragment_count >= 4:
        reasons.append("severely_fragmented_lane")
        return "not_ready", "split_fragments_before_rebuild", tuple(reasons)
    if over_dense_gap_count == 0 and over_sparse_gap_count == 0:
        reasons.append("spacing_already_within_threshold")
        return "ready_for_review", "no_rebuild_needed", tuple(reasons)
    if fragmented_lane_count > max(1, lane_count // 2):
        reasons.append("too_many_fragmented_lanes")
        return "not_ready", "split_fragments_before_rebuild", tuple(reasons)
    if over_dense_gap_count > 0 and over_sparse_gap_count > 0:
        reasons.append("mixed_dense_and_sparse_gaps")
        return "ready_for_review", "lane_family_reorder_or_rebuild_candidate", tuple(reasons)
    if over_dense_gap_count > 0:
        reasons.append("over_dense_gaps_present")
        return "ready_for_review", "lane_family_spread_candidate", tuple(reasons)
    reasons.append("over_sparse_gaps_present")
    return "ready_for_review", "lane_family_fill_or_preserve_candidate", tuple(reasons)


def inspect_lane_issue_window(
    points: Sequence[Point],
    *,
    window_id: int,
    bbox_xyxy: Sequence[float],
    coverage_width_px: int,
    stroke_segments: Sequence[dict[str, Any]] = (),
    segment_sources: Sequence[dict[str, Any]] = (),
    max_parallel_angle_deg: float = 12.0,
    min_segment_length_factor: float = 0.5,
    lane_cluster_factor: float = 0.35,
) -> LaneWindowInspection:
    bbox = tuple(float(value) for value in bbox_xyxy)
    if len(bbox) != 4:
        raise ValueError("bbox_xyxy must contain four values")
    min_segment_length = float(coverage_width_px) * float(min_segment_length_factor)
    raw: list[tuple[int, int, int, Point, float, float]] = []
    for index, (start, end) in enumerate(zip(points, points[1:]), start=1):
        midpoint = ((float(start[0]) + float(end[0])) * 0.5, (float(start[1]) + float(end[1])) * 0.5)
        if not _point_in_bbox(midpoint, bbox):
            continue
        dx = float(end[0] - start[0])
        dy = float(end[1] - start[1])
        length = math.hypot(dx, dy)
        if length < min_segment_length:
            continue
        raw.append((index, index - 1, index, midpoint, math.atan2(dy, dx) % math.pi, length))

    dominant = _dominant_axis([(item[4], item[5]) for item in raw])
    normal = (-math.sin(dominant), math.cos(dominant))
    max_angle = math.radians(float(max_parallel_angle_deg))
    segments: list[_Segment] = []
    for index, start_index, end_index, midpoint, angle, length in raw:
        if _axis_angle_diff_rad(angle, dominant) > max_angle:
            continue
        lateral = float(midpoint[0]) * normal[0] + float(midpoint[1]) * normal[1]
        segments.append(
            _Segment(
                index=index,
                start_index=start_index,
                end_index=end_index,
                midpoint=midpoint,
                angle=angle,
                lateral=lateral,
                length=length,
            )
        )

    threshold = float(coverage_width_px) * float(lane_cluster_factor)
    groups: list[list[_Segment]] = []
    for segment in sorted(segments, key=lambda item: item.lateral):
        if not groups or abs(segment.lateral - float(np.mean([item.lateral for item in groups[-1]]))) > threshold:
            groups.append([segment])
        else:
            groups[-1].append(segment)

    lanes: list[LaneWindowLane] = []
    stroke_by_segment, source_by_segment = _segment_annotation_maps(
        stroke_segments=stroke_segments,
        segment_sources=segment_sources,
    )
    for lane_id, group in enumerate(groups, start=1):
        point_indices = sorted({item.start_index for item in group} | {item.end_index for item in group})
        fragments = _lane_fragments(
            group,
            stroke_by_segment=stroke_by_segment,
            source_by_segment=source_by_segment,
        )
        lanes.append(
            LaneWindowLane(
                lane_id=lane_id,
                segment_indices=tuple(item.index for item in group),
                point_indices=tuple(point_indices),
                lateral_px=float(np.average([item.lateral for item in group], weights=[max(item.length, 1e-6) for item in group])),
                length_px=float(sum(item.length for item in group)),
                point_count=len(point_indices),
                fragment_count=len(fragments),
                fragments=fragments,
            )
        )
    ordered_lanes = tuple(sorted(lanes, key=lambda item: item.lateral_px))
    gaps = [float(right.lateral_px - left.lateral_px) for left, right in zip(ordered_lanes, ordered_lanes[1:])]
    min_allowed = float(coverage_width_px) * 0.65
    max_allowed = float(coverage_width_px) * 1.35
    over_dense_gap_count = sum(1 for gap in gaps if gap < min_allowed)
    over_sparse_gap_count = sum(1 for gap in gaps if gap > max_allowed)
    fragmented_lane_count = sum(1 for lane in ordered_lanes if lane.fragment_count > 1)
    max_lane_fragment_count = max((lane.fragment_count for lane in ordered_lanes), default=0)
    readiness, action, reasons = _classify_rebuild_readiness(
        lane_count=len(ordered_lanes),
        gap_count=len(gaps),
        over_dense_gap_count=over_dense_gap_count,
        over_sparse_gap_count=over_sparse_gap_count,
        fragmented_lane_count=fragmented_lane_count,
        max_lane_fragment_count=max_lane_fragment_count,
    )

    return LaneWindowInspection(
        window_id=int(window_id),
        bbox_xyxy=bbox,  # type: ignore[arg-type]
        dominant_axis_deg=float(math.degrees(dominant)),
        segment_count=len(segments),
        lane_count=len(ordered_lanes),
        gap_count=len(gaps),
        min_gap_px=float(min(gaps) if gaps else 0.0),
        max_gap_px=float(max(gaps) if gaps else 0.0),
        median_gap_px=float(np.median(np.asarray(gaps, dtype=np.float32)) if gaps else 0.0),
        over_dense_gap_count=over_dense_gap_count,
        over_sparse_gap_count=over_sparse_gap_count,
        fragmented_lane_count=fragmented_lane_count,
        max_lane_fragment_count=max_lane_fragment_count,
        rebuild_readiness=readiness,
        recommended_action=action,
        reasons=reasons,
        lanes=ordered_lanes,
    )
