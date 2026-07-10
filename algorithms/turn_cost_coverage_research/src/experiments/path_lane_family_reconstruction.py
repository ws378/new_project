"""lane family 局部重建候选计划。

该模块只生成候选计划，不移动路径点。真正改路径前必须再经过覆盖、
碰撞、长跳、转角和 provenance 守卫。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np


@dataclass(frozen=True)
class LaneFamilyLanePlan:
    lane_id: int
    lateral_px: float
    target_lateral_px: float
    proposed_shift_px: float
    clipped_shift_px: float
    movable: bool
    lock_reason: str
    reject_reasons: tuple[str, ...]
    fragment_roles: tuple[str, ...]
    fragment_count: int
    stroke_ids: tuple[int, ...]
    segment_index_ranges: tuple[tuple[int, int], ...]
    point_indices: tuple[int, ...]
    segment_indices: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane_id": int(self.lane_id),
            "lateral_px": float(self.lateral_px),
            "target_lateral_px": float(self.target_lateral_px),
            "proposed_shift_px": float(self.proposed_shift_px),
            "clipped_shift_px": float(self.clipped_shift_px),
            "movable": bool(self.movable),
            "lock_reason": self.lock_reason,
            "reject_reasons": [str(value) for value in self.reject_reasons],
            "fragment_roles": [str(value) for value in self.fragment_roles],
            "fragment_count": int(self.fragment_count),
            "stroke_ids": [int(value) for value in self.stroke_ids],
            "segment_index_ranges": [[int(a), int(b)] for a, b in self.segment_index_ranges],
            "point_indices": [int(value) for value in self.point_indices],
            "segment_indices": [int(value) for value in self.segment_indices],
        }


@dataclass(frozen=True)
class LaneFamilyGapPlan:
    left_lane_id: int
    right_lane_id: int
    before_gap_px: float
    after_gap_px: float
    before_kind: str
    after_kind: str
    left_movable: bool
    right_movable: bool
    left_fragment_roles: tuple[str, ...]
    right_fragment_roles: tuple[str, ...]
    blocker_reasons: tuple[str, ...]
    recommended_next_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_lane_id": int(self.left_lane_id),
            "right_lane_id": int(self.right_lane_id),
            "before_gap_px": float(self.before_gap_px),
            "after_gap_px": float(self.after_gap_px),
            "before_kind": self.before_kind,
            "after_kind": self.after_kind,
            "left_movable": bool(self.left_movable),
            "right_movable": bool(self.right_movable),
            "left_fragment_roles": [str(value) for value in self.left_fragment_roles],
            "right_fragment_roles": [str(value) for value in self.right_fragment_roles],
            "blocker_reasons": [str(value) for value in self.blocker_reasons],
            "recommended_next_action": self.recommended_next_action,
        }


@dataclass(frozen=True)
class LaneFamilyWindowPlan:
    window_id: int
    status: str
    reason: str
    recommended_action: str
    lane_count: int
    movable_lane_count: int
    locked_lane_count: int
    before_bad_gap_count: int
    after_bad_gap_count: int
    max_abs_shift_px: float
    lane_plans: tuple[LaneFamilyLanePlan, ...]
    gap_plans: tuple[LaneFamilyGapPlan, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": int(self.window_id),
            "status": self.status,
            "reason": self.reason,
            "recommended_action": self.recommended_action,
            "lane_count": int(self.lane_count),
            "movable_lane_count": int(self.movable_lane_count),
            "locked_lane_count": int(self.locked_lane_count),
            "before_bad_gap_count": int(self.before_bad_gap_count),
            "after_bad_gap_count": int(self.after_bad_gap_count),
            "max_abs_shift_px": float(self.max_abs_shift_px),
            "lane_plans": [plan.to_dict() for plan in self.lane_plans],
            "gap_plans": [plan.to_dict() for plan in self.gap_plans],
        }


@dataclass(frozen=True)
class LaneFamilyTargetStrategyEvaluation:
    window_id: int
    strategy: str
    prediction_status: str
    reason: str
    lane_count: int
    movable_lane_count: int
    shift_exceeds_limit_count: int
    locked_lane_shift_required_count: int
    changed_locked_lane_count: int
    before_bad_gap_count: int
    before_over_dense_count: int
    before_over_sparse_count: int
    predicted_bad_gap_count: int
    predicted_over_dense_count: int
    predicted_over_sparse_count: int
    max_abs_shift_px: float
    target_laterals_px: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": int(self.window_id),
            "strategy": self.strategy,
            "prediction_status": self.prediction_status,
            "reason": self.reason,
            "lane_count": int(self.lane_count),
            "movable_lane_count": int(self.movable_lane_count),
            "shift_exceeds_limit_count": int(self.shift_exceeds_limit_count),
            "locked_lane_shift_required_count": int(self.locked_lane_shift_required_count),
            "changed_locked_lane_count": int(self.changed_locked_lane_count),
            "before_bad_gap_count": int(self.before_bad_gap_count),
            "before_over_dense_count": int(self.before_over_dense_count),
            "before_over_sparse_count": int(self.before_over_sparse_count),
            "predicted_bad_gap_count": int(self.predicted_bad_gap_count),
            "predicted_over_dense_count": int(self.predicted_over_dense_count),
            "predicted_over_sparse_count": int(self.predicted_over_sparse_count),
            "max_abs_shift_px": float(self.max_abs_shift_px),
            "target_laterals_px": [float(value) for value in self.target_laterals_px],
        }


@dataclass(frozen=True)
class LaneFamilyPathApplyResult:
    status: str
    reason: str
    window_id: int
    target_strategy: str
    changed_point_count: int
    conflicting_point_count: int
    max_point_shift_px: float
    points: tuple[tuple[float, float], ...]
    applied_lanes: tuple[int, ...]
    skipped_lanes: tuple[int, ...]
    conflicts: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "window_id": int(self.window_id),
            "target_strategy": self.target_strategy,
            "changed_point_count": int(self.changed_point_count),
            "conflicting_point_count": int(self.conflicting_point_count),
            "max_point_shift_px": float(self.max_point_shift_px),
            "applied_lanes": [int(value) for value in self.applied_lanes],
            "skipped_lanes": [int(value) for value in self.skipped_lanes],
            "conflicts": [dict(value) for value in self.conflicts],
        }


@dataclass(frozen=True)
class LaneFamilyTimeGroup:
    group_id: int
    window_id: int
    status: str
    reason: str
    next_review_action: str
    start_segment_index: int
    end_segment_index: int
    segment_span: int
    covered_segment_count: int
    segment_density: float
    lane_count: int
    fragment_count: int
    point_count: int
    stroke_ids: tuple[int, ...]
    lane_ids: tuple[int, ...]
    fragment_roles: tuple[str, ...]
    segment_types: tuple[str, ...]
    action_labels: tuple[str, ...]
    move_source_counts: dict[str, int]
    edge_role_counts: dict[str, int]
    source_evidence_level: str
    max_internal_gap: int
    segment_indices: tuple[int, ...]
    point_indices: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": int(self.group_id),
            "window_id": int(self.window_id),
            "status": self.status,
            "reason": self.reason,
            "next_review_action": self.next_review_action,
            "start_segment_index": int(self.start_segment_index),
            "end_segment_index": int(self.end_segment_index),
            "segment_span": int(self.segment_span),
            "covered_segment_count": int(self.covered_segment_count),
            "segment_density": float(self.segment_density),
            "lane_count": int(self.lane_count),
            "fragment_count": int(self.fragment_count),
            "point_count": int(self.point_count),
            "stroke_ids": [int(value) for value in self.stroke_ids],
            "lane_ids": [int(value) for value in self.lane_ids],
            "fragment_roles": [str(value) for value in self.fragment_roles],
            "segment_types": [str(value) for value in self.segment_types],
            "action_labels": [str(value) for value in self.action_labels],
            "move_source_counts": dict(self.move_source_counts),
            "edge_role_counts": dict(self.edge_role_counts),
            "source_evidence_level": self.source_evidence_level,
            "max_internal_gap": int(self.max_internal_gap),
            "segment_indices": [int(value) for value in self.segment_indices],
            "point_indices": [int(value) for value in self.point_indices],
        }


@dataclass(frozen=True)
class LaneFamilyTimeGroupAnalysis:
    window_id: int
    rebuild_readiness: str
    recommended_action: str
    status: str
    reason: str
    group_count: int
    review_candidate_count: int
    total_covered_segment_count: int
    full_segment_span: int
    full_segment_density: float
    groups: tuple[LaneFamilyTimeGroup, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": int(self.window_id),
            "rebuild_readiness": self.rebuild_readiness,
            "recommended_action": self.recommended_action,
            "status": self.status,
            "reason": self.reason,
            "group_count": int(self.group_count),
            "review_candidate_count": int(self.review_candidate_count),
            "rebuild_candidate_count": int(self.review_candidate_count),
            "total_covered_segment_count": int(self.total_covered_segment_count),
            "full_segment_span": int(self.full_segment_span),
            "full_segment_density": float(self.full_segment_density),
            "groups": [group.to_dict() for group in self.groups],
        }


@dataclass(frozen=True)
class LaneFamilyTimeGroupCandidate:
    candidate_rank: int
    window_id: int
    group_id: int
    status: str
    reason: str
    next_review_action: str
    priority_score: float
    connector_adjacency_count: int
    mixed_adjacency_count: int
    nearest_non_coverage_gap: int | None
    covered_segment_count: int
    segment_span: int
    segment_density: float
    start_segment_index: int
    end_segment_index: int
    lane_ids: tuple[int, ...]
    stroke_ids: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_rank": int(self.candidate_rank),
            "window_id": int(self.window_id),
            "group_id": int(self.group_id),
            "status": self.status,
            "reason": self.reason,
            "next_review_action": self.next_review_action,
            "priority_score": float(self.priority_score),
            "connector_adjacency_count": int(self.connector_adjacency_count),
            "mixed_adjacency_count": int(self.mixed_adjacency_count),
            "nearest_non_coverage_gap": (
                None if self.nearest_non_coverage_gap is None else int(self.nearest_non_coverage_gap)
            ),
            "covered_segment_count": int(self.covered_segment_count),
            "segment_span": int(self.segment_span),
            "segment_density": float(self.segment_density),
            "start_segment_index": int(self.start_segment_index),
            "end_segment_index": int(self.end_segment_index),
            "lane_ids": [int(value) for value in self.lane_ids],
            "stroke_ids": [int(value) for value in self.stroke_ids],
        }


@dataclass(frozen=True)
class _TimeFragment:
    lane_id: int
    start_segment_index: int
    end_segment_index: int
    segment_indices: tuple[int, ...]
    point_indices: tuple[int, ...]
    stroke_ids: tuple[int, ...]
    fragment_role: str
    segment_types: tuple[str, ...]
    action_labels: tuple[str, ...]
    move_source_counts: dict[str, int]
    edge_role_counts: dict[str, int]


def _gap_kind(gap_px: float, *, coverage_width_px: int, min_factor: float, max_factor: float) -> str:
    target = float(coverage_width_px)
    if float(gap_px) < target * float(min_factor):
        return "over_dense"
    if float(gap_px) > target * float(max_factor):
        return "over_sparse"
    return "ok"


def _lane_reject_reasons(lane: dict[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    fragments = list(lane.get("fragments", []))
    if not fragments:
        return ("no_fragment",)
    roles = {str(fragment.get("fragment_role", "unknown")) for fragment in fragments}
    if roles != {"coverage_core"}:
        reasons.append("non_coverage_core_fragment")
    if any(int(fragment.get("segment_count", 0)) <= 0 for fragment in fragments):
        reasons.append("empty_fragment")
    return tuple(reasons)


def _target_laterals(laterals: Sequence[float], *, coverage_width_px: int, strategy: str) -> tuple[float, ...]:
    if not laterals:
        return ()
    ordered = [float(value) for value in laterals]
    if strategy == "linspace_full_range":
        return tuple(float(value) for value in np.linspace(ordered[0], ordered[-1], num=len(ordered)))
    if strategy == "coverage_width_from_first":
        direction = 1.0 if ordered[-1] >= ordered[0] else -1.0
        return tuple(ordered[0] + direction * float(coverage_width_px) * index for index in range(len(ordered)))
    if strategy == "coverage_width_from_median_anchor":
        center = len(ordered) // 2
        anchor = ordered[center]
        return tuple(anchor + float(coverage_width_px) * (index - center) for index in range(len(ordered)))
    if strategy == "preserve_current":
        return tuple(ordered)
    raise ValueError(f"unknown lane target strategy: {strategy}")


def _fragment_segment_indices(fragment: dict[str, Any]) -> tuple[int, ...]:
    start = int(fragment.get("start_segment_index", -1))
    end = int(fragment.get("end_segment_index", -1))
    if start < 0 or end < start:
        return ()
    return tuple(range(start, end + 1))


def _time_fragments(inspection: dict[str, Any]) -> tuple[_TimeFragment, ...]:
    fragments: list[_TimeFragment] = []
    for lane in inspection.get("lanes", []):
        lane_id = int(lane.get("lane_id", -1))
        for fragment in lane.get("fragments", []):
            segment_indices = _fragment_segment_indices(fragment)
            if not segment_indices:
                continue
            fragments.append(
                _TimeFragment(
                    lane_id=lane_id,
                    start_segment_index=min(segment_indices),
                    end_segment_index=max(segment_indices),
                    segment_indices=segment_indices,
                    point_indices=tuple(int(value) for value in fragment.get("point_indices", [])),
                    stroke_ids=tuple(sorted({int(value) for value in fragment.get("stroke_ids", [])})),
                    fragment_role=str(fragment.get("fragment_role", "unknown")),
                    segment_types=tuple(sorted({str(value) for value in fragment.get("segment_types", [])})),
                    action_labels=tuple(sorted({str(value) for value in fragment.get("action_labels", [])})),
                    move_source_counts={
                        str(key): int(value)
                        for key, value in dict(fragment.get("move_source_counts", {}) or {}).items()
                    },
                    edge_role_counts={
                        str(key): int(value)
                        for key, value in dict(fragment.get("edge_role_counts", {}) or {}).items()
                    },
                )
            )
    return tuple(sorted(fragments, key=lambda item: (item.start_segment_index, item.end_segment_index, item.lane_id)))


def _merge_counts(items: Sequence[dict[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for item in items:
        for key, value in item.items():
            merged[str(key)] = merged.get(str(key), 0) + int(value)
    return merged


def _source_evidence_level(move_source_counts: dict[str, int], edge_role_counts: dict[str, int]) -> str:
    if move_source_counts or edge_role_counts:
        return "provenance_segment_source"
    return "stroke_only"


def _time_fragments_compatible(left: _TimeFragment, right: _TimeFragment, *, max_segment_gap: int) -> bool:
    if int(right.start_segment_index) - int(left.end_segment_index) > int(max_segment_gap):
        return False
    if int(left.lane_id) != int(right.lane_id):
        return False
    if set(left.stroke_ids) != set(right.stroke_ids):
        return False
    if left.fragment_role != right.fragment_role:
        return False
    if set(left.segment_types) != set(right.segment_types):
        return False
    if set(left.action_labels) != set(right.action_labels):
        return False
    if dict(left.move_source_counts) != dict(right.move_source_counts):
        return False
    if dict(left.edge_role_counts) != dict(right.edge_role_counts):
        return False
    return True


def _time_group_status(
    *,
    segment_count: int,
    fragment_roles: set[str],
    source_evidence_level: str,
    max_internal_gap: int,
    max_segment_gap: int,
    min_segments_for_review: int,
) -> tuple[str, str, str]:
    if fragment_roles - {"coverage_core"}:
        if "connector_or_transfer" in fragment_roles:
            return "review_only", "contains_connector_or_transfer", "inspect_as_connector_group"
        return "review_only", "contains_non_coverage_fragment", "split_mixed_group_by_source"
    if source_evidence_level != "provenance_segment_source":
        return "review_only", "missing_segment_source_provenance", "inspect_source_mapping_before_rebuild"
    if segment_count < int(min_segments_for_review):
        return "not_ready", "too_few_segments", "not_rebuildable_temporal_fragment"
    if max_internal_gap > int(max_segment_gap):
        return "not_ready", "not_time_continuous", "not_rebuildable_temporal_fragment"
    return "review_candidate", "time_continuous_coverage_core_group", "inspect_as_strip_group"


def analyze_lane_family_time_groups(
    inspection: dict[str, Any],
    *,
    max_segment_gap: int = 3,
    min_segments_for_review: int = 3,
) -> LaneFamilyTimeGroupAnalysis:
    window_id = int(inspection.get("window_id", -1))
    rebuild_readiness = str(inspection.get("rebuild_readiness", "unknown"))
    recommended_action = str(inspection.get("recommended_action", "unknown"))
    fragments = _time_fragments(inspection)
    if not fragments:
        return LaneFamilyTimeGroupAnalysis(
            window_id=window_id,
            rebuild_readiness=rebuild_readiness,
            recommended_action=recommended_action,
            status="skipped",
            reason="no_time_fragment",
            group_count=0,
            review_candidate_count=0,
            total_covered_segment_count=0,
            full_segment_span=0,
            full_segment_density=0.0,
            groups=(),
        )

    raw_groups: list[list[_TimeFragment]] = [[fragments[0]]]
    for fragment in fragments[1:]:
        if _time_fragments_compatible(raw_groups[-1][-1], fragment, max_segment_gap=max_segment_gap):
            raw_groups[-1].append(fragment)
        else:
            raw_groups.append([fragment])

    groups: list[LaneFamilyTimeGroup] = []
    all_segments = sorted({index for fragment in fragments for index in fragment.segment_indices})
    full_span = int(max(all_segments) - min(all_segments) + 1) if all_segments else 0
    full_density = float(len(all_segments) / full_span) if full_span else 0.0
    for group_id, group in enumerate(raw_groups, start=1):
        segment_indices = sorted({index for fragment in group for index in fragment.segment_indices})
        point_indices = sorted({index for fragment in group for index in fragment.point_indices})
        lane_ids = sorted({fragment.lane_id for fragment in group})
        stroke_ids = sorted({stroke for fragment in group for stroke in fragment.stroke_ids})
        fragment_roles = {fragment.fragment_role for fragment in group}
        segment_types = sorted({segment_type for fragment in group for segment_type in fragment.segment_types})
        action_labels = sorted({label for fragment in group for label in fragment.action_labels})
        move_source_counts = _merge_counts([fragment.move_source_counts for fragment in group])
        edge_role_counts = _merge_counts([fragment.edge_role_counts for fragment in group])
        source_evidence = _source_evidence_level(move_source_counts, edge_role_counts)
        internal_gaps = [right - left for left, right in zip(segment_indices, segment_indices[1:])]
        max_internal_gap = max(internal_gaps, default=0)
        segment_span = int(max(segment_indices) - min(segment_indices) + 1) if segment_indices else 0
        status, reason, next_review_action = _time_group_status(
            segment_count=len(segment_indices),
            fragment_roles=fragment_roles,
            source_evidence_level=source_evidence,
            max_internal_gap=max_internal_gap,
            max_segment_gap=max_segment_gap,
            min_segments_for_review=min_segments_for_review,
        )
        groups.append(
            LaneFamilyTimeGroup(
                group_id=group_id,
                window_id=window_id,
                status=status,
                reason=reason,
                next_review_action=next_review_action,
                start_segment_index=int(min(segment_indices)),
                end_segment_index=int(max(segment_indices)),
                segment_span=segment_span,
                covered_segment_count=len(segment_indices),
                segment_density=float(len(segment_indices) / segment_span) if segment_span else 0.0,
                lane_count=len(lane_ids),
                fragment_count=len(group),
                point_count=len(point_indices),
                stroke_ids=tuple(stroke_ids),
                lane_ids=tuple(lane_ids),
                fragment_roles=tuple(sorted(fragment_roles)),
                segment_types=tuple(segment_types),
                action_labels=tuple(action_labels),
                move_source_counts=move_source_counts,
                edge_role_counts=edge_role_counts,
                source_evidence_level=source_evidence,
                max_internal_gap=max_internal_gap,
                segment_indices=tuple(segment_indices),
                point_indices=tuple(point_indices),
            )
        )
    review_count = sum(1 for group in groups if group.status == "review_candidate")
    return LaneFamilyTimeGroupAnalysis(
        window_id=window_id,
        rebuild_readiness=rebuild_readiness,
        recommended_action=recommended_action,
        status="has_review_candidate" if review_count > 0 else "no_review_candidate",
        reason="time_group_analysis_generated",
        group_count=len(groups),
        review_candidate_count=review_count,
        total_covered_segment_count=len(all_segments),
        full_segment_span=full_span,
        full_segment_density=full_density,
        groups=tuple(groups),
    )


def _group_gap(left: dict[str, Any], right: dict[str, Any]) -> int:
    if int(left["end_segment_index"]) < int(right["start_segment_index"]):
        return int(right["start_segment_index"]) - int(left["end_segment_index"])
    if int(right["end_segment_index"]) < int(left["start_segment_index"]):
        return int(left["start_segment_index"]) - int(right["end_segment_index"])
    return 0


def rank_lane_family_time_group_candidates(
    analyses: Sequence[dict[str, Any]],
    *,
    adjacency_gap: int = 3,
    min_preferred_segments: int = 5,
) -> tuple[LaneFamilyTimeGroupCandidate, ...]:
    candidates: list[LaneFamilyTimeGroupCandidate] = []
    for analysis in analyses:
        groups = list(analysis.get("groups", []))
        for group in groups:
            if str(group.get("status")) != "review_candidate":
                continue
            nearby_non_coverage = [
                other
                for other in groups
                if int(other.get("group_id", -1)) != int(group.get("group_id", -1))
                and set(other.get("fragment_roles", [])) - {"coverage_core"}
                and _group_gap(group, other) <= int(adjacency_gap)
            ]
            connector_count = sum(
                1
                for other in nearby_non_coverage
                if "connector_or_transfer" in {str(value) for value in other.get("fragment_roles", [])}
            )
            mixed_count = sum(
                1
                for other in nearby_non_coverage
                if "mixed" in {str(value) for value in other.get("fragment_roles", [])}
            )
            nearest_gap = min((_group_gap(group, other) for other in nearby_non_coverage), default=None)
            segment_count = int(group.get("covered_segment_count", 0))
            density = float(group.get("segment_density", 0.0))
            score = float(segment_count) + density * 2.0
            score -= float(connector_count) * 8.0
            score -= float(mixed_count) * 4.0
            if segment_count < int(min_preferred_segments):
                status = "short_review_candidate"
                reason = "segment_count_below_preferred"
                score -= 2.0
            elif connector_count > 0:
                status = "connector_adjacent_review_candidate"
                reason = "near_connector_or_transfer_group"
            elif mixed_count > 0:
                status = "mixed_adjacent_review_candidate"
                reason = "near_mixed_group"
            else:
                status = "low_risk_strip_review_candidate"
                reason = "time_continuous_coverage_core_without_nearby_non_coverage"
                score += 3.0
            candidates.append(
                LaneFamilyTimeGroupCandidate(
                    candidate_rank=0,
                    window_id=int(analysis.get("window_id", -1)),
                    group_id=int(group.get("group_id", -1)),
                    status=status,
                    reason=reason,
                    next_review_action=str(group.get("next_review_action", "")),
                    priority_score=score,
                    connector_adjacency_count=connector_count,
                    mixed_adjacency_count=mixed_count,
                    nearest_non_coverage_gap=nearest_gap,
                    covered_segment_count=segment_count,
                    segment_span=int(group.get("segment_span", 0)),
                    segment_density=density,
                    start_segment_index=int(group.get("start_segment_index", -1)),
                    end_segment_index=int(group.get("end_segment_index", -1)),
                    lane_ids=tuple(int(value) for value in group.get("lane_ids", [])),
                    stroke_ids=tuple(int(value) for value in group.get("stroke_ids", [])),
                )
            )
    candidates.sort(key=lambda item: (-float(item.priority_score), int(item.window_id), int(item.group_id)))
    return tuple(
        LaneFamilyTimeGroupCandidate(
            candidate_rank=rank,
            window_id=item.window_id,
            group_id=item.group_id,
            status=item.status,
            reason=item.reason,
            next_review_action=item.next_review_action,
            priority_score=item.priority_score,
            connector_adjacency_count=item.connector_adjacency_count,
            mixed_adjacency_count=item.mixed_adjacency_count,
            nearest_non_coverage_gap=item.nearest_non_coverage_gap,
            covered_segment_count=item.covered_segment_count,
            segment_span=item.segment_span,
            segment_density=item.segment_density,
            start_segment_index=item.start_segment_index,
            end_segment_index=item.end_segment_index,
            lane_ids=item.lane_ids,
            stroke_ids=item.stroke_ids,
        )
        for rank, item in enumerate(candidates, start=1)
    )


def _gap_blocker_reasons(left: LaneFamilyLanePlan, right: LaneFamilyLanePlan, *, before_kind: str) -> tuple[str, ...]:
    reasons: list[str] = []
    if before_kind == "ok":
        return ()
    if not left.movable:
        reasons.extend(f"left_{reason}" for reason in left.reject_reasons)
    if not right.movable:
        reasons.extend(f"right_{reason}" for reason in right.reject_reasons)
    roles = set(left.fragment_roles) | set(right.fragment_roles)
    if roles - {"coverage_core"}:
        reasons.append("non_coverage_fragment_adjacent")
    if not reasons:
        reasons.append("movable_coverage_core_gap")
    return tuple(dict.fromkeys(reasons))


def _gap_next_action(before_kind: str, blocker_reasons: Sequence[str]) -> str:
    if before_kind == "ok":
        return "preserve"
    reason_set = {str(value) for value in blocker_reasons}
    if "non_coverage_fragment_adjacent" in reason_set:
        return "peel_connector_or_mixed_fragment_first"
    if before_kind == "over_sparse":
        return "fill_or_preserve_gap"
    if any("shift_exceeds_limit" in reason for reason in reason_set):
        return "requires_nonlocal_lane_rebuild"
    if before_kind == "over_dense":
        return "spread_coverage_core_gap_candidate"
    return "inspect_gap"


def generate_lane_family_window_plan(
    inspection: dict[str, Any],
    *,
    coverage_width_px: int,
    max_shift_factor: float = 0.5,
    min_gap_factor: float = 0.65,
    max_gap_factor: float = 1.35,
    target_strategy: str = "linspace_full_range",
) -> LaneFamilyWindowPlan:
    window_id = int(inspection.get("window_id", -1))
    if str(inspection.get("rebuild_readiness")) != "ready_for_review":
        return LaneFamilyWindowPlan(
            window_id=window_id,
            status="skipped",
            reason="inspection_not_ready_for_review",
            recommended_action=str(inspection.get("recommended_action", "")),
            lane_count=int(inspection.get("lane_count", 0)),
            movable_lane_count=0,
            locked_lane_count=int(inspection.get("lane_count", 0)),
            before_bad_gap_count=0,
            after_bad_gap_count=0,
            max_abs_shift_px=0.0,
            lane_plans=(),
            gap_plans=(),
        )
    recommended_action = str(inspection.get("recommended_action", ""))
    if recommended_action == "no_rebuild_needed":
        return LaneFamilyWindowPlan(
            window_id=window_id,
            status="skipped",
            reason="no_rebuild_needed",
            recommended_action=recommended_action,
            lane_count=int(inspection.get("lane_count", 0)),
            movable_lane_count=0,
            locked_lane_count=int(inspection.get("lane_count", 0)),
            before_bad_gap_count=0,
            after_bad_gap_count=0,
            max_abs_shift_px=0.0,
            lane_plans=(),
            gap_plans=(),
        )
    if recommended_action == "lane_family_fill_or_preserve_candidate":
        return LaneFamilyWindowPlan(
            window_id=window_id,
            status="rejected",
            reason="requires_fill_or_preserve_not_shift",
            recommended_action=recommended_action,
            lane_count=int(inspection.get("lane_count", 0)),
            movable_lane_count=0,
            locked_lane_count=int(inspection.get("lane_count", 0)),
            before_bad_gap_count=0,
            after_bad_gap_count=0,
            max_abs_shift_px=0.0,
            lane_plans=(),
            gap_plans=(),
        )
    if recommended_action not in {"lane_family_spread_candidate", "lane_family_reorder_or_rebuild_candidate"}:
        return LaneFamilyWindowPlan(
            window_id=window_id,
            status="rejected",
            reason="recommended_action_not_shift_based",
            recommended_action=recommended_action,
            lane_count=int(inspection.get("lane_count", 0)),
            movable_lane_count=0,
            locked_lane_count=int(inspection.get("lane_count", 0)),
            before_bad_gap_count=0,
            after_bad_gap_count=0,
            max_abs_shift_px=0.0,
            lane_plans=(),
            gap_plans=(),
        )

    lanes = sorted(list(inspection.get("lanes", [])), key=lambda item: float(item.get("lateral_px", 0.0)))
    if len(lanes) < 3:
        return LaneFamilyWindowPlan(
            window_id=window_id,
            status="rejected",
            reason="lane_count_less_than_3",
            recommended_action=str(inspection.get("recommended_action", "")),
            lane_count=len(lanes),
            movable_lane_count=0,
            locked_lane_count=len(lanes),
            before_bad_gap_count=0,
            after_bad_gap_count=0,
            max_abs_shift_px=0.0,
            lane_plans=(),
            gap_plans=(),
        )

    laterals = [float(lane.get("lateral_px", 0.0)) for lane in lanes]
    targets = _target_laterals(laterals, coverage_width_px=coverage_width_px, strategy=target_strategy)
    max_shift = float(coverage_width_px) * float(max_shift_factor)
    lane_plans: list[LaneFamilyLanePlan] = []
    after_laterals: list[float] = []
    for lane, target in zip(lanes, targets):
        lateral = float(lane.get("lateral_px", 0.0))
        proposed = float(target) - lateral
        reject_reasons = list(_lane_reject_reasons(lane))
        if abs(proposed) > max_shift:
            reject_reasons.append("shift_exceeds_limit")
        movable = not reject_reasons
        clipped = proposed if movable else 0.0
        fragments = list(lane.get("fragments", []))
        roles = sorted({str(fragment.get("fragment_role", "unknown")) for fragment in fragments})
        stroke_ids = sorted(
            {
                int(stroke_id)
                for fragment in fragments
                for stroke_id in fragment.get("stroke_ids", [])
            }
        )
        segment_ranges = tuple(
            (int(fragment.get("start_segment_index", -1)), int(fragment.get("end_segment_index", -1)))
            for fragment in fragments
        )
        lane_plans.append(
            LaneFamilyLanePlan(
                lane_id=int(lane.get("lane_id", 0)),
                lateral_px=lateral,
                target_lateral_px=float(target),
                proposed_shift_px=proposed,
                clipped_shift_px=clipped,
                movable=movable,
                lock_reason=reject_reasons[0] if reject_reasons else "",
                reject_reasons=tuple(reject_reasons),
                fragment_roles=tuple(roles),
                fragment_count=len(fragments),
                stroke_ids=tuple(stroke_ids),
                segment_index_ranges=segment_ranges,
                point_indices=tuple(int(value) for value in lane.get("point_indices", [])),
                segment_indices=tuple(int(value) for value in lane.get("segment_indices", [])),
            )
        )
        after_laterals.append(lateral + clipped)

    gap_plans: list[LaneFamilyGapPlan] = []
    before_bad = 0
    after_bad = 0
    for left, right, before_left, before_right, after_left, after_right in zip(
        lane_plans,
        lane_plans[1:],
        laterals,
        laterals[1:],
        after_laterals,
        after_laterals[1:],
    ):
        before_gap = float(before_right - before_left)
        after_gap = float(after_right - after_left)
        before_kind = _gap_kind(
            before_gap,
            coverage_width_px=coverage_width_px,
            min_factor=min_gap_factor,
            max_factor=max_gap_factor,
        )
        after_kind = _gap_kind(
            after_gap,
            coverage_width_px=coverage_width_px,
            min_factor=min_gap_factor,
            max_factor=max_gap_factor,
        )
        before_bad += int(before_kind != "ok")
        after_bad += int(after_kind != "ok")
        blocker_reasons = _gap_blocker_reasons(left, right, before_kind=before_kind)
        gap_plans.append(
            LaneFamilyGapPlan(
                left_lane_id=left.lane_id,
                right_lane_id=right.lane_id,
                before_gap_px=before_gap,
                after_gap_px=after_gap,
                before_kind=before_kind,
                after_kind=after_kind,
                left_movable=left.movable,
                right_movable=right.movable,
                left_fragment_roles=left.fragment_roles,
                right_fragment_roles=right.fragment_roles,
                blocker_reasons=blocker_reasons,
                recommended_next_action=_gap_next_action(before_kind, blocker_reasons),
            )
        )

    movable_count = sum(1 for plan in lane_plans if plan.movable)
    locked_count = len(lane_plans) - movable_count
    if movable_count == 0:
        status = "rejected"
        reason = "no_movable_coverage_core_lane"
    elif after_bad >= before_bad:
        status = "rejected"
        reason = "bad_gap_count_not_improved"
    else:
        status = "candidate_plan"
        reason = "readonly_plan_generated"
    return LaneFamilyWindowPlan(
        window_id=window_id,
        status=status,
        reason=reason,
        recommended_action=str(inspection.get("recommended_action", "")),
        lane_count=len(lane_plans),
        movable_lane_count=movable_count,
        locked_lane_count=locked_count,
        before_bad_gap_count=before_bad,
        after_bad_gap_count=after_bad,
        max_abs_shift_px=max((abs(plan.clipped_shift_px) for plan in lane_plans), default=0.0),
        lane_plans=tuple(lane_plans),
        gap_plans=tuple(gap_plans),
    )


def generate_lane_family_candidate_plans(
    inspections: Sequence[dict[str, Any]],
    *,
    coverage_width_px: int,
    max_shift_factor: float = 0.5,
) -> tuple[LaneFamilyWindowPlan, ...]:
    return tuple(
        generate_lane_family_window_plan(
            inspection,
            coverage_width_px=coverage_width_px,
            max_shift_factor=max_shift_factor,
        )
        for inspection in inspections
    )


def apply_lane_family_window_plan_to_points(
    points: Sequence[Sequence[float]],
    inspection: dict[str, Any],
    *,
    coverage_width_px: int,
    max_shift_factor: float = 0.5,
    target_strategy: str = "coverage_width_from_median_anchor",
    conflict_tolerance_px: float = 1e-6,
) -> LaneFamilyPathApplyResult:
    plan = generate_lane_family_window_plan(
        inspection,
        coverage_width_px=coverage_width_px,
        max_shift_factor=max_shift_factor,
        target_strategy=target_strategy,
    )
    normalized = tuple((float(point[0]), float(point[1])) for point in points)
    if plan.status != "candidate_plan":
        return LaneFamilyPathApplyResult(
            status="rejected",
            reason=plan.reason,
            window_id=plan.window_id,
            target_strategy=target_strategy,
            changed_point_count=0,
            conflicting_point_count=0,
            max_point_shift_px=0.0,
            points=normalized,
            applied_lanes=(),
            skipped_lanes=tuple(lane.lane_id for lane in plan.lane_plans),
            conflicts=(),
        )

    dominant = np.deg2rad(float(inspection.get("dominant_axis_deg", 0.0))) % np.pi
    normal = (-float(np.sin(dominant)), float(np.cos(dominant)))
    point_shifts: dict[int, tuple[float, float, int]] = {}
    conflicts: list[dict[str, Any]] = []
    applied_lanes: list[int] = []
    skipped_lanes: list[int] = []
    for lane in plan.lane_plans:
        if not lane.movable:
            skipped_lanes.append(lane.lane_id)
            continue
        dx = float(lane.clipped_shift_px) * normal[0]
        dy = float(lane.clipped_shift_px) * normal[1]
        applied_lanes.append(lane.lane_id)
        for point_index in lane.point_indices:
            if point_index < 0 or point_index >= len(normalized):
                conflicts.append(
                    {
                        "point_index": int(point_index),
                        "lane_id": int(lane.lane_id),
                        "reason": "point_index_out_of_range",
                    }
                )
                continue
            existing = point_shifts.get(point_index)
            if existing is not None:
                shift_delta = float(np.hypot(existing[0] - dx, existing[1] - dy))
                if shift_delta > float(conflict_tolerance_px):
                    conflicts.append(
                        {
                            "point_index": int(point_index),
                            "first_lane_id": int(existing[2]),
                            "second_lane_id": int(lane.lane_id),
                            "reason": "conflicting_point_shift",
                            "shift_delta_px": shift_delta,
                        }
                    )
                continue
            point_shifts[point_index] = (dx, dy, lane.lane_id)

    if conflicts:
        return LaneFamilyPathApplyResult(
            status="rejected",
            reason="conflicting_point_shift",
            window_id=plan.window_id,
            target_strategy=target_strategy,
            changed_point_count=0,
            conflicting_point_count=len({int(item["point_index"]) for item in conflicts if "point_index" in item}),
            max_point_shift_px=0.0,
            points=normalized,
            applied_lanes=tuple(applied_lanes),
            skipped_lanes=tuple(skipped_lanes),
            conflicts=tuple(conflicts),
        )

    updated = list(normalized)
    max_shift = 0.0
    changed_count = 0
    for point_index, (dx, dy, _lane_id) in point_shifts.items():
        x, y = updated[point_index]
        updated[point_index] = (float(x + dx), float(y + dy))
        point_shift = float(np.hypot(dx, dy))
        if point_shift > 1e-6:
            changed_count += 1
        max_shift = max(max_shift, point_shift)

    return LaneFamilyPathApplyResult(
        status="candidate_path",
        reason="lane_family_shift_applied",
        window_id=plan.window_id,
        target_strategy=target_strategy,
        changed_point_count=changed_count,
        conflicting_point_count=0,
        max_point_shift_px=max_shift,
        points=tuple(updated),
        applied_lanes=tuple(applied_lanes),
        skipped_lanes=tuple(skipped_lanes),
        conflicts=(),
    )


def evaluate_lane_family_target_strategies(
    inspection: dict[str, Any],
    *,
    coverage_width_px: int,
    max_shift_factor: float = 0.5,
    strategies: Sequence[str] = (
        "preserve_current",
        "linspace_full_range",
        "coverage_width_from_first",
        "coverage_width_from_median_anchor",
    ),
) -> tuple[LaneFamilyTargetStrategyEvaluation, ...]:
    results: list[LaneFamilyTargetStrategyEvaluation] = []
    for strategy in strategies:
        plan = generate_lane_family_window_plan(
            inspection,
            coverage_width_px=coverage_width_px,
            max_shift_factor=max_shift_factor,
            target_strategy=strategy,
        )
        before_kinds = [gap.before_kind for gap in plan.gap_plans]
        after_kinds = [gap.after_kind for gap in plan.gap_plans]
        shift_exceeds = sum(1 for lane in plan.lane_plans if "shift_exceeds_limit" in lane.reject_reasons)
        locked_shift_required = sum(
            1
            for lane in plan.lane_plans
            if not lane.movable and abs(float(lane.proposed_shift_px)) > 1e-6
        )
        changed_locked = sum(
            1
            for lane in plan.lane_plans
            if not lane.movable and abs(float(lane.clipped_shift_px)) > 1e-6
        )
        if changed_locked:
            prediction_status = "invalid_prediction_requires_locked_lane_move"
        elif plan.after_bad_gap_count < plan.before_bad_gap_count:
            prediction_status = "improves_bad_gap_prediction"
        else:
            prediction_status = "no_bad_gap_improvement"
        results.append(
            LaneFamilyTargetStrategyEvaluation(
                window_id=plan.window_id,
                strategy=strategy,
                prediction_status=prediction_status,
                reason=plan.reason,
                lane_count=plan.lane_count,
                movable_lane_count=plan.movable_lane_count,
                shift_exceeds_limit_count=shift_exceeds,
                locked_lane_shift_required_count=locked_shift_required,
                changed_locked_lane_count=changed_locked,
                before_bad_gap_count=plan.before_bad_gap_count,
                before_over_dense_count=sum(1 for kind in before_kinds if kind == "over_dense"),
                before_over_sparse_count=sum(1 for kind in before_kinds if kind == "over_sparse"),
                predicted_bad_gap_count=plan.after_bad_gap_count,
                predicted_over_dense_count=sum(1 for kind in after_kinds if kind == "over_dense"),
                predicted_over_sparse_count=sum(1 for kind in after_kinds if kind == "over_sparse"),
                max_abs_shift_px=plan.max_abs_shift_px,
                target_laterals_px=tuple(lane.target_lateral_px for lane in plan.lane_plans),
            )
        )
    return tuple(results)
