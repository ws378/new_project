from __future__ import annotations

import numpy as np
import pytest

from algorithms.turn_cost_coverage_research.src.guidance import (
    MAPTOOLS_CROP_METER_FRAME,
    MAPTOOLS_CROP_TRANSFORM,
    GuidanceField,
    query_vertex_direction,
)


class _Point:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


class _Vertex:
    def __init__(self, x: float, y: float) -> None:
        self.point = _Point(x, y)


def _field(**overrides: object) -> GuidanceField:
    direction = np.zeros((6, 7), dtype=np.float32)
    confidence = np.zeros((6, 7), dtype=np.float32)
    direction[3, 2] = 1.25
    confidence[3, 2] = 0.9
    values = {
        "direction_rad_map": direction,
        "confidence_map": confidence,
        "resolution_m_per_px": 0.1,
        "frame_id": MAPTOOLS_CROP_METER_FRAME,
        "map_shape_rc": (6, 7),
        "origin_rc": (0, 0),
        "crop_box_px": (1, 2, 8, 9),
        "coordinate_transform": MAPTOOLS_CROP_TRANSFORM,
        "source": "test",
        "metadata": {},
    }
    values.update(overrides)
    return GuidanceField(**values)


def test_query_vertex_direction_maps_crop_meter_frame_to_row_col() -> None:
    hint, status = query_vertex_direction(_Vertex(0.2, -0.3), _field(), min_confidence=0.08)

    assert status.status == "hit"
    assert hint is not None
    assert hint.row == 3
    assert hint.col == 2
    assert hint.preferred_angle_rad == 1.25
    assert hint.confidence == pytest.approx(0.9)


def test_query_vertex_direction_fails_closed_on_frame_mismatch() -> None:
    hint, status = query_vertex_direction(
        _Vertex(0.2, -0.3),
        _field(frame_id="global_map_meter_frame"),
        min_confidence=0.08,
    )

    assert hint is None
    assert status.enabled is False
    assert status.status == "disabled_frame_mismatch"


def test_query_vertex_direction_fails_closed_on_transform_mismatch() -> None:
    hint, status = query_vertex_direction(
        _Vertex(0.2, -0.3),
        _field(coordinate_transform="x_col_resolution_y_positive_row_resolution"),
        min_confidence=0.08,
    )

    assert hint is None
    assert status.enabled is False
    assert status.status == "disabled_coordinate_transform_mismatch"


def test_query_vertex_direction_rejects_shape_mismatch() -> None:
    hint, status = query_vertex_direction(
        _Vertex(0.2, -0.3),
        _field(map_shape_rc=(6, 8)),
        min_confidence=0.08,
    )

    assert hint is None
    assert status.enabled is False
    assert status.status == "disabled_direction_shape_mismatch"


def test_query_vertex_direction_returns_skip_status_for_outside_and_low_confidence() -> None:
    outside_hint, outside_status = query_vertex_direction(_Vertex(5.0, -5.0), _field(), min_confidence=0.08)
    low_hint, low_status = query_vertex_direction(_Vertex(0.1, -0.1), _field(), min_confidence=0.08)

    assert outside_hint is None
    assert outside_status.enabled is True
    assert outside_status.status == "outside_map"
    assert low_hint is None
    assert low_status.enabled is True
    assert low_status.status == "below_min_confidence"
