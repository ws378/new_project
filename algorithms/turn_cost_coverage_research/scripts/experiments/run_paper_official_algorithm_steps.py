"""运行官方 example_algorithm_steps.ipynb 对应算法步骤。"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Callable

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PACKAGE_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

from algorithms.turn_cost_coverage_research.src.guidance import (
    CorridorAxisAtomicStrips,
    GuidanceField,
    GuidedEquiangularRepetitionAtomicStrips,
    collect_vertex_guidance_stats,
    guidance_disabled_config,
)
from algorithms.turn_cost_coverage_research.src.guidance.square8_axis_graph import (
    Square8AxisGraphConfig,
    create_square8_axis_guided_graph,
)
from algorithms.turn_cost_coverage_research.src.visualization.artifact_writer import (
    RunSummary,
    default_dependencies,
    ensure_run_dir,
    inspect_artifact,
    validate_summary_contract,
    write_json,
    write_root_summary,
    write_summary,
)


DEFAULT_OUTPUT_ROOT = PACKAGE_ROOT / "output"
OFFICIAL_REPO = (
    PACKAGE_ROOT
    / "third_party"
    / "paper_official"
    / "ALENEX24-partial-coverage-path-planning"
)
OFFICIAL_SRC = OFFICIAL_REPO / "src"
OFFICIAL_NOTEBOOK = OFFICIAL_REPO / "examples" / "example_algorithm_steps.ipynb"
STAGE_ORDER = (
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
)
OFFICIAL_LICENSE_STATUS = (
    "pyproject classifier declares MIT, but no top-level LICENSE file was found; "
    "dependency licenses require migration review"
)


@dataclass(frozen=True)
class OfficialExampleParameters:
    """官方 notebook 中 RandomPolygonInstanceGenerator 与后续求解参数。"""

    complexity: int = 7
    size: float = 20.0
    penalties: int = 5
    multiplier: int = 2
    turn_costs: int = 10
    penalty_strength: float = 40.0
    multiplier_strength: float = 20.0
    tool_radius: float = 0.5
    graph_length_limit_factor: float = 2.0
    multiplier_attach_radius_factor: float = 0.25
    distance_factor: float = 1.0
    turn_factor: float = 50.0
    atomic_orientation_count: int = 3
    atomic_orientation_repetition: int = 2


def _install_official_path() -> None:
    src = str(OFFICIAL_SRC)
    if src not in sys.path:
        sys.path.insert(0, src)


def _save_figure(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _write_guidance_image(path: Path, image: np.ndarray, *, title: str, cmap: str, vmin: float | None = None, vmax: float | None = None) -> None:
    plt.figure(figsize=(8, 8))
    plt.imshow(image, cmap=cmap, vmin=vmin, vmax=vmax, origin="upper")
    plt.title(title)
    plt.axis("off")
    plt.colorbar(fraction=0.046, pad=0.04)
    _save_figure(path)


def _should_stop(stage: str, stop_after: str) -> bool:
    return STAGE_ORDER.index(stage) >= STAGE_ORDER.index(stop_after)


def _result_scope(stop_after: str) -> dict[str, object]:
    is_full = stop_after == STAGE_ORDER[-1]
    return {
        "stop_after": stop_after,
        "is_full_algorithm_run": is_full,
        "completion_scope": "full_official_algorithm" if is_full else f"official_prefix_until_{stop_after}",
        "success_meaning": "success 表示请求的官方阶段成功，不等同于未执行阶段也成功",
    }


def _normalized_guidance_config(guidance_config: dict[str, Any] | None) -> dict[str, Any]:
    if not guidance_config:
        return guidance_disabled_config()
    return dict(guidance_config)


def _normalized_graph_backend_config(graph_backend_config: dict[str, Any] | None) -> dict[str, Any]:
    if not graph_backend_config:
        return {
            "backend": "hex_delaunay",
            "algorithm_impact": "none",
        }
    return dict(graph_backend_config)


def _record_guidance_observation(
    *,
    case_dir: Path,
    summary: RunSummary,
    artifact_specs: list[tuple[str, str]],
    guidance_field: GuidanceField | None,
    guidance_config: dict[str, Any],
    graph_nodes: Any,
) -> None:
    if guidance_field is None or not bool(guidance_config.get("enabled")):
        summary.metrics["guidance"] = guidance_disabled_config(
            str(guidance_config.get("mode", "none")),
            str(guidance_config.get("status", "disabled_by_cli")),
        )
        return

    ok, status = guidance_field.preflight_status()
    guidance_payload = {
        **guidance_config,
        "status": status,
        "field": guidance_field.to_metadata(),
        "algorithm_impact": str(guidance_config.get("algorithm_impact", "artifact_only_no_path_change")),
        "formal_planner_migration": str(
            guidance_config.get("formal_planner_migration", "允许作为研究观测层；进入正式 planner 前必须另行评审软引导评分边界")
        ),
    }
    if not ok:
        guidance_payload["enabled"] = False
        guidance_payload["disabled_reason"] = status
        summary.metrics["guidance"] = guidance_payload
        write_json(
            case_dir / "11_guidance_vertex_hints.json",
            {
                "guidance": guidance_payload,
                "query": {
                    "vertex_count": 0,
                    "hit_count": 0,
                    "hit_ratio": 0.0,
                    "status_counts": {status: 1},
                },
            },
        )
        artifact_specs.append(("11_guidance_vertex_hints.json", "guidance"))
        return

    _write_guidance_image(
        case_dir / "09_guidance_direction_overlay.png",
        guidance_field.direction_rad_map,
        title="guidance direction radians",
        cmap="hsv",
        vmin=0.0,
        vmax=float(np.pi),
    )
    _write_guidance_image(
        case_dir / "10_guidance_confidence_overlay.png",
        guidance_field.confidence_map,
        title="guidance confidence",
        cmap="viridis",
        vmin=0.0,
        vmax=1.0,
    )
    stats = collect_vertex_guidance_stats(
        graph_nodes,
        guidance_field,
        min_confidence=float(guidance_config.get("min_confidence", 0.08)),
    )
    write_json(
        case_dir / "11_guidance_vertex_hints.json",
        {
            "guidance": guidance_payload,
            **stats,
        },
    )
    query = stats.get("query", {})
    summary.metrics["guidance"] = {
        **guidance_payload,
        "vertex_count": int(query.get("vertex_count", 0)),
        "hit_count": int(query.get("hit_count", 0)),
        "hit_ratio": float(query.get("hit_ratio", 0.0)),
        "average_confidence": float(query.get("average_confidence", 0.0)),
        "status_counts": dict(query.get("status_counts", {})),
    }
    summary.metrics["guidance_vertex_count"] = int(query.get("vertex_count", 0))
    summary.metrics["guidance_hit_count"] = int(query.get("hit_count", 0))
    summary.metrics["guidance_hit_ratio"] = float(query.get("hit_ratio", 0.0))
    artifact_specs.extend(
        [
            ("09_guidance_direction_overlay.png", "guidance"),
            ("10_guidance_confidence_overlay.png", "guidance"),
            ("11_guidance_vertex_hints.json", "guidance"),
        ]
    )


def _vertex_to_shapely_point(vertex: Any) -> Any:
    point = getattr(vertex, "point", vertex)
    if hasattr(point, "to_shapely"):
        return point.to_shapely()
    return point


def _tour_shapely_points(tour: Any) -> list[Any]:
    return [_vertex_to_shapely_point(vertex) for vertex in tour.iterate_vertices(closed=False)]


def _value_area_total(polygon_instance: Any) -> float:
    return float(sum(area.area * value for area, value in polygon_instance.valuable_areas))


def _update_tour_quality_metrics(summary: RunSummary, polygon_instance: Any, tour: Any) -> list[Any]:
    """记录官方 tour 的覆盖质量；只度量结果，不改变算法。"""
    points = _tour_shapely_points(tour)
    summary.metrics["tour_waypoint_count"] = int(len(points))
    summary.metrics["tour_length_m"] = float(tour.length())
    summary.metrics["tour_turn_angle_rad"] = float(tour.angle_sum())
    summary.metrics["tour_turn_angle_deg"] = float(math.degrees(tour.angle_sum()))
    if not points:
        summary.metrics["tour_quality_metric_status"] = "empty_tour"
        return points

    covering_area = polygon_instance.compute_covering_area(points)
    original_area = polygon_instance.original_area
    feasible_area = polygon_instance.feasible_area
    covered_original_area = float(covering_area.intersection(original_area).area)
    covered_feasible_area = float(covering_area.intersection(feasible_area).area)
    original_area_size = float(original_area.area)
    feasible_area_size = float(feasible_area.area)
    covered_value = float(polygon_instance.compute_covering_value(points))
    missed_value = float(polygon_instance.compute_missed_covering_value(points))
    total_value = _value_area_total(polygon_instance)

    summary.metrics["tour_coverage_area_m2"] = float(covering_area.area)
    summary.metrics["tour_covered_original_area_m2"] = covered_original_area
    summary.metrics["tour_original_area_m2"] = original_area_size
    summary.metrics["tour_original_area_coverage_ratio"] = (
        covered_original_area / original_area_size if original_area_size > 0.0 else 0.0
    )
    summary.metrics["tour_covered_feasible_area_m2"] = covered_feasible_area
    summary.metrics["tour_feasible_area_m2"] = feasible_area_size
    summary.metrics["tour_feasible_area_coverage_ratio"] = (
        covered_feasible_area / feasible_area_size if feasible_area_size > 0.0 else 0.0
    )
    summary.metrics["tour_total_valuable_area_value"] = total_value
    summary.metrics["tour_covered_value"] = covered_value
    summary.metrics["tour_missed_value"] = missed_value
    summary.metrics["tour_valuable_area_value_coverage_ratio"] = covered_value / total_value if total_value > 0.0 else 0.0
    summary.metrics["tour_quality_metric_source"] = {
        "source": "pcpptc PolygonInstance.compute_covering_area/compute_covering_value/compute_missed_covering_value",
        "scope": "结果度量，不参与路径生成",
        "algorithm_impact": "不改变官方流程或 HiGHS 替代边界",
    }
    return points


def _official_dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    package_names = (
        "gurobipy",
        "pcst_fast",
        "pygmsh",
        "gmsh",
        "descartes",
        "sympy",
        "chardet",
        "blossomv",
    )
    for package_name in package_names:
        try:
            versions[package_name] = importlib_metadata.version(package_name)
        except importlib_metadata.PackageNotFoundError:
            versions[package_name] = "not_installed"
    try:
        import gurobipy as gp

        versions["gurobi_runtime_version"] = ".".join(str(item) for item in gp.gurobi.version())
    except Exception as exc:  # pragma: no cover - environment probe only
        versions["gurobi_runtime_version"] = f"unavailable:{type(exc).__name__}"
    return versions


def run_official_steps_case(
    case_dir: Path,
    *,
    stop_after: str,
    seed: int,
    parameters: OfficialExampleParameters,
    parameter_profile: str,
    fractional_solver_backend: str,
    polygon_instance_factory: Callable[[], Any] | None = None,
    case_id: str = "official_example_algorithm_steps",
    case_group: str = "paper_official_algorithm_steps",
    input_overrides: dict[str, Any] | None = None,
    parameter_profile_note: dict[str, Any] | None = None,
    guidance_field: GuidanceField | None = None,
    guidance_config: dict[str, Any] | None = None,
    graph_backend_config: dict[str, Any] | None = None,
) -> RunSummary:
    _install_official_path()
    # 官方代码按旧 NumPy 习惯使用 np.math；NumPy 2 移除了该属性。
    # 这是兼容性补丁，不改变论文算法逻辑，summary 中记录来源和影响范围。
    if not hasattr(np, "math"):
        np.math = math  # type: ignore[attr-defined]
    normalized_guidance_config = _normalized_guidance_config(guidance_config)
    normalized_graph_backend_config = _normalized_graph_backend_config(graph_backend_config)
    graph_backend = str(normalized_graph_backend_config.get("backend", "hex_delaunay"))
    if graph_backend not in {"hex_delaunay", "square8_axis_guided"}:
        raise ValueError(f"unsupported graph backend: {graph_backend}")
    if (
        graph_backend == "square8_axis_guided"
        and bool(normalized_guidance_config.get("enabled"))
        and not bool(normalized_graph_backend_config.get("allow_square8_guided_atomic", False))
    ):
        raise ValueError(
            "square8_axis_guided 与 enabled guidance 的组合属于非官方组合实验，"
            "必须在 graph_backend_config 中显式设置 allow_square8_guided_atomic=True"
        )

    case_dir.mkdir(parents=True, exist_ok=True)
    from pcpptc.grid_solver import PointBasedInstance, PointVertex
    from pcpptc.grid_solver.cycle_connecting import connect_cycles_via_pcst
    from pcpptc.grid_solver.cycle_cover.atomic_strip_matcher import (
        AtomicStripMatching,
        TransitionCostCalculator,
    )
    from pcpptc.grid_solver.cycle_cover.atomic_strip_orientation import (
        EquiangularRepetitionAtomicStrips,
    )
    from pcpptc.grid_solver.cycle_cover.fractional_grid_solver import FractionalGridSolver
    from pcpptc.grid_solver.grid_instance import MultipliedTouringCosts
    from pcpptc.grid_solver.grid_solution import create_cycle_solution, is_feasible_cycle_cover
    from pcpptc.grid_solver.grid_solution.coverage_analysis import plot_tour_coverage
    from pcpptc.instance_converter.graph import (
        attach_multiplier_to_graph,
        create_delaunay_graph,
        get_coverage_necessities_from_polygon_instance,
    )
    from pcpptc.instance_converter.grid.basic_grids import hexagonal_grid
    from pcpptc.instance_converter.polygonal_area import PolygonalArea
    from pcpptc.plot import plot_polygon_instance, setup_plot
    from pcpptc.plot.atomic_strip_matching import plot_atomic_strip_matching
    from pcpptc.plot.atomic_strip_orientation import plot_atomic_strips
    from pcpptc.plot.intermediate import plot_environment, plot_fractional_solution, plot_graph, plot_points
    from pcpptc.polygon_instance import RandomPolygonInstanceGenerator
    from pcpptc.polygon_instance.statistics import InstanceStatistics

    random.seed(seed)
    np.random.seed(seed)

    summary = RunSummary(
        case_id=case_id,
        case_group=case_group,
        input={
            "source": str(OFFICIAL_NOTEBOOK),
            "source_repo": str(OFFICIAL_REPO),
            "source_commit": _read_official_commit(),
            "license_status": OFFICIAL_LICENSE_STATUS,
            "algorithm_source": "pcpptc official example_algorithm_steps.ipynb",
            "seed": int(seed),
            "seed_policy": "research_fixed_seed_not_in_official_notebook",
            "seed_reason": "官方 notebook 未固定随机种子；研究脚本固定 seed 以保证产物可复算",
            "stop_after": stop_after,
            "fractional_solver_backend": fractional_solver_backend,
            "parameter_profile": parameter_profile,
            "parameters": asdict(parameters),
            "result_scope": _result_scope(stop_after),
            "guidance": normalized_guidance_config,
            "graph_backend": normalized_graph_backend_config,
        },
        dependencies=default_dependencies(
            mesh_backend=(
                "pcpptc_official_hex_delaunay"
                if graph_backend == "hex_delaunay"
                else "maptools_non_official_square8_axis_guided_graph"
            ),
            solver_backend=(
                "pcpptc_official_gurobi_blossom_pcst"
                if fractional_solver_backend == "gurobi"
                else "highs_non_official_fractional_lp_then_official_blossom_pcst"
            ),
        ),
        stage_status={stage: "skipped_not_applicable" for stage in STAGE_ORDER},
        third_party_usage=[
            {
                "name": "pcpptc",
                "source": str(OFFICIAL_REPO),
                "commit": _read_official_commit(),
                "commit_or_version": _read_official_commit(),
                "license_status": OFFICIAL_LICENSE_STATUS,
                "usage": "直接运行官方 notebook 对应算法步骤",
                "formal_planner_migration": "不允许直接迁入；需完成 license/依赖/接口评估",
            }
        ],
    )
    if input_overrides:
        summary.input.update(input_overrides)
    summary.dependencies["official_dependency_versions"] = _official_dependency_versions()
    summary.metrics["result_scope"] = _result_scope(stop_after)
    summary.metrics["guidance"] = normalized_guidance_config
    summary.metrics["graph_backend"] = normalized_graph_backend_config
    summary.metrics["seed_policy"] = {
        "seed": int(seed),
        "policy": "research_fixed_seed_not_in_official_notebook",
        "reason": "官方 notebook 未固定随机种子；固定 seed 仅用于研究产物可复算",
    }
    if fractional_solver_backend == "highs" and not _should_stop("graph", stop_after):
        summary.metrics["non_official_solver_replacement"] = {
            "stage": "fractional",
            "replacement": "scipy.optimize.linprog(method='highs')",
            "official_stage_replaced": "pcpptc FractionalGridSolver Gurobi LP optimize",
            "scope": "只替换 fractional LP；后续 atomic strips、matching、cycle cover、PCST 仍调用官方流程",
            "algorithm_impact": "非官方替代，可能与 Gurobi 在数值容差、退化最优解和求解时间上不同",
            "formal_planner_migration": "不允许直接迁入；仅用于研究绕过 Gurobi size-limited license 的对照实验",
        }
    summary.metrics["compatibility_patches"] = [
        {
            "patch": "numpy_math_alias",
            "reason": "官方代码使用 np.math；NumPy 2 已移除该属性",
            "scope": "仅运行官方 pcpptc 代码时设置 np.math = math",
            "algorithm_impact": "不改变算法逻辑",
            "formal_planner_migration": "不允许；正式迁入前应修复上游兼容性或固定依赖版本",
        }
    ]
    if parameter_profile_note is not None:
        summary.metrics["parameter_profile_note"] = dict(parameter_profile_note)
    elif parameter_profile != "notebook_default":
        summary.metrics["parameter_profile_note"] = {
            "profile": parameter_profile,
            "reason": "当前 Gurobi size-limited license 无法求解 notebook 默认规模；本 profile 仅用于官方 fractional LP 小规模 solver 对照",
            "algorithm_impact": "仍调用官方 pcpptc 前缀流程，但实例规模与论文 notebook 默认不同，不能作为论文默认效果复现结论",
            "formal_planner_migration": "不允许直接迁入；仅作为研究复现证据",
        }
    artifact_specs: list[tuple[str, str]] = []
    current_stage = "instance"
    try:
        tool_radius = parameters.tool_radius

        current_stage = "instance"
        if polygon_instance_factory is None:
            pi = RandomPolygonInstanceGenerator(
                complexity=parameters.complexity,
                size=parameters.size,
                penalties=parameters.penalties,
                multiplier=parameters.multiplier,
                turn_costs=parameters.turn_costs,
                penalty_strength=parameters.penalty_strength,
                multiplier_strength=parameters.multiplier_strength,
                tool_radius=tool_radius,
            )()
        else:
            pi = polygon_instance_factory()
        ax = setup_plot()
        plot_polygon_instance(ax, pi)
        _save_figure(case_dir / "00_official_instance.png")
        artifact_specs.append(("00_official_instance.png", current_stage))
        stats = InstanceStatistics(pi).as_json()
        summary.metrics["instance_statistics"] = stats
        summary.stage_status[current_stage] = "success"
        if _should_stop(current_stage, stop_after):
            return _finalize(case_dir, summary, artifact_specs)

        current_stage = "grid"
        pa = PolygonalArea(polygon=pi.feasible_area)
        bb = pa.get_bounding_box()
        opt_hex_length = (2 / np.sqrt(3)) * 2 * tool_radius
        pending_graph = None
        square8_stats = None
        if graph_backend == "square8_axis_guided":
            square8_config = Square8AxisGraphConfig(
                grid_step_m=float(normalized_graph_backend_config.get("grid_step_m", 2.0 * tool_radius)),
                diagonal_cost_multiplier=float(normalized_graph_backend_config.get("diagonal_cost_multiplier", 1.15)),
                axis_confidence_threshold=float(normalized_graph_backend_config.get("axis_confidence_threshold", 0.60)),
                axis_angle_tolerance_deg=float(normalized_graph_backend_config.get("axis_angle_tolerance_deg", 25.0)),
                diagonal_axis_suppress_confidence=float(normalized_graph_backend_config.get("diagonal_axis_suppress_confidence", 0.60)),
                bridge_disconnected_components=bool(normalized_graph_backend_config.get("bridge_disconnected_components", True)),
                bridge_max_step_factor=float(normalized_graph_backend_config.get("bridge_max_step_factor", 8.0)),
                bridge_cost_multiplier=float(normalized_graph_backend_config.get("bridge_cost_multiplier", 4.0)),
            )
            grid_points, pending_graph, square8_stats = create_square8_axis_guided_graph(
                polygonal_area=pa,
                point_vertex_cls=PointVertex,
                config=square8_config,
                guidance_field=guidance_field,
            )
            summary.metrics["square8_axis_guided_graph"] = square8_stats
        else:
            grid = hexagonal_grid(
                min_x=bb[0][0],
                min_y=bb[0][1],
                max_x=bb[1][0],
                max_y=bb[1][1],
                side_length=opt_hex_length,
            )
            grid_points = [PointVertex(p) for p in pa.filter(grid)]
        ax = setup_plot()
        plot_environment(ax, pa)
        plot_points(ax, grid_points)
        _save_figure(case_dir / "01_official_grid.png")
        artifact_specs.append(("01_official_grid.png", current_stage))
        summary.metrics["grid_point_count"] = int(len(grid_points))
        summary.metrics["grid_backend"] = graph_backend
        summary.stage_status[current_stage] = "success"
        if _should_stop(current_stage, stop_after):
            return _finalize(case_dir, summary, artifact_specs)

        current_stage = "graph"
        if graph_backend == "square8_axis_guided":
            graph = pending_graph
            if graph is None:
                raise ValueError("square8 graph backend did not create graph")
        else:
            graph = create_delaunay_graph(
                grid_points,
                length_limit=parameters.graph_length_limit_factor * opt_hex_length,
                polygon=pa,
            )
        attach_multiplier_to_graph(graph, pi, parameters.multiplier_attach_radius_factor * tool_radius)
        if graph_backend == "square8_axis_guided":
            for u, v, data in graph.edges(data=True):
                data["multiplier"] = float(data.get("multiplier", 1.0)) * float(data.get("cost_multiplier", 1.0))
        ax = setup_plot()
        plot_environment(ax, pa)
        plot_graph(ax, graph)
        _save_figure(case_dir / "02_official_graph.png")
        artifact_specs.append(("02_official_graph.png", current_stage))
        summary.metrics["graph_node_count"] = int(graph.number_of_nodes())
        summary.metrics["graph_edge_count"] = int(graph.number_of_edges())
        if square8_stats is not None:
            summary.metrics["square8_axis_guided_graph"]["connected_component_count"] = int(nx.number_connected_components(graph))
        _record_guidance_observation(
            case_dir=case_dir,
            summary=summary,
            artifact_specs=artifact_specs,
            guidance_field=guidance_field,
            guidance_config=normalized_guidance_config,
            graph_nodes=graph.nodes,
        )
        summary.stage_status[current_stage] = "success"
        if _should_stop(current_stage, stop_after):
            return _finalize(case_dir, summary, artifact_specs)

        current_stage = "coverage"
        touring_costs = MultipliedTouringCosts(
            graph=graph,
            distance_factor=parameters.distance_factor,
            turn_factor=parameters.turn_factor,
        )
        coverage_necessities = get_coverage_necessities_from_polygon_instance(pi, graph)
        instance = PointBasedInstance(graph, touring_costs, coverage_necessities)
        summary.metrics["coverage_necessity_override_count"] = int(len(getattr(coverage_necessities, "_data", {})))
        summary.stage_status[current_stage] = "success"
        if _should_stop(current_stage, stop_after):
            return _finalize(case_dir, summary, artifact_specs)

        current_stage = "fractional"
        if fractional_solver_backend == "highs":
            from algorithms.turn_cost_coverage_research.src.official_replacements.highs_fractional_solver import (
                HighsFractionalGridSolver,
            )

            fractional_solver = HighsFractionalGridSolver()
        else:
            fractional_solver = FractionalGridSolver()
        fractional_solution = fractional_solver(instance)
        summary.metrics["fractional_solver_backend"] = fractional_solver_backend
        summary.metrics["fractional_objective_value"] = float(fractional_solution[1])
        if fractional_solver_backend == "highs":
            summary.metrics["highs_variable_count"] = int(getattr(fractional_solver, "last_variable_count", 0))
            summary.metrics["highs_constraint_count"] = int(getattr(fractional_solver, "last_constraint_count", 0))
            highs_result = getattr(fractional_solver, "last_result", None)
            if highs_result is not None:
                summary.metrics["highs_status"] = int(highs_result.status)
                summary.metrics["highs_message"] = str(highs_result.message)
        ax = setup_plot()
        ax.set_facecolor("lightgrey")
        plot_polygon_instance(ax, pi)
        plot_points(ax, grid_points)
        plot_fractional_solution(ax, fractional_solution[0])
        _save_figure(case_dir / "03_official_fractional_solution.png")
        artifact_specs.append(("03_official_fractional_solution.png", current_stage))
        summary.stage_status[current_stage] = "success"
        if _should_stop(current_stage, stop_after):
            return _finalize(case_dir, summary, artifact_specs)

        current_stage = "atomic_strips"
        guidance_preflight_ok = False
        if guidance_field is not None and bool(normalized_guidance_config.get("enabled")):
            guidance_preflight_ok, _ = guidance_field.preflight_status()
        if guidance_preflight_ok:
            atomic_guidance_strategy = str(normalized_guidance_config.get("atomic_guidance_strategy", "soft_bias"))
            if atomic_guidance_strategy == "corridor_axis":
                corridor_axis_primary_orientation_count = normalized_guidance_config.get(
                    "corridor_axis_primary_orientation_count"
                )
                corridor_axis_primary_orientation_count = (
                    None
                    if corridor_axis_primary_orientation_count is None
                    else int(corridor_axis_primary_orientation_count)
                )
                strip_builder = CorridorAxisAtomicStrips(
                    number_of_different_orientations=parameters.atomic_orientation_count,
                    repetition_of_each_orientation=parameters.atomic_orientation_repetition,
                    guidance_field=guidance_field,
                    min_confidence=float(normalized_guidance_config.get("min_confidence", 0.08)),
                    primary_orientation_count=corridor_axis_primary_orientation_count,
                )
                summary.metrics["atomic_strip_selection"] = {
                    "strategy": "corridor_axis_atomic_strips",
                    "official_base": "EquiangularRepetitionAtomicStrips",
                    "corridor_axis_primary_orientation_count": corridor_axis_primary_orientation_count,
                    "algorithm_impact": "non_official_corridor_axis_atomic_strip_candidate_replacement",
                    "official_difference": "高置信 corridor 点优先使用 guidance 主轴，并可保留部分垂直候选以维持 strip/cycle 连接性；低置信点回退官方候选选择；后续 assignment/matching/cycle cover/PCST 沿用官方流程",
                }
            else:
                strip_builder = GuidedEquiangularRepetitionAtomicStrips(
                    number_of_different_orientations=parameters.atomic_orientation_count,
                    repetition_of_each_orientation=parameters.atomic_orientation_repetition,
                    guidance_field=guidance_field,
                    guidance_weight_frac=float(normalized_guidance_config.get("weight_frac", 0.25)),
                    guidance_weight_abs=float(normalized_guidance_config.get("weight_abs", 0.0)),
                    min_confidence=float(normalized_guidance_config.get("min_confidence", 0.08)),
                )
                summary.metrics["atomic_strip_selection"] = {
                    "strategy": "guided_equiangular_repetition_atomic_strips",
                    "official_base": "EquiangularRepetitionAtomicStrips",
                    "algorithm_impact": "soft_atomic_strip_orientation_bias",
                    "official_difference": "只在候选方向集合评分处加入方向偏置；后续 assignment/matching/cycle cover/PCST 沿用官方流程",
                }
        else:
            strip_builder = EquiangularRepetitionAtomicStrips(
                number_of_different_orientations=parameters.atomic_orientation_count,
                reptition_of_each_orientation=parameters.atomic_orientation_repetition,
            )
            summary.metrics["atomic_strip_selection"] = {
                "strategy": "official_equiangular_repetition_atomic_strips",
                "algorithm_impact": "none",
            }
        atomic_strips = strip_builder(instance, fractional_solution[0])
        if hasattr(strip_builder, "last_stats"):
            summary.metrics["guided_atomic_strip_stats"] = dict(getattr(strip_builder, "last_stats"))
        ax = setup_plot(figsize=(20, 20))
        plot_environment(ax, pa)
        plot_points(ax, graph.nodes)
        plot_fractional_solution(ax, fractional_solution[0])
        plot_atomic_strips(ax, atomic_strips, tool_radius)
        _save_figure(case_dir / "04_official_atomic_strips.png")
        artifact_specs.append(("04_official_atomic_strips.png", current_stage))
        summary.metrics["atomic_strip_vertex_count"] = int(len(atomic_strips))
        summary.stage_status[current_stage] = "success"
        if _should_stop(current_stage, stop_after):
            return _finalize(case_dir, summary, artifact_specs)

        current_stage = "matching"
        matcher = AtomicStripMatching(graph, TransitionCostCalculator(instance.touring_costs))
        for point in graph.nodes:
            for orientation in atomic_strips[point]:
                strip = matcher.create_atomic_strip(point, orientation.orientation)
                if orientation.is_skippable():
                    matcher.add_skip_penalty(strip, orientation.penalty)
        edges = matcher.solve()
        ax = setup_plot()
        ax.set_facecolor("lightgrey")
        plot_polygon_instance(ax, pi)
        plot_atomic_strip_matching(ax, matcher, color="blue")
        _save_figure(case_dir / "05_official_atomic_strip_matching.png")
        artifact_specs.append(("05_official_atomic_strip_matching.png", current_stage))
        summary.metrics["matching_edge_count"] = int(len(edges))
        summary.stage_status[current_stage] = "success"
        if _should_stop(current_stage, stop_after):
            return _finalize(case_dir, summary, artifact_specs)

        current_stage = "cycle_cover"
        fractional_solution = matcher.to_solution()
        feasible_cycle_cover = bool(is_feasible_cycle_cover(instance, fractional_solution, verbose=True))
        cycle_cover = create_cycle_solution(instance.graph, fractional_solution)
        summary.metrics["cycle_cover_feasible"] = feasible_cycle_cover
        summary.metrics["cycle_count_before_connection"] = int(len(cycle_cover))
        summary.stage_status[current_stage] = "success"
        if _should_stop(current_stage, stop_after):
            return _finalize(case_dir, summary, artifact_specs)

        current_stage = "connected_tour"
        tour = connect_cycles_via_pcst(instance, cycle_cover)
        connected_fractional = tour.to_fractional_solution()
        ax = setup_plot(figsize=(20, 20))
        ax.set_facecolor("lightgrey")
        plot_polygon_instance(ax, pi)
        plot_points(ax, grid_points)
        plot_fractional_solution(ax, connected_fractional)
        _save_figure(case_dir / "06_official_connected_tour.png")
        artifact_specs.append(("06_official_connected_tour.png", current_stage))
        summary.metrics["connected_tour_feasible"] = bool(is_feasible_cycle_cover(instance, connected_fractional))
        tour_points = _update_tour_quality_metrics(summary, pi, tour)
        write_json(
            case_dir / "07_official_tour_waypoints.json",
            {
                "coordinate_frame": "maptools_meter_frame_or_official_instance_frame",
                "closed": False,
                "waypoint_count": len(tour_points),
                "waypoints": [[float(point.x), float(point.y)] for point in tour_points],
            },
        )
        artifact_specs.append(("07_official_tour_waypoints.json", current_stage))
        summary.stage_status[current_stage] = "success"
        if _should_stop(current_stage, stop_after):
            return _finalize(case_dir, summary, artifact_specs)

        current_stage = "coverage_plot"
        ax = setup_plot()
        ax.set_facecolor("lightgrey")
        plot_polygon_instance(ax, pi)
        plot_tour_coverage(ax, tour, tool_radius)
        plot_fractional_solution(ax, tour.to_fractional_solution())
        _save_figure(case_dir / "08_official_tour_coverage.png")
        artifact_specs.append(("08_official_tour_coverage.png", current_stage))
        summary.stage_status[current_stage] = "success"
    except Exception as exc:  # pragma: no cover - script-level official dependency capture
        summary.status = "failure"
        summary.failure_stage = current_stage
        summary.failure_reason = type(exc).__name__
        summary.failure_detail = str(exc)
        if current_stage in summary.stage_status:
            summary.stage_status[current_stage] = "failure"

    return _finalize(case_dir, summary, artifact_specs)


def _read_official_commit() -> str:
    head = OFFICIAL_REPO / ".git" / "HEAD"
    if not head.is_file():
        return ""
    value = head.read_text(encoding="utf-8").strip()
    if not value.startswith("ref: "):
        return value
    ref = OFFICIAL_REPO / ".git" / value.removeprefix("ref: ").strip()
    return ref.read_text(encoding="utf-8").strip() if ref.is_file() else value


def _finalize(case_dir: Path, summary: RunSummary, artifact_specs: list[tuple[str, str]]) -> RunSummary:
    summary.artifacts.extend(
        inspect_artifact(case_dir, filename, stage=stage, required=True)
        for filename, stage in artifact_specs
    )
    if summary.status == "success" and summary.failure_reason:
        summary.status = "failure"
    contract_errors = validate_summary_contract(summary)
    if contract_errors and summary.status == "success":
        summary.status = "failure"
        summary.failure_stage = "summary_contract"
        summary.failure_reason = "contract_violation"
        summary.failure_detail = "; ".join(contract_errors)
    write_summary(case_dir, summary)
    return summary


def run_official_steps(
    output_root: Path,
    *,
    stop_after: str,
    seed: int,
    parameters: OfficialExampleParameters,
    parameter_profile: str,
    fractional_solver_backend: str,
    guidance_config: dict[str, Any] | None = None,
) -> tuple[Path, int, int]:
    run_dir = ensure_run_dir(output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")))
    case_summary = run_official_steps_case(
        run_dir / "official_example_algorithm_steps",
        stop_after=stop_after,
        seed=seed,
        parameters=parameters,
        parameter_profile=parameter_profile,
        fractional_solver_backend=fractional_solver_backend,
        guidance_config=guidance_config,
    ).to_dict()
    case_count = 1
    success_count = 1 if case_summary["status"] == "success" else 0
    write_root_summary(
        run_dir,
        {
            "runner": "run_paper_official_algorithm_steps",
            "case_group": "paper_official_algorithm_steps",
            "case_count": case_count,
            "success_count": success_count,
            "stop_after": stop_after,
            "seed": int(seed),
            "fractional_solver_backend": fractional_solver_backend,
            "parameter_profile": parameter_profile,
            "parameters": asdict(parameters),
            "result_scope": _result_scope(stop_after),
            "profile_purpose": _profile_purpose(parameter_profile, fractional_solver_backend),
            "guidance": _normalized_guidance_config(guidance_config),
            "cases": [case_summary],
        },
    )
    return run_dir, case_count, success_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行官方 example_algorithm_steps.ipynb 对应算法步骤。")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="输出根目录。")
    parser.add_argument("--seed", type=int, help="随机种子；未设置时 notebook_default 使用 7，license_smoke 使用 4。")
    parser.add_argument("--stop-after", choices=STAGE_ORDER, default="coverage_plot", help="运行到指定官方阶段后停止。")
    parser.add_argument(
        "--parameter-profile",
        choices=("notebook_default", "license_smoke"),
        default="notebook_default",
        help="参数 profile。notebook_default 保持官方 notebook 参数；license_smoke 只用于当前 Gurobi 限制下的小规模 fractional LP 对照。",
    )
    parser.add_argument("--complexity", type=int, help="覆盖官方 RandomPolygonInstanceGenerator complexity。")
    parser.add_argument("--size", type=float, help="覆盖官方 RandomPolygonInstanceGenerator size。")
    parser.add_argument("--penalties", type=int, help="覆盖官方 RandomPolygonInstanceGenerator penalties。")
    parser.add_argument("--multiplier", type=int, help="覆盖官方 RandomPolygonInstanceGenerator multiplier。")
    parser.add_argument("--turn-costs", type=int, help="覆盖官方 RandomPolygonInstanceGenerator turn_costs。")
    parser.add_argument("--penalty-strength", type=float, help="覆盖官方 RandomPolygonInstanceGenerator penalty_strength。")
    parser.add_argument("--multiplier-strength", type=float, help="覆盖官方 RandomPolygonInstanceGenerator multiplier_strength。")
    parser.add_argument("--tool-radius", type=float, help="覆盖官方 tool_radius。")
    parser.add_argument("--turn-factor", type=float, help="覆盖官方 MultipliedTouringCosts turn_factor。")
    parser.add_argument(
        "--expect-license-failure",
        action="store_true",
        help="期望 notebook 默认完整链路因 Gurobi size-limited license 在 fractional 阶段失败；匹配时返回 0。",
    )
    parser.add_argument(
        "--fractional-solver",
        choices=("gurobi", "highs"),
        default="gurobi",
        help="fractional LP 求解器。highs 是非官方替代实验，只替换 Gurobi LP。",
    )
    parser.add_argument(
        "--guidance-mode",
        choices=("none", "shelf_local_direction"),
        default="none",
        help="方向引导模式；官方随机 case 无 MapTools crop frame，因此 shelf_local_direction 显式不支持。",
    )
    parser.add_argument("--guidance-weight-frac", type=float, default=0.25, help="预留软引导相对权重；当前 paper runner 不使用。")
    parser.add_argument("--guidance-weight-abs", type=float, default=0.0, help="预留软引导绝对权重；当前 paper runner 不使用。")
    parser.add_argument("--guidance-min-confidence", type=float, default=0.08, help="方向场顶点查询最低置信度。")
    return parser.parse_args()


def _parameters_from_args(args: argparse.Namespace) -> OfficialExampleParameters:
    if args.parameter_profile == "license_smoke":
        params = OfficialExampleParameters(
            complexity=3,
            size=5.0,
            penalties=1,
            multiplier=1,
            turn_costs=1,
            penalty_strength=40.0,
            multiplier_strength=20.0,
            tool_radius=0.5,
        )
    else:
        params = OfficialExampleParameters()

    overrides = {
        "complexity": args.complexity,
        "size": args.size,
        "penalties": args.penalties,
        "multiplier": args.multiplier,
        "turn_costs": args.turn_costs,
        "penalty_strength": args.penalty_strength,
        "multiplier_strength": args.multiplier_strength,
        "tool_radius": args.tool_radius,
        "turn_factor": args.turn_factor,
    }
    values = asdict(params)
    for key, value in overrides.items():
        if value is not None:
            values[key] = value
    return OfficialExampleParameters(**values)


def _profile_purpose(parameter_profile: str, fractional_solver_backend: str) -> str:
    solver_note = ""
    if fractional_solver_backend == "highs":
        solver_note = "；fractional 阶段使用 HiGHS 非官方替代，不代表官方 Gurobi 结果"
    if parameter_profile == "license_smoke":
        return "缩小官方实例规模以绕过当前 Gurobi size-limited license，仅用于官方 fractional LP solver 对照，不代表 notebook 默认效果" + solver_note
    return "保持官方 notebook 的实例生成与求解参数；随机种子是研究脚本额外固定的可复算参数" + solver_note


def _is_expected_license_failure(run_dir: Path) -> bool:
    payload = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    if len(cases) != 1:
        return False
    case = cases[0]
    return (
        payload.get("success_count") == 0
        and payload.get("parameter_profile") == "notebook_default"
        and payload.get("fractional_solver_backend") == "gurobi"
        and payload.get("result_scope", {}).get("is_full_algorithm_run") is True
        and case.get("failure_stage") == "fractional"
        and case.get("failure_reason") == "GurobiError"
        and "size-limited license" in str(case.get("failure_detail", ""))
    )


def main() -> None:
    args = parse_args()
    if args.guidance_mode != "none":
        raise SystemExit(
            "run_paper_official_algorithm_steps.py 不支持 shelf_local_direction：官方随机 case 没有 MapTools crop 坐标系和 geometry_result"
        )
    parameters = _parameters_from_args(args)
    seed = int(args.seed) if args.seed is not None else (4 if args.parameter_profile == "license_smoke" else 7)
    run_dir, case_count, success_count = run_official_steps(
        Path(args.output_root).expanduser().resolve(),
        stop_after=str(args.stop_after),
        seed=seed,
        parameters=parameters,
        parameter_profile=str(args.parameter_profile),
        fractional_solver_backend=str(args.fractional_solver),
        guidance_config={
            "enabled": False,
            "mode": str(args.guidance_mode),
            "status": "unsupported_for_paper_random_case" if args.guidance_mode != "none" else "disabled_by_cli",
            "weight_frac": float(args.guidance_weight_frac),
            "weight_abs": float(args.guidance_weight_abs),
            "min_confidence": float(args.guidance_min_confidence),
            "algorithm_impact": "none",
        },
    )
    print(run_dir)
    if success_count != case_count:
        if args.expect_license_failure and _is_expected_license_failure(run_dir):
            return
        raise SystemExit(1)
    if args.expect_license_failure:
        raise SystemExit("expected Gurobi size-limited license failure, but run succeeded")


if __name__ == "__main__":
    main()
