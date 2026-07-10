from __future__ import annotations

import numpy as np
import pytest

from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.input_validation import (
    validate_planning_input,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import (
    PlannerConfig,
)


def _metadata() -> dict:
    return {
        "resolution": 0.05,
        "origin": [1.0, 2.0, 0.0],
    }


def test_validate_planning_input_records_stage_summary_and_keeps_room_map_reference():
    room_map = np.zeros((4, 5), dtype=np.uint8)
    room_map[1:3, 1:4] = 255
    config = PlannerConfig(
        coverage_width_m=0.63,
        robot_width_m=0.55,
        start_pixel=(2, 2),
    )

    result = validate_planning_input(
        room_map=room_map,
        metadata=_metadata(),
        config=config,
    )

    assert result.map_resolution == 0.05
    assert result.map_origin == (1.0, 2.0)
    assert result.map_height == 4
    assert result.planning_room_map is room_map
    assert result.region_mask is None
    assert result.chosen_start_pixel == (2, 2)
    assert result.coverage_width_px == 12
    assert result.robot_half_width_px == 5.5
    assert result.stage_record.stage_name == "input_validation"
    assert result.stage_record.summary == {
        "free_pixel_count": 6,
        "has_region_mask": False,
        "start_pixel": [2, 2],
        "coverage_width_px": 12,
        "robot_half_width_px": 5.5,
    }


def test_validate_planning_input_normalizes_region_mask_without_changing_old_shape_check():
    room_map = np.full((3, 3), 255, dtype=np.uint8)
    config = PlannerConfig(
        start_pixel=(1, 1),
        region_mask=np.array([[0, 1, 2], [3, 0, 0], [0, 0, 4]], dtype=np.int16),
    )

    result = validate_planning_input(
        room_map=room_map,
        metadata=_metadata(),
        config=config,
    )

    assert result.region_mask is not None
    assert result.region_mask.dtype == np.uint8
    assert result.region_mask.tolist() == [
        [0, 255, 255],
        [255, 0, 0],
        [0, 0, 255],
    ]
    assert result.stage_record.summary["has_region_mask"] is True


def test_validate_planning_input_uses_region_polygon_when_mask_is_absent(monkeypatch):
    room_map = np.full((3, 4), 255, dtype=np.uint8)
    polygon = [(0, 0), (2, 0), (2, 2), (0, 2)]
    expected_mask = np.ones((3, 4), dtype=np.uint8) * 255
    calls: list[tuple[tuple[int, int], list[tuple[int, int]]]] = []

    def fake_polygon_to_mask(shape, region_polygon):
        calls.append((shape, region_polygon))
        return expected_mask

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.input_validation.polygon_to_mask",
        fake_polygon_to_mask,
    )
    config = PlannerConfig(start_pixel=(1, 1), region_polygon=polygon)

    result = validate_planning_input(
        room_map=room_map,
        metadata=_metadata(),
        config=config,
    )

    assert calls == [((3, 4), polygon)]
    assert result.region_mask is expected_mask
    assert result.stage_record.summary["has_region_mask"] is True


def test_validate_planning_input_rejects_region_mask_shape_mismatch():
    room_map = np.full((3, 3), 255, dtype=np.uint8)
    config = PlannerConfig(
        start_pixel=(1, 1),
        region_mask=np.ones((2, 3), dtype=np.uint8),
    )

    with pytest.raises(ValueError, match="区域掩膜必须与房间地图尺寸一致"):
        validate_planning_input(
            room_map=room_map,
            metadata=_metadata(),
            config=config,
        )


def test_validate_planning_input_rejects_room_without_free_space():
    room_map = np.zeros((3, 3), dtype=np.uint8)
    config = PlannerConfig(start_pixel=(1, 1))

    with pytest.raises(ValueError, match="区域内没有可通行空间，无法生成覆盖路径。"):
        validate_planning_input(
            room_map=room_map,
            metadata=_metadata(),
            config=config,
        )


def test_validate_planning_input_rejects_missing_start_pixel_after_free_space_check():
    room_map = np.full((3, 3), 255, dtype=np.uint8)
    config = PlannerConfig(start_pixel=None)

    with pytest.raises(ValueError, match="第一阶段要求手动选择起点，当前未提供起点像素。"):
        validate_planning_input(
            room_map=room_map,
            metadata=_metadata(),
            config=config,
        )


def test_validate_planning_input_rejects_invalid_start_pixel():
    room_map = np.full((3, 3), 255, dtype=np.uint8)
    room_map[1, 1] = 0
    config = PlannerConfig(start_pixel=(1, 1))

    with pytest.raises(ValueError, match="起点不在区域内可通行空间中。"):
        validate_planning_input(
            room_map=room_map,
            metadata=_metadata(),
            config=config,
        )
