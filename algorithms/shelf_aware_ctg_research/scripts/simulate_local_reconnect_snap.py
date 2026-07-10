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
from algorithms.shelf_aware_ctg_research.scripts.simulate_residual_pruning import load_free_mask, read_area_paths


SIMULATION_VERSION = "local_reconnect_snap_sim_v1"
RECONNECT_CLASSES = {"optional_by_overlap_high_confidence", "optional_by_overlap_needs_review"}
SNAP_CLASSES = {"optional_by_near_overlap_needs_review", "snap_or_insert_candidate"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate local reconnect and snap candidates for residual jump targets.")
    parser.add_argument("--run-dir", required=True, help="Existing shelf_aware_ctg_research run directory.")
    parser.add_argument("--area", action="append", default=None, help="Optional area folder name. Repeatable.")
    parser.add_argument("--max-coverage-risk-ratio", type=float, default=0.05)
    parser.add_argument("--snap-threshold-m", type=float, default=0.55)
    return parser.parse_args()


def point_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1])))


def segment_projection(point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> tuple[tuple[float, float], float, float]:
    px, py = point
    ax, ay = a
    bx, by = b
    vx = bx - ax
    vy = by - ay
    denom = vx * vx + vy * vy
    if denom <= 1e-9:
        projected = a
        t = 0.0
    else:
        t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / denom))
        projected = (ax + t * vx, ay + t * vy)
    return projected, t, point_distance(point, projected)


def nearest_prior_segment(point: tuple[float, float], path_points: list[tuple[float, float]], end_before_index: int) -> dict[str, Any] | None:
    limit = max(0, min(len(path_points) - 1, end_before_index - 1))
    best: dict[str, Any] | None = None
    for idx in range(limit):
        a = path_points[idx]
        b = path_points[idx + 1]
        projected, t, distance = segment_projection(point, a, b)
        if best is None or distance < float(best["distance_px"]):
            best = {
                "segment_start_index": int(idx + 1),
                "segment_end_index": int(idx + 2),
                "projection_xy": [float(projected[0]), float(projected[1])],
                "projection_t": float(t),
                "distance_px": float(distance),
            }
    return best


def line_metrics(free_mask: np.ndarray, clearance_map: np.ndarray, a: tuple[float, float], b: tuple[float, float], resolution: float) -> dict[str, Any]:
    length_px = point_distance(a, b)
    sample_count = max(2, int(math.ceil(length_px)) + 1)
    blocked = 0
    min_clearance_px = float("inf")
    h, w = free_mask.shape
    for i in range(sample_count):
        t = i / max(1, sample_count - 1)
        x = int(round(a[0] + (b[0] - a[0]) * t))
        y = int(round(a[1] + (b[1] - a[1]) * t))
        if x < 0 or x >= w or y < 0 or y >= h or free_mask[y, x] == 0:
            blocked += 1
            min_clearance_px = 0.0
            continue
        min_clearance_px = min(min_clearance_px, float(clearance_map[y, x]))
    if not math.isfinite(min_clearance_px):
        min_clearance_px = 0.0
    return {
        "length_px": float(length_px),
        "length_m": float(length_px * resolution),
        "sample_count": int(sample_count),
        "blocked_sample_count": int(blocked),
        "blocked_ratio": float(blocked / sample_count),
        "line_is_free": bool(blocked == 0),
        "min_clearance_m": float(min_clearance_px * resolution),
    }


def load_classified(area_dir: Path) -> list[dict[str, Any]]:
    path = area_dir / "diagnostics" / "residual_candidate_rules" / "residual_candidate_rules.json"
    if not path.is_file():
        raise ValueError(f"missing residual candidate rules: {path}")
    return load_json(path).get("classified_jump_targets", [])


def load_pruning_candidates(area_dir: Path) -> dict[int, dict[str, Any]]:
    path = area_dir / "diagnostics" / "pruning_simulation" / "pruning_simulation.json"
    if not path.is_file():
        return {}
    payload = load_json(path)
    result = {}
    for item in payload.get("candidates", []):
        result[int(item["path_index"])] = item
    return result


