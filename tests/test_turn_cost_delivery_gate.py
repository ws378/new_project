from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Sequence

from algorithms.turn_cost_coverage_research.scripts.baseline.run_candidate_baseline_gate import CommandResult
from algorithms.turn_cost_coverage_research.scripts.baseline.run_shelf_aware_turn_cost_delivery_gate import (
    _default_runner,
    build_pytest_command,
    run_delivery_gate,
    scan_forbidden_runtime_symbols,
)
from algorithms.turn_cost_coverage_research.scripts.diagnostics.build_effect_snapshot import EffectGateConfig
from algorithms.turn_cost_coverage_research.scripts.diagnostics.effect_metric_contract import (
    effect_metric_contract_payload,
)


def _strict_gate_config() -> EffectGateConfig:
    return EffectGateConfig(
        require_path_identity=True,
        coverage_epsilon=0.0,
        narrow_coverage_epsilon=0.0,
        allow_count_increase=0,
    )


def _write_summary(run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path_pixels = run_dir / "path_pixels.json"
    path_pixels.write_text(json.dumps([[1, 2], [3, 4]], ensure_ascii=False), encoding="utf-8")
    summary = {
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
                "final_path_pixels": str(path_pixels),
                "coverage_ratio": 0.998,
                "narrow_coverage_ratio": 0.99,
                "long_jump_count": 0,
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
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary_path


def test_scan_forbidden_runtime_symbols_detects_candidate_ref_legacy_shell(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    source_dir = root / "algorithms" / "coverage_planning" / "planners" / "shelf_aware_guarded"
    source_dir.mkdir(parents=True)
    (source_dir / "bad.py").write_text("value = candidate_ref.legacy_node\n", encoding="utf-8")

    step = scan_forbidden_runtime_symbols(repo_root=root, roots=("algorithms/coverage_planning/planners/shelf_aware_guarded",))

    assert step.status == "fail"
    assert step.failure_reason == "forbidden_symbol_found"
    assert step.details is not None
    assert step.details["matches"][0]["path"].endswith("bad.py")


def test_scan_forbidden_runtime_symbols_detects_traversal_cursor_legacy_shell(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    source_dir = root / "algorithms" / "coverage_planning" / "planners" / "shelf_aware_guarded"
    source_dir.mkdir(parents=True)
    (source_dir / "bad.py").write_text("value = TraversalCursor.legacy_node\n", encoding="utf-8")

    step = scan_forbidden_runtime_symbols(repo_root=root, roots=("algorithms/coverage_planning/planners/shelf_aware_guarded",))

    assert step.status == "fail"
    assert step.failure_reason == "forbidden_symbol_found"
    assert step.details is not None
    assert step.details["matches"][0]["pattern"] == r"TraversalCursor\.legacy_node"


def test_scan_forbidden_runtime_symbols_detects_traversal_cursor_graph_access_factory(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    source_dir = root / "algorithms" / "coverage_planning" / "planners" / "shelf_aware_guarded"
    source_dir.mkdir(parents=True)
    (source_dir / "bad.py").write_text(
        "cursor = TraversalCursor.from_cell_id('r1_c1', graph_access=graph_access)\n",
        encoding="utf-8",
    )

    step = scan_forbidden_runtime_symbols(repo_root=root, roots=("algorithms/coverage_planning/planners/shelf_aware_guarded",))

    assert step.status == "fail"
    assert step.failure_reason == "forbidden_symbol_found"
    assert step.details is not None
    assert step.details["matches"][0]["pattern"] == r"TraversalCursor\.from_cell_id\([^)]*,\s*graph_access"


def test_build_pytest_command_uses_current_interpreter() -> None:
    command = build_pytest_command(("tests/test_coverage_planner_modes.py",))

    assert command[1:4] == ["-m", "pytest", "-q"]
    assert command[-1] == "tests/test_coverage_planner_modes.py"


def test_default_runner_disables_external_pytest_plugins(monkeypatch) -> None:
    received_env = {}

    class Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(command, check, text, capture_output, env):
        received_env.update(env)
        return Completed()

    monkeypatch.delenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", raising=False)
    monkeypatch.setattr(
        "algorithms.turn_cost_coverage_research.scripts.baseline.run_shelf_aware_turn_cost_delivery_gate.subprocess.run",
        fake_run,
    )

    result = _default_runner(build_pytest_command(("tests/test_main_window_flow.py",)))

    assert result.returncode == 0
    assert received_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD" not in os.environ


def test_delivery_gate_passes_with_pytest_and_effect_gate(tmp_path: Path) -> None:
    baseline_summary = _write_summary(tmp_path / "baseline")
    candidate_dir = tmp_path / "candidate" / "run_case"
    _write_summary(candidate_dir)
    commands: list[list[str]] = []

    def runner(command: Sequence[str]) -> CommandResult:
        commands.append(list(command))
        if "-m" in command and "pytest" in command:
            return CommandResult(returncode=0, stdout="pytest ok", stderr="")
        return CommandResult(returncode=0, stdout=f"{candidate_dir}\n", stderr="")

    payload = run_delivery_gate(
        output_root=tmp_path / "delivery",
        baseline_summary_path=baseline_summary,
        run_pytest=True,
        run_effect_baseline=True,
        gate_config=_strict_gate_config(),
        expected_baseline_case_count=1,
        command_runner=runner,
    )

    assert payload["status"] == "pass"
    assert payload["effect_metric_contract"] == effect_metric_contract_payload()
    assert [step["name"] for step in payload["steps"]] == [
        "forbidden_runtime_symbols",
        "formal_contract_tests",
        "ui_contract_tests",
        "export_contract_tests",
        "coverage_graph_contract_tests",
        "traversal_core_tests",
        "scoring_contract_tests",
        "final_path_provenance_tests",
        "candidate_effect_baseline",
    ]
    assert (Path(payload["run_dir"]) / "delivery_gate_summary.json").is_file()
    effect_details = payload["steps"][-1]["details"]
    assert effect_details["not_gated_metric_status_summary"]["narrow_coverage_ratio"]["status_counts"]["pass"] == 1
    assert effect_details["not_gated_metric_status_summary"]["lane_spacing_issue_count"]["status_counts"]["pass"] == 1
    assert any("--planner-mode" in command for command in commands)
    assert any("tests/test_shelf_aware_node_debug_payload.py" in command for command in commands)


def test_delivery_gate_recreates_run_dir_before_writing_summary(tmp_path: Path) -> None:
    baseline_summary = _write_summary(tmp_path / "baseline")
    candidate_dir = tmp_path / "candidate" / "run_case"
    _write_summary(candidate_dir)
    delivery_root = tmp_path / "delivery"

    def runner(command: Sequence[str]) -> CommandResult:
        if "-m" in command and "pytest" in command:
            return CommandResult(returncode=0, stdout="pytest ok", stderr="")
        shutil.rmtree(delivery_root)
        return CommandResult(returncode=0, stdout=f"{candidate_dir}\n", stderr="")

    payload = run_delivery_gate(
        output_root=delivery_root,
        baseline_summary_path=baseline_summary,
        run_pytest=True,
        run_effect_baseline=True,
        gate_config=_strict_gate_config(),
        expected_baseline_case_count=1,
        command_runner=runner,
    )

    summary_path = Path(payload["run_dir"]) / "delivery_gate_summary.json"
    assert summary_path.is_file()


def test_delivery_gate_reports_failed_pytest_without_hiding_effect_result(tmp_path: Path) -> None:
    baseline_summary = _write_summary(tmp_path / "baseline")
    candidate_dir = tmp_path / "candidate" / "run_case"
    _write_summary(candidate_dir)

    def runner(command: Sequence[str]) -> CommandResult:
        if "-m" in command and "pytest" in command:
            return CommandResult(returncode=1, stdout="", stderr="failed")
        return CommandResult(returncode=0, stdout=f"{candidate_dir}\n", stderr="")

    payload = run_delivery_gate(
        output_root=tmp_path / "delivery",
        baseline_summary_path=baseline_summary,
        run_pytest=True,
        run_effect_baseline=True,
        gate_config=_strict_gate_config(),
        expected_baseline_case_count=1,
        command_runner=runner,
    )

    assert payload["status"] == "fail"
    assert payload["failure_reason"] == "command_failed"
    assert payload["steps"][-1]["name"] == "candidate_effect_baseline"
    assert payload["steps"][-1]["status"] == "pass"


def test_delivery_gate_warns_when_explicitly_skipped(tmp_path: Path) -> None:
    payload = run_delivery_gate(
        output_root=tmp_path / "delivery",
        baseline_summary_path=tmp_path / "unused.json",
        run_pytest=False,
        run_effect_baseline=False,
        gate_config=_strict_gate_config(),
        command_runner=lambda _command: CommandResult(returncode=0, stdout="", stderr=""),
    )

    assert payload["status"] == "warn"
    assert {step["status"] for step in payload["steps"]} == {"pass", "skip"}
