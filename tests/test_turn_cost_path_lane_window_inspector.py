from algorithms.turn_cost_coverage_research.src.diagnostics.path_lane_window_inspector import inspect_lane_issue_window
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import normalize_points


def test_inspect_lane_issue_window_clusters_parallel_lanes() -> None:
    points = normalize_points(
        [
            (5, 10),
            (45, 10),
            (45, 16),
            (5, 16),
            (5, 28),
            (45, 28),
        ]
    )

    inspection = inspect_lane_issue_window(
        points,
        window_id=3,
        bbox_xyxy=(0, 0, 50, 40),
        coverage_width_px=10,
    )

    assert inspection.window_id == 3
    assert inspection.segment_count >= 3
    assert inspection.lane_count >= 3
    assert inspection.gap_count >= 2
    assert inspection.min_gap_px > 0
    assert inspection.rebuild_readiness in {"ready_for_review", "not_ready"}
    assert inspection.lanes[0].point_count >= 2
    assert inspection.lanes[0].fragment_count >= 1


def test_inspect_lane_issue_window_marks_fragmented_lane_not_ready() -> None:
    points = normalize_points(
        [
            (0, 0),
            (20, 0),
            (20, 20),
            (40, 20),
            (40, 0),
            (60, 0),
        ]
    )

    inspection = inspect_lane_issue_window(
        points,
        window_id=4,
        bbox_xyxy=(-5, -5, 65, 25),
        coverage_width_px=10,
    )

    assert inspection.fragmented_lane_count > 0
    assert inspection.max_lane_fragment_count >= 2
    assert "fragmented_lanes_present" in inspection.reasons


def test_inspect_lane_issue_window_attaches_fragment_source_annotations() -> None:
    points = normalize_points(
        [
            (0, 0),
            (20, 0),
            (20, 10),
            (0, 10),
            (0, 20),
            (20, 20),
        ]
    )

    inspection = inspect_lane_issue_window(
        points,
        window_id=5,
        bbox_xyxy=(-5, -5, 25, 25),
        coverage_width_px=10,
        stroke_segments=[
            {
                "stroke_id": 7,
                "start_segment_index": 1,
                "end_segment_index": 1,
                "segment_type": "coverage_core",
                "action_label": "keep",
            },
            {
                "stroke_id": 8,
                "start_segment_index": 3,
                "end_segment_index": 3,
                "segment_type": "fragment",
                "action_label": "unsafe_bad",
            },
        ],
        segment_sources=[
            {
                "segment_index": 1,
                "move_source": "normal_neighbor",
                "edge_role": "coverage_lane",
            },
            {
                "segment_index": 3,
                "move_source": "global_fallback",
                "edge_role": "fallback_transfer",
            },
        ],
    )

    roles = {
        fragment.fragment_role
        for lane in inspection.lanes
        for fragment in lane.fragments
    }
    assert "coverage_core" in roles
    assert "connector_or_transfer" in roles
