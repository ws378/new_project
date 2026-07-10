from __future__ import annotations

import argparse

from algorithms.territory_seed_research.src.fourfloor_inputs import DEFAULT_PROJECT_DIR
from algorithms.territory_seed_research.src.study_runner import run_fourfloor_territory_study


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the fourfloor CTG territory seed research extractor.")
    parser.add_argument("--project-dir", default=str(DEFAULT_PROJECT_DIR), help="Path to the maptools fourfloor project directory.")
    parser.add_argument("--area-id", type=int, default=None, help="Area label id to process. Defaults to the first area.")
    parser.add_argument("--output-root", default=None, help="Output root for run artifacts. Defaults to the package output directory.")
    parser.add_argument("--no-boundary-smoothing", action="store_true", help="Disable default boundary-band majority smoothing.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = run_fourfloor_territory_study(
        project_dir=args.project_dir,
        area_id=args.area_id,
        output_root=args.output_root,
        apply_boundary_smoothing=not args.no_boundary_smoothing,
    )
    print(run_dir)


if __name__ == "__main__":
    main()
