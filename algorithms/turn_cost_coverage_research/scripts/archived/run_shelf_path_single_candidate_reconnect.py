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

from algorithms.turn_cost_coverage_research.src.experiments.path_local_reconnector import (  # noqa: E402
    ReconnectConfig,
    turn_aware_astar_bridge,
)
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import (  # noqa: E402
    Point,
    normalize_points,
    path_metrics,
    segment_is_free,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对一个局部优化候选窗口做 turn-cost A* 重连实验。")
    parser.add_argument("--diagnostics-run-dir", required=True, help="包含 optimization_candidate_windows.json 的诊断 run 目录。")
    parser.add_argument("--candidate-rank", type=int, default=1, help="使用 top candidate 的排序编号，默认 1。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="实验输出根目录。")
    parser.add_argument("--anchor-margin-points", type=int, default=1, help="候选窗口前后额外纳入的 anchor 点数量。")
    parser.add_argument("--max-coverage-drop-ratio", type=float, default=0.001, help="允许的最大覆盖率下降。")
    parser.add_argument("--max-turn-increase-deg", type=float, default=0.0, help="允许的最大总转角增加量，默认不允许增加。")
    parser.add_argument("--turn-penalty-px", type=float, default=3.0, help="局部 A* 每次换方向的像素代价。")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_free_mask(input_run_dir: Path) -> tuple[np.ndarray, str]:
    candidates = [
        input_run_dir / "preprocess" / "prepare_map" / "05_prepared_map.png",
        input_run_dir / "preprocess" / "prepare_map" / "04_after_obstacle_expand.png",
    ]
    for candidate in candidates:
        image = cv2.imread(str(candidate), cv2.IMREAD_GRAYSCALE)
        if image is not None:
            return np.where(image > 127, 255, 0).astype(np.uint8), str(candidate)
    raise ValueError(f"无法在 {input_run_dir} 下找到同 frame 的 prepared/free mask 图像。")


def _count_infeasible_segments(points: tuple[Point, ...], free_mask: np.ndarray, *, coverage_width_px: int) -> int:
    clearance = max(1, int(round(float(coverage_width_px) * 0.35)))
    return sum(
        1
        for start, end in zip(points, points[1:])
        if not segment_is_free(free_mask, start, end, clearance_px=clearance)
    )


def _draw_single_candidate_overlay(
    free_mask: np.ndarray,
    before: tuple[Point, ...],
    after: tuple[Point, ...],
    *,
    anchor_start: int,
    anchor_end: int,
    out_path: Path,
) -> None:
    image = cv2.cvtColor(np.where(free_mask > 0, 245, 25).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    before_points = [(int(round(x)), int(round(y))) for x, y in before]
    after_points = [(int(round(x)), int(round(y))) for x, y in after]
    for start, end in zip(before_points, before_points[1:]):
        cv2.line(image, start, end, (185, 185, 185), 1, cv2.LINE_AA)
    for index in range(max(0, anchor_start), min(len(before_points) - 1, anchor_end)):
        cv2.line(image, before_points[index], before_points[index + 1], (0, 0, 255), 4, cv2.LINE_AA)
    for start, end in zip(after_points, after_points[1:]):
        cv2.line(image, start, end, (0, 150, 255), 2, cv2.LINE_AA)
    if 0 <= anchor_start < len(before_points):
        cv2.circle(image, before_points[anchor_start], 8, (0, 180, 0), -1, cv2.LINE_AA)
    if 0 <= anchor_end < len(before_points):
        cv2.circle(image, before_points[anchor_end], 8, (255, 0, 0), -1, cv2.LINE_AA)
    cv2.imwrite(str(out_path), image)


def _metric_delta(before: dict[str, Any], after: dict[str, Any], key: str) -> float:
    return float(after[key]) - float(before[key])


def main() -> None:
    args = parse_args()
    diagnostics_run_dir = Path(args.diagnostics_run_dir).expanduser().resolve()
    summary = _load_json(diagnostics_run_dir / "summary.json")
    candidates_payload = _load_json(diagnostics_run_dir / "optimization_candidate_windows.json")
    top_candidates = list(candidates_payload.get("top_candidates", []))
    rank = int(args.candidate_rank)
    if rank < 1 or rank > len(top_candidates):
        raise ValueError(f"candidate rank out of range: {rank}")
    candidate = top_candidates[rank - 1]

    input_run_dir = Path(str(summary["input"]["input_run_dir"])).expanduser().resolve()
    path_pixels_path = Path(str(summary["input"]["path_pixels"])).expanduser().resolve()
    resolution = float(summary["input"]["resolution_m_per_px"])
    coverage_width_px = int(summary["input"]["coverage_width_px"])
    free_mask, free_mask_source = _load_free_mask(input_run_dir)
    points = normalize_points(_load_json(path_pixels_path))

    margin = max(0, int(args.anchor_margin_points))
    anchor_start = max(0, int(candidate["start_point_index"]) - margin)
    anchor_end = min(len(points) - 1, int(candidate["end_point_index"]) + margin)
    if anchor_end <= anchor_start:
        raise ValueError("候选窗口 anchor 无效。")

    config = ReconnectConfig(
        coverage_width_px=coverage_width_px,
        resolution_m_per_px=resolution,
        turn_penalty_px=float(args.turn_penalty_px),
        search_margin_factor=10.0,
    )
    bridge = turn_aware_astar_bridge(free_mask, points[anchor_start], points[anchor_end], config=config)

    before_metrics = path_metrics(points, free_mask, coverage_width_px=coverage_width_px).to_dict()
    before_infeasible = _count_infeasible_segments(points, free_mask, coverage_width_px=coverage_width_px)
    accepted = False
    status = "failed_no_bridge"
    after_points = points
    if bridge is not None:
        candidate_points = tuple(points[: anchor_start + 1]) + tuple(bridge[1:-1]) + tuple(points[anchor_end:])
        candidate_metrics = path_metrics(candidate_points, free_mask, coverage_width_px=coverage_width_px).to_dict()
        candidate_infeasible = _count_infeasible_segments(candidate_points, free_mask, coverage_width_px=coverage_width_px)
        coverage_drop = float(before_metrics["coverage_ratio"]) - float(candidate_metrics["coverage_ratio"])
        guards = {
            "coverage_drop_ok": bool(coverage_drop <= float(args.max_coverage_drop_ratio)),
            "long_jump_count_ok": bool(int(candidate_metrics["long_jump_count"]) <= int(before_metrics["long_jump_count"])),
            "infeasible_count_ok": bool(candidate_infeasible <= before_infeasible),
            "turn_increase_ok": bool(
                float(candidate_metrics["total_turn_angle_deg"]) - float(before_metrics["total_turn_angle_deg"])
                <= float(args.max_turn_increase_deg)
            ),
        }
        accepted = bool(all(guards.values()))
        status = "accepted" if accepted else "rejected_by_guards"
        after_points = candidate_points if accepted else points
        after_metrics = path_metrics(after_points, free_mask, coverage_width_px=coverage_width_px).to_dict()
        after_infeasible = _count_infeasible_segments(after_points, free_mask, coverage_width_px=coverage_width_px)
    else:
        candidate_metrics = None
        candidate_infeasible = None
        guards = {
            "coverage_drop_ok": False,
            "long_jump_count_ok": False,
            "infeasible_count_ok": False,
            "turn_increase_ok": False,
        }
        after_metrics = before_metrics
        after_infeasible = before_infeasible

    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_single_candidate_reconnect")
    run_dir.mkdir(parents=True, exist_ok=True)
    path_path = run_dir / "single_candidate_reconnect_path_pixels.json"
    path_path.write_text(
        json.dumps([[float(x), float(y)] for x, y in after_points], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    overlay_path = run_dir / "single_candidate_reconnect_overlay.png"
    _draw_single_candidate_overlay(
        free_mask,
        points,
        after_points,
        anchor_start=anchor_start,
        anchor_end=anchor_end,
        out_path=overlay_path,
    )
    payload = {
        "case_group": "single_candidate_local_reconnect",
        "status": status,
        "accepted": accepted,
        "input": {
            "diagnostics_run_dir": str(diagnostics_run_dir),
            "source_input_run_dir": str(input_run_dir),
            "path_pixels": str(path_pixels_path),
            "candidate_rank": rank,
            "coverage_width_px": coverage_width_px,
            "resolution_m_per_px": resolution,
            "free_mask_source": free_mask_source,
        },
        "algorithm_scope": {
            "type": "non_official_single_window_experiment",
            "description": "只对一个已排序候选窗口做局部 turn-aware A* 重连；不批量改路径，不接入正式 planner。",
        },
        "candidate": candidate,
        "window": {
            "anchor_start_point_index": int(anchor_start),
            "anchor_end_point_index": int(anchor_end),
            "replaced_point_count": int(anchor_end - anchor_start + 1),
            "bridge_point_count": int(len(bridge) if bridge is not None else 0),
        },
        "guards": guards,
        "before_metrics": before_metrics,
        "candidate_metrics": candidate_metrics,
        "after_metrics": after_metrics,
        "before_infeasible_segment_count": before_infeasible,
        "candidate_infeasible_segment_count": candidate_infeasible,
        "after_infeasible_segment_count": after_infeasible,
        "delta": {
            "length_px_delta": _metric_delta(before_metrics, after_metrics, "length_px"),
            "turn_angle_deg_delta": _metric_delta(before_metrics, after_metrics, "total_turn_angle_deg"),
            "coverage_ratio_delta": _metric_delta(before_metrics, after_metrics, "coverage_ratio"),
            "long_jump_count_delta": int(after_metrics["long_jump_count"]) - int(before_metrics["long_jump_count"]),
            "infeasible_segment_count_delta": int(after_infeasible) - int(before_infeasible),
        },
        "artifacts": {
            "path_pixels": str(path_path),
            "overlay": str(overlay_path),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
