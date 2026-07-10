from __future__ import annotations

import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from algorithms.channel_topology_graph.contracts import JunctionRebuildResult
from algorithms.channel_topology_graph.io import (
    write_geometry_preparation_summary,
    write_junction_rebuild_summary,
)
from algorithms.channel_topology_graph.io.result_jsonable import to_jsonable
from algorithms.channel_topology_graph.pipeline import PipelineConfig, PipelineInput, PipelineStages
from algorithms.channel_topology_graph.pipeline.main_pipeline import (
    build_pipeline_runtime_context,
    normalize_pipeline_runtime_inputs,
    run_geometry_preparation_stage,
)
from algorithms.channel_topology_graph.renderers import (
    write_geometry_preparation_visualizations,
    write_junction_rebuild_visualizations,
)
from algorithms.channel_topology_graph.stages.junction_rebuild import (
    build_junction_rebuild_result,
    build_junction_rebuild_stage_outputs,
    normalize_junction_rebuild_inputs,
)
from algorithms.territory_seed_research.src.ctg_territory_extractor import build_ctg_stage_config
from algorithms.territory_seed_research.src.fourfloor_inputs import DEFAULT_PROJECT_DIR, PACKAGE_ROOT, build_study_input


AREA_ID = 6


def make_run_dir() -> Path:
    run_name = "run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_area6_ctg_diagnostic"
    run_dir = PACKAGE_ROOT / "output" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def extra_meta(run_dir: Path) -> dict[str, Any]:
    return {
        "source": "territory_seed_research_area6_diagnostic",
        "area_id": AREA_ID,
        "artifacts_dir": str(run_dir),
        "project_dir": str(DEFAULT_PROJECT_DIR),
    }


def build_runtime(study_input: Any) -> tuple[PipelineConfig, PipelineStages, dict[str, Any]]:
    config_obj, stages = normalize_pipeline_runtime_inputs(
        config=build_ctg_stage_config(study_input),
        stages=PipelineStages(),
    )
    return config_obj, stages, build_pipeline_runtime_context(config_obj)


def run_geometry_stage(study_input: Any, run_dir: Path) -> tuple[Any, PipelineConfig, PipelineStages, dict[str, Any]]:
    config_obj, stages, runtime_context = build_runtime(study_input)
    pipeline_input = PipelineInput(
        raw_map=np.asarray(study_input.prepared_map),
        region_constraint=np.asarray(study_input.region_mask),
        meta={
            "source": "territory_seed_research_area6_diagnostic",
            "project_dir": str(study_input.project_dir),
            "area_id": int(study_input.area.area_id),
        },
    )
    geometry_result = run_geometry_preparation_stage(
        pipeline_input=pipeline_input,
        config=config_obj,
        stages=stages,
    )
    geometry_dir = run_dir / "geometry_preparation"
    write_geometry_preparation_summary(geometry_result, geometry_dir, extra_meta=extra_meta(run_dir))
    write_geometry_preparation_visualizations(
        geometry_result,
        geometry_dir / "viz",
        summary_viz=True,
        detail_viz=True,
        render_scale=8,
    )
    runtime_context["geometry_preparation_result"] = geometry_result
    return geometry_result, config_obj, stages, runtime_context


def build_partial_junction_result(stage_outputs: dict[str, Any], validation_error: Exception) -> JunctionRebuildResult:
    return JunctionRebuildResult(
        node_info_list=tuple(stage_outputs["node_info_list"]),
        edge_info_list=tuple(stage_outputs["edge_info_list"]),
        debug_info={
            "merge_groups": stage_outputs["merge_debug"],
            "merge_groups_applied": stage_outputs["merge_apply_debug"].get("merge_groups_applied", []),
            "post_geometry_merge": stage_outputs["post_geometry_merge_debug"],
            "node_geometry": stage_outputs["node_geometry_debug"],
            "edge_geometry": stage_outputs["edge_geometry_debug"],
            "compact": stage_outputs["compact_debug"],
            "partial_result_reason": "junction_rebuild_result_validation_failed",
        },
        validation_info={
            "valid": False,
            "error_type": type(validation_error).__name__,
            "error_message": str(validation_error),
        },
        meta={
            "stage_name": "junction_rebuild",
            "partial": True,
        },
    )


def missing_polygon_junction_nodes(result: JunctionRebuildResult) -> list[Any]:
    return [
        node
        for node in result.node_info_list
        if str(node.node_type) == "junction" and len(tuple(node.polygon_vertices_rc or ())) == 0
    ]


def draw_failure_overlay(geometry_result: Any, result: JunctionRebuildResult, missing_nodes: list[Any], output_path: Path) -> None:
    image = cv2.cvtColor(np.asarray(geometry_result.gray, dtype=np.uint8), cv2.COLOR_GRAY2BGR)
    skeleton = np.asarray(geometry_result.skeleton_pruned_mask) > 0
    image[skeleton] = (255, 255, 0)

    for edge in result.edge_info_list:
        points = [(int(round(col)), int(round(row))) for row, col in tuple(edge.path_rc or ())]
        for start, end in zip(points, points[1:]):
            cv2.line(image, start, end, (0, 180, 255), 1, cv2.LINE_AA)

    missing_ids = {int(node.node_id) for node in missing_nodes}
    for node in result.node_info_list:
        row, col = node.point_rc
        center = (int(round(col)), int(round(row)))
        if int(node.node_id) in missing_ids:
            color = (0, 0, 255)
            radius = 7
            thickness = 2
        elif str(node.node_type) == "junction":
            color = (0, 160, 255)
            radius = 4
            thickness = 1
        else:
            color = (0, 220, 0)
            radius = 3
            thickness = 1
        cv2.circle(image, center, radius, color, thickness, cv2.LINE_AA)
        cv2.putText(image, str(int(node.node_id)), center, cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)

    cv2.imwrite(str(output_path), image)


