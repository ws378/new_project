"""运行 ShelfAware+TurnCost 正式交付门禁。"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PACKAGE_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.turn_cost_coverage_research.scripts.baseline.run_candidate_baseline_gate import (  # noqa: E402
    DEFAULT_BASELINE_SUMMARY,
    DEFAULT_EXPECTED_BASELINE_CASE_COUNT,
    CommandResult,
    run_candidate_baseline_gate,
)
from algorithms.turn_cost_coverage_research.scripts.diagnostics.build_effect_snapshot import (  # noqa: E402
    EffectGateConfig,
)
from algorithms.turn_cost_coverage_research.scripts.diagnostics.effect_metric_contract import (  # noqa: E402
    effect_metric_contract_payload,
)

DEFAULT_OUTPUT_ROOT = PACKAGE_ROOT / "output" / "delivery_gates"

FORMAL_CONTRACT_TESTS = (
    "tests/test_coverage_planner_modes.py",
    "tests/test_planner_factory_modes.py",
    "tests/test_turn_cost_candidate_baseline_gate.py",
)

UI_CONTRACT_TESTS = (
    "tests/test_main_window_flow.py",
)

EXPORT_CONTRACT_TESTS = (
    "tests/test_coverage_repo_export_diagnostics.py",
    "tests/test_coverage_repo_export_planner_modes.py",
)

COVERAGE_GRAPH_CONTRACT_TESTS = (
    "tests/test_shelf_aware_grid_builder.py",
    "tests/test_shelf_aware_coverage_graph_stage.py",
    "tests/test_shelf_aware_traversal_graph_access.py",
)

TRAVERSAL_CORE_TESTS = (
    "tests/test_shelf_aware_traversal_candidate_enumeration.py",
    "tests/test_shelf_aware_traversal_candidate_summary.py",
    "tests/test_shelf_aware_traversal_phase_selectors.py",
    "tests/test_shelf_aware_traversal_move_commit.py",
    "tests/test_shelf_aware_traversal_state.py",
    "tests/test_shelf_aware_node_truth_boundaries.py",
)

SCORING_CONTRACT_TESTS = (
    "tests/test_shelf_aware_candidate_score_breakdown.py",
    "tests/test_shelf_aware_traversal_candidate_evaluation.py",
)

FINAL_PATH_PROVENANCE_TESTS = (
    "tests/test_shelf_aware_final_path_transform_record.py",
    "tests/test_shelf_aware_final_path_realization.py",
    "tests/test_shelf_aware_artifact_write_stage.py",
    "tests/test_shelf_aware_artifact_outputs.py",
    "tests/test_shelf_aware_node_debug_payload.py",
    "tests/test_shelf_aware_final_provenance.py",
)

FORBIDDEN_RUNTIME_SYMBOLS = (
    r"candidate_ref\.legacy_node",
    r"TraversalCandidateRef\.legacy_node",
    r"TraversalCandidateRef\([^)]*,\s*legacy_node\s*=",
    r"TraversalCandidateRef\.from_cell_id\([^)]*,\s*graph_access",
    r"TraversalCursor\.legacy_node",
    r"TraversalCursor\([^)]*legacy_node\s*=",
    r"TraversalCursor\.from_cell_id\([^)]*,\s*graph_access",
    r"TraversalCursor\.from_graph_access",
)

FORBIDDEN_SCAN_ROOTS = (
    "algorithms/coverage_planning/planners/shelf_aware_guarded",
    "tests/test_shelf_aware_traversal_candidate_enumeration.py",
    "tests/test_shelf_aware_traversal_candidate_summary.py",
    "tests/test_shelf_aware_traversal_move_commit.py",
    "tests/test_shelf_aware_traversal_phase_selectors.py",
    "tests/test_shelf_aware_traversal_state.py",
    "tests/test_shelf_aware_node_truth_boundaries.py",
)

IGNORED_DIR_NAMES = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".venv", "output", "third_party"}


CommandRunner = Callable[[Sequence[str]], CommandResult]


@dataclass(frozen=True)
class GateStep:
    name: str
    status: str
    failure_reason: str = ""
    command: tuple[str, ...] = ()
    returncode: int | None = None
    stdout_tail: tuple[str, ...] = ()
    stderr_tail: tuple[str, ...] = ()
    details: dict[str, Any] | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="交付门禁输出根目录。")
    parser.add_argument("--baseline-summary", type=Path, default=DEFAULT_BASELINE_SUMMARY, help="固定候选基线 summary.json。")
    parser.add_argument("--skip-pytest", action="store_true", help="跳过 pytest 子门禁，仅用于定位门禁脚本自身问题。")
    parser.add_argument("--skip-effect-baseline", action="store_true", help="跳过三项目效果基线，仅用于本地快速预检。")
    parser.add_argument("--project-name", action="append", help="效果基线只运行指定项目，可重复。")
    parser.add_argument("--area-id", action="append", type=int, help="效果基线只运行指定区域，可重复。")
    parser.add_argument("--coverage-epsilon", type=float, default=0.0, help="允许 coverage_ratio 下降的最大值。")
    parser.add_argument("--narrow-coverage-epsilon", type=float, default=0.0, help="允许 narrow_coverage_ratio 下降的最大值。")
    parser.add_argument("--allow-count-increase", type=int, default=0, help="允许计数类风险指标增加的最大整数值。")
    return parser.parse_args()


def _default_runner(command: Sequence[str]) -> CommandResult:
    env = os.environ.copy()
    if "-m" in command and "pytest" in command:
        env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    completed = subprocess.run(command, check=False, text=True, capture_output=True, env=env)
    return CommandResult(returncode=int(completed.returncode), stdout=completed.stdout, stderr=completed.stderr)


def _tail(text: str, *, line_count: int = 40) -> tuple[str, ...]:
    return tuple(text.splitlines()[-line_count:])


def _iter_scan_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    if root.is_file():
        yield root
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIR_NAMES for part in path.parts):
            continue
        if path.suffix not in {".py", ".md"}:
            continue
        yield path


def scan_forbidden_runtime_symbols(
    *,
    repo_root: Path = REPO_ROOT,
    roots: Sequence[str] = FORBIDDEN_SCAN_ROOTS,
    patterns: Sequence[str] = FORBIDDEN_RUNTIME_SYMBOLS,
) -> GateStep:
    compiled = [re.compile(pattern) for pattern in patterns]
    matches: list[dict[str, Any]] = []
    for root_name in roots:
        for path in _iter_scan_files(repo_root / root_name):
            relative = path.relative_to(repo_root)
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(text.splitlines(), start=1):
                for pattern in compiled:
                    if pattern.search(line):
                        matches.append(
                            {
                                "path": str(relative),
                                "line": line_no,
                                "pattern": pattern.pattern,
                                "text": line.strip(),
                            }
                        )
    if matches:
        return GateStep(
            name="forbidden_runtime_symbols",
            status="fail",
            failure_reason="forbidden_symbol_found",
            details={"matches": matches},
        )
    return GateStep(name="forbidden_runtime_symbols", status="pass", details={"match_count": 0})


def build_pytest_command(test_paths: Sequence[str]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        *test_paths,
    ]


def run_command_step(name: str, command: Sequence[str], *, command_runner: CommandRunner = _default_runner) -> GateStep:
    result = command_runner(command)
    return GateStep(
        name=name,
        status="pass" if result.returncode == 0 else "fail",
        failure_reason="" if result.returncode == 0 else "command_failed",
        command=tuple(command),
        returncode=int(result.returncode),
        stdout_tail=_tail(result.stdout),
        stderr_tail=_tail(result.stderr),
    )


def _step_to_json(step: GateStep) -> dict[str, Any]:
    return {
        "name": step.name,
        "status": step.status,
        "failure_reason": step.failure_reason,
        "command": list(step.command),
        "returncode": step.returncode,
        "stdout_tail": list(step.stdout_tail),
        "stderr_tail": list(step.stderr_tail),
        "details": step.details or {},
    }


def run_delivery_gate(
    *,
    output_root: Path,
    baseline_summary_path: Path,
    project_names: Sequence[str] = (),
    area_ids: Sequence[int] = (),
    run_pytest: bool = True,
    run_effect_baseline: bool = True,
    gate_config: EffectGateConfig,
    expected_baseline_case_count: int = DEFAULT_EXPECTED_BASELINE_CASE_COUNT,
    command_runner: CommandRunner = _default_runner,
) -> dict[str, Any]:
    output_root = Path(output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_aware_turn_cost_delivery_gate")
    run_dir.mkdir(parents=True, exist_ok=True)

    steps: list[GateStep] = [scan_forbidden_runtime_symbols()]
    if run_pytest:
        steps.append(run_command_step("formal_contract_tests", build_pytest_command(FORMAL_CONTRACT_TESTS), command_runner=command_runner))
        steps.append(run_command_step("ui_contract_tests", build_pytest_command(UI_CONTRACT_TESTS), command_runner=command_runner))
        steps.append(run_command_step("export_contract_tests", build_pytest_command(EXPORT_CONTRACT_TESTS), command_runner=command_runner))
        steps.append(run_command_step("coverage_graph_contract_tests", build_pytest_command(COVERAGE_GRAPH_CONTRACT_TESTS), command_runner=command_runner))
        steps.append(run_command_step("traversal_core_tests", build_pytest_command(TRAVERSAL_CORE_TESTS), command_runner=command_runner))
        steps.append(run_command_step("scoring_contract_tests", build_pytest_command(SCORING_CONTRACT_TESTS), command_runner=command_runner))
        steps.append(run_command_step("final_path_provenance_tests", build_pytest_command(FINAL_PATH_PROVENANCE_TESTS), command_runner=command_runner))
    else:
        steps.append(GateStep(name="formal_contract_tests", status="skip", failure_reason="skip_pytest"))
        steps.append(GateStep(name="ui_contract_tests", status="skip", failure_reason="skip_pytest"))
        steps.append(GateStep(name="export_contract_tests", status="skip", failure_reason="skip_pytest"))
        steps.append(GateStep(name="coverage_graph_contract_tests", status="skip", failure_reason="skip_pytest"))
        steps.append(GateStep(name="traversal_core_tests", status="skip", failure_reason="skip_pytest"))
        steps.append(GateStep(name="scoring_contract_tests", status="skip", failure_reason="skip_pytest"))
        steps.append(GateStep(name="final_path_provenance_tests", status="skip", failure_reason="skip_pytest"))

    effect_payload: dict[str, Any] | None = None
    if run_effect_baseline:
        effect_payload = run_candidate_baseline_gate(
            output_root=PACKAGE_ROOT / "output" / "candidate_baselines",
            baseline_summary_path=baseline_summary_path,
            project_names=project_names,
            area_ids=area_ids,
            gate_config=gate_config,
            expected_baseline_case_count=expected_baseline_case_count,
            command_runner=command_runner,
        )
        steps.append(
            GateStep(
                name="candidate_effect_baseline",
                status=str(effect_payload.get("status", "fail")),
                failure_reason=str(effect_payload.get("failure_reason", "")),
                command=tuple(effect_payload.get("candidate_batch_command", ())),
                returncode=effect_payload.get("candidate_runner_returncode"),
                stdout_tail=tuple(effect_payload.get("stdout_tail", ())),
                stderr_tail=tuple(effect_payload.get("stderr_tail", ())),
                details={
                    "candidate_run_dir": effect_payload.get("candidate_run_dir", ""),
                    "comparison_case_count": effect_payload.get("comparison_case_count"),
                    "comparison_fail_count": effect_payload.get("comparison_fail_count"),
                    "comparison_warn_count": effect_payload.get("comparison_warn_count"),
                    "path_identity_pass_count": effect_payload.get("path_identity_pass_count"),
                    "not_gated_metric_status_summary": effect_payload.get("not_gated_metric_status_summary", {}),
                },
            )
        )
    else:
        steps.append(GateStep(name="candidate_effect_baseline", status="skip", failure_reason="skip_effect_baseline"))

    failed_steps = [step for step in steps if step.status not in {"pass", "skip"}]
    skipped_steps = [step for step in steps if step.status == "skip"]
    status = "pass" if not failed_steps and not skipped_steps else "warn" if not failed_steps else "fail"
    payload = {
        "runner": "run_shelf_aware_turn_cost_delivery_gate",
        "status": status,
        "failure_reason": failed_steps[0].failure_reason if failed_steps else "",
        "run_dir": str(run_dir),
        "baseline_summary": str(Path(baseline_summary_path).expanduser()),
        "steps": [_step_to_json(step) for step in steps],
        "effect_metric_contract": effect_metric_contract_payload(),
        "effect_gate_summary": effect_payload,
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "delivery_gate_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    args = parse_args()
    payload = run_delivery_gate(
        output_root=Path(args.output_root),
        baseline_summary_path=Path(args.baseline_summary),
        project_names=tuple(args.project_name or ()),
        area_ids=tuple(int(value) for value in (args.area_id or ())),
        run_pytest=not bool(args.skip_pytest),
        run_effect_baseline=not bool(args.skip_effect_baseline),
        gate_config=EffectGateConfig(
            require_path_identity=True,
            coverage_epsilon=float(args.coverage_epsilon),
            narrow_coverage_epsilon=float(args.narrow_coverage_epsilon),
            allow_count_increase=int(args.allow_count_increase),
        ),
    )
    print(payload["run_dir"])
    print(payload["status"])
    if payload["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
