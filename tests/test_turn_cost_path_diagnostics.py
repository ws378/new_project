import numpy as np

from algorithms.turn_cost_coverage_research.src.diagnostics.path_diagnostics import (
    diagnose_lane_balance,
    diagnose_lane_spacing,
    diagnose_local_quality,
    diagnose_path,
    diagnose_path_strokes,
    diagnose_segment_crossings,
    draw_lane_balance_overlay,
    draw_lane_spacing_overlay,
    draw_local_quality_overlay,
    draw_path_diagnostic_overlay,
    draw_path_stroke_segments_overlay,
    draw_path_stroke_quality_overlay,
    draw_segment_crossing_overlay,
    group_lane_balance_windows,
    group_lane_spacing_windows,
    group_segment_crossing_windows,
    rasterize_path_visit_count,
    semantic_by_baseline_index,
    select_lane_issue_windows,
    _classify_stroke_type_and_action,
)
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import normalize_points


def test_diagnose_path_reports_long_jump_and_semantics() -> None:
    points = normalize_points([(0, 0), (5, 0), (50, 0), (50, 5)])
    semantics = {
        2: {"node_role": "connector"},
        3: {"node_role": "cover_core"},
    }

    result = diagnose_path(
        points,
        resolution_m_per_px=0.1,
        coverage_width_px=5,
        long_jump_factor=4.0,
        semantic_index=semantics,
    )

    assert result.long_jump_threshold_px == 20.0
    assert len(result.long_jumps) == 1
    assert result.long_jumps[0].start_index == 2
    assert result.long_jumps[0].end_index == 3
    assert result.long_jumps[0].length_m == 4.5
    assert result.long_jumps[0].semantic_start == {"node_role": "connector"}


def test_diagnose_path_reports_turn_hotspot() -> None:
    points = normalize_points([(0, 0), (10, 0), (10, 10), (20, 10)])

    result = diagnose_path(
        points,
        resolution_m_per_px=0.05,
        coverage_width_px=4,
        turn_hotspot_angle_deg=80.0,
    )

    assert len(result.turn_hotspots) == 2
    assert result.turn_hotspots[0].angle_deg == 90.0


def test_semantic_by_baseline_index_uses_formal_payload() -> None:
    payload = {
        "annotated_path": [
            {
                "baseline_index": 7,
                "node_role": "connector",
                "primary_space_type": "junction",
                "primary_territory_label": 3,
                "primary_junction_id": 11,
                "coverage_obligation": 0.2,
                "connectivity_value": 0.9,
            }
        ]
    }

    result = semantic_by_baseline_index(payload)

    assert result[7]["node_role"] == "connector"
    assert result[7]["primary_junction_id"] == 11


def test_draw_path_diagnostic_overlay_writes_image(tmp_path) -> None:
    free_mask = np.full((80, 80), 255, dtype=np.uint8)
    points = normalize_points([(5, 5), (20, 5), (60, 5), (60, 30)])
    diagnostics = diagnose_path(
        points,
        resolution_m_per_px=0.1,
        coverage_width_px=5,
        long_jump_factor=4.0,
        turn_hotspot_angle_deg=70.0,
    )
    out_path = tmp_path / "overlay.png"

    draw_path_diagnostic_overlay(free_mask, points, diagnostics, str(out_path))

    assert out_path.is_file()
    assert out_path.stat().st_size > 0


def test_diagnose_local_quality_reports_uncovered_and_repeated_coverage() -> None:
    free_mask = np.full((60, 60), 255, dtype=np.uint8)
    points = normalize_points([(5, 5), (45, 5), (5, 5), (45, 5)])

    quality = diagnose_local_quality(
        points,
        free_mask,
        coverage_width_px=5,
        uncovered_min_area_px=25,
    )

    assert quality.coverage_ratio < 1.0
    assert quality.uncovered_component_count >= 1
    assert quality.repeated_coverage_pixel_count > 0
    assert quality.over_dense_coverage_pixel_count > 0


