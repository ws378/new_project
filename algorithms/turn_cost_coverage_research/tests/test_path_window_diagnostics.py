from algorithms.turn_cost_coverage_research.src.diagnostics.path_window_diagnostics import (
    PathWindowDiagnosticConfig,
    compute_window_metrics,
    detect_path_windows,
)


def test_three_point_window_reports_sharp_turn() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    config = PathWindowDiagnosticConfig(resolution_m=0.05, sharp_turn_deg=70.0)

    metrics = compute_window_metrics(points, center_index=1, window_size=3, config=config)

    assert metrics["turn_angle_deg"] == 90.0
    assert "sharp_turn" in metrics["risk_reason"]
    assert metrics["requires_turn_swept_check"] is True


def test_five_point_window_requires_short_alternating_zigzag() -> None:
    points = [(0.0, 0.0), (5.0, 2.0), (10.0, 0.0), (15.0, 2.0), (20.0, 0.0)]
    config = PathWindowDiagnosticConfig(
        resolution_m=0.05,
        straight_angle_tol_deg=10.0,
        zigzag_turn_sum_deg=55.0,
        zigzag_direction_change_max_deg=20.0,
        zigzag_max_window_length_m=2.0,
    )

    metrics = compute_window_metrics(points, center_index=2, window_size=5, config=config)

    assert "short_zigzag" in metrics["risk_reason"]
    assert metrics["window_length_m"] <= config.zigzag_max_window_length_m


def test_seven_point_window_uses_half_window_direction_change() -> None:
    points = [
        (0.0, 0.0),
        (5.0, 0.0),
        (10.0, 0.0),
        (15.0, 0.0),
        (15.0, 5.0),
        (15.0, 10.0),
        (15.0, 15.0),
    ]
    config = PathWindowDiagnosticConfig(resolution_m=0.05, direction_change_deg=45.0)

    metrics = compute_window_metrics(points, center_index=3, window_size=7, config=config)

    assert metrics["direction_change_deg"] == 90.0
    assert "direction_change" in metrics["risk_reason"]


def test_detect_path_windows_keeps_raw_candidates_for_turn_swept_checks() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (20.0, 10.0), (20.0, 20.0)]
    config = PathWindowDiagnosticConfig(resolution_m=0.05, sharp_turn_deg=70.0)

    result = detect_path_windows(points, config)

    assert result["candidate_window_count"] >= result["merged_window_count"]
    assert result["candidate_windows"]
    assert all(item["requires_turn_swept_check"] for item in result["candidate_windows"])
