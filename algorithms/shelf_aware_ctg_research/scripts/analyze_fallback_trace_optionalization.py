from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from algorithms.shelf_aware_ctg_research.scripts.diagnose_path_grid_jumps import load_json
from algorithms.shelf_aware_ctg_research.scripts.simulate_residual_pruning import read_area_paths


ANALYSIS_VERSION = "fallback_trace_optionalization_v1"
OPTIONAL_CLASSES = {"optional_by_overlap_high_confidence", "optional_by_overlap_needs_review"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze optional fallback targets using planner fallback_debug_trace artifacts.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--area", action="append", default=None)
    return parser.parse_args()


def point_distance(a: list[float] | tuple[float, float], b: list[float] | tuple[float, float]) -> float:
    return float(math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1])))


def load_classified(area_dir: Path) -> list[dict[str, Any]]:
    path = area_dir / "diagnostics" / "residual_candidate_rules" / "residual_candidate_rules.json"
    if not path.is_file():
        raise ValueError(f"missing candidate rules: {path}")
    return load_json(path).get("classified_jump_targets", [])


def optional_nodes_by_id(area_dir: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in load_classified(area_dir):
        if item.get("rule_class") not in OPTIONAL_CLASSES:
            continue
        jump = item.get("jump") or {}
        metrics = jump.get("target_node_metrics") or {}
        node_id = metrics.get("node_id")
        if node_id:
            result[str(node_id)] = item
    return result


def selected_replacement(event: dict[str, Any], optional_node_ids: set[str]) -> dict[str, Any] | None:
    for candidate in event.get("candidates", []):
        node_id = str(candidate.get("node_id"))
        if node_id not in optional_node_ids:
            return candidate
    return None


def candidate_rank(event: dict[str, Any], node_id: str) -> int | None:
    for idx, candidate in enumerate(event.get("candidates", []), start=1):
        if str(candidate.get("node_id")) == node_id:
            return idx
    return None


def analyze_area(area_dir: Path) -> dict[str, Any]:
    planner_run_dir, _path_points, resolution = read_area_paths(area_dir)
    trace_path = planner_run_dir / "fallback_debug_trace.json"
    if not trace_path.is_file():
        raise ValueError(f"missing fallback trace: {trace_path}")
    trace = load_json(trace_path)
    optional = optional_nodes_by_id(area_dir)
    optional_ids = set(optional)
    selected_optional_events = []
    for event in trace:
        selected = str(event.get("selected_node_id"))
        if selected not in optional_ids:
            continue
        replacement = selected_replacement(event, optional_ids)
        selected_candidate = None
        for candidate in event.get("candidates", []):
            if str(candidate.get("node_id")) == selected:
                selected_candidate = candidate
                break
        current = event.get("current_node") or {}
        current_center = current.get("center_rotated") or [0, 0]
        replacement_delta = None
        if replacement is not None and selected_candidate is not None:
            replacement_delta = {
                "replacement_node_id": replacement.get("node_id"),
                "replacement_energy": float(replacement.get("energy", 0.0)),
                "selected_energy": float(selected_candidate.get("energy", 0.0)),
                "energy_delta": float(replacement.get("energy", 0.0)) - float(selected_candidate.get("energy", 0.0)),
                "selected_distance_m": point_distance(current_center, selected_candidate.get("center_rotated", current_center)) * resolution,
                "replacement_distance_m": point_distance(current_center, replacement.get("center_rotated", current_center)) * resolution,
            }
        selected_optional_events.append(
            {
                "step": int(event.get("step", 0)),
                "path_index_before_selection": int(event.get("path_index_before_selection", 0)),
                "selected_node_id": selected,
                "selected_rule_class": optional[selected].get("rule_class"),
                "selected_jump_number": int((optional[selected].get("jump") or {}).get("jump_number", 0)),
                "selected_rank": candidate_rank(event, selected),
                "candidate_count": int(event.get("candidate_count", 0)),
                "unvisited_node_count_before_selection": int(event.get("unvisited_node_count_before_selection", 0)),
                "replacement": replacement_delta,
            }
        )
    with_replacement = [item for item in selected_optional_events if item.get("replacement") is not None]
    energy_deltas = [float(item["replacement"]["energy_delta"]) for item in with_replacement]
    replacement_distance_delta = [
        float(item["replacement"]["replacement_distance_m"]) - float(item["replacement"]["selected_distance_m"])
        for item in with_replacement
    ]
    output_dir = area_dir / "diagnostics" / "fallback_trace_optionalization"
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "area_dir": str(area_dir),
        "planner_run_dir": str(planner_run_dir),
        "analysis_version": ANALYSIS_VERSION,
        "fallback_event_count": int(len(trace)),
        "optional_node_count": int(len(optional_ids)),
        "selected_optional_fallback_event_count": int(len(selected_optional_events)),
        "selected_optional_with_replacement_count": int(len(with_replacement)),
        "replacement_energy_delta_mean": float(sum(energy_deltas) / len(energy_deltas)) if energy_deltas else 0.0,
        "replacement_distance_delta_m_mean": float(sum(replacement_distance_delta) / len(replacement_distance_delta)) if replacement_distance_delta else 0.0,
        "selected_optional_events": selected_optional_events,
    }
    (output_dir / "fallback_trace_optionalization.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "area": area_dir.name,
        "diagnostics_dir": str(output_dir),
        "fallback_event_count": payload["fallback_event_count"],
        "optional_node_count": payload["optional_node_count"],
        "selected_optional_fallback_event_count": payload["selected_optional_fallback_event_count"],
        "selected_optional_with_replacement_count": payload["selected_optional_with_replacement_count"],
        "replacement_energy_delta_mean": payload["replacement_energy_delta_mean"],
        "replacement_distance_delta_m_mean": payload["replacement_distance_delta_m_mean"],
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
    areas = [analyze_area(area_dir) for area_dir in select_area_dirs(run_dir, args)]
    aggregate = {
        "fallback_event_count": sum(item["fallback_event_count"] for item in areas),
        "optional_node_count": sum(item["optional_node_count"] for item in areas),
        "selected_optional_fallback_event_count": sum(item["selected_optional_fallback_event_count"] for item in areas),
        "selected_optional_with_replacement_count": sum(item["selected_optional_with_replacement_count"] for item in areas),
    }
    output = {
        "run_dir": str(run_dir),
        "analysis_version": ANALYSIS_VERSION,
        "aggregate": aggregate,
        "areas": areas,
    }
    target = run_dir / "fallback_trace_optionalization_summary.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