def test_diagnose_local_quality_reports_narrow_channel_coverage() -> None:
    free_mask = np.zeros((40, 80), dtype=np.uint8)
    free_mask[15:25, 5:75] = 255
    points = normalize_points([(10, 20), (70, 20)])

    quality = diagnose_local_quality(points, free_mask, coverage_width_px=6)

    assert quality.narrow_free_pixel_count > 0
    assert quality.narrow_coverage_ratio > 0.5


def test_diagnose_local_quality_reports_infeasible_segment() -> None:
    free_mask = np.full((50, 50), 255, dtype=np.uint8)
    free_mask[20:30, 20:30] = 0
    points = normalize_points([(5, 25), (45, 25)])

    quality = diagnose_local_quality(points, free_mask, coverage_width_px=5)

    assert quality.infeasible_segment_count == 1
    assert quality.max_infeasible_segment_length_px == 40.0


def test_rasterize_path_visit_count_counts_revisits() -> None:
    points = normalize_points([(5, 5), (20, 5), (5, 5)])

    visits = rasterize_path_visit_count((30, 30), points, coverage_width_px=3)

    assert visits[5, 10] >= 2


def test_draw_local_quality_overlay_writes_image(tmp_path) -> None:
    free_mask = np.full((40, 40), 255, dtype=np.uint8)
    points = normalize_points([(5, 5), (30, 5)])
    out_path = tmp_path / "local_quality.png"

    draw_local_quality_overlay(free_mask, points, coverage_width_px=5, out_path=str(out_path))

    assert out_path.is_file()
    assert out_path.stat().st_size > 0


def test_diagnose_lane_spacing_reports_over_dense_parallel_lanes() -> None:
    points = normalize_points([(5, 10), (45, 10), (45, 15), (5, 15)])

    result = diagnose_lane_spacing(
        points,
        coverage_width_px=10,
        resolution_m_per_px=0.05,
        min_spacing_factor=0.65,
        max_spacing_factor=1.35,
    )

    assert result.neighbor_found_count >= 2
    assert result.over_dense_count >= 2
    assert result.over_sparse_count == 0


def test_diagnose_lane_spacing_reports_over_sparse_parallel_lanes() -> None:
    points = normalize_points([(5, 10), (45, 10), (45, 28), (5, 28)])

    result = diagnose_lane_spacing(
        points,
        coverage_width_px=10,
        resolution_m_per_px=0.05,
        min_spacing_factor=0.65,
        max_spacing_factor=1.35,
    )

    assert result.neighbor_found_count >= 2
    assert result.over_sparse_count >= 2


def test_draw_lane_spacing_overlay_writes_image(tmp_path) -> None:
    free_mask = np.full((50, 60), 255, dtype=np.uint8)
    points = normalize_points([(5, 10), (45, 10), (45, 15), (5, 15)])
    spacing = diagnose_lane_spacing(points, coverage_width_px=10, resolution_m_per_px=0.05)
    out_path = tmp_path / "lane_spacing.png"

    draw_lane_spacing_overlay(free_mask, points, spacing, out_path=str(out_path))

    assert out_path.is_file()
    assert out_path.stat().st_size > 0


def test_group_lane_spacing_windows_clusters_nearby_issues() -> None:
    points = normalize_points(
        [
            (5, 10),
            (45, 10),
            (45, 15),
            (5, 15),
            (5, 20),
            (45, 20),
        ]
    )
    spacing = diagnose_lane_spacing(points, coverage_width_px=10, resolution_m_per_px=0.05)

    windows = group_lane_spacing_windows(spacing, merge_radius_px=40.0, min_issue_count=2)

    assert windows
    assert windows[0].issue_count >= 2
    assert windows[0].kind in {"over_dense", "over_sparse"}


