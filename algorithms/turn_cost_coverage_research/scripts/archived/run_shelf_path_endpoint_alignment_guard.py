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

from algorithms.turn_cost_coverage_research.scripts.diagnostics.run_shelf_path_turn_cost_diagnostics import (
    _axis_angle_deg,
    _dominant_axis_deg,
    diagnose_endpoint_alignment,
)
from algorithms.turn_cost_coverage_research.src.diagnostics.path_diagnostics import (
    diagnose_lane_balance,
    diagnose_lane_spacing,
    diagnose_local_quality,
    diagnose_path,
)
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import normalize_points


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只对路径首尾 connector 做质量守卫的航段对齐实验。")
    parser.add_argument("--input-run-dir", required=True, help="同一 case 的 UI/shelf run 目录，用于读取 mask 和 summary。")
    parser.add_argument("--path-pixels-path", required=True, help="待修正的路径点。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="输出根目录。")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_summary(input_run_dir: Path) -> dict[str, Any]:
    candidates = sorted(input_run_dir.glob("*summary.json"))
    if not candidates:
        return {}
    payload = _load_json(candidates[0])
    return dict(payload) if isinstance(payload, dict) else {}


def _coverage_width_and_resolution(summary: dict[str, Any], input_run_dir: Path) -> tuple[int, float]:
    config = summary.get("diagnostics", {}).get("applied_public_config", {})
    coverage_width_m = float(config.get("coverage_width_m", 0.6))
    resolution = None
    metadata_path = next(input_run_dir.glob("run_*/metadata.json"), None)
    if metadata_path is not None:
        metadata = _load_json(metadata_path)
        if isinstance(metadata, dict):
            resolution = metadata.get("map_resolution", metadata.get("resolution"))
    if resolution is None:
        resolution = 0.05
    resolution = float(resolution)
    return max(2, int(round(coverage_width_m / resolution))), resolution


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


def _metrics(points: tuple[tuple[float, float], ...], free_mask: np.ndarray, *, coverage_width_px: int, resolution: float) -> dict[str, Any]:
    path = diagnose_path(points, resolution_m_per_px=resolution, coverage_width_px=coverage_width_px)
    quality = diagnose_local_quality(points, free_mask, coverage_width_px=coverage_width_px)
    spacing = diagnose_lane_spacing(points, coverage_width_px=coverage_width_px, resolution_m_per_px=resolution)
    balance = diagnose_lane_balance(points, coverage_width_px=coverage_width_px, resolution_m_per_px=resolution)
    endpoint = diagnose_endpoint_alignment(points, coverage_width_px=coverage_width_px)
    return {
        "path": path.to_dict(),
        "quality": quality.to_dict(),
        "spacing": spacing.to_dict(),
        "balance": balance.to_dict(),
        "endpoint": endpoint,
    }


def _reference_axis(points: tuple[tuple[float, float], ...], *, side: str, coverage_width_px: int) -> float | None:
    work = points if side == "start" else tuple(reversed(points))
    angles: list[float] = []
    min_len = max(1.0, float(coverage_width_px) * 0.5)
    for start, end in zip(work[1:], work[2:]):
        length = float(np.linalg.norm(np.asarray(end, dtype=np.float64) - np.asarray(start, dtype=np.float64)))
        if length < min_len:
            continue
        angle = _axis_angle_deg(start, end)
        if angle is not None:
            angles.append(angle)
        if len(angles) >= 30:
            break
    return _dominant_axis_deg(angles)


def _adjacent_path_axis(points: tuple[tuple[float, float], ...], *, side: str, coverage_width_px: int) -> float | None:
    angles: list[float] = []
    min_len = max(1.0, float(coverage_width_px) * 0.5)
    if side == "start":
        iterator = zip(points[1:], points[2:])
    else:
        start = max(0, len(points) - 32)
        iterator = zip(points[start:-2], points[start + 1:-1])
    for start_point, end_point in iterator:
        length = float(np.linalg.norm(np.asarray(end_point, dtype=np.float64) - np.asarray(start_point, dtype=np.float64)))
        if length < min_len:
            continue
        angle = _axis_angle_deg(start_point, end_point)
        if angle is not None:
            angles.append(angle)
        if len(angles) >= 30:
            break
    return _dominant_axis_deg(angles)


def _endpoint_candidates(
    points: tuple[tuple[float, float], ...],
    free_mask: np.ndarray,
    *,
    side: str,
    coverage_width_px: int,
) -> list[tuple[tuple[float, float], ...]]:
    if len(points) < 3:
        return []
    axis_degs = [
        axis
        for axis in (
            _reference_axis(points, side=side, coverage_width_px=coverage_width_px),
            _adjacent_path_axis(points, side=side, coverage_width_px=coverage_width_px),
        )
        if axis is not None
    ]
    if not axis_degs:
        return []
    work = list(points)
    if side == "start":
        anchor = np.asarray(work[1], dtype=np.float64)
        original = np.asarray(work[0], dtype=np.float64)
        replace_index = 0
    else:
        anchor = np.asarray(work[-2], dtype=np.float64)
        original = np.asarray(work[-1], dtype=np.float64)
        replace_index = len(work) - 1
    original_length = max(float(np.linalg.norm(original - anchor)), float(coverage_width_px) * 0.5)
    candidates: list[tuple[tuple[float, float], ...]] = []
    for axis_deg in axis_degs:
        axis = np.radians(float(axis_deg))
        for sign in (1.0, -1.0):
            unit = np.asarray([np.cos(axis) * sign, np.sin(axis) * sign], dtype=np.float64)
            for factor in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
                candidate_point = anchor + unit * original_length * factor
                x = int(round(float(candidate_point[0])))
                y = int(round(float(candidate_point[1])))
                if not (0 <= x < free_mask.shape[1] and 0 <= y < free_mask.shape[0]):
                    continue
                if free_mask[y, x] != 255:
                    continue
                candidate = list(work)
                candidate[replace_index] = (float(candidate_point[0]), float(candidate_point[1]))
                candidates.append(tuple(candidate))
    return candidates


def _accept_candidate(before: dict[str, Any], after: dict[str, Any], *, target_side: str) -> bool:
    if not after["endpoint"].get(target_side, {}).get("aligned"):
        return False
    if int(after["path"]["long_jump_count"]) > int(before["path"]["long_jump_count"]):
        return False
    if float(after["quality"]["coverage_ratio"]) + 1e-9 < float(before["quality"]["coverage_ratio"]):
        return False
    if float(after["quality"]["narrow_coverage_ratio"]) + 1e-9 < float(before["quality"]["narrow_coverage_ratio"]):
        return False
    if int(after["spacing"]["over_dense_count"]) > int(before["spacing"]["over_dense_count"]):
        return False
    if int(after["spacing"]["over_sparse_count"]) > int(before["spacing"]["over_sparse_count"]):
        return False
    if int(after["balance"]["imbalanced_count"]) > int(before["balance"]["imbalanced_count"]):
        return False
    return True


def _draw_overlay(free_mask: np.ndarray, before: tuple[tuple[float, float], ...], after: tuple[tuple[float, float], ...], out_path: Path) -> None:
    image = cv2.cvtColor(np.where(free_mask > 0, 245, 20).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    before_points = [(int(round(x)), int(round(y))) for x, y in before]
    after_points = [(int(round(x)), int(round(y))) for x, y in after]
    for start, end in zip(before_points, before_points[1:]):
        cv2.line(image, start, end, (180, 180, 180), 1, cv2.LINE_AA)
    for start, end in zip(after_points, after_points[1:]):
        cv2.line(image, start, end, (0, 130, 255), 2, cv2.LINE_AA)
    cv2.imwrite(str(out_path), image)


def main() -> None:
    args = parse_args()
    input_run_dir = Path(args.input_run_dir).expanduser().resolve()
    path_pixels_path = Path(args.path_pixels_path).expanduser().resolve()
    summary = _find_summary(input_run_dir)
    coverage_width_px, resolution = _coverage_width_and_resolution(summary, input_run_dir)
    free_mask, free_mask_source = _load_free_mask(input_run_dir)
    points = normalize_points(_load_json(path_pixels_path))

    before = _metrics(points, free_mask, coverage_width_px=coverage_width_px, resolution=resolution)
    current_points = points
    accepted: list[dict[str, Any]] = []
    current_metrics = before
    for side in ("start", "end"):
        if current_metrics["endpoint"].get(side, {}).get("aligned"):
            continue
        best_points = None
        best_metrics = None
        for candidate in _endpoint_candidates(current_points, free_mask, side=side, coverage_width_px=coverage_width_px):
            candidate_metrics = _metrics(candidate, free_mask, coverage_width_px=coverage_width_px, resolution=resolution)
            if not _accept_candidate(current_metrics, candidate_metrics, target_side=side):
                continue
            if best_metrics is None or float(candidate_metrics["path"]["total_turn_angle_deg"]) < float(best_metrics["path"]["total_turn_angle_deg"]):
                best_points = candidate
                best_metrics = candidate_metrics
        if best_points is not None and best_metrics is not None:
            current_points = best_points
            accepted.append({"side": side, "after": best_metrics["endpoint"].get(side)})
            current_metrics = best_metrics

    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_path_endpoint_alignment_guard")
    run_dir.mkdir(parents=True, exist_ok=True)
    path_path = run_dir / "endpoint_aligned_path_pixels.json"
    path_path.write_text(json.dumps([[float(x), float(y)] for x, y in current_points], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    overlay_path = run_dir / "endpoint_alignment_overlay.png"
    _draw_overlay(free_mask, points, current_points, overlay_path)
    payload = {
        "case_group": "shelf_path_endpoint_alignment_guard",
        "status": "success",
        "input": {
            "input_run_dir": str(input_run_dir),
            "path_pixels": str(path_pixels_path),
            "free_mask_source": str(free_mask_source),
            "coverage_width_px": int(coverage_width_px),
        },
        "algorithm_scope": {
            "type": "endpoint_connector_only_guarded_experiment",
            "description": "只允许替换首尾 connector 的一个端点；不改 coverage core，不改中间 lane。",
        },
        "accepted": accepted,
        "before": before,
        "after": current_metrics,
        "artifacts": {
            "endpoint_aligned_path_pixels": str(path_path),
            "overlay": str(overlay_path),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
