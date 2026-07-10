from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from algorithms.shelf_aware_ctg_research.scripts.diagnose_path_grid_jumps import (
    build_area_labels,
    build_label_overlay,
    compute_edge_switches,
    deterministic_color,
    enrich_jumps,
    latest_child_run,
    load_json,
    min_distance_to_points,
    path_points_from_json,
    read_energy_nodes,
    read_jumps,
    sample_label,
)


DEFAULT_FOCUS_AREAS = ("beiguo_lanshan_0407_area_6", "fourfloor_area_6", "fourfloor_area_7")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose residual grid nodes and jump targets for shelf-aware baseline paths.")
    parser.add_argument("--run-dir", required=True, help="Existing shelf_aware_ctg_research run directory.")
    parser.add_argument("--area", action="append", default=None, help="Optional area folder name. Repeatable.")
    parser.add_argument("--focus-only", action="store_true", help="Only diagnose the default focus areas.")
    parser.add_argument("--actual-clean-width-m", type=float, default=0.70, help="Assumed real cleaning width for overlap diagnostics.")
    parser.add_argument("--near-path-margin-m", type=float, default=0.08, help="Extra tolerance beyond actual clean radius.")
    parser.add_argument("--low-degree-threshold", type=int, default=3, help="Degree threshold for low-degree candidates.")
    parser.add_argument("--small-local-free-ratio", type=float, default=0.35, help="Local cell free ratio threshold for small-area candidates.")
    parser.add_argument("--no-boundary-smoothing", action="store_true", help="Recompute CTG labels without boundary smoothing.")
    return parser.parse_args()


