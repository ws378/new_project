import json
from dataclasses import replace

import cv2
import numpy as np
import pytest

from algorithms.coverage_planning.contracts import (
    coverage_planner_config_diff,
    coverage_planner_mode_default_overrides,
    coverage_planner_profile_metadata,
    CoveragePlannerConfig,
    CoveragePlanningRequest,
    CoveragePlanningStatus,
    SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR,
    SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE,
)
from algorithms.coverage_planning.planners.region_basic import CoveragePlanner
from algorithms.coverage_planning.planner_factory import (
    _artifact_manifest_summary,
    _candidate_decision_debug_summary,
    _final_segment_provenance_summary,
    _path_generation_provenance_summary,
    check_optional_planner_dependencies,
    create_coverage_planner,
    run_formal_planner_request,
    _shelf_quality_guard_meta,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded import (
    ShelfAwareCoveragePlanner,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded import (
    PlannerConfig,
    plan_coverage_path,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.decision_debug_payloads import (
    CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.schema_registry import (
    ARTIFACT_MANIFEST_RESULT_CONTRACT,
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    FINAL_SEGMENT_PROVENANCE_VERSION,
    TRAVERSAL_MOVE_TRACE_VERSION,
)


def test_create_coverage_planner_returns_basic_planner():
    planner = create_coverage_planner(CoveragePlannerConfig(planner_mode="basic"))

    assert isinstance(planner, CoveragePlanner)


def test_create_coverage_planner_returns_shelf_aware_planner():
    planner = create_coverage_planner(CoveragePlannerConfig(planner_mode="shelf_aware"))

    assert isinstance(planner, ShelfAwareCoveragePlanner)
    assert planner.cfg.shelf_node_generation_mode == "shelf_cell_adjusted"
    assert planner.cfg.shelf_ctg_auxiliary_enable is False
    assert planner.cfg.isolated_jump_cleanup_enable is True


def test_create_coverage_planner_returns_turn_cost_shelf_aware_planner_with_mode_defaults():
    planner = create_coverage_planner(
        CoveragePlannerConfig(
            planner_mode="shelf_aware_turn_cost",
            shelf_ctg_auxiliary_enable=False,
            shelf_node_generation_mode="shelf_cell_adjusted",
            shelf_repaired_grid_max_offset_factor=0.35,
            isolated_jump_cleanup_enable=True,
        )
    )

    assert isinstance(planner, ShelfAwareCoveragePlanner)
    assert planner.cfg.planner_mode == "shelf_aware_turn_cost"
    assert planner.cfg.shelf_ctg_auxiliary_enable is False
    assert planner.cfg.shelf_node_generation_mode == SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE
    assert (
        planner.cfg.shelf_repaired_grid_max_offset_factor
        == SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR
    )
    assert planner.cfg.isolated_jump_cleanup_enable is False


def test_shelf_aware_modes_build_internal_config_without_semantic_public_fields():
    assert not hasattr(CoveragePlannerConfig(), "semantic_path_enable")
    assert not hasattr(CoveragePlannerConfig(), "semantic_actual_clean_width_m")

    shelf_planner = create_coverage_planner(CoveragePlannerConfig(planner_mode="shelf_aware"))
    assert isinstance(shelf_planner, ShelfAwareCoveragePlanner)
    shelf_internal = shelf_planner._build_planner_config(
        room_map=np.ones((8, 8), dtype=np.uint8) * 255,
        starting_position=(1, 1),
    )

    assert shelf_internal.semantic_path_enable is True
    assert shelf_internal.semantic_actual_clean_width_m == 0.70
    assert shelf_internal.strategy.name == "shelf_aware"
    assert shelf_internal.node_generation_mode == "shelf_cell_adjusted"
    assert shelf_internal.repaired_grid_max_offset_factor == 0.35
    assert shelf_internal.isolated_jump_cleanup.enable is True

    turn_cost_planner = create_coverage_planner(
        CoveragePlannerConfig(
            planner_mode="shelf_aware_turn_cost",
            shelf_ctg_auxiliary_enable=False,
            shelf_node_generation_mode="shelf_cell_adjusted",
            shelf_repaired_grid_max_offset_factor=0.35,
            isolated_jump_cleanup_enable=True,
        )
    )
    assert isinstance(turn_cost_planner, ShelfAwareCoveragePlanner)
    turn_cost_internal = turn_cost_planner._build_planner_config(
        room_map=np.ones((8, 8), dtype=np.uint8) * 255,
        starting_position=(1, 1),
    )

    assert turn_cost_internal.semantic_path_enable is True
    assert turn_cost_internal.semantic_actual_clean_width_m == 0.70
    assert turn_cost_internal.strategy.name == "shelf_aware"
    assert turn_cost_internal.node_generation_mode == SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE
    assert (
        turn_cost_internal.repaired_grid_max_offset_factor
        == SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR
    )
    assert turn_cost_internal.isolated_jump_cleanup.enable is False


def test_turn_cost_shelf_aware_profile_metadata_and_override_diff():
    requested = CoveragePlannerConfig(
        planner_mode="shelf_aware_turn_cost",
        shelf_ctg_auxiliary_enable=False,
        shelf_node_generation_mode="shelf_cell_adjusted",
        shelf_repaired_grid_max_offset_factor=0.35,
        isolated_jump_cleanup_enable=True,
    )
    applied = create_coverage_planner(requested).cfg

    assert coverage_planner_profile_metadata(applied.planner_mode) == {
        "planner_mode": "shelf_aware_turn_cost",
        "profile_id": "shelf_aware_turn_cost_repaired_grid_0_28",
        "profile_version": 2,
        "profile_status": "candidate_enhancement",
        "profile_version_policy": "increment_on_default_overrides_or_formal_behavior_contract_change",
    }
    assert coverage_planner_mode_default_overrides(applied.planner_mode) == {
        "shelf_node_generation_mode": SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE,
        "shelf_repaired_grid_max_offset_factor": SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR,
        "isolated_jump_cleanup_enable": False,
    }
    assert coverage_planner_config_diff(requested, applied) == {
        "isolated_jump_cleanup_enable": {"requested": True, "applied": False},
        "shelf_node_generation_mode": {
            "requested": "shelf_cell_adjusted",
            "applied": SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE,
        },
        "shelf_repaired_grid_max_offset_factor": {
            "requested": 0.35,
            "applied": SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR,
        },
    }
    applied_with_artifact_change = replace(applied, artifacts_output_root="/tmp/generated")
    assert coverage_planner_config_diff(
        requested,
        applied_with_artifact_change,
        keys=frozenset(coverage_planner_mode_default_overrides(applied.planner_mode)),
    ) == {
        "isolated_jump_cleanup_enable": {"requested": True, "applied": False},
        "shelf_node_generation_mode": {
            "requested": "shelf_cell_adjusted",
            "applied": SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE,
        },
        "shelf_repaired_grid_max_offset_factor": {
            "requested": 0.35,
            "applied": SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR,
        },
    }


def test_unknown_planner_profile_does_not_look_valid():
    assert coverage_planner_profile_metadata("typo_mode") == {
        "planner_mode": "typo_mode",
        "profile_id": "",
        "profile_version": 0,
        "profile_status": "unknown_planner_mode",
        "profile_version_policy": "increment_on_default_overrides_or_formal_behavior_contract_change",
    }


def test_check_optional_planner_dependencies_accepts_shelf_aware():
    ok, reason = check_optional_planner_dependencies("shelf_aware")

    assert ok
    assert reason is None


def test_check_optional_planner_dependencies_accepts_turn_cost_shelf_aware():
    ok, reason = check_optional_planner_dependencies("shelf_aware_turn_cost")

    assert ok
    assert reason is None


def test_shelf_quality_guard_meta_reports_without_modifying_path():
    room_map = np.zeros((30, 30), dtype=np.uint8)
    room_map[5:25, 5:25] = 255
    path_pixels = ((5.0, 15.0), (24.0, 15.0), (24.0, 24.0))

    meta = _shelf_quality_guard_meta(
        planner_mode="shelf_aware",
        planner_config=CoveragePlannerConfig(
            planner_mode="shelf_aware",
            coverage_width_m=0.5,
            shelf_quality_guard_enable=True,
            shelf_quality_guard_min_coverage_ratio=0.1,
        ),
        effective_map=room_map,
        path_pixels=path_pixels,
        map_resolution=0.05,
    )

    assert meta["enabled"] is True
    assert "formal_planner_migration" in meta
    assert meta["point_count"] == len(path_pixels)


def test_shelf_quality_guard_meta_can_be_disabled():
    meta = _shelf_quality_guard_meta(
        planner_mode="shelf_aware",
        planner_config=CoveragePlannerConfig(
            planner_mode="shelf_aware",
            shelf_quality_guard_enable=False,
        ),
        effective_map=np.ones((10, 10), dtype=np.uint8) * 255,
        path_pixels=((1.0, 1.0), (8.0, 8.0)),
        map_resolution=0.05,
    )

    assert meta == {"enabled": False, "reason": "disabled_by_config"}


def test_run_formal_planner_request_supports_shelf_aware(tmp_path):
    room_map = np.zeros((80, 120), dtype=np.uint8)
    room_map[10:70, 10:110] = 255
    request = CoveragePlanningRequest(
        prepared_map=room_map,
        map_resolution=0.05,
        starting_position_px=(20, 20),
            public_config=CoveragePlannerConfig(
                planner_mode="shelf_aware",
                coverage_width_m=0.5,
                shelf_quality_guard_enable=True,
                robot_width_m=0.2,
            open_kernel_m=0.1,
            obstacle_expand_m=0.1,
            auto_rotate=False,
            write_artifacts=False,
            artifacts_output_root=str(tmp_path),
        ),
        artifacts_output_root=tmp_path,
    )

    result = run_formal_planner_request(request, "shelf_aware")

    assert result.status == CoveragePlanningStatus.SUCCESS
    assert result.path_pixels
    assert result.diagnostics.selected_planner == "shelf_aware"
    assert result.diagnostics.runtime is not None
    guard_meta = result.diagnostics.runtime.coverage_meta["shelf_quality_guard"]
    assert guard_meta["enabled"] is True
    assert "formal_planner_migration" in guard_meta
    summary = result.diagnostics.to_summary_dict()
    assert summary["runtime"]["path_quality_summary"]["available"] is True
    assert summary["runtime"]["path_quality_summary"]["source"] == "shelf_quality_guard"


def test_shelf_aware_continues_when_ctg_auxiliary_fails(monkeypatch, tmp_path):
    def fail_ctg_auxiliary(_request):
        raise ValueError("edge 6 path too short")

    monkeypatch.setattr(
        "algorithms.coverage_planning.planner_factory.build_shelf_aware_ctg_auxiliary_maps",
        fail_ctg_auxiliary,
    )
    room_map = np.zeros((80, 120), dtype=np.uint8)
    room_map[10:70, 10:110] = 255
    request = CoveragePlanningRequest(
        prepared_map=room_map,
        map_resolution=0.05,
        starting_position_px=(20, 20),
        public_config=CoveragePlannerConfig(
            planner_mode="shelf_aware",
            coverage_width_m=0.5,
            robot_width_m=0.2,
            open_kernel_m=0.1,
            obstacle_expand_m=0.1,
            shelf_ctg_auxiliary_enable=True,
            auto_rotate=False,
            write_artifacts=False,
            artifacts_output_root=str(tmp_path),
        ),
        artifacts_output_root=tmp_path,
    )

    result = run_formal_planner_request(request, "shelf_aware")

    assert result.status == CoveragePlanningStatus.SUCCESS
    assert "shelf_ctg_auxiliary_disabled_after_failure" in result.diagnostics.reasons
    assert any("shelf_ctg_auxiliary_unavailable" in item for item in result.diagnostics.warnings)
    assert result.diagnostics.runtime is not None
    ctg_meta = result.diagnostics.runtime.coverage_meta["shelf_ctg_auxiliary"]
    assert ctg_meta["enabled"] is False
    assert ctg_meta["reason"] == "auxiliary_failed_continued_without_ctg"


def test_turn_cost_shelf_aware_continues_when_ctg_auxiliary_fails(monkeypatch, tmp_path):
    def fail_ctg_auxiliary(_request):
        raise ValueError("edge 6 path too short")

    monkeypatch.setattr(
        "algorithms.coverage_planning.planner_factory.build_shelf_aware_ctg_auxiliary_maps",
        fail_ctg_auxiliary,
    )
    room_map = np.zeros((80, 120), dtype=np.uint8)
    room_map[10:70, 10:110] = 255
    request = CoveragePlanningRequest(
        prepared_map=room_map,
        map_resolution=0.05,
        starting_position_px=(20, 20),
            public_config=CoveragePlannerConfig(
                planner_mode="shelf_aware_turn_cost",
                coverage_width_m=0.5,
                shelf_quality_guard_enable=True,
                robot_width_m=0.2,
                open_kernel_m=0.1,
                obstacle_expand_m=0.1,
                shelf_ctg_auxiliary_enable=True,
            auto_rotate=False,
            write_artifacts=False,
            artifacts_output_root=str(tmp_path),
        ),
        artifacts_output_root=tmp_path,
    )

    result = run_formal_planner_request(request, "shelf_aware_turn_cost")

    assert result.status == CoveragePlanningStatus.SUCCESS
    assert "shelf_ctg_auxiliary_disabled_after_failure" in result.diagnostics.reasons
    assert result.diagnostics.runtime is not None
    assert result.diagnostics.runtime.coverage_meta["shelf_ctg_auxiliary"] == {
        "enabled": False,
        "reason": "auxiliary_failed_continued_without_ctg",
        "error_message": "edge 6 path too short",
    }
    assert result.diagnostics.applied_public_config is not None
    assert result.diagnostics.requested_public_config is not None
    assert result.diagnostics.applied_public_config.shelf_ctg_auxiliary_enable is True
    assert result.diagnostics.requested_public_config.shelf_ctg_auxiliary_enable is True
    assert (
        result.diagnostics.applied_public_config.shelf_node_generation_mode
        == SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE
    )
    assert (
        result.diagnostics.applied_public_config.shelf_repaired_grid_max_offset_factor
        == SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR
    )
    summary = result.diagnostics.to_summary_dict()
    assert summary["profile"] == {
        "planner_mode": "shelf_aware_turn_cost",
        "profile_id": "shelf_aware_turn_cost_repaired_grid_0_28",
        "profile_version": 2,
        "profile_status": "candidate_enhancement",
        "profile_version_policy": "increment_on_default_overrides_or_formal_behavior_contract_change",
    }
    assert summary["mode_default_overrides"]["shelf_node_generation_mode"] == SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE
    compact = summary["compact_summary"]
    assert compact["profile_id"] == "shelf_aware_turn_cost_repaired_grid_0_28"
    assert compact["profile_status"] == "candidate_enhancement"
    assert compact["profile_version_policy"] == "increment_on_default_overrides_or_formal_behavior_contract_change"
    assert compact["mode_default_override_count"] == 3
    assert "shelf_node_generation_mode" in compact["mode_default_override_fields"]
    assert compact["override_diff_count"] == 3
    assert "shelf_ctg_auxiliary_enable" not in compact["override_diff_fields"]
    runtime_summary = summary["runtime"]
    assert runtime_summary["runtime_adjustments"]["start_position"] == {
        "requested_px": [20, 20],
        "applied_px": [20, 20],
        "snapped": False,
    }
    assert runtime_summary["postprocess_stage_summary"]["research_postprocess"] == {
        "enabled": False,
        "reason": "formal_planner_does_not_apply_research_postprocess",
    }
    transform_summary = runtime_summary["postprocess_stage_summary"]["final_path_transforms"]
    assert transform_summary["record_count"] == 4
    assert transform_summary["disallowed_transform_count"] == 0
    assert [record["name"] for record in transform_summary["records"]] == [
        "simplify_rotated_path",
        "semantic_global_path",
        "isolated_jump_cleanup",
        "final_path_geometry",
    ]
    assert runtime_summary["path_quality_summary"]["available"] is True
    assert runtime_summary["path_quality_summary"]["source"] == "shelf_quality_guard"
    assert runtime_summary["provenance_summary"]["final_segment_provenance"] == {
        "available": False,
        "path": "",
        "reason": "final_segment_provenance_sidecar_not_enabled",
    }
    assert runtime_summary["provenance_summary"]["candidate_decision_debug"] == {
        "available": False,
        "path": "",
        "reason": "candidate_decision_debug_sidecar_not_enabled",
    }
    assert runtime_summary["geometry_risk_summary"] == {
        "available": False,
        "status": "not_run",
        "reason": "readonly_geometry_diagnostic_not_run_in_formal_planner",
    }
    assert compact["geometry_risk"]["available"] is False
    assert compact["geometry_risk"]["status"] == "not_run"
    assert compact["geometry_risk"]["reason"] == "readonly_geometry_diagnostic_not_run_in_formal_planner"


def test_shelf_aware_turn_cost_runtime_provenance_summary_reads_sidecars(tmp_path):
    room_map = np.zeros((80, 120), dtype=np.uint8)
    room_map[10:70, 10:110] = 255
    request = CoveragePlanningRequest(
        prepared_map=room_map,
        map_resolution=0.05,
        starting_position_px=(20, 20),
        public_config=CoveragePlannerConfig(
            planner_mode="shelf_aware_turn_cost",
            coverage_width_m=0.5,
            robot_width_m=0.2,
            open_kernel_m=0.1,
            obstacle_expand_m=0.1,
            auto_rotate=False,
            write_artifacts=True,
            artifacts_output_root=str(tmp_path),
        ),
        artifacts_output_root=tmp_path,
    )

    result = run_formal_planner_request(request, "shelf_aware_turn_cost")

    assert result.status == CoveragePlanningStatus.SUCCESS
    summary = result.diagnostics.to_summary_dict()
    provenance = summary["runtime"]["provenance_summary"]
    assert provenance["available"] is True
    manifest_summary = provenance["artifact_manifest"]
    assert manifest_summary["available"] is True
    assert manifest_summary["schema_version"] == "shelf_aware_guarded_artifact_manifest.v1"
    assert manifest_summary["result_contract"] == "CoveragePlanningResult"
    assert manifest_summary["artifact_count"] >= 20
    assert manifest_summary["artifact_roles"]["candidate_decision_debug"] == (
        "artifact_only_candidate_decision_evidence"
    )
    assert manifest_summary["artifact_paths"]["path_overlay"]["path"].endswith("/path_overlay.png")
    assert manifest_summary["artifact_paths"]["path_pixels"]["role"] == "final_path_pixels_evidence"
    assert manifest_summary["artifact_paths"]["candidate_decision_debug"]["schema_or_format"] == (
        CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION
    )
    move_trace_summary = provenance["path_generation_provenance"]
    assert move_trace_summary["available"] is True
    assert move_trace_summary["move_trace_count"] >= len(result.path_pixels)
    assert move_trace_summary["move_source_counts"]["start"] == 1
    assert "normal_neighbor" in move_trace_summary["move_source_counts"]
    assert move_trace_summary["phase_candidate_summary"]["available"] is True
    assert move_trace_summary["phase_candidate_summary"]["max_phase_candidate_count"] >= 1
    assert move_trace_summary["phase_candidate_summary"]["max_phase_energy_evaluated_candidate_count"] >= 1
    assert move_trace_summary["phase_candidate_summary"]["total_phase_rejected_before_energy_count"] >= 0
    final_segment_summary = provenance["final_segment_provenance"]
    assert final_segment_summary["available"] is True
    assert final_segment_summary["source_summary"]["matched_traversal_segment_count"] >= 1
    assert (
        final_segment_summary["source_summary"]["matched_traversal_segment_count"]
        + final_segment_summary["source_summary"]["derived_final_geometry_segment_count"]
        == len(result.path_pixels) - 1
    )
    decision_debug_summary = provenance["candidate_decision_debug"]
    assert decision_debug_summary["available"] is True
    assert decision_debug_summary["schema_version"] == CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION
    assert decision_debug_summary["event_count"] >= len(result.path_pixels) - 2
    assert decision_debug_summary["attempted_phase_counts"]["normal_neighbor"] >= 1
    assert sum(decision_debug_summary["selected_phase_counts"].values()) == decision_debug_summary["event_count"]
    compact = summary["compact_summary"]
    assert compact["provenance"]["artifact_manifest_available"] is True
    assert compact["provenance"]["artifact_manifest_path"].endswith("/artifact_manifest.json")
    assert compact["provenance"]["artifact_paths"]["path_pixels"]["path"].endswith("/path_pixels.json")
    assert compact["provenance"]["path_generation_available"] is True
    assert compact["provenance"]["final_segment_available"] is True
    assert compact["provenance"]["candidate_decision_available"] is True


def test_artifact_manifest_summary_rejects_schema_mismatch(tmp_path):
    (tmp_path / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "wrong_manifest_schema",
                "result_contract": ARTIFACT_MANIFEST_RESULT_CONTRACT,
                "artifacts": {},
            }
        ),
        encoding="utf-8",
    )

    summary = _artifact_manifest_summary(tmp_path)

    assert summary["available"] is False
    assert summary["reason"] == "artifact_manifest_schema_mismatch"
    assert summary["schema_version"] == "wrong_manifest_schema"
    assert summary["expected_schema_version"] == ARTIFACT_MANIFEST_SCHEMA_VERSION


def test_artifact_manifest_summary_rejects_result_contract_mismatch(tmp_path):
    (tmp_path / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": ARTIFACT_MANIFEST_SCHEMA_VERSION,
                "result_contract": "LegacyCoverageResult",
                "artifacts": {},
            }
        ),
        encoding="utf-8",
    )

    summary = _artifact_manifest_summary(tmp_path)

    assert summary["available"] is False
    assert summary["reason"] == "artifact_manifest_result_contract_mismatch"
    assert summary["result_contract"] == "LegacyCoverageResult"
    assert summary["expected_result_contract"] == ARTIFACT_MANIFEST_RESULT_CONTRACT


