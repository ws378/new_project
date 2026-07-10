"""运行单个 MapTools area 的 pure official 与 guided A/B，并按阈值选择结果。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PACKAGE_ROOT.parents[1]
DEFAULT_PROJECT_DIR = REPO_ROOT / "examples" / "maptools_projects" / "beiguoshangcheng_floor_3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, default=DEFAULT_PROJECT_DIR, help="MapTools project 目录。")
    parser.add_argument("--area-id", type=int, default=3, help="area id。")
    parser.add_argument("--output-root", type=Path, default=PACKAGE_ROOT / "output", help="输出根目录。")
    parser.add_argument("--stop-after", default="coverage_plot", help="传给 run_maptools_official_cases.py。")
    parser.add_argument("--fractional-solver", default="highs", choices=("gurobi", "highs"))
    parser.add_argument("--penalty-strength", type=float, default=160.0)
    parser.add_argument("--graph-length-limit-factor", type=float, default=2.0)
    parser.add_argument("--tool-radius-scale", type=float, default=1.0)
    parser.add_argument("--guidance-weight-frac", type=float, default=0.25)
    parser.add_argument("--guidance-weight-abs", type=float, default=0.0)
    parser.add_argument("--guidance-min-confidence", type=float, default=0.08)
    parser.add_argument(
        "--max-coverage-drop",
        type=float,
        default=0.003,
        help="guided 相对 pure official 可接受的最大覆盖率下降；超过则选择 pure official。",
    )
    parser.add_argument(
        "--require-turn-nonincrease",
        action="store_true",
        help="启用后 guided 只有在总转角不增加时才可能被选择。",
    )
    return parser.parse_args()


def _load_summary(run_dir: Path | None) -> dict[str, Any]:
    if run_dir is None:
        return {}
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        return {}
    return json.loads(summary_path.read_text(encoding="utf-8"))


def _metrics(root_summary: dict[str, Any]) -> dict[str, float]:
    aggregate = root_summary.get("aggregate_metrics", {})
    cases = root_summary.get("cases", [])
    turn_total = 0.0
    length_total = 0.0
    for case in cases:
        metrics = case.get("metrics", {})
        turn_total += float(metrics.get("tour_turn_angle_deg", 0.0) or 0.0)
        length_total += float(metrics.get("tour_length_m", 0.0) or 0.0)
    return {
        "coverage": float(aggregate.get("area_weighted_feasible_coverage_ratio", 0.0) or 0.0),
        "turn_deg": turn_total,
        "length_m": length_total,
        "success_count": float(root_summary.get("success_count", 0) or 0),
        "case_count": float(root_summary.get("case_count", 0) or 0),
    }


def select_ab_winner(
    *,
    official_metrics: dict[str, float],
    guided_metrics: dict[str, float],
    max_coverage_drop: float,
    require_turn_nonincrease: bool,
) -> dict[str, Any]:
    official_success = official_metrics["case_count"] > 0 and official_metrics["success_count"] == official_metrics["case_count"]
    guided_success = guided_metrics["case_count"] > 0 and guided_metrics["success_count"] == guided_metrics["case_count"]
    if not official_success and guided_success:
        return {"selected": "guided", "reason": "official_failed_guided_succeeded"}
    if official_success and not guided_success:
        return {"selected": "official", "reason": "guided_failed"}
    if not official_success and not guided_success:
        return {"selected": "none", "reason": "both_failed"}
    coverage_drop = official_metrics["coverage"] - guided_metrics["coverage"]
    turn_delta = guided_metrics["turn_deg"] - official_metrics["turn_deg"]
    if coverage_drop > max_coverage_drop:
        return {
            "selected": "official",
            "reason": "guided_coverage_drop_exceeds_threshold",
            "coverage_drop": float(coverage_drop),
            "max_coverage_drop": float(max_coverage_drop),
        }
    if require_turn_nonincrease and turn_delta > 0.0:
        return {
            "selected": "official",
            "reason": "guided_turn_increased",
            "turn_delta_deg": float(turn_delta),
        }
    return {
        "selected": "guided",
        "reason": "guided_within_fallback_thresholds",
        "coverage_drop": float(coverage_drop),
        "turn_delta_deg": float(turn_delta),
    }


def _run_child(args: argparse.Namespace, run_dir: Path, *, guidance_mode: str) -> tuple[int, Path | None, str]:
    script = PACKAGE_ROOT / "scripts" / "experiments" / "run_maptools_official_cases.py"
    command = [
        sys.executable,
        str(script),
        "--project-dir",
        str(args.project_dir),
        "--area-id",
        str(args.area_id),
        "--output-root",
        str(run_dir / guidance_mode),
        "--stop-after",
        str(args.stop_after),
        "--fractional-solver",
        str(args.fractional_solver),
        "--penalty-strength",
        str(args.penalty_strength),
        "--graph-length-limit-factor",
        str(args.graph_length_limit_factor),
        "--tool-radius-scale",
        str(args.tool_radius_scale),
        "--split-disconnected-components",
        "--guidance-mode",
        guidance_mode,
        "--guidance-weight-frac",
        str(args.guidance_weight_frac),
        "--guidance-weight-abs",
        str(args.guidance_weight_abs),
        "--guidance-min-confidence",
        str(args.guidance_min_confidence),
    ]
    completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    child_run_dir = Path(lines[-1]) if lines else None
    return int(completed.returncode), child_run_dir, completed.stderr


def _copy_selected_coverage_images(
    *,
    run_dir: Path,
    selected: str,
    official_run_dir: Path | None,
    guided_run_dir: Path | None,
) -> list[dict[str, str]]:
    source_run_dir = guided_run_dir if selected == "guided" else official_run_dir
    if selected not in {"official", "guided"} or source_run_dir is None:
        return []
    root_summary = _load_summary(source_run_dir)
    target_dir = run_dir / "被选中最终coverage"
    target_dir.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, str]] = []
    prefix = "guided_tour_coverage" if selected == "guided" else "official_tour_coverage"
    for case in root_summary.get("cases", []):
        if case.get("status") != "success":
            continue
        case_id = str(case.get("case_id", ""))
        source = source_run_dir / case_id / "08_official_tour_coverage.png"
        if not source.is_file():
            continue
        target = target_dir / f"{prefix}_{case_id}.png"
        shutil.copy2(source, target)
        copied.append(
            {
                "selected": selected,
                "case_id": case_id,
                "source": str(source),
                "target": str(target),
            }
        )
    (target_dir / "manifest.json").write_text(json.dumps(copied, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return copied


def main() -> None:
    args = parse_args()
    run_dir = Path(args.output_root).expanduser().resolve() / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    run_dir.mkdir(parents=True, exist_ok=True)
    official_returncode, official_run_dir, official_stderr = _run_child(args, run_dir, guidance_mode="none")
    guided_returncode, guided_run_dir, guided_stderr = _run_child(args, run_dir, guidance_mode="shelf_local_direction")
    official_summary = _load_summary(official_run_dir)
    guided_summary = _load_summary(guided_run_dir)
    official_metrics = _metrics(official_summary)
    guided_metrics = _metrics(guided_summary)
    decision = select_ab_winner(
        official_metrics=official_metrics,
        guided_metrics=guided_metrics,
        max_coverage_drop=float(args.max_coverage_drop),
        require_turn_nonincrease=bool(args.require_turn_nonincrease),
    )
    selected_images = _copy_selected_coverage_images(
        run_dir=run_dir,
        selected=str(decision["selected"]),
        official_run_dir=official_run_dir,
        guided_run_dir=guided_run_dir,
    )
    payload = {
        "runner": "run_maptools_guidance_ab_case",
        "case_group": "maptools_official_vs_guided_ab",
        "maptools_project": Path(args.project_dir).name,
        "area_id": int(args.area_id),
        "stop_after": str(args.stop_after),
        "fractional_solver_backend": str(args.fractional_solver),
        "parameters": {
            "penalty_strength": float(args.penalty_strength),
            "graph_length_limit_factor": float(args.graph_length_limit_factor),
            "tool_radius_scale": float(args.tool_radius_scale),
            "guidance_weight_frac": float(args.guidance_weight_frac),
            "guidance_weight_abs": float(args.guidance_weight_abs),
            "guidance_min_confidence": float(args.guidance_min_confidence),
            "max_coverage_drop": float(args.max_coverage_drop),
            "require_turn_nonincrease": bool(args.require_turn_nonincrease),
        },
        "official": {
            "returncode": int(official_returncode),
            "run_dir": str(official_run_dir) if official_run_dir else "",
            "metrics": official_metrics,
            "stderr": official_stderr,
        },
        "guided": {
            "returncode": int(guided_returncode),
            "run_dir": str(guided_run_dir) if guided_run_dir else "",
            "metrics": guided_metrics,
            "stderr": guided_stderr,
        },
        "decision": decision,
        "selected_coverage_image_dir": str(run_dir / "被选中最终coverage"),
        "selected_coverage_images": selected_images,
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)
    if decision["selected"] == "none":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
