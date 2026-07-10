from __future__ import annotations

from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.output_assembly import (
    OutputPathAssemblyInput,
    assemble_world_path,
)


def test_assemble_world_path_converts_pixel_pose_to_world_path():
    result = assemble_world_path(
        OutputPathAssemblyInput(
            pixel_poses=[(2.0, 3.0, 0.5), (4.0, 1.0, -1.0)],
            map_resolution=0.25,
            map_origin=(10.0, -2.0),
            map_height=20,
        )
    )

    assert result.world_path == [
        {"index": 1, "x": 10.5, "y": 2.25, "theta": -0.5},
        {"index": 2, "x": 11.0, "y": 2.75, "theta": 1.0},
    ]
    assert result.stage_record.stage_name == "output_assembly"
    assert result.stage_record.input_point_count == 2
    assert result.stage_record.output_point_count == 2


def test_assemble_world_path_keeps_empty_path_empty():
    result = assemble_world_path(
        OutputPathAssemblyInput(
            pixel_poses=[],
            map_resolution=0.25,
            map_origin=(10.0, -2.0),
            map_height=20,
        )
    )

    assert result.world_path == []
    assert result.stage_record.stage_name == "output_assembly"
    assert result.stage_record.output_point_count == 0
