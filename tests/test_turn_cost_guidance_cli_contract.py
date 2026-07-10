from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from algorithms.turn_cost_coverage_research.scripts.experiments import run_maptools_official_all_areas


def test_all_area_runner_transmits_guidance_arguments(monkeypatch, tmp_path: Path) -> None:
    area_run_dir = tmp_path / "area_run"
    area_run_dir.mkdir()
    (area_run_dir / "summary.json").write_text(
        json.dumps(
            {
                "case_count": 1,
                "success_count": 1,
                "component_count": 1,
                "aggregate_metrics": {"area_weighted_feasible_coverage_ratio": 0.5},
                "cases": [
                    {
                        "status": "success",
                        "case_id": "case",
                        "input": {"adapter_metadata": {"polygon_area_m2": 1.0}},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=str(area_run_dir) + "\n", stderr="")

    monkeypatch.setattr(run_maptools_official_all_areas.subprocess, "run", fake_run)
    args = SimpleNamespace(
        stop_after="graph",
        fractional_solver="highs",
        penalty_strength=160.0,
        graph_length_limit_factor=2.0,
        tool_radius_scale=1.0,
        atomic_orientation_count=3,
        atomic_orientation_repetition=2,
        no_retry_profiles=True,
        retry_min_coverage_ratio=0.85,
        graph_backend="hex_delaunay",
        square_grid_step_scale=1.0,
        square_diagonal_cost_multiplier=1.15,
        square_axis_confidence_threshold=0.60,
        square_axis_angle_tolerance_deg=25.0,
        square_no_component_bridge=False,
        square_bridge_max_step_factor=8.0,
        square_bridge_cost_multiplier=4.0,
        allow_square8_guided_atomic=False,
        guidance_mode="shelf_local_direction",
        guidance_weight_frac=0.25,
        guidance_weight_abs=0.0,
        guidance_min_confidence=0.08,
        atomic_guidance_strategy="corridor_axis",
        corridor_axis_primary_orientation_count=2,
    )

    run_maptools_official_all_areas._run_one_area(
        args=args,
        case_script=Path("case_script.py"),
        run_dir=tmp_path,
        project_name="fourfloor_20250923_8",
        project_dir=Path("examples/maptools_projects/fourfloor_20250923_8"),
        area_id=2,
    )

    command = commands[0]
    assert "--graph-backend" in command
    assert command[command.index("--graph-backend") + 1] == "hex_delaunay"
    assert "--atomic-orientation-count" in command
    assert command[command.index("--atomic-orientation-count") + 1] == "3"
    assert "--atomic-orientation-repetition" in command
    assert command[command.index("--atomic-orientation-repetition") + 1] == "2"
    assert "--guidance-mode" in command
    assert command[command.index("--guidance-mode") + 1] == "shelf_local_direction"
    assert "--guidance-weight-frac" in command
    assert "--guidance-weight-abs" in command
    assert "--guidance-min-confidence" in command
    assert "--atomic-guidance-strategy" in command
    assert command[command.index("--atomic-guidance-strategy") + 1] == "corridor_axis"
    assert "--corridor-axis-primary-orientation-count" in command
    assert command[command.index("--corridor-axis-primary-orientation-count") + 1] == "2"


def test_all_area_runner_rejects_square8_guided_atomic_combo() -> None:
    args = SimpleNamespace(
        graph_backend="square8_axis_guided",
        guidance_mode="shelf_local_direction",
        allow_square8_guided_atomic=False,
    )

    with pytest.raises(SystemExit, match="guided atomic"):
        run_maptools_official_all_areas._validate_experiment_scope(args)


def test_all_area_runner_accepts_explicit_square8_guided_atomic_combo() -> None:
    args = SimpleNamespace(
        graph_backend="square8_axis_guided",
        guidance_mode="shelf_local_direction",
        allow_square8_guided_atomic=True,
    )

    run_maptools_official_all_areas._validate_experiment_scope(args)


def test_square8_retry_profiles_prioritize_penalty_without_width_change() -> None:
    args = SimpleNamespace(
        penalty_strength=160.0,
        graph_length_limit_factor=2.0,
        tool_radius_scale=1.0,
        no_retry_profiles=False,
        graph_backend="square8_axis_guided",
    )

    profiles = run_maptools_official_all_areas._area_profiles(args)

    assert [profile["penalty_strength"] for profile in profiles] == [160.0, 300.0, 400.0, 600.0, 800.0]
    assert {profile["tool_radius_scale"] for profile in profiles} == {1.0}


def test_retry_stop_condition_requires_coverage_threshold() -> None:
    args = SimpleNamespace(retry_min_coverage_ratio=0.85)
    summary = {
        "case_count": 1,
        "success_count": 1,
        "aggregate_metrics": {"area_weighted_feasible_coverage_ratio": 0.56},
    }

    assert not run_maptools_official_all_areas._has_met_retry_stop_condition(summary, args)
    summary["aggregate_metrics"]["area_weighted_feasible_coverage_ratio"] = 0.86
    assert run_maptools_official_all_areas._has_met_retry_stop_condition(summary, args)
