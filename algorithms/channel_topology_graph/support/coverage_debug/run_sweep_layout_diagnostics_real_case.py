"""导出 CoveragePlanning 横向 sweep 铺设诊断表。

输出内容：
- sweep_layout_diagnostics.json
- sweep_layout_diagnostics.md

这不是临时脚本。它服务于 CoveragePlanning 横向铺设方案的长期审查：
- 每条 coverage lane 的局部 sweep 数
- 排序结果
- 稳健分位数结果
- 每个锚点的最终 offsets
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.channel_topology_graph.io import load_plan1_case_input  # noqa: E402
from algorithms.channel_topology_graph.stages.coverage_planning import build_coverage_plan  # noqa: E402
from algorithms.channel_topology_graph.stages.geometry_preparation import build_geometry_preparation  # noqa: E402
from algorithms.channel_topology_graph.stages.junction_rebuild import build_junction_rebuild  # noqa: E402
from algorithms.channel_topology_graph.stages.topology_graph_build import build_topology_graph  # noqa: E402


def _build_real_case_result():
    """跑真实 case，返回 CoveragePlanning 结果。"""

    coverage_width_m = 0.55
    robot_width_m = 0.55
    case_dir = (
        REPO_ROOT
        / "tests"
        / "fixtures"
        / "coverage_cases"
        / "case_demo"
    )
    case_input = load_plan1_case_input(case_dir=case_dir)
    geometry_result = build_geometry_preparation(
        raw_map=case_input.raw_map,
        region_constraint=case_input.region_constraint,
        config={
            "crop_box_px": case_input.meta["crop_box_px"],
            "open_kernel_m": 0.3,
            "short_side_branch_m": 1.2,
            "summary_viz": False,
            "detail_viz": False,
        },
    )
    junction_result = build_junction_rebuild(
        geometry_preparation_result=geometry_result,
        config={
            "intersection_merge_geodesic_px": 20,
            "initial_junction_zone_radius_px": 2,
            "initial_dead_end_zone_radius_px": 1,
            "junction_polygon_radius_px": 10.0,
            "dead_end_polygon_radius_px": 4.0,
            "summary_viz": False,
            "detail_viz": False,
        },
    )
    topology_result = build_topology_graph(junction_result)
    coverage_result = build_coverage_plan(
        topology_result,
        config={
            "robot_width_m": robot_width_m,
            "coverage_width_m": coverage_width_m,
            "free_node_min_clearance_m": 0.35,
        },
        context={"geometry_preparation_result": geometry_result},
    )
    return case_dir, coverage_result


def _build_lane_diagnostics(coverage_result) -> dict[str, Any]:
    """从 coverage_lane_info 收集横向铺设诊断数据。"""

    lane_items = tuple(coverage_result.coverage_lane_sweep_info.coverage_lane_info)
    diagnostics: list[dict[str, Any]] = []
    for lane in lane_items:
        layout_debug = dict((lane.get("debug_info") or {}).get("sweep_layout_debug") or {})
        lane_item = {
            "coverage_lane_id": int(lane["coverage_lane_id"]),
            "source_edge_id": int(lane["source_edge_id"]),
            "active": bool(lane.get("active", True)),
            "excluded_reason": str(lane.get("excluded_reason", "")),
            "anchor_count": int(layout_debug.get("anchor_count", 0)),
            "sampling_step_px": int(layout_debug.get("sampling_step_px", 0)),
            "normal_search_px": int(layout_debug.get("normal_search_px", 0)),
            "effective_min_clearance_px": float(layout_debug.get("effective_min_clearance_px", 0.0)),
            "local_sweep_counts_raw": [int(item) for item in layout_debug.get("local_sweep_counts_raw", ())],
            "local_sweep_counts_sorted": [int(item) for item in layout_debug.get("local_sweep_counts_sorted", ())],
            "robust_quantile": float(layout_debug.get("robust_quantile", 0.0)),
            "target_sweep_count": int(layout_debug.get("target_sweep_count", 0)),
            "final_sweep_count_generated": int(layout_debug.get("final_sweep_count_generated", 0)),
            "center_sweep_index": int(layout_debug.get("center_sweep_index", -1)),
            "mean_offsets_px": [float(item) for item in layout_debug.get("mean_offsets_px", ())],
            "anchors": [],
        }
        for anchor in layout_debug.get("anchors", ()):
            lane_item["anchors"].append(
                {
                    "anchor_index": int(anchor["anchor_index"]),
                    "anchor_rc": [float(anchor["anchor_rc"][0]), float(anchor["anchor_rc"][1])],
                    "center_point_rc": [float(anchor["center_point_rc"][0]), float(anchor["center_point_rc"][1])],
                    "normal_vec": [float(anchor["normal_vec"][0]), float(anchor["normal_vec"][1])],
                    "offset_min_px": int(anchor["offset_min_px"]),
                    "offset_max_px": int(anchor["offset_max_px"]),
                    "interval_width_px": float(anchor["interval_width_px"]),
                    "local_sweep_count": int(anchor["local_sweep_count"]),
                    "final_offsets_px": [int(item) for item in anchor.get("final_offsets_px", ())],
                }
            )
        diagnostics.append(lane_item)

    return {
        "summary": {
            "coverage_lane_unit_count": int(len(lane_items)),
            "active_coverage_lane_unit_count": int(sum(1 for item in lane_items if bool(item.get("active", True)))),
        },
        "coverage_lanes": diagnostics,
    }


def _write_markdown(path: Path, diagnostics: dict[str, Any]) -> None:
    """把诊断结果写成人工可读 markdown 表。"""

    lines: list[str] = []
    summary = diagnostics["summary"]
    lines.append("# CoveragePlanning 横向 Sweep 铺设诊断")
    lines.append("")
    lines.append(f"- coverage_lane_unit_count: {summary['coverage_lane_unit_count']}")
    lines.append(f"- active_coverage_lane_unit_count: {summary['active_coverage_lane_unit_count']}")
    lines.append("")

    for lane in diagnostics["coverage_lanes"]:
        lines.append(f"## CL{lane['coverage_lane_id']} / Edge {lane['source_edge_id']}")
        lines.append("")
        lines.append(f"- active: {lane['active']}")
        lines.append(f"- excluded_reason: {lane['excluded_reason']}")
        lines.append(f"- anchor_count: {lane['anchor_count']}")
        lines.append(f"- sampling_step_px: {lane['sampling_step_px']}")
        lines.append(f"- normal_search_px: {lane['normal_search_px']}")
        lines.append(f"- effective_min_clearance_px: {lane['effective_min_clearance_px']}")
        lines.append(f"- local_sweep_counts_raw: {lane['local_sweep_counts_raw']}")
        lines.append(f"- local_sweep_counts_sorted: {lane['local_sweep_counts_sorted']}")
        lines.append(f"- robust_quantile: {lane['robust_quantile']}")
        lines.append(f"- target_sweep_count: {lane['target_sweep_count']}")
        lines.append(f"- final_sweep_count_generated: {lane['final_sweep_count_generated']}")
        lines.append(f"- center_sweep_index: {lane['center_sweep_index']}")
        lines.append(f"- mean_offsets_px: {lane['mean_offsets_px']}")
        lines.append("")
        lines.append("| anchor_idx | anchor_rc | center_point_rc | offset_min_px | offset_max_px | width_px | local_sweep_count | final_offsets_px |")
        lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | --- |")
        for anchor in lane["anchors"]:
            lines.append(
                "| "
                f"{anchor['anchor_index']} | "
                f"{anchor['anchor_rc']} | "
                f"{anchor['center_point_rc']} | "
                f"{anchor['offset_min_px']} | "
                f"{anchor['offset_max_px']} | "
                f"{anchor['interval_width_px']:.2f} | "
                f"{anchor['local_sweep_count']} | "
                f"{anchor['final_offsets_px']} |"
            )
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    """执行真实 case 诊断导出。"""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = (
        REPO_ROOT
        / "algorithms"
        / "channel_topology_graph"
        / "test_outputs"
        / f"sweep_layout_diagnostics_{timestamp}"
    )
    output_root.mkdir(parents=True, exist_ok=True)

    case_dir, coverage_result = _build_real_case_result()
    diagnostics = _build_lane_diagnostics(coverage_result)
    diagnostics["meta"] = {
        "case_dir": str(case_dir),
        "coverage_lane_unit_count": int(len(coverage_result.coverage_lane_sweep_info.coverage_lane_info)),
        "sweep_count": int(len(coverage_result.coverage_lane_sweep_info.sweeps)),
    }

    json_path = output_root / "sweep_layout_diagnostics.json"
    json_path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = output_root / "sweep_layout_diagnostics.md"
    _write_markdown(md_path, diagnostics)

    print(f"output_dir={output_root}")
    print(f"diagnostics_json={json_path}")
    print(f"diagnostics_md={md_path}")
    print(f"coverage_lane_unit_count={len(coverage_result.coverage_lane_sweep_info.coverage_lane_info)}")
    print(f"sweep_count={len(coverage_result.coverage_lane_sweep_info.sweeps)}")


if __name__ == "__main__":
    main()