def node_payload(node: Any) -> dict[str, Any]:
    return {
        "node_id": int(node.node_id),
        "node_type": str(node.node_type),
        "point_rc": [float(node.point_rc[0]), float(node.point_rc[1])],
        "degree": int(node.degree),
        "incident_edge_ids": [int(edge_id) for edge_id in tuple(node.incident_edge_ids or ())],
        "polygon_vertex_count": int(len(tuple(node.polygon_vertices_rc or ()))),
        "debug_info": to_jsonable(node.debug_info),
        "validation_info": to_jsonable(node.validation_info),
    }


def edge_payload(edge: Any) -> dict[str, Any]:
    return {
        "edge_id": int(edge.edge_id),
        "src_node_id": int(edge.src_node_id),
        "dst_node_id": int(edge.dst_node_id),
        "edge_type": str(edge.edge_type or ""),
        "path_point_count": int(len(tuple(edge.path_rc or ()))),
        "inner_path_point_count": int(len(tuple(edge.inner_path_rc or ()))),
        "outer_path_point_count": int(len(tuple(edge.outer_path_rc or ()))),
        "length_px": float(edge.length_px),
        "length_m": float(edge.length_m),
        "debug_info": to_jsonable(edge.debug_info),
        "validation_info": to_jsonable(edge.validation_info),
    }


def write_failure_debug(
    *,
    run_dir: Path,
    geometry_result: Any,
    stage_outputs: dict[str, Any],
    partial_result: JunctionRebuildResult,
    validation_error: Exception,
) -> None:
    missing_nodes = missing_polygon_junction_nodes(partial_result)
    missing_ids = {int(node.node_id) for node in missing_nodes}
    related_edges = [
        edge
        for edge in partial_result.edge_info_list
        if int(edge.src_node_id) in missing_ids or int(edge.dst_node_id) in missing_ids
    ]
    payload = {
        "failed_stage": "junction_rebuild",
        "failure_phase": "build_junction_rebuild_result_validation",
        "error_type": type(validation_error).__name__,
        "error_message": str(validation_error),
        "traceback": traceback.format_exc(),
        "missing_polygon_junction_count": int(len(missing_nodes)),
        "missing_polygon_junction_nodes": [node_payload(node) for node in missing_nodes],
        "related_edges": [edge_payload(edge) for edge in related_edges],
        "node_count": int(len(partial_result.node_info_list)),
        "edge_count": int(len(partial_result.edge_info_list)),
        "compact_debug": to_jsonable(stage_outputs.get("compact_debug", {})),
        "node_geometry_debug": to_jsonable(stage_outputs.get("node_geometry_debug", {})),
        "edge_geometry_debug": to_jsonable(stage_outputs.get("edge_geometry_debug", {})),
    }
    (run_dir / "junction_failure_debug.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    draw_failure_overlay(
        geometry_result,
        partial_result,
        missing_nodes,
        run_dir / "junction_failure_overlay.png",
    )


def write_pipeline_failure(run_dir: Path, exc: Exception) -> None:
    payload = {
        "failed_stage": "junction_rebuild",
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "traceback": traceback.format_exc(),
    }
    (run_dir / "pipeline_failure.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_diagnostic() -> Path:
    run_dir = make_run_dir()
    study_input = build_study_input(DEFAULT_PROJECT_DIR, AREA_ID, run_dir)
    geometry_result, config_obj, _, runtime_context = run_geometry_stage(study_input, run_dir)

    junction_config, junction_context = normalize_junction_rebuild_inputs(
        config_obj.junction_rebuild,
        runtime_context,
    )
    try:
        stage_outputs = build_junction_rebuild_stage_outputs(
            geometry_preparation_result=geometry_result,
            config=junction_config,
        )
        try:
            junction_result = build_junction_rebuild_result(
                stage_outputs=stage_outputs,
                context=junction_context,
            )
        except Exception as exc:
            partial_result = build_partial_junction_result(stage_outputs, exc)
            junction_dir = run_dir / "junction_rebuild"
            write_junction_rebuild_summary(partial_result, junction_dir, extra_meta=extra_meta(run_dir))
            write_junction_rebuild_visualizations(
                geometry_result=geometry_result,
                result=partial_result,
                output_dir=junction_dir / "viz",
                summary_viz=True,
                detail_viz=True,
                render_scale=8,
            )
            write_failure_debug(
                run_dir=run_dir,
                geometry_result=geometry_result,
                stage_outputs=stage_outputs,
                partial_result=partial_result,
                validation_error=exc,
            )
            write_pipeline_failure(run_dir, exc)
            return run_dir

        junction_dir = run_dir / "junction_rebuild"
        write_junction_rebuild_summary(junction_result, junction_dir, extra_meta=extra_meta(run_dir))
        write_junction_rebuild_visualizations(
            geometry_result=geometry_result,
            result=junction_result,
            output_dir=junction_dir / "viz",
            summary_viz=True,
            detail_viz=True,
            render_scale=8,
        )
    except Exception as exc:
        write_pipeline_failure(run_dir, exc)
    return run_dir


def main() -> None:
    print(run_diagnostic())


if __name__ == "__main__":
    main()
