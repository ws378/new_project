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
    generate_lane_family_candidate_plans,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="基于 lane window inspection 生成只读 lane family 重建候选计划。")
    parser.add_argument("--inspection-summary", required=True, help="run_shelf_path_lane_window_inspection.py 输出的 summary.json。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="输出根目录。")
    parser.add_argument("--max-shift-factor", type=float, default=0.5, help="候选计划允许的最大横向位移，单位为 coverage_width 倍率。")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _report(plans: list[dict[str, Any]]) -> str:
    lines = [
        "# lane family 重建候选计划",
        "",
        "该报告只生成候选计划，不移动、不删除、不重连路径点。",
        "",
        "| window | status | reason | action | lanes | movable | locked | bad gaps | max shift |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for plan in plans:
        lines.append(
            "| {window_id} | {status} | {reason} | {recommended_action} | {lane_count} | {movable_lane_count} | {locked_lane_count} | {before_bad_gap_count}->{after_bad_gap_count} | {max_abs_shift_px:.2f} |".format(
                **plan
            )
        )
    lines.extend(
        [
            "",
            "## 异常 gap 阻断原因",
            "",
            "| window | gap | kind | next action | blockers |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for plan in plans:
        for gap in plan.get("gap_plans", []):
            if gap.get("before_kind") == "ok":
                continue
            lines.append(
                "| {window_id} | {left_lane_id}-{right_lane_id} | {before_kind}->{after_kind} | {recommended_next_action} | {blockers} |".format(
                    window_id=plan.get("window_id"),
                    left_lane_id=gap.get("left_lane_id"),
                    right_lane_id=gap.get("right_lane_id"),
                    before_kind=gap.get("before_kind"),
                    after_kind=gap.get("after_kind"),
                    recommended_next_action=gap.get("recommended_next_action"),
                    blockers=", ".join(gap.get("blocker_reasons", [])),
                )
            )
    lines.extend(
        [
            "",
            "说明：",
            "",
            "- `candidate_plan` 只是下一步可验证的候选，不代表可直接应用。",
            "- `locked` lane 通常包含 connector、fallback、mixed fragment，不能被 lane family 平移直接处理。",
            "- 真正应用前仍需覆盖率、窄通道覆盖、碰撞、长跳、转角、lane spacing 和 provenance 守卫。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    summary_path = Path(args.inspection_summary).expanduser().resolve()
    inspection_summary = _load_json(summary_path)
    coverage_width_px = int(inspection_summary["input"]["coverage_width_px"])
    inspections = list(inspection_summary.get("inspections", []))
    plans = [
        plan.to_dict()
        for plan in generate_lane_family_candidate_plans(
            inspections,
            coverage_width_px=coverage_width_px,
            max_shift_factor=float(args.max_shift_factor),
        )
    ]

    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_path_lane_family_reconstruction_candidates")
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "lane_family_reconstruction_candidates.md"
    report_path.write_text(_report(plans), encoding="utf-8")
    payload = {
        "case_group": "shelf_aware_path_lane_family_reconstruction_candidates",
        "status": "success",
        "input": {
            "inspection_summary": str(summary_path),
            "coverage_width_px": int(coverage_width_px),
            "max_shift_factor": float(args.max_shift_factor),
        },
        "algorithm_scope": {
            "type": "readonly_candidate_plan",
            "description": "只生成 lane family 局部重建候选计划，不移动、不删除、不重连路径点。",
        },
        "plan_count": len(plans),
        "candidate_plan_count": sum(1 for plan in plans if plan["status"] == "candidate_plan"),
        "plans": plans,
        "artifacts": {
            "report": str(report_path),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
