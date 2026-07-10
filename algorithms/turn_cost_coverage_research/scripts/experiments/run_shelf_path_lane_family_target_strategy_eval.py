from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.turn_cost_coverage_research.src.experiments.path_lane_family_reconstruction import (  # noqa: E402
    evaluate_lane_family_target_strategies,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读评估 lane family 横向目标位置策略。")
    parser.add_argument("--inspection-summary", required=True, help="run_shelf_path_lane_window_inspection.py 输出的 summary.json。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="输出根目录。")
    parser.add_argument("--max-shift-factor", type=float, default=0.5, help="预测时允许的最大横向位移，单位为 coverage_width 倍率。")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _report(items: list[dict[str, Any]]) -> str:
    lines = [
        "# lane family 目标横向位置策略评估",
        "",
        "该报告只比较目标策略的预测 gap 结果，不移动、不删除、不重连路径点。",
        "",
        "| window | strategy | prediction | reason | movable | shift-limit | locked-shift | bad gaps | dense | sparse | max shift |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in items:
        lines.append(
            "| {window_id} | {strategy} | {prediction_status} | {reason} | {movable_lane_count} | {shift_exceeds_limit_count} | {locked_lane_shift_required_count} | {before_bad_gap_count}->{predicted_bad_gap_count} | {before_over_dense_count}->{predicted_over_dense_count} | {before_over_sparse_count}->{predicted_over_sparse_count} | {max_abs_shift_px:.2f} |".format(
                **item
            )
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    summary_path = Path(args.inspection_summary).expanduser().resolve()
    inspection_summary = _load_json(summary_path)
    coverage_width_px = int(inspection_summary["input"]["coverage_width_px"])
    items: list[dict[str, Any]] = []
    for inspection in inspection_summary.get("inspections", []):
        if str(inspection.get("rebuild_readiness")) != "ready_for_review":
            continue
        items.extend(
            item.to_dict()
            for item in evaluate_lane_family_target_strategies(
                inspection,
                coverage_width_px=coverage_width_px,
                max_shift_factor=float(args.max_shift_factor),
            )
        )

    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_path_lane_family_target_strategy_eval")
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "lane_family_target_strategy_eval.md"
    report_path.write_text(_report(items), encoding="utf-8")
    payload = {
        "case_group": "shelf_aware_path_lane_family_target_strategy_eval",
        "status": "success",
        "input": {
            "inspection_summary": str(summary_path),
            "coverage_width_px": int(coverage_width_px),
            "max_shift_factor": float(args.max_shift_factor),
        },
        "algorithm_scope": {
            "type": "readonly_target_strategy_eval",
            "description": "只比较 lane family 横向目标策略的预测结果，不移动、不删除、不重连路径点。",
        },
        "evaluation_count": len(items),
        "evaluations": items,
        "artifacts": {
            "report": str(report_path),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
