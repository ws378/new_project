from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.turn_cost_coverage_research.src.experiments.path_lane_family_reconstruction import (  # noqa: E402
    rank_lane_family_time_group_candidates,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读排序 lane family 时间连续 strip group 复核候选。")
    parser.add_argument("--time-groups-summary", required=True, help="run_shelf_path_lane_family_time_groups.py 输出的 summary.json。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="输出根目录。")
    parser.add_argument("--adjacency-gap", type=int, default=3, help="判断 connector/mixed 邻接风险的最大 segment gap。")
    parser.add_argument("--min-preferred-segments", type=int, default=5, help="低风险候选偏好的最小连续 segment 数。")
    parser.add_argument("--top-count", type=int, default=30, help="报告展示的候选数量。")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _report(candidates: list[dict[str, Any]], *, top_count: int, status_counts: dict[str, int]) -> str:
    lines = [
        "# lane family 时间连续 group 复核候选排序",
        "",
        "该报告只排序可复核的时间连续 coverage_core group，不生成路径，不移动、不删除、不重连路径点。",
        "",
        "## 状态统计",
        "",
        "| status | count |",
        "| --- | ---: |",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"| {status} | {count} |")
    lines.extend(
        [
            "",
            "## top candidates",
            "",
            "| rank | window | group | status | score | segment range | segments | lanes | strokes | adjacency |",
            "| ---: | ---: | ---: | --- | ---: | --- | ---: | --- | --- | --- |",
        ]
    )
    for item in candidates[: int(top_count)]:
        adjacency = f"connector={item['connector_adjacency_count']},mixed={item['mixed_adjacency_count']}"
        lines.append(
            "| {candidate_rank} | {window_id} | {group_id} | {status} | {priority_score:.2f} | {start_segment_index}-{end_segment_index} | {covered_segment_count} | {lanes} | {strokes} | {adjacency} |".format(
                candidate_rank=item["candidate_rank"],
                window_id=item["window_id"],
                group_id=item["group_id"],
                status=item["status"],
                priority_score=float(item["priority_score"]),
                start_segment_index=item["start_segment_index"],
                end_segment_index=item["end_segment_index"],
                covered_segment_count=item["covered_segment_count"],
                lanes=",".join(str(value) for value in item.get("lane_ids", [])) or "无",
                strokes=",".join(str(value) for value in item.get("stroke_ids", [])) or "无",
                adjacency=adjacency,
            )
        )
    lines.extend(
        [
            "",
            "说明：",
            "",
            "- `low_risk_strip_review_candidate` 只表示下一步可以优先做离线可行性评估，不等于可直接替换路径。",
            "- `short_review_candidate`、`mixed_adjacent_review_candidate`、`connector_adjacent_review_candidate` 不应优先生成真实路径候选。",
            "- 排序不含 area / window 专用规则，只使用时间连续性、segment 数、density 和非 coverage 邻接风险。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    summary_path = Path(args.time_groups_summary).expanduser().resolve()
    time_groups = _load_json(summary_path)
    candidates = [
        item.to_dict()
        for item in rank_lane_family_time_group_candidates(
            time_groups.get("analyses", []),
            adjacency_gap=int(args.adjacency_gap),
            min_preferred_segments=int(args.min_preferred_segments),
        )
    ]
    status_counts = Counter(str(item["status"]) for item in candidates)

    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_path_lane_family_time_group_candidates")
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "lane_family_time_group_candidates.md"
    report_path.write_text(
        _report(candidates, top_count=int(args.top_count), status_counts=dict(status_counts)),
        encoding="utf-8",
    )
    payload = {
        "case_group": "shelf_path_lane_family_time_group_candidates",
        "status": "success",
        "input": {
            "time_groups_summary": str(summary_path),
            "adjacency_gap": int(args.adjacency_gap),
            "min_preferred_segments": int(args.min_preferred_segments),
            "top_count": int(args.top_count),
        },
        "algorithm_scope": {
            "type": "readonly_time_group_candidate_ranking",
            "description": "只排序时间连续 coverage_core group 复核候选，不生成路径，不移动、不删除、不重连路径点。",
        },
        "candidate_count": len(candidates),
        "status_counts": dict(status_counts),
        "top_candidates": candidates[: int(args.top_count)],
        "all_candidates": candidates,
        "artifacts": {
            "report": str(report_path),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