def test_diagnose_lane_balance_reports_left_right_imbalance() -> None:
    points = normalize_points([(5, 10), (45, 10), (45, 20), (5, 20), (5, 36), (45, 36)])

    result = diagnose_lane_balance(points, coverage_width_px=10, resolution_m_per_px=0.05, imbalance_factor=0.4)

    assert result.both_side_neighbor_count >= 1
    assert result.imbalanced_count >= 1
    assert result.max_imbalance_px >= 6.0
    assert any(issue.kind == "imbalanced" and issue.left_spacing_px is not None and issue.right_spacing_px is not None for issue in result.issues)


def test_diagnose_segment_crossings_reports_non_adjacent_crossing() -> None:
    points = normalize_points([(0, 0), (20, 20), (20, 0), (0, 20)])

    crossings = diagnose_segment_crossings(points, coverage_width_px=5)

    assert crossings.crossing_count == 1
    assert crossings.issues[0].first_segment_index == 1
    assert crossings.issues[0].second_segment_index == 3
    assert crossings.issues[0].point == (10.0, 10.0)


def test_group_segment_crossing_windows_clusters_near_crossings() -> None:
    points = normalize_points([(0, 0), (20, 20), (20, 0), (0, 20), (0, 25), (20, 5)])
    crossings = diagnose_segment_crossings(points, coverage_width_px=5)

    windows = group_segment_crossing_windows(crossings, merge_radius_px=20.0, min_issue_count=1)

    assert windows
    assert windows[0].issue_count >= 1


def test_diagnose_path_strokes_marks_quality_actions() -> None:
    points = normalize_points(
        [
            (0, 0),
            (20, 0),
            (40, 0),
            (40, 20),
            (20, 0),
            (20, 20),
            (40, 0),
        ]
    )
    crossings = diagnose_segment_crossings(points, coverage_width_px=5)
    spacing = diagnose_lane_spacing(points, coverage_width_px=5, resolution_m_per_px=0.05)
    balance = diagnose_lane_balance(points, coverage_width_px=5, resolution_m_per_px=0.05)

    strokes = diagnose_path_strokes(
        points,
        coverage_width_px=5,
        crossings=crossings,
        lane_spacing=spacing,
        lane_balance=balance,
    )

    assert strokes.stroke_count >= 2
    assert strokes.cut_boundaries
    assert strokes.cut_boundaries[0].after_segment_index < len(points) - 1
    assert strokes.good_count >= 1
    assert any(stroke.action_label in {"endpoint_fix_candidate", "local_fix_candidate", "optimize_candidate", "unsafe_bad"} for stroke in strokes.strokes)
    assert strokes.action_label_counts


def test_diagnose_path_strokes_splits_on_turn_delta() -> None:
    # turn_angle_deg 使用方向变化量：近似直行约 0 度，突变到大转折时应截断。
    points = normalize_points([(0, 0), (20, 0), (40, 0), (60, 0), (65, 15), (65, 35)])
    crossings = diagnose_segment_crossings(points, coverage_width_px=5)
    spacing = diagnose_lane_spacing(points, coverage_width_px=5, resolution_m_per_px=0.05)
    balance = diagnose_lane_balance(points, coverage_width_px=5, resolution_m_per_px=0.05)

    strokes = diagnose_path_strokes(
        points,
        coverage_width_px=5,
        crossings=crossings,
        lane_spacing=spacing,
        lane_balance=balance,
        split_turn_deg=80.0,
        split_turn_delta_deg=30.0,
    )

    assert any("turn_delta" in boundary.reasons for boundary in strokes.cut_boundaries)


