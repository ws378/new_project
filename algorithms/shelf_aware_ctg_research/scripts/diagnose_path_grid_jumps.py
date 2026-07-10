from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from algorithms.shelf_aware_ctg_research.src.ctg_territory_extractor import extract_ctg_territory
from algorithms.shelf_aware_ctg_research.src.project_inputs import build_study_input
from algorithms.shelf_aware_ctg_research.src.territory_expansion import expand_dead_end_territories


VARIANTS = ("shelf_aware_baseline",)
PALETTE = np.array(
    [
        (66, 135, 245),
        (245, 130, 48),
        (80, 180, 95),
        (220, 80, 80),
        (150, 100, 220),
        (80, 190, 200),
        (230, 190, 70),
        (190, 90, 160),
        (120, 170, 70),
        (90, 120, 190),
        (200, 130, 80),
        (110, 110, 110),
    ],
    dtype=np.uint8,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose shelf-aware path, grid nodes, and jumps against CTG territory labels.")
    parser.add_argument("--run-dir", required=True, help="Existing shelf_aware_ctg_research run directory.")
    parser.add_argument("--area", action="append", default=None, help="Optional area folder name to diagnose. Repeatable.")
    parser.add_argument("--actual-clean-width-m", type=float, default=0.70, help="Assumed real cleaning width for overlap diagnostics.")
    parser.add_argument("--max-areas", type=int, default=None, help="Optional maximum number of area folders to process.")
    parser.add_argument("--no-boundary-smoothing", action="store_true", help="Recompute CTG labels without boundary smoothing.")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_child_run(variant_dir: Path) -> Path | None:
    runs = sorted(path for path in variant_dir.glob("run_*") if path.is_dir())
    return runs[-1] if runs else None


def deterministic_color(label: int) -> tuple[int, int, int]:
    if label < 0:
        return (150, 150, 150)
    return tuple(int(value) for value in PALETTE[int(label) % len(PALETTE)])


def point_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1])))


def sample_label(labels: np.ndarray, point: tuple[float, float]) -> int:
    x = int(round(float(point[0])))
    y = int(round(float(point[1])))
    if y < 0 or y >= labels.shape[0] or x < 0 or x >= labels.shape[1]:
        return -2
    return int(labels[y, x])


def min_distance_to_points(point: tuple[float, float], points: list[tuple[float, float]]) -> float:
    if not points:
        return float("inf")
    px, py = float(point[0]), float(point[1])
    return float(min(math.hypot(px - x, py - y) for x, y in points))


