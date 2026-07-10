from __future__ import annotations

import json
import math
import shutil
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from ...contracts import (
    CoveragePlanningDiagnostics,
    CoveragePlanningFinalPathSummary,
    CoveragePlanningFinalPathValidation,
    CoveragePlanningPipelineMeta,
    CoveragePlanningRequest,
    CoveragePlanningResult,
    CoveragePlanningRuntimeDetails,
    CoveragePlanningStatus,
    CoveragePose2D,
)
from ...preprocessing import resolve_request_region_mask


class ChannelTopologyGraphStageError(RuntimeError):
    """Wrap a CTG stage failure with stable stage/artifact context."""

    def __init__(
        self,
        *,
        stage_name: str,
        artifacts_dir: Path | None,
        original_exc: Exception,
    ) -> None:
        self.stage_name = str(stage_name)
        self.artifacts_dir = artifacts_dir
        self.original_exc = original_exc
        super().__init__(f"{self.stage_name}: {self.original_exc}")


def build_region_mask_from_request(request: CoveragePlanningRequest) -> np.ndarray | None:
    """Build a full-image region mask from formal mask truth or polygon fallback."""

    return resolve_request_region_mask(request)


def build_channel_topology_graph_config(request: CoveragePlanningRequest) -> dict[str, Any]:
    """Build stage configs for the in-memory CTG pipeline."""

    assert request.public_config is not None
    private_config = request.private_config
    coverage_width_m = float(request.public_config.coverage_width_m)
    robot_width_m = float(request.public_config.robot_width_m)
    if "robot_width_m" not in request.public_config_source_keys and coverage_width_m > 0.0:
        robot_width_m = coverage_width_m
    elif robot_width_m <= 0.0 and coverage_width_m > 0.0:
        robot_width_m = coverage_width_m

    return {
        "geometry_preparation": {
            "input_is_prepared_map": True,
            "resolution_m_per_px": float(request.map_resolution),
            "open_kernel_m": float(
                private_config.ctg_open_kernel_m
                if private_config is not None and private_config.ctg_open_kernel_m is not None
                else request.public_config.open_kernel_m
            ),
            "short_side_branch_m": float(
                private_config.ctg_short_side_branch_m
                if private_config is not None and private_config.ctg_short_side_branch_m is not None
                else request.public_config.short_side_branch_m
            ),
            "crop_pad_px": int(
                private_config.ctg_crop_pad_px
                if private_config is not None and private_config.ctg_crop_pad_px is not None
                else (
                    private_config.crop_pad_px
                    if private_config is not None and private_config.crop_pad_px is not None
                    else 0
                )
            ),
        },
        "junction_rebuild": {
            "intersection_merge_geodesic_px": int(
                private_config.ctg_intersection_merge_geodesic_px
                if private_config is not None and private_config.ctg_intersection_merge_geodesic_px is not None
                else request.public_config.intersection_merge_geodesic_px
            ),
            "initial_junction_zone_radius_px": int(
                private_config.ctg_initial_junction_zone_radius_px
                if private_config is not None and private_config.ctg_initial_junction_zone_radius_px is not None
                else 2
            ),
            "initial_dead_end_zone_radius_px": int(
                private_config.ctg_initial_dead_end_zone_radius_px
                if private_config is not None and private_config.ctg_initial_dead_end_zone_radius_px is not None
                else 1
            ),
            "junction_polygon_radius_px": float(
                private_config.ctg_junction_polygon_radius_px
                if private_config is not None and private_config.ctg_junction_polygon_radius_px is not None
                else request.public_config.junction_polygon_radius_px
            ),
            "dead_end_polygon_radius_px": float(
                private_config.ctg_dead_end_polygon_radius_px
                if private_config is not None and private_config.ctg_dead_end_polygon_radius_px is not None
                else 4.0
            ),
            "include_truncation_debug": bool(
                private_config.ctg_include_truncation_debug
                if private_config is not None and private_config.ctg_include_truncation_debug is not None
                else request.public_config.write_artifacts
            ),
            "pure_cycle_parallel_workers": int(
                private_config.ctg_pure_cycle_parallel_workers
                if private_config is not None and private_config.ctg_pure_cycle_parallel_workers is not None
                else 8
            ),
        },
        "topology_graph_build": {},
        "coverage_planning": {
            "coverage_width_m": coverage_width_m,
            "free_node_min_clearance_m": float(request.public_config.free_node_min_clearance_m),
            "robot_width_m": float(robot_width_m),
        },
        "runtime": {
            "adapter_name": "channel_topology_graph_adapter",
        },
    }


