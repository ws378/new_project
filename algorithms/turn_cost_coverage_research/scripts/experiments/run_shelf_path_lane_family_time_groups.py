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
    analyze_lane_family_time_groups,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读拆解 lane family 空间窗口内的时间连续 stroke group。")
    parser.add_argument("--inspection-summary", required=True, help="run_shelf_path_lane_window_inspection.py 输出的 summary.json。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="输出根目录。")
    parser.add_argument("--max-segment-gap", type=int, default=3, help="同一时间连续 group 内允许的最大 segment index 间隔。")
    parser.add_argument("--min-segments-for-review", type=int, default=3, help="可进入后续 strip group 复核的最小 segment 数。")
    parser.add_argument("--ready-only", action="store_true", help="只分析 ready_for_review 窗口；默认分析全部 lane issue windows。")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _report(analyses: list[dict[str, Any]]) -> str:
    lines = [
        "# lane family 时间连续 group 拆解",
        "",
        "该报告只做空间窗口内的时间连续性拆解，不移动、不删除、不重连路径点。",
        "",
        "## 窗口汇总",
        "",
        "| window | readiness | status | groups | review candidates | covered segments | full span | density |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for analysis in analyses:
        lines.append(
            "| {window_id} | {rebuild_readiness} | {status} | {group_count} | {review_candidate_count} | {total_covered_segment_count} | {full_segment_span} | {full_segment_density:.3f} |".format(
                **analysis
            )
        )
    lines.extend(
        [
            "",
            "## group 明细",
            "",
            "| window | group | status | action | reason | segment range | segments | lane | strokes | roles | source | density |",
            "| --- | ---: | --- | --- | --- | --- | ---: | --- | --- | --- | --- | ---: |",
        ]
    )
    for analysis in analyses:
        for group in analysis.get("groups", []):
            lines.append(
                "| {window_id} | {group_id} | {status} | {next_review_action} | {reason} | {start_segment_index}-{end_segment_index} | {covered_segment_count} | {lanes} | {strokes} | {roles} | {source} | {segment_density:.3f} |".format(
                    window_id=analysis.get("window_id"),
                    group_id=group.get("group_id"),
                    status=group.get("status"),
                    next_review_action=group.get("next_review_action"),
                    reason=group.get("reason"),
                    start_segment_index=group.get("start_segment_index"),
                    end_segment_index=group.get("end_segment_index"),
                    covered_segment_count=group.get("covered_segment_count"),
                    lanes=",".join(str(value) for value in group.get("lane_ids", [])) or "无",
                    strokes=",".join(str(value) for value in group.get("stroke_ids", [])) or "无",
                    roles=",".join(str(value) for value in group.get("fragment_roles", [])) or "无",
                    source=group.get("source_evidence_level"),
                    segment_density=float(group.get("segment_density", 0.0)),
                )
            )
    lines.extend(
        [
            "",
            "判断口径：",
            "",
            "- `review_candidate` 只表示该 group 时间上较连续、纯 coverage_core、长度达到下游 strip 复核的最低前置条件。",
            "- 该状态不是优化成功，也不代表可以直接重连；后续仍需要覆盖率、窄通道、碰撞、转角、长跳、局部线距和 provenance 守卫。",
            "- `not_ready` / `review_only` group 不应被强行纳入 strip 重建，否则会把空间问题误处理成大范围 tour 重排。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    summary_path = Path(args.inspection_summary).expanduser().resolve()
    inspection_summary = _load_json(summary_path)
    analyses = [
        analyze_lane_family_time_groups(
            inspection,
            max_segment_gap=int(args.max_segment_gap),
            min_segments_for_review=int(args.min_segments_for_review),
        ).to_dict()
        for inspection in inspection_summary.get("inspections", [])
        if not bool(args.ready_only) or str(inspection.get("rebuild_readiness")) == "ready_for_review"
    ]

    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_path_lane_family_time_groups")
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "lane_family_time_groups.md"
    report_path.write_text(_report(analyses), encoding="utf-8")
    payload = {
        "case_group": "shelf_path_lane_family_time_groups",
        "status": "success",
        "input": {
            "inspection_summary": str(summary_path),
            "scope": "ready_windows_only" if bool(args.ready_only) else "all_lane_issue_windows",
            "max_segment_gap": int(args.max_segment_gap),
            "min_segments_for_review": int(args.min_segments_for_review),
        },
        "algorithm_scope": {
            "type": "readonly_time_continuity_grouping",
            "description": "只拆解 lane family 空间窗口内的时间连续 group，不移动、不删除、不重连路径点。",
        },
        "analysis_count": len(analyses),
        "review_candidate_count": sum(int(item.get("review_candidate_count", 0)) for item in analyses),
        "rebuild_candidate_count": sum(int(item.get("review_candidate_count", 0)) for item in analyses),
        "analyses": analyses,
        "artifacts": {
            "report": str(report_path),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
