from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.turn_cost_coverage_research.src.diagnostics.path_diagnostics import diagnose_local_quality  # noqa: E402
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import (  # noqa: E402
    Point,
    normalize_points,
    path_metrics,
    segment_is_free,
    total_turn_angle_deg,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读评估时间连续 group 的端点直连 shortcut 可行性。")
    parser.add_argument("--candidate-summary", required=True, help="run_shelf_path_lane_family_time_group_candidates.py 输出的 summary.json。")
    parser.add_argument("--candidate-rank", type=int, default=1, help="评估的候选排序编号。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="输出根目录。")
    parser.add_argument("--max-coverage-drop-ratio", type=float, default=0.001, help="允许的最大覆盖率下降。")
    parser.add_argument("--max-turn-increase-deg", type=float, default=0.0, help="允许的最大总转角增加。")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_free_mask(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"无法读取 free mask: {path}")
    return np.where(image > 127, 255, 0).astype(np.uint8)


def _metric_delta(before: dict[str, Any], after: dict[str, Any], key: str) -> float:
    return float(after[key]) - float(before[key])


def _count_infeasible_segments(points: tuple[Point, ...], free_mask: np.ndarray, *, coverage_width_px: int) -> tuple[int, float]:
    clearance = max(1, int(round(float(coverage_width_px) * 0.35)))
    lengths: list[float] = []
    for start, end in zip(points, points[1:]):
        if not segment_is_free(free_mask, start, end, clearance_px=clearance):
            lengths.append(float(np.linalg.norm(np.asarray(end) - np.asarray(start))))
    return len(lengths), max(lengths, default=0.0)


def _candidate_by_rank(payload: dict[str, Any], rank: int) -> dict[str, Any]:
    for item in payload.get("all_candidates", []):
        if int(item.get("candidate_rank", -1)) == int(rank):
            return dict(item)
    raise ValueError(f"未找到 candidate_rank={rank}")


def _draw_overlay(
    free_mask: np.ndarray,
    before: tuple[Point, ...],
    candidate: tuple[Point, ...],
    *,
    start_point_index: int,
    end_point_index: int,
    out_path: Path,
) -> None:
    image = cv2.cvtColor(np.where(free_mask > 0, 245, 28).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    before_pixels = [(int(round(x)), int(round(y))) for x, y in before[start_point_index : end_point_index + 1]]
    for start, end in zip(before_pixels, before_pixels[1:]):
        cv2.line(image, start, end, (180, 180, 180), 2, cv2.LINE_AA)
    candidate_pixels = [(int(round(x)), int(round(y))) for x, y in candidate[start_point_index : start_point_index + 2]]
    if len(candidate_pixels) == 2:
        cv2.line(image, candidate_pixels[0], candidate_pixels[1], (0, 140, 255), 3, cv2.LINE_AA)
        cv2.circle(image, candidate_pixels[0], 5, (0, 0, 255), -1, cv2.LINE_AA)
        cv2.circle(image, candidate_pixels[1], 5, (0, 0, 255), -1, cv2.LINE_AA)
    cv2.imwrite(str(out_path), image)


def _report(payload: dict[str, Any]) -> str:
    candidate = payload["candidate"]
    lines = [
        "# 时间连续 group 端点直连 shortcut 可行性评估",
        "",
        "该报告只评估一个离线 shortcut 候选，不替换当前最佳路径，不接入 UI。",
        "",
        f"- candidate rank：`{candidate['candidate_rank']}`",
        f"- window/group：`{candidate['window_id']} / {candidate['group_id']}`",
        f"- segment range：`{candidate['start_segment_index']}-{candidate['end_segment_index']}`",
        f"- 状态：`{payload['decision']['status']}`",
        "",
        "## 守卫",
        "",
        "| guard | pass |",
        "| --- | --- |",
    ]
    for key, value in payload["decision"]["guards"].items():
        lines.append(f"| {key} | `{value}` |")
    lines.extend(
        [
            "",
            "## 指标变化",
            "",
            "| metric | delta |",
            "| --- | ---: |",
        ]
    )
    for key, value in payload["delta"].items():
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    candidate_summary_path = Path(args.candidate_summary).expanduser().resolve()
    candidate_summary = _load_json(candidate_summary_path)
    candidate = _candidate_by_rank(candidate_summary, int(args.candidate_rank))
    time_groups_summary_path = Path(str(candidate_summary["input"]["time_groups_summary"])).expanduser().resolve()
    time_groups_summary = _load_json(time_groups_summary_path)
    inspection_summary_path = Path(str(time_groups_summary["input"]["inspection_summary"])).expanduser().resolve()
    inspection_summary = _load_json(inspection_summary_path)
    diagnostics_summary_path = Path(str(inspection_summary["input"]["diagnostics_summary"])).expanduser().resolve()
    diagnostics_summary = _load_json(diagnostics_summary_path)
    path_pixels_path = Path(str(inspection_summary["input"]["path_pixels"])).expanduser().resolve()
    free_mask_path = Path(str(diagnostics_summary["input"]["free_mask_source"])).expanduser().resolve()
    coverage_width_px = int(inspection_summary["input"]["coverage_width_px"])

    free_mask = _load_free_mask(free_mask_path)
    points = normalize_points(_load_json(path_pixels_path))
    start_segment = int(candidate["start_segment_index"])
    end_segment = int(candidate["end_segment_index"])
    start_point_index = max(0, start_segment - 1)
    end_point_index = min(len(points) - 1, end_segment)
    if end_point_index <= start_point_index + 1:
        raise ValueError("候选片段太短，无法评估端点直连 shortcut。")

    candidate_points = (
        points[: start_point_index + 1]
        + (points[end_point_index],)
        + points[end_point_index + 1 :]
    )
    before_metrics = path_metrics(points, free_mask, coverage_width_px=coverage_width_px).to_dict()
    after_metrics = path_metrics(candidate_points, free_mask, coverage_width_px=coverage_width_px).to_dict()
    before_local = diagnose_local_quality(points, free_mask, coverage_width_px=coverage_width_px).to_dict()
    after_local = diagnose_local_quality(candidate_points, free_mask, coverage_width_px=coverage_width_px).to_dict()
    before_infeasible_count, before_max_infeasible = _count_infeasible_segments(
        points,
        free_mask,
        coverage_width_px=coverage_width_px,
    )
    after_infeasible_count, after_max_infeasible = _count_infeasible_segments(
        candidate_points,
        free_mask,
        coverage_width_px=coverage_width_px,
    )
    before_group_points = points[start_point_index : end_point_index + 1]
    after_group_points = (points[start_point_index], points[end_point_index])
    direct_free = segment_is_free(
        free_mask,
        points[start_point_index],
        points[end_point_index],
        clearance_px=max(1, int(round(float(coverage_width_px) * 0.35))),
    )
    guards = {
        "candidate_status_ok": str(candidate.get("status")) == "low_risk_strip_review_candidate",
        "direct_segment_free_ok": bool(direct_free),
        "coverage_drop_ok": bool(
            float(before_metrics["coverage_ratio"]) - float(after_metrics["coverage_ratio"])
            <= float(args.max_coverage_drop_ratio)
        ),
        "narrow_coverage_ok": bool(
            float(after_local["narrow_coverage_ratio"]) + 1e-12 >= float(before_local["narrow_coverage_ratio"])
        ),
        "long_jump_count_ok": bool(int(after_metrics["long_jump_count"]) <= int(before_metrics["long_jump_count"])),
        "infeasible_count_ok": bool(after_infeasible_count <= before_infeasible_count),
        "max_infeasible_length_ok": bool(after_max_infeasible <= before_max_infeasible + 1e-9),
        "turn_increase_ok": bool(
            float(after_metrics["total_turn_angle_deg"]) - float(before_metrics["total_turn_angle_deg"])
            <= float(args.max_turn_increase_deg)
        ),
    }
    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_path_time_group_direct_shortcut_eval")
    run_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = run_dir / "time_group_direct_shortcut_overlay.png"
    _draw_overlay(
        free_mask,
        points,
        candidate_points,
        start_point_index=start_point_index,
        end_point_index=end_point_index,
        out_path=overlay_path,
    )
    payload = {
        "case_group": "shelf_path_time_group_direct_shortcut_eval",
        "status": "success",
        "input": {
            "candidate_summary": str(candidate_summary_path),
            "candidate_rank": int(args.candidate_rank),
            "time_groups_summary": str(time_groups_summary_path),
            "inspection_summary": str(inspection_summary_path),
            "diagnostics_summary": str(diagnostics_summary_path),
            "path_pixels": str(path_pixels_path),
            "free_mask_source": str(free_mask_path),
            "coverage_width_px": int(coverage_width_px),
        },
        "algorithm_scope": {
            "type": "readonly_direct_shortcut_feasibility",
            "description": "只评估一个时间连续 group 的端点直连 shortcut，不替换当前最佳路径，不接入正式 planner。",
        },
        "candidate": candidate,
        "window": {
            "start_point_index": int(start_point_index),
            "end_point_index": int(end_point_index),
            "removed_inner_point_count": int(end_point_index - start_point_index - 1),
            "before_group_point_count": int(len(before_group_points)),
            "after_group_point_count": int(len(after_group_points)),
            "before_group_turn_deg": float(total_turn_angle_deg(before_group_points)),
            "after_group_turn_deg": float(total_turn_angle_deg(after_group_points)),
        },
        "before_metrics": before_metrics,
        "after_metrics": after_metrics,
        "before_local_quality": before_local,
        "after_local_quality": after_local,
        "decision": {
            "status": "accepted_by_guards" if all(guards.values()) else "rejected_by_guards",
            "guards": guards,
        },
        "delta": {
            "coverage_ratio_delta": _metric_delta(before_metrics, after_metrics, "coverage_ratio"),
            "narrow_coverage_ratio_delta": _metric_delta(before_local, after_local, "narrow_coverage_ratio"),
            "length_px_delta": _metric_delta(before_metrics, after_metrics, "length_px"),
            "total_turn_angle_deg_delta": _metric_delta(before_metrics, after_metrics, "total_turn_angle_deg"),
            "long_jump_count_delta": int(after_metrics["long_jump_count"]) - int(before_metrics["long_jump_count"]),
            "infeasible_segment_count_delta": int(after_infeasible_count) - int(before_infeasible_count),
            "max_infeasible_segment_length_px_delta": float(after_max_infeasible) - float(before_max_infeasible),
        },
        "artifacts": {
            "overlay": str(overlay_path),
            "report": str(run_dir / "time_group_direct_shortcut_eval.md"),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_dir / "time_group_direct_shortcut_eval.md").write_text(_report(payload), encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
