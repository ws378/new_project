"""使用真实 case 跑第 1、2、3 步联调。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import sys

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.channel_topology_graph.io import load_plan1_case_input  # noqa: E402
from algorithms.channel_topology_graph.io import write_topology_graph_build_summary  # noqa: E402
from algorithms.channel_topology_graph.stages.geometry_preparation import build_geometry_preparation  # noqa: E402
from algorithms.channel_topology_graph.stages.junction_rebuild import build_junction_rebuild  # noqa: E402
from algorithms.channel_topology_graph.stages.topology_graph_build import build_topology_graph  # noqa: E402


def main() -> None:
    """执行真实 case 的第 1、2、3 步联调。"""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(__file__).resolve().parents[2] / "test_outputs" / f"topology_graph_build_real_case_{timestamp}"
    output_root.mkdir(parents=True, exist_ok=True)

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
    summary_path = write_topology_graph_build_summary(
        result=topology_result,
        output_dir=output_root,
        extra_meta={
            "case_dir": str(case_dir),
        },
    )

    print(f"output_dir={output_root}")
    print(f"summary_json={summary_path}")
    print(f"graph_node_count={len(topology_result.graph_info.nodes)}")
    print(f"graph_edge_count={len(topology_result.graph_info.edges)}")
    incident_port_info = topology_result.incident_port_info or {}
    node_local_connection_hypothesis_info = topology_result.node_local_connection_hypothesis_info or {}
    print(f"incident_port_count={len(incident_port_info.get('items', ()))}")
    print(f"node_with_ports_count={len(incident_port_info.get('items_by_node', {}))}")
    print(f"node_local_hypothesis_count={len(node_local_connection_hypothesis_info.get('items', ()))}")
    print(
        "node_with_hypotheses_count="
        f"{len(node_local_connection_hypothesis_info.get('items_by_node', {}))}"
    )


if __name__ == "__main__":
    main()
