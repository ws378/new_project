from algorithms.turn_cost_coverage_research.src.experiments.path_lane_family_blocker_attribution import (
    attribute_blocked_gaps,
)


def test_attribute_blocked_gap_uses_direct_provenance_for_connector() -> None:
    plan_summary = {
        "plans": [
            {
                "window_id": 1,
                "lane_plans": [
                    {
                        "lane_id": 1,
                        "movable": False,
                        "reject_reasons": ["non_coverage_core_fragment"],
                        "fragment_roles": ["connector_or_transfer"],
                        "stroke_ids": [10],
                        "segment_index_ranges": [[4, 4]],
                    },
                    {
                        "lane_id": 2,
                        "movable": True,
                        "reject_reasons": [],
                        "fragment_roles": ["coverage_core"],
                        "stroke_ids": [11],
                        "segment_index_ranges": [[5, 5]],
                    },
                ],
                "gap_plans": [
                    {
                        "left_lane_id": 1,
                        "right_lane_id": 2,
                        "before_kind": "over_dense",
                        "after_kind": "over_dense",
                        "before_gap_px": 4.0,
                        "after_gap_px": 4.0,
                    }
                ],
            }
        ]
    }
    inspection_summary = {
        "inspections": [
            {
                "window_id": 1,
                "lanes": [
                    {
                        "lane_id": 1,
                        "fragments": [
                            {
                                "fragment_role": "connector_or_transfer",
                                "move_source_counts": {"global_fallback": 1},
                                "edge_role_counts": {"fallback_transfer": 1},
                            }
                        ],
                    },
                    {
                        "lane_id": 2,
                        "fragments": [
                            {
                                "fragment_role": "coverage_core",
                                "move_source_counts": {"normal_neighbor": 1},
                                "edge_role_counts": {"coverage_lane": 1},
                            }
                        ],
                    },
                ],
            }
        ]
    }

    items = attribute_blocked_gaps(plan_summary, inspection_summary)

    assert len(items) == 1
    assert items[0].attribution == "connector_transfer"
    assert items[0].evidence_level == "direct_provenance"
    assert items[0].recommended_next_action == "split_connector_before_rebuild"


def test_attribute_blocked_gap_keeps_shift_limit_separate_from_connector() -> None:
    plan_summary = {
        "plans": [
            {
                "window_id": 2,
                "lane_plans": [
                    {
                        "lane_id": 1,
                        "movable": False,
                        "reject_reasons": ["shift_exceeds_limit"],
                        "fragment_roles": ["coverage_core"],
                    },
                    {
                        "lane_id": 2,
                        "movable": False,
                        "reject_reasons": ["shift_exceeds_limit"],
                        "fragment_roles": ["coverage_core"],
                    },
                ],
                "gap_plans": [
                    {
                        "left_lane_id": 1,
                        "right_lane_id": 2,
                        "before_kind": "over_sparse",
                        "after_kind": "over_sparse",
                    }
                ],
            }
        ]
    }
    inspection_summary = {
        "inspections": [
            {
                "window_id": 2,
                "lanes": [
                    {"lane_id": 1, "fragments": [{"fragment_role": "coverage_core"}]},
                    {"lane_id": 2, "fragments": [{"fragment_role": "coverage_core"}]},
                ],
            }
        ]
    }

    items = attribute_blocked_gaps(plan_summary, inspection_summary)

    assert items[0].attribution == "shift_limit"
    assert items[0].evidence_level == "lane_plan_only"
    assert items[0].recommended_next_action == "shift_limit_requires_retarget"
