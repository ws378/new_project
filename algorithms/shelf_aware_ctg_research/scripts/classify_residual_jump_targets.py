from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from algorithms.shelf_aware_ctg_research.scripts.diagnose_path_grid_jumps import build_label_overlay, load_json, path_points_from_json
from algorithms.shelf_aware_ctg_research.scripts.diagnose_residual_grid_nodes import circle_point, draw_legend


RULE_VERSION = "residual_candidate_rules_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify residual jump-target candidates without changing the planner.")
    parser.add_argument("--run-dir", required=True, help="Existing shelf_aware_ctg_research run directory with residual_grid_nodes diagnostics.")
    parser.add_argument("--area", action="append", default=None, help="Optional area folder name. Repeatable.")
    parser.add_argument("--max-contact-jumps", type=int, default=24, help="Maximum jump targets per contact sheet.")
    parser.add_argument("--crop-radius-px", type=int, default=80, help="Half size of per-jump target context crop in pixels.")
    return parser.parse_args()


def classify_jump_target(jump: dict[str, Any]) -> tuple[str, list[str]]:
    metrics = jump.get("target_node_metrics") or {}
    tags = set(metrics.get("classification", []))
    reasons: list[str] = []
    if bool(jump.get("end_within_overlap_radius")):
        reasons.append("target is within actual-clean overlap radius of prior path")
    if "candidate_near_overlap_margin" in tags:
        reasons.append("target is just outside overlap radius but within margin")
    if "candidate_by_boundary_sensitive" in tags:
        reasons.append("target node is boundary-sensitive")
    if "candidate_by_low_degree" in tags:
        reasons.append("target node has low estimated degree")
    if "candidate_by_small_local_free_area" in tags:
        reasons.append("target node has small local free area")
    if "candidate_by_unknown_or_junction_label" in tags:
        reasons.append("target is in unknown/junction territory label")

    if bool(jump.get("end_within_overlap_radius")) and (
        "candidate_by_boundary_sensitive" in tags
        or "candidate_by_low_degree" in tags
        or "candidate_by_small_local_free_area" in tags
        or "candidate_by_unknown_or_junction_label" in tags
    ):
        return "optional_by_overlap_high_confidence", reasons
    if bool(jump.get("end_within_overlap_radius")):
        return "optional_by_overlap_needs_review", reasons
    if "candidate_near_overlap_margin" in tags and (
        "candidate_by_boundary_sensitive" in tags or "candidate_by_low_degree" in tags or "candidate_by_small_local_free_area" in tags
    ):
        return "optional_by_near_overlap_needs_review", reasons
    if "candidate_by_low_degree" in tags or "candidate_by_small_local_free_area" in tags:
        return "snap_or_insert_candidate", reasons
    if "candidate_by_boundary_sensitive" in tags:
        return "boundary_sensitive_review", reasons
    return "required_or_topology_review", reasons or ["no low-value evidence from current diagnostics"]


def read_area_paths(area_dir: Path) -> tuple[Path, list[tuple[float, float]]]:
    summary = load_json(area_dir / "summary.json")
    baseline = summary.get("shelf_aware_baseline", {})
    run_value = baseline.get("planner_run_dir") or baseline.get("artifacts_dir") or ""
    run_dir = Path(run_value)
    if not run_dir.is_dir():
        runs = sorted((area_dir / "shelf_aware_baseline").glob("run_*"))
        if not runs:
            raise ValueError(f"missing baseline run for {area_dir}")
        run_dir = runs[-1]
    return run_dir, path_points_from_json(run_dir / "path_pixels.json")


def load_context_base(area_dir: Path) -> np.ndarray:
    context = cv2.imread(str(area_dir / "diagnostics" / "path_grid_jumps" / "00_territory_label_context.png"), cv2.IMREAD_COLOR)
    if context is not None:
        return context
    prepared = cv2.imread(str(area_dir / "01_prepared_map.png"), cv2.IMREAD_GRAYSCALE)
    if prepared is None:
        raise ValueError(f"missing context image for {area_dir}")
    return cv2.cvtColor(prepared, cv2.COLOR_GRAY2BGR)


def crop_with_padding(image: np.ndarray, center: tuple[float, float], radius: int) -> np.ndarray:
    x = int(round(float(center[0])))
    y = int(round(float(center[1])))
    h, w = image.shape[:2]
    x0 = max(0, x - radius)
    x1 = min(w, x + radius + 1)
    y0 = max(0, y - radius)
    y1 = min(h, y + radius + 1)
    crop = image[y0:y1, x0:x1].copy()
    target_h = radius * 2 + 1
    target_w = radius * 2 + 1
    canvas = np.full((target_h, target_w, 3), 245, dtype=np.uint8)
    canvas[: crop.shape[0], : crop.shape[1]] = crop
    return canvas


