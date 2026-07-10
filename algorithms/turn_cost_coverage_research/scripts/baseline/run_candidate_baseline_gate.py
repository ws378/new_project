"""运行 ShelfAware+TurnCost 候选基线，并生成效果门禁摘要。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PACKAGE_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.turn_cost_coverage_research.scripts.diagnostics.build_effect_snapshot import (  # noqa: E402
    EffectGateConfig,
    build_snapshot,
    write_snapshot_outputs,
)
from algorithms.turn_cost_coverage_research.scripts.diagnostics.effect_metric_contract import (  # noqa: E402
    effect_metric_contract_payload,
    gated_effect_metric_names,
    not_gated_effect_metric_names,
)

DEFAULT_BASELINE_SUMMARY = (
    PACKAGE_ROOT
    / "baselines"
    / "shelf_aware_turn_cost_20260617"
    / "summary.json"
)
DEFAULT_EXPECTED_BASELINE_CASE_COUNT = 19


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str]], CommandResult]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PACKAGE_ROOT / "output" / "candidate_baselines",
        help="候选基线输出根目录。",
    )
    parser.add_argument(
        "--baseline-summary",
        type=Path,
        default=DEFAULT_BASELINE_SUMMARY,
        help="用于同口径比较的既有候选基线 summary.json。",
    )
    parser.add_argument("--project-name", action="append", help="只运行指定项目，可重复；默认三项目全区域。")
    parser.add_argument("--area-id", action="append", type=int, help="只运行指定 area_id，可重复；默认项目内全部区域。")
    parser.add_argument("--coverage-epsilon", type=float, default=0.0, help="允许 coverage_ratio 下降的最大值。")
    parser.add_argument("--narrow-coverage-epsilon", type=float, default=0.0, help="允许 narrow_coverage_ratio 下降的最大值。")
    parser.add_argument("--allow-count-increase", type=int, default=0, help="允许计数类风险指标增加的最大整数值。")
    parser.add_argument(
        "--expected-baseline-case-count",
        type=int,
        default=DEFAULT_EXPECTED_BASELINE_CASE_COUNT,
        help="要求 baseline summary 的 case 数。默认 19；传 0 表示局部预检时不检查。",
    )
    parser.add_argument(
        "--no-require-path-identity",
        action="store_true",
        help="关闭路径点哈希一致性要求；只应在行为改变批次中显式使用。",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印候选批量命令，不运行、不写候选基线。")
    return parser.parse_args()


def _default_runner(command: Sequence[str]) -> CommandResult:
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    return CommandResult(returncode=int(completed.returncode), stdout=completed.stdout, stderr=completed.stderr)


def build_candidate_batch_command(
    *,
    output_root: Path,
    project_names: Sequence[str] = (),
    area_ids: Sequence[int] = (),
) -> list[str]:
    command = [
        sys.executable,
        str(PACKAGE_ROOT / "scripts" / "baseline" / "run_shelf_aware_all_areas.py"),
        "--planner-mode",
        "shelf_aware_turn_cost",
        "--output-root",
        str(Path(output_root).expanduser()),
    ]
    for project_name in project_names:
        command.extend(["--project-name", str(project_name)])
    for area_id in area_ids:
        command.extend(["--area-id", str(int(area_id))])
    return command


def _extract_candidate_run_dir(stdout: str) -> Path | None:
    for line in reversed([item.strip() for item in stdout.splitlines() if item.strip()]):
        path = Path(line).expanduser()
        if path.is_dir():
            return path
    return None


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def _summary_sha256(path: Path) -> str:
    payload = _load_json(path)
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _stable_payload_sha256(payload: Any) -> str:
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _summary_case_count(summary: dict[str, Any]) -> int:
    return int(summary.get("area_count", len(summary.get("areas", []))) or len(summary.get("areas", [])))


def _baseline_fingerprint(path: Path) -> dict[str, Any]:
    summary_path = Path(path).expanduser()
    summary = _load_json(summary_path)
    snapshot = build_snapshot(summary)
    path_hashes = [
        {
            "case_key": str(area.get("case_key", "")),
            "final_path_pixels_sha256": area.get("final_path_pixels_sha256"),
        }
        for area in sorted(snapshot.get("areas", []), key=lambda item: str(item.get("case_key", "")))
    ]
    missing_path_count = sum(1 for item in path_hashes if not item["final_path_pixels_sha256"])
    available_path_hashes = [item for item in path_hashes if item["final_path_pixels_sha256"]]
    return {
        "baseline_summary_sha256": _summary_sha256(summary_path),
        "baseline_case_count": _summary_case_count(summary),
        "baseline_path_pixels_count": len(available_path_hashes),
        "baseline_path_pixels_missing_count": int(missing_path_count),
        "baseline_path_pixels_bundle_sha256": _stable_payload_sha256(path_hashes) if missing_path_count == 0 else "",
        "baseline_run_id": summary_path.parent.name,
    }


def _write_gate_summary(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _comparison_summary(comparison: dict[str, Any] | None) -> dict[str, Any]:
    if comparison is None:
        return {
            "case_count": None,
            "path_identity_pass_count": None,
            "not_available_metrics": [],
            "unknown_metrics": [],
            "not_gated_metric_status_summary": {},
        }
    path_identity_pass_count = sum(1 for case in comparison.get("cases", []) if case.get("path_identity_status") == "pass")
    not_available_metrics = sorted(
        {
            str(metric.get("metric"))
            for case in comparison.get("cases", [])
            for metric in case.get("metric_results", [])
            if metric.get("status") == "not_available"
        }
    )
    unknown_metrics = sorted(
        {
            str(metric.get("metric"))
            for case in comparison.get("cases", [])
            for metric in case.get("metric_results", [])
            if metric.get("status") == "unknown"
        }
    )
    not_gated_metrics = tuple(str(metric) for metric in comparison.get("gate", {}).get("not_gated_metrics", []))
    metric_status_summary = comparison.get("metric_status_summary", {})
    if not isinstance(metric_status_summary, dict):
        metric_status_summary = {}
    return {
        "case_count": int(comparison.get("case_count", 0) or 0),
        "path_identity_pass_count": int(path_identity_pass_count),
        "not_available_metrics": not_available_metrics,
        "unknown_metrics": unknown_metrics,
        "not_gated_metric_status_summary": {
            metric: dict(metric_status_summary.get(metric, {}))
            for metric in not_gated_metrics
        },
    }


def _effect_gate_contract_payload(config: EffectGateConfig) -> dict[str, Any]:
    return {
        "require_path_identity": bool(config.require_path_identity),
        "coverage_epsilon": float(config.coverage_epsilon),
        "narrow_coverage_epsilon": float(config.narrow_coverage_epsilon),
        "allow_count_increase": int(config.allow_count_increase),
        "gated_metrics": list(gated_effect_metric_names()),
        "not_gated_metrics": list(not_gated_effect_metric_names()),
        "metric_contract": effect_metric_contract_payload(),
    }


def run_candidate_baseline_gate(
    *,
    output_root: Path,
    baseline_summary_path: Path,
    project_names: Sequence[str] = (),
    area_ids: Sequence[int] = (),
    gate_config: EffectGateConfig,
    expected_baseline_case_count: int | None = DEFAULT_EXPECTED_BASELINE_CASE_COUNT,
    command_runner: CommandRunner = _default_runner,
) -> dict[str, Any]:
    output_root = Path(output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    command = build_candidate_batch_command(output_root=output_root, project_names=project_names, area_ids=area_ids)
    if not Path(baseline_summary_path).expanduser().is_file():
        failed_run_dir = output_root / ("gate_failed_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        payload = {
            "runner": "run_candidate_baseline_gate",
            "status": "fail",
            "failure_reason": "baseline_summary_missing",
            "candidate_runner_returncode": None,
            "candidate_batch_command": list(command),
            "candidate_run_dir": str(failed_run_dir),
            "candidate_summary": "",
            "baseline_summary": str(Path(baseline_summary_path).expanduser()),
            "effect_snapshot_dir": "",
            "comparison_status": "",
            "comparison_fail_count": None,
            "comparison_warn_count": None,
            "comparison_case_count": None,
            "path_identity_pass_count": None,
            "not_available_metrics": [],
            "unknown_metrics": [],
            "not_gated_metric_status_summary": {},
            "gated_metrics": list(gated_effect_metric_names()),
            "not_gated_metrics": list(not_gated_effect_metric_names()),
            "gate": _effect_gate_contract_payload(gate_config),
            "stdout_tail": [],
            "stderr_tail": [],
        }
        _write_gate_summary(failed_run_dir / "candidate_baseline_gate_summary.json", payload)
        return payload
    baseline_fingerprint = _baseline_fingerprint(Path(baseline_summary_path))
    expected_count = int(expected_baseline_case_count or 0)
    if expected_count > 0 and int(baseline_fingerprint["baseline_case_count"]) != expected_count:
        failed_run_dir = output_root / ("gate_failed_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        payload = {
            "runner": "run_candidate_baseline_gate",
            "status": "fail",
            "failure_reason": "baseline_case_count_mismatch",
            "candidate_runner_returncode": None,
            "candidate_batch_command": list(command),
            "candidate_run_dir": str(failed_run_dir),
            "candidate_summary": "",
            "baseline_summary": str(Path(baseline_summary_path).expanduser()),
            **baseline_fingerprint,
            "expected_baseline_case_count": expected_count,
            "effect_snapshot_dir": "",
            "comparison_status": "",
            "comparison_fail_count": None,
            "comparison_warn_count": None,
            "comparison_case_count": None,
            "path_identity_pass_count": None,
            "not_available_metrics": [],
            "unknown_metrics": [],
            "not_gated_metric_status_summary": {},
            "gated_metrics": list(gated_effect_metric_names()),
            "not_gated_metrics": list(not_gated_effect_metric_names()),
            "gate": _effect_gate_contract_payload(gate_config),
            "stdout_tail": [],
            "stderr_tail": [],
        }
        _write_gate_summary(failed_run_dir / "candidate_baseline_gate_summary.json", payload)
        return payload
    if expected_count > 0 and int(baseline_fingerprint["baseline_path_pixels_missing_count"]) > 0:
        failed_run_dir = output_root / ("gate_failed_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        payload = {
            "runner": "run_candidate_baseline_gate",
            "status": "fail",
            "failure_reason": "baseline_path_pixels_missing",
            "candidate_runner_returncode": None,
            "candidate_batch_command": list(command),
            "candidate_run_dir": str(failed_run_dir),
            "candidate_summary": "",
            "baseline_summary": str(Path(baseline_summary_path).expanduser()),
            **baseline_fingerprint,
            "expected_baseline_case_count": expected_count,
            "effect_snapshot_dir": "",
            "comparison_status": "",
            "comparison_fail_count": None,
            "comparison_warn_count": None,
            "comparison_case_count": None,
            "path_identity_pass_count": None,
            "not_available_metrics": [],
            "unknown_metrics": [],
            "not_gated_metric_status_summary": {},
            "gated_metrics": list(gated_effect_metric_names()),
            "not_gated_metrics": list(not_gated_effect_metric_names()),
            "gate": _effect_gate_contract_payload(gate_config),
            "stdout_tail": [],
            "stderr_tail": [],
        }
        _write_gate_summary(failed_run_dir / "candidate_baseline_gate_summary.json", payload)
        return payload
    command_result = command_runner(command)
    candidate_run_dir = _extract_candidate_run_dir(command_result.stdout)
    if candidate_run_dir is None:
        candidate_run_dir = output_root / ("gate_failed_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        candidate_run_dir.mkdir(parents=True, exist_ok=True)
    candidate_summary_path = candidate_run_dir / "summary.json"
    effect_snapshot_dir = candidate_run_dir / "effect_snapshot_against_fixed_candidate_baseline"
    comparison: dict[str, Any] | None = None
    gate_status = "fail"
    failure_reason = ""
    if not candidate_summary_path.is_file():
        failure_reason = "candidate_summary_missing"
    elif not Path(baseline_summary_path).expanduser().is_file():
        failure_reason = "baseline_summary_missing"
    else:
        outputs = write_snapshot_outputs(
            candidate_summary=_load_json(candidate_summary_path),
            baseline_summary=_load_json(Path(baseline_summary_path).expanduser()),
            gate_config=gate_config,
            output_dir=effect_snapshot_dir,
        )
        comparison = outputs["comparison"]
        if command_result.returncode != 0:
            failure_reason = "candidate_batch_failed"
        elif comparison is not None and comparison.get("status") == "fail":
            failure_reason = "effect_gate_failed"
        elif comparison is not None and comparison.get("status") == "warn":
            gate_status = "warn"
            failure_reason = "effect_gate_warn"
        else:
            gate_status = "pass"
    comparison_meta = _comparison_summary(comparison)
    payload = {
        "runner": "run_candidate_baseline_gate",
        "status": gate_status,
        "failure_reason": failure_reason,
        "candidate_runner_returncode": int(command_result.returncode),
        "candidate_batch_command": list(command),
        "candidate_run_dir": str(candidate_run_dir),
        "candidate_summary": str(candidate_summary_path) if candidate_summary_path.is_file() else "",
        "baseline_summary": str(Path(baseline_summary_path).expanduser()),
        **baseline_fingerprint,
        "expected_baseline_case_count": expected_count if expected_count > 0 else None,
        "effect_snapshot_dir": str(effect_snapshot_dir) if effect_snapshot_dir.exists() else "",
        "comparison_status": comparison.get("status") if comparison else "",
        "comparison_fail_count": comparison.get("fail_count") if comparison else None,
        "comparison_warn_count": comparison.get("warn_count") if comparison else None,
        "comparison_case_count": comparison_meta["case_count"],
        "path_identity_pass_count": comparison_meta["path_identity_pass_count"],
        "not_available_metrics": comparison_meta["not_available_metrics"],
        "unknown_metrics": comparison_meta["unknown_metrics"],
        "not_gated_metric_status_summary": comparison_meta["not_gated_metric_status_summary"],
        "gated_metrics": list(gated_effect_metric_names()),
        "not_gated_metrics": list(not_gated_effect_metric_names()),
        "gate": _effect_gate_contract_payload(gate_config),
        "stdout_tail": command_result.stdout.splitlines()[-20:],
        "stderr_tail": command_result.stderr.splitlines()[-20:],
    }
    _write_gate_summary(candidate_run_dir / "candidate_baseline_gate_summary.json", payload)
    return payload


def main() -> None:
    args = parse_args()
    if args.dry_run:
        command = build_candidate_batch_command(
            output_root=Path(args.output_root),
            project_names=tuple(args.project_name or ()),
            area_ids=tuple(int(value) for value in (args.area_id or ())),
        )
        print(" ".join(command))
        return
    payload = run_candidate_baseline_gate(
        output_root=Path(args.output_root),
        baseline_summary_path=Path(args.baseline_summary),
        project_names=tuple(args.project_name or ()),
        area_ids=tuple(int(value) for value in (args.area_id or ())),
        gate_config=EffectGateConfig(
            require_path_identity=not bool(args.no_require_path_identity),
            coverage_epsilon=float(args.coverage_epsilon),
            narrow_coverage_epsilon=float(args.narrow_coverage_epsilon),
            allow_count_increase=int(args.allow_count_increase),
        ),
        expected_baseline_case_count=int(args.expected_baseline_case_count or 0) or None,
    )
    print(payload["candidate_run_dir"])
    print(payload["status"])
    if payload["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
