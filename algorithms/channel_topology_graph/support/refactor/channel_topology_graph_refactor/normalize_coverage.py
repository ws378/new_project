"""CoveragePlanning 结果的归一化。

说明：
    本模块里保留的 `stage_a/b/c/d` 字段是 compare 协议键名，
    不是当前正式源码的业务命名。
"""

from __future__ import annotations

from typing import Any

from algorithms.channel_topology_graph.support.refactor.coverage_planning_refactor.normalize import (
    normalize_stage_a,
    normalize_stage_b,
    normalize_stage_c,
    normalize_stage_d,
)

from ._common import to_jsonable


def normalize_coverage_result(coverage_result: Any) -> dict[str, Any]:
    """把 coverage_planning 结果压成稳定、可 diff 的结构。"""

    coverage_lane_sweep_info = coverage_result.coverage_lane_sweep_info
    sweep_graph_build_info = coverage_result.sweep_graph_build_info
    sweep_cadence_build_info = coverage_result.sweep_cadence_build_info
    final_coverage_path_build_info = coverage_result.final_coverage_path_build_info
    stage_a_summary = dict(coverage_lane_sweep_info.summary) if coverage_lane_sweep_info is not None else {}
    stage_b_summary = dict(sweep_graph_build_info.summary) if sweep_graph_build_info is not None else {}
    stage_c_summary = dict(sweep_cadence_build_info.summary) if sweep_cadence_build_info is not None else {}
    stage_d_summary = dict(final_coverage_path_build_info.summary) if final_coverage_path_build_info is not None else {}
    coverage_stats = dict(sweep_cadence_build_info.coverage_stats) if sweep_cadence_build_info is not None else {}
    final_validation = dict(final_coverage_path_build_info.validation_info) if final_coverage_path_build_info is not None else {}
    return {
        "summary": {
            "graph_node_count": int(len(coverage_result.graph_info.nodes)),
            "graph_edge_count": int(len(coverage_result.graph_info.edges)),
            "coverage_lane_unit_count": int(stage_a_summary.get("coverage_lane_count", 0)),
            "sweep_count": int(stage_a_summary.get("sweep_count", 0)),
            "sweep_group_count": int(stage_b_summary.get("sweep_group_count", 0)),
            "sweep_transition_count": int(stage_b_summary.get("sweep_transition_count", 0)),
            "sweep_cadence_count": int(stage_c_summary.get("sweep_cadence_count", 0)),
            "junction_connection_count": int(stage_d_summary.get("junction_connection_count", 0)),
            "final_path_point_count": int(stage_d_summary.get("path_point_count", 0)),
            "final_path_length_m": float(stage_d_summary.get("path_length_m", 0.0)),
            "coverage_ratio": float(coverage_stats.get("coverage_ratio", 0.0)),
            "is_complete": bool(coverage_stats.get("is_complete", False)),
            "final_path_is_valid": bool(final_validation.get("is_valid", False)),
        },
        "stage_summaries": {
            "stage_a": to_jsonable(stage_a_summary),
            "stage_b": to_jsonable(stage_b_summary),
            "stage_c": to_jsonable(stage_c_summary),
            "stage_d": to_jsonable(stage_d_summary),
        },
        "stage_validations": {
            "stage_a": to_jsonable(getattr(coverage_lane_sweep_info, "validation_info", None)),
            "stage_b": to_jsonable(getattr(sweep_graph_build_info, "validation_info", None)),
            "stage_c": to_jsonable(getattr(sweep_cadence_build_info, "validation_info", None)),
            "stage_d": to_jsonable(getattr(final_coverage_path_build_info, "validation_info", None)),
        },
        "coverage_stats": to_jsonable(coverage_stats),
        "stage_a": normalize_stage_a(coverage_result),
        "stage_b": normalize_stage_b(coverage_result),
        "stage_c": normalize_stage_c(coverage_result),
        "stage_d": normalize_stage_d(coverage_result),
        "validation_info": to_jsonable(coverage_result.validation_info),
        "meta": to_jsonable(coverage_result.meta),
    }