def draw_contact_sheet(
    area_dir: Path,
    classified: list[dict[str, Any]],
    path_points: list[tuple[float, float]],
    output_path: Path,
    max_items: int,
    crop_radius_px: int,
) -> str:
    if not classified:
        return ""
    base = load_context_base(area_dir)
    annotated = base.copy()
    for prev, curr in zip(path_points, path_points[1:]):
        cv2.line(annotated, circle_point(prev), circle_point(curr), (50, 50, 50), 1, cv2.LINE_AA)
    crops = []
    for item in classified[:max_items]:
        jump = item["jump"]
        start = tuple(jump["start_xy"])
        end = tuple(jump["end_xy"])
        local = annotated.copy()
        cv2.line(local, circle_point(start), circle_point(end), (0, 0, 220), 2, cv2.LINE_AA)
        cv2.circle(local, circle_point(end), 6, class_color(item["rule_class"]), -1)
        crop = crop_with_padding(local, end, crop_radius_px)
        title = f"#{item['jump_number']} {item['rule_class']}"
        length = f"L={jump.get('length_m', 0.0):.1f}m prior={jump.get('end_distance_to_prior_path_m', 0.0):.2f}m"
        cv2.rectangle(crop, (0, 0), (crop.shape[1] - 1, 34), (245, 245, 245), -1)
        cv2.putText(crop, title[:36], (4, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (10, 10, 10), 1, cv2.LINE_AA)
        cv2.putText(crop, length[:42], (4, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (10, 10, 10), 1, cv2.LINE_AA)
        crops.append(crop)
    cols = min(4, len(crops))
    rows = int(np.ceil(len(crops) / cols))
    h, w = crops[0].shape[:2]
    sheet = np.full((rows * h, cols * w, 3), 245, dtype=np.uint8)
    for idx, crop in enumerate(crops):
        row = idx // cols
        col = idx % cols
        sheet[row * h : (row + 1) * h, col * w : (col + 1) * w] = crop
    cv2.imwrite(str(output_path), sheet)
    return str(output_path)


def class_color(rule_class: str) -> tuple[int, int, int]:
    if rule_class == "optional_by_overlap_high_confidence":
        return (0, 180, 255)
    if rule_class == "optional_by_overlap_needs_review":
        return (0, 220, 220)
    if rule_class == "optional_by_near_overlap_needs_review":
        return (0, 160, 220)
    if rule_class == "snap_or_insert_candidate":
        return (255, 0, 180)
    if rule_class == "boundary_sensitive_review":
        return (0, 140, 255)
    return (0, 0, 220)


def summarize_classes(classified: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    avoidable_length_upper_bound_m = 0.0
    for item in classified:
        cls = item["rule_class"]
        counts[cls] = counts.get(cls, 0) + 1
        if cls in {"optional_by_overlap_high_confidence", "optional_by_overlap_needs_review"}:
            avoidable_length_upper_bound_m += float(item["jump"].get("length_m", 0.0))
    return {
        "rule_counts": dict(sorted(counts.items())),
        "optional_overlap_candidate_count": int(
            counts.get("optional_by_overlap_high_confidence", 0) + counts.get("optional_by_overlap_needs_review", 0)
        ),
        "avoidable_jump_length_upper_bound_m": float(avoidable_length_upper_bound_m),
        "note": "Upper bound only: skipping a jump target may require reconnecting nearby path segments and checking coverage loss.",
    }


def classify_area(area_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    residual_dir = area_dir / "diagnostics" / "residual_grid_nodes"
    jump_path = residual_dir / "jump_target_diagnostics.json"
    if not jump_path.is_file():
        raise ValueError(f"missing residual jump diagnostics: {jump_path}")
    diagnostics = load_json(jump_path)
    classified: list[dict[str, Any]] = []
    for jump in diagnostics.get("jumps", []):
        rule_class, reasons = classify_jump_target(jump)
        classified.append(
            {
                "jump_number": int(jump.get("jump_number", len(classified) + 1)),
                "rule_class": rule_class,
                "reasons": reasons,
                "jump": jump,
            }
        )
    classified.sort(key=lambda item: (class_rank(item["rule_class"]), -float(item["jump"].get("length_m", 0.0))))
    output_dir = area_dir / "diagnostics" / "residual_candidate_rules"
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir, path_points = read_area_paths(area_dir)
    contact_sheet = draw_contact_sheet(
        area_dir,
        classified,
        path_points,
        output_dir / "01_jump_target_context_sheet.png",
        max_items=int(args.max_contact_jumps),
        crop_radius_px=int(args.crop_radius_px),
    )
    payload = {
        "area_dir": str(area_dir),
        "planner_run_dir": str(run_dir),
        "rule_version": RULE_VERSION,
        "summary": summarize_classes(classified),
        "artifacts": {"jump_target_context_sheet": contact_sheet},
        "classified_jump_targets": classified,
    }
    (output_dir / "residual_candidate_rules.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "area": area_dir.name,
        "diagnostics_dir": str(output_dir),
        "summary": payload["summary"],
        "artifacts": payload["artifacts"],
    }


def class_rank(rule_class: str) -> int:
    order = {
        "optional_by_overlap_high_confidence": 0,
        "optional_by_overlap_needs_review": 1,
        "optional_by_near_overlap_needs_review": 2,
        "snap_or_insert_candidate": 3,
        "boundary_sensitive_review": 4,
        "required_or_topology_review": 5,
    }
    return order.get(rule_class, 99)


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
    summaries = [classify_area(area_dir, args) for area_dir in select_area_dirs(run_dir, args)]
    aggregate_counts: dict[str, int] = {}
    upper_bound = 0.0
    for area in summaries:
        for key, value in area["summary"]["rule_counts"].items():
            aggregate_counts[key] = aggregate_counts.get(key, 0) + int(value)
        upper_bound += float(area["summary"].get("avoidable_jump_length_upper_bound_m", 0.0))
    output = {
        "run_dir": str(run_dir),
        "area_count": int(len(summaries)),
        "rule_version": RULE_VERSION,
        "aggregate_rule_counts": dict(sorted(aggregate_counts.items())),
        "avoidable_jump_length_upper_bound_m": float(upper_bound),
        "areas": summaries,
    }
    target = run_dir / "residual_candidate_rules_summary.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
