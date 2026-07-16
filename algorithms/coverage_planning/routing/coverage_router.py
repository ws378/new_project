from __future__ import annotations

from dataclasses import replace

from ..contracts import (
    CoveragePlannerConfig,
    CoveragePlanningDiagnostics,
    CoveragePlanningRequest,
    CoveragePlanningResult,
    CoveragePlanningRuntimeDetails,
    CoveragePlanningStatus,
    CoveragePose2D,
)
from ..modes import (
    BASIC_IMPROVED_MODE,
    CHANNEL_TOPOLOGY_GRAPH_MODE,
    CSTAR_MODES,
    REGION_BASIC_ROUTED_MODE,
    ROUTED_PLANNER_MODES,
    SHELF_AWARE_MODE,
    config_planner_mode_from_routed_mode,
    is_shelf_aware_routed_mode,
)
from ..planners.region_basic import CoveragePlanner
from ..planners.shelf_aware_guarded import ShelfAwareCoveragePlanner
from ..preprocessing import (
    apply_region_constraint,
    resolve_request_region_mask,
    resolve_request_starting_position,
)
from ..quality_guard import build_shelf_quality_guard_meta, shelf_quality_guard_warnings
from .applicability import classify_applicability
from .adapters import run_channel_topology_graph_adapter


def _config_from_request(request: CoveragePlanningRequest, planner_mode: str) -> CoveragePlannerConfig:
    assert request.public_config is not None
    return replace(
        request.public_config,
        planner_mode=config_planner_mode_from_routed_mode(planner_mode),
        region_polygon_px=(
            [tuple(point) for point in request.region_polygon_px]
            if request.region_polygon_px
            else None
        ),
        map_yaml_path=str(request.map_yaml_path) if request.map_yaml_path is not None else "",
        artifacts_output_root=(
            str(request.artifacts_output_root) if request.artifacts_output_root is not None else ""
        ),
    )


def _create_planner(planner_name: str, config: CoveragePlannerConfig):
    if planner_name == REGION_BASIC_ROUTED_MODE:
        return CoveragePlanner(config)
    if is_shelf_aware_routed_mode(planner_name):
        return ShelfAwareCoveragePlanner(config)
    raise ValueError(f"unsupported routed planner: {planner_name}")


def _convert_path(path) -> tuple[CoveragePose2D, ...]:
    return tuple(
        CoveragePose2D(float(pose.x), float(pose.y), float(pose.theta))
        for pose in path
    )


