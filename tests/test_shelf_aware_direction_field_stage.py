from __future__ import annotations

import numpy as np
import pytest

from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.direction_field import (
    build_direction_field_stage,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import (
    PlannerConfig,
)


def test_direction_field_stage_resolves_direction_and_rotates_external_edge_labels(monkeypatch):
    planning_room_map = np.zeros((3, 4), dtype=np.uint8)
    planning_room_map[:, :] = 255
    rotated_room_map = np.zeros((2, 5), dtype=np.uint8)
    rotated_room_map[:, 1:4] = 255
    rotation_matrix = np.array([[1.0, 0.0, 1.0], [0.0, 1.0, 2.0]], dtype=np.float32)
    local_direction_map = np.full(rotated_room_map.shape, 0.5, dtype=np.float32)
    local_confidence = np.zeros(rotated_room_map.shape, dtype=np.float32)
    local_confidence[rotated_room_map == 255] = 0.8
    rotated_edge_labels = np.full(rotated_room_map.shape, 7, dtype=np.int32)
    config = PlannerConfig()
    config.external_edge_label_map = np.ones(planning_room_map.shape, dtype=np.float32)
    config.external_junction_label_map = np.ones(planning_room_map.shape, dtype=np.int32)
    config.external_axis_direction_map = np.ones(planning_room_map.shape, dtype=np.float32)
    config.external_axis_confidence_map = np.ones(planning_room_map.shape, dtype=np.float32)
    config.external_axis_blend_with_image_gradient = True
    calls = []

    def fake_resolve(**kwargs):
        calls.append(("resolve", kwargs))
        return local_direction_map, local_confidence, "external_axis"

    def fake_rotate(**kwargs):
        calls.append(("rotate_edge", kwargs))
        return rotated_edge_labels

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.direction_field.resolve_local_direction_maps",
        fake_resolve,
    )
    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.direction_field.rotate_external_edge_label_map",
        fake_rotate,
    )

    result = build_direction_field_stage(
        planning_room_map=planning_room_map,
        rotated_room_map=rotated_room_map,
        rotation_matrix=rotation_matrix,
        bounding_rect=(0, 0, 5, 2),
        coverage_width_px=6,
        config=config,
    )

    assert calls[0][0] == "resolve"
    assert calls[0][1]["room_map"] is planning_room_map
    assert calls[0][1]["rotated_room_map"] is rotated_room_map
    assert calls[0][1]["rotation_matrix"] is rotation_matrix
    assert calls[0][1]["bounding_rect"] == (0, 0, 5, 2)
    assert calls[0][1]["coverage_width_px"] == 6
    assert calls[0][1]["config"] is config
    assert calls[1][0] == "rotate_edge"
    assert np.array_equal(calls[1][1]["edge_label_map"], config.external_edge_label_map)
    assert calls[1][1]["edge_label_map"].dtype == np.int32
    assert calls[1][1]["rotation_matrix"] is rotation_matrix
    assert calls[1][1]["bounding_rect"] == (0, 0, 5, 2)
    assert calls[1][1]["rotated_room_map"] is rotated_room_map
    assert result.local_direction_map is local_direction_map
    assert result.local_direction_confidence is local_confidence
    assert result.local_direction_source == "external_axis"
    assert result.rotated_edge_label_map is rotated_edge_labels
    assert result.stage_record.stage_name == "local_direction_field"
    assert result.stage_record.summary["source"] == "external_axis"
    assert result.stage_record.summary["mean_confidence"] == pytest.approx(0.8)
    assert result.stage_record.summary["external_guidance_inputs"] == {
        "axis_blend_with_image_gradient": True,
        "has_axis_confidence_map": True,
        "has_axis_direction_map": True,
        "has_edge_label_map": True,
        "has_junction_label_map": True,
    }


def test_direction_field_stage_rejects_edge_label_shape_mismatch(monkeypatch):
    planning_room_map = np.zeros((3, 4), dtype=np.uint8)
    rotated_room_map = np.zeros((3, 4), dtype=np.uint8)
    config = PlannerConfig()
    config.external_edge_label_map = np.ones((2, 4), dtype=np.int32)

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.direction_field.resolve_local_direction_maps",
        lambda **_kwargs: (
            np.zeros(rotated_room_map.shape, dtype=np.float32),
            np.zeros(rotated_room_map.shape, dtype=np.float32),
            "image_gradient",
        ),
    )

    with pytest.raises(ValueError, match="外部边标签图必须与房间地图尺寸一致"):
        build_direction_field_stage(
            planning_room_map=planning_room_map,
            rotated_room_map=rotated_room_map,
            rotation_matrix=np.eye(2, 3, dtype=np.float32),
            bounding_rect=(0, 0, 4, 3),
            coverage_width_px=6,
            config=config,
        )


def test_direction_field_stage_rotates_external_edge_labels_into_cropped_frame(monkeypatch):
    planning_room_map = np.full((8, 8), 255, dtype=np.uint8)
    rotated_room_map = np.full((4, 4), 255, dtype=np.uint8)
    external_edge_labels = np.full(planning_room_map.shape, -1, dtype=np.int32)
    external_edge_labels[3, 4] = 9
    config = PlannerConfig()
    config.external_edge_label_map = external_edge_labels

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.direction_field.resolve_local_direction_maps",
        lambda **_kwargs: (
            np.zeros(rotated_room_map.shape, dtype=np.float32),
            np.ones(rotated_room_map.shape, dtype=np.float32),
            "image_gradient",
        ),
    )

    result = build_direction_field_stage(
        planning_room_map=planning_room_map,
        rotated_room_map=rotated_room_map,
        rotation_matrix=np.array([[1.0, 0.0, -3.0], [0.0, 1.0, -2.0]], dtype=np.float32),
        bounding_rect=(0, 0, 4, 4),
        coverage_width_px=6,
        config=config,
    )

    assert result.rotated_edge_label_map is not None
    assert result.rotated_edge_label_map[1, 1] == 9
    assert result.rotated_edge_label_map.shape == rotated_room_map.shape
