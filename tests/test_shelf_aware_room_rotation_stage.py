from __future__ import annotations

import numpy as np

from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.room_rotation import (
    rotate_room_stage,
)


def test_rotate_room_stage_wraps_rotation_and_trace(monkeypatch):
    room_map = np.zeros((3, 4), dtype=np.uint8)
    rotation_matrix = np.array([[1.0, 0.0, 2.0], [0.0, 1.0, 3.0]], dtype=np.float32)
    rotated_room_map = np.zeros((5, 6), dtype=np.uint8)
    rotated_room_map[2:4, 3:5] = 255
    calls = []

    def fake_compute(input_map, map_resolution):
        calls.append(("compute", input_map, map_resolution))
        return 0.25, rotation_matrix, (1, 2, 6, 5)

    def fake_rotate(input_map, matrix, bounding_rect):
        calls.append(("rotate", input_map, matrix, bounding_rect))
        return rotated_room_map

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.room_rotation.compute_room_rotation",
        fake_compute,
    )
    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.room_rotation.rotate_room",
        fake_rotate,
    )

    result = rotate_room_stage(planning_room_map=room_map, map_resolution=0.05, crop_padding_px=0)

    assert calls == [
        ("compute", room_map, 0.05),
        ("rotate", room_map, rotation_matrix, (1, 2, 6, 5)),
    ]
    assert result.rotation_angle_rad == 0.25
    np.testing.assert_allclose(result.full_rotation_matrix, rotation_matrix)
    np.testing.assert_allclose(result.rotation_matrix, np.array([[1.0, 0.0, -1.0], [0.0, 1.0, 1.0]], dtype=np.float32))
    np.testing.assert_allclose(result.inverse_rotation, np.array([[1.0, 0.0, 1.0], [0.0, 1.0, -1.0]], dtype=np.float32))
    assert result.full_bounding_rect == (1, 2, 6, 5)
    assert result.bounding_rect == (0, 0, 2, 2)
    assert result.crop_rect == (3, 2, 2, 2)
    assert result.rotated_crop_offset_px == (3, 2)
    assert result.full_rotated_shape == (5, 6)
    assert result.rotated_room_map.shape == (2, 2)
    assert np.all(result.rotated_room_map == 255)
    assert result.frame_id == "cropped_rotated_room"
    assert result.stage_record.stage_name == "room_rotation"
    assert result.stage_record.summary["rotation_angle_rad"] == 0.25
    assert result.stage_record.summary["full_bounding_rect"] == [1, 2, 6, 5]
    assert result.stage_record.summary["crop_rect"] == [3, 2, 2, 2]
    assert result.stage_record.summary["rotated_crop_offset_px"] == [3, 2]
    assert result.stage_record.summary["full_rotated_shape"] == [5, 6]
    assert result.stage_record.summary["rotated_shape"] == [2, 2]
    original_point = np.array([[[4.0, 5.0]]], dtype=np.float32)
    cropped_point = np.array([[[3.0, 6.0]]], dtype=np.float32)
    np.testing.assert_allclose(
        np.array([cropped_point[0, 0]]),
        np.array([[
            result.rotation_matrix[0, 0] * original_point[0, 0, 0]
            + result.rotation_matrix[0, 1] * original_point[0, 0, 1]
            + result.rotation_matrix[0, 2],
            result.rotation_matrix[1, 0] * original_point[0, 0, 0]
            + result.rotation_matrix[1, 1] * original_point[0, 0, 1]
            + result.rotation_matrix[1, 2],
        ]]),
    )
    restored_x = result.inverse_rotation[0, 0] * cropped_point[0, 0, 0] + result.inverse_rotation[0, 1] * cropped_point[0, 0, 1] + result.inverse_rotation[0, 2]
    restored_y = result.inverse_rotation[1, 0] * cropped_point[0, 0, 0] + result.inverse_rotation[1, 1] * cropped_point[0, 0, 1] + result.inverse_rotation[1, 2]
    np.testing.assert_allclose(np.array([restored_x, restored_y]), original_point[0, 0])
