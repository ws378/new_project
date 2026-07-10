"""生成“人工标注窗口 -> 真实路径数据”的只读对齐报告。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.turn_cost_coverage_research.src.diagnostics.annotated_window_alignment import (  # noqa: E402
    AnnotatedWindow,
    align_annotated_windows,
    load_annotated_windows,
)
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import Point, normalize_points  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostics-run-dir", required=True, help="已有 turn-cost 路径诊断 run 目录。")
    parser.add_argument("--window-config", required=True, help="人工标注窗口配置 JSON。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="输出根目录。")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_free_mask(summary: dict[str, Any]) -> np.ndarray:
    source = Path(summary["input"]["free_mask_source"]).expanduser().resolve()
    image = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"free mask not readable: {source}")
    return (image > 127).astype(np.uint8) * 255


def _load_path_points(summary: dict[str, Any]) -> tuple[Point, ...]:
    path = Path(summary["input"]["path_pixels"]).expanduser().resolve()
    return normalize_points(_load_json(path))


def _load_candidates(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = _load_json(path)
    return list(payload.get("all_candidates") or payload.get("top_candidates") or [])


def _draw_overlay(
    free_mask: np.ndarray,
    points: Sequence[Point],
    windows: Sequence[AnnotatedWindow],
    output_path: Path,
) -> None:
    background = np.zeros((*free_mask.shape[:2], 3), dtype=np.uint8)
    background[free_mask > 0] = (235, 235, 235)
    pixel_points = [(int(round(point[0])), int(round(point[1]))) for point in points]
    for start, end in zip(pixel_points, pixel_points[1:]):
        cv2.line(background, start, end, (0, 165, 255), 2, cv2.LINE_AA)
    for index, window in enumerate(windows, start=1):
        x0, y0, x1, y1 = (int(round(value)) for value in window.bbox_xyxy)
        cv2.rectangle(background, (x0, y0), (x1, y1), (0, 0, 255), 3, cv2.LINE_AA)
        cv2.putText(
            background,
            str(index),
            (x0, max(24, y0 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
    cv2.imwrite(str(output_path), background)


def _format_ranges(ranges: Sequence[dict[str, int]]) -> str:
    if not ranges:
        return "无"
    return "、".join(f"{item['start']}-{item['end']}" if item["start"] != item["end"] else str(item["start"]) for item in ranges)


def _write_markdown(
    output_path: Path,
    *,
    config: dict[str, Any],
    summary: dict[str, Any],
    alignment: dict[str, Any],
    overlay_path: Path,
) -> None:
    lines: list[str] = []
    lines.append("# 人工标注窗口到真实路径数据对齐报告")
    lines.append("")
    lines.append("## 报告边界")
    lines.append("")
    lines.append("- 本报告只做只读对齐：解释人工红框命中的真实路径点、线段、stroke、candidate 和局部数字。")
    lines.append("- 人工 `bbox_xyxy` 是观察入口，不是新的质量判定真值；后续若要调整红框，只改窗口配置。")
    lines.append("- 本报告不移动点、不删除点、不重连路径，也不修改质量阈值。")
    lines.append("")
    lines.append("## 输入")
    lines.append("")
    lines.append(f"- 标注截图：`{config.get('annotated_image')}`")
    lines.append(f"- bbox 坐标来源：{config.get('bbox_source')}")
    lines.append(f"- 诊断路径：`{summary['input']['path_pixels']}`")
    lines.append(f"- 诊断 run：`{summary['artifacts'].get('summary')}`")
    lines.append(f"- 覆盖宽度：`{summary['input']['coverage_width_px']} px` / `{summary['input']['coverage_width_m']} m`")
    lines.append(f"- 对齐叠加图：`{overlay_path}`")
    lines.append("")
    lines.append("## 窗口索引")
    lines.append("")
    lines.append("| 窗口 | 用户观察 | 命中点范围 | 命中线段范围 | stroke | candidate | 最大转角 | 不可行段 | lane 数 | 线距范围 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for item in alignment["windows"]:
        strokes = ",".join(str(stroke["stroke_id"]) for stroke in item["matched_strokes"]) or "无"
        candidates = ",".join(str(candidate["candidate_id"]) for candidate in item["matched_optimization_candidates"]) or "无"
        lane_stats = item["lane_inspection"]["lane_gap_stats"]
        lane_range = "无"
        if lane_stats["gap_count"]:
            lane_range = f"{lane_stats['min_gap_px']:.1f}-{lane_stats['max_gap_px']:.1f}"
        lines.append(
            "| "
            + " | ".join(
                [
                    item["title"],
                    item["user_observation"],
                    _format_ranges(item["path_point_index_ranges"]),
                    _format_ranges(item["path_segment_index_ranges"]),
                    strokes,
                    candidates,
                    f"{item['local_turn_metrics']['max_turn_deg']:.1f}",
                    str(item["local_segment_metrics"]["infeasible_segment_count"]),
                    str(item["lane_inspection"]["lane_count"]),
                    lane_range,
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## 逐窗口数据")
    lines.append("")
    for item in alignment["windows"]:
        lines.append(f"### {item['title']}")
        lines.append("")
        lines.append(f"- bbox：`{item['bbox_xyxy']}`")
        lines.append(f"- 用户观察：{item['user_observation']}")
        lines.append(f"- 范围约束：{item['scope_note']}")
        lines.append(f"- 命中路径点：{_format_ranges(item['path_point_index_ranges'])}，共 `{item['path_point_count']}` 个")
        lines.append(f"- 命中路径线段：{_format_ranges(item['path_segment_index_ranges'])}，共 `{item['path_segment_count']}` 段")
        lines.append(
            "- 转角："
            f"总 `{item['local_turn_metrics']['total_turn_deg']:.1f}`，"
            f"均值 `{item['local_turn_metrics']['mean_turn_deg']:.1f}`，"
            f"最大 `{item['local_turn_metrics']['max_turn_deg']:.1f}`，"
            f"热点点 `{item['local_turn_metrics']['hotspot_point_indices']}`"
        )
        lines.append(
            "- 线段："
            f"总长 `{item['local_segment_metrics']['total_length_px']:.1f}px`，"
            f"最长 `{item['local_segment_metrics']['max_segment_length_px']:.1f}px`，"
            f"长跳 `{item['local_segment_metrics']['long_jump_count']}`，"
            f"不可行段 `{item['local_segment_metrics']['infeasible_segment_count']}`"
        )
        lane_stats = item["lane_inspection"]["lane_gap_stats"]
        lines.append(
            "- lane："
            f"方向 `{item['lane_inspection']['dominant_axis_deg']:.1f}deg`，"
            f"lane `{item['lane_inspection']['lane_count']}`，"
            f"线距 `{lane_stats['min_gap_px']:.1f}-{lane_stats['max_gap_px']:.1f}px`，"
            f"目标 `{lane_stats['target_coverage_width_px']:.1f}px`"
        )
        if item["matched_strokes"]:
            lines.append("- 命中 stroke：")
            for stroke in item["matched_strokes"]:
                lines.append(
                    f"  - `stroke {stroke['stroke_id']}`："
                    f"{stroke['segment_type']} / {stroke['action_label']} / {stroke['classification']}，"
                    f"点 `{stroke['point_index_range']['start']}-{stroke['point_index_range']['end']}`，"
                    f"原因 `{stroke['reasons']}`"
                )
        if item["matched_optimization_candidates"]:
            lines.append("- 命中 candidate：")
            for candidate in item["matched_optimization_candidates"]:
                lines.append(
                    f"  - `candidate {candidate['candidate_id']}`："
                    f"{candidate['candidate_kind']} / stroke `{candidate['stroke_id']}` / "
                    f"{candidate['classification']}"
                )
        lines.append("")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    diagnostics_run_dir = Path(args.diagnostics_run_dir).expanduser().resolve()
    window_config_path = Path(args.window_config).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    summary = _load_json(diagnostics_run_dir / "summary.json")
    config = _load_json(window_config_path)
    windows = load_annotated_windows(config)
    points = _load_path_points(summary)
    free_mask = _load_free_mask(summary)
    stroke_payload = _load_json(diagnostics_run_dir / "path_stroke_segments.json")
    candidates = _load_candidates(diagnostics_run_dir / "optimization_candidate_windows.json")
    alignment = align_annotated_windows(
        points,
        windows,
        coverage_width_px=int(summary["input"]["coverage_width_px"]),
        stroke_segments=stroke_payload.get("segments", []),
        optimization_candidates=candidates,
        free_mask=free_mask,
    )

    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_annotated_window_alignment")
    run_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = run_dir / "人工标注窗口对齐叠加图.png"
    _draw_overlay(free_mask, points, windows, overlay_path)
    json_path = run_dir / "人工标注窗口对齐报告.json"
    json_path.write_text(json.dumps(alignment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path = run_dir / "人工标注窗口对齐报告.md"
    _write_markdown(md_path, config=config, summary=summary, alignment=alignment, overlay_path=overlay_path)
    summary_payload = {
        "case_group": "manual_annotation_alignment",
        "status": "success",
        "diagnostics_run_dir": str(diagnostics_run_dir),
        "window_config": str(window_config_path),
        "artifacts": {
            "report_json": str(json_path),
            "report_markdown": str(md_path),
            "overlay": str(overlay_path),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