def route_coverage_plan(request: CoveragePlanningRequest) -> CoveragePlanningResult:
    """Route a request to a conservative formal coverage planner."""

    applicability = classify_applicability(request)
    if applicability.scene_type == "invalid":
        return CoveragePlanningResult(
            status=CoveragePlanningStatus.UNSUPPORTED,
            error_message="coverage planning skipped: invalid scene",
            diagnostics=CoveragePlanningDiagnostics(
                selected_planner="",
                scene_type=applicability.scene_type,
                fallback_chain=applicability.fallback_chain,
                reasons=applicability.reasons,
                warnings=applicability.warnings,
                metrics=applicability.metrics,
                applied_public_config=request.public_config,
            ),
        )

    planner_name = applicability.recommended_planner
    if planner_name not in ROUTED_PLANNER_MODES:
        return CoveragePlanningResult(
            status=CoveragePlanningStatus.UNSUPPORTED,
            error_message=f"planner is not connected to routing: {planner_name}",
            diagnostics=CoveragePlanningDiagnostics(
                selected_planner=planner_name,
                scene_type=applicability.scene_type,
                fallback_chain=applicability.fallback_chain,
                reasons=applicability.reasons,
                warnings=applicability.warnings,
                metrics=applicability.metrics,
                applied_public_config=request.public_config,
            ),
        )
    if planner_name == CHANNEL_TOPOLOGY_GRAPH_MODE:
        result = run_channel_topology_graph_adapter(request)
        return CoveragePlanningResult(
            status=result.status,
            path=result.path,
            path_pixels=result.path_pixels,
            error_message=result.error_message,
            diagnostics=CoveragePlanningDiagnostics(
                selected_planner=result.diagnostics.selected_planner,
                scene_type=applicability.scene_type,
                fallback_chain=applicability.fallback_chain,
                reasons=tuple(applicability.reasons) + tuple(result.diagnostics.reasons),
                warnings=tuple(applicability.warnings) + tuple(result.diagnostics.warnings),
                metrics=applicability.metrics,
                artifacts_dir=result.diagnostics.artifacts_dir,
                applied_public_config=request.public_config,
                runtime=result.diagnostics.runtime,
            ),
        )

    if planner_name in CSTAR_MODES or planner_name == BASIC_IMPROVED_MODE:
        from ..planner_factory import run_formal_planner_request
        result = run_formal_planner_request(request, planner_name)
        if not result.success:
            return result
        return CoveragePlanningResult(
            status=result.status,
            path=result.path,
            path_pixels=result.path_pixels,
            diagnostics=CoveragePlanningDiagnostics(
                selected_planner=planner_name,
                scene_type=applicability.scene_type,
                fallback_chain=applicability.fallback_chain,
                reasons=tuple(applicability.reasons) + tuple(result.diagnostics.reasons),
                warnings=tuple(applicability.warnings) + tuple(result.diagnostics.warnings),
                metrics=applicability.metrics,
                artifacts_dir=result.diagnostics.artifacts_dir,
                applied_public_config=result.diagnostics.applied_public_config,
                runtime=result.diagnostics.runtime,
            ),
        )

    planner_config = _config_from_request(request, planner_name)
    planner = _create_planner(planner_name, planner_config)
    effective_map = apply_region_constraint(
        request.prepared_map,
        resolve_request_region_mask(request),
    )
    starting_position, start_snapped = resolve_request_starting_position(request, effective_map)
    if starting_position is None:
        return CoveragePlanningResult(
            status=CoveragePlanningStatus.FAILURE,
            error_message="区域内没有可通行空间，无法生成覆盖路径。",
            diagnostics=CoveragePlanningDiagnostics(
                selected_planner=planner_name,
                scene_type=applicability.scene_type,
                fallback_chain=applicability.fallback_chain,
                reasons=tuple(applicability.reasons) + ("no_free_start_pixel",),
                warnings=tuple(applicability.warnings) + ("区域内没有可通行空间，无法生成覆盖路径。",),
                metrics=applicability.metrics,
                applied_public_config=planner_config,
            ),
        )
    start_warnings = (
        (f"起点已从 {tuple(request.starting_position_px)} 吸附到最近可通行像素 {tuple(starting_position)}",)
        if start_snapped
        else ()
    )
    start_reasons = ("start_snapped_to_nearest_free_pixel",) if start_snapped else ()
    if is_shelf_aware_routed_mode(planner_name):
        result = planner.plan(
            effective_map,
            map_resolution=float(request.map_resolution),
            starting_position=starting_position,
            map_origin=request.map_origin_xy,
            region_mask=resolve_request_region_mask(request),
        )
    else:
        result = planner.plan(
            effective_map,
            map_resolution=float(request.map_resolution),
            starting_position=starting_position,
            map_origin=request.map_origin_xy,
        )

    quality_guard_meta = {"enabled": False}
    if planner_name == SHELF_AWARE_MODE and result.success:
        quality_guard_meta = build_shelf_quality_guard_meta(
            enabled=bool(getattr(planner_config, "shelf_quality_guard_enable", True)),
            effective_map=effective_map,
            path_pixels=result.path_pixels,
            coverage_width_m=float(planner_config.coverage_width_m),
            map_resolution=float(request.map_resolution),
            min_coverage_ratio=float(planner_config.shelf_quality_guard_min_coverage_ratio),
        )
    guard_warnings = shelf_quality_guard_warnings(quality_guard_meta)
    diagnostics = CoveragePlanningDiagnostics(
        selected_planner=planner_name,
        scene_type=applicability.scene_type,
        fallback_chain=applicability.fallback_chain,
        reasons=tuple(applicability.reasons) + start_reasons,
        warnings=tuple(applicability.warnings) + start_warnings + guard_warnings,
        metrics=applicability.metrics,
        artifacts_dir=str(getattr(result, "artifacts_dir", "")),
        applied_public_config=planner_config,
        runtime=CoveragePlanningRuntimeDetails(
            coverage_meta={
                "shelf_quality_guard": quality_guard_meta,
            },
        ),
    )
    if not result.success:
        return CoveragePlanningResult(
            status=CoveragePlanningStatus.FAILURE,
            error_message=str(result.error_message),
            diagnostics=diagnostics,
        )

    return CoveragePlanningResult(
        status=CoveragePlanningStatus.SUCCESS,
        path=_convert_path(result.path),
        path_pixels=tuple((float(x), float(y)) for x, y in result.path_pixels),
        diagnostics=diagnostics,
    )