def _make_ctg_run_dir(request: CoveragePlanningRequest) -> Path | None:
    """Create a per-run CTG artifact directory under the existing GUI/tool root."""

    output_root = request.artifacts_output_root
    if output_root is None:
        return None
    normalized_root = Path(output_root).expanduser().resolve()
    normalized_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = normalized_root / f"{timestamp}_selected-channel_topology_graph"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _copy_prepare_map_artifacts(
    *,
    request: CoveragePlanningRequest,
    run_dir: Path | None,
) -> None:
    """Reuse the already-written prepare_map directory under the per-run CTG output."""

    if run_dir is None or request.artifacts_output_root is None:
        return
    source_dir = Path(request.artifacts_output_root).expanduser().resolve() / "prepare_map"
    if not source_dir.is_dir():
        return
    target_dir = run_dir / "prepare_map"
    shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)


def _build_stage_extra_meta(
    *,
    request: CoveragePlanningRequest,
    run_dir: Path | None,
) -> dict[str, Any]:
    """Build lightweight stage write-out metadata for GUI CTG runs."""

    return {
        "source": "coverage_planning_router",
        "map_yaml_path": str(request.map_yaml_path or ""),
        "artifacts_dir": str(run_dir or ""),
    }


def _write_pipeline_failure_payload(
    *,
    run_dir: Path | None,
    failed_stage: str,
    exc: Exception,
) -> None:
    """Persist a lightweight pipeline failure manifest when CTG aborts mid-stage."""

    if run_dir is None:
        return
    payload = {
        "failed_stage": str(failed_stage),
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "traceback": traceback.format_exc(),
    }
    (run_dir / "pipeline_failure.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_ctg_with_stage_artifacts(
    request: CoveragePlanningRequest,
) -> tuple[Any, Path | None]:
    """Run CTG stage-by-stage and persist the same staged outputs used by real-case runners."""

    from algorithms.channel_topology_graph.io import (
        write_coverage_planning_result_json,
        write_coverage_planning_summary,
        write_geometry_preparation_summary,
        write_junction_rebuild_summary,
        write_topology_graph_build_summary,
    )
    from algorithms.channel_topology_graph.pipeline.main_pipeline import (
        PipelineConfig,
        PipelineInput,
        PipelineStages,
        build_pipeline_run_result,
        build_pipeline_runtime_context,
        normalize_pipeline_runtime_inputs,
        run_coverage_planning_stage,
        run_geometry_preparation_stage,
        run_junction_rebuild_stage,
        run_topology_graph_build_stage,
    )
    from algorithms.channel_topology_graph.renderers import (
        write_coverage_planning_visualizations,
        write_geometry_preparation_visualizations,
        write_junction_rebuild_visualizations,
    )

    region_mask = build_region_mask_from_request(request)
    pipeline_input = PipelineInput(
        raw_map=np.asarray(request.prepared_map),
        region_constraint=region_mask,
        meta={
            "source": "coverage_planning_router",
            "map_yaml_path": str(request.map_yaml_path or ""),
        },
    )
    config_obj, stages = normalize_pipeline_runtime_inputs(
        config=PipelineConfig(**build_channel_topology_graph_config(request)),
        stages=PipelineStages(),
    )
    runtime_context = build_pipeline_runtime_context(config_obj)
    run_dir = _make_ctg_run_dir(request)
    _copy_prepare_map_artifacts(request=request, run_dir=run_dir)
    extra_meta = _build_stage_extra_meta(request=request, run_dir=run_dir)

    try:
        geometry_result = run_geometry_preparation_stage(
            pipeline_input=pipeline_input,
            config=config_obj,
            stages=stages,
        )
        if run_dir is not None:
            geometry_dir = run_dir / "geometry_preparation"
            write_geometry_preparation_summary(geometry_result, geometry_dir, extra_meta=extra_meta)
            write_geometry_preparation_visualizations(
                geometry_result,
                geometry_dir / "viz",
                summary_viz=True,
                detail_viz=True,
                render_scale=8,
            )
    except Exception as exc:
        _write_pipeline_failure_payload(run_dir=run_dir, failed_stage="geometry_preparation", exc=exc)
        raise ChannelTopologyGraphStageError(
            stage_name="geometry_preparation",
            artifacts_dir=run_dir,
            original_exc=exc,
        ) from exc

    runtime_context["geometry_preparation_result"] = geometry_result

    try:
        junction_result = run_junction_rebuild_stage(
            geometry_preparation_result=geometry_result,
            config=config_obj,
            stages=stages,
            runtime_context=runtime_context,
        )
        if run_dir is not None:
            junction_dir = run_dir / "junction_rebuild"
            write_junction_rebuild_summary(junction_result, junction_dir, extra_meta=extra_meta)
            write_junction_rebuild_visualizations(
                geometry_result=geometry_result,
                result=junction_result,
                output_dir=junction_dir / "viz",
                summary_viz=True,
                detail_viz=True,
                render_scale=8,
            )
    except Exception as exc:
        _write_pipeline_failure_payload(run_dir=run_dir, failed_stage="junction_rebuild", exc=exc)
        raise ChannelTopologyGraphStageError(
            stage_name="junction_rebuild",
            artifacts_dir=run_dir,
            original_exc=exc,
        ) from exc

    try:
        topology_result = run_topology_graph_build_stage(
            junction_rebuild_result=junction_result,
            config=config_obj,
            stages=stages,
            runtime_context=runtime_context,
        )
        if run_dir is not None:
            topology_dir = run_dir / "topology_graph_build"
            write_topology_graph_build_summary(topology_result, topology_dir, extra_meta=extra_meta)
    except Exception as exc:
        _write_pipeline_failure_payload(run_dir=run_dir, failed_stage="topology_graph_build", exc=exc)
        raise ChannelTopologyGraphStageError(
            stage_name="topology_graph_build",
            artifacts_dir=run_dir,
            original_exc=exc,
        ) from exc

    try:
        coverage_result = run_coverage_planning_stage(
            topology_graph_build_result=topology_result,
            config=config_obj,
            stages=stages,
            runtime_context=runtime_context,
        )
        if run_dir is not None:
            coverage_dir = run_dir / "coverage_planning"
            write_coverage_planning_summary(coverage_result, coverage_dir, extra_meta=extra_meta)
            write_coverage_planning_result_json(coverage_result, coverage_dir)
            write_coverage_planning_visualizations(
                geometry_result=geometry_result,
                result=coverage_result,
                output_dir=coverage_dir / "viz",
                render_scale=8,
            )
    except Exception as exc:
        _write_pipeline_failure_payload(run_dir=run_dir, failed_stage="coverage_planning", exc=exc)
        raise ChannelTopologyGraphStageError(
            stage_name="coverage_planning",
            artifacts_dir=run_dir,
            original_exc=exc,
        ) from exc

    return (
        build_pipeline_run_result(
            stage_results={
                "geometry_preparation_result": geometry_result,
                "junction_rebuild_result": junction_result,
                "topology_graph_build_result": topology_result,
                "coverage_planning_result": coverage_result,
            },
            runtime_context=runtime_context,
            pipeline_input=pipeline_input,
        ),
        run_dir,
    )


