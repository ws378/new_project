"""CoveragePlanning 局部重构的桥接归一层。

说明：
    本模块仍输出 `stage_a/b/c/d`，原因仅是 compare/baseline 协议冻结；
    当前正式业务语义应以 coverage lane sweep、sweep graph、sweep cadence、final coverage path 为准。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .pipeline_case import CoveragePlanningFixedCaseSpec


def write_json(path: str | Path, payload: Any) -> None:
    """把 payload 以稳定格式写出为 JSON。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_json(path: str | Path) -> Any:
    """读取 JSON 文件。"""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalize_case_spec(
    spec: CoveragePlanningFixedCaseSpec,
    *,
    resolved_geometry_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把固定输入规格转成稳定 JSON。"""

    return {
        "case_name": str(spec.case_name),
        "case_dir": str(spec.case_dir),
        "geometry_config": _to_jsonable(resolved_geometry_config if resolved_geometry_config is not None else spec.geometry_config),
        "junction_config": _to_jsonable(spec.junction_config),
        "coverage_config": _to_jsonable(spec.coverage_config),
    }


def normalize_stage_a(coverage_result: Any) -> dict[str, Any]:
    """归一阶段 A: coverage_lane_info + sweeps。"""

    coverage_lane_sweep_info = _require_stage_info(coverage_result, "coverage_lane_sweep_info")
    coverage_lane_info = tuple(coverage_lane_sweep_info.coverage_lane_info)
    sweeps = tuple(coverage_lane_sweep_info.sweeps)
    lanes = [
        {
            "coverage_lane_id": int(item["coverage_lane_id"]),
            "source_edge_id": int(item["source_edge_id"]),
            "active": bool(item.get("active", True)),
            "sweep_ids": [int(sweep_id) for sweep_id in tuple(item.get("sweep_ids", ()))],
            "sweep_count": int(item.get("sweep_count", 0)),
        }
        for item in coverage_lane_info
    ]
    sweeps_normalized = [
        {
            "sweep_id": int(item["sweep_id"]),
            "coverage_lane_id": int(item["coverage_lane_id"]),
            "source_edge_id": int(item["source_edge_id"]),
            "active": bool(item.get("active", True)),
            "path_rc": _normalize_path(item.get("path_rc", ())),
        }
        for item in sweeps
    ]
    return {
        "summary": {
            "coverage_lane_count": int(len(coverage_lane_info)),
            "active_coverage_lane_count": int(sum(1 for item in lanes if bool(item["active"]))),
            "sweep_count": int(len(sweeps)),
            "active_sweep_count": int(sum(1 for item in sweeps_normalized if bool(item["active"]))),
        },
        "coverage_lanes": sorted(lanes, key=lambda item: int(item["coverage_lane_id"])),
        "sweeps": sorted(sweeps_normalized, key=lambda item: int(item["sweep_id"])),
    }


def normalize_stage_b(coverage_result: Any) -> dict[str, Any]:
    """归一阶段 B: sweep_graph 中间图层。"""

    sweep_graph_build_info = _require_stage_info(coverage_result, "sweep_graph_build_info")
    sweep_group_info = dict(sweep_graph_build_info.sweep_group_info)
    sweep_port_view_info = dict(sweep_graph_build_info.sweep_port_view_info)
    sweep_transition_candidate_info = dict(sweep_graph_build_info.sweep_transition_candidate_info)
    sweep_graph_info = dict(sweep_graph_build_info.sweep_graph_info)
    return {
        "summary": {
            "group_count": int(len(tuple(sweep_group_info.get("groups", ())))),
            "port_view_count": int(len(tuple(sweep_port_view_info.get("items", ())))),
            "transition_candidate_count": int(len(tuple(sweep_transition_candidate_info.get("items", ())))),
            "kept_transition_candidate_count": int(len(tuple(sweep_transition_candidate_info.get("kept_items", ())))),
            "transition_count": int(len(tuple(sweep_graph_info.get("transitions", ())))),
        },
        "groups": [
            {
                "group_id": int(item["group_id"]),
                "coverage_lane_id": int(item["coverage_lane_id"]),
                "source_edge_id": int(item["source_edge_id"]),
                "src_node_id": int(item["src_node_id"]),
                "dst_node_id": int(item["dst_node_id"]),
                "ordered_sweep_ids": [int(sweep_id) for sweep_id in tuple(item.get("ordered_sweep_ids", ()))],
                "center_sweep_id": int(item["center_sweep_id"]),
                "center_sweep_index": int(item["center_sweep_index"]),
            }
            for item in tuple(sweep_group_info.get("groups", ()))
        ],
        "port_views": [
            {
                "group_id": int(item["group_id"]),
                "coverage_lane_id": int(item["coverage_lane_id"]),
                "node_id": int(item["node_id"]),
                "port_side": str(item["port_side"]),
                "ordered_port_sweep_ids": [int(sweep_id) for sweep_id in tuple(item.get("ordered_port_sweep_ids", ()))],
                "center_port_rank": int(item.get("center_port_rank", -1)),
            }
            for item in tuple(sweep_port_view_info.get("items", ()))
        ],
        "kept_transition_candidates": [
            {
                "candidate_id": int(item["candidate_id"]),
                "via_node_id": int(item["via_node_id"]),
                "in_sweep_id": int(item["in_sweep_id"]),
                "out_sweep_id": int(item["out_sweep_id"]),
                "turn_type": str(item["turn_type"]),
                "mapping_type": str(item["mapping_type"]),
                "candidate_level": str(item["candidate_level"]),
                "port_rank_gap": int(item.get("port_rank_gap", 0)),
            }
            for item in tuple(sweep_transition_candidate_info.get("kept_items", ()))
        ],
        "transitions": [
            {
                "transition_id": int(item["transition_id"]),
                "source_candidate_id": int(item["source_candidate_id"]),
                "via_node_id": int(item["via_node_id"]),
                "from_sweep_id": int(item["from_sweep_id"]),
                "to_sweep_id": int(item["to_sweep_id"]),
                "from_end_type": str(item["from_end_type"]),
                "to_end_type": str(item["to_end_type"]),
                "turn_type": str(item["turn_type"]),
                "mapping_type": str(item["mapping_type"]),
                "candidate_level": str(item["candidate_level"]),
            }
            for item in tuple(sweep_graph_info.get("transitions", ()))
        ],
    }


def normalize_stage_c(coverage_result: Any) -> dict[str, Any]:
    """归一阶段 C: sweep_cadence_info。"""

    sweep_cadence_build_info = _require_stage_info(coverage_result, "sweep_cadence_build_info")
    sweep_cadence_info = dict(sweep_cadence_build_info.sweep_cadence_info)
    routes = []
    for route in tuple(sweep_cadence_info.get("routes", ())):
        segments = []
        for segment_index, item in enumerate(tuple(route.get("segments", ())), start=1):
            segments.append(
                {
                    "segment_index": int(item.get("segment_index", segment_index)),
                    "primitive_type": str(item["primitive_type"]),
                    "from_sweep_id": int(item["from_sweep_id"]),
                    "to_sweep_id": int(item["to_sweep_id"]),
                    "transition_id": int(item["transition_id"]) if item.get("transition_id") is not None else None,
                    "via_node_id": int(item["via_node_id"]) if item.get("via_node_id") is not None else None,
                    "entry_end_type": str(item["entry_end_type"]),
                    "exit_end_type": str(item["exit_end_type"]),
                    "requires_junction_connection": bool(item.get("requires_junction_connection", False)),
                    "is_repeat_coverage_transition": bool(item.get("is_repeat_coverage_transition", False)),
                }
            )
        routes.append(
            {
                "route_id": int(route["route_id"]),
                "start_sweep_id": int(route["start_sweep_id"]),
                "end_sweep_id": int(route["end_sweep_id"]),
                "start_end_type": str(route["start_end_type"]),
                "end_end_type": str(route["end_end_type"]),
                "sweep_sequence": [int(item) for item in tuple(route.get("sweep_sequence", ()))],
                "transition_sequence": [int(item) for item in tuple(route.get("transition_sequence", ()))],
                "segments": segments,
            }
        )
    return {
        "summary": {
            "route_count": int(len(routes)),
            "covered_sweep_count": int(len({int(item["sweep_id"]) for item in tuple(sweep_cadence_info.get("route_sweep_order", ())) })),
        },
        "routes": routes,
        "route_sweep_order": [
            {
                "route_id": int(item["route_id"]),
                "order_in_route": int(item["order_in_route"]),
                "sweep_id": int(item["sweep_id"]),
            }
            for item in tuple(sweep_cadence_info.get("route_sweep_order", ()))
        ],
    }


def normalize_stage_d(coverage_result: Any) -> dict[str, Any]:
    """归一阶段 D: final_coverage_path_info。"""

    final_coverage_path_build_info = _require_stage_info(coverage_result, "final_coverage_path_build_info")
    final_info = dict(final_coverage_path_build_info.final_coverage_path_info)
    routes = []
    for route in tuple(final_info.get("routes", ())):
        routes.append(
            {
                "route_id": int(route["route_id"]),
                "ordered_items": [
                    _normalize_ordered_item(item) for item in tuple(route.get("ordered_items", ()))
                ],
                "junction_connections": [
                    _normalize_connection(item) for item in tuple(route.get("junction_connections", ()))
                ],
                "path_subchains_rc": _normalize_route_subchains(route),
            }
        )
    return {
        "summary": {
            "route_count": int(len(routes)),
            "junction_connection_count": int(len(tuple(final_info.get("junction_connections", ())))),
            "u_turn_connection_count": int(sum(1 for item in tuple(final_info.get("junction_connections", ())) if bool(item.get("is_u_turn", False)))),
        },
        "routes": routes,
        "ordered_items": [_normalize_ordered_item(item) for item in tuple(final_info.get("ordered_items", ()))],
        "junction_connections": [
            _normalize_connection(item) for item in tuple(final_info.get("junction_connections", ()))
        ],
    }


def _normalize_ordered_item(item: dict[str, Any]) -> dict[str, Any]:
    item_type = str(item.get("item_type", ""))
    normalized = {
        "item_type": item_type,
        "route_id": int(item["route_id"]),
        "item_index": int(item["item_index"]),
    }
    if item_type == "sweep_segment":
        normalized.update(
            {
                "sweep_id": int(item["sweep_id"]),
                "direction": str(item["direction"]),
                "points_rc": _normalize_path(item.get("sweep_points_rc", ())),
            }
        )
        return normalized
    if item_type == "junction_connection":
        normalized.update(
            {
                "connection_id": int(item["connection_id"]),
                "from_sweep_id": int(item["from_sweep_id"]),
                "to_sweep_id": int(item["to_sweep_id"]),
                "via_node_id": int(item["via_node_id"]),
                "connection_class": str(item["connection_class"]),
                "is_constructible": bool(item.get("is_constructible", True)),
                "points_rc": _normalize_path(item.get("junction_connection_points_rc", ())),
            }
        )
        return normalized
    return normalized


def _require_stage_info(coverage_result: Any, field_name: str) -> Any:
    """要求 compare 输入已经切到四阶段正式对象。"""

    value = getattr(coverage_result, field_name, None)
    if value is None:
        raise ValueError(f"coverage result missing required stage field: {field_name}")
    return value


def _normalize_connection(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "connection_id": int(item["connection_id"]),
        "route_id": int(item["route_id"]),
        "from_sweep_id": int(item["from_sweep_id"]),
        "to_sweep_id": int(item["to_sweep_id"]),
        "via_node_id": int(item["via_node_id"]),
        "connection_type": str(item["connection_type"]),
        "point_a_rc": _normalize_point(item["point_a_rc"]),
        "point_b_rc": _normalize_point(item["point_b_rc"]),
        "point_c_rc": _normalize_point(item["point_c_rc"]),
        "point_d_rc": _normalize_point(item["point_d_rc"]),
        "theta_deg": float(item["theta_deg"]),
        "connection_class": str(item["connection_class"]),
        "is_constructible": bool(item.get("is_constructible", True)),
        "failure_reason": str(item.get("failure_reason", "")),
        "rule_geometry_rc": _normalize_path(item.get("rule_geometry_rc", ())),
        "path_points_rc": _normalize_path(item.get("path_points_rc", ())),
        "coverage_support_width_m": float(item.get("coverage_support_width_m", 0.0)),
        "is_u_turn": bool(item.get("is_u_turn", False)),
    }


def _normalize_route_subchains(route: dict[str, Any]) -> list[list[list[float]]]:
    path_subchains = tuple(route.get("path_subchains_rc", ()))
    if path_subchains:
        return [_normalize_path(chain) for chain in path_subchains]
    path_points = tuple(route.get("path_points_rc", ()))
    if path_points:
        return [_normalize_path(path_points)]
    return []


def _normalize_path(path_rc: Any) -> list[list[float]]:
    return [[float(point[0]), float(point[1])] for point in tuple(path_rc or ())]


def _normalize_point(point_rc: Any) -> list[float]:
    point = tuple(point_rc or ())
    return [float(point[0]), float(point[1])]


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
