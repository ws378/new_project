"""lane family 异常 gap 阻断归因。

该模块只读候选计划和 inspection 证据，不生成或修改路径。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class BlockedGapAttribution:
    window_id: int
    left_lane_id: int
    right_lane_id: int
    before_kind: str
    after_kind: str
    before_gap_px: float
    after_gap_px: float
    attribution: str
    evidence_level: str
    recommended_next_action: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": int(self.window_id),
            "left_lane_id": int(self.left_lane_id),
            "right_lane_id": int(self.right_lane_id),
            "before_kind": self.before_kind,
            "after_kind": self.after_kind,
            "before_gap_px": float(self.before_gap_px),
            "after_gap_px": float(self.after_gap_px),
            "attribution": self.attribution,
            "evidence_level": self.evidence_level,
            "recommended_next_action": self.recommended_next_action,
            "evidence": self.evidence,
        }


def _lane_by_id(items: Sequence[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in items:
        try:
            result[int(item.get("lane_id"))] = item
        except (TypeError, ValueError):
            continue
    return result


def _source_counts(lane: dict[str, Any]) -> tuple[dict[str, int], dict[str, int], tuple[str, ...], tuple[str, ...]]:
    move_counts: dict[str, int] = {}
    edge_counts: dict[str, int] = {}
    segment_types: set[str] = set()
    action_labels: set[str] = set()
    for fragment in lane.get("fragments", []):
        for key, value in dict(fragment.get("move_source_counts", {})).items():
            move_counts[str(key)] = move_counts.get(str(key), 0) + int(value)
        for key, value in dict(fragment.get("edge_role_counts", {})).items():
            edge_counts[str(key)] = edge_counts.get(str(key), 0) + int(value)
        segment_types.update(str(value) for value in fragment.get("segment_types", []))
        action_labels.update(str(value) for value in fragment.get("action_labels", []))
    return move_counts, edge_counts, tuple(sorted(segment_types)), tuple(sorted(action_labels))


def _lane_evidence(lane_id: int, plan_lane: dict[str, Any], inspection_lane: dict[str, Any] | None) -> dict[str, Any]:
    move_counts: dict[str, int] = {}
    edge_counts: dict[str, int] = {}
    segment_types: tuple[str, ...] = ()
    action_labels: tuple[str, ...] = ()
    if inspection_lane is not None:
        move_counts, edge_counts, segment_types, action_labels = _source_counts(inspection_lane)
    return {
        "lane_id": int(lane_id),
        "movable": bool(plan_lane.get("movable")),
        "reject_reasons": list(plan_lane.get("reject_reasons", [])),
        "fragment_roles": list(plan_lane.get("fragment_roles", [])),
        "stroke_ids": list(plan_lane.get("stroke_ids", [])),
        "segment_index_ranges": list(plan_lane.get("segment_index_ranges", [])),
        "move_source_counts": move_counts,
        "edge_role_counts": edge_counts,
        "segment_types": list(segment_types),
        "action_labels": list(action_labels),
    }


def _classify(left: dict[str, Any], right: dict[str, Any]) -> tuple[str, str, str]:
    move_sources = set(left["move_source_counts"]) | set(right["move_source_counts"])
    edge_roles = set(left["edge_role_counts"]) | set(right["edge_role_counts"])
    fragment_roles = set(left["fragment_roles"]) | set(right["fragment_roles"])
    reject_reasons = set(left["reject_reasons"]) | set(right["reject_reasons"])
    if move_sources & {"global_fallback", "revisit_bridge", "turn_aware_reconnect"} or edge_roles & {
        "fallback_transfer",
        "revisit_bridge",
        "local_reconnect_bridge",
    }:
        return "connector_transfer", "direct_provenance", "split_connector_before_rebuild"
    if "mixed" in fragment_roles or "non_coverage_core_fragment" in reject_reasons:
        return "mixed_fragment", "stroke_only", "need_stroke_provenance_review"
    if reject_reasons == {"shift_exceeds_limit"} or "shift_exceeds_limit" in reject_reasons:
        return "shift_limit", "lane_plan_only", "shift_limit_requires_retarget"
    if fragment_roles <= {"coverage_core"}:
        return "coverage_core_gap", "stroke_only", "not_lane_family_problem"
    return "unknown_source", "lane_plan_only", "need_stroke_provenance_review"


def attribute_blocked_gaps(
    plan_summary: dict[str, Any],
    inspection_summary: dict[str, Any],
) -> tuple[BlockedGapAttribution, ...]:
    inspections = {int(item.get("window_id")): item for item in inspection_summary.get("inspections", [])}
    results: list[BlockedGapAttribution] = []
    for plan in plan_summary.get("plans", []):
        window_id = int(plan.get("window_id", -1))
        inspection = inspections.get(window_id, {})
        inspection_lanes = _lane_by_id(inspection.get("lanes", []))
        plan_lanes = _lane_by_id(plan.get("lane_plans", []))
        for gap in plan.get("gap_plans", []):
            if str(gap.get("before_kind")) == "ok":
                continue
            left_id = int(gap.get("left_lane_id"))
            right_id = int(gap.get("right_lane_id"))
            left = _lane_evidence(left_id, plan_lanes.get(left_id, {}), inspection_lanes.get(left_id))
            right = _lane_evidence(right_id, plan_lanes.get(right_id, {}), inspection_lanes.get(right_id))
            attribution, evidence_level, action = _classify(left, right)
            results.append(
                BlockedGapAttribution(
                    window_id=window_id,
                    left_lane_id=left_id,
                    right_lane_id=right_id,
                    before_kind=str(gap.get("before_kind")),
                    after_kind=str(gap.get("after_kind")),
                    before_gap_px=float(gap.get("before_gap_px", 0.0)),
                    after_gap_px=float(gap.get("after_gap_px", 0.0)),
                    attribution=attribution,
                    evidence_level=evidence_level,
                    recommended_next_action=action,
                    evidence={"left": left, "right": right},
                )
            )
    return tuple(results)