def nearest_node(point: tuple[float, float], nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not nodes:
        return None
    px, py = float(point[0]), float(point[1])
    best = min(nodes, key=lambda node: math.hypot(px - float(node["x"]), py - float(node["y"])))
    distance = math.hypot(px - float(best["x"]), py - float(best["y"]))
    result = dict(best)
    result["distance_to_query_px"] = float(distance)
    return result


def path_points_from_json(path: Path) -> list[tuple[float, float]]:
    payload = load_json(path)
    return [(float(item["x"]), float(item["y"])) for item in payload]


def indexed_path_points(path: Path) -> dict[int, tuple[float, float]]:
    payload = load_json(path)
    return {int(item["index"]): (float(item["x"]), float(item["y"])) for item in payload}


def read_jumps(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    jumps = []
    for segment in load_json(path):
        if len(segment) != 2:
            continue
        start, end = segment
        start_point = (float(start["x"]), float(start["y"]))
        end_point = (float(end["x"]), float(end["y"]))
        jumps.append(
            {
                "start_index": int(start["index"]),
                "end_index": int(end["index"]),
                "start_xy": [start_point[0], start_point[1]],
                "end_xy": [end_point[0], end_point[1]],
                "length_px": point_distance(start_point, end_point),
            }
        )
    return jumps


def read_energy_nodes(csv_path: Path, metadata: dict[str, Any], map_height: int) -> list[dict[str, Any]]:
    if not csv_path.is_file():
        return []
    resolution = float(metadata["map_resolution"])
    origin = metadata.get("map_origin", {"x": 0.0, "y": 0.0})
    origin_x = float(origin.get("x", 0.0))
    origin_y = float(origin.get("y", 0.0))
    nodes = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            x_world = float(row["x"])
            y_world = float(row["y"])
            x = (x_world - origin_x) / resolution
            y = float(map_height) - (y_world - origin_y) / resolution
            node = {
                "x": float(x),
                "y": float(y),
                "visited": int(row["status"]) == 1,
                "obstacle_neighbor_count": int(row["obstacle_neighbor_count"]),
                "min_distance_m": float(row["min_distance_m"]),
            }
            for optional_key in (
                "node_id",
                "grid_row",
                "grid_col",
                "center_rotated_x",
                "center_rotated_y",
                "grid_center_rotated_x",
                "grid_center_rotated_y",
                "adjusted_from_grid_center",
                "non_obstacle_neighbor_count",
            ):
                if optional_key in row and row[optional_key] != "":
                    value = row[optional_key]
                    if optional_key == "node_id":
                        node[optional_key] = value
                    else:
                        node[optional_key] = int(value)
            nodes.append(node)
    return nodes


def build_label_overlay(base: np.ndarray, labels: np.ndarray) -> np.ndarray:
    image = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR) if base.ndim == 2 else base.copy()
    overlay = image.copy()
    for label in sorted(int(item) for item in np.unique(labels) if int(item) >= 0):
        mask = labels == label
        overlay[mask] = deterministic_color(label)
    unknown_mask = labels < 0
    overlay[unknown_mask & (base > 0)] = (170, 170, 170)
    return cv2.addWeighted(image, 0.45, overlay, 0.55, 0.0)


def draw_path_by_label(base: np.ndarray, labels: np.ndarray, path_points: list[tuple[float, float]], output_path: Path) -> None:
    image = build_label_overlay(base, labels)
    for prev, curr in zip(path_points, path_points[1:]):
        label = sample_label(labels, curr)
        color = deterministic_color(label)
        p0 = (int(round(prev[0])), int(round(prev[1])))
        p1 = (int(round(curr[0])), int(round(curr[1])))
        cv2.line(image, p0, p1, color, 1, cv2.LINE_AA)
    for idx, point in enumerate(path_points):
        if idx % 25 != 0:
            continue
        cv2.circle(image, (int(round(point[0])), int(round(point[1]))), 2, (0, 0, 0), -1)
    cv2.imwrite(str(output_path), image)


def draw_jumps(base: np.ndarray, labels: np.ndarray, jumps: list[dict[str, Any]], output_path: Path) -> None:
    image = build_label_overlay(base, labels)
    for index, jump in enumerate(jumps, start=1):
        start = tuple(jump["start_xy"])
        end = tuple(jump["end_xy"])
        p0 = (int(round(start[0])), int(round(start[1])))
        p1 = (int(round(end[0])), int(round(end[1])))
        cv2.line(image, p0, p1, (0, 0, 255), 2, cv2.LINE_AA)
        cv2.circle(image, p1, 4, (0, 255, 255), -1)
        if index <= 30:
            cv2.putText(image, str(index), p1, cv2.FONT_HERSHEY_SIMPLEX, 0.35, (20, 20, 20), 1, cv2.LINE_AA)
    cv2.imwrite(str(output_path), image)


def draw_nodes(base: np.ndarray, labels: np.ndarray, nodes: list[dict[str, Any]], output_path: Path) -> None:
    image = build_label_overlay(base, labels)
    for node in nodes:
        point = (int(round(node["x"])), int(round(node["y"])))
        if node["visited"]:
            color = (20, 170, 20)
            radius = 1
        else:
            color = (0, 0, 255)
            radius = 3
        if int(node["obstacle_neighbor_count"]) >= 5:
            color = (0, 160, 255)
            radius = max(radius, 3)
        cv2.circle(image, point, radius, color, -1)
    cv2.imwrite(str(output_path), image)


def compute_edge_switches(labels: np.ndarray, path_points: list[tuple[float, float]]) -> list[dict[str, Any]]:
    switches = []
    previous_label = None
    for index, point in enumerate(path_points, start=1):
        label = sample_label(labels, point)
        if previous_label is not None and label != previous_label:
            switches.append(
                {
                    "index": index,
                    "from_label": int(previous_label),
                    "to_label": int(label),
                    "xy": [float(point[0]), float(point[1])],
                }
            )
        previous_label = label
    return switches


def enrich_jumps(
    jumps: list[dict[str, Any]],
    labels: np.ndarray,
    path_points: list[tuple[float, float]],
    nodes: list[dict[str, Any]],
    resolution: float,
    overlap_radius_px: float,
) -> list[dict[str, Any]]:
    enriched = []
    for jump in jumps:
        start = tuple(jump["start_xy"])
        end = tuple(jump["end_xy"])
        prior_points = path_points[: max(0, int(jump["start_index"]) - 1)]
        end_to_prior = min_distance_to_points(end, prior_points)
        item = dict(jump)
        item["length_m"] = float(item["length_px"] * resolution)
        item["start_label"] = sample_label(labels, start)
        item["end_label"] = sample_label(labels, end)
        item["edge_label_changed"] = bool(item["start_label"] != item["end_label"])
        item["end_distance_to_prior_path_px"] = float(end_to_prior)
        item["end_distance_to_prior_path_m"] = float(end_to_prior * resolution) if math.isfinite(end_to_prior) else float("inf")
        item["end_within_overlap_radius"] = bool(end_to_prior <= overlap_radius_px)
        node = nearest_node(end, nodes)
        if node is not None:
            item["nearest_node"] = {
                "x": node["x"],
                "y": node["y"],
                "node_id": node.get("node_id"),
                "grid_row": node.get("grid_row"),
                "grid_col": node.get("grid_col"),
                "label": node.get("label", sample_label(labels, (node["x"], node["y"]))),
                "visited": node["visited"],
                "obstacle_neighbor_count": node["obstacle_neighbor_count"],
                "non_obstacle_neighbor_count": node.get("non_obstacle_neighbor_count"),
                "min_distance_m": node["min_distance_m"],
                "distance_to_query_px": node["distance_to_query_px"],
            }
        enriched.append(item)
    return enriched


def summarize_variant(
    *,
    variant_dir: Path,
    diagnostics_dir: Path,
    base: np.ndarray,
    labels: np.ndarray,
    resolution: float,
    actual_clean_width_m: float,
) -> dict[str, Any]:
    run_dir = latest_child_run(variant_dir)
    if run_dir is None:
        return {"success": False, "error": "missing planner run directory"}
    path_points = path_points_from_json(run_dir / "path_pixels.json")
    raw_path_points = path_points_from_json(run_dir / "path_pixels_raw.json") if (run_dir / "path_pixels_raw.json").is_file() else path_points
    jumps = read_jumps(run_dir / "path_jump_segments_pixels.json")
    metadata = load_json(run_dir / "metadata.json")
    nodes = read_energy_nodes(run_dir / "energy_debug.csv", metadata, base.shape[0])
    overlap_radius_px = max(0.0, (float(actual_clean_width_m) * 0.5) / float(resolution))
    edge_switches = compute_edge_switches(labels, path_points)

    for node in nodes:
        point = (float(node["x"]), float(node["y"]))
        node["label"] = sample_label(labels, point)
        node["distance_to_path_px"] = min_distance_to_points(point, raw_path_points)
        node["within_overlap_radius"] = bool(node["distance_to_path_px"] <= overlap_radius_px)

    enriched_jumps = enrich_jumps(jumps, labels, path_points, nodes, resolution, overlap_radius_px)
    unvisited_nodes = [node for node in nodes if not node["visited"]]
    low_value_unvisited = [
        node
        for node in unvisited_nodes
        if node["within_overlap_radius"] or int(node["obstacle_neighbor_count"]) >= 5 or float(node["min_distance_m"]) <= float(resolution) * 1.5
    ]
    low_clearance_nodes = [node for node in nodes if float(node["min_distance_m"]) <= float(resolution) * 1.5]
    high_obstacle_neighbor_nodes = [node for node in nodes if int(node["obstacle_neighbor_count"]) >= 5]
    unknown_label_nodes = [node for node in nodes if int(node.get("label", -2)) < 0]
    boundary_sensitive_nodes = []
    seen_boundary_keys: set[tuple[int, int]] = set()
    for node in low_clearance_nodes + high_obstacle_neighbor_nodes + unknown_label_nodes:
        key = (int(round(node["x"])), int(round(node["y"])))
        if key in seen_boundary_keys:
            continue
        seen_boundary_keys.add(key)
        boundary_sensitive_nodes.append(node)

    long_jumps = [jump for jump in enriched_jumps if float(jump["length_m"]) >= 2.0]
    overlap_jump_targets = [jump for jump in enriched_jumps if bool(jump["end_within_overlap_radius"])]
    boundary_sensitive_jump_targets = [
        jump for jump in enriched_jumps
        if int(jump.get("nearest_node", {}).get("obstacle_neighbor_count", 0)) >= 5
        or float(jump.get("nearest_node", {}).get("min_distance_m", 999.0)) <= float(resolution) * 1.5
        or int(jump.get("nearest_node", {}).get("label", 0)) < 0
    ]

    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    draw_path_by_label(base, labels, path_points, diagnostics_dir / "01_path_by_territory.png")
    draw_nodes(base, labels, nodes, diagnostics_dir / "02_grid_node_quality.png")
    draw_jumps(base, labels, enriched_jumps, diagnostics_dir / "03_jump_overlay.png")

    summary = {
        "success": True,
        "planner_run_dir": str(run_dir),
        "path_point_count": int(len(path_points)),
        "raw_path_point_count": int(len(raw_path_points)),
        "edge_switch_count": int(len(edge_switches)),
        "edge_switch_sample": edge_switches[:50],
        "jump_count": int(len(enriched_jumps)),
        "long_jump_count_ge_2m": int(len(long_jumps)),
        "jump_targets_within_overlap_radius_count": int(len(overlap_jump_targets)),
        "max_jump_length_m": float(max((jump["length_m"] for jump in enriched_jumps), default=0.0)),
        "node_count": int(len(nodes)),
        "visited_node_count": int(sum(1 for node in nodes if node["visited"])),
        "unvisited_node_count": int(len(unvisited_nodes)),
        "low_clearance_node_count": int(len(low_clearance_nodes)),
        "high_obstacle_neighbor_node_count": int(len(high_obstacle_neighbor_nodes)),
        "unknown_label_node_count": int(len(unknown_label_nodes)),
        "boundary_sensitive_node_count": int(len(boundary_sensitive_nodes)),
        "boundary_sensitive_node_ratio": float(len(boundary_sensitive_nodes) / len(nodes)) if nodes else 0.0,
        "low_value_unvisited_node_count": int(len(low_value_unvisited)),
        "low_value_unvisited_ratio": float(len(low_value_unvisited) / len(unvisited_nodes)) if unvisited_nodes else 0.0,
        "boundary_sensitive_jump_target_count": int(len(boundary_sensitive_jump_targets)),
        "overlap_radius_px": float(overlap_radius_px),
        "overlap_radius_m": float(overlap_radius_px * resolution),
        "jump_sample": enriched_jumps[:80],
        "unvisited_node_sample": unvisited_nodes[:80],
        "low_value_unvisited_node_sample": low_value_unvisited[:80],
        "boundary_sensitive_node_sample": boundary_sensitive_nodes[:80],
        "boundary_sensitive_jump_target_sample": boundary_sensitive_jump_targets[:80],
        "artifacts": {
            "path_by_territory": str(diagnostics_dir / "01_path_by_territory.png"),
            "grid_node_quality": str(diagnostics_dir / "02_grid_node_quality.png"),
            "jump_overlay": str(diagnostics_dir / "03_jump_overlay.png"),
        },
    }
    (diagnostics_dir / "diagnostics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def build_area_labels(area_dir: Path, apply_boundary_smoothing: bool) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    summary = load_json(area_dir / "summary.json")
    project_dir = Path(summary["project_dir"])
    area_id = int(summary["area_id"])
    study_input = build_study_input(project_dir, area_id, area_dir / "diagnostics" / "prepare_map_recomputed")
    ctg = extract_ctg_territory(study_input, apply_boundary_smoothing=apply_boundary_smoothing)
    geometry_result = ctg["geometry_result"]
    graph_info = ctg["topology_result"].graph_info
    lane_info = tuple(ctg["coverage_lane_sweep_info"].coverage_lane_info)
    expanded = expand_dead_end_territories(geometry_result, graph_info, lane_info)
    free_mask = np.where(np.asarray(geometry_result.free_mask) > 0, 255, 0).astype(np.uint8)
    return free_mask, np.asarray(expanded.labels, dtype=np.int32), {
        "project_dir": str(project_dir),
        "area_id": area_id,
        "node_count": int(len(graph_info.nodes)),
        "edge_count": int(len(graph_info.edges)),
        "label_shape": list(expanded.labels.shape),
        "free_shape": list(free_mask.shape),
    }


def diagnose_area(area_dir: Path, actual_clean_width_m: float, apply_boundary_smoothing: bool) -> dict[str, Any]:
    diagnostics_root = area_dir / "diagnostics" / "path_grid_jumps"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    free_mask, labels, label_info = build_area_labels(area_dir, apply_boundary_smoothing)
    cv2.imwrite(str(diagnostics_root / "00_territory_label_context.png"), build_label_overlay(free_mask, labels))
    area_summary = {
        "area_dir": str(area_dir),
        "label_info": label_info,
        "actual_clean_width_m": float(actual_clean_width_m),
        "variants": {},
    }
    for variant in VARIANTS:
        area_summary["variants"][variant] = summarize_variant(
            variant_dir=area_dir / variant,
            diagnostics_dir=diagnostics_root / variant,
            base=free_mask,
            labels=labels,
            resolution=float(load_json(area_dir / "summary.json")["resolution_m_per_px"]),
            actual_clean_width_m=actual_clean_width_m,
        )
    (diagnostics_root / "area_diagnostics.json").write_text(json.dumps(area_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return area_summary


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.is_dir():
        raise ValueError(f"run directory does not exist: {run_dir}")
    selected = set(args.area or [])
    area_dirs = sorted(path for path in run_dir.iterdir() if path.is_dir() and (path / "summary.json").is_file())
    if selected:
        area_dirs = [path for path in area_dirs if path.name in selected]
    if args.max_areas is not None:
        area_dirs = area_dirs[: int(args.max_areas)]
    summaries = [
        diagnose_area(
            area_dir,
            actual_clean_width_m=float(args.actual_clean_width_m),
            apply_boundary_smoothing=not args.no_boundary_smoothing,
        )
        for area_dir in area_dirs
    ]
    output = {
        "run_dir": str(run_dir),
        "area_count": int(len(summaries)),
        "actual_clean_width_m": float(args.actual_clean_width_m),
        "areas": summaries,
    }
    target = run_dir / "path_grid_jump_diagnostics_summary.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
