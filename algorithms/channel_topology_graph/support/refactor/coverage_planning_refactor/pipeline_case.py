"""固定 real-case 入口，供覆盖规划局部重构基线与 compare 使用。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.channel_topology_graph.io import load_plan1_case_input
from algorithms.channel_topology_graph.stages.coverage_planning import build_coverage_plan
from algorithms.channel_topology_graph.stages.geometry_preparation import build_geometry_preparation
from algorithms.channel_topology_graph.stages.junction_rebuild import build_junction_rebuild
from algorithms.channel_topology_graph.stages.topology_graph_build import build_topology_graph


@dataclass(frozen=True)
class CoveragePlanningFixedCaseSpec:
    """当前覆盖规划局部重构的固定输入规格。"""

    case_name: str
    case_dir: Path
    geometry_config: dict[str, Any]
    junction_config: dict[str, Any]
    coverage_config: dict[str, Any]


def fixed_case_spec() -> CoveragePlanningFixedCaseSpec:
    """返回当前冻结的 real-case 输入规格。"""

    case_dir = (
        REPO_ROOT
        / "tests"
        / "fixtures"
        / "coverage_cases"
        / "case_demo"
    )
    coverage_width_m = 0.55
    robot_width_m = 0.55
    return CoveragePlanningFixedCaseSpec(
        case_name="case_01",
        case_dir=case_dir,
        geometry_config={
            "open_kernel_m": 0.3,
            "short_side_branch_m": 1.2,
            "summary_viz": False,
            "detail_viz": False,
        },
        junction_config={
            "intersection_merge_geodesic_px": 20,
            "initial_junction_zone_radius_px": 2,
            "initial_dead_end_zone_radius_px": 1,
            "junction_polygon_radius_px": 10.0,
            "dead_end_polygon_radius_px": 4.0,
            "summary_viz": False,
            "detail_viz": False,
        },
        coverage_config={
            "coverage_width_m": coverage_width_m,
            "free_node_min_clearance_m": 0.35,
            "robot_width_m": robot_width_m,
        },
    )


def run_fixed_case() -> dict[str, Any]:
    """运行固定 case，并返回 1/2/3/4 步结果。"""

    spec = fixed_case_spec()
    case_input = load_plan1_case_input(case_dir=spec.case_dir)
    geometry_config = {
        **dict(spec.geometry_config),
        "crop_box_px": list(case_input.meta["crop_box_px"]),
    }
    geometry_result = build_geometry_preparation(
        raw_map=case_input.raw_map,
        region_constraint=case_input.region_constraint,
        config=geometry_config,
    )
    junction_result = build_junction_rebuild(
        geometry_preparation_result=geometry_result,
        config=dict(spec.junction_config),
    )
    topology_result = build_topology_graph(junction_result)
    coverage_result = build_coverage_plan(
        topology_result,
        config={
            "coverage_width_m": float(spec.coverage_config["coverage_width_m"]),
            "free_node_min_clearance_m": float(spec.coverage_config["free_node_min_clearance_m"]),
            "robot_width_m": float(spec.coverage_config["robot_width_m"]),
        },
        context={"geometry_preparation_result": geometry_result},
    )
    return {
        "spec": spec,
        "resolved_geometry_config": geometry_config,
        "geometry_result": geometry_result,
        "junction_result": junction_result,
        "topology_result": topology_result,
        "coverage_result": coverage_result,
    }
