"""junction_rebuild 真实数据集成测试。"""

from __future__ import annotations

from pathlib import Path

from algorithms.channel_topology_graph.io import load_plan1_case_input
from algorithms.channel_topology_graph.stages.geometry_preparation import build_geometry_preparation
from algorithms.channel_topology_graph.stages.junction_rebuild import build_junction_rebuild


def test_junction_rebuild_runs_on_current_ctg_case() -> None:
    """当前 CTG 测试集真实 case 上的 geometry_preparation 与 junction_rebuild 应能稳定跑通。"""

    repo_root = Path(__file__).resolve().parents[3]
    case_dir = (
        repo_root
        / "coverage_dataset"
        / "cases"
        / "channel_topology_graph"
        / "business_maps"
        / "beiguo_lanshan_1770397756"
        / "crop_S_01"
    )
    case_input = load_plan1_case_input(case_dir=case_dir)
    geometry_result = build_geometry_preparation(
        raw_map=case_input.raw_map,
        region_constraint=case_input.region_constraint,
        config={
            "crop_box_px": case_input.meta["crop_box_px"],
            "open_kernel_m": 0.3,
            "short_side_branch_m": 1.2,
        },
    )
    rebuild_result = build_junction_rebuild(
        geometry_preparation_result=geometry_result,
        config={
            "intersection_merge_geodesic_px": 20,
            "initial_junction_zone_radius_px": 2,
            "initial_dead_end_zone_radius_px": 1,
            "dead_end_polygon_radius_px": 4.0,
        },
    )

    assert len(rebuild_result.node_info_list) > 0
    assert len(rebuild_result.edge_info_list) > 0
    assert all(item.path_rc for item in rebuild_result.edge_info_list)
    assert any(item.node_type == "junction" for item in rebuild_result.node_info_list)
    assert all(item.polygon_vertices_rc for item in rebuild_result.node_info_list if item.node_type == "junction")
