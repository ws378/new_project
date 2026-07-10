from __future__ import annotations

import math

import pytest

from algorithms.coverage_planning.planners.shelf_aware_guarded.models import (
    StrategyConfig,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_history_clearance import (
    HistoryClearanceIndex,
    build_history_clearance_index,
)


def test_history_clearance_index_skips_recent_points_and_returns_infinity_when_empty() -> None:
    short_path = [(float(index), 0.0) for index in range(12)]
    index = HistoryClearanceIndex(short_path, clearance_limit_px=4.0)

    assert index.cells == {}
    assert math.isinf(index.min_distance((0.0, 0.0)))


def test_history_clearance_index_uses_bucketed_points_and_incremental_add() -> None:
    path = [(float(index), 0.0) for index in range(15)]
    index = HistoryClearanceIndex(path, clearance_limit_px=4.0)

    assert index.min_distance((1.5, 0.0)) == pytest.approx(0.5)
    assert math.isinf(index.min_distance((14.0, 0.0)))

    index.add_point((12.0, 0.0))

    assert index.min_distance((14.0, 0.0)) == 2.0


def test_history_clearance_index_checks_neighbor_buckets() -> None:
    index = HistoryClearanceIndex([], clearance_limit_px=4.0)

    index.add_point((3.9, 0.0))

    assert index.min_distance((4.1, 0.0)) == pytest.approx(0.2)


def test_history_clearance_index_cell_size_has_one_pixel_lower_bound() -> None:
    index = HistoryClearanceIndex([], clearance_limit_px=0.25)

    assert index.cell_size_px == 1.0


def test_build_history_clearance_index_respects_weight_and_radius_factor() -> None:
    disabled = StrategyConfig(history_clearance_weight=0.0)

    assert build_history_clearance_index([(0.0, 0.0)], 10, disabled) is None

    enabled = StrategyConfig(
        history_clearance_weight=1.0,
        history_clearance_radius_factor=2.5,
    )
    index = build_history_clearance_index([(float(index), 0.0) for index in range(13)], 10, enabled)

    assert isinstance(index, HistoryClearanceIndex)
    assert index.clearance_limit_px == 25.0
    assert index.cell_size_px == 25.0