def test_diagnose_path_strokes_splits_on_window_turn() -> None:
    # 单步转角都不大，但 7 点窗口的整体方向已经明显变化，应能截断。
    points = normalize_points([(0, 0), (20, 0), (40, 0), (60, 5), (75, 20), (85, 40), (90, 65)])
    crossings = diagnose_segment_crossings(points, coverage_width_px=5)
    spacing = diagnose_lane_spacing(points, coverage_width_px=5, resolution_m_per_px=0.05)
    balance = diagnose_lane_balance(points, coverage_width_px=5, resolution_m_per_px=0.05)

    strokes = diagnose_path_strokes(
        points,
        coverage_width_px=5,
        crossings=crossings,
        lane_spacing=spacing,
        lane_balance=balance,
        split_turn_deg=80.0,
        split_turn_delta_deg=80.0,
        split_window_turn_deg=30.0,
        split_window_point_count=7,
    )

    assert any("window_turn" in boundary.reasons for boundary in strokes.cut_boundaries)


def test_diagnose_path_strokes_downgrades_infeasible_keep_candidate() -> None:
    points = normalize_points([(5, 10), (25, 10), (45, 10)])
    free_mask = np.full((30, 60), 255, dtype=np.uint8)
    free_mask[:, 28:34] = 0
    crossings = diagnose_segment_crossings(points, coverage_width_px=5)
    spacing = diagnose_lane_spacing(points, coverage_width_px=5, resolution_m_per_px=0.05)
    balance = diagnose_lane_balance(points, coverage_width_px=5, resolution_m_per_px=0.05)

    strokes = diagnose_path_strokes(
        points,
        coverage_width_px=5,
        crossings=crossings,
        lane_spacing=spacing,
        lane_balance=balance,
        free_mask=free_mask,
    )

    assert strokes.strokes[0].infeasible_segment_count > 0
    assert strokes.strokes[0].action_label in {"optimize_candidate", "unsafe_bad"}


def test_diagnose_path_strokes_does_not_mark_two_point_segment_as_core() -> None:
    points = normalize_points([(0, 0), (30, 0)])
    crossings = diagnose_segment_crossings(points, coverage_width_px=10)
    spacing = diagnose_lane_spacing(points, coverage_width_px=10, resolution_m_per_px=0.05)
    balance = diagnose_lane_balance(points, coverage_width_px=10, resolution_m_per_px=0.05)

    strokes = diagnose_path_strokes(
        points,
        coverage_width_px=10,
        crossings=crossings,
        lane_spacing=spacing,
        lane_balance=balance,
    )

    assert strokes.strokes[0].segment_type == "fragment"
    assert strokes.strokes[0].action_label != "keep"


def test_classify_risky_short_connector_as_unsafe_bad() -> None:
    segment_type, _problem_location, action_label, classification, _score, reasons = _classify_stroke_type_and_action(
        length=38.0,
        coverage_width_px=12,
        point_count=4,
        total_turn=89.0,
        mean_turn=44.5,
        max_turn=80.0,
        crossing_count=1,
        high_risk_count=1,
        connector_like_count=1,
        endpoint_crossing_count=1,
        interior_crossing_count=0,
        infeasible_segment_count=0,
        max_infeasible_segment_length=0.0,
        spacing_count=1,
        balance_count=2,
    )

    assert segment_type == "connector"
    assert action_label == "unsafe_bad"
    assert classification == "bad"
    assert "risky_short_connector" in reasons


def test_classify_smooth_long_core_with_sparse_local_infeasible_is_not_unsafe_bad() -> None:
    segment_type, _problem_location, action_label, classification, _score, reasons = _classify_stroke_type_and_action(
        length=1000.0,
        coverage_width_px=12,
        point_count=80,
        total_turn=380.0,
        mean_turn=5.0,
        max_turn=20.0,
        crossing_count=0,
        high_risk_count=0,
        connector_like_count=0,
        endpoint_crossing_count=0,
        interior_crossing_count=0,
        infeasible_segment_count=8,
        max_infeasible_segment_length=10.0,
        spacing_count=60,
        balance_count=50,
    )

    assert segment_type == "coverage_core"
    assert action_label == "local_fix_candidate"
    assert classification == "uncertain"
    assert "protect_smooth_core_with_local_issue" in reasons


