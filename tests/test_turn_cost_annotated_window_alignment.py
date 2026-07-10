import numpy as np

from algorithms.turn_cost_coverage_research.src.diagnostics.annotated_window_alignment import (
    AnnotatedWindow,
    align_annotated_windows,
    load_annotated_windows,
)
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import normalize_points


def test_load_annotated_windows_validates_bbox() -> None:
    payload = {
        "windows": [
            {
                "window_id": "问题1",
                "title": "问题1",
                "category": "micro_kink",
                "bbox_xyxy": [0, 0, 10, 10],
                "user_observation": "局部小折返",
            }
        ]
    }

    windows = load_annotated_windows(payload)

    assert windows == (
        AnnotatedWindow(
            window_id="问题1",
            title="问题1",
            category="micro_kink",
            bbox_xyxy=(0.0, 0.0, 10.0, 10.0),
            user_observation="局部小折返",
            scope_note="",
            allowed_analysis_scope="",
        ),
    )


def test_align_annotated_windows_reports_path_ranges_and_matches_strokes() -> None:
    points = normalize_points(
        [
            [0, 0],
            [10, 0],
            [20, 0],
            [30, 10],
            [40, 10],
            [50, 10],
        ]
    )
    windows = (
        AnnotatedWindow(
            window_id="窗口A",
            title="窗口A",
            category="local",
            bbox_xyxy=(15.0, -5.0, 42.0, 15.0),
            user_observation="局部窗口",
            scope_note="只读",
            allowed_analysis_scope="对齐",
        ),
    )
    strokes = [
        {
            "stroke_id": 7,
            "segment_type": "coverage_core",
            "action_label": "keep",
            "classification": "good",
            "score": 1.0,
            "reasons": ["coverage_core_shape"],
            "start_point_index": 1,
            "end_point_index": 4,
            "start_segment_index": 2,
            "end_segment_index": 4,
            "point_count": 4,
            "length_px": 34.0,
            "total_turn_deg": 45.0,
            "crossing_count": 0,
            "high_risk_crossing_count": 0,
            "infeasible_segment_count": 0,
            "lane_spacing_issue_count": 1,
            "lane_balance_issue_count": 0,
            "points": [[10, 0], [20, 0], [30, 10], [40, 10]],
        }
    ]
    candidates = [
        {
            "candidate_id": 3,
            "stroke_id": 7,
            "candidate_kind": "turn_cost_local_fix",
            "action_label": "optimize_candidate",
            "segment_type": "connector",
            "classification": "bad",
            "priority_score": 10.0,
            "bbox_xyxy": [18, -2, 35, 12],
            "start_point_index": 2,
            "end_point_index": 3,
            "start_segment_index": 3,
            "end_segment_index": 3,
            "reasons": ["high_turn"],
        }
    ]
    free_mask = np.full((80, 80), 255, dtype=np.uint8)

    result = align_annotated_windows(
        points,
        windows,
        coverage_width_px=10,
        stroke_segments=strokes,
        optimization_candidates=candidates,
        free_mask=free_mask,
    )

    window = result["windows"][0]
    assert window["path_point_index_ranges"] == [{"start": 2, "end": 4, "count": 3}]
    assert window["path_segment_index_ranges"] == [{"start": 2, "end": 4, "count": 3}]
    assert window["matched_strokes"][0]["stroke_id"] == 7
    assert window["matched_optimization_candidates"][0]["candidate_id"] == 3
    assert window["local_turn_metrics"]["hotspot_point_indices"] == [2, 3]
    assert window["local_segment_metrics"]["infeasible_segment_count"] == 0
    assert window["interpretation_boundary"]["forbidden"]

