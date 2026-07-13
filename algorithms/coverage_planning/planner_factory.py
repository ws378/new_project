"""Formal coverage planner factory."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .contracts import (
    apply_planner_mode_defaults,
    coverage_planner_config_diff,
    coverage_planner_mode_default_overrides,
    coverage_planner_profile_metadata,
    CoveragePlannerConfig,
    CoveragePlanningDiagnostics,
    CoveragePlanningRequest,
    CoveragePlanningResult,
    CoveragePlanningRuntimeDetails,
    CoveragePlanningStatus,
    CoveragePose2D,
)
from .modes import (
    BASIC_MODE,
    BASIC_IMPROVED_MODE,
    BOUSTROPHEDON_MODE,
    BCD_BOUSTROPHEDON_MODE,
    CELL_DNN_MODE,
    CONTOUR_DNN_MODE,
    CONTOUR_MATRIX_MODE,
    CSTAR_CIRCLE_MODE,
    CSTAR_RECT_MODE,
    CSTAR_TSP_MODE,
    ECD_DNN_MODE,
    FORMAL_FACTORY_MODES,
    SHELF_AWARE_MODE,
    SPIRAL_MODE,
    STC_MODE,
    WAVEFRONT_MODE,
    formal_selected_planner_name,
    is_formal_factory_mode,
    is_shelf_aware_formal_mode,
)
from .planners.cstar import CStarCircleCoveragePlanner, CStarRectCoveragePlanner, CStarTspCoveragePlanner
from .planners.gbnn import ContourDnnCoveragePlanner, ContourMatrixCoveragePlanner, EcdCoveragePlanner, GbnnCoveragePlanner
from .planners.region_basic import CoveragePlanner
from .planners.region_basic_improved import CoveragePlanner as CoveragePlannerImproved
from .planners.survey import BoustrophedonCoveragePlanner, BcdBoustrophedonCoveragePlanner, SpiralCoveragePlanner, WavefrontCoveragePlanner, SpanningTreeCoveragePlanner
from .planners.shelf_aware_guarded import ShelfAwareCoveragePlanner
from .planners.shelf_aware_guarded.artifacts.schema_registry import (
    ARTIFACT_MANIFEST_RESULT_CONTRACT,
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION,
    FINAL_SEGMENT_PROVENANCE_VERSION,
    TRAVERSAL_MOVE_TRACE_VERSION,
)
from .preprocessing import (
    apply_region_constraint,
    resolve_request_region_mask,
    resolve_request_starting_position,
)
from .quality_guard import build_shelf_quality_guard_meta, shelf_quality_guard_warnings
from .routing.adapters.shelf_aware_ctg_auxiliary import build_shelf_aware_ctg_auxiliary_maps


GEOMETRY_RISK_COUNT_FIELDS = (
    "body_swept_collision_count",
    "body_tight_clearance_count",
    "turn_swept_collision_count",
    "turn_swept_tight_clearance_count",
    "sharp_turn_window_count",
    "continuous_zigzag_count",
    "direction_change_window_count",
)
GEOMETRY_RISK_RATIO_FIELDS = (
    "cleaning_footprint_coverage_ratio",
    "brush_coverage_ratio",
    "squeegee_coverage_ratio",
    "buffer_coverage_ratio",
    "buffer_coverage_vs_cleaning_coverage_delta",
)
GEOMETRY_RISK_REQUIRED_FIELDS = (
    "body_swept_collision_count",
    "turn_swept_collision_count",
    "cleaning_footprint_coverage_ratio",
)


def check_optional_planner_dependencies(planner_mode: str) -> tuple[bool, str | None]:
    """Return whether a planner mode is available in the formal planner domain."""

    if is_formal_factory_mode(planner_mode):
        return True, None
    return False, f"unknown planner mode: {planner_mode}"


def create_coverage_planner(config: CoveragePlannerConfig | None = None):
    """Create a formal coverage planner from `CoveragePlannerConfig.planner_mode`."""

    cfg = apply_planner_mode_defaults(config or CoveragePlannerConfig())
    planner_mode = getattr(cfg, "planner_mode", BASIC_MODE)
    if planner_mode == CONTOUR_DNN_MODE:
        return ContourDnnCoveragePlanner(cfg)
    if planner_mode == CELL_DNN_MODE:
        return GbnnCoveragePlanner(cfg)
    if planner_mode == ECD_DNN_MODE:
        return EcdCoveragePlanner(cfg)
    if planner_mode == CONTOUR_MATRIX_MODE:
        return ContourMatrixCoveragePlanner(cfg)
    if planner_mode == CSTAR_RECT_MODE:
        return CStarRectCoveragePlanner(cfg)
    if planner_mode == CSTAR_CIRCLE_MODE:
        return CStarCircleCoveragePlanner(cfg)
    if planner_mode == CSTAR_TSP_MODE:
        return CStarTspCoveragePlanner(cfg)
    if planner_mode == BOUSTROPHEDON_MODE:
        return BoustrophedonCoveragePlanner(cfg)
    if planner_mode == BCD_BOUSTROPHEDON_MODE:
        return BcdBoustrophedonCoveragePlanner(cfg)
    if planner_mode == SPIRAL_MODE:
        return SpiralCoveragePlanner(cfg)
    if planner_mode == WAVEFRONT_MODE:
        return WavefrontCoveragePlanner(cfg)
    if planner_mode == STC_MODE:
        return SpanningTreeCoveragePlanner(cfg)
    if is_shelf_aware_formal_mode(planner_mode):
        return ShelfAwareCoveragePlanner(cfg)
    if planner_mode == BASIC_IMPROVED_MODE:
        return CoveragePlannerImproved(cfg)
    if planner_mode != BASIC_MODE:
        raise ValueError(
            f"unsupported planner_mode={planner_mode!r}; "
            f"use one of {tuple(sorted(FORMAL_FACTORY_MODES))!r}"
        )
    return CoveragePlanner(cfg)


def _formal_planner_name(planner_mode: str) -> str:
    return formal_selected_planner_name(planner_mode)


def _shelf_quality_guard_meta(
    *,
    planner_mode: str,
    planner_config: CoveragePlannerConfig,
    effective_map,
    path_pixels,
    map_resolution: float,
) -> dict[str, object]:
    if not is_shelf_aware_formal_mode(planner_mode):
        return {"enabled": False}
    return build_shelf_quality_guard_meta(
        enabled=bool(getattr(planner_config, "shelf_quality_guard_enable", True)),
        effective_map=effective_map,
        path_pixels=path_pixels,
        coverage_width_m=float(planner_config.coverage_width_m),
        map_resolution=float(map_resolution),
        min_coverage_ratio=float(planner_config.shelf_quality_guard_min_coverage_ratio),
    )


def _requested_config_from_request(request: CoveragePlanningRequest, planner_mode: str) -> CoveragePlannerConfig:
    assert request.public_config is not None
    return replace(
        request.public_config,
        planner_mode=str(planner_mode),
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


def _config_from_request(request: CoveragePlanningRequest, planner_mode: str) -> CoveragePlannerConfig:
    return apply_planner_mode_defaults(_requested_config_from_request(request, planner_mode))


def _diagnostics_config_kwargs(
    *,
    requested_config: CoveragePlannerConfig,
    applied_config: CoveragePlannerConfig,
) -> dict[str, object]:
    mode_default_overrides = coverage_planner_mode_default_overrides(applied_config.planner_mode)
    return {
        "requested_public_config": requested_config,
        "applied_public_config": applied_config,
        "profile": coverage_planner_profile_metadata(applied_config.planner_mode),
        "mode_default_overrides": mode_default_overrides,
        "override_diff": coverage_planner_config_diff(
            requested_config,
            applied_config,
            keys=frozenset(mode_default_overrides),
        ),
    }


def _runtime_adjustments_meta(request: CoveragePlanningRequest, starting_position, start_snapped: bool) -> dict[str, object]:
    return {
        "start_position": {
            "requested_px": (
                [int(request.starting_position_px[0]), int(request.starting_position_px[1])]
                if request.starting_position_px is not None
                else None
            ),
            "applied_px": [int(starting_position[0]), int(starting_position[1])] if starting_position is not None else None,
            "snapped": bool(start_snapped),
        },
    }


def _postprocess_stage_summary(
    planner_mode: str,
    planner_config: CoveragePlannerConfig,
    ctg_auxiliary_meta: dict[str, object],
    final_path_transform_records: object = (),
) -> dict[str, object]:
    transform_records = [
        dict(record)
        for record in (final_path_transform_records or ())
        if isinstance(record, dict)
    ]
    return {
        "planner_mode": str(planner_mode),
        "shelf_ctg_auxiliary": dict(ctg_auxiliary_meta),
        "isolated_jump_cleanup": {
            "enabled": bool(getattr(planner_config, "isolated_jump_cleanup_enable", False)),
        },
        "final_path_transforms": {
            "records": transform_records,
            "record_count": int(len(transform_records)),
            "changed_transform_count": int(sum(1 for record in transform_records if bool(record.get("changes_path_points", False)))),
            "disallowed_transform_count": int(sum(1 for record in transform_records if not bool(record.get("allowed_in_formal", False)))),
            "total_point_count_delta": int(sum(int(record.get("point_count_delta", 0) or 0) for record in transform_records)),
        },
        "research_postprocess": {
            "enabled": False,
            "reason": "formal_planner_does_not_apply_research_postprocess",
        },
    }


def _path_quality_summary(planner_mode: str, quality_guard_meta: dict[str, object]) -> dict[str, object]:
    if not is_shelf_aware_formal_mode(planner_mode):
        return {"available": False, "reason": "not_shelf_aware_mode"}
    if not bool(quality_guard_meta.get("enabled", False)):
        return {
            "available": False,
            "reason": str(quality_guard_meta.get("reason", "quality_guard_disabled_or_skipped")),
        }
    return {
        "available": True,
        "source": "shelf_quality_guard",
        "status": str(quality_guard_meta.get("status", "")),
        "passed": bool(quality_guard_meta.get("passed", False)),
        "coverage_ratio": float(quality_guard_meta.get("coverage_ratio", 0.0) or 0.0),
        "long_jump_count": int(quality_guard_meta.get("long_jump_count", 0) or 0),
        "infeasible_segment_count": int(quality_guard_meta.get("infeasible_segment_count", 0) or 0),
        "total_turn_angle_deg": float(quality_guard_meta.get("total_turn_angle_deg", 0.0) or 0.0),
        "warnings": [str(item) for item in quality_guard_meta.get("warnings", [])],
    }


def _read_json_mapping(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _path_generation_provenance_summary(artifacts_path: Path | None) -> dict[str, object]:
    path = artifacts_path / "path_generation_provenance.json" if artifacts_path is not None else None
    if path is None or not path.is_file():
        return {
            "available": False,
            "path": "",
            "reason": "path_generation_provenance_sidecar_not_enabled",
        }
    payload = _read_json_mapping(path)
    if payload is None:
        return {
            "available": False,
            "path": str(path),
            "reason": "path_generation_provenance_invalid_json",
        }
    version = str(payload.get("version", "") or "")
    if version != TRAVERSAL_MOVE_TRACE_VERSION:
        return {
            "available": False,
            "path": str(path),
            "reason": "path_generation_provenance_version_mismatch",
            "schema_version": version,
            "expected_schema_version": TRAVERSAL_MOVE_TRACE_VERSION,
        }
    items = payload.get("items", [])
    if not isinstance(items, list):
        items = []
    move_source_counts = Counter(str(item.get("move_source", "unknown")) for item in items if isinstance(item, dict))
    edge_role_counts = Counter(str(item.get("edge_role", "unknown")) for item in items if isinstance(item, dict))
    phase_candidate_counts = [
        int(item["phase_candidate_count"])
        for item in items
        if isinstance(item, dict) and item.get("phase_candidate_count") is not None
    ]
    phase_energy_evaluated_candidate_counts = [
        int(item["phase_energy_evaluated_candidate_count"])
        for item in items
        if isinstance(item, dict) and item.get("phase_energy_evaluated_candidate_count") is not None
    ]
    phase_rejected_before_energy_counts = [
        int(item["phase_rejected_before_energy_count"])
        for item in items
        if isinstance(item, dict) and item.get("phase_rejected_before_energy_count") is not None
    ]
    phase_candidate_ranks = [
        int(item["phase_candidate_rank"])
        for item in items
        if isinstance(item, dict) and item.get("phase_candidate_rank") is not None
    ]
    return {
        "available": True,
        "path": str(path),
        "move_trace_count": int(len(items)),
        "move_source_counts": {key: int(value) for key, value in sorted(move_source_counts.items())},
        "edge_role_counts": {key: int(value) for key, value in sorted(edge_role_counts.items())},
        "global_fallback_count": int(move_source_counts.get("global_fallback", 0)),
        "revisit_bridge_count": int(move_source_counts.get("revisit_bridge", 0)),
        "phase_candidate_summary": {
            "available": bool(phase_candidate_counts),
            "selected_move_count": int(len(phase_candidate_counts)),
            "max_phase_candidate_count": int(max(phase_candidate_counts)) if phase_candidate_counts else 0,
            "max_phase_energy_evaluated_candidate_count": (
                int(max(phase_energy_evaluated_candidate_counts))
                if phase_energy_evaluated_candidate_counts
                else 0
            ),
            "total_phase_rejected_before_energy_count": int(sum(phase_rejected_before_energy_counts)),
            "max_phase_candidate_rank": int(max(phase_candidate_ranks)) if phase_candidate_ranks else 0,
            "phase_candidate_rank_gt1_count": int(sum(1 for value in phase_candidate_ranks if value > 1)),
        },
    }


def _final_segment_provenance_summary(artifacts_path: Path | None) -> dict[str, object]:
    final_segment_path = artifacts_path / "final_segment_provenance.json" if artifacts_path is not None else None
    final_segment_available = bool(final_segment_path is not None and final_segment_path.is_file())
    if not final_segment_available:
        return {
            "available": False,
            "path": "",
            "reason": "final_segment_provenance_sidecar_not_enabled",
        }
    payload = _read_json_mapping(final_segment_path)
    if payload is None:
        return {
            "available": False,
            "path": str(final_segment_path),
            "reason": "final_segment_provenance_invalid_json",
        }
    version = str(payload.get("version", "") or "")
    if version != FINAL_SEGMENT_PROVENANCE_VERSION:
        return {
            "available": False,
            "path": str(final_segment_path),
            "reason": "final_segment_provenance_version_mismatch",
            "schema_version": version,
            "expected_schema_version": FINAL_SEGMENT_PROVENANCE_VERSION,
        }
    source_summary = payload.get("source_summary", {})
    if not isinstance(source_summary, dict):
        source_summary = {}
    return {
        "available": True,
        "path": str(final_segment_path),
        "reason": "",
        "source_summary": dict(source_summary),
    }


def _candidate_decision_debug_summary(artifacts_path: Path | None) -> dict[str, object]:
    decision_debug_path = artifacts_path / "candidate_decision_debug.json" if artifacts_path is not None else None
    if decision_debug_path is None or not decision_debug_path.is_file():
        return {
            "available": False,
            "path": "",
            "reason": "candidate_decision_debug_sidecar_not_enabled",
        }
    payload = _read_json_mapping(decision_debug_path)
    if payload is None:
        return {
            "available": False,
            "path": str(decision_debug_path),
            "reason": "candidate_decision_debug_invalid_json",
        }
    schema_version = str(payload.get("schema_version", "") or "")
    if schema_version != CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION:
        return {
            "available": False,
            "path": str(decision_debug_path),
            "reason": "candidate_decision_debug_schema_mismatch",
            "schema_version": schema_version,
            "expected_schema_version": CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION,
        }
    events = payload.get("events", [])
    if not isinstance(events, list):
        events = []
    selected_phase_counts: Counter[str] = Counter()
    attempted_phase_counts: Counter[str] = Counter()
    terminal_no_selection_event_count = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        selected_phase = event.get("selected_phase")
        selected_phase_key = str(selected_phase) if selected_phase is not None else "none"
        selected_phase_counts[selected_phase_key] += 1
        if selected_phase is None:
            terminal_no_selection_event_count += 1
        phases = event.get("phases", [])
        if not isinstance(phases, list):
            continue
        for phase in phases:
            if isinstance(phase, dict):
                attempted_phase_counts[str(phase.get("phase_name", "unknown"))] += 1
    return {
        "available": True,
        "path": str(decision_debug_path),
        "reason": "",
        "schema_version": schema_version,
        "event_count": int(len(events)),
        "selected_phase_counts": {key: int(value) for key, value in sorted(selected_phase_counts.items())},
        "attempted_phase_counts": {key: int(value) for key, value in sorted(attempted_phase_counts.items())},
        "terminal_no_selection_event_count": int(terminal_no_selection_event_count),
    }


def _artifact_manifest_summary(artifacts_path: Path | None) -> dict[str, object]:
    manifest_path = artifacts_path / "artifact_manifest.json" if artifacts_path is not None else None
    if manifest_path is None or not manifest_path.is_file():
        return {
            "available": False,
            "path": "",
            "reason": "artifact_manifest_not_enabled",
        }
    payload = _read_json_mapping(manifest_path)
    if payload is None:
        return {
            "available": False,
            "path": str(manifest_path),
            "reason": "artifact_manifest_invalid_json",
        }
    schema_version = str(payload.get("schema_version", "") or "")
    result_contract = str(payload.get("result_contract", "") or "")
    if schema_version != ARTIFACT_MANIFEST_SCHEMA_VERSION:
        return {
            "available": False,
            "path": str(manifest_path),
            "reason": "artifact_manifest_schema_mismatch",
            "schema_version": schema_version,
            "expected_schema_version": ARTIFACT_MANIFEST_SCHEMA_VERSION,
        }
    if result_contract != ARTIFACT_MANIFEST_RESULT_CONTRACT:
        return {
            "available": False,
            "path": str(manifest_path),
            "reason": "artifact_manifest_result_contract_mismatch",
            "result_contract": result_contract,
            "expected_result_contract": ARTIFACT_MANIFEST_RESULT_CONTRACT,
        }
    artifacts = payload.get("artifacts", {})
    if not isinstance(artifacts, dict):
        artifacts = {}
    artifact_paths = {}
    for name, info in sorted(artifacts.items()):
        if not isinstance(info, dict):
            continue
        if not bool(info.get("available", True)):
            continue
        path_text = str(info.get("path", "") or "")
        if not path_text:
            continue
        artifact_paths[str(name)] = {
            "path": path_text,
            "role": str(info.get("role", "") or ""),
            "schema_or_format": str(info.get("schema_or_format", "") or ""),
        }
    return {
        "available": True,
        "path": str(manifest_path),
        "reason": "",
        "schema_version": schema_version,
        "result_contract": result_contract,
        "artifact_count": int(len(artifacts)),
        "artifact_paths": artifact_paths,
        "artifact_roles": {
            str(name): str(info.get("role", ""))
            for name, info in sorted(artifacts.items())
            if isinstance(info, dict)
        },
    }


def _provenance_summary(artifacts_dir: str) -> dict[str, object]:
    artifacts_path = Path(artifacts_dir) if str(artifacts_dir or "") else None
    return {
        "available": bool(str(artifacts_dir or "")),
        "artifacts_dir": str(artifacts_dir or ""),
        "artifact_manifest": _artifact_manifest_summary(artifacts_path),
        "path_generation_provenance": _path_generation_provenance_summary(artifacts_path),
        "final_segment_provenance": _final_segment_provenance_summary(artifacts_path),
        "candidate_decision_debug": _candidate_decision_debug_summary(artifacts_path),
    }


def _resolve_geometry_summary_path(path_text: str) -> Path | None:
    if not str(path_text or ""):
        return None
    path = Path(path_text).expanduser()
    if path.is_dir():
        path = path / "summary.json"
    return path


def _geometry_risk_summary(summary_path: str = "") -> dict[str, object]:
    path = _resolve_geometry_summary_path(summary_path)
    if path is None:
        return {
            "available": False,
            "status": "not_run",
            "reason": "readonly_geometry_diagnostic_not_run_in_formal_planner",
        }
    if not path.is_file():
        return {
            "available": False,
            "status": "summary_missing",
            "reason": "geometry_risk_summary_path_not_found",
            "summary_path": str(path),
        }
    payload = _read_json_mapping(path)
    if payload is None:
        return {
            "available": False,
            "status": "invalid_summary",
            "reason": "geometry_risk_summary_invalid_json",
            "summary_path": str(path),
        }
    missing_fields = [field for field in GEOMETRY_RISK_REQUIRED_FIELDS if field not in payload]
    if missing_fields:
        return {
            "available": False,
            "status": "invalid_summary",
            "reason": "geometry_risk_summary_missing_required_fields",
            "summary_path": str(path),
            "missing_fields": missing_fields,
        }
    invalid_fields: list[str] = []
    count_metrics: dict[str, int] = {}
    ratio_metrics: dict[str, float] = {}
    for field in GEOMETRY_RISK_COUNT_FIELDS:
        if field not in payload:
            continue
        try:
            count_metrics[field] = int(payload.get(field, 0) or 0)
        except (TypeError, ValueError):
            invalid_fields.append(field)
    for field in GEOMETRY_RISK_RATIO_FIELDS:
        if field not in payload:
            continue
        try:
            ratio_metrics[field] = float(payload.get(field, 0.0) or 0.0)
        except (TypeError, ValueError):
            invalid_fields.append(field)
    try:
        cleaning_gap_area_m2 = float(payload.get("cleaning_footprint_gap_area_m2", 0.0) or 0.0)
    except (TypeError, ValueError):
        cleaning_gap_area_m2 = 0.0
        invalid_fields.append("cleaning_footprint_gap_area_m2")
    if invalid_fields:
        return {
            "available": False,
            "status": "invalid_summary",
            "reason": "geometry_risk_summary_invalid_metric_value",
            "summary_path": str(path),
            "invalid_fields": sorted(set(invalid_fields)),
        }
    return {
        "available": True,
        "status": "read_only_diagnostic_available",
        "reason": "",
        "summary_path": str(path),
        "diagnostic_scope": str(payload.get("diagnostic_scope", "")),
        "geometry_source": str(payload.get("geometry_source", "")),
        "target_definition": str(payload.get("target_definition", "")),
        "count_metrics": count_metrics,
        "ratio_metrics": ratio_metrics,
        "cleaning_footprint_gap_area_m2": cleaning_gap_area_m2,
    }


def run_formal_planner_request(request: CoveragePlanningRequest, planner_mode: str) -> CoveragePlanningResult:
    """Run basic or shelf-aware planners through the stage2 request contract."""

    if not is_formal_factory_mode(planner_mode):
        raise ValueError(f"unsupported formal planner mode: {planner_mode}")
    requested_config = _requested_config_from_request(request, planner_mode)
    planner_config = apply_planner_mode_defaults(requested_config)
    diagnostics_config_kwargs = _diagnostics_config_kwargs(
        requested_config=requested_config,
        applied_config=planner_config,
    )
    planner = create_coverage_planner(planner_config)
    effective_map = apply_region_constraint(
        request.prepared_map,
        resolve_request_region_mask(request),
    )
    starting_position, start_snapped = resolve_request_starting_position(request, effective_map)
    runtime_adjustments = _runtime_adjustments_meta(request, starting_position, start_snapped)
    if starting_position is None:
        diagnostics = CoveragePlanningDiagnostics(
            selected_planner=_formal_planner_name(planner_mode),
            scene_type="explicit",
            fallback_chain=(),
            reasons=("explicit_planner_mode", "no_free_start_pixel"),
            warnings=("区域内没有可通行空间，无法生成覆盖路径。",),
            **diagnostics_config_kwargs,
            runtime=CoveragePlanningRuntimeDetails(
                runtime_adjustments=runtime_adjustments,
                provenance_summary=_provenance_summary(""),
                geometry_risk_summary=_geometry_risk_summary(planner_config.geometry_risk_summary_path),
            ),
        )
        return CoveragePlanningResult(
            status=CoveragePlanningStatus.FAILURE,
            error_message="区域内没有可通行空间，无法生成覆盖路径。",
            diagnostics=diagnostics,
        )
    ctg_auxiliary = None
    reasons = ["explicit_planner_mode"]
    warnings: list[str] = []
    if start_snapped:
        reasons.append("start_snapped_to_nearest_free_pixel")
        warnings.append(
            f"起点已从 {tuple(request.starting_position_px)} 吸附到最近可通行像素 {tuple(starting_position)}"
        )
    ctg_auxiliary_meta: dict[str, object] = {"enabled": False}
    if is_shelf_aware_formal_mode(planner_mode) and bool(getattr(planner_config, "shelf_ctg_auxiliary_enable", False)):
        try:
            ctg_auxiliary = build_shelf_aware_ctg_auxiliary_maps(request)
            reasons.append("shelf_ctg_auxiliary_enabled")
        except Exception as exc:
            reasons.append("shelf_ctg_auxiliary_disabled_after_failure")
            warnings.append(f"shelf_ctg_auxiliary_unavailable:{exc}")
            ctg_auxiliary_meta = {
                "enabled": False,
                "reason": "auxiliary_failed_continued_without_ctg",
                "error_message": str(exc),
            }
        else:
            ctg_auxiliary_meta = dict(ctg_auxiliary.debug_info)

    if is_shelf_aware_formal_mode(planner_mode):
        planner_result = planner.plan(
            effective_map,
            map_resolution=float(request.map_resolution),
            starting_position=starting_position,
            map_origin=request.map_origin_xy,
            local_edge_label_map=ctg_auxiliary.edge_label_map if ctg_auxiliary is not None else None,
            local_junction_label_map=ctg_auxiliary.junction_label_map if ctg_auxiliary is not None else None,
            region_mask=resolve_request_region_mask(request),
        )
    else:
        planner_result = planner.plan(
            effective_map,
            map_resolution=float(request.map_resolution),
            starting_position=starting_position,
            map_origin=request.map_origin_xy,
        )
    quality_guard_meta = (
        _shelf_quality_guard_meta(
            planner_mode=planner_mode,
            planner_config=planner_config,
            effective_map=effective_map,
            path_pixels=planner_result.path_pixels,
            map_resolution=float(request.map_resolution),
        )
        if planner_result.success
        else {"enabled": planner_mode == SHELF_AWARE_MODE, "status": "skipped_planner_failed"}
    )
    guard_warnings = shelf_quality_guard_warnings(quality_guard_meta)
    diagnostics = CoveragePlanningDiagnostics(
        selected_planner=_formal_planner_name(planner_mode),
        scene_type="explicit",
        fallback_chain=(),
        reasons=tuple(reasons),
        warnings=tuple(warnings) + guard_warnings,
        **diagnostics_config_kwargs,
        artifacts_dir=str(getattr(planner_result, "artifacts_dir", "")),
        runtime=CoveragePlanningRuntimeDetails(
            runtime_adjustments=runtime_adjustments,
            coverage_meta={
                "shelf_ctg_auxiliary": ctg_auxiliary_meta,
                "shelf_quality_guard": quality_guard_meta,
            },
            postprocess_stage_summary=_postprocess_stage_summary(
                planner_mode,
                planner_config,
                ctg_auxiliary_meta,
                getattr(planner_result, "runtime_metadata", {}).get("final_path_transform_records", ()),
            ),
            path_quality_summary=_path_quality_summary(planner_mode, quality_guard_meta),
            provenance_summary=_provenance_summary(str(getattr(planner_result, "artifacts_dir", ""))),
            geometry_risk_summary=_geometry_risk_summary(planner_config.geometry_risk_summary_path),
        ),
    )
    if not planner_result.success:
        return CoveragePlanningResult(
            status=CoveragePlanningStatus.FAILURE,
            error_message=str(planner_result.error_message),
            diagnostics=diagnostics,
        )
    return CoveragePlanningResult(
        status=CoveragePlanningStatus.SUCCESS,
        path=tuple(
            CoveragePose2D(float(p.x), float(p.y), float(p.theta))
            for p in planner_result.path
        ),
        path_pixels=tuple((float(x), float(y)) for x, y in planner_result.path_pixels),
        diagnostics=diagnostics,
    )
