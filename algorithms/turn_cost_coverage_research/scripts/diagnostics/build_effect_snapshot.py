"""构建覆盖路径效果快照，并可与既有 baseline 做只读对比。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PACKAGE_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.turn_cost_coverage_research.scripts.diagnostics.effect_metric_contract import (  # noqa: E402
    effect_metric_contract_payload,
    effect_metric_names,
    gated_effect_metric_names,
    higher_is_better_effect_metric_names,
    lower_is_better_effect_metric_names,
    not_gated_effect_metric_names,
)

AREA_ID_KEYS = ("project_name", "area_id")
SNAPSHOT_METRICS = effect_metric_names()
GATED_SNAPSHOT_METRICS = gated_effect_metric_names()
NOT_GATED_SNAPSHOT_METRICS = not_gated_effect_metric_names()
HIGHER_IS_BETTER_METRICS = higher_is_better_effect_metric_names()
LOWER_IS_BETTER_METRICS = lower_is_better_effect_metric_names()


@dataclass(frozen=True)
class EffectGateConfig:
    require_path_identity: bool
    coverage_epsilon: float
    narrow_coverage_epsilon: float
    allow_count_increase: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-summary", type=Path, required=True, help="候选批量 summary.json。")
    parser.add_argument("--baseline-summary", type=Path, help="可选 baseline 批量 summary.json。")
    parser.add_argument("--output-dir", type=Path, required=True, help="输出目录。")
    parser.add_argument(
        "--require-path-identity",
        action="store_true",
        help="要求同一项目同一区域的 final_path_pixels 文件内容哈希完全一致，适用于 P1/P2 行为不变重构。",
    )
    parser.add_argument("--coverage-epsilon", type=float, default=0.0, help="允许 coverage_ratio 下降的最大值。")
    parser.add_argument("--narrow-coverage-epsilon", type=float, default=0.0, help="允许 narrow_coverage_ratio 下降的最大值。")
    parser.add_argument("--allow-count-increase", type=int, default=0, help="允许计数类风险指标增加的最大整数值。")
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def _resolve_data_path(path_text: str) -> Path:
    path = Path(str(path_text)).expanduser()
    if path.is_absolute():
        return path
    if path.is_file():
        return path
    return REPO_ROOT / path


def _case_key(record: dict[str, Any]) -> str:
    return f"{record.get('project_name')}#area{int(record.get('area_id'))}"


def _hash_json_file(path_text: str | None) -> str | None:
    if not path_text:
        return None
    path = _resolve_data_path(str(path_text))
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        content = path.read_bytes()
    else:
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _final_path_pixels_path(record: dict[str, Any]) -> str:
    explicit_path = str(record.get("final_path_pixels", "") or "")
    if explicit_path:
        return explicit_path
    area_run_dir = str(record.get("area_run_dir", "") or "")
    if not area_run_dir:
        return ""
    candidate = Path(area_run_dir).expanduser() / "path_pixels.json"
    return str(candidate) if candidate.is_file() else ""


def _metric_value(record: dict[str, Any], key: str) -> float | int | None:
    value = record.get(key)
    if value is None or value == "":
        return None
    if key.endswith("_count"):
        return int(value)
    return float(value)


def build_snapshot(summary: dict[str, Any]) -> dict[str, Any]:
    areas = []
    for record in summary.get("areas", []):
        metrics = {key: _metric_value(record, key) for key in SNAPSHOT_METRICS}
        areas.append(
            {
                "project_name": record.get("project_name"),
                "area_id": int(record.get("area_id")),
                "case_key": _case_key(record),
                "status": record.get("status"),
                "returncode": int(record.get("returncode", 0) or 0),
                "area_run_dir": record.get("area_run_dir", ""),
                "final_diagnostics_run_dir": record.get("final_diagnostics_run_dir", ""),
                "final_path_pixels": _final_path_pixels_path(record),
                "final_path_pixels_sha256": _hash_json_file(_final_path_pixels_path(record)),
                "metrics": metrics,
            }
        )
    metric_summary: dict[str, dict[str, float | int | None]] = {}
    for key in SNAPSHOT_METRICS:
        values = [area["metrics"][key] for area in areas if area["metrics"].get(key) is not None]
        if not values:
            metric_summary[key] = {"min": None, "max": None, "mean": None}
            continue
        metric_summary[key] = {
            "min": min(values),
            "max": max(values),
            "mean": float(sum(float(value) for value in values) / len(values)),
        }
    return {
        "source_runner": summary.get("runner"),
        "source_case_group": summary.get("case_group"),
        "node_generation_mode": summary.get("node_generation_mode"),
        "repaired_grid_max_offset_factor": summary.get("repaired_grid_max_offset_factor"),
        "batch_reconnect_passes": summary.get("batch_reconnect_passes"),
        "batch_reconnect_max_candidates": summary.get("batch_reconnect_max_candidates"),
        "area_count": int(summary.get("area_count", len(areas)) or len(areas)),
        "success_count": int(summary.get("success_count", 0) or 0),
        "failed_count": int(summary.get("failed_count", 0) or 0),
        "metric_contract": effect_metric_contract_payload(),
        "metric_summary": metric_summary,
        "areas": areas,
    }


def _compare_metric(
    *,
    key: str,
    baseline: float | int | None,
    candidate: float | int | None,
    config: EffectGateConfig,
) -> dict[str, Any]:
    if baseline is None and candidate is None:
        return {"metric": key, "status": "not_available", "baseline": baseline, "candidate": candidate, "delta": None}
    if baseline is None or candidate is None:
        return {"metric": key, "status": "unknown", "baseline": baseline, "candidate": candidate, "delta": None}
    delta = float(candidate) - float(baseline)
    if key == "coverage_ratio":
        passed = delta >= -float(config.coverage_epsilon)
    elif key == "narrow_coverage_ratio":
        passed = delta >= -float(config.narrow_coverage_epsilon)
    else:
        passed = delta <= float(config.allow_count_increase)
    return {
        "metric": key,
        "status": "pass" if passed else "fail",
        "baseline": baseline,
        "candidate": candidate,
        "delta": delta,
    }


def _metric_status_summary(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for metric in SNAPSHOT_METRICS:
        summary[metric] = {
            "gated": metric in GATED_SNAPSHOT_METRICS,
            "status_counts": {
                "pass": 0,
                "fail": 0,
                "unknown": 0,
                "not_available": 0,
            },
            "baseline_available_count": 0,
            "candidate_available_count": 0,
        }
    for case in cases:
        for result in case.get("metric_results", []):
            metric = str(result.get("metric", ""))
            if metric not in summary:
                continue
            status = str(result.get("status", "unknown"))
            status_counts = summary[metric]["status_counts"]
            if status not in status_counts:
                status_counts[status] = 0
            status_counts[status] += 1
            if result.get("baseline") is not None:
                summary[metric]["baseline_available_count"] += 1
            if result.get("candidate") is not None:
                summary[metric]["candidate_available_count"] += 1
    return summary


def compare_snapshots(
    *,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    config: EffectGateConfig,
) -> dict[str, Any]:
    baseline_by_key = {str(area["case_key"]): area for area in baseline.get("areas", [])}
    candidate_by_key = {str(area["case_key"]): area for area in candidate.get("areas", [])}
    all_keys = sorted(set(baseline_by_key) | set(candidate_by_key))
    cases: list[dict[str, Any]] = []
    fail_count = 0
    warn_count = 0
    for key in all_keys:
        base_area = baseline_by_key.get(key)
        cand_area = candidate_by_key.get(key)
        if base_area is None or cand_area is None:
            cases.append(
                {
                    "case_key": key,
                    "status": "fail",
                    "reason": "missing_candidate_case" if cand_area is None else "missing_baseline_case",
                }
            )
            fail_count += 1
            continue
        metric_results = [
            _compare_metric(
                key=metric,
                baseline=base_area["metrics"].get(metric),
                candidate=cand_area["metrics"].get(metric),
                config=config,
            )
            for metric in SNAPSHOT_METRICS
        ]
        case_failures = [
            item
            for item in metric_results
            if item["status"] == "fail" and item["metric"] in GATED_SNAPSHOT_METRICS
        ]
        case_unknowns = [
            item
            for item in metric_results
            if item["status"] == "unknown" and item["metric"] in GATED_SNAPSHOT_METRICS
        ]
        path_identity_status = "not_required"
        if config.require_path_identity:
            path_identity_status = (
                "pass"
                if base_area.get("final_path_pixels_sha256") and base_area.get("final_path_pixels_sha256") == cand_area.get("final_path_pixels_sha256")
                else "fail"
            )
        status = "pass"
        if case_failures or path_identity_status == "fail" or cand_area.get("status") != "success":
            status = "fail"
            fail_count += 1
        elif case_unknowns:
            status = "warn"
            warn_count += 1
        cases.append(
            {
                "case_key": key,
                "project_name": cand_area.get("project_name"),
                "area_id": cand_area.get("area_id"),
                "status": status,
                "candidate_status": cand_area.get("status"),
                "path_identity_status": path_identity_status,
                "metric_results": metric_results,
            }
        )
    return {
        "status": "fail" if fail_count else ("warn" if warn_count else "pass"),
        "fail_count": int(fail_count),
        "warn_count": int(warn_count),
        "case_count": int(len(cases)),
        "gate": {
            "require_path_identity": bool(config.require_path_identity),
            "coverage_epsilon": float(config.coverage_epsilon),
            "narrow_coverage_epsilon": float(config.narrow_coverage_epsilon),
            "allow_count_increase": int(config.allow_count_increase),
            "gated_metrics": list(GATED_SNAPSHOT_METRICS),
            "not_gated_metrics": list(NOT_GATED_SNAPSHOT_METRICS),
            "metric_contract": effect_metric_contract_payload(),
        },
        "metric_status_summary": _metric_status_summary(cases),
        "cases": cases,
    }


def _write_comparison_csv(path: Path, comparison: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.writer(file_obj)
        writer.writerow(["case_key", "status", "path_identity_status", "metric", "baseline", "candidate", "delta", "metric_status"])
        for case in comparison.get("cases", []):
            for metric in case.get("metric_results", []):
                writer.writerow(
                    [
                        case.get("case_key"),
                        case.get("status"),
                        case.get("path_identity_status"),
                        metric.get("metric"),
                        metric.get("baseline"),
                        metric.get("candidate"),
                        metric.get("delta"),
                        metric.get("status"),
                    ]
                )


def _write_markdown(path: Path, snapshot: dict[str, Any], comparison: dict[str, Any] | None) -> None:
    lines = [
        "# 覆盖路径效果快照",
        "",
        "## 候选概况",
        "",
        f"- 区域数量：`{snapshot['area_count']}`",
        f"- 成功数量：`{snapshot['success_count']}`",
        f"- 失败数量：`{snapshot['failed_count']}`",
        f"- 节点生成模式：`{snapshot.get('node_generation_mode')}`",
        f"- repaired_grid_max_offset_factor：`{snapshot.get('repaired_grid_max_offset_factor')}`",
        "",
        "## 指标汇总",
        "",
        "| 指标 | 最小值 | 最大值 | 平均值 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key in SNAPSHOT_METRICS:
        item = snapshot["metric_summary"].get(key, {})
        lines.append(f"| `{key}` | {item.get('min')} | {item.get('max')} | {item.get('mean')} |")
    if comparison is not None:
        lines.extend(
            [
                "",
                "## 基线对比结论",
                "",
                f"- 总状态：`{comparison['status']}`",
                f"- 失败区域数：`{comparison['fail_count']}`",
                f"- 警告区域数：`{comparison['warn_count']}`",
                "",
                "| 区域 | 状态 | 路径一致性 | 失败指标 |",
                "| --- | --- | --- | --- |",
            ]
        )
        for case in comparison.get("cases", []):
            failed_metrics = [item["metric"] for item in case.get("metric_results", []) if item.get("status") == "fail"]
            lines.append(
                f"| `{case.get('case_key')}` | `{case.get('status')}` | `{case.get('path_identity_status')}` | "
                f"{', '.join(failed_metrics) if failed_metrics else '-'} |"
            )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_snapshot_outputs(
    *,
    candidate_summary: dict[str, Any],
    output_dir: Path,
    baseline_summary: dict[str, Any] | None = None,
    gate_config: EffectGateConfig | None = None,
) -> dict[str, Any]:
    """写出效果快照产物，并在提供 baseline 时写出对比产物。"""

    candidate_snapshot = build_snapshot(candidate_summary)
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = None
    if baseline_summary is not None:
        if gate_config is None:
            raise ValueError("gate_config is required when baseline_summary is provided")
        baseline_snapshot = build_snapshot(baseline_summary)
        comparison = compare_snapshots(
            baseline=baseline_snapshot,
            candidate=candidate_snapshot,
            config=gate_config,
        )
        (output_dir / "effect_comparison.json").write_text(
            json.dumps(comparison, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _write_comparison_csv(output_dir / "effect_comparison.csv", comparison)
    (output_dir / "effect_snapshot.json").write_text(
        json.dumps(candidate_snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_markdown(output_dir / "效果快照.md", candidate_snapshot, comparison)
    return {"snapshot": candidate_snapshot, "comparison": comparison}


def main() -> None:
    args = parse_args()
    candidate_summary = _load_json(args.candidate_summary)
    output_dir = Path(args.output_dir).expanduser().resolve()
    baseline_summary = None
    gate_config = None
    if args.baseline_summary:
        baseline_summary = _load_json(args.baseline_summary)
        gate_config = EffectGateConfig(
            require_path_identity=bool(args.require_path_identity),
            coverage_epsilon=float(args.coverage_epsilon),
            narrow_coverage_epsilon=float(args.narrow_coverage_epsilon),
            allow_count_increase=int(args.allow_count_increase),
        )
    outputs = write_snapshot_outputs(
        candidate_summary=candidate_summary,
        baseline_summary=baseline_summary,
        gate_config=gate_config,
        output_dir=output_dir,
    )
    print(output_dir)
    comparison = outputs["comparison"]
    if comparison is not None and comparison["status"] == "fail":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
