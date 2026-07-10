from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from algorithms.shelf_aware_ctg_research.scripts.diagnose_path_grid_jumps import load_json


ANALYSIS_VERSION = "fallback_optionalization_feasibility_v1"
OPTIONAL_CLASSES = {"optional_by_overlap_high_confidence", "optional_by_overlap_needs_review"}
REVIEW_CLASSES = {"required_or_topology_review", "boundary_sensitive_review", "snap_or_insert_candidate", "optional_by_near_overlap_needs_review"}
REQUIRED_ARTIFACT_FIELDS = (
    "per_step_selected_node",
    "per_step_is_global_fallback",
    "per_step_candidate_energy_list",
    "per_step_unvisited_node_set_before_selection",
    "node_grid_row_col_or_stable_node_id",
    "complete_cell_original_center_and_adjusted_flag",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze whether fallback target optionalization can be replayed from current artifacts.")
    parser.add_argument("--run-dir", required=True, help="Existing shelf_aware_ctg_research run directory.")
    parser.add_argument("--area", action="append", default=None, help="Optional area folder name. Repeatable.")
    return parser.parse_args()


def load_area_rules(area_dir: Path) -> list[dict[str, Any]]:
    path = area_dir / "diagnostics" / "residual_candidate_rules" / "residual_candidate_rules.json"
    if not path.is_file():
        raise ValueError(f"missing residual candidate rules: {path}")
    return load_json(path).get("classified_jump_targets", [])


def load_local_reconnect(area_dir: Path) -> dict[int, str]:
    path = area_dir / "diagnostics" / "local_reconnect_snap" / "local_reconnect_snap.json"
    if not path.is_file():
        return {}
    payload = load_json(path)
    result = {}
    for item in payload.get("reconnect_candidates", []):
        result[int(item.get("jump_number", 0))] = str(item.get("verdict", "unknown"))
    return result


def analyze_area(area_dir: Path) -> dict[str, Any]:
    rules = load_area_rules(area_dir)
    reconnect_by_jump = load_local_reconnect(area_dir)
    optional = []
    review = []
    for item in rules:
        rule_class = str(item.get("rule_class", ""))
        jump = item.get("jump") or {}
        jump_number = int(item.get("jump_number", jump.get("jump_number", 0)))
        record = {
            "jump_number": jump_number,
            "rule_class": rule_class,
            "jump_length_m": float(jump.get("length_m", 0.0)),
            "end_distance_to_prior_path_m": float(jump.get("end_distance_to_prior_path_m", 0.0)),
            "reconnect_verdict": reconnect_by_jump.get(jump_number),
        }
        if rule_class in OPTIONAL_CLASSES:
            optional.append(record)
        elif rule_class in REVIEW_CLASSES:
            review.append(record)
    optional_reconnect_ready = [item for item in optional if item.get("reconnect_verdict") == "reconnect_ready"]
    optional_reconnect_blocked = [item for item in optional if item.get("reconnect_verdict") == "reconnect_blocked"]
    optional_coverage_review = [item for item in optional if item.get("reconnect_verdict") == "coverage_risk_review"]
    return {
        "area": area_dir.name,
        "exact_fallback_replay_supported": False,
        "reason": "Current artifacts contain final path, jump segments, final grid-node CSV, and diagnostics; they do not contain per-step fallback candidate lists or unvisited sets.",
        "required_missing_artifact_fields": list(REQUIRED_ARTIFACT_FIELDS),
        "proxy_summary": {
            "jump_target_count": int(len(rules)),
            "optional_overlap_candidate_count": int(len(optional)),
            "review_candidate_count": int(len(review)),
            "optional_reconnect_ready_count": int(len(optional_reconnect_ready)),
            "optional_reconnect_blocked_count": int(len(optional_reconnect_blocked)),
            "optional_coverage_review_count": int(len(optional_coverage_review)),
            "optional_jump_length_upper_bound_m": float(sum(item["jump_length_m"] for item in optional)),
            "reconnect_ready_jump_length_upper_bound_m": float(sum(item["jump_length_m"] for item in optional_reconnect_ready)),
        },
        "optional_candidates": optional,
        "review_candidates": review,
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
    area_results = []
    for area_dir in select_area_dirs(run_dir, args):
        result = analyze_area(area_dir)
        output_dir = area_dir / "diagnostics" / "fallback_optionalization_feasibility"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "fallback_optionalization_feasibility.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        area_results.append(result)
    aggregate = {
        "jump_target_count": sum(item["proxy_summary"]["jump_target_count"] for item in area_results),
        "optional_overlap_candidate_count": sum(item["proxy_summary"]["optional_overlap_candidate_count"] for item in area_results),
        "review_candidate_count": sum(item["proxy_summary"]["review_candidate_count"] for item in area_results),
        "optional_reconnect_ready_count": sum(item["proxy_summary"]["optional_reconnect_ready_count"] for item in area_results),
        "optional_reconnect_blocked_count": sum(item["proxy_summary"]["optional_reconnect_blocked_count"] for item in area_results),
        "optional_coverage_review_count": sum(item["proxy_summary"]["optional_coverage_review_count"] for item in area_results),
        "optional_jump_length_upper_bound_m": sum(item["proxy_summary"]["optional_jump_length_upper_bound_m"] for item in area_results),
        "reconnect_ready_jump_length_upper_bound_m": sum(item["proxy_summary"]["reconnect_ready_jump_length_upper_bound_m"] for item in area_results),
    }
    output = {
        "run_dir": str(run_dir),
        "analysis_version": ANALYSIS_VERSION,
        "exact_fallback_replay_supported": False,
        "required_missing_artifact_fields": list(REQUIRED_ARTIFACT_FIELDS),
        "aggregate_proxy_summary": aggregate,
        "areas": area_results,
    }
    target = run_dir / "fallback_optionalization_feasibility_summary.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
