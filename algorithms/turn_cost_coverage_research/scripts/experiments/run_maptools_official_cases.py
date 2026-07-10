"""使用既有 MapTools 预处理结果运行官方 pcpptc 前缀流程。"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PACKAGE_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.turn_cost_coverage_research.scripts.experiments.run_paper_official_algorithm_steps import (
    DEFAULT_OUTPUT_ROOT,
    OfficialExampleParameters,
    run_official_steps_case,
)
from algorithms.turn_cost_coverage_research.src.guidance import build_shelf_direction_guidance, guidance_disabled_config
from algorithms.turn_cost_coverage_research.src.adapters.official_maptools_adapter import (
    MapToolsOfficialAdapterConfig,
    build_maptools_official_inputs,
)
from algorithms.turn_cost_coverage_research.src.visualization.artifact_writer import (
    ROOT_SUMMARY_CONTRACT_VERSION,
    RunSummary,
    default_dependencies,
    inspect_artifact,
    write_json,
    write_root_summary,
    write_summary,
)


DEFAULT_PROJECT_DIR = REPO_ROOT / "examples" / "maptools_projects" / "fourfloor_20250923_8"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, default=DEFAULT_PROJECT_DIR, help="MapTools project 目录。")
    parser.add_argument("--area-id", type=int, default=2, help="area id。")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="输出根目录。")
    parser.add_argument(
        "--stop-after",
        default="graph",
        choices=(
            "instance",
            "grid",
            "graph",
            "coverage",
            "fractional",
            "atomic_strips",
            "matching",
            "cycle_cover",
            "connected_tour",
            "coverage_plot",
        ),
        help="官方流程停止阶段。MapTools 初始适配默认只到 graph。",
    )
    parser.add_argument(
        "--fractional-solver",
        choices=("gurobi", "highs"),
        default="highs",
        help="fractional LP 求解器；默认使用 HiGHS 非官方替代。",
    )
    parser.add_argument("--seed", type=int, default=7, help="官方流程随机种子。")
    parser.add_argument("--penalty-strength", type=float, default=40.0, help="official valuable area penalty。")
    parser.add_argument(
        "--turn-cost",
        type=float,
        default=10.0,
        help="仅写入 PolygonInstance.turn_cost 元数据；当前求解转角权重使用 --turn-factor。",
    )
    parser.add_argument("--turn-factor", type=float, default=50.0, help="官方 PointBasedInstance turn_factor。")
    parser.add_argument("--distance-factor", type=float, default=1.0, help="官方 distance_factor。")
    parser.add_argument("--graph-length-limit-factor", type=float, default=2.0, help="官方 Delaunay graph length limit factor。")
    parser.add_argument("--atomic-orientation-count", type=int, default=3, help="官方 EquiangularRepetitionAtomicStrips 方向组数；论文默认 3。")
    parser.add_argument("--atomic-orientation-repetition", type=int, default=2, help="官方 EquiangularRepetitionAtomicStrips 每组重复数；论文默认 2。")
    parser.add_argument(
        "--tool-radius-scale",
        type=float,
        default=1.0,
        help="MapTools coverage_width/2 到官方 tool_radius 的比例；小于 1 会增密官方 grid，属于参数实验。",
    )
    parser.add_argument("--no-boundary-smoothing", action="store_true", help="关闭既有 geometry_preparation 边界平滑。")
    parser.add_argument(
        "--split-disconnected-components",
        action="store_true",
        help="将既有 free_mask 的多连通 component 拆成多个官方单连通子 case；不丢弃 component，不补虚拟连接。",
    )
    parser.add_argument(
        "--component-index",
        type=int,
        default=None,
        help="仅运行拆分后的指定 component index；默认运行全部 component。",
    )
    parser.add_argument(
        "--graph-backend",
        choices=("hex_delaunay", "square8_axis_guided"),
        default="hex_delaunay",
        help="图构建后端；默认 hex_delaunay 为现有 pure official 适配，square8_axis_guided 为工程变种实验。",
    )
    parser.add_argument("--square-grid-step-scale", type=float, default=1.0, help="square8 grid_step = 2 * tool_radius * scale。")
    parser.add_argument("--square-diagonal-cost-multiplier", type=float, default=1.15, help="square8 对角边距离倍率。")
    parser.add_argument("--square-axis-confidence-threshold", type=float, default=0.60, help="square8 使用方向场的最低置信度。")
    parser.add_argument("--square-axis-angle-tolerance-deg", type=float, default=25.0, help="square8 判断边方向贴合主轴的角度阈值。")
    parser.add_argument("--square-no-component-bridge", action="store_true", help="关闭 square8 采样分量 LoS bridge；默认开启并在 summary 标注。")
    parser.add_argument("--square-bridge-max-step-factor", type=float, default=8.0, help="square8 连接采样分量的最大 LoS bridge 长度，单位为 grid step。")
    parser.add_argument("--square-bridge-cost-multiplier", type=float, default=4.0, help="square8 component bridge 边惩罚倍率。")
    parser.add_argument(
        "--allow-square8-guided-atomic",
        action="store_true",
        help="显式允许 square8 图实验叠加 guided atomic strips；这是非官方组合实验，默认禁止。",
    )
    parser.add_argument(
        "--guidance-mode",
        choices=("none", "shelf_local_direction"),
        default="none",
        help="方向引导模式。当前只先接入观测层，不改变官方 atomic strips。",
    )
    parser.add_argument("--guidance-weight-frac", type=float, default=0.25, help="预留软引导相对权重；观测层记录但不参与路径。")
    parser.add_argument("--guidance-weight-abs", type=float, default=0.0, help="预留软引导绝对权重；观测层记录但不参与路径。")
    parser.add_argument("--guidance-min-confidence", type=float, default=0.08, help="顶点方向命中最低置信度。")
    parser.add_argument(
        "--atomic-guidance-strategy",
        choices=("soft_bias", "corridor_axis"),
        default="soft_bias",
        help="guidance 启用后的 atomic strip 实验策略；corridor_axis 为非官方 04 阶段形态诊断实验。",
    )
    parser.add_argument(
        "--corridor-axis-primary-orientation-count",
        type=int,
        default=None,
        help="corridor_axis 策略中高置信走廊点使用主轴方向的候选槽位数；默认等于 atomic orientation count。",
    )
    return parser.parse_args()


def _validate_experiment_scope(args: argparse.Namespace) -> None:
    if args.graph_backend != "square8_axis_guided":
        return
    if args.guidance_mode != "none" and not bool(args.allow_square8_guided_atomic):
        raise SystemExit("square8_axis_guided 默认只允许 guidance_mode=none；如需非官方 guided atomic 组合实验，必须显式传 --allow-square8-guided-atomic")


def _guidance_config_from_args(args: argparse.Namespace) -> dict[str, object]:
    if args.guidance_mode == "none":
        return {
            **guidance_disabled_config("none", "disabled_by_cli"),
            "weight_frac": float(args.guidance_weight_frac),
            "weight_abs": float(args.guidance_weight_abs),
            "min_confidence": float(args.guidance_min_confidence),
            "atomic_guidance_strategy": str(args.atomic_guidance_strategy),
            "corridor_axis_primary_orientation_count": args.corridor_axis_primary_orientation_count,
        }
    return {
        "enabled": True,
        "mode": "shelf_local_direction",
        "status": "enabled_soft_atomic_strip_orientation_bias",
        "weight_frac": float(args.guidance_weight_frac),
        "weight_abs": float(args.guidance_weight_abs),
        "min_confidence": float(args.guidance_min_confidence),
        "atomic_guidance_strategy": str(args.atomic_guidance_strategy),
        "corridor_axis_primary_orientation_count": args.corridor_axis_primary_orientation_count,
        "source": "shelf_aware_guarded.compute_local_direction_map",
        "algorithm_impact": (
            "non_official_corridor_axis_atomic_strip_candidate_replacement"
            if args.atomic_guidance_strategy == "corridor_axis"
            else "soft_atomic_strip_orientation_bias"
        ),
        "formal_planner_migration": "仅为研究实验；迁入正式 planner 前需完成 A/B、回退阈值和参数边界评审",
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


def _graph_backend_config_from_args(args: argparse.Namespace, *, tool_radius_m: float) -> dict[str, object]:
    if args.graph_backend == "hex_delaunay":
        return {
            "backend": "hex_delaunay",
            "algorithm_impact": "none",
        }
    combines_guided_atomic = args.guidance_mode != "none" and bool(args.allow_square8_guided_atomic)
    uses_corridor_axis = combines_guided_atomic and args.atomic_guidance_strategy == "corridor_axis"
    official_difference = (
        "替换 hex+Delaunay 图构建，并显式叠加 corridor-axis atomic strip 候选替换；"
        "fractional/matching/cycle/PCST 后续流程仍复用官方代码"
        if uses_corridor_axis
        else
        "替换 hex+Delaunay 图构建，并显式叠加 guided atomic strip 候选评分；"
        "fractional/matching/cycle/PCST 后续流程仍复用官方代码"
        if combines_guided_atomic
        else "替换 hex+Delaunay 图构建；fractional/atomic/matching/cycle/PCST 后续流程仍复用官方代码"
    )
    algorithm_impact = (
        "non_official_square8_axis_guided_graph_backend_plus_corridor_axis_atomic_strip_replacement"
        if uses_corridor_axis
        else
        "non_official_square8_axis_guided_graph_backend_plus_guided_atomic_strip_bias"
        if combines_guided_atomic
        else "non_official_square8_axis_guided_graph_backend"
    )
    return {
        "backend": "square8_axis_guided",
        "grid_step_m": 2.0 * float(tool_radius_m) * float(args.square_grid_step_scale),
        "grid_step_source": "2 * tool_radius_m * square_grid_step_scale",
        "diagonal_cost_multiplier": float(args.square_diagonal_cost_multiplier),
        "axis_confidence_threshold": float(args.square_axis_confidence_threshold),
        "axis_angle_tolerance_deg": float(args.square_axis_angle_tolerance_deg),
        "diagonal_axis_suppress_confidence": float(args.square_axis_confidence_threshold),
        "bridge_disconnected_components": not bool(args.square_no_component_bridge),
        "bridge_max_step_factor": float(args.square_bridge_max_step_factor),
        "bridge_cost_multiplier": float(args.square_bridge_cost_multiplier),
        "allow_square8_guided_atomic": bool(args.allow_square8_guided_atomic),
        "algorithm_impact": algorithm_impact,
        "official_difference": official_difference,
        "formal_planner_migration": "仅为工程变种实验；需通过形态与覆盖率 A/B 后再评估迁入",
    }


def _graph_backend_cli_config_from_args(args: argparse.Namespace) -> dict[str, object]:
    combines_guided_atomic = (
        args.graph_backend == "square8_axis_guided"
        and args.guidance_mode != "none"
        and bool(args.allow_square8_guided_atomic)
    )
    uses_corridor_axis = combines_guided_atomic and args.atomic_guidance_strategy == "corridor_axis"
    return {
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
            if uses_corridor_axis
            else
            "non_official_square8_axis_guided_graph_backend_plus_guided_atomic_strip_bias"
            if combines_guided_atomic
            else "non_official_square8_axis_guided_graph_backend"
            if args.graph_backend == "square8_axis_guided"
            else "none"
        ),
    }


def main() -> None:
    args = parse_args()
    _validate_experiment_scope(args)
    guidance_config = _guidance_config_from_args(args)
    run_dir = Path(args.output_root).expanduser().resolve() / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    base_case_id = f"{Path(args.project_dir).name}_area_{int(args.area_id)}"
    case_dir = run_dir / base_case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    try:
        adapter_inputs = build_maptools_official_inputs(
            args.project_dir,
            area_id=int(args.area_id),
            output_dir=case_dir / "existing_preprocessing",
            apply_boundary_smoothing=not bool(args.no_boundary_smoothing),
            split_disconnected_components=bool(args.split_disconnected_components),
            config=MapToolsOfficialAdapterConfig(
                penalty_strength=float(args.penalty_strength),
                turn_cost=float(args.turn_cost),
                distance_cost=float(args.distance_factor),
                tool_radius_scale=float(args.tool_radius_scale),
            ),
        )
    except Exception as exc:
        summary = RunSummary(
            case_id=base_case_id,
            case_group=_case_group_for_guidance(args),
            status="failure",
            failure_stage="input_adapter",
            failure_reason=type(exc).__name__,
            failure_detail=str(exc),
            input={
                "source": str(Path(args.project_dir).expanduser().resolve()),
                "algorithm_source": "pcpptc official flow with MapTools existing geometry_preparation adapter",
                "instance_source": "maptools_existing_geometry_preparation",
                "maptools_project": Path(args.project_dir).name,
                "area_id": int(args.area_id),
                "stop_after": str(args.stop_after),
                "fractional_solver_backend": str(args.fractional_solver),
                "parameter_profile": "maptools_existing_preprocessing",
                "split_disconnected_components": bool(args.split_disconnected_components),
                "guidance": guidance_config,
                "graph_backend": _graph_backend_cli_config_from_args(args),
            },
            dependencies=default_dependencies(),
            stage_status={"input_adapter": "failure"},
            metrics={
                "adapter": "maptools_existing_preprocessing_to_official_polygon_instance",
                "adapter_scope": "只消费既有 geometry_preparation 输出；不新增预处理语义",
                "component_split_enabled": bool(args.split_disconnected_components),
            },
        )
        write_summary(case_dir, summary)
        write_root_summary(
            run_dir,
            {
                "runner": "run_maptools_official_cases",
                "case_group": _case_group_for_guidance(args),
                "case_count": 1,
                "success_count": 0,
                "stop_after": str(args.stop_after),
                "fractional_solver_backend": str(args.fractional_solver),
                "parameter_profile": "maptools_existing_preprocessing",
                "split_disconnected_components": bool(args.split_disconnected_components),
                "guidance": guidance_config,
                "graph_backend": _graph_backend_cli_config_from_args(args),
                "summary_contract_version": ROOT_SUMMARY_CONTRACT_VERSION,
                "cases": [summary.to_dict()],
            },
        )
        print(run_dir)
        raise SystemExit(1) from exc

    summaries = []
    filtered_inputs = [
        adapter_input
        for adapter_input in adapter_inputs
        if args.component_index is None or int(adapter_input.component_index) == int(args.component_index)
    ]
    if not filtered_inputs:
        raise SystemExit(f"no component matched --component-index {args.component_index}")
    for adapter_input in filtered_inputs:
        component_suffix = (
            ""
            if int(adapter_input.component_count) == 1
            else f"_component_{int(adapter_input.component_index)}"
        )
        case_id = f"{base_case_id}{component_suffix}"
        component_dir = run_dir / case_id
        component_dir.mkdir(parents=True, exist_ok=True)
        summaries.append(
            _run_adapter_input(
                args=args,
                case_id=case_id,
                case_dir=component_dir,
                adapter_input=adapter_input,
            )
        )
    case_dicts = [summary.to_dict() for summary in summaries]
    aggregate_metrics = _aggregate_component_metrics(case_dicts)
    root_payload = {
        "runner": "run_maptools_official_cases",
        "case_group": _case_group_for_guidance(args),
        "case_count": len(case_dicts),
        "success_count": sum(1 for summary in case_dicts if summary["status"] == "success"),
        "stop_after": str(args.stop_after),
        "fractional_solver_backend": str(args.fractional_solver),
        "parameter_profile": "maptools_existing_preprocessing",
        "split_disconnected_components": bool(args.split_disconnected_components),
        "atomic_orientation_count": int(args.atomic_orientation_count),
        "atomic_orientation_repetition": int(args.atomic_orientation_repetition),
        "guidance": guidance_config,
        "graph_backend": _graph_backend_cli_config_from_args(args),
        "maptools_project": Path(args.project_dir).name,
        "area_id": int(args.area_id),
        "component_count": len(case_dicts),
        "component_index_filter": args.component_index,
        "aggregate_metrics": aggregate_metrics,
        "summary_contract_version": ROOT_SUMMARY_CONTRACT_VERSION,
        "cases": case_dicts,
    }
    write_root_summary(run_dir, root_payload)
    print(run_dir)
    if any(summary["status"] != "success" for summary in case_dicts):
        raise SystemExit(1)


def _run_adapter_input(*, args: argparse.Namespace, case_id: str, case_dir: Path, adapter_input: object) -> RunSummary:
    parameters = OfficialExampleParameters(
        tool_radius=float(adapter_input.tool_radius_m),
        turn_costs=float(args.turn_cost),
        penalty_strength=float(args.penalty_strength),
        distance_factor=float(args.distance_factor),
        turn_factor=float(args.turn_factor),
        graph_length_limit_factor=float(args.graph_length_limit_factor),
        atomic_orientation_count=int(args.atomic_orientation_count),
        atomic_orientation_repetition=int(args.atomic_orientation_repetition),
    )
    guidance_config = _guidance_config_from_args(args)
    guidance_field = None
    if args.guidance_mode == "shelf_local_direction" or args.graph_backend == "square8_axis_guided":
        official_hex_side_length_m = (2.0 / math.sqrt(3.0)) * 2.0 * float(adapter_input.tool_radius_m)
        guidance_field = build_shelf_direction_guidance(
            geometry_result=adapter_input.geometry_result,
            coverage_width_m=float(adapter_input.metadata["coverage_width_m"]),
            tool_radius_m=float(adapter_input.tool_radius_m),
            official_hex_side_length_m=official_hex_side_length_m,
            resolution_m_per_px=float(adapter_input.metadata["resolution_m_per_px"]),
        )
    write_json(case_dir / "00_maptools_adapter_metadata.json", adapter_input.metadata)
    summary = run_official_steps_case(
        case_dir,
        stop_after=str(args.stop_after),
        seed=int(args.seed),
        parameters=parameters,
        parameter_profile="maptools_existing_preprocessing",
        fractional_solver_backend=str(args.fractional_solver),
        polygon_instance_factory=lambda: adapter_input.polygon_instance,
        case_id=case_id,
        case_group=_case_group_for_guidance(args),
        input_overrides={
            "source": str(adapter_input.project_dir),
            "algorithm_source": "pcpptc official flow with MapTools existing geometry_preparation adapter",
            "instance_source": "maptools_existing_geometry_preparation",
            "maptools_project": adapter_input.project_dir.name,
            "area_id": int(adapter_input.area_id),
            "area_name": adapter_input.area_name,
            "adapter_metadata": adapter_input.metadata,
            "parameters": asdict(parameters),
            "guidance": guidance_config,
            "graph_backend": _graph_backend_config_from_args(args, tool_radius_m=float(adapter_input.tool_radius_m)),
        },
        parameter_profile_note={
            "profile": "maptools_existing_preprocessing",
            "reason": "使用既有 MapTools geometry_preparation 输出构造官方 PolygonInstance",
            "algorithm_impact": "官方流程输入来自本地项目，不是官方随机 notebook case；不新增本地路径生成算法",
            "formal_planner_migration": "仅为研究适配入口；迁入前需评估 license、参数映射和失败处理",
        },
        guidance_field=guidance_field,
        guidance_config=guidance_config,
        graph_backend_config=_graph_backend_config_from_args(args, tool_radius_m=float(adapter_input.tool_radius_m)),
    )
    summary.artifacts.insert(
        0,
        inspect_artifact(
            case_dir,
            "00_maptools_adapter_metadata.json",
            stage="input_adapter",
            required=True,
        ),
    )
    write_summary(case_dir, summary)
    return summary


def _aggregate_component_metrics(case_dicts: list[dict[str, object]]) -> dict[str, object]:
    success_cases = [case for case in case_dicts if case.get("status") == "success"]
    total_area = 0.0
    covered_area = 0.0
    total_value = 0.0
    covered_value = 0.0
    total_length = 0.0
    waypoint_count = 0
    for case in success_cases:
        metrics = case.get("metrics", {})
        if not isinstance(metrics, dict):
            continue
        area = float(metrics.get("tour_feasible_area_m2", 0.0) or 0.0)
        covered = float(metrics.get("tour_covered_feasible_area_m2", 0.0) or 0.0)
        value = float(metrics.get("tour_total_valuable_area_value", 0.0) or 0.0)
        value_covered = float(metrics.get("tour_covered_value", 0.0) or 0.0)
        total_area += area
        covered_area += covered
        total_value += value
        covered_value += value_covered
        total_length += float(metrics.get("tour_length_m", 0.0) or 0.0)
        waypoint_count += int(metrics.get("tour_waypoint_count", 0) or 0)
    return {
        "component_count": int(len(case_dicts)),
        "successful_component_count": int(len(success_cases)),
        "failed_component_count": int(len(case_dicts) - len(success_cases)),
        "area_weighted_feasible_coverage_ratio": covered_area / total_area if total_area > 0.0 else None,
        "value_weighted_coverage_ratio": covered_value / total_value if total_value > 0.0 else None,
        "total_feasible_area_m2": total_area,
        "total_covered_feasible_area_m2": covered_area,
        "total_tour_length_m": total_length,
        "total_tour_waypoint_count": waypoint_count,
    }


if __name__ == "__main__":
    main()
