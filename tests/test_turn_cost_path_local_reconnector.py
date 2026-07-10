import numpy as np

from algorithms.turn_cost_coverage_research.src.diagnostics.path_diagnostics import diagnose_path
from algorithms.turn_cost_coverage_research.src.experiments.path_local_reconnector import ReconnectConfig, reconnect_long_jumps, turn_aware_astar_bridge
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import normalize_points


def test_reconnect_long_jumps_inserts_safe_bridge() -> None:
    free_mask = np.full((80, 80), 255, dtype=np.uint8)
    points = normalize_points([(10, 10), (65, 10), (65, 20)])

    result = reconnect_long_jumps(
        points,
        free_mask,
        ReconnectConfig(
            coverage_width_px=5,
            resolution_m_per_px=0.1,
            long_jump_factor=4.0,
            turn_penalty_px=1.0,
        ),
    )

    assert result.before_long_jump_count == 1
    assert result.after_long_jump_count == 0
    assert len(result.points) > len(points)
    assert result.attempts[0].status == "reconnected"


def test_reconnect_long_jumps_keeps_failed_obstacle_case() -> None:
    free_mask = np.full((80, 80), 255, dtype=np.uint8)
    free_mask[:, 30:40] = 0
    points = normalize_points([(10, 10), (65, 10)])

    result = reconnect_long_jumps(
        points,
        free_mask,
        ReconnectConfig(
            coverage_width_px=5,
            resolution_m_per_px=0.1,
            long_jump_factor=4.0,
            turn_penalty_px=1.0,
        ),
    )

    assert result.before_long_jump_count == 1
    assert result.after_long_jump_count == 1
    assert result.attempts[0].status == "failed"


def test_reconnect_result_is_accepted_by_diagnostics() -> None:
    free_mask = np.full((100, 100), 255, dtype=np.uint8)
    points = normalize_points([(5, 5), (70, 5), (70, 50)])
    result = reconnect_long_jumps(
        points,
        free_mask,
        ReconnectConfig(
            coverage_width_px=6,
            resolution_m_per_px=0.05,
            long_jump_factor=4.0,
        ),
    )

    diagnostics = diagnose_path(
        result.points,
        resolution_m_per_px=0.05,
        coverage_width_px=6,
        long_jump_factor=4.0,
    )

    assert not diagnostics.long_jumps


def test_turn_aware_astar_bridge_exposes_local_bridge() -> None:
    free_mask = np.full((80, 80), 255, dtype=np.uint8)
    bridge = turn_aware_astar_bridge(
        free_mask,
        (10.0, 10.0),
        (60.0, 10.0),
        config=ReconnectConfig(
            coverage_width_px=5,
            resolution_m_per_px=0.1,
            long_jump_factor=4.0,
            turn_penalty_px=1.0,
        ),
    )

    assert bridge is not None
    assert bridge[0] == (10.0, 10.0)
    assert bridge[-1] == (60.0, 10.0)