def ensure_bgr(gray_or_bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(gray_or_bgr, cv2.COLOR_GRAY2BGR) if gray_or_bgr.ndim == 2 else gray_or_bgr.copy()


def draw_legend(image: np.ndarray, items: list[tuple[str, tuple[int, int, int]]]) -> None:
    if not items:
        return
    x0, y0 = 8, 8
    width = 300
    height = 22 * len(items) + 10
    cv2.rectangle(image, (x0 - 4, y0 - 4), (x0 + width, y0 + height), (245, 245, 245), -1)
    cv2.rectangle(image, (x0 - 4, y0 - 4), (x0 + width, y0 + height), (80, 80, 80), 1)
    for idx, (label, color) in enumerate(items):
        y = y0 + 18 + idx * 22
        cv2.circle(image, (x0 + 8, y - 5), 5, color, -1)
        cv2.putText(image, label, (x0 + 22, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (20, 20, 20), 1, cv2.LINE_AA)


def circle_point(point: tuple[float, float]) -> tuple[int, int]:
    return (int(round(point[0])), int(round(point[1])))


def local_free_stats(free_mask: np.ndarray, point: tuple[float, float], radius_px: int) -> dict[str, Any]:
    x = int(round(float(point[0])))
    y = int(round(float(point[1])))
    h, w = free_mask.shape
    r0 = max(0, y - radius_px)
    r1 = min(h, y + radius_px + 1)
    c0 = max(0, x - radius_px)
    c1 = min(w, x + radius_px + 1)
    patch = free_mask[r0:r1, c0:c1]
    total = int(patch.size)
    free = int(np.count_nonzero(patch > 0))
    return {
        "window_radius_px": int(radius_px),
        "window_pixel_count": total,
        "free_pixel_count": free,
        "free_ratio": float(free / total) if total else 0.0,
    }


def nearest_path_index(point: tuple[float, float], path_points: list[tuple[float, float]]) -> int | None:
    if not path_points:
        return None
    px, py = float(point[0]), float(point[1])
    best_index = min(range(len(path_points)), key=lambda idx: math.hypot(px - path_points[idx][0], py - path_points[idx][1]))
    return int(best_index + 1)


def estimate_node_degrees(nodes: list[dict[str, Any]], neighbor_radius_px: float) -> None:
    if not nodes:
        return
    radius = float(neighbor_radius_px)
    radius_sq = radius * radius
    for node in nodes:
        x0 = float(node["x"])
        y0 = float(node["y"])
        degree = 0
        for other in nodes:
            if other is node:
                continue
            dx = x0 - float(other["x"])
            dy = y0 - float(other["y"])
            dist_sq = dx * dx + dy * dy
            if 0.0 < dist_sq <= radius_sq:
                degree += 1
        node["estimated_degree"] = int(degree)


def classify_node(
    node: dict[str, Any],
    *,
    overlap_radius_px: float,
    near_path_margin_px: float,
    low_degree_threshold: int,
    small_local_free_ratio: float,
    clearance_threshold_m: float,
    jump_target: bool,
) -> list[str]:
    tags: list[str] = []
    jump_distance_to_prior = node.get("jump_end_distance_to_prior_path_px")
    if jump_target and jump_distance_to_prior is not None:
        distance_to_prior = float(jump_distance_to_prior)
        if distance_to_prior <= overlap_radius_px:
            tags.append("candidate_by_overlap")
        elif distance_to_prior <= overlap_radius_px + near_path_margin_px:
            tags.append("candidate_near_overlap_margin")
    if float(node.get("local_free_ratio", 1.0)) <= small_local_free_ratio:
        tags.append("candidate_by_small_local_free_area")
    if int(node.get("estimated_degree", 99)) <= low_degree_threshold:
        tags.append("candidate_by_low_degree")
    if float(node.get("min_distance_m", 999.0)) <= clearance_threshold_m or int(node.get("obstacle_neighbor_count", 0)) >= 5:
        tags.append("candidate_by_boundary_sensitive")
    if int(node.get("label", 0)) < 0:
        tags.append("candidate_by_unknown_or_junction_label")
    if jump_target:
        tags.append("jump_target")
    return tags or ["required_like"]


def read_variant_data(area_dir: Path, free_mask: np.ndarray, labels: np.ndarray, actual_clean_width_m: float) -> dict[str, Any]:
    variant_dir = area_dir / "shelf_aware_baseline"
    run_dir = latest_child_run(variant_dir)
    if run_dir is None:
        raise ValueError(f"missing shelf_aware_baseline planner run in {area_dir}")
    metadata = load_json(run_dir / "metadata.json")
    resolution = float(metadata["map_resolution"])
    coverage_width_px = int(metadata.get("coverage_width_px") or max(1, round(float(metadata.get("coverage_width_m", 0.55)) / resolution)))
    path_points = path_points_from_json(run_dir / "path_pixels.json")
    raw_path_points = path_points_from_json(run_dir / "path_pixels_raw.json") if (run_dir / "path_pixels_raw.json").is_file() else path_points
    jumps = read_jumps(run_dir / "path_jump_segments_pixels.json")
    nodes = read_energy_nodes(run_dir / "energy_debug.csv", metadata, free_mask.shape[0])
    overlap_radius_px = max(0.0, (float(actual_clean_width_m) * 0.5) / resolution)
    enriched_jumps = enrich_jumps(jumps, labels, path_points, nodes, resolution, overlap_radius_px)
    return {
        "run_dir": run_dir,
        "metadata": metadata,
        "resolution": resolution,
        "coverage_width_px": coverage_width_px,
        "path_points": path_points,
        "raw_path_points": raw_path_points,
        "jumps": enriched_jumps,
        "nodes": nodes,
        "overlap_radius_px": overlap_radius_px,
    }


def enrich_nodes(
    *,
    nodes: list[dict[str, Any]],
    labels: np.ndarray,
    free_mask: np.ndarray,
    path_points: list[tuple[float, float]],
    raw_path_points: list[tuple[float, float]],
    jumps: list[dict[str, Any]],
    resolution: float,
    coverage_width_px: int,
    overlap_radius_px: float,
    near_path_margin_m: float,
    low_degree_threshold: int,
    small_local_free_ratio: float,
) -> tuple[list[dict[str, Any]], set[tuple[int, int]]]:
    estimate_node_degrees(nodes, neighbor_radius_px=max(1.0, float(coverage_width_px) * 1.55))
    jump_target_keys: set[tuple[int, int]] = set()
    jump_target_info_by_key: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for jump_number, jump in enumerate(jumps, start=1):
        nearest = jump.get("nearest_node") or {}
        if "x" in nearest and "y" in nearest:
            key = (int(round(float(nearest["x"]))), int(round(float(nearest["y"]))))
            jump_target_keys.add(key)
            jump_target_info_by_key.setdefault(key, []).append(
                {
                    "jump_number": int(jump_number),
                    "length_m": float(jump.get("length_m", 0.0)),
                    "end_distance_to_prior_path_px": float(jump.get("end_distance_to_prior_path_px", float("inf"))),
                    "end_distance_to_prior_path_m": float(jump.get("end_distance_to_prior_path_m", float("inf"))),
                    "end_within_overlap_radius": bool(jump.get("end_within_overlap_radius", False)),
                }
            )

    local_radius_px = max(1, int(round(float(coverage_width_px) * 0.5)))
    clearance_threshold_m = max(float(resolution) * 1.5, 0.10)
    near_path_margin_px = float(near_path_margin_m) / float(resolution)
    enriched: list[dict[str, Any]] = []
    for node in nodes:
        point = (float(node["x"]), float(node["y"]))
        local = local_free_stats(free_mask, point, local_radius_px)
        key = (int(round(point[0])), int(round(point[1])))
        item = dict(node)
        item["label"] = sample_label(labels, point)
        item["distance_to_path_px"] = min_distance_to_points(point, raw_path_points)
        item["distance_to_path_m"] = float(item["distance_to_path_px"] * resolution) if math.isfinite(float(item["distance_to_path_px"])) else float("inf")
        item["nearest_path_index"] = nearest_path_index(point, path_points)
        item["within_overlap_radius"] = bool(float(item["distance_to_path_px"]) <= overlap_radius_px)
        item["local_free_pixel_count"] = local["free_pixel_count"]
        item["local_window_pixel_count"] = local["window_pixel_count"]
        item["local_free_ratio"] = local["free_ratio"]
        item["jump_target"] = key in jump_target_keys
        item["targeted_by_jumps"] = jump_target_info_by_key.get(key, [])
        if item["targeted_by_jumps"]:
            item["jump_end_distance_to_prior_path_px"] = min(float(info["end_distance_to_prior_path_px"]) for info in item["targeted_by_jumps"])
            item["jump_end_distance_to_prior_path_m"] = min(float(info["end_distance_to_prior_path_m"]) for info in item["targeted_by_jumps"])
            item["jump_end_within_overlap_radius"] = any(bool(info["end_within_overlap_radius"]) for info in item["targeted_by_jumps"])
        item["classification"] = classify_node(
            item,
            overlap_radius_px=overlap_radius_px,
            near_path_margin_px=near_path_margin_px,
            low_degree_threshold=low_degree_threshold,
            small_local_free_ratio=small_local_free_ratio,
            clearance_threshold_m=clearance_threshold_m,
            jump_target=bool(item["jump_target"]),
        )
        enriched.append(item)
    return enriched, jump_target_keys


def draw_path_territory_jumps(
    free_mask: np.ndarray,
    labels: np.ndarray,
    path_points: list[tuple[float, float]],
    edge_switches: list[dict[str, Any]],
    jumps: list[dict[str, Any]],
    output_path: Path,
) -> None:
    image = build_label_overlay(free_mask, labels)
    for prev, curr in zip(path_points, path_points[1:]):
        cv2.line(image, circle_point(prev), circle_point(curr), (30, 30, 30), 1, cv2.LINE_AA)
    for switch in edge_switches[:300]:
        point = tuple(switch["xy"])
        cv2.circle(image, circle_point(point), 3, (255, 255, 255), -1)
        cv2.circle(image, circle_point(point), 3, (0, 0, 0), 1)
    for idx, jump in enumerate(jumps, start=1):
        start = tuple(jump["start_xy"])
        end = tuple(jump["end_xy"])
        cv2.line(image, circle_point(start), circle_point(end), (0, 0, 255), 2, cv2.LINE_AA)
        cv2.circle(image, circle_point(end), 5, (0, 255, 255), -1)
        if idx <= 40:
            cv2.putText(image, str(idx), circle_point(end), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (20, 20, 20), 1, cv2.LINE_AA)
    draw_legend(
        image,
        [
            ("path", (30, 30, 30)),
            ("edge switch", (255, 255, 255)),
            ("jump segment", (0, 0, 255)),
            ("jump target", (0, 255, 255)),
            ("label=-1", (170, 170, 170)),
        ],
    )
    cv2.imwrite(str(output_path), image)


def node_color(node: dict[str, Any]) -> tuple[int, int, int]:
    tags = set(node.get("classification", []))
    if "jump_target" in tags:
        return (0, 0, 255)
    if "candidate_by_overlap" in tags:
        return (0, 200, 255)
    if "candidate_by_small_local_free_area" in tags:
        return (255, 0, 180)
    if "candidate_by_low_degree" in tags:
        return (255, 130, 0)
    if "candidate_by_boundary_sensitive" in tags:
        return (0, 160, 255)
    if "candidate_by_unknown_or_junction_label" in tags:
        return (160, 160, 160)
    return (40, 180, 40)


def draw_nodes_enriched(free_mask: np.ndarray, labels: np.ndarray, nodes: list[dict[str, Any]], output_path: Path) -> None:
    image = build_label_overlay(free_mask, labels)
    for node in nodes:
        point = circle_point((node["x"], node["y"]))
        color = node_color(node)
        radius = 4 if node.get("jump_target") else 2
        cv2.circle(image, point, radius, color, -1)
        if int(node.get("estimated_degree", 0)) <= 2:
            cv2.circle(image, point, radius + 2, (255, 255, 255), 1)
    draw_legend(
        image,
        [
            ("required-like", (40, 180, 40)),
            ("overlap", (0, 200, 255)),
            ("small local free", (255, 0, 180)),
            ("low degree", (255, 130, 0)),
            ("boundary", (0, 160, 255)),
            ("jump target", (0, 0, 255)),
        ],
    )
    cv2.imwrite(str(output_path), image)


def draw_jump_target_context(
    free_mask: np.ndarray,
    labels: np.ndarray,
    path_points: list[tuple[float, float]],
    jumps: list[dict[str, Any]],
    nodes_by_key: dict[tuple[int, int], dict[str, Any]],
    overlap_radius_px: float,
    output_path: Path,
) -> None:
    image = build_label_overlay(free_mask, labels)
    for prev, curr in zip(path_points, path_points[1:]):
        cv2.line(image, circle_point(prev), circle_point(curr), (60, 60, 60), 1, cv2.LINE_AA)
    for idx, jump in enumerate(jumps, start=1):
        start = tuple(jump["start_xy"])
        end = tuple(jump["end_xy"])
        cv2.line(image, circle_point(start), circle_point(end), (0, 0, 220), 2, cv2.LINE_AA)
        cv2.circle(image, circle_point(end), int(round(overlap_radius_px)), (0, 220, 220), 1)
        cv2.circle(image, circle_point(end), 5, (0, 0, 255), -1)
        nearest = jump.get("nearest_node") or {}
        key = (int(round(float(nearest.get("x", end[0])))), int(round(float(nearest.get("y", end[1])))))
        node = nodes_by_key.get(key)
        if node is not None:
            cv2.circle(image, circle_point((node["x"], node["y"])), 7, node_color(node), 2)
        if idx <= 60:
            cv2.putText(image, str(idx), circle_point(end), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (20, 20, 20), 1, cv2.LINE_AA)
    draw_legend(
        image,
        [
            ("path", (60, 60, 60)),
            ("jump", (0, 0, 220)),
            ("actual clean radius", (0, 220, 220)),
            ("target node class", (0, 0, 255)),
        ],
    )
    cv2.imwrite(str(output_path), image)


def summarize_nodes(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for node in nodes:
        for tag in node.get("classification", []):
            counts[tag] = counts.get(tag, 0) + 1
    return {
        "node_count": int(len(nodes)),
        "classification_counts": dict(sorted(counts.items())),
        "estimated_degree_min": int(min((node.get("estimated_degree", 0) for node in nodes), default=0)),
        "estimated_degree_max": int(max((node.get("estimated_degree", 0) for node in nodes), default=0)),
        "estimated_degree_mean": float(sum(float(node.get("estimated_degree", 0)) for node in nodes) / len(nodes)) if nodes else 0.0,
        "local_free_ratio_mean": float(sum(float(node.get("local_free_ratio", 0.0)) for node in nodes) / len(nodes)) if nodes else 0.0,
        "jump_target_node_count": int(sum(1 for node in nodes if bool(node.get("jump_target")))),
    }


def enrich_jump_targets(jumps: list[dict[str, Any]], nodes_by_key: dict[tuple[int, int], dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for idx, jump in enumerate(jumps, start=1):
        item = dict(jump)
        item["jump_number"] = int(idx)
        nearest = item.get("nearest_node") or {}
        key = None
        if "x" in nearest and "y" in nearest:
            key = (int(round(float(nearest["x"]))), int(round(float(nearest["y"]))))
        node = nodes_by_key.get(key) if key is not None else None
        if node is not None:
            item["target_node_metrics"] = {
                "x": node["x"],
                "y": node["y"],
                "node_id": node.get("node_id"),
                "grid_row": node.get("grid_row"),
                "grid_col": node.get("grid_col"),
                "label": node["label"],
                "estimated_degree": node["estimated_degree"],
                "local_free_ratio": node["local_free_ratio"],
                "local_free_pixel_count": node["local_free_pixel_count"],
                "distance_to_path_m": node["distance_to_path_m"],
                "jump_end_distance_to_prior_path_m": node.get("jump_end_distance_to_prior_path_m"),
                "jump_end_within_overlap_radius": node.get("jump_end_within_overlap_radius"),
                "min_distance_m": node["min_distance_m"],
                "obstacle_neighbor_count": node["obstacle_neighbor_count"],
                "classification": node["classification"],
            }
        enriched.append(item)
    return enriched


def diagnose_area(area_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    diagnostics_root = area_dir / "diagnostics" / "residual_grid_nodes"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    free_mask, labels, label_info = build_area_labels(area_dir, apply_boundary_smoothing=not args.no_boundary_smoothing)
    variant = read_variant_data(area_dir, free_mask, labels, float(args.actual_clean_width_m))
    edge_switches = compute_edge_switches(labels, variant["path_points"])
    nodes, jump_target_keys = enrich_nodes(
        nodes=variant["nodes"],
        labels=labels,
        free_mask=free_mask,
        path_points=variant["path_points"],
        raw_path_points=variant["raw_path_points"],
        jumps=variant["jumps"],
        resolution=float(variant["resolution"]),
        coverage_width_px=int(variant["coverage_width_px"]),
        overlap_radius_px=float(variant["overlap_radius_px"]),
        near_path_margin_m=float(args.near_path_margin_m),
        low_degree_threshold=int(args.low_degree_threshold),
        small_local_free_ratio=float(args.small_local_free_ratio),
    )
    nodes_by_key = {(int(round(float(node["x"]))), int(round(float(node["y"])))): node for node in nodes}
    jump_targets = enrich_jump_targets(variant["jumps"], nodes_by_key)

    draw_path_territory_jumps(free_mask, labels, variant["path_points"], edge_switches, variant["jumps"], diagnostics_root / "01_path_territory_jumps.png")
    draw_nodes_enriched(free_mask, labels, nodes, diagnostics_root / "02_nodes_debug_enriched.png")
    draw_jump_target_context(
        free_mask,
        labels,
        variant["path_points"],
        variant["jumps"],
        nodes_by_key,
        float(variant["overlap_radius_px"]),
        diagnostics_root / "03_jump_target_context.png",
    )

    node_payload = {
        "area_dir": str(area_dir),
        "planner_run_dir": str(variant["run_dir"]),
        "label_info": label_info,
        "resolution_m_per_px": float(variant["resolution"]),
        "coverage_width_px": int(variant["coverage_width_px"]),
        "actual_clean_width_m": float(args.actual_clean_width_m),
        "overlap_radius_px": float(variant["overlap_radius_px"]),
        "summary": summarize_nodes(nodes),
        "notes": {
            "estimated_degree": "Estimated from non-obstacle debug nodes within 1.55 * coverage_width_px in original pixel space.",
            "local_free_ratio": "Measured in an original-image square window around each exported node; it is a diagnostic proxy, not the exact rotated complete_cell_test cell.",
            "center_adjustment": "Not available in current energy_debug.csv; requires future planner-side debug fields if exact attribution is needed.",
        },
        "nodes": nodes,
    }
    jump_payload = {
        "area_dir": str(area_dir),
        "planner_run_dir": str(variant["run_dir"]),
        "jump_count": int(len(jump_targets)),
        "long_jump_count_ge_2m": int(sum(1 for jump in jump_targets if float(jump.get("length_m", 0.0)) >= 2.0)),
        "jump_targets_within_overlap_radius_count": int(sum(1 for jump in jump_targets if bool(jump.get("end_within_overlap_radius")))),
        "jump_targets_with_classification_counts": summarize_jump_target_classes(jump_targets),
        "jumps": jump_targets,
    }
    (diagnostics_root / "grid_node_metrics.json").write_text(json.dumps(node_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (diagnostics_root / "jump_target_diagnostics.json").write_text(json.dumps(jump_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "area": area_dir.name,
        "diagnostics_dir": str(diagnostics_root),
        "node_summary": node_payload["summary"],
        "jump_count": jump_payload["jump_count"],
        "long_jump_count_ge_2m": jump_payload["long_jump_count_ge_2m"],
        "jump_targets_within_overlap_radius_count": jump_payload["jump_targets_within_overlap_radius_count"],
        "artifacts": {
            "path_territory_jumps": str(diagnostics_root / "01_path_territory_jumps.png"),
            "nodes_debug_enriched": str(diagnostics_root / "02_nodes_debug_enriched.png"),
            "jump_target_context": str(diagnostics_root / "03_jump_target_context.png"),
            "grid_node_metrics": str(diagnostics_root / "grid_node_metrics.json"),
            "jump_target_diagnostics": str(diagnostics_root / "jump_target_diagnostics.json"),
        },
    }


def summarize_jump_target_classes(jump_targets: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for jump in jump_targets:
        metrics = jump.get("target_node_metrics") or {}
        for tag in metrics.get("classification", []):
            counts[tag] = counts.get(tag, 0) + 1
    return dict(sorted(counts.items()))


def select_area_dirs(run_dir: Path, args: argparse.Namespace) -> list[Path]:
    area_dirs = sorted(path for path in run_dir.iterdir() if path.is_dir() and (path / "summary.json").is_file())
    if args.area:
        selected = set(args.area)
        area_dirs = [path for path in area_dirs if path.name in selected]
    elif args.focus_only:
        selected = set(DEFAULT_FOCUS_AREAS)
        area_dirs = [path for path in area_dirs if path.name in selected]
    return area_dirs


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.is_dir():
        raise ValueError(f"run directory does not exist: {run_dir}")
    area_dirs = select_area_dirs(run_dir, args)
    summaries = [diagnose_area(area_dir, args) for area_dir in area_dirs]
    output = {
        "run_dir": str(run_dir),
        "area_count": int(len(summaries)),
        "actual_clean_width_m": float(args.actual_clean_width_m),
        "areas": summaries,
    }
    target = run_dir / "residual_grid_node_diagnostics_summary.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
