from __future__ import annotations

import argparse

from algorithms.shelf_aware_ctg_research.src.project_inputs import DEFAULT_PROJECT_DIR
from algorithms.shelf_aware_ctg_research.src.study_runner import run_projects_territory_study


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run shelf-aware CTG research for every area in one or more maptools projects.")
    parser.add_argument(
        "--project-dir",
        action="append",
        default=None,
        help="Path to a maptools project directory. Repeat to process multiple projects into one run.",
    )
    parser.add_argument("--output-root", default=None, help="Output root for run artifacts. Defaults to the package output directory.")
    parser.add_argument("--no-boundary-smoothing", action="store_true", help="Disable default boundary-band majority smoothing.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = run_projects_territory_study(
        project_dirs=args.project_dir or [str(DEFAULT_PROJECT_DIR)],
        output_root=args.output_root,
        apply_boundary_smoothing=not args.no_boundary_smoothing,
    )
    print(run_dir)


if __name__ == "__main__":
    main()
