import numpy as np

from algorithms.turn_cost_coverage_research.src.experiments.path_quality_guarded_optimizer import (
    QualityGuardedConfig,
    quality_guarded_simplify_path,
)
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import normalize_points


def test_quality_guarded_simplify_removes_redundant_point_without_local_quality_loss() -> None:
    free_mask = np.zeros((80, 80), dtype=np.uint8)
    free_mask[6:16, 5:75] = 255
    points = normalize_points([(10, 10), (20, 12), (30, 10), (70, 10)])

    result = quality_guarded_simplify_path(
        points,
        free_mask,
        QualityGuardedConfig(
            coverage_width_px=12,
            max_coverage_drop_ratio=0.2,
            max_narrow_coverage_drop_ratio=0.2,
            min_score_improvement=0.0,
        ),
    )

    assert result.accepted_count >= 1
    assert result.after_metrics.point_count < result.before_metrics.point_count
    assert result.after_quality.uncovered_component_count <= result.before_quality.uncovered_component_count


def test_quality_guarded_simplify_rejects_uncovered_component_regression() -> None:
    free_mask = np.zeros((50, 90), dtype=np.uint8)
    free_mask[20:30, 5:85] = 255
    points = normalize_points([(10, 25), (45, 25), (80, 25)])

    result = quality_guarded_simplify_path(
        points,
        free_mask,
        QualityGuardedConfig(
            coverage_width_px=5,
            max_coverage_drop_ratio=1.0,
            max_narrow_coverage_drop_ratio=1.0,
            min_score_improvement=0.0,
        ),
    )

    assert result.after_quality.uncovered_component_count <= result.before_quality.uncovered_component_count


def test_quality_guarded_simplify_does_not_increase_long_jumps() -> None:
    free_mask = np.full((120, 120), 255, dtype=np.uint8)
    points = normalize_points([(10, 10), (10, 45), (10, 80), (90, 80), (95, 85)])

    result = quality_guarded_simplify_path(
        points,
        free_mask,
        QualityGuardedConfig(
            coverage_width_px=10,
            max_coverage_drop_ratio=1.0,
            max_narrow_coverage_drop_ratio=1.0,
            min_score_improvement=0.0,
        ),
    )

    assert result.after_metrics.long_jump_count <= result.before_metrics.long_jump_count
    assert result.after_metrics.max_segment_px <= result.before_metrics.max_segment_px
