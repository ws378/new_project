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

from algorithms.turn_cost_coverage_research.src.diagnostics.path_lane_window_inspector import inspect_lane_issue_window  # noqa: E402
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import normalize_points  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出 lane_issue_windows 内的局部 lane 结构，只读检查，不改变路径。")
    parser.add_argument("--diagnostics-summary", required=True, help="包含 lane_issue_windows 的诊断 summary.json。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="输出根目录。")
    parser.add_argument("--max-windows", type=int, default=5, help="检查前 N 个 lane_issue_windows。")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_path(summary_path: Path, summary: dict[str, Any], name: str) -> Path | None:
    raw = summary.get("artifacts", {}).get(name)
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = summary_path.parent / path
    return path if path.exists() else None


def _load_stroke_segments(summary_path: Path, summary: dict[str, Any]) -> list[dict[str, Any]]:
    path = _artifact_path(summary_path, summary, "path_stroke_segments") or (summary_path.parent / "path_stroke_segments.json")
    if not path.exists():
        return []
    payload = _load_json(path)
    return list(payload.get("segments", [])) if isinstance(payload, dict) else []


def _load_segment_sources(summary_path: Path, summary: dict[str, Any]) -> list[dict[str, Any]]:
    path = _artifact_path(summary_path, summary, "generation_segment_mapping") or (summary_path.parent / "generation_segment_mapping.json")
    if not path.exists():
        return []
    payload = _load_json(path)
    return list(payload.get("segment_items", [])) if isinstance(payload, dict) else []


def _inspection_report(inspections: list[dict[str, Any]]) -> str:
    lines = [
        "# lane family 局部窗口只读检查报告",
        "",
        "该报告只判断窗口是否具备进入 lane family 重建的条件，不移动、不删除、不重连路径点。",
        "",
        "| window | readiness | action | lanes | fragments | gaps | dense | sparse | min_gap | median_gap | max_gap |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in inspections:
        lines.append(
            "| {window_id} | {rebuild_readiness} | {recommended_action} | {lane_count} | {fragmented_lane_count}/{max_lane_fragment_count} | {gap_count} | {over_dense_gap_count} | {over_sparse_gap_count} | {min_gap_px:.2f} | {median_gap_px:.2f} | {max_gap_px:.2f} |".format(
                **item
            )
        )
    lines.extend(
        [
            "",
            "说明：",
            "",
            "- `ready_for_review` 表示结构上可以进入下一步候选生成，但仍需要覆盖、碰撞、长跳、转角和 provenance 守卫。",
            "- `not_ready` 表示窗口内 lane 过碎或 lane family 不成立，不能直接做整组横向重建。",
            "- `split_fragments_before_rebuild` 表示应先拆连续片段和 connector，再考虑重建。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    summary_path = Path(args.diagnostics_summary).expanduser().resolve()
    summary = _load_json(summary_path)
    path_pixels_path = Path(str(summary["input"]["path_pixels"])).expanduser().resolve()
    path_pixels = normalize_points(_load_json(path_pixels_path))
    coverage_width_px = int(summary["input"]["coverage_width_px"])
    windows = list(summary.get("lane_issue_windows", []))[: int(args.max_windows)]
    stroke_segments = _load_stroke_segments(summary_path, summary)
    segment_sources = _load_segment_sources(summary_path, summary)

    inspections = [
        inspect_lane_issue_window(
            path_pixels,
            window_id=int(window["window_id"]),
            bbox_xyxy=window["bbox_xyxy"],
            coverage_width_px=coverage_width_px,
            stroke_segments=stroke_segments,
            segment_sources=segment_sources,
        ).to_dict()
        for window in windows
    ]

    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_path_lane_window_inspection")
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "lane_family_window_inspection_report.md"
    report_path.write_text(_inspection_report(inspections), encoding="utf-8")
    payload = {
        "case_group": "shelf_aware_path_lane_window_inspection",
        "status": "success",
        "input": {
            "diagnostics_summary": str(summary_path),
            "path_pixels": str(path_pixels_path),
            "coverage_width_px": coverage_width_px,
            "stroke_segment_count": len(stroke_segments),
            "segment_source_count": len(segment_sources),
        },
        "algorithm_scope": {
            "type": "diagnostics_only",
            "description": "只导出 lane_issue_windows 内的局部 lane 聚类结构，不改变路径，不接入正式 planner。",
        },
        "inspections": inspections,
        "artifacts": {
            "report": str(report_path),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
