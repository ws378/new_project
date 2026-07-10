from pathlib import Path

from algorithms.turn_cost_coverage_research.scripts.diagnostics.run_geometry_coverage_plan_comparison import (
    _area_dir_from,
    _planner_run_dir,
)
from algorithms.turn_cost_coverage_research.scripts.diagnostics.run_geometry_coverage_readonly_diagnostic import (
    _aggregate_turn_events_by_merged_windows,
    _exclude_tight_windows_with_collision,
)


def test_planner_run_dir_accepts_area_dir(tmp_path: Path) -> None:
    area_dir = tmp_path / "case_area_1"
    run_dir = area_dir / "planner" / "run_1"
    run_dir.mkdir(parents=True)
    (run_dir / "region_mask.png").write_bytes(b"")
    (run_dir / "path_pixels.json").write_text("[]", encoding="utf-8")
    (area_dir / "preprocess" / "prepare_map").mkdir(parents=True)

    resolved = _planner_run_dir(area_dir)

    assert resolved == run_dir
    assert _area_dir_from(area_dir, resolved) == area_dir


def test_area_dir_from_accepts_specific_planner_run(tmp_path: Path) -> None:
    area_dir = tmp_path / "case_area_1"
    run_dir = area_dir / "planner" / "run_1"
    run_dir.mkdir(parents=True)
    (run_dir / "region_mask.png").write_bytes(b"")
    (run_dir / "path_pixels.json").write_text("[]", encoding="utf-8")

    resolved = _planner_run_dir(run_dir)

    assert resolved == run_dir
    assert _area_dir_from(run_dir, resolved) == area_dir


def test_turn_events_are_aggregated_by_merged_windows() -> None:
    events = [
        {"window_start_index": 10, "window_end_index": 12, "center_index": 11, "clearance_m": 0.03},
        {"window_start_index": 11, "window_end_index": 13, "center_index": 12, "clearance_m": 0.01},
        {"window_start_index": 30, "window_end_index": 32, "center_index": 31, "clearance_m": 0.02},
    ]
    merged_windows = [
        {"window_id": 0, "window_start_index": 9, "window_end_index": 14},
        {"window_id": 1, "window_start_index": 29, "window_end_index": 33},
    ]

    aggregated = _aggregate_turn_events_by_merged_windows(events, merged_windows)

    assert len(aggregated) == 2
    first = next(item for item in aggregated if item["merged_window_id"] == 0)
    assert first["clearance_m"] == 0.01


def test_turn_tight_windows_are_excluded_when_collision_exists() -> None:
    tight = [{"merged_window_id": 1}, {"merged_window_id": 2}]
    collision = [{"merged_window_id": 1}]

    filtered = _exclude_tight_windows_with_collision(tight, collision)

    assert filtered == [{"merged_window_id": 2}]
