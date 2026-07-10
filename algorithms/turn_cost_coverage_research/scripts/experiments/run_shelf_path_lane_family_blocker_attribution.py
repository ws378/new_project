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

from algorithms.turn_cost_coverage_research.src.experiments.path_lane_family_blocker_attribution import (  # noqa: E402
    attribute_blocked_gaps,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对 lane family 候选计划中的异常 gap 做只读阻断归因。")
    parser.add_argument("--candidate-summary", required=True, help="lane family reconstruction candidates 输出的 summary.json。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="输出根目录。")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _report(items: list[dict[str, Any]]) -> str:
    lines = [
        "# lane family 异常 gap 阻断归因报告",
        "",
        "该报告只读分析异常 gap 的阻断来源，不移动、不删除、不重连路径点。",
        "",
        "| window | gap | kind | attribution | evidence | next action |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in items:
        lines.append(
            "| {window_id} | {left_lane_id}-{right_lane_id} | {before_kind}->{after_kind} | {attribution} | {evidence_level} | {recommended_next_action} |".format(
                **item
            )
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    candidate_summary_path = Path(args.candidate_summary).expanduser().resolve()
    candidate_summary = _load_json(candidate_summary_path)
    inspection_summary_path = Path(str(candidate_summary["input"]["inspection_summary"])).expanduser().resolve()
    inspection_summary = _load_json(inspection_summary_path)
    items = [item.to_dict() for item in attribute_blocked_gaps(candidate_summary, inspection_summary)]
    attribution_counts: dict[str, int] = {}
    evidence_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    for item in items:
        attribution_counts[item["attribution"]] = attribution_counts.get(item["attribution"], 0) + 1
        evidence_counts[item["evidence_level"]] = evidence_counts.get(item["evidence_level"], 0) + 1
        action_counts[item["recommended_next_action"]] = action_counts.get(item["recommended_next_action"], 0) + 1

    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_path_lane_family_blocker_attribution")
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "lane_family_blocker_attribution_report.md"
    report_path.write_text(_report(items), encoding="utf-8")
    payload = {
        "case_group": "shelf_aware_path_lane_family_blocker_attribution",
        "status": "success",
        "input": {
            "candidate_summary": str(candidate_summary_path),
            "inspection_summary": str(inspection_summary_path),
        },
        "algorithm_scope": {
            "type": "readonly_attribution",
            "description": "只对 lane family 异常 gap 阻断来源做归因，不移动、不删除、不重连路径点。",
        },
        "blocked_gap_count": len(items),
        "attribution_counts": attribution_counts,
        "evidence_level_counts": evidence_counts,
        "recommended_action_counts": action_counts,
        "blocked_gaps": items,
        "artifacts": {
            "report": str(report_path),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