def test_draw_crossing_and_stroke_overlays_write_images(tmp_path) -> None:
    free_mask = np.full((50, 50), 255, dtype=np.uint8)
    points = normalize_points([(0, 0), (20, 20), (20, 0), (0, 20)])
    crossings = diagnose_segment_crossings(points, coverage_width_px=5)
    spacing = diagnose_lane_spacing(points, coverage_width_px=5, resolution_m_per_px=0.05)
    balance = diagnose_lane_balance(points, coverage_width_px=5, resolution_m_per_px=0.05)
    strokes = diagnose_path_strokes(points, coverage_width_px=5, crossings=crossings, lane_spacing=spacing, lane_balance=balance)
    crossing_path = tmp_path / "crossings.png"
    stroke_path = tmp_path / "strokes.png"
    segment_path = tmp_path / "segments.png"

    draw_segment_crossing_overlay(free_mask, points, crossings, out_path=str(crossing_path))
    draw_path_stroke_quality_overlay(free_mask, points, strokes, out_path=str(stroke_path))
    draw_path_stroke_segments_overlay(free_mask, points, strokes, out_path=str(segment_path))

    assert crossing_path.is_file()
    assert stroke_path.is_file()
    assert segment_path.is_file()


def test_diagnose_lane_balance_reports_missing_side() -> None:
    points = normalize_points([(5, 10), (45, 10), (45, 20), (5, 20)])

    result = diagnose_lane_balance(points, coverage_width_px=10, resolution_m_per_px=0.05)

    assert result.missing_left_count + result.missing_right_count >= 2
    assert any(issue.kind in {"missing_left", "missing_right"} for issue in result.issues)


def test_draw_lane_balance_overlay_writes_image(tmp_path) -> None:
    free_mask = np.full((50, 60), 255, dtype=np.uint8)
    points = normalize_points([(5, 10), (45, 10), (45, 20), (5, 20), (5, 36), (45, 36)])
    balance = diagnose_lane_balance(points, coverage_width_px=10, resolution_m_per_px=0.05)
    out_path = tmp_path / "lane_balance.png"

    draw_lane_balance_overlay(free_mask, points, balance, out_path=str(out_path))

    assert out_path.is_file()
    assert out_path.stat().st_size > 0


def test_group_lane_balance_windows_clusters_imbalance_issues() -> None:
    points = normalize_points(
        [
            (5, 10),
            (45, 10),
            (45, 20),
            (5, 20),
            (5, 36),
            (45, 36),
            (45, 46),
            (5, 46),
        ]
    )
    balance = diagnose_lane_balance(points, coverage_width_px=10, resolution_m_per_px=0.05, imbalance_factor=0.4)

    windows = group_lane_balance_windows(balance, merge_radius_px=60.0, min_issue_count=1)

    assert windows
    assert windows[0].kind in {"imbalanced", "missing_left", "missing_right"}
    assert windows[0].issue_count >= 1


def test_select_lane_issue_windows_intersects_spacing_and_balance_windows() -> None:
    points = normalize_points(
        [
            (5, 10),
            (45, 10),
            (45, 14),
            (5, 14),
            (5, 30),
            (45, 30),
        ]
    )
    spacing = diagnose_lane_spacing(points, coverage_width_px=10, resolution_m_per_px=0.05)
    spacing_windows = group_lane_spacing_windows(spacing, merge_radius_px=60.0, min_issue_count=1)
    balance = diagnose_lane_balance(points, coverage_width_px=10, resolution_m_per_px=0.05, imbalance_factor=0.4)
    balance_windows = group_lane_balance_windows(balance, merge_radius_px=60.0, min_issue_count=1)

    issue_windows = select_lane_issue_windows(spacing_windows, balance_windows, centroid_merge_radius_px=60.0)

    assert issue_windows
    assert issue_windows[0].spacing_kind == "over_dense"
    assert issue_windows[0].issue_count_score >= 2
