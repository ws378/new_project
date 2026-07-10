from algorithms.turn_cost_coverage_research.src.experiments.path_lane_family_reconstruction import (
    analyze_lane_family_time_groups,
    apply_lane_family_window_plan_to_points,
    evaluate_lane_family_target_strategies,
    generate_lane_family_window_plan,
    rank_lane_family_time_group_candidates,
)


def _lane(lane_id: int, lateral: float, role: str = "coverage_core", point_indices: list[int] | None = None) -> dict:
    return {
        "lane_id": lane_id,
        "lateral_px": lateral,
        "point_indices": point_indices if point_indices is not None else [lane_id * 2, lane_id * 2 + 1],
        "segment_indices": [lane_id],
        "fragments": [
            {
                "fragment_role": role,
                "segment_types": ["coverage_core" if role == "coverage_core" else "fragment"],
                "segment_count": 1,
                "start_segment_index": lane_id,
                "end_segment_index": lane_id,
                "stroke_ids": [lane_id + 10],
                "move_source_counts": {"normal_neighbor": 1},
                "edge_role_counts": {"coverage_lane": 1},
            }
        ],
    }


def _lane_with_fragment(
    lane_id: int,
    lateral: float,
    start: int,
    end: int,
    role: str = "coverage_core",
    stroke_id: int | None = None,
) -> dict:
    return {
        "lane_id": lane_id,
        "lateral_px": lateral,
        "point_indices": [start, end + 1],
        "segment_indices": list(range(start, end + 1)),
        "fragments": [
            {
                "fragment_role": role,
                "segment_types": ["coverage_core" if role == "coverage_core" else "fragment"],
                "segment_count": end - start + 1,
                "start_segment_index": start,
                "end_segment_index": end,
                "point_indices": [start, end + 1],
                "stroke_ids": [stroke_id if stroke_id is not None else lane_id + 10],
                "action_labels": ["local_fix_candidate"],
                "move_source_counts": {"normal_neighbor": end - start + 1},
                "edge_role_counts": {"coverage_lane": end - start + 1},
            }
        ],
    }


def test_generate_lane_family_window_plan_moves_only_coverage_core_lanes() -> None:
    inspection = {
        "window_id": 3,
        "rebuild_readiness": "ready_for_review",
        "recommended_action": "lane_family_reorder_or_rebuild_candidate",
        "lane_count": 4,
        "lanes": [
            _lane(1, 0.0),
            _lane(2, 5.0),
            _lane(3, 30.0, role="connector_or_transfer"),
            _lane(4, 36.0),
        ],
    }

    plan = generate_lane_family_window_plan(
        inspection,
        coverage_width_px=12,
        max_shift_factor=1.0,
    )

    by_id = {lane.lane_id: lane for lane in plan.lane_plans}
    assert plan.status == "candidate_plan"
    assert by_id[2].movable
    assert not by_id[3].movable
    assert by_id[3].lock_reason == "non_coverage_core_fragment"
    assert by_id[3].reject_reasons == ("non_coverage_core_fragment",)
    assert by_id[3].stroke_ids == (13,)
    assert by_id[3].segment_index_ranges == ((3, 3),)
    assert plan.before_bad_gap_count >= plan.after_bad_gap_count
    connector_gap = next(
        gap
        for gap in plan.gap_plans
        if gap.left_lane_id == 2 and gap.right_lane_id == 3
    )
    assert "non_coverage_fragment_adjacent" in connector_gap.blocker_reasons
    assert connector_gap.recommended_next_action == "peel_connector_or_mixed_fragment_first"


def test_generate_lane_family_window_plan_skips_not_ready_window() -> None:
    plan = generate_lane_family_window_plan(
        {
            "window_id": 9,
            "rebuild_readiness": "not_ready",
            "recommended_action": "split_fragments_before_rebuild",
            "lane_count": 5,
            "lanes": [_lane(index, float(index * 10)) for index in range(5)],
        },
        coverage_width_px=12,
    )

    assert plan.status == "skipped"
    assert plan.reason == "inspection_not_ready_for_review"


def test_generate_lane_family_window_plan_rejects_fill_action() -> None:
    plan = generate_lane_family_window_plan(
        {
            "window_id": 11,
            "rebuild_readiness": "ready_for_review",
            "recommended_action": "lane_family_fill_or_preserve_candidate",
            "lane_count": 4,
            "lanes": [_lane(index, float(index * 20)) for index in range(4)],
        },
        coverage_width_px=12,
    )

    assert plan.status == "rejected"
    assert plan.reason == "requires_fill_or_preserve_not_shift"


def test_evaluate_lane_family_target_strategies_reports_each_strategy() -> None:
    inspection = {
        "window_id": 12,
        "rebuild_readiness": "ready_for_review",
        "recommended_action": "lane_family_reorder_or_rebuild_candidate",
        "lane_count": 3,
        "lanes": [
            _lane(1, 0.0),
            _lane(2, 5.0),
            _lane(3, 20.0),
        ],
    }

    evaluations = evaluate_lane_family_target_strategies(
        inspection,
        coverage_width_px=10,
        max_shift_factor=2.0,
        strategies=("preserve_current", "coverage_width_from_first"),
    )

    assert [item.strategy for item in evaluations] == ["preserve_current", "coverage_width_from_first"]
    assert all(item.window_id == 12 for item in evaluations)
    assert evaluations[0].target_laterals_px == (0.0, 5.0, 20.0)
    assert evaluations[1].target_laterals_px == (0.0, 10.0, 20.0)
    assert evaluations[1].prediction_status == "improves_bad_gap_prediction"
    assert evaluations[1].changed_locked_lane_count == 0
    assert evaluations[1].predicted_over_dense_count == 0