def evaluate_area(area_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    run_dir, path_points, resolution = read_area_paths(area_dir)
    free_mask = load_free_mask(area_dir)
    clearance_map = cv2.distanceTransform(free_mask, cv2.DIST_L2, 3)
    classified = load_classified(area_dir)
    pruning_by_index = load_pruning_candidates(area_dir)
    reconnect_items = []
    snap_items = []
    for item in classified:
        rule_class = item.get("rule_class", "")
        jump = item.get("jump") or {}
        end_index = int(jump.get("end_index", 0))
        target = tuple(jump.get("end_xy", [0.0, 0.0]))
        if rule_class in RECONNECT_CLASSES and 1 < end_index < len(path_points):
            prev_point = path_points[end_index - 2]
            next_point = path_points[end_index]
            metrics = line_metrics(free_mask, clearance_map, prev_point, next_point, resolution)
            pruning = pruning_by_index.get(end_index, {})
            low_risk = bool(pruning.get("low_risk_by_threshold", False))
            if metrics["line_is_free"] and low_risk:
                verdict = "reconnect_ready"
            elif not metrics["line_is_free"]:
                verdict = "reconnect_blocked"
            else:
                verdict = "coverage_risk_review"
            reconnect_items.append(
                {
                    "jump_number": int(jump.get("jump_number", 0)),
                    "path_index": int(end_index),
                    "rule_class": rule_class,
                    "target_xy": [float(target[0]), float(target[1])],
                    "prev_xy": [float(prev_point[0]), float(prev_point[1])],
                    "next_xy": [float(next_point[0]), float(next_point[1])],
                    "line_metrics": metrics,
                    "coverage_risk": pruning.get("coverage_risk"),
                    "low_risk_by_threshold": low_risk,
                    "verdict": verdict,
                }
            )
        if rule_class in SNAP_CLASSES:
            start_index = int(jump.get("start_index", max(1, end_index - 1)))
            nearest = nearest_prior_segment(target, path_points, start_index)
            if nearest is None:
                continue
            snap_distance_m = float(nearest["distance_px"] * resolution)
            projection = tuple(nearest["projection_xy"])
            connector = line_metrics(free_mask, clearance_map, target, projection, resolution)
            if snap_distance_m <= float(args.snap_threshold_m) and connector["line_is_free"]:
                verdict = "snap_ready"
            elif snap_distance_m <= float(args.snap_threshold_m):
                verdict = "snap_connector_blocked"
            else:
                verdict = "snap_too_far"
            snap_items.append(
                {
                    "jump_number": int(jump.get("jump_number", 0)),
                    "path_index": int(end_index),
                    "rule_class": rule_class,
                    "target_xy": [float(target[0]), float(target[1])],
                    "nearest_prior_segment": nearest,
                    "snap_distance_m": snap_distance_m,
                    "connector_metrics": connector,
                    "verdict": verdict,
                }
            )
    output_dir = area_dir / "diagnostics" / "local_reconnect_snap"
    output_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = output_dir / "01_reconnect_snap_overlay.png"
    draw_overlay(area_dir, path_points, reconnect_items, snap_items, overlay_path)
    payload = {
        "area_dir": str(area_dir),
        "planner_run_dir": str(run_dir),
        "simulation_version": SIMULATION_VERSION,
        "snap_threshold_m": float(args.snap_threshold_m),
        "reconnect_summary": summarize_verdicts(reconnect_items),
        "snap_summary": summarize_verdicts(snap_items),
        "reconnect_candidates": reconnect_items,
        "snap_candidates": snap_items,
        "artifacts": {"overlay": str(overlay_path)},
    }
    (output_dir / "local_reconnect_snap.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "area": area_dir.name,
        "diagnostics_dir": str(output_dir),
        "reconnect_summary": payload["reconnect_summary"],
        "snap_summary": payload["snap_summary"],
        "artifacts": payload["artifacts"],
    }


def summarize_verdicts(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in items:
        verdict = str(item.get("verdict", "unknown"))
        counts[verdict] = counts.get(verdict, 0) + 1
    return {"count": int(len(items)), "verdict_counts": dict(sorted(counts.items()))}


def draw_overlay(
    area_dir: Path,
    path_points: list[tuple[float, float]],
    reconnect_items: list[dict[str, Any]],
    snap_items: list[dict[str, Any]],
    output_path: Path,
) -> None:
    base = cv2.imread(str(area_dir / "diagnostics" / "path_grid_jumps" / "00_territory_label_context.png"), cv2.IMREAD_COLOR)
    if base is None:
        gray = cv2.imread(str(area_dir / "01_prepared_map.png"), cv2.IMREAD_GRAYSCALE)
        base = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    image = base.copy()
    for prev, curr in zip(path_points, path_points[1:]):
        cv2.line(image, circle_point(prev), circle_point(curr), (80, 80, 80), 1, cv2.LINE_AA)
    for item in reconnect_items:
        prev = tuple(item["prev_xy"])
        nxt = tuple(item["next_xy"])
        target = tuple(item["target_xy"])
        verdict = item["verdict"]
        color = (0, 190, 0) if verdict == "reconnect_ready" else ((0, 0, 220) if verdict == "reconnect_blocked" else (0, 180, 255))
        cv2.line(image, circle_point(prev), circle_point(nxt), color, 2, cv2.LINE_AA)
        cv2.circle(image, circle_point(target), 5, color, -1)
    for item in snap_items:
        target = tuple(item["target_xy"])
        projection = tuple(item["nearest_prior_segment"]["projection_xy"])
        verdict = item["verdict"]
        color = (220, 0, 220) if verdict == "snap_ready" else ((0, 0, 220) if verdict == "snap_connector_blocked" else (160, 160, 160))
        cv2.line(image, circle_point(target), circle_point(projection), color, 2, cv2.LINE_AA)
        cv2.circle(image, circle_point(target), 5, color, -1)
        cv2.circle(image, circle_point(projection), 4, (255, 255, 255), -1)
    draw_legend(
        image,
        [
            ("baseline path", (80, 80, 80)),
            ("reconnect ready", (0, 190, 0)),
            ("reconnect blocked", (0, 0, 220)),
            ("coverage review", (0, 180, 255)),
            ("snap ready", (220, 0, 220)),
        ],
    )
    cv2.imwrite(str(output_path), image)


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
    areas = [evaluate_area(area_dir, args) for area_dir in select_area_dirs(run_dir, args)]
    aggregate_reconnect: dict[str, int] = {}
    aggregate_snap: dict[str, int] = {}
    for area in areas:
        for key, value in area["reconnect_summary"]["verdict_counts"].items():
            aggregate_reconnect[key] = aggregate_reconnect.get(key, 0) + int(value)
        for key, value in area["snap_summary"]["verdict_counts"].items():
            aggregate_snap[key] = aggregate_snap.get(key, 0) + int(value)
    output = {
        "run_dir": str(run_dir),
        "area_count": int(len(areas)),
        "simulation_version": SIMULATION_VERSION,
        "aggregate_reconnect_verdict_counts": dict(sorted(aggregate_reconnect.items())),
        "aggregate_snap_verdict_counts": dict(sorted(aggregate_snap.items())),
        "areas": areas,
    }
    target = run_dir / "local_reconnect_snap_summary.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
