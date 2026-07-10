import numpy as np

from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import (
    SimplifyConfig,
    normalize_points,
    path_metrics,
    simplify_path_turn_cost,
    turn_angle_deg,
)


def test_turn_angle_deg_counts_right_angle() -> None:
    assert turn_angle_deg((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)) == 90.0


def test_path_metrics_counts_length_turn_and_coverage() -> None:
    free_mask = np.full((20, 20), 255, dtype=np.uint8)
    points = normalize_points([(1, 1), (10, 1), (10, 10)])

    metrics = path_metrics(points, free_mask, coverage_width_px=3)

    assert metrics.point_count == 3
    assert metrics.length_px == 18.0
    assert metrics.total_turn_angle_deg == 90.0
    assert metrics.coverage_ratio > 0.0


def test_simplify_path_turn_cost_removes_safe_corner_when_coverage_is_preserved() -> None:
    free_mask = np.full((40, 40), 255, dtype=np.uint8)
    points = normalize_points([(5, 5), (10, 15), (15, 15), (20, 20)])

    result = simplify_path_turn_cost(
        points,
        free_mask,
        SimplifyConfig(
            coverage_width_px=8,
            max_coverage_drop_ratio=0.20,
            min_turn_improvement_deg=0.0,
        ),
    )

    assert result.removed_point_count >= 1
    assert result.after.length_px < result.before.length_px


def test_simplify_path_turn_cost_rejects_shortcut_through_obstacle() -> None:
    free_mask = np.full((40, 40), 255, dtype=np.uint8)
    free_mask[17:23, 17:23] = 0
    points = normalize_points([(5, 20), (15, 10), (25, 20), (35, 20)])

    result = simplify_path_turn_cost(
        points,
        free_mask,
        SimplifyConfig(
            coverage_width_px=4,
            max_coverage_drop_ratio=0.20,
            min_turn_improvement_deg=0.0,
        ),
    )

    assert result.rejected_by_collision_count >= 1


def test_simplify_path_turn_cost_rejects_when_long_jump_would_increase() -> None:
    free_mask = np.full((120, 120), 255, dtype=np.uint8)
    points = normalize_points([(10, 10), (10, 45), (10, 80), (90, 80), (95, 85)])

    result = simplify_path_turn_cost(
        points,
        free_mask,
        SimplifyConfig(
            coverage_width_px=10,
            max_coverage_drop_ratio=1.0,
            min_turn_improvement_deg=0.0,
            long_jump_factor=4.0,
            allow_long_jump_increase=False,
        ),
    )

    assert result.rejected_by_jump_count >= 1
    assert result.after.long_jump_count == result.before.long_jump_count
    assert result.after.max_segment_px <= result.before.max_segment_px
