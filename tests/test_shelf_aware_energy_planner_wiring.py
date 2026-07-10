from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from algorithms.coverage_planning.planners.shelf_aware_guarded import (
    planner,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import (
    PlannerArtifacts,
    PlannerConfig,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.trace import (
    PipelineStageRecord,
)


def test_plan_coverage_path_reuses_graph_access_from_coverage_graph_stage(monkeypatch, tmp_path):
    graph_access = object()
    start_cell_id = "cell_start"
    received: dict[str, object] = {}
    stage_records = {
        "input": PipelineStageRecord(stage_name="input_validation"),
        "rotation": PipelineStageRecord(stage_name="room_rotation"),
        "direction": PipelineStageRecord(stage_name="local_direction_field"),
        "graph": PipelineStageRecord(stage_name="coverage_graph_build"),
        "start": PipelineStageRecord(stage_name="start_cell_selection"),
        "traversal": PipelineStageRecord(stage_name="graph_traversal"),
    }

    def fake_validate_planning_input(**_kwargs):
        return SimpleNamespace(
            map_resolution=0.05,
            map_origin=(0.0, 0.0),
            map_height=10,
            coverage_width_px=12,
            robot_half_width_px=5.0,
            planning_room_map=np.full((10, 10), 255, dtype=np.uint8),
            chosen_start_pixel=(1, 2),
            stage_record=stage_records["input"],
        )

    def fake_rotate_room_stage(**_kwargs):
        return SimpleNamespace(
            rotation_matrix=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32),
            inverse_rotation=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32),
            bounding_rect=(0, 0, 10, 10),
            rotated_room_map=np.full((10, 10), 255, dtype=np.uint8),
            stage_record=stage_records["rotation"],
        )

    def fake_direction_field_stage(**_kwargs):
        return SimpleNamespace(
            local_direction_map=np.zeros((10, 10), dtype=np.float32),
            local_direction_confidence=np.zeros((10, 10), dtype=np.float32),
            rotated_edge_label_map=None,
            local_direction_source="test",
            stage_record=stage_records["direction"],
        )

    def fake_build_coverage_graph_stage(**_kwargs):
        return SimpleNamespace(
            legacy_mirror_matrix=[["legacy-node"]],
            coverage_graph=object(),
            graph_access=graph_access,
            min_room=(0, 0),
            max_room=(9, 9),
            stage_record=stage_records["graph"],
        )

    def fake_select_start_cell_stage(**kwargs):
        received["start_graph_access"] = kwargs["graph_access"]
        return SimpleNamespace(
            start_cell_id=start_cell_id,
            stage_record=stage_records["start"],
        )

    def fake_run_graph_traversal_stage(stage_input):
        received["traversal_graph_access"] = stage_input.graph_access
        received["traversal_start_cell_id"] = stage_input.start_cell_id
        return SimpleNamespace(
            traversal_result=SimpleNamespace(
                fov_coverage_path=[(1.0, 2.0), (3.0, 4.0)],
                move_trace=[],
                fallback_debug_trace=[],
                candidate_decision_debug_trace=[],
                traversal_state_summary={},
                traversal_state_snapshot=None,
            ),
            stage_record=stage_records["traversal"],
        )

    def fake_realize_final_path(stage_input):
        received["final_graph_access"] = stage_input.graph_access
        return SimpleNamespace(
            pixel_poses=[(1.0, 2.0, 0.0)],
            pipeline_stage_records=[PipelineStageRecord(stage_name="final_path_geometry")],
        )

    def fake_assemble_world_path(stage_input):
        received["output_assembly_pixel_poses"] = stage_input.pixel_poses
        return SimpleNamespace(
            world_path=[{"index": 1, "x": 1.0, "y": 2.0, "theta": 0.0}],
            stage_record=PipelineStageRecord(stage_name="output_assembly"),
        )

    def fake_write_artifacts_stage(stage_input):
        received["artifact_graph_access"] = stage_input.graph_stage.graph_access
        received["artifact_world_path"] = stage_input.output_assembly_result.world_path
        received["pipeline_trace_stage_names"] = [
            record.stage_name for record in stage_input.pipeline_trace
        ]
        return SimpleNamespace(
            artifacts=PlannerArtifacts(
                output_dir=str(tmp_path),
                rotated_map_path=None,
                overlay_path=None,
                nodes_path=None,
                path_pixels_path=None,
                path_world_path=None,
                debug_csv_path=None,
            )
        )

    monkeypatch.setattr(planner, "validate_planning_input", fake_validate_planning_input)
    monkeypatch.setattr(planner, "rotate_room_stage", fake_rotate_room_stage)
    monkeypatch.setattr(planner, "build_direction_field_stage", fake_direction_field_stage)
    monkeypatch.setattr(planner, "build_coverage_graph_stage", fake_build_coverage_graph_stage)
    monkeypatch.setattr(planner, "select_start_cell_stage", fake_select_start_cell_stage)
    monkeypatch.setattr(planner, "run_graph_traversal_stage", fake_run_graph_traversal_stage)
    monkeypatch.setattr(planner, "realize_final_path", fake_realize_final_path)
    monkeypatch.setattr(planner, "assemble_world_path", fake_assemble_world_path)
    monkeypatch.setattr(planner, "write_artifacts_stage", fake_write_artifacts_stage)

    world_path, _artifacts = planner.plan_coverage_path(
        np.full((10, 10), 255, dtype=np.uint8),
        {"resolution": 0.05, "origin": [0.0, 0.0, 0.0]},
        str(tmp_path),
        PlannerConfig(),
    )

    assert world_path == [{"index": 1, "x": 1.0, "y": 2.0, "theta": 0.0}]
    assert received == {
        "start_graph_access": graph_access,
        "traversal_graph_access": graph_access,
        "traversal_start_cell_id": start_cell_id,
        "final_graph_access": graph_access,
        "output_assembly_pixel_poses": [(1.0, 2.0, 0.0)],
        "artifact_graph_access": graph_access,
        "artifact_world_path": world_path,
        "pipeline_trace_stage_names": [
            "input_validation",
            "room_rotation",
            "local_direction_field",
            "coverage_graph_build",
            "start_cell_selection",
            "graph_traversal",
            "final_path_geometry",
            "output_assembly",
        ],
    }
