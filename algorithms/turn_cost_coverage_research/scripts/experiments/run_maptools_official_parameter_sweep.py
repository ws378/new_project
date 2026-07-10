"""扫描 MapTools 官方流程 penalty_strength 参数。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PACKAGE_ROOT.parents[1]

DEFAULT_SWEEP_CASES: tuple[tuple[str, int, tuple[float, ...]], ...] = (
    ("beiguo_lanshan_1770397756", 2, (40.0, 80.0, 160.0, 320.0, 640.0, 1200.0)),
    ("beiguoshangcheng_floor_3", 3, (40.0, 80.0, 160.0, 320.0, 640.0)),
    ("fourfloor_20250923_8", 2, (40.0, 80.0, 160.0, 320.0, 400.0, 640.0)),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PACKAGE_ROOT / "output", help="输出根目录。")
    parser.add_argument("--stop-after", default="coverage_plot", help="传给 run_maptools_official_cases.py 的停止阶段。")
    parser.add_argument("--fractional-solver", default="highs", choices=("gurobi", "highs"))
    return parser.parse_args()


def _read_case_summary(run_dir: Path | None) -> dict[str, object]:
    if run_dir is None:
        return {}
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        return {}
    root_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    cases = root_summary.get("cases", [])
    return cases[0] if cases else {}


def main() -> None:
    args = parse_args()
    run_dir = Path(args.output_root).expanduser().resolve() / (
        "run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    case_script = PACKAGE_ROOT / "scripts" / "experiments" / "run_maptools_official_cases.py"
    records: list[dict[str, object]] = []
    for project_name, area_id, penalties in DEFAULT_SWEEP_CASES:
        project_dir = REPO_ROOT / "examples" / "maptools_projects" / project_name
        for penalty_strength in penalties:
            command = [
                sys.executable,
                str(case_script),
                "--project-dir",
                str(project_dir),
                "--area-id",
                str(area_id),
                "--stop-after",
                str(args.stop_after),
                "--fractional-solver",
                str(args.fractional_solver),
                "--penalty-strength",
                str(penalty_strength),
                "--output-root",
                str(run_dir / "cases"),
            ]
            completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
            output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
            case_run_dir = Path(output_lines[-1]) if output_lines else None
            case_summary = _read_case_summary(case_run_dir)
            metrics = case_summary.get("metrics", {}) if isinstance(case_summary, dict) else {}
            records.append(
                {
                    "project_name": project_name,
                    "area_id": area_id,
                    "penalty_strength": penalty_strength,
                    "returncode": int(completed.returncode),
                    "status": case_summary.get("status") if isinstance(case_summary, dict) else "",
                    "failure_stage": case_summary.get("failure_stage") if isinstance(case_summary, dict) else "",
                    "failure_detail": case_summary.get("failure_detail") if isinstance(case_summary, dict) else "",
                    "coverage_ratio": metrics.get("tour_feasible_area_coverage_ratio"),
                    "tour_length_m": metrics.get("tour_length_m"),
                    "tour_waypoint_count": metrics.get("tour_waypoint_count"),
                    "cycle_count_before_connection": metrics.get("cycle_count_before_connection"),
                    "fractional_objective_value": metrics.get("fractional_objective_value"),
                    "case_run_dir": str(case_run_dir) if case_run_dir else "",
                    "stderr": completed.stderr,
                }
            )
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "runner": "run_maptools_official_parameter_sweep",
                "case_group": "maptools_official_algorithm_steps",
                "fractional_solver_backend": str(args.fractional_solver),
                "stop_after": str(args.stop_after),
                "case_count": len(records),
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(run_dir)


if __name__ == "__main__":
    main()