def test_provenance_sidecar_summaries_reject_schema_mismatch(tmp_path):
    (tmp_path / "path_generation_provenance.json").write_text(
        json.dumps({"version": "wrong_move_trace", "items": []}),
        encoding="utf-8",
    )
    (tmp_path / "final_segment_provenance.json").write_text(
        json.dumps({"version": "wrong_final_segment", "source_summary": {}}),
        encoding="utf-8",
    )

    move_trace_summary = _path_generation_provenance_summary(tmp_path)
    final_segment_summary = _final_segment_provenance_summary(tmp_path)

    assert move_trace_summary["available"] is False
    assert move_trace_summary["reason"] == "path_generation_provenance_version_mismatch"
    assert move_trace_summary["expected_schema_version"] == TRAVERSAL_MOVE_TRACE_VERSION
    assert final_segment_summary["available"] is False
    assert final_segment_summary["reason"] == "final_segment_provenance_version_mismatch"
    assert final_segment_summary["expected_schema_version"] == FINAL_SEGMENT_PROVENANCE_VERSION


def test_candidate_decision_debug_summary_rejects_schema_mismatch(tmp_path):
    (tmp_path / "candidate_decision_debug.json").write_text(
        json.dumps({"schema_version": "wrong_candidate_debug", "events": []}),
        encoding="utf-8",
    )

    summary = _candidate_decision_debug_summary(tmp_path)

    assert summary["available"] is False
    assert summary["reason"] == "candidate_decision_debug_schema_mismatch"
    assert summary["schema_version"] == "wrong_candidate_debug"
    assert summary["expected_schema_version"] == CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION


