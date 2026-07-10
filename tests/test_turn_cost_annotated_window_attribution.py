from algorithms.turn_cost_coverage_research.src.diagnostics.annotated_window_attribution import (
    attribute_annotated_windows,
)


def test_attribute_lane_spacing_window_prioritizes_lane_gap() -> None:
    alignment = {
        "coverage_width_px": 12,
        "windows": [
            {
                "window_id": "问题4",
                "title": "线距窗口",
                "category": "lane_spacing_imbalance",
                "bbox_xyxy": [0, 0, 100, 100],
                "user_observation": "线距不均匀",
                "path_point_index_ranges": [{"start": 10, "end": 20, "count": 11}],
                "path_segment_index_ranges": [{"start": 11, "end": 20, "count": 10}],
                "local_turn_metrics": {"max_turn_deg": 10, "hotspot_point_indices": []},
                "local_segment_metrics": {"long_jump_count": 0, "max_segment_length_px": 12, "infeasible_segment_count": 0},
                "lane_inspection": {
                    "lane_count": 3,
                    "lane_gap_stats": {"gap_count": 2, "min_gap_px": 5.5, "max_gap_px": 17.0},
                },
                "matched_strokes": [],
                "matched_optimization_candidates": [],
            }
        ],
    }

    result = attribute_annotated_windows(alignment)

    window = result["windows"][0]
    assert window["attribution"]["primary"] == "lane 横向间距异常"
    assert window["attribution"]["confidence"] == "high"
    assert window["signals"]["dense_lane_gap"] is True
    assert window["signals"]["sparse_lane_gap"] is True


def test_attribute_messy_window_selects_suspicious_strokes_and_candidates() -> None:
    alignment = {
        "coverage_width_px": 12,
        "windows": [
            {
                "window_id": "问题2",
                "title": "乱线窗口",
                "category": "local_messy_lines",
                "bbox_xyxy": [0, 0, 100, 100],
                "user_observation": "局部乱线",
                "path_point_index_ranges": [
                    {"start": 1, "end": 3, "count": 3},
                    {"start": 20, "end": 22, "count": 3},
                    {"start": 50, "end": 55, "count": 6},
                ],
                "path_segment_index_ranges": [{"start": 2, "end": 4, "count": 3}],
                "local_turn_metrics": {"max_turn_deg": 85, "hotspot_point_indices": [2, 21, 52]},
                "local_segment_metrics": {"long_jump_count": 1, "max_segment_length_px": 70, "infeasible_segment_count": 2},
                "lane_inspection": {
                    "lane_count": 2,
                    "lane_gap_stats": {"gap_count": 1, "min_gap_px": 9.0, "max_gap_px": 9.0},
                },
                "matched_strokes": [
                    {
                        "stroke_id": 8,
                        "segment_type": "fragment",
                        "action_label": "unsafe_bad",
                        "classification": "bad",
                        "point_index_range": {"start": 20, "end": 21},
                        "segment_index_range": {"start": 21, "end": 21},
                        "reasons": ["high_risk_crossing_present"],
                        "metrics": {
                            "high_risk_crossing_count": 2,
                            "crossing_count": 3,
                            "infeasible_segment_count": 1,
                            "total_turn_deg": 90,
                        },
                    }
                ],
                "matched_optimization_candidates": [
                    {
                        "candidate_id": 5,
                        "stroke_id": 8,
                        "candidate_kind": "crossing_reconnect",
                        "classification": "bad",
                        "point_index_range": {"start": 20, "end": 21},
                        "segment_index_range": {"start": 21, "end": 21},
                    }
                ],
            }
        ],
    }

    result = attribute_annotated_windows(alignment)

    window = result["windows"][0]
    assert window["attribution"]["primary"] == "交叉/重访组织风险"
    assert window["signals"]["disjoint_path_visit_count"] == 3
    assert window["suspicious_strokes"][0]["stroke_id"] == 8
    assert window["suspicious_candidates"][0]["candidate_id"] == 5
    assert "不能把多个不连续 path visit 合成单个连续重连窗口" in window["next_step_boundary"]["forbidden"]