def _flatten_final_path_points_rc(final_path_info: dict[str, Any]) -> tuple[tuple[float, float], ...]:
    routes = tuple(final_path_info.get("routes", ()))
    points: list[tuple[float, float]] = []
    for route in routes:
        for subchain in tuple(route.get("path_subchains_rc", ())):
            for row, col in tuple(subchain):
                current = (float(row), float(col))
                if points and math.hypot(points[-1][0] - current[0], points[-1][1] - current[1]) <= 1e-9:
                    continue
                points.append(current)
    return tuple(points)


def _theta_from_pixels(
    path_pixels: tuple[tuple[float, float], ...],
    index: int,
) -> float:
    if len(path_pixels) <= 1:
        return 0.0
    current = path_pixels[index]
    other = path_pixels[index + 1] if index < len(path_pixels) - 1 else path_pixels[index - 1]
    dx = float(other[0] - current[0])
    # Image y grows downward while world y grows upward.
    dy = -float(other[1] - current[1])
    return float(math.atan2(dy, dx))


def _to_formal_path(
    *,
    points_rc: tuple[tuple[float, float], ...],
    crop_box_px: tuple[int, int, int, int],
    map_height: int,
    resolution_m_per_px: float,
    map_origin_xy: tuple[float, float],
) -> tuple[tuple[CoveragePose2D, ...], tuple[tuple[float, float], ...]]:
    top, left, _, _ = crop_box_px
    path_pixels = tuple((float(col + left), float(row + top)) for row, col in points_rc)
    path = tuple(
        CoveragePose2D(
            x=float(map_origin_xy[0] + pixel_x * resolution_m_per_px),
            y=float(map_origin_xy[1] + (float(map_height) - pixel_y) * resolution_m_per_px),
            theta=_theta_from_pixels(path_pixels, index),
        )
        for index, (pixel_x, pixel_y) in enumerate(path_pixels)
    )
    return path, path_pixels


