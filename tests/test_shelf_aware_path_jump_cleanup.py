from algorithms.coverage_planning.planners.shelf_aware_guarded.final_path.jump_cleanup import (
    IsolatedJumpCleanupConfig,
    cleanup_isolated_jump_fragments,
)


def test_cleanup_deletes_isolated_fragment_when_reinsert_is_not_close():
    path = [
        (0.0, 0.0),
        (1.0, 0.0),
        (100.0, 100.0),
        (101.0, 100.0),
        (2.0, 0.0),
        (3.0, 0.0),
    ]

    result = cleanup_isolated_jump_fragments(
        path,
        resolution_m_per_px=1.0,
        config=IsolatedJumpCleanupConfig(
            enable=True,
            jump_distance_m=10.0,
            max_isolated_points=2,
            max_isolated_length_m=2.0,
            reinsert_max_distance_m=3.0,
            reinsert_improvement_ratio=0.8,
        ),
    )

    assert result.path_points == [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]
    assert len(result.inactive_fragments) == 1
    assert result.inactive_fragments[0].reason == "长跳后的孤立片段无法重插"
    assert result.reinserted_fragments == ()


def test_cleanup_reinserts_isolated_fragment_when_it_belongs_near_later_path():
    path = [
        (0.0, 0.0),
        (1.0, 0.0),
        (10.0, 10.0),
        (10.5, 10.0),
        (2.0, 0.0),
        (3.0, 0.0),
        (4.0, 0.0),
        (5.0, 0.0),
        (6.0, 0.0),
        (10.0, 9.0),
        (11.0, 9.0),
    ]

    result = cleanup_isolated_jump_fragments(
        path,
        resolution_m_per_px=1.0,
        config=IsolatedJumpCleanupConfig(
            enable=True,
            jump_distance_m=5.0,
            max_isolated_points=2,
            max_isolated_length_m=2.0,
            reinsert_max_distance_m=2.0,
            reinsert_improvement_ratio=0.8,
        ),
    )

    assert result.path_points == [
        (0.0, 0.0),
        (1.0, 0.0),
        (2.0, 0.0),
        (3.0, 0.0),
        (4.0, 0.0),
        (5.0, 0.0),
        (6.0, 0.0),
        (10.0, 9.0),
        (10.0, 10.0),
        (10.5, 10.0),
        (11.0, 9.0),
    ]
    assert result.inactive_fragments == ()
    assert len(result.reinserted_fragments) == 1


def test_cleanup_disabled_keeps_path_unchanged():
    path = [(0.0, 0.0), (100.0, 100.0), (1.0, 0.0)]

    result = cleanup_isolated_jump_fragments(
        path,
        resolution_m_per_px=1.0,
        config=IsolatedJumpCleanupConfig(enable=False),
    )

    assert result.path_points == path
    assert result.changed is False
