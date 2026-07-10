"""运行三个 MapTools 项目的全部区域官方流程。"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PACKAGE_ROOT.parents[1]

DEFAULT_PROJECT_NAMES = (
    "beiguo_lanshan_1770397756",
    "beiguoshangcheng_floor_3",
    "fourfloor_20250923_8",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PACKAGE_ROOT / "output", help="输出根目录。")
    parser.add_argument("--stop-after", default="coverage_plot", help="传给 run_maptools_official_cases.py 的停止阶段。")
    parser.add_argument("--fractional-solver", default="highs", choices=("gurobi", "highs"))
    parser.add_argument("--penalty-strength", type=float, default=160.0, help="MapTools 覆盖导向研究参数。")
    parser.add_argument("--graph-length-limit-factor", type=float, default=2.0, help="官方 Delaunay graph length limit factor。")
    parser.add_argument("--tool-radius-scale", type=float, default=1.0, help="传给 MapTools 官方 case 的 tool radius scale。")
    parser.add_argument("--atomic-orientation-count", type=int, default=3, help="透传 atomic strip 方向组数；论文默认 3。")
    parser.add_argument("--atomic-orientation-repetition", type=int, default=2, help="透传 atomic strip 每组重复数；论文默认 2。")
    parser.add_argument("--project-name", action="append", choices=DEFAULT_PROJECT_NAMES, help="只运行指定项目，可重复。")
    parser.add_argument("--no-retry-profiles", action="store_true", help="关闭自动参数重试，只跑命令行给出的参数。")
    parser.add_argument(
        "--retry-min-coverage-ratio",
        type=float,
        default=0.85,
        help="自动重试提前停止阈值；component 成功且覆盖率达到该值才停止继续尝试。",
    )
    parser.add_argument(
        "--graph-backend",
        choices=("hex_delaunay", "square8_axis_guided"),
        default="hex_delaunay",
        help="透传图构建后端；默认 hex_delaunay 为纯官方图构建，square8_axis_guided 为非纯官方实验。",
    )
    parser.add_argument("--square-grid-step-scale", type=float, default=1.0, help="透传 square8 grid step scale。")
    parser.add_argument("--square-diagonal-cost-multiplier", type=float, default=1.15, help="透传 square8 对角边距离倍率。")
    parser.add_argument("--square-axis-confidence-threshold", type=float, default=0.60, help="透传 square8 方向场最低置信度。")
    parser.add_argument("--square-axis-angle-tolerance-deg", type=float, default=25.0, help="透传 square8 方向贴合阈值。")
    parser.add_argument("--square-no-component-bridge", action="store_true", help="透传关闭 square8 采样分量 LoS bridge。")
    parser.add_argument("--square-bridge-max-step-factor", type=float, default=8.0, help="透传 square8 bridge 最大步长因子。")
    parser.add_argument("--square-bridge-cost-multiplier", type=float, default=4.0, help="透传 square8 bridge 惩罚倍率。")
    parser.add_argument(
        "--allow-square8-guided-atomic",
        action="store_true",
        help="显式允许 square8 图实验叠加 guided atomic strips；这是非官方组合实验，默认禁止。",
    )
    parser.add_argument(
        "--guidance-mode",
        choices=("none", "shelf_local_direction"),
        default="none",
        help="透传给单 area runner 的方向引导模式。",
    )
    parser.add_argument("--guidance-weight-frac", type=float, default=0.25, help="透传方向引导相对权重。")
    parser.add_argument("--guidance-weight-abs", type=float, default=0.0, help="透传方向引导绝对权重。")
    parser.add_argument("--guidance-min-confidence", type=float, default=0.08, help="透传方向场最低置信度。")
    parser.add_argument(
        "--atomic-guidance-strategy",
        choices=("soft_bias", "corridor_axis"),
        default="soft_bias",
        help="透传 atomic strip 方向引导策略；corridor_axis 为非官方 04 阶段形态诊断实验。",
    )
    parser.add_argument(
        "--corridor-axis-primary-orientation-count",
        type=int,
        default=None,
        help="透传 corridor_axis 策略中主轴方向候选槽位数；默认等于 atomic orientation count。",
    )
    return parser.parse_args()


def _validate_experiment_scope(args: argparse.Namespace) -> None:
    if args.graph_backend == "square8_axis_guided" and args.guidance_mode != "none" and not bool(args.allow_square8_guided_atomic):
        raise SystemExit("square8_axis_guided 批量实验默认只允许 guidance_mode=none；如需非官方 guided atomic 组合实验，必须显式传 --allow-square8-guided-atomic")


def _load_area_ids(project_dir: Path) -> list[int]:
    payload = json.loads((project_dir / "areas.json").read_text(encoding="utf-8"))
    return sorted(int(item["area_id"]) for item in payload.get("areas", []))


def _guidance_config_from_args(args: argparse.Namespace) -> dict[str, object]:
    return {
        "enabled": args.guidance_mode != "none",
        "mode": str(args.guidance_mode),
        "status": "enabled_soft_atomic_strip_orientation_bias" if args.guidance_mode != "none" else "disabled_by_cli",
        "weight_frac": float(args.guidance_weight_frac),
        "weight_abs": float(args.guidance_weight_abs),
        "min_confidence": float(args.guidance_min_confidence),
        "atomic_guidance_strategy": str(args.atomic_guidance_strategy),
        "corridor_axis_primary_orientation_count": args.corridor_axis_primary_orientation_count,
        "algorithm_impact": (
            "non_official_corridor_axis_atomic_strip_candidate_replacement"
            if args.guidance_mode != "none" and args.atomic_guidance_strategy == "corridor_axis"
            else "soft_atomic_strip_orientation_bias"
            if args.guidance_mode != "none"
            else "none"
        ),
    }


def _case_group_for_guidance(args: argparse.Namespace) -> str:
    if args.graph_backend == "square8_axis_guided":
        if args.guidance_mode != "none":
            if args.atomic_guidance_strategy == "corridor_axis":
                return "maptools_square8_axis_guided_graph_corridor_axis_atomic_flow"
            return "maptools_square8_axis_guided_graph_guided_atomic_flow"
        return "maptools_square8_axis_guided_official_flow"
    if args.guidance_mode == "none":
        return "maptools_official_algorithm_steps"
    return "maptools_official_algorithm_steps_guided"


def _final_image_dirname(*, guidance_mode: str, graph_backend: str) -> str:
    if graph_backend == "square8_axis_guided":
        if guidance_mode != "none":
            return "全部最终square8_axis_guided_atomic_tour_coverage"
        return "全部最终square8_axis_guided_tour_coverage"
    return "全部最终official_tour_coverage" if guidance_mode == "none" else "全部最终guided_tour_coverage"


def _final_image_prefix(*, guidance_mode: str, graph_backend: str) -> str:
    if graph_backend == "square8_axis_guided":
        if guidance_mode != "none":
            return "square8_axis_guided_atomic_tour_coverage"
        return "square8_axis_guided_tour_coverage"
    return "official_tour_coverage" if guidance_mode == "none" else "guided_tour_coverage"


def _copy_final_coverage_images(
    run_dir: Path,
    area_records: list[dict[str, object]],
    *,
    guidance_mode: str,
    graph_backend: str,
) -> list[dict[str, object]]:
    dirname = _final_image_dirname(guidance_mode=guidance_mode, graph_backend=graph_backend)
    image_dir = run_dir / dirname
    image_dir.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, object]] = []
    for record in area_records:
        area_run_dir = Path(str(record.get("area_run_dir", "")))
        if not area_run_dir.is_dir():
            continue
        root_summary_path = area_run_dir / "summary.json"
        if not root_summary_path.is_file():
            continue
        root_summary = json.loads(root_summary_path.read_text(encoding="utf-8"))
        for case in root_summary.get("cases", []):
            if case.get("status") != "success":
                continue
            case_dir = area_run_dir / str(case.get("case_id", ""))
            source = case_dir / "08_official_tour_coverage.png"
            if not source.is_file():
                continue
            adapter_metadata = case.get("input", {}).get("adapter_metadata", {})
            project_name = str(record.get("project_name"))
            area_id = int(record.get("area_id"))
            component_count = int(adapter_metadata.get("component_count", 1) or 1)
            component_index = int(adapter_metadata.get("component_index", 0) or 0)
            suffix = "" if component_count == 1 else f"_component{component_index}"
            prefix = _final_image_prefix(guidance_mode=guidance_mode, graph_backend=graph_backend)
            target_name = f"{prefix}_{project_name}_area{area_id}{suffix}.png"
            target = image_dir / target_name
            shutil.copy2(source, target)
            copied.append(
                {
                    "project_name": project_name,
                    "area_id": area_id,
                    "component_index": component_index,
                    "component_count": component_count,
                    "source": str(source),
                    "target": str(target),
                }
            )
    (image_dir / "manifest.json").write_text(json.dumps(copied, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (image_dir / "manifest.csv").open("w", encoding="utf-8", newline="") as file_obj:
        fieldnames = ("project_name", "area_id", "component_index", "component_count", "source", "target")
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for item in copied:
            writer.writerow({field: item.get(field, "") for field in fieldnames})
    return copied


def _area_profiles(args: argparse.Namespace) -> list[dict[str, float]]:
    first = {
        "penalty_strength": float(args.penalty_strength),
        "graph_length_limit_factor": float(args.graph_length_limit_factor),
        "tool_radius_scale": float(args.tool_radius_scale),
    }
    if bool(args.no_retry_profiles):
        return [first]
    if args.graph_backend == "square8_axis_guided":
        candidates = [
            first,
            {"penalty_strength": 300.0, "graph_length_limit_factor": 2.0, "tool_radius_scale": float(args.tool_radius_scale)},
            {"penalty_strength": 400.0, "graph_length_limit_factor": 2.0, "tool_radius_scale": float(args.tool_radius_scale)},
            {"penalty_strength": 600.0, "graph_length_limit_factor": 2.0, "tool_radius_scale": float(args.tool_radius_scale)},
            {"penalty_strength": 800.0, "graph_length_limit_factor": 2.0, "tool_radius_scale": float(args.tool_radius_scale)},
        ]
        return _dedupe_area_profiles(candidates)
    candidates = [
        first,
        {"penalty_strength": float(args.penalty_strength), "graph_length_limit_factor": 2.0, "tool_radius_scale": 0.75},
        {"penalty_strength": float(args.penalty_strength), "graph_length_limit_factor": 2.0, "tool_radius_scale": 0.5},
        {"penalty_strength": float(args.penalty_strength), "graph_length_limit_factor": 2.0, "tool_radius_scale": 0.35},
        {"penalty_strength": 400.0, "graph_length_limit_factor": 2.0, "tool_radius_scale": 1.0},
    ]
    return _dedupe_area_profiles(candidates)


def _dedupe_area_profiles(candidates: list[dict[str, float]]) -> list[dict[str, float]]:
    deduped: list[dict[str, float]] = []
    seen: set[tuple[float, float, float]] = set()
    for item in candidates:
        key = (
            float(item["penalty_strength"]),
            float(item["graph_length_limit_factor"]),
            float(item["tool_radius_scale"]),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _has_met_retry_stop_condition(area_summary: dict[str, Any], args: argparse.Namespace) -> bool:
    case_count = int(area_summary.get("case_count") or 0)
    success_count = int(area_summary.get("success_count") or 0)
    if case_count <= 0 or case_count != success_count:
        return False
    aggregate_metrics = area_summary.get("aggregate_metrics", {})
    coverage_ratio = float(aggregate_metrics.get("area_weighted_feasible_coverage_ratio") or 0.0)
    return coverage_ratio >= float(args.retry_min_coverage_ratio)


def _read_area_summary(area_run_dir: Path | None) -> dict[str, Any]:
    if area_run_dir is None:
        return {}
    summary_path = area_run_dir / "summary.json"
    if not summary_path.is_file():
        return {}
    return json.loads(summary_path.read_text(encoding="utf-8"))


def _score_area_summary(area_summary: dict[str, Any]) -> tuple[float, float, float, float]:
    area_totals = _component_area_totals(area_summary)
    success_area_ratio = area_totals["success_area_m2"] / area_totals["total_area_m2"] if area_totals["total_area_m2"] > 0.0 else 0.0
    case_count = int(area_summary.get("case_count") or len(area_summary.get("cases", [])) or 0)
    success_count = int(area_summary.get("success_count") or 0)
    success_ratio = success_count / case_count if case_count > 0 else 0.0
    aggregate_metrics = area_summary.get("aggregate_metrics", {})
    coverage_ratio = float(aggregate_metrics.get("area_weighted_feasible_coverage_ratio") or 0.0)
    return (success_area_ratio, success_ratio, coverage_ratio, float(success_count))


def _component_area_totals(area_summary: dict[str, Any]) -> dict[str, float]:
    cases = area_summary.get("cases", [])
    total_area = 0.0
    success_area = 0.0
    for case in cases:
        metadata = case.get("input", {}).get("adapter_metadata", {})
        area = float(metadata.get("polygon_area_m2", 0.0) or 0.0)
        total_area += area
        if case.get("status") == "success":
            success_area += area
    return {
        "total_area_m2": total_area,
        "success_area_m2": success_area,
        "failed_area_m2": max(0.0, total_area - success_area),
        "success_area_ratio": success_area / total_area if total_area > 0.0 else 0.0,
    }


def _run_one_area(
    *,
    args: argparse.Namespace,
    case_script: Path,
    run_dir: Path,
    project_name: str,
    project_dir: Path,
    area_id: int,
) -> dict[str, object]:
    attempts: list[dict[str, object]] = []
    best_record: dict[str, object] | None = None
    best_score = (-1.0, -1.0, -1.0, -1.0)
    for profile_index, profile in enumerate(_area_profiles(args)):
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
            str(profile["penalty_strength"]),
            "--graph-length-limit-factor",
            str(profile["graph_length_limit_factor"]),
            "--tool-radius-scale",
            str(profile["tool_radius_scale"]),
            "--atomic-orientation-count",
            str(args.atomic_orientation_count),
            "--atomic-orientation-repetition",
            str(args.atomic_orientation_repetition),
            "--split-disconnected-components",
            "--output-root",
            str(run_dir / "areas"),
            "--graph-backend",
            str(args.graph_backend),
            "--square-grid-step-scale",
            str(args.square_grid_step_scale),
            "--square-diagonal-cost-multiplier",
            str(args.square_diagonal_cost_multiplier),
            "--square-axis-confidence-threshold",
            str(args.square_axis_confidence_threshold),
            "--square-axis-angle-tolerance-deg",
            str(args.square_axis_angle_tolerance_deg),
            "--square-bridge-max-step-factor",
            str(args.square_bridge_max_step_factor),
            "--square-bridge-cost-multiplier",
            str(args.square_bridge_cost_multiplier),
            "--guidance-mode",
            str(args.guidance_mode),
            "--guidance-weight-frac",
            str(args.guidance_weight_frac),
            "--guidance-weight-abs",
            str(args.guidance_weight_abs),
            "--guidance-min-confidence",
            str(args.guidance_min_confidence),
            "--atomic-guidance-strategy",
            str(args.atomic_guidance_strategy),
        ]
        if args.corridor_axis_primary_orientation_count is not None:
            command.extend(
                [
                    "--corridor-axis-primary-orientation-count",
                    str(args.corridor_axis_primary_orientation_count),
                ]
            )
        if bool(args.square_no_component_bridge):
            command.append("--square-no-component-bridge")
        if bool(args.allow_square8_guided_atomic):
            command.append("--allow-square8-guided-atomic")
        completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
        output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
        area_run_dir = Path(output_lines[-1]) if output_lines else None
        area_summary = _read_area_summary(area_run_dir)
        aggregate_metrics = area_summary.get("aggregate_metrics", {}) if isinstance(area_summary, dict) else {}
        component_area_totals = _component_area_totals(area_summary)
        score = _score_area_summary(area_summary)
        attempt = {
            "profile_index": int(profile_index),
            "profile": dict(profile),
            "returncode": int(completed.returncode),
            "area_run_dir": str(area_run_dir) if area_run_dir else "",
            "case_count": area_summary.get("case_count"),
            "success_count": area_summary.get("success_count"),
            "component_count": area_summary.get("component_count"),
            "aggregate_metrics": aggregate_metrics,
            "component_area_totals": component_area_totals,
            "score": list(score),
            "stderr": completed.stderr,
        }
        attempts.append(attempt)
        if score > best_score:
            best_score = score
            best_record = attempt
        if _has_met_retry_stop_condition(area_summary, args):
            break
    assert best_record is not None
    return {
        "project_name": project_name,
        "area_id": area_id,
        "selected_attempt_index": int(best_record["profile_index"]),
        "selected_profile": dict(best_record["profile"]),
        "returncode": int(best_record["returncode"]),
        "area_run_dir": str(best_record["area_run_dir"]),
        "case_count": best_record.get("case_count"),
        "success_count": best_record.get("success_count"),
        "component_count": best_record.get("component_count"),
        "aggregate_metrics": best_record.get("aggregate_metrics"),
        "component_area_totals": best_record.get("component_area_totals"),
        "score": best_record.get("score"),
        "attempts": attempts,
    }


def main() -> None:
    args = parse_args()
    _validate_experiment_scope(args)
    run_dir = Path(args.output_root).expanduser().resolve() / (
        "run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    project_names = tuple(args.project_name) if args.project_name else DEFAULT_PROJECT_NAMES
    case_script = PACKAGE_ROOT / "scripts" / "experiments" / "run_maptools_official_cases.py"
    area_records: list[dict[str, object]] = []
    for project_name in project_names:
        project_dir = REPO_ROOT / "examples" / "maptools_projects" / project_name
        for area_id in _load_area_ids(project_dir):
            area_records.append(
                _run_one_area(
                    args=args,
                    case_script=case_script,
                    run_dir=run_dir,
                    project_name=project_name,
                    project_dir=project_dir,
                    area_id=area_id,
                )
            )
    copied_images = _copy_final_coverage_images(
        run_dir,
        area_records,
        guidance_mode=str(args.guidance_mode),
        graph_backend=str(args.graph_backend),
    )
    payload = {
        "runner": "run_maptools_official_all_areas",
        "case_group": _case_group_for_guidance(args),
        "project_names": list(project_names),
        "area_count": int(len(area_records)),
        "all_component_success_area_count": int(
            sum(
                1
                for record in area_records
                if int(record.get("case_count") or 0) == int(record.get("success_count") or -1)
            )
        ),
        "area_with_final_coverage_count": int(
            sum(1 for record in area_records if int(record.get("success_count") or 0) > 0)
        ),
        "fractional_solver_backend": str(args.fractional_solver),
        "penalty_strength": float(args.penalty_strength),
        "graph_length_limit_factor": float(args.graph_length_limit_factor),
        "tool_radius_scale": float(args.tool_radius_scale),
        "atomic_orientation_count": int(args.atomic_orientation_count),
        "atomic_orientation_repetition": int(args.atomic_orientation_repetition),
        "retry_min_coverage_ratio": float(args.retry_min_coverage_ratio),
        "graph_backend": {
            "backend": str(args.graph_backend),
            "square_grid_step_scale": float(args.square_grid_step_scale),
            "square_diagonal_cost_multiplier": float(args.square_diagonal_cost_multiplier),
            "square_axis_confidence_threshold": float(args.square_axis_confidence_threshold),
            "square_axis_angle_tolerance_deg": float(args.square_axis_angle_tolerance_deg),
            "square_component_bridge_enabled": not bool(args.square_no_component_bridge),
            "square_bridge_max_step_factor": float(args.square_bridge_max_step_factor),
            "square_bridge_cost_multiplier": float(args.square_bridge_cost_multiplier),
            "allow_square8_guided_atomic": bool(args.allow_square8_guided_atomic),
            "atomic_guidance_strategy": str(args.atomic_guidance_strategy),
            "corridor_axis_primary_orientation_count": args.corridor_axis_primary_orientation_count,
            "algorithm_impact": (
                "non_official_square8_axis_guided_graph_backend_plus_corridor_axis_atomic_strip_replacement"
                if args.graph_backend == "square8_axis_guided"
                and args.guidance_mode != "none"
                and bool(args.allow_square8_guided_atomic)
                and args.atomic_guidance_strategy == "corridor_axis"
                else "non_official_square8_axis_guided_graph_backend_plus_guided_atomic_strip_bias"
                if args.graph_backend == "square8_axis_guided"
                and args.guidance_mode != "none"
                and bool(args.allow_square8_guided_atomic)
                else "non_official_square8_axis_guided_graph_backend"
                if args.graph_backend == "square8_axis_guided"
                else "none"
            ),
        },
        "guidance": _guidance_config_from_args(args),
        "split_disconnected_components": True,
        "final_coverage_image_dir": str(
            run_dir
            / _final_image_dirname(guidance_mode=str(args.guidance_mode), graph_backend=str(args.graph_backend))
        ),
        "final_coverage_image_count": int(len(copied_images)),
        "final_coverage_images": copied_images,
        "areas": area_records,
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)
    if payload["area_with_final_coverage_count"] != payload["area_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
