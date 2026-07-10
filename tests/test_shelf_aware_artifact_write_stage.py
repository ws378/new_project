from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np

from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.manifest import (
    ARTIFACT_MANIFEST_RESULT_CONTRACT,
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    ARTIFACT_ROLE_NOTE,
    artifact_manifest_entry,
    artifact_manifest_payload,
    planner_artifact_manifest_entries,
    write_artifact_manifest,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.metadata_payloads import (
    planner_metadata_payload,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.decision_debug_payloads import (
    CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded import artifacts
from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.path_payloads import (
    indexed_points_payload,
    path_jump_segments_pixels_payload,
    path_pixels_payload,
    path_segments_pixels_payload,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.paths import (
    PlannerArtifactPaths,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.provenance_payloads import (
    FINAL_SEGMENT_PROVENANCE_VERSION,
    TRAVERSAL_MOVE_TRACE_VERSION,
    final_segment_provenance_payload,
    path_generation_provenance_payload,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.schema_registry import (
    ARTIFACT_SCHEMA_REGISTRY,
    FINAL_PATH_TRANSFORM_RECORDS_SCHEMA_VERSION,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.artifact_write import (
    ArtifactWriteStageInput,
    build_planner_artifact_context,
    write_artifacts_stage,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.coverage_graph import (
    CoverageGraphBuildResult,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.direction_field import (
    DirectionFieldStageResult,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.final_path.realization import (
    FinalPathRealizationResult,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.final_path.transform_record import (
    FINAL_PATH_TRANSFORM_FINAL_PATH_GEOMETRY,
    FINAL_PATH_TRANSFORM_TYPE_GEOMETRIC_FORMATTING,
    build_final_path_transform_record,
    final_path_transform_records_payload,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.graph_traversal import (
    GraphTraversalStageResult,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.graph_build.grid_builder import (
    CellCandidate,
    CoverageCellGrid,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.input_validation import (
    InputValidationStageResult,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import (
    PlannerArtifacts,
    PlannerConfig,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.output_assembly import (
    OutputPathAssemblyResult,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.trace import (
    PipelineStageRecord,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.room_rotation import (
    RoomRotationStageResult,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal import (
    TraversalResult,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_MODULE_DIR = (
    REPO_ROOT
    / "algorithms"
    / "coverage_planning"
    / "planners"
    / "shelf_aware_guarded"
    / "artifacts"
)


def _parse_module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _called_attribute_names(tree: ast.Module) -> set[str]:
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }


def _stage_inputs():
    config = PlannerConfig()
    room_map = np.full((4, 5), 255, dtype=np.uint8)
    planning_room_map = room_map.copy()
    rotated_room_map = np.full((3, 4), 255, dtype=np.uint8)
    rotation_matrix = np.array([[1.0, 0.0, 2.0], [0.0, 1.0, 3.0]], dtype=np.float32)
    inverse_rotation = np.array([[1.0, 0.0, -2.0], [0.0, 1.0, -3.0]], dtype=np.float32)
    local_direction_map = np.ones((3, 4), dtype=np.float32)
    local_direction_confidence = np.full((3, 4), 0.8, dtype=np.float32)
    edge_label_map = np.zeros((3, 4), dtype=np.int32)
    region_mask = np.full((4, 5), 255, dtype=np.uint8)
    static_cell_grid = CoverageCellGrid.from_rows(
        [
            [
                CellCandidate(
                    planning_point_px=(1, 2),
                    grid_center_px=(1, 2),
                    obstacle=False,
                    grid_row=0,
                    grid_col=0,
                )
            ]
        ]
    )
    graph_access = object()
    jump_cleanup_result = object()
    pipeline_trace = [PipelineStageRecord(stage_name="input_validation")]

    input_stage = InputValidationStageResult(
        map_resolution=0.05,
        map_origin=(1.0, 2.0),
        map_height=4,
        planning_room_map=planning_room_map,
        region_mask=region_mask,
        chosen_start_pixel=(2, 3),
        coverage_width_px=12,
        robot_half_width_px=5.5,
        stage_record=pipeline_trace[0],
    )
    rotation_stage = RoomRotationStageResult(
        rotation_angle_rad=0.25,
        rotation_matrix=rotation_matrix,
        inverse_rotation=inverse_rotation,
        full_rotation_matrix=rotation_matrix,
        bounding_rect=(0, 0, 4, 3),
        full_bounding_rect=(1, 2, 8, 7),
        crop_rect=(2, 3, 4, 3),
        rotated_crop_offset_px=(2, 3),
        full_rotated_shape=(7, 8),
        rotated_room_map=rotated_room_map,
        frame_id="cropped_rotated_room",
        stage_record=PipelineStageRecord(stage_name="room_rotation"),
    )
    direction_stage = DirectionFieldStageResult(
        local_direction_map=local_direction_map,
        local_direction_confidence=local_direction_confidence,
        local_direction_source="image_gradient",
        rotated_edge_label_map=edge_label_map,
        stage_record=PipelineStageRecord(stage_name="local_direction_field"),
    )
    graph_stage = CoverageGraphBuildResult(
        static_cell_grid=static_cell_grid,
        coverage_graph=object(),
        graph_access=graph_access,
        min_room=(1, 2),
        max_room=(9, 10),
        stage_record=PipelineStageRecord(stage_name="coverage_graph_build"),
    )
    traversal_state_snapshot = object()
    traversal_result = TraversalResult(
        fov_coverage_path=[(1.0, 1.0), (2.0, 2.0)],
        move_trace=[{"move_id": "m1"}],
        fallback_debug_trace=[{"step": 1}],
        traversal_state_summary={"visited": 2},
        traversal_state_snapshot=traversal_state_snapshot,
        candidate_decision_debug_trace=[{"step": 1, "phases": []}],
    )
    graph_traversal_stage = GraphTraversalStageResult(
        traversal_result=traversal_result,
        stage_record=PipelineStageRecord(stage_name="graph_traversal"),
    )
    final_path_transform_record = build_final_path_transform_record(
        name=FINAL_PATH_TRANSFORM_FINAL_PATH_GEOMETRY,
        transform_type=FINAL_PATH_TRANSFORM_TYPE_GEOMETRIC_FORMATTING,
        enabled=True,
        input_point_count=2,
        output_point_count=2,
        changes_path_points=False,
    )
    final_path_result = FinalPathRealizationResult(
        simplified_fov_path=[(1.0, 1.0)],
        pixel_points_raw=[(1.0, 1.0), (2.0, 2.0)],
        baseline_pixel_points=[(1.0, 1.0)],
        pixel_points=[(1.0, 1.0), (2.0, 2.0)],
        pixel_poses=[(1.0, 1.0, 0.0), (2.0, 2.0, 0.5)],
        pixel_segments=[[(1.0, 1.0), (2.0, 2.0)]],
        pixel_segment_indices=[[1, 2]],
        jump_segments=[((1.0, 1.0), (2.0, 2.0))],
        jump_segment_indices=[(1, 2)],
        node_semantics_payload={"summary": {"enabled": True}},
        semantic_path_payload={"summary": {"enabled": True}},
        jump_cleanup_result=jump_cleanup_result,
        pipeline_stage_records=[PipelineStageRecord(stage_name="final_path_geometry")],
        transform_records=(final_path_transform_record,),
    )
    output_assembly_result = OutputPathAssemblyResult(
        world_path=[{"index": 1, "x": 1.0, "y": 2.0, "theta": -0.5}],
        stage_record=PipelineStageRecord(stage_name="output_assembly"),
    )
    return ArtifactWriteStageInput(
        output_path=Path("/tmp/artifacts"),
        config=config,
        room_map=room_map,
        metadata={"resolution": 0.05},
        input_stage=input_stage,
        rotation_stage=rotation_stage,
        direction_stage=direction_stage,
        graph_stage=graph_stage,
        graph_traversal_stage=graph_traversal_stage,
        final_path_result=final_path_result,
        output_assembly_result=output_assembly_result,
        inverse_rotation=inverse_rotation,
        pipeline_trace=pipeline_trace,
    )


def test_artifact_writer_stays_as_orchestrator_not_renderer() -> None:
    tree = _parse_module(ARTIFACT_MODULE_DIR / "writer.py")
    imported = _imported_modules(tree)

    assert "cv2" not in imported
    assert "PIL" not in imported
    assert "csv" not in imported
    assert "imwrite" not in _called_attribute_names(tree)


def test_artifact_renderers_do_not_own_json_result_payloads() -> None:
    forbidden_import_tails = {
        "cleanup_payloads",
        "decision_debug_payloads",
        "manifest",
        "metadata_payloads",
        "node_debug",
        "path_payloads",
        "paths",
        "provenance_payloads",
    }
    offenders: list[str] = []

    for module_name in ("visualization.py", "csv_debug.py"):
        tree = _parse_module(ARTIFACT_MODULE_DIR / module_name)
        imported = _imported_modules(tree)
        if "json" in imported:
            offenders.append(f"{module_name}:import json")
        for module in sorted(imported):
            if module.rsplit(".", 1)[-1] in forbidden_import_tails:
                offenders.append(f"{module_name}:import {module}")

    assert offenders == []


def test_artifact_json_payload_modules_do_not_write_visual_or_csv_artifacts() -> None:
    payload_modules = [
        ARTIFACT_MODULE_DIR / "cleanup_payloads.py",
        ARTIFACT_MODULE_DIR / "decision_debug_payloads.py",
        ARTIFACT_MODULE_DIR / "manifest.py",
        ARTIFACT_MODULE_DIR / "metadata_payloads.py",
        ARTIFACT_MODULE_DIR / "path_payloads.py",
        ARTIFACT_MODULE_DIR / "provenance_payloads.py",
    ]
    offenders: list[str] = []

    for path in payload_modules:
        tree = _parse_module(path)
        imported = _imported_modules(tree)
        for module in sorted(imported):
            module_tail = module.rsplit(".", 1)[-1]
            if module == "PIL" or module_tail in {"visualization", "csv_debug"}:
                offenders.append(f"{path.name}:import {module}")
        if "imwrite" in _called_attribute_names(tree):
            offenders.append(f"{path.name}:cv2.imwrite")
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "save_debug_csv":
                offenders.append(f"{path.name}:save_debug_csv")

    assert offenders == []


def test_artifact_node_debug_writer_stays_json_only() -> None:
    tree = _parse_module(ARTIFACT_MODULE_DIR / "node_debug.py")
    imported = _imported_modules(tree)

    assert "PIL" not in imported
    assert "csv" not in imported
    assert not any(module.rsplit(".", 1)[-1] == "visualization" for module in imported)
    assert not any(module.rsplit(".", 1)[-1] == "csv_debug" for module in imported)
    assert "imwrite" not in _called_attribute_names(tree)
    for node in ast.walk(tree):
        assert not (isinstance(node, ast.Name) and node.id == "save_debug_csv")


def test_artifact_package_exports_only_public_orchestration() -> None:
    assert artifacts.__all__ == (
        "PlannerArtifactContext",
        "write_planner_artifacts",
    )


def test_artifact_manifest_payload_keeps_result_contract_and_entries(tmp_path):
    path_pixels_json_path = tmp_path / "path_pixels.json"
    entry = artifact_manifest_entry(
        path_pixels_json_path,
        role="final_path_pixels_evidence",
        schema_or_format="path_pixels_v1",
    )

    payload = artifact_manifest_payload({"path_pixels": entry})

    assert payload["schema_version"] == ARTIFACT_MANIFEST_SCHEMA_VERSION
    assert payload["result_contract"] == ARTIFACT_MANIFEST_RESULT_CONTRACT
    assert payload["artifact_role_note"] == ARTIFACT_ROLE_NOTE
    assert payload["artifacts"]["path_pixels"] == entry

    artifact_manifest_json_path = tmp_path / "artifact_manifest.json"
    write_artifact_manifest(artifact_manifest_json_path, {"path_pixels": entry})

    assert json.loads(artifact_manifest_json_path.read_text(encoding="utf-8")) == payload


def test_planner_artifact_paths_are_single_fixed_filename_source(tmp_path):
    paths = PlannerArtifactPaths.from_output_dir(tmp_path)

    assert paths.output_dir == tmp_path
    assert paths.rotated_map == tmp_path / "rotated_room_map.png"
    assert paths.nodes_debug == tmp_path / "nodes_debug.png"
    assert paths.path_overlay == tmp_path / "path_overlay.png"
    assert paths.region_mask == tmp_path / "region_mask.png"
    assert paths.region_overlay == tmp_path / "region_overlay.png"
    assert paths.local_direction_debug == tmp_path / "local_direction_debug.png"
    assert paths.region_json == tmp_path / "region.json"
    assert paths.path_pixels_raw == tmp_path / "path_pixels_raw.json"
    assert paths.path_pixels_baseline_before_semantics == tmp_path / "path_pixels_baseline_before_semantics.json"
    assert paths.path_pixels == tmp_path / "path_pixels.json"
    assert paths.path_segments_pixels == tmp_path / "path_segments_pixels.json"
    assert paths.path_jump_segments_pixels == tmp_path / "path_jump_segments_pixels.json"
    assert paths.path_world == tmp_path / "path_world.json"
    assert paths.metadata == tmp_path / "metadata.json"
    assert paths.fallback_debug_trace == tmp_path / "fallback_debug_trace.json"
    assert paths.candidate_decision_debug == tmp_path / "candidate_decision_debug.json"
    assert paths.path_generation_provenance == tmp_path / "path_generation_provenance.json"
    assert paths.final_segment_provenance == tmp_path / "final_segment_provenance.json"
    assert paths.pipeline_trace == tmp_path / "pipeline_trace.json"
    assert paths.artifact_manifest == tmp_path / "artifact_manifest.json"
    assert paths.node_debug_enriched == tmp_path / "node_debug_enriched.json"
    assert paths.node_semantics == tmp_path / "node_semantics.json"
    assert paths.semantic_global_path == tmp_path / "semantic_global_path.json"
    assert paths.isolated_jump_cleanup == tmp_path / "isolated_jump_cleanup.json"
    assert paths.node_obstacle_ratio_filter_debug == tmp_path / "node_obstacle_ratio_filter_debug.png"
    assert paths.energy_debug == tmp_path / "energy_debug.csv"


def test_artifact_schema_registry_is_unique_and_covers_version_constants() -> None:
    names = list(ARTIFACT_SCHEMA_REGISTRY.keys())
    artifact_names = [spec.artifact_name for spec in ARTIFACT_SCHEMA_REGISTRY.values()]
    filenames = [spec.filename for spec in ARTIFACT_SCHEMA_REGISTRY.values()]

    assert names == artifact_names
    assert len(names) == len(set(names))
    assert len(artifact_names) == len(set(artifact_names))
    assert "candidate_decision_debug.json" in filenames
    assert "path_generation_provenance.json" in filenames
    assert "final_segment_provenance.json" in filenames
    assert ARTIFACT_SCHEMA_REGISTRY["candidate_decision_debug"].schema_or_format == (
        CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION
    )
    assert ARTIFACT_SCHEMA_REGISTRY["path_generation_provenance"].schema_or_format == TRAVERSAL_MOVE_TRACE_VERSION
    assert ARTIFACT_SCHEMA_REGISTRY["final_segment_provenance"].schema_or_format == FINAL_SEGMENT_PROVENANCE_VERSION
    assert ARTIFACT_SCHEMA_REGISTRY["final_path_transform_records"].schema_or_format == (
        FINAL_PATH_TRANSFORM_RECORDS_SCHEMA_VERSION
    )


def test_planner_artifact_manifest_entries_preserve_complete_artifact_contract(tmp_path):
    paths = PlannerArtifactPaths.from_output_dir(tmp_path)

    entries = planner_artifact_manifest_entries(
        paths=paths,
        region_mask_available=False,
        node_obstacle_ratio_filter_enabled=False,
        debug_csv_enabled=False,
        node_semantics_available=False,
        semantic_path_available=False,
    )

    expected_paths = {
        "rotated_room_map": paths.rotated_map,
        "nodes_debug": paths.nodes_debug,
        "path_overlay": paths.path_overlay,
        "region_mask": paths.region_mask,
        "region_overlay": paths.region_overlay,
        "local_direction_debug": paths.local_direction_debug,
        "region": paths.region_json,
        "path_pixels_raw": paths.path_pixels_raw,
        "path_pixels_baseline_before_semantics": paths.path_pixels_baseline_before_semantics,
        "path_pixels": paths.path_pixels,
        "path_segments_pixels": paths.path_segments_pixels,
        "path_jump_segments_pixels": paths.path_jump_segments_pixels,
        "path_world": paths.path_world,
        "metadata": paths.metadata,
        "fallback_debug_trace": paths.fallback_debug_trace,
        "candidate_decision_debug": paths.candidate_decision_debug,
        "path_generation_provenance": paths.path_generation_provenance,
        "final_segment_provenance": paths.final_segment_provenance,
        "pipeline_trace": paths.pipeline_trace,
        "node_debug_enriched": paths.node_debug_enriched,
        "node_semantics": paths.node_semantics,
        "semantic_global_path": paths.semantic_global_path,
        "isolated_jump_cleanup": paths.isolated_jump_cleanup,
        "node_obstacle_ratio_filter_debug": paths.node_obstacle_ratio_filter_debug,
        "energy_debug": paths.energy_debug,
        "final_path_transform_records": paths.metadata,
    }
    expected_unavailable_reasons = {
        "region_mask": "region_mask_not_provided",
        "region_overlay": "region_mask_not_provided",
        "region": "region_mask_not_provided",
        "node_semantics": "semantic_path_disabled_or_unavailable",
        "semantic_global_path": "semantic_path_disabled_or_unavailable",
        "node_obstacle_ratio_filter_debug": "node_obstacle_ratio_filter_disabled",
        "energy_debug": "debug_csv_disabled",
    }

    assert list(entries.keys()) == list(ARTIFACT_SCHEMA_REGISTRY.keys())
    for name, spec in ARTIFACT_SCHEMA_REGISTRY.items():
        available = name not in expected_unavailable_reasons
        optional_reason = expected_unavailable_reasons.get(name, "")
        assert entries[name] == artifact_manifest_entry(
            expected_paths[name],
            role=spec.role,
            schema_or_format=spec.schema_or_format,
            available=available,
            optional_reason=optional_reason,
        )
        assert Path(entries[name]["path"]).name == spec.filename


def test_planner_artifact_manifest_entries_preserve_optional_available_contract(tmp_path):
    paths = PlannerArtifactPaths.from_output_dir(tmp_path)

    entries = planner_artifact_manifest_entries(
        paths=paths,
        region_mask_available=True,
        node_obstacle_ratio_filter_enabled=True,
        debug_csv_enabled=True,
        node_semantics_available=True,
        semantic_path_available=True,
    )

    assert entries["region_mask"]["available"] is True
    assert entries["region_mask"]["optional_reason"] == ""
    assert entries["region_overlay"]["available"] is True
    assert entries["region_overlay"]["optional_reason"] == ""
    assert entries["region"]["available"] is True
    assert entries["region"]["optional_reason"] == ""
    assert entries["node_obstacle_ratio_filter_debug"]["available"] is True
    assert entries["node_obstacle_ratio_filter_debug"]["optional_reason"] == ""
    assert entries["node_semantics"]["available"] is True
    assert entries["node_semantics"]["optional_reason"] == ""
    assert entries["semantic_global_path"]["available"] is True
    assert entries["semantic_global_path"]["optional_reason"] == ""
    assert entries["energy_debug"]["available"] is True
    assert entries["energy_debug"]["optional_reason"] == ""


def test_manifest_marks_final_path_transform_records_as_metadata_embedded_evidence(tmp_path):
    paths = PlannerArtifactPaths.from_output_dir(tmp_path)

    entries = planner_artifact_manifest_entries(
        paths=paths,
        region_mask_available=True,
        node_obstacle_ratio_filter_enabled=True,
        debug_csv_enabled=True,
        node_semantics_available=True,
        semantic_path_available=True,
    )

    transform_entry = entries["final_path_transform_records"]
    assert transform_entry["path"] == str(paths.metadata)
    assert transform_entry["role"] == "final_path_transform_manifest_embedded_in_metadata"
    assert transform_entry["schema_or_format"] == FINAL_PATH_TRANSFORM_RECORDS_SCHEMA_VERSION
    assert transform_entry["available"] is True
    assert transform_entry["optional_reason"] == ""


def test_path_payload_helpers_preserve_pixel_index_contract():
    pixel_points = [(10.0, 20.0), (11.0, 21.0), (12.0, 22.0)]
    pixel_poses = [(10.0, 20.0, 0.1), (11.0, 21.0, 0.2)]

    assert indexed_points_payload(pixel_points[:2]) == [
        {"index": 1, "x": 10.0, "y": 20.0},
        {"index": 2, "x": 11.0, "y": 21.0},
    ]
    assert path_pixels_payload(pixel_poses) == [
        {"index": 1, "x": 10.0, "y": 20.0, "theta": 0.1},
        {"index": 2, "x": 11.0, "y": 21.0, "theta": 0.2},
    ]
    assert path_segments_pixels_payload(
        pixel_points=pixel_points,
        pixel_segment_indices=[[1, 3]],
    ) == [[{"index": 1, "x": 10.0, "y": 20.0}, {"index": 3, "x": 12.0, "y": 22.0}]]
    assert path_jump_segments_pixels_payload(
        pixel_points=pixel_points,
        jump_segment_indices=[(2, 3)],
    ) == [[{"index": 2, "x": 11.0, "y": 21.0}, {"index": 3, "x": 12.0, "y": 22.0}]]


def test_provenance_payload_helpers_preserve_versions_and_matching():
    class JumpCleanupResult:
        def to_summary_dict(self, map_resolution):
            return {"map_resolution": map_resolution, "enabled": False}

    inverse_rotation = np.eye(2, 3, dtype=np.float32)
    move_trace = [
        {
            "move_id": "move_000001",
            "path_index": 1,
            "move_source": "normal_neighbor",
            "edge_role": "coverage",
            "from_node_id": "cell_a",
            "to_node_id": "cell_b",
            "selected_energy": 1.5,
            "distance_px": 2.0,
            "heading_rad": 0.0,
            "turn_angle_deg": 0.0,
            "phase_candidate_count": 3,
            "phase_energy_evaluated_candidate_count": 2,
            "phase_accepted_candidate_count": 1,
            "phase_rejected_before_energy_count": 1,
            "phase_candidate_rank": 0,
            "from_point_rotated_px": (1.0, 2.0),
            "to_point_rotated_px": (3.0, 4.0),
        }
    ]

    move_payload = path_generation_provenance_payload(move_trace, inverse_rotation=inverse_rotation)
    assert move_payload["version"] == TRAVERSAL_MOVE_TRACE_VERSION
    assert move_payload["items"][0]["from_point"]["pixel_x"] == 1.0
    assert move_payload["items"][0]["to_point"]["pixel_y"] == 4.0

    final_payload = final_segment_provenance_payload(
        pixel_points=[(1.0, 2.0), (3.0, 4.0)],
        pixel_poses=[(1.0, 2.0, 0.0), (3.0, 4.0, 0.0)],
        traversal_move_trace=move_trace,
        inverse_rotation=inverse_rotation,
        map_resolution=0.05,
        semantic_path_payload=None,
        jump_cleanup_result=JumpCleanupResult(),
    )

    assert final_payload["version"] == FINAL_SEGMENT_PROVENANCE_VERSION
    assert final_payload["source_summary"]["matched_traversal_segment_count"] == 1
    assert final_payload["items"][0]["generation_move"]["move_id"] == "move_000001"
    assert final_payload["stage_summary"]["semantic_path"] == {"enabled": False}


def test_build_planner_artifact_context_maps_stage_results_without_mutation(monkeypatch):
    inputs = _stage_inputs()
    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.metadata_payloads.node_obstacle_ratio_filter_metadata",
        lambda **_: {"enabled": False},
    )

    context = build_planner_artifact_context(inputs)

    assert context.output_path == Path("/tmp/artifacts")
    assert context.config is inputs.config
    assert context.room_map is inputs.room_map
    assert context.planning_room_map is inputs.input_stage.planning_room_map
    assert context.rotated_room_map is inputs.rotation_stage.rotated_room_map
    assert not hasattr(context, "legacy_node_matrix")
    assert not hasattr(context, "nodes")
    assert context.graph_access is inputs.graph_stage.graph_access
    assert context.metadata == {"resolution": 0.05}
    assert context.map_resolution == 0.05
    assert context.map_origin == (1.0, 2.0)
    assert context.map_height == 4
    assert context.coverage_width_px == 12
    assert context.rotation_angle == 0.25
    assert context.rotation_matrix is inputs.rotation_stage.rotation_matrix
    assert context.inverse_rotation is inputs.inverse_rotation
    assert context.full_rotation_matrix is inputs.rotation_stage.full_rotation_matrix
    assert context.full_bounding_rect == (1, 2, 8, 7)
    assert context.crop_rect == (2, 3, 4, 3)
    assert context.rotated_crop_offset_px == (2, 3)
    assert context.full_rotated_shape == (7, 8)
    assert context.local_direction_map is inputs.direction_stage.local_direction_map
    assert context.local_direction_confidence is inputs.direction_stage.local_direction_confidence
    assert context.local_direction_source == "image_gradient"
    assert context.chosen_start_pixel == (2, 3)
    assert context.region_mask is inputs.input_stage.region_mask
    assert context.rotated_edge_label_map is inputs.direction_stage.rotated_edge_label_map
    assert context.pixel_points_raw == [(1.0, 1.0), (2.0, 2.0)]
    assert context.baseline_pixel_points == [(1.0, 1.0)]
    assert context.pixel_points == [(1.0, 1.0), (2.0, 2.0)]
    assert context.pixel_poses == [(1.0, 1.0, 0.0), (2.0, 2.0, 0.5)]
    assert context.pixel_segments == [[(1.0, 1.0), (2.0, 2.0)]]
    assert context.pixel_segment_indices == [[1, 2]]
    assert context.jump_segments == [((1.0, 1.0), (2.0, 2.0))]
    assert context.jump_segment_indices == [(1, 2)]
    assert context.world_path == [{"index": 1, "x": 1.0, "y": 2.0, "theta": -0.5}]
    assert context.fallback_debug_trace == [{"step": 1}]
    assert context.candidate_decision_debug_trace == [{"step": 1, "phases": []}]
    assert context.fov_coverage_path == [(1.0, 1.0), (2.0, 2.0)]
    assert context.traversal_move_trace == [{"move_id": "m1"}]
    assert context.traversal_state_snapshot is inputs.graph_traversal_stage.traversal_result.traversal_state_snapshot
    assert context.min_room == (1, 2)
    assert context.max_room == (9, 10)
    assert context.node_semantics_payload == {"summary": {"enabled": True}}
    assert context.semantic_path_payload == {"summary": {"enabled": True}}
    assert context.jump_cleanup_result is inputs.final_path_result.jump_cleanup_result
    assert context.final_path_transform_records == inputs.final_path_result.transform_records
    assert context.pipeline_trace == tuple(inputs.pipeline_trace)
    final_path_transform_payloads = final_path_transform_records_payload(context.final_path_transform_records)

    class _JumpCleanupSummary:
        def to_summary_dict(self, _resolution_m_per_px: float) -> dict[str, object]:
            return {"enabled": False}

    metadata_payload = planner_metadata_payload(
        paths=PlannerArtifactPaths.from_output_dir(context.output_path),
        config=context.config,
        map_resolution=context.map_resolution,
        map_origin=context.map_origin,
        coverage_width_px=context.coverage_width_px,
        rotation_angle=context.rotation_angle,
        rotation_matrix=context.rotation_matrix,
        full_rotation_matrix=context.full_rotation_matrix,
        full_bounding_rect=context.full_bounding_rect,
        crop_rect=context.crop_rect,
        rotated_crop_offset_px=context.rotated_crop_offset_px,
        full_rotated_shape=context.full_rotated_shape,
        local_direction_confidence=context.local_direction_confidence,
        rotated_room_map=context.rotated_room_map,
        local_direction_source=context.local_direction_source,
        rotated_edge_label_map=context.rotated_edge_label_map,
        semantic_path_payload=context.semantic_path_payload,
        node_semantics_payload=context.node_semantics_payload,
        jump_cleanup_result=_JumpCleanupSummary(),
        final_path_transform_records=final_path_transform_payloads,
        pipeline_trace=context.pipeline_trace,
        chosen_start_pixel=context.chosen_start_pixel,
        pixel_points_raw=context.pixel_points_raw,
        world_path=context.world_path,
        pixel_segments=context.pixel_segments,
        jump_segments=context.jump_segments,
        fallback_debug_trace=context.fallback_debug_trace,
        candidate_decision_debug_trace=context.candidate_decision_debug_trace,
        traversal_move_trace=context.traversal_move_trace,
        region_mask=context.region_mask,
        planning_room_map=context.planning_room_map,
        graph_access=context.graph_access,
    )
    assert metadata_payload["final_path_transform_records"] == final_path_transform_payloads
    assert metadata_payload["rotated_frame"] == {
        "frame_id": "cropped_rotated_room",
        "semantics": "graph, traversal, direction field, and *_rotated debug fields use cropped rotated coordinates; final path_pixels/path_world and node_debug planning_point_pixel use original image/world coordinates",
        "crop_rect_in_full_rotated_px": [2, 3, 4, 3],
        "crop_offset_in_full_rotated_px": [2, 3],
        "cropped_shape": [3, 4],
        "full_rotated_shape": [7, 8],
        "full_bounding_rect": [1, 2, 8, 7],
        "original_to_full_rotated_matrix": context.full_rotation_matrix.tolist(),
    }
    assert metadata_payload["rotated_edge_label_enabled"] is True


def test_write_artifacts_stage_calls_existing_writer(monkeypatch):
    inputs = _stage_inputs()
    expected_artifacts = PlannerArtifacts(
        output_dir="/tmp/artifacts",
        rotated_map_path=None,
        overlay_path=None,
        nodes_path=None,
        path_pixels_path=None,
        path_world_path=None,
        debug_csv_path=None,
    )
    received_contexts = []

    def fake_write_planner_artifacts(context):
        received_contexts.append(context)
        return expected_artifacts

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.artifact_write.write_planner_artifacts",
        fake_write_planner_artifacts,
    )

    result = write_artifacts_stage(inputs)

    assert result.artifacts is expected_artifacts
    assert result.stage_record.stage_name == "artifact_write"
    assert len(received_contexts) == 1
    assert received_contexts[0].world_path == inputs.output_assembly_result.world_path
    assert [record.stage_name for record in received_contexts[0].pipeline_trace] == [
        "input_validation",
        "artifact_write",
    ]
