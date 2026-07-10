"""批量运行固定 MapTools 官方流程回归用例。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PACKAGE_ROOT.parents[1]


@dataclass(frozen=True)
class MapToolsOfficialRegressionCase:
    project_name: str
    area_id: int
    penalty_strength: float = 40.0
    expected_status: str = "success"
    min_coverage_ratio: float | None = None
    note: str = ""


DEFAULT_CASES = (
    MapToolsOfficialRegressionCase(
        "fourfloor_20250923_8",
        2,
        160.0,
        "success",
        0.85,
        "覆盖导向研究参数；默认 penalty=40 会在 connected_tour 因 0 cycle 失败",
    ),
    MapToolsOfficialRegressionCase("beiguoshangcheng_floor_3", 3, 160.0, "success", 0.85),
    MapToolsOfficialRegressionCase("beiguo_lanshan_1770397756", 2, 160.0, "success", 0.85),
    MapToolsOfficialRegressionCase(
        "beiguo_lanshan_1770397756",
        1,
        40.0,
        "failure",
        None,
        "既有预处理输出为多连通 polygon，当前适配按设计失败",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PACKAGE_ROOT / "output", help="输出根目录。")
    parser.add_argument("--stop-after", default="coverage_plot", help="传给 run_maptools_official_cases.py 的停止阶段。")
    parser.add_argument("--fractional-solver", default="highs", choices=("gurobi", "highs"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = Path(args.output_root).expanduser().resolve() / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    run_dir.mkdir(parents=True, exist_ok=True)
    case_script = PACKAGE_ROOT / "scripts" / "experiments" / "run_maptools_official_cases.py"
    records: list[dict[str, object]] = []
    for item in DEFAULT_CASES:
        project_dir = REPO_ROOT / "examples" / "maptools_projects" / item.project_name
        command = [
            sys.executable,
            str(case_script),
            "--project-dir",
            str(project_dir),
            "--area-id",
            str(item.area_id),
            "--stop-after",
            str(args.stop_after),
            "--fractional-solver",
            str(args.fractional_solver),
            "--penalty-strength",
            str(item.penalty_strength),
            "--output-root",
            str(run_dir / "cases"),
        ]
        completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
        output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
        case_run_dir = Path(output_lines[-1]) if output_lines else None
        root_summary_path = case_run_dir / "summary.json" if case_run_dir else None
        root_summary = {}
        if root_summary_path and root_summary_path.is_file():
            root_summary = json.loads(root_summary_path.read_text(encoding="utf-8"))
        actual_success = int(root_summary.get("success_count", 0)) == int(root_summary.get("case_count", 1))
        actual_status = "success" if actual_success else "failure"
        coverage_ratio = None
        if root_summary.get("cases"):
            metrics = root_summary["cases"][0].get("metrics", {})
            coverage_ratio = metrics.get("tour_feasible_area_coverage_ratio")
        coverage_ok = (
            True
            if item.min_coverage_ratio is None or actual_status != "success"
            else coverage_ratio is not None and float(coverage_ratio) >= float(item.min_coverage_ratio)
        )
        records.append(
            {
                **asdict(item),
                "command": command,
                "returncode": int(completed.returncode),
                "actual_status": actual_status,
                "coverage_ratio": coverage_ratio,
                "coverage_ok": coverage_ok,
                "expected_matched": actual_status == item.expected_status and coverage_ok,
                "case_run_dir": str(case_run_dir) if case_run_dir else "",
                "stderr": completed.stderr,
            }
        )
    success = all(bool(record["expected_matched"]) for record in records)
    payload = {
        "runner": "run_maptools_official_regression",
        "case_count": len(records),
        "expected_match_count": sum(1 for record in records if bool(record["expected_matched"])),
        "success": success,
        "cases": records,
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
