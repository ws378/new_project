from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from algorithms.turn_cost_coverage_research.src.guidance import (
    MAPTOOLS_CROP_METER_FRAME,
    MAPTOOLS_CROP_TRANSFORM,
)
from algorithms.turn_cost_coverage_research.src.guidance import shelf_direction_adapter


def test_shelf_direction_adapter_records_maptools_crop_frame(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_compute(room_map, coverage_width_px, config):
        calls.append(
            {
                "room_map": room_map,
                "coverage_width_px": coverage_width_px,
                "config": config,
            }
        )
        return (
            np.full(room_map.shape, 0.5, dtype=np.float32),
            np.full(room_map.shape, 0.8, dtype=np.float32),
        )

    monkeypatch.setattr(shelf_direction_adapter, "compute_local_direction_map", fake_compute)
    geometry_result = SimpleNamespace(
        free_mask=np.array([[0, 255, 255], [0, 255, 0]], dtype=np.uint8),
        crop_box_px=(10, 20, 13, 22),
    )

    field = shelf_direction_adapter.build_shelf_direction_guidance(
        geometry_result=geometry_result,
        coverage_width_m=0.4,
        tool_radius_m=0.2,
        official_hex_side_length_m=0.5,
        resolution_m_per_px=0.1,
    )

    assert len(calls) == 1
    assert calls[0]["coverage_width_px"] == 5
    assert field.frame_id == MAPTOOLS_CROP_METER_FRAME
    assert field.coordinate_transform == MAPTOOLS_CROP_TRANSFORM
    assert field.origin_rc == (0, 0)
    assert field.map_shape_rc == geometry_result.free_mask.shape
    assert field.crop_box_px == (10, 20, 13, 22)
    assert field.source == "shelf_aware_local_direction"
    assert field.metadata["official_hex_side_length_m"] == 0.5
    assert field.metadata["coverage_width_px"] == 5
