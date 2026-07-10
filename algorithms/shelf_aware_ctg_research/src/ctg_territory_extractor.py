from __future__ import annotations

from typing import Any

import numpy as np

from algorithms.channel_topology_graph.coverage_planning import build_coverage_lane_sweep_info
from algorithms.channel_topology_graph.pipeline import PipelineConfig, PipelineInput, PipelineStages
from algorithms.channel_topology_graph.pipeline.main_pipeline import (
    build_pipeline_runtime_context,
    normalize_pipeline_runtime_inputs,
    run_geometry_preparation_stage,
    run_junction_rebuild_stage,
    run_topology_graph_build_stage,
)

from .project_inputs import StudyInput


def build_ctg_stage_config(study_input: StudyInput, *, apply_boundary_smoothing: bool = True) -> PipelineConfig:
    return PipelineConfig(
        geometry_preparation={
            "input_is_prepared_map": True,
            "resolution_m_per_px": float(study_input.map_resolution),
            "open_kernel_m": float(study_input.public_config.open_kernel_m),
            "short_side_branch_m": float(study_input.public_config.short_side_branch_m),
            "crop_pad_px": 0,
            "boundary_smoothing_enable": bool(apply_boundary_smoothing),
        },
        junction_rebuild={
            "intersection_merge_geodesic_px": int(study_input.public_config.intersection_merge_geodesic_px),
            "initial_junction_zone_radius_px": 2,
            "initial_dead_end_zone_radius_px": 1,
            "junction_polygon_radius_px": float(study_input.public_config.junction_polygon_radius_px),
            "dead_end_polygon_radius_px": 4.0,
        },
        topology_graph_build={},
        coverage_planning={
            "coverage_width_m": float(study_input.public_config.coverage_width_m),
            "free_node_min_clearance_m": float(study_input.public_config.free_node_min_clearance_m),
            "robot_width_m": float(study_input.public_config.robot_width_m),
        },
        runtime={"adapter_name": "shelf_aware_ctg_research"},
    )


def run_geometry_preparation(
    study_input: StudyInput,
    config: PipelineConfig,
    stages: PipelineStages,
    raw_map: np.ndarray,
    region_constraint: np.ndarray,
    source: str,
) -> Any:
    pipeline_input = PipelineInput(
        raw_map=np.asarray(raw_map),
        region_constraint=np.asarray(region_constraint),
        meta={
            "source": source,
            "project_dir": str(study_input.project_dir),
            "area_id": int(study_input.area.area_id),
        },
    )
    return run_geometry_preparation_stage(
        pipeline_input=pipeline_input,
        config=config,
        stages=stages,
    )


def extract_ctg_territory(study_input: StudyInput, *, apply_boundary_smoothing: bool = True) -> dict[str, Any]:
    config, stages = normalize_pipeline_runtime_inputs(
        config=build_ctg_stage_config(study_input, apply_boundary_smoothing=apply_boundary_smoothing),
        stages=PipelineStages(),
    )
    runtime_context = build_pipeline_runtime_context(config)
    geometry_result = run_geometry_preparation(
        study_input=study_input,
        config=config,
        stages=stages,
        raw_map=study_input.prepared_map,
        region_constraint=study_input.region_mask,
        source="shelf_aware_ctg_research",
    )
    baseline_geometry_result = geometry_result
    boundary_smoothing = None

    runtime_context["geometry_preparation_result"] = geometry_result
    junction_result = run_junction_rebuild_stage(
        geometry_preparation_result=geometry_result,
        config=config,
        stages=stages,
        runtime_context=runtime_context,
    )
    topology_result = run_topology_graph_build_stage(
        junction_rebuild_result=junction_result,
        config=config,
        stages=stages,
        runtime_context=runtime_context,
    )
    coverage_lane_sweep_info = build_coverage_lane_sweep_info(
        graph_info=topology_result.graph_info,
        geometry_result=geometry_result,
        config=config.coverage_planning,
    )
    return {
        "baseline_geometry_result": baseline_geometry_result,
        "boundary_smoothing": boundary_smoothing,
        "geometry_result": geometry_result,
        "junction_result": junction_result,
        "topology_result": topology_result,
        "coverage_lane_sweep_info": coverage_lane_sweep_info,
    }
