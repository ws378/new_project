#!/usr/bin/env python3
"""对 shelfAware 与 ShelfAware+TurnCost 输出同口径只读几何诊断对比。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.turn_cost_coverage_research.scripts.diagnostics.run_geometry_coverage_readonly_diagnostic import (
    run_diagnostic,
)


COMPARE_KEYS = (
    "body_swept_collision_count",
    "body_tight_clearance_count",
    "turn_swept_collision_count",
    "turn_swept_tight_clearance_count",
    "sharp_turn_window_count",
    "continuous_zigzag_count",
    "direction_change_window_count",
    "cleaning_footprint_coverage_ratio",
    "cleaning_footprint_gap_area_m2",
    "brush_coverage_ratio",
    "squeegee_coverage_ratio",
    "buffer_coverage_ratio",
    "buffer_coverage_vs_cleaning_coverage_delta",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-name", required=True, help="对比 case 名称。")
    parser.add_argument("--shelf-aware-run-dir", type=Path, required=True, help="shelfAware 运行目录。")
    parser.add_argument("--turn-cost-run-dir", type=Path, required=True, help="ShelfAware+TurnCost 运行目录。")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "algorithms" / "turn_cost_coverage_research" / "output",
        help="对比输出根目录。",
    )
    parser.add_argument("--max-visual-size", type=int, default=1800)
    return parser.parse_args()


def _planner_run_dir(run_dir: Path) -> Path:
    if (run_dir / "region_mask.png").is_file() and (run_dir / "path_pixels.json").is_file():
        return run_dir
    planner_runs = sorted((run_dir / "planner").glob("run_*"))
    valid = [path for path in planner_runs if (path / "region_mask.png").is_file() and (path / "path_pixels.json").is_file()]
    if not valid:
        raise FileNotFoundError(f"未找到可诊断 planner run: {run_dir}")
    return valid[-1]


def _area_dir_from(run_dir: Path, diagnostic_run_dir: Path) -> Path:
    if (run_dir / "preprocess" / "prepare_map").is_dir():
        return run_dir
    if diagnostic_run_dir.parent.name == "planner":
        return diagnostic_run_dir.parent.parent
    return run_dir


def _read_summary(output_dir: Path) -> dict[str, Any]:
    return json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))


def _diagnose_one(label: str, run_dir: Path, case_name: str, output_root: Path, max_visual_size: int) -> Path:
    diagnostic_run_dir = _planner_run_dir(run_dir)
    area_dir = _area_dir_from(run_dir, diagnostic_run_dir)
    args = argparse.Namespace(
        run_dir=diagnostic_run_dir,
        prepare_dir=area_dir / "preprocess" / "prepare_map",
        output_root=output_root,
        case_name=f"{case_name}_{label}",
        max_visual_size=max_visual_size,
    )
    return run_diagnostic(args)


def main() -> None:
    args = parse_args()
    output_root = args.output_root.expanduser().resolve()
    shelf_dir = args.shelf_aware_run_dir.expanduser().resolve()
    turn_dir = args.turn_cost_run_dir.expanduser().resolve()

    shelf_output = _diagnose_one("shelfAware", shelf_dir, args.case_name, output_root, args.max_visual_size)
    turn_output = _diagnose_one("ShelfAwareTurnCost", turn_dir, args.case_name, output_root, args.max_visual_size)
    shelf_summary = _read_summary(shelf_output)
    turn_summary = _read_summary(turn_output)

    comparison: dict[str, Any] = {
        "version": "geometry_coverage_plan_comparison.v1",
        "case_name": args.case_name,
        "diagnostic_scope": "read_only_no_path_modification",
        "plans": {
            "shelfAware": {
                "source_run_dir": str(shelf_dir),
                "diagnostic_output_dir": str(shelf_output),
            },
            "ShelfAware+TurnCost": {
                "source_run_dir": str(turn_dir),
                "diagnostic_output_dir": str(turn_output),
            },
        },
        "metric_comparison": {},
    }
    for key in COMPARE_KEYS:
        shelf_value = shelf_summary.get(key)
        turn_value = turn_summary.get(key)
        if isinstance(shelf_value, (int, float)) and isinstance(turn_value, (int, float)):
            delta = float(turn_value) - float(shelf_value)
        else:
            delta = None
        comparison["metric_comparison"][key] = {
            "shelfAware": shelf_value,
            "ShelfAware+TurnCost": turn_value,
            "turn_cost_minus_shelfAware": delta,
        }

    compare_dir = turn_output.parent.parent / f"{args.case_name}_两方案几何覆盖对比"
    compare_dir.mkdir(parents=True, exist_ok=True)
    output_path = compare_dir / "comparison_summary.json"
    output_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
