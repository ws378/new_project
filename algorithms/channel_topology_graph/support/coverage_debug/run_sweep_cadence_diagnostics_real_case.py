"""导出 CoveragePlanning 的 SweepCadence 诊断表。

输出内容：
- sweep_cadence_diagnostics.json
- sweep_cadence_diagnostics.md

这不是临时脚本。它服务于 SweepGraph -> SweepCadence 规则收敛：
- 哪些 sweep 双端都有连接
- 哪些 sweep 只有一端连接
- 哪些 sweep 两端都没连接
- 孤立 / 单端问题是来自 graph 缺 transition，还是 cadence 没吃到，还是仍需要更高层原语
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


def _classify_cadence_issue(
    *,
    in_count: int,
    out_count: int,
    graph_in_count: int,
    graph_out_count: int,
    route_length: int,
) -> str:
    """给单 sweep 的 cadence 问题做粗分型。"""

    if in_count > 0 and out_count > 0:
        return "both_connected"
    if in_count == 0 and out_count == 0:
        if graph_in_count == 0 and graph_out_count == 0:
            return "graph_transition_absent"
        if route_length <= 1:
            return "cadence_singleton_with_graph_options"
        return "cadence_unconsumed"
    if graph_in_count > 0 or graph_out_count > 0:
        return "one_side_only_with_graph_options"
    return "one_side_only_graph_limited"


def _build_cadence_diagnostics(coverage_result) -> dict[str, Any]:
    """从 coverage_result 中收集 SweepCadence 诊断数据。"""

    sweeps = tuple(coverage_result.coverage_lane_sweep_info.sweeps)
    lane_by_id = {
        int(item["coverage_lane_id"]): item
        for item in tuple(coverage_result.coverage_lane_sweep_info.coverage_lane_info)
    }
    graph_transitions = tuple(coverage_result.sweep_graph_build_info.sweep_graph_info["transitions"])
    routes = tuple(coverage_result.sweep_cadence_build_info.sweep_cadence_info["routes"])

    graph_in: dict[int, list[dict[str, Any]]] = {int(s["sweep_id"]): [] for s in sweeps}
    graph_out: dict[int, list[dict[str, Any]]] = {int(s["sweep_id"]): [] for s in sweeps}
    for item in graph_transitions:
        graph_out[int(item["from_sweep_id"])].append(item)
        graph_in[int(item["to_sweep_id"])].append(item)

    cadence_in: dict[int, list[dict[str, Any]]] = {int(s["sweep_id"]): [] for s in sweeps}
    cadence_out: dict[int, list[dict[str, Any]]] = {int(s["sweep_id"]): [] for s in sweeps}
    route_by_sweep_id: dict[int, dict[str, Any]] = {}
    for route in routes:
        for sweep_id in route["sweep_sequence"]:
            route_by_sweep_id[int(sweep_id)] = route
        for segment in route.get("segments", ()):
            if str(segment.get("primitive_type", "")) != "transition":
                continue
            cadence_out[int(segment["from_sweep_id"])].append(segment)
            cadence_in[int(segment["to_sweep_id"])].append(segment)

    items: list[dict[str, Any]] = []
    for sweep in sweeps:
        sweep_id = int(sweep["sweep_id"])
        coverage_lane_id = int(sweep["coverage_lane_id"])
        coverage_lane = lane_by_id[coverage_lane_id]
        route = route_by_sweep_id.get(sweep_id)
        route_length = int(len(route["sweep_sequence"])) if route is not None else 0
        item = {
            "sweep_id": sweep_id,
            "coverage_lane_id": coverage_lane_id,
            "source_edge_id": int(coverage_lane["source_edge_id"]),
            "side_label": str(sweep.get("side_label", "")),
            "side_level": int(sweep.get("side_level", 0)),
            "active": bool(sweep.get("active", True)),
            "route_id": int(route["route_id"]) if route is not None else -1,
            "route_length": route_length,
            "graph_in_count": int(len(graph_in[sweep_id])),
            "graph_out_count": int(len(graph_out[sweep_id])),
            "cadence_in_count": int(len(cadence_in[sweep_id])),
            "cadence_out_count": int(len(cadence_out[sweep_id])),
            "graph_in_transition_ids": [int(x["transition_id"]) for x in graph_in[sweep_id]],
            "graph_out_transition_ids": [int(x["transition_id"]) for x in graph_out[sweep_id]],
            "cadence_in_transition_ids": [int(x["transition_id"]) for x in cadence_in[sweep_id]],
            "cadence_out_transition_ids": [int(x["transition_id"]) for x in cadence_out[sweep_id]],
            "issue_type": _classify_cadence_issue(
                in_count=len(cadence_in[sweep_id]),
                out_count=len(cadence_out[sweep_id]),
                graph_in_count=len(graph_in[sweep_id]),
                graph_out_count=len(graph_out[sweep_id]),
                route_length=route_length,
            ),
        }
        items.append(item)

    both_connected = [item for item in items if item["issue_type"] == "both_connected"]
    one_side = [item for item in items if item["cadence_in_count"] + item["cadence_out_count"] > 0 and item["issue_type"] != "both_connected"]
    none_connected = [item for item in items if item["cadence_in_count"] == 0 and item["cadence_out_count"] == 0]

    return {
        "summary": {
            "sweep_count": int(len(sweeps)),
            "cadence_count": int(len(routes)),
            "both_connected_count": int(len(both_connected)),
            "one_side_connected_count": int(len(one_side)),
            "none_connected_count": int(len(none_connected)),
            "singleton_route_count": int(sum(1 for route in routes if len(route["sweep_sequence"]) == 1)),
        },
        "sweeps": items,
        "routes": [
            {
                "route_id": int(route["route_id"]),
                "sweep_sequence": [int(x) for x in route["sweep_sequence"]],
                "transition_sequence": [int(x) for x in route["transition_sequence"]],
                "start_sweep_id": int(route["start_sweep_id"]),
                "end_sweep_id": int(route["end_sweep_id"]),
                "start_end_type": str(route["start_end_type"]),
                "end_end_type": str(route["end_end_type"]),
                "route_length": int(len(route["sweep_sequence"])),
            }
            for route in routes
        ],
    }


def _write_markdown(path: Path, diagnostics: dict[str, Any]) -> None:
    """把诊断结果写成人工可读 markdown 表。"""

    lines: list[str] = []
    summary = diagnostics["summary"]
    lines.append("# CoveragePlanning SweepCadence 诊断")
    lines.append("")
    lines.append(f"- sweep_count: {summary['sweep_count']}")
    lines.append(f"- cadence_count: {summary['cadence_count']}")
    lines.append(f"- both_connected_count: {summary['both_connected_count']}")
    lines.append(f"- one_side_connected_count: {summary['one_side_connected_count']}")
    lines.append(f"- none_connected_count: {summary['none_connected_count']}")
    lines.append(f"- singleton_route_count: {summary['singleton_route_count']}")
    lines.append("")

    lines.append("## 异常 sweep")
    lines.append("")
    lines.append("| sweep_id | CL | edge | side | route_id | route_length | graph_in | graph_out | cadence_in | cadence_out | issue_type |")
    lines.append("| ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for item in diagnostics["sweeps"]:
        if item["issue_type"] == "both_connected":
            continue
        lines.append(
            "| "
            f"{item['sweep_id']} | "
            f"{item['coverage_lane_id']} | "
            f"{item['source_edge_id']} | "
            f"{item['side_label']}:{item['side_level']} | "
            f"{item['route_id']} | "
            f"{item['route_length']} | "
            f"{item['graph_in_count']} | "
            f"{item['graph_out_count']} | "
            f"{item['cadence_in_count']} | "
            f"{item['cadence_out_count']} | "
            f"{item['issue_type']} |"
        )
    lines.append("")

    lines.append("## Cadence Routes")
    lines.append("")
    lines.append("| route_id | route_length | start | end | start_end | end_end | sequence |")
    lines.append("| ---: | ---: | ---: | ---: | --- | --- | --- |")
    for item in diagnostics["routes"]:
        lines.append(
            "| "
            f"{item['route_id']} | "
            f"{item['route_length']} | "
            f"{item['start_sweep_id']} | "
            f"{item['end_sweep_id']} | "
            f"{item['start_end_type']} | "
            f"{item['end_end_type']} | "
            f"{item['sweep_sequence']} |"
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
        / f"sweep_cadence_diagnostics_{timestamp}"
    )
    output_root.mkdir(parents=True, exist_ok=True)

    case_dir, coverage_result = _build_real_case_result()
    diagnostics = _build_cadence_diagnostics(coverage_result)
    diagnostics["meta"] = {
        "case_dir": str(case_dir),
    }

    json_path = output_root / "sweep_cadence_diagnostics.json"
    json_path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = output_root / "sweep_cadence_diagnostics.md"
    _write_markdown(md_path, diagnostics)

    print(f"output_dir={output_root}")
    print(f"diagnostics_json={json_path}")
    print(f"diagnostics_md={md_path}")
    print(f"sweep_count={diagnostics['summary']['sweep_count']}")
    print(f"cadence_count={diagnostics['summary']['cadence_count']}")
    print(f"both_connected_count={diagnostics['summary']['both_connected_count']}")
    print(f"one_side_connected_count={diagnostics['summary']['one_side_connected_count']}")
    print(f"none_connected_count={diagnostics['summary']['none_connected_count']}")
    print(f"singleton_route_count={diagnostics['summary']['singleton_route_count']}")


if __name__ == "__main__":
    main()
