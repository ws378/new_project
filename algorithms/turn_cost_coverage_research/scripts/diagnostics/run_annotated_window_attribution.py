"""生成“人工标注窗口 -> 局部原因归因”的只读报告。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.turn_cost_coverage_research.src.diagnostics.annotated_window_attribution import (  # noqa: E402
    attribute_annotated_windows,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alignment-report-json", required=True, help="人工标注窗口对齐报告 JSON。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="输出根目录。")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _format_ranges(ranges: Sequence[dict[str, int]]) -> str:
    if not ranges:
        return "无"
    return "、".join(f"{item['start']}-{item['end']}" if item["start"] != item["end"] else str(item["start"]) for item in ranges)


def _write_markdown(path: Path, *, alignment_path: Path, attribution: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# 人工标注窗口局部原因归因报告")
    lines.append("")
    lines.append("## 报告边界")
    lines.append("")
    lines.append("- 本报告基于上一阶段对齐 JSON 进行只读归因。")
    lines.append("- `主归因` 表示当前窗口内证据最强的可疑原因，不等同确定根因。")
    lines.append("- `置信度` 表示证据强弱，不代表因果已经被证明。")
    lines.append("- 归因只对当前 `bbox_xyxy` 内命中的真实路径数据成立。")
    lines.append("- 本报告不移动点、不删点、不重连、不修改诊断阈值，也不产生新的全局质量规则。")
    lines.append("")
    lines.append("## 输入")
    lines.append("")
    lines.append(f"- 对齐报告：`{alignment_path}`")
    lines.append(f"- coverage width：`{attribution.get('coverage_width_px')} px`")
    lines.append("")
    lines.append("## 窗口归因索引")
    lines.append("")
    lines.append("| 窗口 | 主归因（最高可疑） | 置信度 | 点范围 | 主要信号 | 可疑 stroke | 可疑 candidate |")
    lines.append("|---|---|---:|---:|---|---:|---:|")
    for window in attribution.get("windows", []):
        signals = _compact_signal_text(window.get("signals", {}))
        stroke_ids = ",".join(str(item["stroke_id"]) for item in window.get("suspicious_strokes", [])) or "无"
        candidate_ids = ",".join(str(item["candidate_id"]) for item in window.get("suspicious_candidates", [])) or "无"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(window.get("title")),
                    str(window.get("attribution", {}).get("primary")),
                    str(window.get("attribution", {}).get("confidence")),
                    _format_ranges(window.get("path_point_index_ranges", [])),
                    signals,
                    stroke_ids,
                    candidate_ids,
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## 逐窗口归因")
    lines.append("")
    for window in attribution.get("windows", []):
        attrib = window.get("attribution", {})
        signals = window.get("signals", {})
        lines.append(f"### {window.get('title')}")
        lines.append("")
        lines.append(f"- bbox：`{window.get('bbox_xyxy')}`")
        lines.append(f"- 用户观察：{window.get('user_observation')}")
        lines.append(f"- 主归因（最高可疑）：{attrib.get('primary')}，置信度 `{attrib.get('confidence')}`")
        lines.append(f"- 归因标签：{attrib.get('labels')}")
        lines.append(f"- 证据原因：{attrib.get('evidence_reasons')}")
        lines.append(f"- 点范围：{_format_ranges(window.get('path_point_index_ranges', []))}")
        lines.append(f"- 线段范围：{_format_ranges(window.get('path_segment_index_ranges', []))}")
        lines.append(
            "- 数字信号："
            f"max_turn `{signals.get('max_turn_deg'):.1f}`，"
            f"turn_hotspot `{signals.get('moderate_turn_hotspots')}`，"
            f"long_jump `{signals.get('long_jump_count')}`，"
            f"infeasible `{signals.get('infeasible_segment_count')}`，"
            f"lane `{signals.get('lane_count')}`，"
            f"gap `{signals.get('lane_gap_min_px'):.1f}-{signals.get('lane_gap_max_px'):.1f}`，"
            f"crossing `{signals.get('crossing_count_from_strokes')}`，"
            f"high_risk_crossing `{signals.get('high_risk_crossing_count')}`，"
            f"fragment `{signals.get('fragment_stroke_count')}`，"
            f"connector `{signals.get('connector_stroke_count')}`，"
            f"disjoint_visit `{signals.get('disjoint_path_visit_count')}`"
        )
        if window.get("suspicious_strokes"):
            lines.append("- 可疑 stroke：")
            for stroke in window["suspicious_strokes"]:
                lines.append(
                    f"  - `stroke {stroke['stroke_id']}`："
                    f"{stroke['segment_type']} / {stroke['action_label']} / {stroke['classification']}，"
                    f"点 `{stroke.get('point_index_range')}`，"
                    f"原因 `{stroke.get('reasons')}`"
                )
        if window.get("suspicious_candidates"):
            lines.append("- 可疑 candidate：")
            for candidate in window["suspicious_candidates"]:
                lines.append(
                    f"  - `candidate {candidate['candidate_id']}`："
                    f"{candidate['candidate_kind']} / stroke `{candidate['stroke_id']}` / {candidate['classification']}，"
                    f"点 `{candidate.get('point_index_range')}`"
                )
        boundary = window.get("next_step_boundary", {})
        lines.append(f"- 后续允许：{boundary.get('allowed')}")
        lines.append(f"- 后续禁止：{boundary.get('forbidden')}")
        lines.append(f"- 范围警告：{attrib.get('scope_warning')}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _compact_signal_text(signals: dict[str, Any]) -> str:
    parts: list[str] = []
    if signals.get("high_turn"):
        parts.append(f"急转{float(signals.get('max_turn_deg', 0.0)):.0f}")
    if signals.get("infeasible_segment_count", 0):
        parts.append(f"不可行{signals.get('infeasible_segment_count')}")
    if signals.get("long_jump_count", 0):
        parts.append(f"长跳{signals.get('long_jump_count')}")
    if signals.get("dense_lane_gap") or signals.get("sparse_lane_gap"):
        parts.append(f"线距{float(signals.get('lane_gap_min_px', 0.0)):.1f}-{float(signals.get('lane_gap_max_px', 0.0)):.1f}")
    if signals.get("crossing_count_from_strokes", 0):
        parts.append(f"交叉{signals.get('crossing_count_from_strokes')}")
    if signals.get("fragment_stroke_count", 0) or signals.get("connector_stroke_count", 0):
        parts.append(f"frag/conn {signals.get('fragment_stroke_count')}/{signals.get('connector_stroke_count')}")
    if signals.get("disjoint_path_visit_count", 0) >= 3:
        parts.append(f"多次经过{signals.get('disjoint_path_visit_count')}")
    return "；".join(parts) if parts else "弱信号"


def main() -> None:
    args = parse_args()
    alignment_path = Path(args.alignment_report_json).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    alignment = _load_json(alignment_path)
    attribution = attribute_annotated_windows(alignment)
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_annotated_window_attribution")
    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / "人工标注窗口局部归因报告.json"
    md_path = run_dir / "人工标注窗口局部归因报告.md"
    json_path.write_text(json.dumps(attribution, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(md_path, alignment_path=alignment_path, attribution=attribution)
    summary = {
        "case_group": "manual_annotation_window_attribution",
        "status": "success",
        "alignment_report_json": str(alignment_path),
        "artifacts": {
            "report_json": str(json_path),
            "report_markdown": str(md_path),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
