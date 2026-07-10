from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from algorithms.shelf_aware_ctg_research.scripts.classify_residual_jump_targets import class_color
from algorithms.shelf_aware_ctg_research.scripts.diagnose_path_grid_jumps import load_json, path_points_from_json
from algorithms.shelf_aware_ctg_research.scripts.diagnose_residual_grid_nodes import circle_point, draw_legend


SIMULATION_VERSION = "overlap_target_pruning_sim_v1"
PRUNABLE_CLASSES = {"optional_by_overlap_high_confidence", "optional_by_overlap_needs_review"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate pruning overlap jump targets without changing the planner.")
    parser.add_argument("--run-dir", required=True, help="Existing shelf_aware_ctg_research run directory with residual candidate rules.")
    parser.add_argument("--area", action="append", default=None, help="Optional area folder name. Repeatable.")
    parser.add_argument("--max-coverage-risk-ratio", type=float, default=0.05, help="Candidate is low-risk if local uncovered free ratio stays below this value after removing the target point.")
    return parser.parse_args()


def point_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1])))


def path_length(points: list[tuple[float, float]]) -> float:
    return float(sum(point_distance(a, b) for a, b in zip(points, points[1:])))


def read_area_paths(area_dir: Path) -> tuple[Path, list[tuple[float, float]], float]:
    summary = load_json(area_dir / "summary.json")
    baseline = summary.get("shelf_aware_baseline", {})
    run_value = baseline.get("planner_run_dir") or baseline.get("artifacts_dir") or ""
    run_dir = Path(run_value)
    if not run_dir.is_dir():
        runs = sorted((area_dir / "shelf_aware_baseline").glob("run_*"))
        if not runs:
            raise ValueError(f"missing baseline run for {area_dir}")
        run_dir = runs[-1]
    metadata = load_json(run_dir / "metadata.json")
    return run_dir, path_points_from_json(run_dir / "path_pixels.json"), float(metadata["map_resolution"])


def load_free_mask(area_dir: Path) -> np.ndarray:
    image = cv2.imread(str(area_dir / "01_prepared_map.png"), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"missing prepared map: {area_dir}")
    return np.where(image > 0, 255, 0).astype(np.uint8)


def load_candidate_rules(area_dir: Path) -> list[dict[str, Any]]:
    path = area_dir / "diagnostics" / "residual_candidate_rules" / "residual_candidate_rules.json"
    if not path.is_file():
        raise ValueError(f"missing residual candidate rules: {path}")
    return load_json(path).get("classified_jump_targets", [])