def test_apply_lane_family_window_plan_moves_only_movable_lanes() -> None:
    inspection = {
        "window_id": 12,
        "dominant_axis_deg": 0.0,
        "rebuild_readiness": "ready_for_review",
        "recommended_action": "lane_family_reorder_or_rebuild_candidate",
        "lane_count": 3,
        "lanes": [
            _lane(1, 0.0, point_indices=[0]),
            _lane(2, 5.0, point_indices=[1]),
            _lane(3, 20.0, point_indices=[2]),
        ],
    }

    result = apply_lane_family_window_plan_to_points(
        [(0.0, 0.0), (10.0, 5.0), (20.0, 20.0)],
        inspection,
        coverage_width_px=10,
        max_shift_factor=2.0,
        target_strategy="coverage_width_from_first",
    )

    assert result.status == "candidate_path"
    assert result.changed_point_count == 1
    assert result.applied_lanes == (1, 2, 3)
    assert result.points == ((0.0, 0.0), (10.0, 10.0), (20.0, 20.0))


def test_apply_lane_family_window_plan_rejects_conflicting_shared_point() -> None:
    inspection = {
        "window_id": 12,
        "dominant_axis_deg": 0.0,
        "rebuild_readiness": "ready_for_review",
        "recommended_action": "lane_family_reorder_or_rebuild_candidate",
        "lane_count": 3,
        "lanes": [
            _lane(1, 0.0, point_indices=[0]),
            _lane(2, 5.0, point_indices=[1]),
            _lane(3, 20.0, point_indices=[1]),
        ],
    }

    result = apply_lane_family_window_plan_to_points(
        [(0.0, 0.0), (10.0, 5.0)],
        inspection,
        coverage_width_px=10,
        max_shift_factor=2.0,
        target_strategy="coverage_width_from_first",
    )

    assert result.status == "rejected"
    assert result.reason == "conflicting_point_shift"
    assert result.points == ((0.0, 0.0), (10.0, 5.0))


def test_analyze_lane_family_time_groups_splits_non_continuous_segments() -> None:
    inspection = {
        "window_id": 5,
        "lanes": [
            _lane_with_fragment(1, 0.0, 10, 11, stroke_id=1),
            _lane_with_fragment(2, 10.0, 12, 12, stroke_id=1),
            _lane_with_fragment(3, 20.0, 40, 40, stroke_id=9),
        ],
    }

    analysis = analyze_lane_family_time_groups(
        inspection,
        max_segment_gap=2,
        min_segments_for_review=3,
    )

    assert analysis.window_id == 5
    assert analysis.group_count == 3
    assert analysis.review_candidate_count == 0
    assert analysis.full_segment_span == 31
    assert round(analysis.full_segment_density, 3) == 0.129
    assert analysis.groups[0].status == "not_ready"
    assert analysis.groups[0].segment_indices == (10, 11)
    assert analysis.groups[0].next_review_action == "not_rebuildable_temporal_fragment"
    assert analysis.groups[1].status == "not_ready"
    assert analysis.groups[1].reason == "too_few_segments"


def test_analyze_lane_family_time_groups_rejects_non_coverage_group() -> None:
    inspection = {
        "window_id": 6,
        "lanes": [
            _lane_with_fragment(1, 0.0, 10, 11, role="coverage_core"),
            _lane_with_fragment(2, 10.0, 12, 12, role="connector_or_transfer"),
        ],
    }

    analysis = analyze_lane_family_time_groups(
        inspection,
        max_segment_gap=2,
        min_segments_for_review=3,
    )

    assert analysis.status == "no_review_candidate"
    assert analysis.groups[1].status == "review_only"
    assert analysis.groups[1].reason == "contains_connector_or_transfer"


def test_analyze_lane_family_time_groups_marks_long_coverage_fragment_for_review() -> None:
    inspection = {
        "window_id": 7,
        "lanes": [
            _lane_with_fragment(1, 0.0, 10, 13, role="coverage_core"),
        ],
    }

    analysis = analyze_lane_family_time_groups(
        inspection,
        max_segment_gap=2,
        min_segments_for_review=3,
    )

    assert analysis.status == "has_review_candidate"
    assert analysis.review_candidate_count == 1
    assert analysis.groups[0].status == "review_candidate"
    assert analysis.groups[0].next_review_action == "inspect_as_strip_group"
    assert analysis.groups[0].source_evidence_level == "provenance_segment_source"


def test_rank_lane_family_time_group_candidates_penalizes_mixed_adjacency() -> None:
    clean = analyze_lane_family_time_groups(
        {
            "window_id": 1,
            "lanes": [
                _lane_with_fragment(1, 0.0, 10, 15, role="coverage_core"),
            ],
        },
        max_segment_gap=2,
        min_segments_for_review=3,
    )
    mixed_adjacent = analyze_lane_family_time_groups(
        {
            "window_id": 2,
            "lanes": [
                _lane_with_fragment(1, 0.0, 20, 24, role="coverage_core"),
                _lane_with_fragment(2, 10.0, 26, 26, role="connector_or_transfer"),
            ],
        },
        max_segment_gap=2,
        min_segments_for_review=3,
    )

    candidates = rank_lane_family_time_group_candidates(
        [clean.to_dict(), mixed_adjacent.to_dict()],
        adjacency_gap=3,
        min_preferred_segments=5,
    )

    assert [candidate.candidate_rank for candidate in candidates] == [1, 2]
    assert candidates[0].status == "low_risk_strip_review_candidate"
    assert candidates[0].window_id == 1
    assert candidates[1].status == "connector_adjacent_review_candidate"
    assert candidates[1].connector_adjacency_count == 1