def test_shelf_aware_turn_cost_reads_geometry_risk_summary_sidecar(tmp_path):
    geometry_summary = tmp_path / "geometry_summary.json"
    geometry_summary.write_text(
        json.dumps(
            {
                "version": "geometry_coverage_readonly_diagnostic.v1",
                "diagnostic_scope": "read_only_no_path_modification",
                "geometry_source": "sample_geometry_until_robot_calibration_is_confirmed",
                "target_definition": "region_mask AND prepared_map",
                "body_swept_collision_count": 2,
                "body_tight_clearance_count": 3,
                "turn_swept_collision_count": 4,
                "turn_swept_tight_clearance_count": 5,
                "sharp_turn_window_count": 6,
                "continuous_zigzag_count": 7,
                "direction_change_window_count": 8,
                "cleaning_footprint_coverage_ratio": 0.987,
                "brush_coverage_ratio": 0.876,
                "squeegee_coverage_ratio": 0.965,
                "buffer_coverage_ratio": 0.990,
                "buffer_coverage_vs_cleaning_coverage_delta": 0.003,
                "cleaning_footprint_gap_area_m2": 0.42,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    room_map = np.zeros((80, 120), dtype=np.uint8)
    room_map[10:70, 10:110] = 255
    request = CoveragePlanningRequest(
        prepared_map=room_map,
        map_resolution=0.05,
        starting_position_px=(20, 20),
        public_config=CoveragePlannerConfig(
            planner_mode="shelf_aware_turn_cost",
            coverage_width_m=0.5,
            robot_width_m=0.2,
            open_kernel_m=0.1,
            obstacle_expand_m=0.1,
            auto_rotate=False,
            write_artifacts=False,
            geometry_risk_summary_path=str(geometry_summary),
        ),
    )

    result = run_formal_planner_request(request, "shelf_aware_turn_cost")

    assert result.status == CoveragePlanningStatus.SUCCESS
    assert result.path_pixels
    summary = result.diagnostics.to_summary_dict()
    geometry = summary["runtime"]["geometry_risk_summary"]
    assert geometry["available"] is True
    assert geometry["status"] == "read_only_diagnostic_available"
    assert geometry["summary_path"] == str(geometry_summary)
    assert geometry["count_metrics"]["body_swept_collision_count"] == 2
    assert geometry["count_metrics"]["turn_swept_collision_count"] == 4
    assert geometry["ratio_metrics"]["cleaning_footprint_coverage_ratio"] == 0.987
    compact_geometry = summary["compact_summary"]["geometry_risk"]
    assert compact_geometry["available"] is True
    assert compact_geometry["body_swept_collision_count"] == 2
    assert compact_geometry["turn_swept_collision_count"] == 4
    assert compact_geometry["cleaning_footprint_coverage_ratio"] == 0.987


def test_shelf_aware_turn_cost_marks_invalid_geometry_risk_sidecar_unavailable(tmp_path):
    geometry_summary = tmp_path / "summary.json"
    geometry_summary.write_text("{bad json", encoding="utf-8")
    room_map = np.zeros((80, 120), dtype=np.uint8)
    room_map[10:70, 10:110] = 255
    request = CoveragePlanningRequest(
        prepared_map=room_map,
        map_resolution=0.05,
        starting_position_px=(20, 20),
        public_config=CoveragePlannerConfig(
            planner_mode="shelf_aware_turn_cost",
            coverage_width_m=0.5,
            robot_width_m=0.2,
            open_kernel_m=0.1,
            obstacle_expand_m=0.1,
            auto_rotate=False,
            write_artifacts=False,
            geometry_risk_summary_path=str(geometry_summary),
        ),
    )

    result = run_formal_planner_request(request, "shelf_aware_turn_cost")

    assert result.status == CoveragePlanningStatus.SUCCESS
    geometry = result.diagnostics.to_summary_dict()["runtime"]["geometry_risk_summary"]
    assert geometry["available"] is False
    assert geometry["status"] == "invalid_summary"
    assert geometry["reason"] == "geometry_risk_summary_invalid_json"


def test_shelf_aware_turn_cost_marks_missing_geometry_risk_sidecar_unavailable(tmp_path):
    missing_summary = tmp_path / "missing_summary.json"
    room_map = np.zeros((80, 120), dtype=np.uint8)
    room_map[10:70, 10:110] = 255
    request = CoveragePlanningRequest(
        prepared_map=room_map,
        map_resolution=0.05,
        starting_position_px=(20, 20),
        public_config=CoveragePlannerConfig(
            planner_mode="shelf_aware_turn_cost",
            coverage_width_m=0.5,
            robot_width_m=0.2,
            open_kernel_m=0.1,
            obstacle_expand_m=0.1,
            auto_rotate=False,
            write_artifacts=False,
            geometry_risk_summary_path=str(missing_summary),
        ),
    )

    result = run_formal_planner_request(request, "shelf_aware_turn_cost")

    assert result.status == CoveragePlanningStatus.SUCCESS
    geometry = result.diagnostics.to_summary_dict()["runtime"]["geometry_risk_summary"]
    assert geometry["available"] is False
    assert geometry["status"] == "summary_missing"
    assert geometry["reason"] == "geometry_risk_summary_path_not_found"
    assert geometry["summary_path"] == str(missing_summary)


def test_shelf_aware_turn_cost_marks_incomplete_geometry_risk_sidecar_unavailable(tmp_path):
    geometry_summary_dir = tmp_path / "geometry"
    geometry_summary_dir.mkdir()
    (geometry_summary_dir / "summary.json").write_text(
        json.dumps(
            {
                "body_swept_collision_count": 2,
                "turn_swept_collision_count": 4,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    room_map = np.zeros((80, 120), dtype=np.uint8)
    room_map[10:70, 10:110] = 255
    request = CoveragePlanningRequest(
        prepared_map=room_map,
        map_resolution=0.05,
        starting_position_px=(20, 20),
        public_config=CoveragePlannerConfig(
            planner_mode="shelf_aware_turn_cost",
            coverage_width_m=0.5,
            robot_width_m=0.2,
            open_kernel_m=0.1,
            obstacle_expand_m=0.1,
            auto_rotate=False,
            write_artifacts=False,
            geometry_risk_summary_path=str(geometry_summary_dir),
        ),
    )

    result = run_formal_planner_request(request, "shelf_aware_turn_cost")

    assert result.status == CoveragePlanningStatus.SUCCESS
    geometry = result.diagnostics.to_summary_dict()["runtime"]["geometry_risk_summary"]
    assert geometry["available"] is False
    assert geometry["status"] == "invalid_summary"
    assert geometry["reason"] == "geometry_risk_summary_missing_required_fields"
    assert geometry["missing_fields"] == ["cleaning_footprint_coverage_ratio"]


def test_shelf_aware_turn_cost_marks_bad_geometry_metric_value_unavailable(tmp_path):
    geometry_summary = tmp_path / "summary.json"
    geometry_summary.write_text(
        json.dumps(
            {
                "body_swept_collision_count": "bad",
                "turn_swept_collision_count": 4,
                "cleaning_footprint_coverage_ratio": "bad",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    room_map = np.zeros((80, 120), dtype=np.uint8)
    room_map[10:70, 10:110] = 255
    request = CoveragePlanningRequest(
        prepared_map=room_map,
        map_resolution=0.05,
        starting_position_px=(20, 20),
        public_config=CoveragePlannerConfig(
            planner_mode="shelf_aware_turn_cost",
            coverage_width_m=0.5,
            robot_width_m=0.2,
            open_kernel_m=0.1,
            obstacle_expand_m=0.1,
            auto_rotate=False,
            write_artifacts=False,
            geometry_risk_summary_path=str(geometry_summary),
        ),
    )

    result = run_formal_planner_request(request, "shelf_aware_turn_cost")

    assert result.status == CoveragePlanningStatus.SUCCESS
    geometry = result.diagnostics.to_summary_dict()["runtime"]["geometry_risk_summary"]
    assert geometry["available"] is False
    assert geometry["status"] == "invalid_summary"
    assert geometry["reason"] == "geometry_risk_summary_invalid_metric_value"
    assert geometry["invalid_fields"] == [
        "body_swept_collision_count",
        "cleaning_footprint_coverage_ratio",
    ]


def test_shelf_aware_default_artifacts_root_is_outside_python_ws():
    planner = ShelfAwareCoveragePlanner(CoveragePlannerConfig(planner_mode="shelf_aware"))

    output_root = planner._default_output_root()

    assert output_root.parts[-2:] == ("runtime_runs", "coverage_planning")
    assert "python_ws" not in output_root.parts


def test_shelf_aware_explicit_artifacts_root_wins(tmp_path):
    planner = ShelfAwareCoveragePlanner(
        CoveragePlannerConfig(
            planner_mode="shelf_aware",
            artifacts_output_root=str(tmp_path),
        )
    )

    assert planner._default_output_root() == tmp_path.resolve()


def test_shelf_aware_passes_isolated_jump_cleanup_config_to_internal_planner():
    planner = ShelfAwareCoveragePlanner(
        CoveragePlannerConfig(
            planner_mode="shelf_aware",
            isolated_jump_cleanup_enable=True,
            isolated_jump_distance_m=4.0,
            isolated_jump_max_points=5,
            isolated_jump_max_length_m=1.5,
            isolated_jump_reinsert_max_distance_m=0.8,
            isolated_jump_reinsert_improvement_ratio=0.7,
        )
    )

    internal = planner._build_planner_config(
        room_map=np.ones((8, 8), dtype=np.uint8) * 255,
        starting_position=(1, 1),
    )

    assert internal.isolated_jump_cleanup.enable is True
    assert internal.isolated_jump_cleanup.jump_distance_m == 4.0
    assert internal.isolated_jump_cleanup.max_isolated_points == 5
    assert internal.isolated_jump_cleanup.max_isolated_length_m == 1.5
    assert internal.isolated_jump_cleanup.reinsert_max_distance_m == 0.8
    assert internal.isolated_jump_cleanup.reinsert_improvement_ratio == 0.7


def test_shelf_aware_passes_row_endpoint_alignment_config_to_internal_planner():
    planner = ShelfAwareCoveragePlanner(
        CoveragePlannerConfig(
            planner_mode="shelf_aware",
            shelf_row_endpoint_alignment_enable=False,
        )
    )

    internal = planner._build_planner_config(
        room_map=np.ones((8, 8), dtype=np.uint8) * 255,
        starting_position=(1, 1),
    )

    assert internal.row_endpoint_alignment_enable is False


def test_shelf_aware_passes_node_obstacle_ratio_filter_config_to_internal_planner():
    planner = ShelfAwareCoveragePlanner(
        CoveragePlannerConfig(
            planner_mode="shelf_aware",
            shelf_node_obstacle_ratio_filter_enable=False,
            shelf_node_obstacle_ratio_threshold=0.35,
        )
    )

    internal = planner._build_planner_config(
        room_map=np.ones((8, 8), dtype=np.uint8) * 255,
        starting_position=(1, 1),
    )

    assert internal.node_obstacle_ratio_filter_enable is False
    assert internal.node_obstacle_ratio_threshold == 0.35


def test_create_coverage_planner_rejects_unknown_mode():
    with pytest.raises(ValueError, match="unsupported planner_mode"):
        create_coverage_planner(CoveragePlannerConfig(planner_mode="mystery"))


def test_coverage_planner_config_rejects_invalid_ui_quality_guard_threshold():
    with pytest.raises(ValueError, match="shelf_quality_guard_min_coverage_ratio"):
        CoveragePlannerConfig(shelf_quality_guard_min_coverage_ratio=1.1)


def test_check_optional_planner_dependencies_marks_unknown_mode_unavailable():
    ok, reason = check_optional_planner_dependencies("mystery")

    assert not ok
    assert reason is not None
    assert "unknown planner mode" in reason


def test_shelf_aware_no_longer_runs_internal_erode(monkeypatch, tmp_path):
    def forbidden_erode(*args, **kwargs):
        raise AssertionError("shelfAware 在阶段2预处理后不能再执行内部 cv2.erode")

    monkeypatch.setattr(cv2, "erode", forbidden_erode)
    planner = ShelfAwareCoveragePlanner(
        CoveragePlannerConfig(
            planner_mode="shelf_aware",
            write_artifacts=False,
            artifacts_output_root=str(tmp_path),
            auto_rotate=False,
        )
    )
    room_map = np.zeros((80, 120), dtype=np.uint8)
    room_map[10:70, 10:110] = 255

    result = planner.plan(room_map, map_resolution=0.05, starting_position=(20, 20))

    assert result.success


def test_shelf_aware_internal_artifact_paths_are_none_when_artifacts_disabled(tmp_path):
    room_map = np.zeros((60, 60), dtype=np.uint8)
    room_map[5:55, 5:55] = 255

    _, artifacts = plan_coverage_path(
        room_map=room_map,
        metadata={"resolution": 0.05, "origin": [0.0, 0.0, 0.0]},
        output_dir=str(tmp_path),
        config=PlannerConfig(
            coverage_width_m=0.5,
            start_pixel=(10, 10),
            write_artifacts=False,
            save_debug_csv=False,
            semantic_path_enable=False,
        ),
    )

    assert artifacts.rotated_map_path is None
    assert artifacts.overlay_path is None
    assert artifacts.path_pixels_path is None
    assert artifacts.path_world_path is None
    assert artifacts.final_segment_provenance_path is None
    assert artifacts.candidate_decision_debug_path is None


def test_shelf_aware_writes_config_region_mask_artifact(tmp_path):
    room_map = np.zeros((60, 60), dtype=np.uint8)
    room_map[5:55, 5:55] = 255
    region_mask = np.zeros_like(room_map)
    region_mask[10:40, 10:35] = 255

    _, artifacts = plan_coverage_path(
        room_map=room_map,
        metadata={"resolution": 0.05, "origin": [0.0, 0.0, 0.0]},
        output_dir=str(tmp_path),
        config=PlannerConfig(
            coverage_width_m=0.5,
            start_pixel=(12, 12),
            region_mask=region_mask,
            write_artifacts=True,
            save_debug_csv=False,
            semantic_path_enable=False,
        ),
    )

    assert artifacts.path_pixels_path is not None
    assert artifacts.final_segment_provenance_path is not None
    assert artifacts.pipeline_trace_path is not None
    written_mask = cv2.imread(str(tmp_path / "region_mask.png"), cv2.IMREAD_GRAYSCALE)
    assert np.array_equal(written_mask, region_mask)
    final_provenance = json.loads((tmp_path / "final_segment_provenance.json").read_text(encoding="utf-8"))
    assert final_provenance["version"] == "shelf_aware_guarded_final_segment_provenance_v2"
    assert final_provenance["source_path_artifact"] == "path_pixels.json"
    assert final_provenance["source_move_trace_artifact"] == "path_generation_provenance.json"
    assert final_provenance["point_count"] >= 2
    assert final_provenance["segment_count"] == final_provenance["point_count"] - 1
    source_summary = final_provenance["source_summary"]
    assert (
        source_summary["matched_traversal_segment_count"]
        + source_summary["derived_final_geometry_segment_count"]
        == final_provenance["segment_count"]
    )
    first_segment = final_provenance["items"][0]
    assert first_segment["evidence_level"] in {"matched_traversal_edge", "final_segment_sidecar"}
    assert first_segment["source_policy"] in {"traversal_move_trace", "final_path_geometry"}
    assert "move_source" in first_segment
    assert "edge_role" in first_segment
    if first_segment["generation_move"] is not None:
        assert first_segment["generation_move"]["move_source"] == first_segment["move_source"]
        assert first_segment["generation_move"]["edge_role"] == first_segment["edge_role"]
    pipeline_trace = json.loads((tmp_path / "pipeline_trace.json").read_text(encoding="utf-8"))
    assert pipeline_trace["version"] == "shelf_aware_guarded_pipeline_trace_v1"
    assert pipeline_trace["path_mutating_stage_count"] >= 3
    stage_names = [item["stage_name"] for item in pipeline_trace["stages"]]
    assert stage_names == [
        "input_validation",
        "room_rotation",
        "local_direction_field",
        "coverage_graph_build",
        "start_cell_selection",
        "graph_traversal",
        "simplify_rotated_path",
        "semantic_global_path",
        "isolated_jump_cleanup",
        "final_path_geometry",
        "output_assembly",
        "artifact_write",
    ]
