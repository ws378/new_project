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

from algorithms.turn_cost_coverage_research.src.diagnostics.path_diagnostics import (  # noqa: E402
    diagnose_lane_balance,
    diagnose_lane_spacing,
    diagnose_local_quality,
)
from algorithms.turn_cost_coverage_research.src.diagnostics.path_lane_window_inspector import inspect_lane_issue_window  # noqa: E402
from algorithms.turn_cost_coverage_research.src.experiments.path_lane_family_reconstruction import (  # noqa: E402
    apply_lane_family_window_plan_to_points,
)
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import (  # noqa: E402
    Point,
    normalize_points,
    path_metrics,
    segment_is_free,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对 ready lane family 窗口生成受守卫的离线路径候选。")
    parser.add_argument("--inspection-summary", required=True, help="run_shelf_path_lane_window_inspection.py 输出的 summary.json。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="输出根目录。")
    parser.add_argument("--target-strategy", default="coverage_width_from_median_anchor", help="lane family 目标横向位置策略。")
    parser.add_argument("--max-shift-factor", type=float, default=0.5, help="最大横向位移，单位为 coverage_width 倍率。")
    parser.add_argument("--max-coverage-drop-ratio", type=float, default=0.001, help="允许的最大覆盖率下降。")
    parser.add_argument("--max-turn-increase-deg", type=float, default=0.0, help="允许的最大总转角增加量。")
    parser.add_argument("--max-lane-over-dense-increase", type=int, default=0, help="允许新增的过密计数。")
    parser.add_argument("--max-lane-over-sparse-increase", type=int, default=0, help="允许新增的过疏计数。")
    parser.add_argument("--max-lane-imbalance-increase", type=int, default=0, help="允许新增的左右不平衡计数。")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_free_mask(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"无法读取 free mask: {path}")
    return np.where(image > 127, 255, 0).astype(np.uint8)


def _count_infeasible_segments(points: tuple[Point, ...], free_mask: np.ndarray, *, coverage_width_px: int) -> int:
    clearance = max(1, int(round(float(coverage_width_px) * 0.35)))
    return sum(
        1
        for start, end in zip(points, points[1:])
        if not segment_is_free(free_mask, start, end, clearance_px=clearance)
    )


def _lane_metrics(points: tuple[Point, ...], *, coverage_width_px: int, resolution_m_per_px: float) -> dict[str, int | float]:
    spacing = diagnose_lane_spacing(
        points,
        coverage_width_px=coverage_width_px,
        resolution_m_per_px=resolution_m_per_px,
    )
    balance = diagnose_lane_balance(
        points,
        coverage_width_px=coverage_width_px,
        resolution_m_per_px=resolution_m_per_px,
    )
    return {
        "over_dense_count": int(spacing.over_dense_count),
        "over_sparse_count": int(spacing.over_sparse_count),
        "imbalanced_count": int(balance.imbalanced_count),
        "mean_nearest_spacing_px": float(spacing.mean_nearest_spacing_px),
        "median_nearest_spacing_px": float(spacing.median_nearest_spacing_px),
        "mean_imbalance_px": float(balance.mean_imbalance_px),
        "median_imbalance_px": float(balance.median_imbalance_px),
    }


def _local_quality_metrics(points: tuple[Point, ...], free_mask: np.ndarray, *, coverage_width_px: int) -> dict[str, Any]:
    return diagnose_local_quality(points, free_mask, coverage_width_px=coverage_width_px).to_dict()


def _window_bad_gap_count(points: tuple[Point, ...], inspection: dict[str, Any], *, coverage_width_px: int) -> int:
    after = inspect_lane_issue_window(
        points,
        window_id=int(inspection.get("window_id", -1)),
        bbox_xyxy=inspection.get("bbox_xyxy", [0, 0, 0, 0]),
        coverage_width_px=coverage_width_px,
    )
    return int(after.over_dense_gap_count) + int(after.over_sparse_gap_count)


def _metric_delta(before: dict[str, Any], after: dict[str, Any], key: str) -> float:
    return float(after[key]) - float(before[key])


def _is_spacing_beneficial(before: dict[str, int | float], after: dict[str, int | float]) -> bool:
    before_bad = int(before["over_dense_count"]) + int(before["over_sparse_count"]) + int(before["imbalanced_count"])
    after_bad = int(after["over_dense_count"]) + int(after["over_sparse_count"]) + int(after["imbalanced_count"])
    return after_bad < before_bad


def _draw_overlay(
    free_mask: np.ndarray,
    before: tuple[Point, ...],
    after: tuple[Point, ...],
    *,
    changed_indices: set[int],
    out_path: Path,
) -> None:
    image = cv2.cvtColor(np.where(free_mask > 0, 245, 28).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    before_pixels = [(int(round(x)), int(round(y))) for x, y in before]
    after_pixels = [(int(round(x)), int(round(y))) for x, y in after]
    for start, end in zip(before_pixels, before_pixels[1:]):
        cv2.line(image, start, end, (180, 180, 180), 2, cv2.LINE_AA)
    for start, end in zip(after_pixels, after_pixels[1:]):
        cv2.line(image, start, end, (0, 140, 255), 2, cv2.LINE_AA)
    for index in changed_indices:
        if 0 <= index < len(after_pixels):
            cv2.circle(image, after_pixels[index], 5, (0, 0, 255), -1, cv2.LINE_AA)
    cv2.imwrite(str(out_path), image)


def _report(payload: dict[str, Any]) -> str:
    lines = [
        "# lane family 受守卫路径候选",
        "",
        "该报告只输出离线候选路径，不接入 UI，不迁入正式 planner。",
        "",
        f"- 状态：`{payload['status']}`",
        f"- 策略：`{payload['input']['target_strategy']}`",
        f"- 尝试窗口数：`{payload['attempt_count']}`",
        f"- 接受窗口数：`{payload['accepted_count']}`",
        "",
        "## 全局指标",
        "",
        "| metric | before | after | delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key in ("coverage_ratio", "length_px", "total_turn_angle_deg", "long_jump_count", "max_segment_px"):
        lines.append(
            "| {key} | {before} | {after} | {delta} |".format(
                key=key,
                before=payload["before_metrics"][key],
                after=payload["after_metrics"][key],
                delta=payload["delta"].get(f"{key}_delta", ""),
            )
        )
    lines.extend(
        [
            "",
            "## 窗口尝试",
            "",
            "| window | status | reason | changed points | guards | spacing bad |",
            "| --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for attempt in payload["attempts"]:
        guards = ",".join(key for key, value in attempt.get("guards", {}).items() if not value) or "all_ok"
        before_lane = attempt.get("before_lane_metrics", {})
        after_lane = attempt.get("after_lane_metrics", {})
        lines.append(
            "| {window_id} | {status} | {reason} | {changed_point_count} | {guards} | {before_bad}->{after_bad} |".format(
                window_id=attempt.get("window_id"),
                status=attempt.get("status"),
                reason=attempt.get("reason"),
                changed_point_count=attempt.get("changed_point_count", 0),
                guards=guards,
                before_bad=int(before_lane.get("over_dense_count", 0))
                + int(before_lane.get("over_sparse_count", 0))
                + int(before_lane.get("imbalanced_count", 0)),
                after_bad=int(after_lane.get("over_dense_count", 0))
                + int(after_lane.get("over_sparse_count", 0))
                + int(after_lane.get("imbalanced_count", 0)),
            )
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    inspection_summary_path = Path(args.inspection_summary).expanduser().resolve()
    inspection_summary = _load_json(inspection_summary_path)
    diagnostics_summary_path = Path(str(inspection_summary["input"]["diagnostics_summary"])).expanduser().resolve()
    diagnostics_summary = _load_json(diagnostics_summary_path)
    diagnostics_input = diagnostics_summary["input"]
    path_pixels_path = Path(str(inspection_summary["input"]["path_pixels"])).expanduser().resolve()
    free_mask_path = Path(str(diagnostics_input["free_mask_source"])).expanduser().resolve()
    coverage_width_px = int(inspection_summary["input"]["coverage_width_px"])
    resolution = float(diagnostics_input["resolution_m_per_px"])

    free_mask = _load_free_mask(free_mask_path)
    before_points = normalize_points(_load_json(path_pixels_path))
    current_points = before_points
    before_metrics = path_metrics(before_points, free_mask, coverage_width_px=coverage_width_px).to_dict()
    before_infeasible = _count_infeasible_segments(before_points, free_mask, coverage_width_px=coverage_width_px)
    before_local_quality = _local_quality_metrics(before_points, free_mask, coverage_width_px=coverage_width_px)
    before_lane_metrics = _lane_metrics(
        before_points,
        coverage_width_px=coverage_width_px,
        resolution_m_per_px=resolution,
    )
    attempts: list[dict[str, Any]] = []
    changed_indices: set[int] = set()

    for inspection in inspection_summary.get("inspections", []):
        if str(inspection.get("rebuild_readiness")) != "ready_for_review":
            continue
        result = apply_lane_family_window_plan_to_points(
            current_points,
            inspection,
            coverage_width_px=coverage_width_px,
            max_shift_factor=float(args.max_shift_factor),
            target_strategy=str(args.target_strategy),
        )
        attempt: dict[str, Any] = result.to_dict()
        if result.status != "candidate_path":
            attempt["guards"] = {}
            attempts.append(attempt)
            continue

        candidate_points = result.points
        current_metrics = path_metrics(current_points, free_mask, coverage_width_px=coverage_width_px).to_dict()
        candidate_metrics = path_metrics(candidate_points, free_mask, coverage_width_px=coverage_width_px).to_dict()
        current_infeasible = _count_infeasible_segments(current_points, free_mask, coverage_width_px=coverage_width_px)
        candidate_infeasible = _count_infeasible_segments(candidate_points, free_mask, coverage_width_px=coverage_width_px)
        current_local_quality = _local_quality_metrics(
            current_points,
            free_mask,
            coverage_width_px=coverage_width_px,
        )
        candidate_local_quality = _local_quality_metrics(
            candidate_points,
            free_mask,
            coverage_width_px=coverage_width_px,
        )
        current_lane_metrics = _lane_metrics(
            current_points,
            coverage_width_px=coverage_width_px,
            resolution_m_per_px=resolution,
        )
        candidate_lane_metrics = _lane_metrics(
            candidate_points,
            coverage_width_px=coverage_width_px,
            resolution_m_per_px=resolution,
        )
        current_window_bad_gap_count = _window_bad_gap_count(
            current_points,
            inspection,
            coverage_width_px=coverage_width_px,
        )
        candidate_window_bad_gap_count = _window_bad_gap_count(
            candidate_points,
            inspection,
            coverage_width_px=coverage_width_px,
        )
        guards = {
            "coverage_drop_ok": bool(
                float(current_metrics["coverage_ratio"]) - float(candidate_metrics["coverage_ratio"])
                <= float(args.max_coverage_drop_ratio)
            ),
            "narrow_coverage_ok": bool(
                float(candidate_local_quality["narrow_coverage_ratio"])
                + 1e-12
                >= float(current_local_quality["narrow_coverage_ratio"])
            ),
            "long_jump_count_ok": bool(
                int(candidate_metrics["long_jump_count"]) <= int(current_metrics["long_jump_count"])
            ),
            "infeasible_count_ok": bool(candidate_infeasible <= current_infeasible),
            "max_infeasible_length_ok": bool(
                float(candidate_local_quality["max_infeasible_segment_length_px"])
                <= float(current_local_quality["max_infeasible_segment_length_px"]) + 1e-9
            ),
            "turn_increase_ok": bool(
                float(candidate_metrics["total_turn_angle_deg"]) - float(current_metrics["total_turn_angle_deg"])
                <= float(args.max_turn_increase_deg)
            ),
            "lane_over_dense_count_ok": bool(
                int(candidate_lane_metrics["over_dense_count"]) - int(current_lane_metrics["over_dense_count"])
                <= int(args.max_lane_over_dense_increase)
            ),
            "lane_over_sparse_count_ok": bool(
                int(candidate_lane_metrics["over_sparse_count"]) - int(current_lane_metrics["over_sparse_count"])
                <= int(args.max_lane_over_sparse_increase)
            ),
            "lane_imbalance_count_ok": bool(
                int(candidate_lane_metrics["imbalanced_count"]) - int(current_lane_metrics["imbalanced_count"])
                <= int(args.max_lane_imbalance_increase)
            ),
            "spacing_beneficial_ok": _is_spacing_beneficial(current_lane_metrics, candidate_lane_metrics),
            "local_window_bad_gap_ok": bool(candidate_window_bad_gap_count <= current_window_bad_gap_count),
        }
        attempt.update(
            {
                "status": "accepted" if all(guards.values()) else "rejected_by_guards",
                "guards": guards,
                "before_metrics": current_metrics,
                "candidate_metrics": candidate_metrics,
                "before_local_quality": current_local_quality,
                "candidate_local_quality": candidate_local_quality,
                "before_lane_metrics": current_lane_metrics,
                "after_lane_metrics": candidate_lane_metrics,
                "before_window_bad_gap_count": int(current_window_bad_gap_count),
                "candidate_window_bad_gap_count": int(candidate_window_bad_gap_count),
                "before_infeasible_segment_count": int(current_infeasible),
                "candidate_infeasible_segment_count": int(candidate_infeasible),
                "delta": {
                    "coverage_ratio_delta": _metric_delta(current_metrics, candidate_metrics, "coverage_ratio"),
                    "length_px_delta": _metric_delta(current_metrics, candidate_metrics, "length_px"),
                    "total_turn_angle_deg_delta": _metric_delta(
                        current_metrics,
                        candidate_metrics,
                        "total_turn_angle_deg",
                    ),
                    "long_jump_count_delta": int(candidate_metrics["long_jump_count"])
                    - int(current_metrics["long_jump_count"]),
                    "infeasible_segment_count_delta": int(candidate_infeasible) - int(current_infeasible),
                    "max_infeasible_segment_length_px_delta": _metric_delta(
                        current_local_quality,
                        candidate_local_quality,
                        "max_infeasible_segment_length_px",
                    ),
                    "narrow_coverage_ratio_delta": _metric_delta(
                        current_local_quality,
                        candidate_local_quality,
                        "narrow_coverage_ratio",
                    ),
                    "local_window_bad_gap_count_delta": int(candidate_window_bad_gap_count)
                    - int(current_window_bad_gap_count),
                    "lane_over_dense_count_delta": int(candidate_lane_metrics["over_dense_count"])
                    - int(current_lane_metrics["over_dense_count"]),
                    "lane_over_sparse_count_delta": int(candidate_lane_metrics["over_sparse_count"])
                    - int(current_lane_metrics["over_sparse_count"]),
                    "lane_imbalance_count_delta": int(candidate_lane_metrics["imbalanced_count"])
                    - int(current_lane_metrics["imbalanced_count"]),
                },
            }
        )
        attempts.append(attempt)
        if all(guards.values()):
            moved = {
                index
                for index, (before, after) in enumerate(zip(current_points, candidate_points))
                if abs(float(before[0]) - float(after[0])) > 1e-6 or abs(float(before[1]) - float(after[1])) > 1e-6
            }
            changed_indices.update(moved)
            current_points = candidate_points

    after_metrics = path_metrics(current_points, free_mask, coverage_width_px=coverage_width_px).to_dict()
    after_infeasible = _count_infeasible_segments(current_points, free_mask, coverage_width_px=coverage_width_px)
    after_local_quality = _local_quality_metrics(current_points, free_mask, coverage_width_px=coverage_width_px)
    after_lane_metrics = _lane_metrics(
        current_points,
        coverage_width_px=coverage_width_px,
        resolution_m_per_px=resolution,
    )

    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_path_lane_family_guarded_apply")
    run_dir.mkdir(parents=True, exist_ok=True)
    path_path = run_dir / "lane_family_guarded_path_pixels.json"
    path_path.write_text(
        json.dumps([[float(x), float(y)] for x, y in current_points], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    overlay_path = run_dir / "lane_family_guarded_overlay.png"
    _draw_overlay(
        free_mask,
        before_points,
        current_points,
        changed_indices=changed_indices,
        out_path=overlay_path,
    )
    payload = {
        "case_group": "shelf_path_lane_family_guarded_apply",
        "status": "success",
        "input": {
            "inspection_summary": str(inspection_summary_path),
            "diagnostics_summary": str(diagnostics_summary_path),
            "path_pixels": str(path_pixels_path),
            "free_mask_source": str(free_mask_path),
            "coverage_width_px": int(coverage_width_px),
            "resolution_m_per_px": float(resolution),
            "target_strategy": str(args.target_strategy),
            "max_shift_factor": float(args.max_shift_factor),
        },
        "algorithm_scope": {
            "type": "offline_guarded_lane_family_path_candidate",
            "description": "只对 ready lane family 窗口做 coverage_core 横向小位移；不移动 connector/mixed/locked lane，不接入正式 planner。",
        },
        "attempt_count": len(attempts),
        "accepted_count": sum(1 for attempt in attempts if attempt["status"] == "accepted"),
        "rejected_count": sum(1 for attempt in attempts if attempt["status"] != "accepted"),
        "attempts": attempts,
        "before_metrics": before_metrics,
        "after_metrics": after_metrics,
        "before_infeasible_segment_count": int(before_infeasible),
        "after_infeasible_segment_count": int(after_infeasible),
        "before_local_quality": before_local_quality,
        "after_local_quality": after_local_quality,
        "before_lane_metrics": before_lane_metrics,
        "after_lane_metrics": after_lane_metrics,
        "delta": {
            "coverage_ratio_delta": _metric_delta(before_metrics, after_metrics, "coverage_ratio"),
            "length_px_delta": _metric_delta(before_metrics, after_metrics, "length_px"),
            "total_turn_angle_deg_delta": _metric_delta(before_metrics, after_metrics, "total_turn_angle_deg"),
            "long_jump_count_delta": int(after_metrics["long_jump_count"]) - int(before_metrics["long_jump_count"]),
            "max_segment_px_delta": _metric_delta(before_metrics, after_metrics, "max_segment_px"),
            "infeasible_segment_count_delta": int(after_infeasible) - int(before_infeasible),
            "max_infeasible_segment_length_px_delta": _metric_delta(
                before_local_quality,
                after_local_quality,
                "max_infeasible_segment_length_px",
            ),
            "narrow_coverage_ratio_delta": _metric_delta(
                before_local_quality,
                after_local_quality,
                "narrow_coverage_ratio",
            ),
            "lane_over_dense_count_delta": int(after_lane_metrics["over_dense_count"])
            - int(before_lane_metrics["over_dense_count"]),
            "lane_over_sparse_count_delta": int(after_lane_metrics["over_sparse_count"])
            - int(before_lane_metrics["over_sparse_count"]),
            "lane_imbalance_count_delta": int(after_lane_metrics["imbalanced_count"])
            - int(before_lane_metrics["imbalanced_count"]),
        },
        "artifacts": {
            "path_pixels": str(path_path),
            "overlay": str(overlay_path),
            "report": str(run_dir / "lane_family_guarded_apply.md"),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_dir / "lane_family_guarded_apply.md").write_text(_report(payload), encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
