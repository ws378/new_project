"""固定全链 real-case 入口，供 baseline 与 compare 使用。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.channel_topology_graph.io import load_plan1_case_input
from algorithms.channel_topology_graph.pipeline.main_pipeline import (
    PipelineConfig,
    PipelineInput,
    run_channel_topology_graph_pipeline,
)


@dataclass(frozen=True)
class ChannelTopologyGraphFixedCaseSpec:
    """当前全链重构对照使用的固定输入规格。"""

    case_name: str
    case_dir: Path
    geometry_config: dict[str, Any]
    junction_config: dict[str, Any]
    topology_config: dict[str, Any]
    coverage_config: dict[str, Any]
    runtime_config: dict[str, Any]


def fixed_case_spec() -> ChannelTopologyGraphFixedCaseSpec:
    """返回当前冻结的全链 real-case 输入规格。"""

    case_dir = (
        REPO_ROOT
        / "tests"
        / "fixtures"
        / "coverage_cases"
        / "case_demo"
    )
    coverage_width_m = 0.55
    robot_width_m = 0.55
    return ChannelTopologyGraphFixedCaseSpec(
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
        topology_config={},
        coverage_config={
            "coverage_width_m": coverage_width_m,
            "free_node_min_clearance_m": 0.35,
            "robot_width_m": robot_width_m,
        },
        runtime_config={},
    )


def resolve_pipeline_config(spec: ChannelTopologyGraphFixedCaseSpec, case_input: Any) -> PipelineConfig:
    """把冻结规格解析成正式 pipeline 配置。"""

    geometry_config = {
        **dict(spec.geometry_config),
        "crop_box_px": list(case_input.meta["crop_box_px"]),
    }
    return PipelineConfig(
        geometry_preparation=geometry_config,
        junction_rebuild=dict(spec.junction_config),
        topology_graph_build=dict(spec.topology_config),
        coverage_planning={
            "coverage_width_m": float(spec.coverage_config["coverage_width_m"]),
            "free_node_min_clearance_m": float(spec.coverage_config["free_node_min_clearance_m"]),
            "robot_width_m": float(spec.coverage_config["robot_width_m"]),
        },
        runtime=dict(spec.runtime_config),
    )


def run_fixed_case() -> dict[str, Any]:
    """运行固定 case，并返回全链 4 步结果。"""

    spec = fixed_case_spec()
    case_input = load_plan1_case_input(case_dir=spec.case_dir)
    pipeline_config = resolve_pipeline_config(spec, case_input)
    pipeline_result = run_channel_topology_graph_pipeline(
        pipeline_input=PipelineInput(
            raw_map=case_input.raw_map,
            region_constraint=case_input.region_constraint,
            meta={
                "case_name": spec.case_name,
                "case_dir": str(spec.case_dir),
            },
        ),
        config=pipeline_config,
    )
    return {
        "spec": spec,
        "resolved_pipeline_config": {
            "geometry_preparation": dict(pipeline_config.geometry_preparation),
            "junction_rebuild": dict(pipeline_config.junction_rebuild),
            "topology_graph_build": dict(pipeline_config.topology_graph_build),
            "coverage_planning": dict(pipeline_config.coverage_planning),
            "runtime": dict(pipeline_config.runtime),
        },
        "pipeline_result": pipeline_result,
    }
