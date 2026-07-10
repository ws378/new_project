import numpy as np
import pytest

from algorithms.coverage_planning.quality_guard import (
    PathQualityGuardConfig,
    evaluate_path_quality_guard,
)


def test_quality_guard_passes_simple_dense_path():
    free_mask = np.ones((30, 30), dtype=np.uint8) * 255
    path_pixels = (
        (5.0, 5.0),
        (15.0, 5.0),
        (25.0, 5.0),
        (25.0, 15.0),
        (25.0, 25.0),
        (15.0, 25.0),
        (5.0, 25.0),
    )

    result = evaluate_path_quality_guard(
        free_mask,
        path_pixels,
        PathQualityGuardConfig(
            coverage_width_m=0.5,
            resolution_m_per_px=0.05,
            min_coverage_ratio=0.5,
        ),
    )

    assert result.passed
    assert result.status == "pass"
    assert result.coverage_ratio >= 0.5
    assert result.infeasible_segment_count == 0


def test_quality_guard_warns_on_cross_obstacle_segment():
    free_mask = np.ones((30, 30), dtype=np.uint8) * 255
    free_mask[10:20, 14:17] = 0

    result = evaluate_path_quality_guard(
        free_mask,
        ((5.0, 15.0), (25.0, 15.0)),
        PathQualityGuardConfig(
            coverage_width_m=0.5,
            resolution_m_per_px=0.05,
            min_coverage_ratio=0.1,
        ),
    )

    assert not result.passed
    assert "infeasible_segment_detected" in result.warnings
    assert result.infeasible_segment_count == 1


def test_quality_guard_warns_on_long_jump():
    free_mask = np.ones((120, 120), dtype=np.uint8) * 255

    result = evaluate_path_quality_guard(
        free_mask,
        ((5.0, 5.0), (100.0, 5.0)),
        PathQualityGuardConfig(
            coverage_width_m=0.5,
            resolution_m_per_px=0.05,
            min_coverage_ratio=0.1,
            long_jump_factor=4.0,
        ),
    )

    assert not result.passed
    assert "long_jump_detected" in result.warnings
    assert result.long_jump_count == 1


def test_quality_guard_warns_on_path_too_short():
    result = evaluate_path_quality_guard(
        np.ones((10, 10), dtype=np.uint8) * 255,
        ((5.0, 5.0),),
        PathQualityGuardConfig(
            coverage_width_m=0.5,
            resolution_m_per_px=0.05,
            min_coverage_ratio=0.0,
        ),
    )

    assert not result.passed
    assert "path_too_short" in result.warnings


def test_quality_guard_rejects_invalid_resolution():
    with pytest.raises(ValueError, match="resolution_m_per_px"):
        evaluate_path_quality_guard(
            np.ones((10, 10), dtype=np.uint8) * 255,
            ((1.0, 1.0), (2.0, 2.0)),
            PathQualityGuardConfig(
                coverage_width_m=0.5,
                resolution_m_per_px=0.0,
            ),
        )
