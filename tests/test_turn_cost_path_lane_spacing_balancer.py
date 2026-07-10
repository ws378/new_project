import numpy as np

from algorithms.turn_cost_coverage_research.src.experiments.path_lane_spacing_balancer import (
    LaneBalanceConfig,
    balance_lane_spacing,
)
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import normalize_points


def test_balance_lane_spacing_shifts_local_middle_lane() -> None:
    free_mask = np.full((80, 80), 255, dtype=np.uint8)
    points = normalize_points(
        [
            (5, 10),
            (45, 10),
            (45, 14),
            (5, 14),
            (5, 30),
            (45, 30),
        ]
    )

    result = balance_lane_spacing(
        points,
        free_mask,
        LaneBalanceConfig(
            coverage_width_px=10,
            resolution_m_per_px=0.05,
            max_coverage_drop_ratio=0.01,
            min_window_issue_count=1,
            max_windows=1,
            min_improvement_dense_count=1,
        ),
    )

    assert result.accepted_window_count == 1
    assert result.after_lane_spacing["median_nearest_spacing_px"] > result.before_lane_spacing["median_nearest_spacing_px"]
    assert result.after_lane_spacing["over_dense_count"] < result.before_lane_spacing["over_dense_count"]
    assert "before_lane_balance" in result.to_dict()
    assert "after_lane_balance" in result.to_dict()
    assert result.points[2][1] > points[2][1]
    assert result.points[3][1] > points[3][1]


def test_balance_lane_spacing_rejects_when_no_lane_structure() -> None:
    free_mask = np.full((80, 80), 255, dtype=np.uint8)
    points = normalize_points([(5, 10), (45, 10), (45, 14)])

    result = balance_lane_spacing(
        points,
        free_mask,
        LaneBalanceConfig(
            coverage_width_px=10,
            resolution_m_per_px=0.05,
            min_window_issue_count=1,
            max_windows=1,
        ),
    )

    assert result.accepted_window_count == 0
    assert result.points == points
