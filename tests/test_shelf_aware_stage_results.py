from __future__ import annotations

from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.summaries import (
    ArtifactWriteStageSummary,
    CoverageGraphStageSummary,
    GraphTraversalStageSummary,
    InputValidationStageSummary,
    LocalDirectionFieldStageSummary,
    OutputAssemblyStageSummary,
    RoomRotationStageSummary,
    SemanticGlobalPathStageSummary,
    StartCellSelectionStageSummary,
)


def test_stage_summaries_generate_stable_pipeline_records() -> None:
    input_record = InputValidationStageSummary(
        free_pixel_count=12,
        has_region_mask=True,
        start_pixel=(3, 4),
        coverage_width_px=10,
        robot_half_width_px=5.5,
    ).to_stage_record()

    assert input_record.stage_name == "input_validation"
    assert input_record.summary == {
        "free_pixel_count": 12,
        "has_region_mask": True,
        "start_pixel": [3, 4],
        "coverage_width_px": 10,
        "robot_half_width_px": 5.5,
    }

    rotation_record = RoomRotationStageSummary(
        rotation_angle_rad=0.25,
        full_bounding_rect=(1, 2, 30, 40),
        crop_rect=(5, 6, 20, 30),
        crop_padding_px=8,
        rotated_crop_offset_px=(5, 6),
        full_rotated_shape=(40, 30),
        rotated_shape=(30, 20),
    ).to_stage_record()

    assert rotation_record.stage_name == "room_rotation"
    assert rotation_record.summary["full_bounding_rect"] == [1, 2, 30, 40]
    assert rotation_record.summary["crop_rect"] == [5, 6, 20, 30]
    assert rotation_record.summary["crop_padding_px"] == 8
    assert rotation_record.summary["rotated_crop_offset_px"] == [5, 6]
    assert rotation_record.summary["full_rotated_shape"] == [40, 30]
    assert rotation_record.summary["rotated_shape"] == [30, 20]

    direction_record = LocalDirectionFieldStageSummary(
        source="external_axis",
        enabled=True,
        mean_confidence=0.75,
        external_guidance_inputs={
            "has_axis_direction_map": True,
            "has_axis_confidence_map": False,
            "axis_blend_with_image_gradient": True,
            "has_edge_label_map": True,
            "has_junction_label_map": False,
        },
    ).to_stage_record()

    assert direction_record.stage_name == "local_direction_field"
    assert direction_record.summary["external_guidance_inputs"]["has_axis_direction_map"] is True
    assert direction_record.summary["external_guidance_inputs"]["axis_blend_with_image_gradient"] is True

    graph_record = CoverageGraphStageSummary(
        graph_summary={"cell_count": 20, "accessible_cell_count": 18},
        node_generation_mode="turn_cost_repaired_grid",
        node_generation_profile={
            "profile_id": "turn_cost_repaired_grid_v1",
            "strategy": "regular_grid_with_bounded_repair",
        },
        coverage_width_px=10,
        rotated_min_room_px=(2, 3),
        rotated_max_room_px=(40, 50),
    ).to_stage_record()

    assert graph_record.stage_name == "coverage_graph_build"
    assert graph_record.summary["cell_count"] == 20
    assert graph_record.summary["node_generation_profile"]["profile_id"] == "turn_cost_repaired_grid_v1"
    assert graph_record.summary["rotated_min_room_px"] == [2, 3]
    assert graph_record.summary["rotated_max_room_px"] == [40, 50]

    start_record = StartCellSelectionStageSummary(
        requested_start_pixel=(5, 6),
        rotated_start_pixel=(7, 8),
        selected_cell_id="r1_c2",
        selected_grid_row=1,
        selected_grid_col=2,
        selected_planning_point_rotated_px=(9, 10),
        distance_to_rotated_start_px=2.5,
    ).to_stage_record()

    assert start_record.stage_name == "start_cell_selection"
    assert start_record.summary["requested_start_pixel"] == [5, 6]
    assert start_record.summary["selected_cell_id"] == "r1_c2"
    assert start_record.summary["selected_planning_point_rotated_px"] == [9, 10]
    assert start_record.summary["distance_to_rotated_start_px"] == 2.5

    traversal_record = GraphTraversalStageSummary(
        move_trace_count=5,
        fallback_event_count=1,
        candidate_decision_event_count=4,
        traversal_state={"remaining_unvisited_count": 0},
        output_point_count=5,
    ).to_stage_record()

    assert traversal_record.stage_name == "graph_traversal"
    assert traversal_record.mutates_path is True
    assert traversal_record.output_point_count == 5
    assert traversal_record.summary["fallback_event_count"] == 1
    assert traversal_record.summary["candidate_decision_event_count"] == 4

    semantic_skipped = SemanticGlobalPathStageSummary(
        enabled=False,
        input_point_count=7,
        output_point_count=7,
        summary={"enabled": False},
    ).to_stage_record()

    assert semantic_skipped.stage_name == "semantic_global_path"
    assert semantic_skipped.status == "skipped"
    assert semantic_skipped.mutates_path is True

    output_record = OutputAssemblyStageSummary(
        input_pose_count=3,
        world_path_count=3,
    ).to_stage_record()

    assert output_record.stage_name == "output_assembly"
    assert output_record.input_point_count == 3
    assert output_record.output_point_count == 3
    assert output_record.summary["world_path_count"] == 3

    artifact_record = ArtifactWriteStageSummary(
        enabled=True,
        output_path="/tmp/artifacts",
    ).to_stage_record()

    assert artifact_record.stage_name == "artifact_write"
    assert artifact_record.status == "completed"
    assert artifact_record.summary == {
        "enabled": True,
        "output_path": "/tmp/artifacts",
    }