def candidate_target_indices(classified: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in classified:
        if item.get("rule_class") not in PRUNABLE_CLASSES:
            continue
        jump = item.get("jump") or {}
        end_index = int(jump.get("end_index", 0))
        if end_index > 0:
            result[end_index] = item
    return result


def simulate_removed_path(path_points: list[tuple[float, float]], remove_indices: set[int]) -> list[tuple[float, float]]:
    return [point for idx, point in enumerate(path_points, start=1) if idx not in remove_indices]


def local_coverage_risk(
    free_mask: np.ndarray,
    target: tuple[float, float],
    simulated_path: list[tuple[float, float]],
    clean_radius_px: float,
) -> dict[str, Any]:
    x = int(round(float(target[0])))
    y = int(round(float(target[1])))
    radius = max(1, int(math.ceil(clean_radius_px)))
    h, w = free_mask.shape
    r0 = max(0, y - radius)
    r1 = min(h, y + radius + 1)
    c0 = max(0, x - radius)
    c1 = min(w, x + radius + 1)
    free_pixels = []
    radius_sq = clean_radius_px * clean_radius_px
    for row in range(r0, r1):
        for col in range(c0, c1):
            if free_mask[row, col] == 0:
                continue
            if (row - y) * (row - y) + (col - x) * (col - x) <= radius_sq:
                free_pixels.append((float(col), float(row)))
    if not free_pixels:
        return {"local_free_pixel_count": 0, "uncovered_pixel_count": 0, "uncovered_ratio": 0.0}
    nearby_path = [point for point in simulated_path if abs(point[0] - x) <= clean_radius_px * 2.0 and abs(point[1] - y) <= clean_radius_px * 2.0]
    uncovered = 0
    for pixel in free_pixels:
        if not nearby_path:
            uncovered += 1
            continue
        if min(point_distance(pixel, point) for point in nearby_path) > clean_radius_px:
            uncovered += 1
    return {
        "local_free_pixel_count": int(len(free_pixels)),
        "uncovered_pixel_count": int(uncovered),
        "uncovered_ratio": float(uncovered / len(free_pixels)),
    }


def draw_simulation_overlay(
    area_dir: Path,
    path_points: list[tuple[float, float]],
    removed: dict[int, dict[str, Any]],
    output_path: Path,
) -> None:
    base = cv2.imread(str(area_dir / "diagnostics" / "path_grid_jumps" / "00_territory_label_context.png"), cv2.IMREAD_COLOR)
    if base is None:
        gray = cv2.imread(str(area_dir / "01_prepared_map.png"), cv2.IMREAD_GRAYSCALE)
        base = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    image = base.copy()
    for prev, curr in zip(path_points, path_points[1:]):
        cv2.line(image, circle_point(prev), circle_point(curr), (70, 70, 70), 1, cv2.LINE_AA)
    for idx, item in removed.items():
        jump = item.get("jump", {})
        point = path_points[idx - 1]
        color = class_color(item.get("rule_class", ""))
        cv2.circle(image, circle_point(point), 7, color, -1)
        cv2.putText(image, str(jump.get("jump_number", idx)), circle_point(point), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (10, 10, 10), 1, cv2.LINE_AA)
        start_index = int(jump.get("start_index", idx - 1))
        if 1 <= start_index <= len(path_points):
            cv2.line(image, circle_point(path_points[start_index - 1]), circle_point(point), (0, 0, 220), 2, cv2.LINE_AA)
    draw_legend(
        image,
        [
            ("baseline path", (70, 70, 70)),
            ("prune simulation target", (0, 180, 255)),
            ("original jump", (0, 0, 220)),
        ],
    )
    cv2.imwrite(str(output_path), image)


def simulate_area(area_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    run_dir, path_points, resolution = read_area_paths(area_dir)
    classified = load_candidate_rules(area_dir)
    candidates = candidate_target_indices(classified)
    remove_indices = set(candidates.keys())
    simulated_path = simulate_removed_path(path_points, remove_indices)
    free_mask = load_free_mask(area_dir)
    clean_radius_px = 0.35 / resolution
    original_length_px = path_length(path_points)
    simulated_length_px = path_length(simulated_path)
    candidate_details = []
    low_risk_count = 0
    for index, item in sorted(candidates.items()):
        target = path_points[index - 1]
        risk = local_coverage_risk(free_mask, target, simulated_path, clean_radius_px)
        low_risk = bool(float(risk["uncovered_ratio"]) <= float(args.max_coverage_risk_ratio))
        if low_risk:
            low_risk_count += 1
        candidate_details.append(
            {
                "path_index": int(index),
                "rule_class": item.get("rule_class"),
                "jump_number": int((item.get("jump") or {}).get("jump_number", 0)),
                "jump_length_m": float((item.get("jump") or {}).get("length_m", 0.0)),
                "target_xy": [float(target[0]), float(target[1])],
                "coverage_risk": risk,
                "low_risk_by_threshold": low_risk,
            }
        )
    output_dir = area_dir / "diagnostics" / "pruning_simulation"
    output_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = output_dir / "01_overlap_pruning_simulation_overlay.png"
    draw_simulation_overlay(area_dir, path_points, candidates, overlay_path)
    payload = {
        "area_dir": str(area_dir),
        "planner_run_dir": str(run_dir),
        "simulation_version": SIMULATION_VERSION,
        "prunable_classes": sorted(PRUNABLE_CLASSES),
        "candidate_count": int(len(candidates)),
        "low_coverage_risk_candidate_count": int(low_risk_count),
        "coverage_risk_threshold": float(args.max_coverage_risk_ratio),
        "original_path_point_count": int(len(path_points)),
        "simulated_path_point_count": int(len(simulated_path)),
        "original_path_length_m": float(original_length_px * resolution),
        "simulated_path_length_m": float(simulated_length_px * resolution),
        "simulated_length_delta_m": float((simulated_length_px - original_length_px) * resolution),
        "notes": {
            "simulated_length_delta_m": "Post-hoc point-removal estimate only; it does not prove executable path quality.",
            "coverage_risk": "Local disk risk around removed target using actual clean radius; does not replace full swept-area coverage evaluation.",
        },
        "candidates": candidate_details,
        "artifacts": {"overlay": str(overlay_path)},
    }
    (output_dir / "pruning_simulation.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "area": area_dir.name,
        "diagnostics_dir": str(output_dir),
        "candidate_count": payload["candidate_count"],
        "low_coverage_risk_candidate_count": payload["low_coverage_risk_candidate_count"],
        "simulated_length_delta_m": payload["simulated_length_delta_m"],
        "artifacts": payload["artifacts"],
    }


def select_area_dirs(run_dir: Path, args: argparse.Namespace) -> list[Path]:
    area_dirs = sorted(path for path in run_dir.iterdir() if path.is_dir() and (path / "summary.json").is_file())
    if args.area:
        selected = set(args.area)
        area_dirs = [path for path in area_dirs if path.name in selected]
    return area_dirs


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.is_dir():
        raise ValueError(f"run directory does not exist: {run_dir}")
    summaries = [simulate_area(area_dir, args) for area_dir in select_area_dirs(run_dir, args)]
    output = {
        "run_dir": str(run_dir),
        "area_count": int(len(summaries)),
        "simulation_version": SIMULATION_VERSION,
        "areas": summaries,
        "aggregate": {
            "candidate_count": int(sum(item["candidate_count"] for item in summaries)),
            "low_coverage_risk_candidate_count": int(sum(item["low_coverage_risk_candidate_count"] for item in summaries)),
            "simulated_length_delta_m": float(sum(float(item["simulated_length_delta_m"]) for item in summaries)),
        },
    }
    target = run_dir / "pruning_simulation_summary.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
