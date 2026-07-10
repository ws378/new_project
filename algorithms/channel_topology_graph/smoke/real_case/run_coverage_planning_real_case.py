"""使用真实 case 跑 geometry -> junction -> topology -> coverage 联调。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.channel_topology_graph.io import load_plan1_case_input  # noqa: E402
from algorithms.channel_topology_graph.io import write_coverage_planning_result_json  # noqa: E402
from algorithms.channel_topology_graph.io import write_coverage_planning_summary  # noqa: E402
from algorithms.channel_topology_graph.renderers import write_coverage_planning_visualizations  # noqa: E402
from algorithms.channel_topology_graph.stages.coverage_planning import build_coverage_plan  # noqa: E402
from algorithms.channel_topology_graph.stages.geometry_preparation import build_geometry_preparation  # noqa: E402
from algorithms.channel_topology_graph.stages.junction_rebuild import build_junction_rebuild  # noqa: E402
from algorithms.channel_topology_graph.stages.topology_graph_build import build_topology_graph  # noqa: E402


def main() -> None:
    """执行真实 case 的完整主线联调。"""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(__file__).resolve().parents[2] / "test_outputs" / f"coverage_planning_real_case_{timestamp}"
    output_root.mkdir(parents=True, exist_ok=True)
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
            "coverage_width_m": coverage_width_m,
            "free_node_min_clearance_m": 0.35,
            "robot_width_m": robot_width_m,
        },
        context={"geometry_preparation_result": geometry_result},
    )
    summary_path = write_coverage_planning_summary(
        result=coverage_result,
        output_dir=output_root,
        extra_meta={
            "case_dir": str(case_dir),
        },
    )
    result_json_path = write_coverage_planning_result_json(
        result=coverage_result,
        output_dir=output_root,
    )
    viz_paths = write_coverage_planning_visualizations(
        geometry_result=geometry_result,
        result=coverage_result,
        output_dir=output_root / "coverage_viz",
        render_scale=8,
    )

    print(f"output_dir={output_root}")
    print(f"summary_json={summary_path}")
    print(f"coverage_planning_result_json={result_json_path}")
    print(f"coverage_lanes_summary={viz_paths['coverage_lanes_summary']}")
    print(f"coverage_lane_territory_summary={viz_paths['coverage_lane_territory_summary']}")
    print(f"coverage_lane_effective_region_summary={viz_paths['coverage_lane_effective_region_summary']}")
    print(f"coverage_sweeps_summary={viz_paths['coverage_sweeps_summary']}")
    print(f"sweep_node_chain_debug={viz_paths['sweep_node_chain_debug']}")
    print(f"sweep_cadence_debug={viz_paths['sweep_cadence_debug']}")
    print(f"sweep_cadence_classification_inputs_debug={viz_paths['sweep_cadence_classification_inputs_debug']}")
    print(f"sweep_cadence_connection_rules_debug={viz_paths['sweep_cadence_connection_rules_debug']}")
    print(f"final_coverage_path_debug={viz_paths['final_coverage_path_debug']}")
    print(f"junction_connection_summary={viz_paths['junction_connection_summary']}")
    print(f"graph_node_count={len(coverage_result.graph_info.nodes)}")
    print(f"graph_edge_count={len(coverage_result.graph_info.edges)}")
    print(f"coverage_lane_unit_count={len(coverage_result.coverage_lane_sweep_info.coverage_lane_info)}")
    print(f"sweep_count={len(coverage_result.coverage_lane_sweep_info.sweeps)}")
    print(f"sweep_group_count={len(coverage_result.sweep_graph_build_info.sweep_group_info['groups'])}")
    print(f"connection_unit_count={len(coverage_result.sweep_graph_build_info.sweep_graph_info['connection_units'])}")
    print(f"sweep_transition_count={len(coverage_result.sweep_graph_build_info.sweep_graph_info['transitions'])}")
    print(f"sweep_cadence_count={len(coverage_result.sweep_cadence_build_info.sweep_cadence_info['routes'])}")
    print(f"junction_connection_count={len(coverage_result.final_coverage_path_build_info.final_coverage_path_info.get('junction_connections', ()))}")
    print(f"covered_sweep_count={coverage_result.sweep_cadence_build_info.coverage_stats['covered_sweep_count']}")
    print(f"total_sweep_count={coverage_result.sweep_cadence_build_info.coverage_stats['total_sweep_count']}")
    print(f"coverage_ratio={coverage_result.sweep_cadence_build_info.coverage_stats['coverage_ratio']}")


if __name__ == "__main__":
    main()
