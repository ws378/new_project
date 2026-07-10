from __future__ import annotations

import argparse
import json
from pathlib import Path

from algorithms.shelf_aware_ctg_research.src.node_semantics import (
    NodeSemanticsConfig,
    build_node_semantics_from_maps,
    build_semantic_maps,
    write_node_semantics_outputs,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build territory/junction-aware grid-node semantics for shelf_aware_ctg_research runs.")
    parser.add_argument("--run-dir", required=True, help="Existing shelf_aware_ctg_research run directory.")
    parser.add_argument("--area", action="append", default=None, help="Optional area folder name. Repeatable.")
    parser.add_argument("--no-boundary-smoothing", action="store_true", help="Recompute CTG labels without boundary smoothing.")
    parser.add_argument("--footprint-radius-factor", type=float, default=0.5, help="Node footprint radius as factor of coverage_width_px.")
    parser.add_argument("--small-local-free-ratio", type=float, default=0.45, help="Threshold for small local free ratio.")
    parser.add_argument("--low-degree-threshold", type=int, default=5, help="Threshold for low-degree node feature.")
    parser.add_argument("--obstacle-neighbor-boundary-threshold", type=int, default=2, help="Threshold for obstacle-neighbor boundary feature.")
    parser.add_argument("--mixed-ratio-threshold", type=float, default=0.10, help="Minimum ratio for a space type to count as mixed footprint.")
    return parser.parse_args()


def select_area_dirs(run_dir: Path, selected: list[str] | None) -> list[Path]:
    area_dirs = sorted(path for path in run_dir.iterdir() if path.is_dir() and (path / "summary.json").is_file())
    if selected:
        names = set(selected)
        area_dirs = [path for path in area_dirs if path.name in names]
    return area_dirs


def process_area(area_dir: Path, args: argparse.Namespace) -> dict:
    config = NodeSemanticsConfig(
        footprint_radius_factor=float(args.footprint_radius_factor),
        small_local_free_ratio_threshold=float(args.small_local_free_ratio),
        low_degree_threshold=int(args.low_degree_threshold),
        obstacle_neighbor_boundary_threshold=int(args.obstacle_neighbor_boundary_threshold),
        mixed_ratio_threshold=float(args.mixed_ratio_threshold),
    )
    free_mask, territory_labels, junction_id_map, label_info = build_semantic_maps(area_dir, apply_boundary_smoothing=not args.no_boundary_smoothing)
    payload = build_node_semantics_from_maps(
        area_dir,
        free_mask=free_mask,
        territory_labels=territory_labels,
        junction_id_map=junction_id_map,
        label_info=label_info,
        config=config,
    )
    output_dir = area_dir / "diagnostics" / "node_semantics"
    artifacts = write_node_semantics_outputs(payload, free_mask, output_dir)
    return {
        "area": area_dir.name,
        "diagnostics_dir": str(output_dir),
        "summary": payload["summary"],
        "artifacts": artifacts,
    }


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.is_dir():
        raise ValueError(f"run directory does not exist: {run_dir}")
    records = [process_area(area_dir, args) for area_dir in select_area_dirs(run_dir, args.area)]
    aggregate_roles: dict[str, int] = {}
    aggregate_spaces: dict[str, int] = {}
    for record in records:
        for key, value in record["summary"].get("node_role_counts", {}).items():
            aggregate_roles[key] = aggregate_roles.get(key, 0) + int(value)
        for key, value in record["summary"].get("primary_space_counts", {}).items():
            aggregate_spaces[key] = aggregate_spaces.get(key, 0) + int(value)
    output = {
        "run_dir": str(run_dir),
        "area_count": int(len(records)),
        "aggregate_node_role_counts": dict(sorted(aggregate_roles.items())),
        "aggregate_primary_space_counts": dict(sorted(aggregate_spaces.items())),
        "areas": records,
    }
    target = run_dir / "node_semantics_summary.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
