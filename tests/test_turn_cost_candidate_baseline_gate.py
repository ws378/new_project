from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import numpy as np

from algorithms.turn_cost_coverage_research.scripts.baseline.run_candidate_baseline_gate import (
    CommandResult,
    DEFAULT_BASELINE_SUMMARY,
    DEFAULT_EXPECTED_BASELINE_CASE_COUNT,
    build_candidate_batch_command,
    run_candidate_baseline_gate,
)
from algorithms.turn_cost_coverage_research.scripts.baseline.run_shelf_aware_all_areas import _readonly_quality_metrics
from algorithms.turn_cost_coverage_research.scripts.diagnostics.build_effect_snapshot import EffectGateConfig, build_snapshot
from algorithms.turn_cost_coverage_research.scripts.diagnostics.effect_metric_contract import (
    effect_metric_contract_payload,
    gated_effect_metric_names,
    not_gated_effect_metric_names,
)


def _write_path(path: Path, points: list[list[float]]) -> str:
    path.write_text(json.dumps(points, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _write_summary(run_dir: Path, *, coverage_ratio: float, long_jump_count: int, path_points: list[list[float]]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path_pixels = _write_path(run_dir / "path_pixels.json", path_points)
    payload = {
        "runner": "run_shelf_aware_all_areas",
        "planner_mode": "shelf_aware_turn_cost",
        "area_count": 1,
        "success_count": 1,
        "failed_count": 0,
        "areas": [
            {
                "project_name": "beiguoshangcheng_floor_3",
                "area_id": 5,
                "status": "success",
                "area_run_dir": str(run_dir),
                "final_path_pixels": path_pixels,
                "coverage_ratio": coverage_ratio,
                "narrow_coverage_ratio": 0.99,
                "long_jump_count": long_jump_count,
                "turn_hotspot_count": 0,
                "infeasible_segment_count": 0,
                "lane_over_dense_count": 0,
                "lane_over_sparse_count": 0,
                "lane_spacing_issue_count": 0,
                "segment_crossing_count": 0,
            }
        ],
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary_path


def _strict_gate_config() -> EffectGateConfig:
    return EffectGateConfig(
        require_path_identity=True,
        coverage_epsilon=0.0,
        narrow_coverage_epsilon=0.0,
        allow_count_increase=0,
    )


def test_candidate_baseline_gate_builds_fixed_shelf_aware_turn_cost_command(tmp_path: Path) -> None:
    command = build_candidate_batch_command(
        output_root=tmp_path / "out",
        project_names=("beiguoshangcheng_floor_3",),
        area_ids=(5,),
    )

    assert "--planner-mode" in command
    assert command[command.index("--planner-mode") + 1] == "shelf_aware_turn_cost"
    assert "--project-name" in command
    assert command[command.index("--project-name") + 1] == "beiguoshangcheng_floor_3"
    assert "--area-id" in command
    assert command[command.index("--area-id") + 1] == "5"


def test_shelf_aware_all_areas_readonly_quality_metrics_fill_not_gated_fields() -> None:
    prepared_map = np.full((80, 80), 255, dtype=np.uint8)
    path_pixels = [[5.0, 10.0], [55.0, 10.0], [55.0, 14.0], [5.0, 14.0]]

    metrics = _readonly_quality_metrics(
        path_pixels=path_pixels,
        prepared_map=prepared_map,
        resolution_m_per_px=0.05,
        coverage_width_m=0.5,
    )

    assert metrics["coverage_width_px"] == 10
    assert metrics["narrow_coverage_ratio"] >= 0.0
    assert metrics["turn_hotspot_count"] >= 1
    assert metrics["lane_over_dense_count"] >= 2
    assert metrics["lane_spacing_issue_count"] == metrics["lane_over_dense_count"] + metrics["lane_over_sparse_count"]
    assert metrics["segment_crossing_count"] == 0


def test_default_candidate_baseline_is_lightweight_committed_fixture() -> None:
    assert DEFAULT_BASELINE_SUMMARY.is_file()
    assert "baselines" in DEFAULT_BASELINE_SUMMARY.parts
    assert "output" not in DEFAULT_BASELINE_SUMMARY.parts
    assert DEFAULT_EXPECTED_BASELINE_CASE_COUNT == 19

    payload = json.loads(DEFAULT_BASELINE_SUMMARY.read_text(encoding="utf-8"))
    assert payload["planner_mode"] == "shelf_aware_turn_cost"
    assert payload["area_count"] == 19
    assert payload["success_count"] == 19

    for area in payload["areas"]:
        path_pixels = Path(area["final_path_pixels"])
        assert not path_pixels.is_absolute()
        assert path_pixels.is_file()

    snapshot = build_snapshot(payload)
    assert snapshot["area_count"] == 19
    assert all(area["final_path_pixels_sha256"] for area in snapshot["areas"])


def test_candidate_baseline_gate_passes_and_writes_status_artifact(tmp_path: Path) -> None:
    output_root = tmp_path / "candidate"
    candidate_run_dir = output_root / "run_candidate"
    baseline_summary = _write_summary(
        tmp_path / "baseline",
        coverage_ratio=0.998,
        long_jump_count=0,
        path_points=[[1, 2], [3, 4]],
    )
    _write_summary(candidate_run_dir, coverage_ratio=0.998, long_jump_count=0, path_points=[[1, 2], [3, 4]])

    def runner(command: Sequence[str]) -> CommandResult:
        assert "--planner-mode" in command
        return CommandResult(returncode=0, stdout=f"case ok\n{candidate_run_dir}\n", stderr="")

    payload = run_candidate_baseline_gate(
        output_root=output_root,
        baseline_summary_path=baseline_summary,
        gate_config=_strict_gate_config(),
        expected_baseline_case_count=None,
        command_runner=runner,
    )

    assert payload["status"] == "pass"
    assert payload["comparison_status"] == "pass"
    assert payload["comparison_case_count"] == 1
    assert payload["path_identity_pass_count"] == 1
    assert payload["baseline_summary_sha256"]
    assert payload["baseline_case_count"] == 1
    assert payload["baseline_path_pixels_count"] == 1
    assert payload["baseline_path_pixels_missing_count"] == 0
    assert payload["baseline_path_pixels_bundle_sha256"]
    assert payload["baseline_run_id"] == "baseline"
    assert payload["expected_baseline_case_count"] is None
    assert payload["not_available_metrics"] == []
    assert payload["unknown_metrics"] == []
    assert payload["gated_metrics"] == ["coverage_ratio", "long_jump_count", "infeasible_segment_count"]
    assert "narrow_coverage_ratio" in payload["not_gated_metrics"]
    assert payload["gated_metrics"] == list(gated_effect_metric_names())
    assert payload["not_gated_metrics"] == list(not_gated_effect_metric_names())
    assert payload["gate"]["metric_contract"] == effect_metric_contract_payload()
    assert payload["not_gated_metric_status_summary"]["narrow_coverage_ratio"]["status_counts"]["pass"] == 1
    assert payload["not_gated_metric_status_summary"]["lane_spacing_issue_count"]["status_counts"]["pass"] == 1
    assert (candidate_run_dir / "candidate_baseline_gate_summary.json").is_file()
    assert (candidate_run_dir / "effect_snapshot_against_fixed_candidate_baseline" / "effect_comparison.json").is_file()


def test_candidate_baseline_gate_fails_when_expected_baseline_case_count_mismatches(tmp_path: Path) -> None:
    called = False

    def runner(_command: Sequence[str]) -> CommandResult:
        nonlocal called
        called = True
        return CommandResult(returncode=0, stdout="", stderr="")

    payload = run_candidate_baseline_gate(
        output_root=tmp_path / "candidate",
        baseline_summary_path=_write_summary(
            tmp_path / "baseline",
            coverage_ratio=0.998,
            long_jump_count=0,
            path_points=[[1, 2], [3, 4]],
        ),
        gate_config=_strict_gate_config(),
        command_runner=runner,
    )

    assert payload["status"] == "fail"
    assert payload["failure_reason"] == "baseline_case_count_mismatch"
    assert payload["baseline_case_count"] == 1
    assert payload["expected_baseline_case_count"] == 19
    assert payload["gated_metrics"] == list(gated_effect_metric_names())
    assert payload["not_gated_metrics"] == list(not_gated_effect_metric_names())
    assert called is False


def test_candidate_baseline_gate_fails_fast_when_committed_baseline_path_pixels_missing(tmp_path: Path) -> None:
    called = False

    def runner(_command: Sequence[str]) -> CommandResult:
        nonlocal called
        called = True
        return CommandResult(returncode=0, stdout="", stderr="")

    baseline_summary = _write_summary(
        tmp_path / "baseline",
        coverage_ratio=0.998,
        long_jump_count=0,
        path_points=[[1, 2], [3, 4]],
    )
    (baseline_summary.parent / "path_pixels.json").unlink()

    payload = run_candidate_baseline_gate(
        output_root=tmp_path / "candidate",
        baseline_summary_path=baseline_summary,
        gate_config=_strict_gate_config(),
        expected_baseline_case_count=1,
        command_runner=runner,
    )

    assert payload["status"] == "fail"
    assert payload["failure_reason"] == "baseline_path_pixels_missing"
    assert payload["baseline_case_count"] == 1
    assert payload["baseline_path_pixels_count"] == 0
    assert payload["baseline_path_pixels_missing_count"] == 1
    assert payload["baseline_path_pixels_bundle_sha256"] == ""
    assert payload["gate"]["metric_contract"] == effect_metric_contract_payload()
    assert called is False


def test_candidate_baseline_gate_fails_on_metric_regression(tmp_path: Path) -> None:
    output_root = tmp_path / "candidate"
    candidate_run_dir = output_root / "run_candidate"
    baseline_summary = _write_summary(
        tmp_path / "baseline",
        coverage_ratio=0.998,
        long_jump_count=0,
        path_points=[[1, 2], [3, 4]],
    )
    _write_summary(candidate_run_dir, coverage_ratio=0.990, long_jump_count=1, path_points=[[1, 2], [3, 4]])

    payload = run_candidate_baseline_gate(
        output_root=output_root,
        baseline_summary_path=baseline_summary,
        gate_config=_strict_gate_config(),
        expected_baseline_case_count=None,
        command_runner=lambda _command: CommandResult(returncode=0, stdout=str(candidate_run_dir), stderr=""),
    )

    assert payload["status"] == "fail"
    assert payload["failure_reason"] == "effect_gate_failed"
    assert payload["comparison_status"] == "fail"
    assert payload["comparison_fail_count"] == 1


def test_candidate_baseline_gate_records_batch_failure_without_losing_comparison(tmp_path: Path) -> None:
    output_root = tmp_path / "candidate"
    candidate_run_dir = output_root / "run_candidate"
    baseline_summary = _write_summary(
        tmp_path / "baseline",
        coverage_ratio=0.998,
        long_jump_count=0,
        path_points=[[1, 2], [3, 4]],
    )
    _write_summary(candidate_run_dir, coverage_ratio=0.998, long_jump_count=0, path_points=[[1, 2], [3, 4]])

    payload = run_candidate_baseline_gate(
        output_root=output_root,
        baseline_summary_path=baseline_summary,
        gate_config=_strict_gate_config(),
        expected_baseline_case_count=None,
        command_runner=lambda _command: CommandResult(returncode=1, stdout=f"{candidate_run_dir}\n", stderr="one area failed"),
    )

    assert payload["status"] == "fail"
    assert payload["failure_reason"] == "candidate_batch_failed"
    assert payload["comparison_status"] == "pass"
    assert payload["candidate_runner_returncode"] == 1


def test_candidate_baseline_gate_fails_when_candidate_summary_missing(tmp_path: Path) -> None:
    output_root = tmp_path / "candidate"
    missing_run_dir = output_root / "run_without_summary"
    missing_run_dir.mkdir(parents=True)
    baseline_summary = _write_summary(
        tmp_path / "baseline",
        coverage_ratio=0.998,
        long_jump_count=0,
        path_points=[[1, 2], [3, 4]],
    )

    payload = run_candidate_baseline_gate(
        output_root=output_root,
        baseline_summary_path=baseline_summary,
        gate_config=_strict_gate_config(),
        expected_baseline_case_count=None,
        command_runner=lambda _command: CommandResult(returncode=0, stdout=f"{missing_run_dir}\n", stderr=""),
    )

    assert payload["status"] == "fail"
    assert payload["failure_reason"] == "candidate_summary_missing"
    assert payload["gated_metrics"] == list(gated_effect_metric_names())
    assert payload["not_gated_metrics"] == list(not_gated_effect_metric_names())
    assert payload["gate"]["metric_contract"] == effect_metric_contract_payload()
    assert (missing_run_dir / "candidate_baseline_gate_summary.json").is_file()


def test_candidate_baseline_gate_warns_when_gated_metric_is_unknown(tmp_path: Path) -> None:
    output_root = tmp_path / "candidate"
    candidate_run_dir = output_root / "run_candidate"
    baseline_summary = _write_summary(
        tmp_path / "baseline",
        coverage_ratio=0.998,
        long_jump_count=0,
        path_points=[[1, 2], [3, 4]],
    )
    candidate_summary = _write_summary(candidate_run_dir, coverage_ratio=0.998, long_jump_count=0, path_points=[[1, 2], [3, 4]])
    payload = json.loads(candidate_summary.read_text(encoding="utf-8"))
    del payload["areas"][0]["coverage_ratio"]
    candidate_summary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    gate_payload = run_candidate_baseline_gate(
        output_root=output_root,
        baseline_summary_path=baseline_summary,
        gate_config=EffectGateConfig(
            require_path_identity=False,
            coverage_epsilon=0.0,
            narrow_coverage_epsilon=0.0,
            allow_count_increase=0,
        ),
        expected_baseline_case_count=None,
        command_runner=lambda _command: CommandResult(returncode=0, stdout=str(candidate_run_dir), stderr=""),
    )

    assert gate_payload["status"] == "warn"
    assert gate_payload["failure_reason"] == "effect_gate_warn"
    assert gate_payload["comparison_status"] == "warn"
    assert gate_payload["unknown_metrics"] == ["coverage_ratio"]


def test_candidate_baseline_gate_fails_fast_when_baseline_summary_missing(tmp_path: Path) -> None:
    called = False

    def runner(_command: Sequence[str]) -> CommandResult:
        nonlocal called
        called = True
        return CommandResult(returncode=0, stdout="", stderr="")

    payload = run_candidate_baseline_gate(
        output_root=tmp_path / "candidate",
        baseline_summary_path=tmp_path / "missing_baseline.json",
        gate_config=_strict_gate_config(),
        command_runner=runner,
    )

    assert payload["status"] == "fail"
    assert payload["failure_reason"] == "baseline_summary_missing"
    assert payload["not_gated_metric_status_summary"] == {}
    assert payload["gated_metrics"] == list(gated_effect_metric_names())
    assert payload["not_gated_metrics"] == list(not_gated_effect_metric_names())
    assert payload["gate"]["metric_contract"] == effect_metric_contract_payload()
    assert called is False