def _build_success_result(
    *,
    request: CoveragePlanningRequest,
    pipeline_result: Any,
    artifacts_dir: Path | None = None,
) -> CoveragePlanningResult:
    coverage_result = pipeline_result.coverage_planning_result
    final_build_info = coverage_result.final_coverage_path_build_info
    final_path_info = dict(final_build_info.final_coverage_path_info if final_build_info is not None else {})
    points_rc = _flatten_final_path_points_rc(final_path_info)
    if not points_rc:
        return CoveragePlanningResult(
            status=CoveragePlanningStatus.FAILURE,
            error_message="channel_topology_graph produced no final path points",
        diagnostics=CoveragePlanningDiagnostics(
            selected_planner="channel_topology_graph",
            scene_type="aisle_like",
            fallback_chain=(),
            reasons=("ctg_final_path_empty",),
            artifacts_dir=str(artifacts_dir or ""),
            applied_public_config=request.public_config,
            runtime=CoveragePlanningRuntimeDetails(
                    pipeline_meta=CoveragePlanningPipelineMeta.from_mapping(
                        dict(getattr(pipeline_result, "meta", {}) or {})
                    ),
                    coverage_meta=dict(coverage_result.meta or {}),
                ),
            ),
        )

    geometry_result = pipeline_result.geometry_preparation_result
    path, path_pixels = _to_formal_path(
        points_rc=points_rc,
        crop_box_px=geometry_result.crop_box_px,
        map_height=int(np.asarray(request.prepared_map).shape[0]),
        resolution_m_per_px=float(geometry_result.resolution_m_per_px),
        map_origin_xy=request.map_origin_xy,
    )
    validation_info = dict(final_build_info.validation_info or {})
    status = CoveragePlanningStatus.SUCCESS if bool(validation_info.get("is_valid", True)) else CoveragePlanningStatus.FAILURE
    return CoveragePlanningResult(
        status=status,
        path=path,
        path_pixels=path_pixels,
        error_message="" if status == CoveragePlanningStatus.SUCCESS else "channel_topology_graph final path validation failed",
        diagnostics=CoveragePlanningDiagnostics(
            selected_planner="channel_topology_graph",
            scene_type="aisle_like",
            fallback_chain=(),
            reasons=("explicit_channel_topology_graph_enabled",),
            warnings=() if status == CoveragePlanningStatus.SUCCESS else ("ctg_final_path_validation_failed",),
            artifacts_dir=str(artifacts_dir or ""),
            applied_public_config=request.public_config,
            runtime=CoveragePlanningRuntimeDetails(
                pipeline_meta=CoveragePlanningPipelineMeta.from_mapping(
                    dict(getattr(pipeline_result, "meta", {}) or {})
                ),
                coverage_meta=dict(coverage_result.meta or {}),
                final_path_summary=CoveragePlanningFinalPathSummary.from_mapping(
                    dict(final_build_info.summary or {})
                ),
                final_path_validation=CoveragePlanningFinalPathValidation.from_mapping(validation_info),
            ),
        ),
    )


def run_channel_topology_graph_adapter(request: CoveragePlanningRequest) -> CoveragePlanningResult:
    """Run the channel-topology graph planner through the formal result contract."""

    try:
        pipeline_result, artifacts_dir = _run_ctg_with_stage_artifacts(request)
        return _build_success_result(
            request=request,
            pipeline_result=pipeline_result,
            artifacts_dir=artifacts_dir,
        )
    except ChannelTopologyGraphStageError as exc:
        return CoveragePlanningResult(
            status=CoveragePlanningStatus.FAILURE,
            error_message=f"channel_topology_graph failed at {exc.stage_name}: {exc.original_exc}",
            diagnostics=CoveragePlanningDiagnostics(
                selected_planner="channel_topology_graph",
                scene_type="aisle_like",
                fallback_chain=(),
                reasons=("ctg_adapter_stage_exception",),
                warnings=(f"failed_stage={exc.stage_name}", str(exc.original_exc)),
                artifacts_dir=str(exc.artifacts_dir or ""),
                applied_public_config=request.public_config,
            ),
        )
    except Exception as exc:
        return CoveragePlanningResult(
            status=CoveragePlanningStatus.FAILURE,
            error_message=f"channel_topology_graph failed: {exc}",
            diagnostics=CoveragePlanningDiagnostics(
                selected_planner="channel_topology_graph",
                scene_type="aisle_like",
                fallback_chain=(),
                reasons=("ctg_adapter_exception",),
                warnings=(str(exc),),
                applied_public_config=request.public_config,
            ),
        )
