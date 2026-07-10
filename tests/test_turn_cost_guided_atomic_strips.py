from __future__ import annotations

import math

import pytest

from algorithms.turn_cost_coverage_research.src.guidance import CorridorAxisAtomicStrips, axis_angle_distance_rad


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (0.0, 0.0, 0.0),
        (0.0, math.pi, 0.0),
        (0.0, 0.5 * math.pi, 0.5 * math.pi),
        (0.1, math.pi - 0.1, 0.2),
    ],
)
def test_axis_angle_distance_rad_uses_undirected_axis(a: float, b: float, expected: float) -> None:
    assert axis_angle_distance_rad(a, b) == pytest.approx(expected)


@pytest.mark.parametrize("primary_orientation_count", [0, 4])
def test_corridor_axis_atomic_strips_rejects_invalid_primary_count(primary_orientation_count: int) -> None:
    with pytest.raises(ValueError, match="primary_orientation_count"):
        CorridorAxisAtomicStrips(
            number_of_different_orientations=3,
            repetition_of_each_orientation=2,
            guidance_field=None,  # type: ignore[arg-type]
            min_confidence=0.60,
            primary_orientation_count=primary_orientation_count,
        )
