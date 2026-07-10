"""人工标注窗口与真实路径诊断数据的只读对齐工具。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from algorithms.turn_cost_coverage_research.src.diagnostics.path_lane_window_inspector import (
    inspect_lane_issue_window,
)
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import (
    Point,
    path_length_px,
    segment_is_free,
    turn_angle_deg,
)


@dataclass(frozen=True)
class AnnotatedWindow:
    window_id: str
    title: str
    category: str
    bbox_xyxy: tuple[float, float, float, float]
    user_observation: str
    scope_note: str
    allowed_analysis_scope: str


def load_annotated_windows(payload: dict[str, Any]) -> tuple[AnnotatedWindow, ...]:
    windows: list[AnnotatedWindow] = []
    for item in payload.get("windows", []):
        bbox = tuple(float(value) for value in item.get("bbox_xyxy", []))
        if len(bbox) != 4:
            raise ValueError(f"window {item.get('window_id')} bbox_xyxy must contain four values")
        if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            raise ValueError(f"window {item.get('window_id')} bbox_xyxy is invalid: {bbox}")
        windows.append(
            AnnotatedWindow(
                window_id=str(item["window_id"]),
                title=str(item.get("title", item["window_id"])),
                category=str(item.get("category", "manual_annotation")),
                bbox_xyxy=bbox,
                user_observation=str(item.get("user_observation", "")),
                scope_note=str(item.get("scope_note", "")),
                allowed_analysis_scope=str(item.get("allowed_analysis_scope", "")),
            )
        )
    return tuple(windows)


def align_annotated_windows(
    points: Sequence[Point],
    windows: Sequence[AnnotatedWindow],
    *,
    coverage_width_px: int,
    stroke_segments: Sequence[dict[str, Any]] = (),
    optimization_candidates: Sequence[dict[str, Any]] = (),
    free_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    """只做窗口对齐，不产生新的路径质量规则或优化建议。"""

    aligned = []
    for serial, window in enumerate(windows, start=1):
        aligned.append(
            _align_one_window(
                points,
                window,
                serial=serial,
                coverage_width_px=coverage_width_px,
                stroke_segments=stroke_segments,
                optimization_candidates=optimization_candidates,
                free_mask=free_mask,
            )
        )
    return {
        "scope": "manual_annotation_to_path_data_alignment",
        "note": "只读报告：人工 bbox 是观察入口，路径索引、stroke、candidate 和局部指标来自已有真实路径数据。",
        "coverage_width_px": int(coverage_width_px),
        "window_count": len(aligned),
        "windows": aligned,
    }


def _align_one_window(
    points: Sequence[Point],
    window: AnnotatedWindow,
    *,
    serial: int,
    coverage_width_px: int,
    stroke_segments: Sequence[dict[str, Any]],
    optimization_candidates: Sequence[dict[str, Any]],
    free_mask: np.ndarray | None,
) -> dict[str, Any]:
    bbox = window.bbox_xyxy
    point_indices = tuple(index for index, point in enumerate(points) if _point_in_bbox(point, bbox))
    segment_indices = tuple(
        index
        for index, (start, end) in enumerate(zip(points, points[1:]), start=1)
        if _point_in_bbox(_midpoint(start, end), bbox)
    )
    turn_items = _turn_items_in_bbox(points, bbox)
    local_segments = _local_segment_metrics(points, segment_indices, coverage_width_px=coverage_width_px, free_mask=free_mask)
    matched_strokes = _matched_strokes(stroke_segments, bbox, point_indices, segment_indices)
    matched_candidates = _matched_candidates(optimization_candidates, bbox, point_indices, segment_indices)
    lane_inspection = inspect_lane_issue_window(
        points,
        window_id=serial,
        bbox_xyxy=bbox,
        coverage_width_px=coverage_width_px,
    ).to_dict()
    lane_offsets = [float(lane["lateral_px"]) for lane in lane_inspection.get("lanes", [])]
    lane_gaps = [float(right - left) for left, right in zip(lane_offsets, lane_offsets[1:])]
    lane_inspection["lane_gap_px"] = lane_gaps
    lane_inspection["lane_gap_stats"] = _gap_stats(lane_gaps, coverage_width_px=coverage_width_px)

    return {
        "window_id": window.window_id,
        "title": window.title,
        "category": window.category,
        "bbox_xyxy": [float(value) for value in bbox],
        "user_observation": window.user_observation,
        "scope_note": window.scope_note,
        "allowed_analysis_scope": window.allowed_analysis_scope,
        "path_point_count": len(point_indices),
        "path_point_indices": [int(value) for value in point_indices],
        "path_point_index_ranges": _contiguous_ranges(point_indices),
        "path_segment_count": len(segment_indices),
        "path_segment_indices": [int(value) for value in segment_indices],
        "path_segment_index_ranges": _contiguous_ranges(segment_indices),
        "local_turn_metrics": _turn_summary(turn_items),
        "local_segment_metrics": local_segments,
        "lane_inspection": lane_inspection,
        "matched_strokes": matched_strokes,
        "matched_optimization_candidates": matched_candidates,
        "interpretation_boundary": {
            "allowed": "解释该人工窗口命中的真实路径点、线段、stroke、candidate 与局部指标。",
            "forbidden": "不得据此扩大成整段/整区问题，不得在本报告内移动点、删除点或重连路径。",
        },
    }


def _point_in_bbox(point: Point, bbox: tuple[float, float, float, float]) -> bool:
    return bbox[0] <= float(point[0]) <= bbox[2] and bbox[1] <= float(point[1]) <= bbox[3]


def _bbox_intersects(left: Sequence[float], right: Sequence[float]) -> bool:
    return not (float(left[2]) < float(right[0]) or float(left[0]) > float(right[2]) or float(left[3]) < float(right[1]) or float(left[1]) > float(right[3]))


def _midpoint(start: Point, end: Point) -> Point:
    return ((float(start[0]) + float(end[0])) * 0.5, (float(start[1]) + float(end[1])) * 0.5)


def _contiguous_ranges(indices: Sequence[int]) -> list[dict[str, int]]:
    if not indices:
        return []
    ranges: list[dict[str, int]] = []
    start = int(indices[0])
    prev = int(indices[0])
    for value in indices[1:]:
        current = int(value)
        if current == prev + 1:
            prev = current
            continue
        ranges.append({"start": start, "end": prev, "count": prev - start + 1})
        start = current
        prev = current
    ranges.append({"start": start, "end": prev, "count": prev - start + 1})
    return ranges


def _turn_items_in_bbox(points: Sequence[Point], bbox: tuple[float, float, float, float]) -> list[dict[str, float | int]]:
    items: list[dict[str, float | int]] = []
    for index in range(1, len(points) - 1):
        pivot = points[index]
        if not _point_in_bbox(pivot, bbox):
            continue
        angle = turn_angle_deg(points[index - 1], pivot, points[index + 1])
        items.append({"pivot_point_index": int(index), "turn_deg": float(angle)})
    return items


def _turn_summary(items: Sequence[dict[str, float | int]]) -> dict[str, Any]:
    turns = [float(item["turn_deg"]) for item in items]
    if not turns:
        return {
            "turn_point_count": 0,
            "total_turn_deg": 0.0,
            "mean_turn_deg": 0.0,
            "max_turn_deg": 0.0,
            "hotspot_point_indices": [],
            "items": [],
        }
    return {
        "turn_point_count": len(turns),
        "total_turn_deg": float(sum(turns)),
        "mean_turn_deg": float(sum(turns) / len(turns)),
        "max_turn_deg": float(max(turns)),
        "hotspot_point_indices": [int(item["pivot_point_index"]) for item in items if float(item["turn_deg"]) >= 30.0],
        "items": list(items),
    }


def _local_segment_metrics(
    points: Sequence[Point],
    segment_indices: Sequence[int],
    *,
    coverage_width_px: int,
    free_mask: np.ndarray | None,
) -> dict[str, Any]:
    lengths: list[float] = []
    infeasible: list[dict[str, float | int]] = []
    long_jump_threshold = float(coverage_width_px) * 4.0
    clearance = max(1, int(round(float(coverage_width_px) * 0.35)))
    for segment_index in segment_indices:
        start_index = int(segment_index) - 1
        end_index = int(segment_index)
        if start_index < 0 or end_index >= len(points):
            continue
        start = points[start_index]
        end = points[end_index]
        length = path_length_px((start, end))
        lengths.append(length)
        if free_mask is not None and not segment_is_free(free_mask, start, end, clearance_px=clearance):
            infeasible.append({"segment_index": int(segment_index), "length_px": float(length)})
    return {
        "segment_count": len(lengths),
        "total_length_px": float(sum(lengths)),
        "mean_segment_length_px": float(sum(lengths) / len(lengths)) if lengths else 0.0,
        "max_segment_length_px": float(max(lengths)) if lengths else 0.0,
        "long_jump_count": int(sum(1 for length in lengths if length > long_jump_threshold)),
        "long_jump_threshold_px": float(long_jump_threshold),
        "infeasible_segment_count": len(infeasible),
        "infeasible_segments": infeasible,
    }


def _matched_strokes(
    stroke_segments: Sequence[dict[str, Any]],
    bbox: tuple[float, float, float, float],
    point_indices: Sequence[int],
    segment_indices: Sequence[int],
) -> list[dict[str, Any]]:
    point_set = set(int(value) for value in point_indices)
    segment_set = set(int(value) for value in segment_indices)
    matched: list[dict[str, Any]] = []
    for stroke in stroke_segments:
        start_point = int(stroke.get("start_point_index", -1))
        end_point = int(stroke.get("end_point_index", -1))
        start_segment = int(stroke.get("start_segment_index", -1))
        end_segment = int(stroke.get("end_segment_index", -1))
        point_overlap = [index for index in point_set if start_point <= index <= end_point]
        segment_overlap = [index for index in segment_set if start_segment <= index <= end_segment]
        stroke_bbox = _stroke_bbox(stroke)
        if not point_overlap and not segment_overlap and (stroke_bbox is None or not _bbox_intersects(stroke_bbox, bbox)):
            continue
        matched.append(
            {
                "stroke_id": int(stroke.get("stroke_id", -1)),
                "segment_type": stroke.get("segment_type"),
                "action_label": stroke.get("action_label"),
                "classification": stroke.get("classification"),
                "problem_location": stroke.get("problem_location"),
                "score": float(stroke.get("score", 0.0)),
                "reasons": list(stroke.get("reasons", [])),
                "point_index_range": {"start": start_point, "end": end_point},
                "segment_index_range": {"start": start_segment, "end": end_segment},
                "overlap_point_count": len(point_overlap),
                "overlap_segment_count": len(segment_overlap),
                "metrics": {
                    "point_count": int(stroke.get("point_count", 0)),
                    "length_px": float(stroke.get("length_px", 0.0)),
                    "total_turn_deg": float(stroke.get("total_turn_deg", 0.0)),
                    "crossing_count": int(stroke.get("crossing_count", 0)),
                    "high_risk_crossing_count": int(stroke.get("high_risk_crossing_count", 0)),
                    "infeasible_segment_count": int(stroke.get("infeasible_segment_count", 0)),
                    "lane_spacing_issue_count": int(stroke.get("lane_spacing_issue_count", 0)),
                    "lane_balance_issue_count": int(stroke.get("lane_balance_issue_count", 0)),
                },
            }
        )
    return sorted(matched, key=lambda item: (int(item["stroke_id"])))


def _matched_candidates(
    candidates: Sequence[dict[str, Any]],
    bbox: tuple[float, float, float, float],
    point_indices: Sequence[int],
    segment_indices: Sequence[int],
) -> list[dict[str, Any]]:
    point_set = set(int(value) for value in point_indices)
    segment_set = set(int(value) for value in segment_indices)
    matched: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_bbox = candidate.get("bbox_xyxy")
        start_point = int(candidate.get("start_point_index", -1))
        end_point = int(candidate.get("end_point_index", -1))
        start_segment = int(candidate.get("start_segment_index", -1))
        end_segment = int(candidate.get("end_segment_index", -1))
        point_overlap = [index for index in point_set if start_point <= index <= end_point]
        segment_overlap = [index for index in segment_set if start_segment <= index <= end_segment]
        if not point_overlap and not segment_overlap and (
            not candidate_bbox or not _bbox_intersects(tuple(float(value) for value in candidate_bbox), bbox)
        ):
            continue
        matched.append(
            {
                "candidate_id": int(candidate.get("candidate_id", -1)),
                "stroke_id": int(candidate.get("stroke_id", -1)),
                "candidate_kind": candidate.get("candidate_kind"),
                "action_label": candidate.get("action_label"),
                "segment_type": candidate.get("segment_type"),
                "classification": candidate.get("classification"),
                "priority_score": float(candidate.get("priority_score", 0.0)),
                "bbox_xyxy": [float(value) for value in candidate.get("bbox_xyxy", [])],
                "point_index_range": {"start": start_point, "end": end_point},
                "segment_index_range": {"start": start_segment, "end": end_segment},
                "overlap_point_count": len(point_overlap),
                "overlap_segment_count": len(segment_overlap),
                "reasons": list(candidate.get("reasons", [])),
            }
        )
    return sorted(matched, key=lambda item: (int(item["candidate_id"])))


def _stroke_bbox(stroke: dict[str, Any]) -> tuple[float, float, float, float] | None:
    points = stroke.get("points") or []
    if not points:
        return None
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _gap_stats(gaps: Sequence[float], *, coverage_width_px: int) -> dict[str, float | int]:
    if not gaps:
        return {
            "gap_count": 0,
            "min_gap_px": 0.0,
            "max_gap_px": 0.0,
            "mean_gap_px": 0.0,
            "target_coverage_width_px": float(coverage_width_px),
            "max_abs_deviation_from_width_px": 0.0,
        }
    deviations = [abs(float(gap) - float(coverage_width_px)) for gap in gaps]
    return {
        "gap_count": len(gaps),
        "min_gap_px": float(min(gaps)),
        "max_gap_px": float(max(gaps)),
        "mean_gap_px": float(sum(gaps) / len(gaps)),
        "target_coverage_width_px": float(coverage_width_px),
        "max_abs_deviation_from_width_px": float(max(deviations)),
    }

