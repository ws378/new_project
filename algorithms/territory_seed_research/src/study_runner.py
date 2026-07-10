from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from algorithms.coverage_planning.contracts import CoveragePlannerConfig
from algorithms.coverage_planning.planners.shelf_aware_guarded import ShelfAwareCoveragePlanner

from .ctg_territory_extractor import extract_ctg_territory
from .direction_grid import DirectionGridResult, build_direction_grid, direction_grid_to_axis_maps
from .fourfloor_inputs import DEFAULT_PROJECT_DIR, PACKAGE_ROOT, StudyInput, build_study_input, load_fourfloor_project
from .territory_expansion import ExpandedTerritory, expand_dead_end_territories
from .visualization import write_visualizations


DEFAULT_OUTPUT_ROOT = PACKAGE_ROOT / "output"


def build_summary(
    study_input: StudyInput,
    ctg: dict[str, Any],
    expanded: ExpandedTerritory,
    direction_grid: DirectionGridResult,
    smoothing: Any | None,
) -> dict[str, Any]:
    geometry_result = ctg["geometry_result"]
    graph_info = ctg["topology_result"].graph_info
    lane_info = tuple(ctg["coverage_lane_sweep_info"].coverage_lane_info)
    active_lanes = tuple(lane for lane in lane_info if bool(lane.get("active", False)))
    return {
        "project_dir": str(study_input.project_dir),
        "project_name": study_input.project_dir.name,
        "area_id": int(study_input.area.area_id),
        "area_name": str(study_input.area.name),
        "resolution_m_per_px": float(study_input.map_resolution),
        "start_point_px": [int(study_input.start_point_px[0]), int(study_input.start_point_px[1])],
        "boundary_smoothing": dict((geometry_result.debug_info or {}).get("boundary_smoothing", {"enabled": False})),
        "geometry_crop_box_px": list(geometry_result.crop_box_px),
        "node_count": int(len(graph_info.nodes)),
        "edge_count": int(len(graph_info.edges)),
        "coverage_lane_count": int(len(lane_info)),
        "active_lane_count": int(len(active_lanes)),
        "territory_pixel_count_by_edge": {
            str(int(lane.get("source_edge_id", -1))): int(len(lane.get("territory_pixels", ())))
            for lane in active_lanes
        },
        "expanded_territory": {
            "method": "outer_path_territory_seed_with_dead_end_fill",
            "expanded_edge_ids": [int(edge_id) for edge_id in expanded.expanded_edge_ids],
            "pixel_count_by_edge": {
                str(int(edge_id)): int(pixel_count)
                for edge_id, pixel_count in expanded.pixel_count_by_edge.items()
            },
        },
        "direction_grid": direction_grid.debug_info,
        "junction_polygon_count": int(sum(1 for node in graph_info.nodes if len(tuple(node.polygon_vertices_rc or ())) >= 3)),
        "free_pixel_count": int(np.count_nonzero(np.asarray(geometry_result.free_mask) > 0)),
        "region_pixel_count": int(np.count_nonzero(np.asarray(geometry_result.region_mask) > 0)),
        "validation": {
            "geometry": geometry_result.validation_info,
            "junction": ctg["junction_result"].validation_info,
            "topology": ctg["topology_result"].validation_info,
            "coverage_lane_generation": ctg["coverage_lane_sweep_info"].validation_info,
        },
    }


def local_start_pixel(study_input: StudyInput, geometry_result: Any) -> tuple[int, int]:
    crop_box = tuple(int(value) for value in tuple(geometry_result.crop_box_px))
    if len(crop_box) != 4:
        return int(study_input.start_point_px[0]), int(study_input.start_point_px[1])
    row0, col0, _row1, _col1 = crop_box
    start_x, start_y = study_input.start_point_px
    return int(round(float(start_x) - float(col0))), int(round(float(start_y) - float(row0)))


def nearest_free_start(free_mask: np.ndarray, preferred_xy: tuple[int, int]) -> tuple[int, int] | None:
    free = np.asarray(free_mask) > 0
    if not np.any(free):
        return None
    x, y = int(preferred_xy[0]), int(preferred_xy[1])
    if 0 <= y < free.shape[0] and 0 <= x < free.shape[1] and free[y, x]:
        return x, y
    rows, cols = np.where(free)
    distances = (cols.astype(np.int64) - int(x)) ** 2 + (rows.astype(np.int64) - int(y)) ** 2
    index = int(np.argmin(distances))
    return int(cols[index]), int(rows[index])


def path_length_px(path_pixels: list[tuple[float, float]] | tuple[tuple[float, float], ...]) -> float:
    if len(path_pixels) < 2:
        return 0.0
    return float(
        sum(
            float(np.hypot(float(curr[0]) - float(prev[0]), float(curr[1]) - float(prev[1])))
            for prev, curr in zip(path_pixels, path_pixels[1:])
        )
    )


def copy_path_overlay(artifacts_dir: Path, output_dir: Path, target_name: str) -> str:
    source_overlay = artifacts_dir / "path_overlay.png"
    target_overlay = output_dir / target_name
    if source_overlay.is_file():
        shutil.copyfile(source_overlay, target_overlay)
    return str(target_overlay) if target_overlay.is_file() else ""


def write_path_comparison_image(axis_overlay_path: str, baseline_overlay_path: str, output_dir: Path) -> str:
    return write_multi_path_comparison_image(
        (
            ("baseline", baseline_overlay_path),
            ("axis prior", axis_overlay_path),
        ),
        output_dir / "11_shelf_aware_path_comparison.png",
    )


def write_multi_path_comparison_image(overlays: tuple[tuple[str, str], ...], target: Path) -> str:
    loaded: list[tuple[str, np.ndarray]] = []
    for label, overlay_path in overlays:
        if not overlay_path:
            continue
        image = cv2.imread(overlay_path, cv2.IMREAD_COLOR)
        if image is not None:
            loaded.append((label, image))
    if len(loaded) < 2:
        return ""
    height = max(image.shape[0] for _, image in loaded)
    width = max(image.shape[1] for _, image in loaded)

    def pad(image: np.ndarray, label: str) -> np.ndarray:
        canvas = np.zeros((height, width, 3), dtype=np.uint8)
        canvas[: image.shape[0], : image.shape[1]] = image
        cv2.rectangle(canvas, (0, 0), (min(width, 360), 28), (245, 245, 245), -1)
        cv2.putText(canvas, label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 1, cv2.LINE_AA)
        return canvas

    comparison = np.concatenate([pad(image, label) for label, image in loaded], axis=1)
    cv2.imwrite(str(target), comparison)
    return str(target)


def run_shelf_aware_path_variant(
    *,
    study_input: StudyInput,
    geometry_result: Any,
    output_dir: Path,
    variant_dir_name: str,
    overlay_name: str,
    local_axis_direction_map: np.ndarray | None = None,
    local_axis_confidence_map: np.ndarray | None = None,
    local_edge_label_map: np.ndarray | None = None,
    blend_axis_with_local_direction: bool = False,
    ctg_guidance_enable: bool = False,
) -> dict[str, Any]:
    free_mask = np.where(np.asarray(geometry_result.free_mask) > 0, 255, 0).astype(np.uint8)
    start_xy = nearest_free_start(free_mask, local_start_pixel(study_input, geometry_result))
    planner_dir = output_dir / variant_dir_name
    if start_xy is None:
        return {
            "enabled": True,
            "success": False,
            "error_message": "no free start pixel",
            "artifacts_dir": str(planner_dir),
            "path_overlay": "",
        }
    planner = ShelfAwareCoveragePlanner(
        CoveragePlannerConfig(
            planner_mode="shelf_aware_guarded",
            coverage_width_m=float(study_input.public_config.coverage_width_m),
            robot_width_m=float(study_input.public_config.robot_width_m),
            artifacts_output_root=str(planner_dir),
            write_artifacts=True,
        )
    )
    result = planner.plan(
        free_mask,
        map_resolution=float(geometry_result.resolution_m_per_px),
        starting_position=start_xy,
        map_origin=(0.0, 0.0),
        local_axis_direction_map=local_axis_direction_map,
        local_axis_confidence_map=local_axis_confidence_map,
        local_edge_label_map=local_edge_label_map,
        blend_axis_with_local_direction=blend_axis_with_local_direction,
        ctg_guidance_enable=ctg_guidance_enable,
    )
    artifacts_dir = Path(result.artifacts_dir) if result.artifacts_dir else planner_dir
    overlay_path = copy_path_overlay(artifacts_dir, output_dir, overlay_name)
    length_px = path_length_px(tuple(result.path_pixels))
    return {
        "enabled": True,
        "success": bool(result.success),
        "error_code": int(result.error_code),
        "error_message": str(result.error_message or ""),
        "start_pixel_xy": [int(start_xy[0]), int(start_xy[1])],
        "path_pixel_point_count": int(len(result.path_pixels)),
        "path_length_px": float(length_px),
        "path_length_m": float(length_px * float(geometry_result.resolution_m_per_px)),
        "artifacts_dir": str(artifacts_dir),
        "path_overlay": overlay_path,
    }


def run_shelf_aware_path_comparison(
    study_input: StudyInput,
    geometry_result: Any,
    direction_grid: DirectionGridResult,
    expanded: ExpandedTerritory,
    output_dir: Path,
) -> dict[str, Any]:
    free_mask = np.where(np.asarray(geometry_result.free_mask) > 0, 255, 0).astype(np.uint8)
    axis_map, confidence_map = direction_grid_to_axis_maps(direction_grid, free_mask.shape)
    edge_label_map = np.asarray(expanded.labels, dtype=np.int32)
    baseline = run_shelf_aware_path_variant(
        study_input=study_input,
        geometry_result=geometry_result,
        output_dir=output_dir,
        variant_dir_name="shelf_aware_baseline",
        overlay_name="10_shelf_aware_baseline_path_overlay.png",
    )
    axis_prior = run_shelf_aware_path_variant(
        study_input=study_input,
        geometry_result=geometry_result,
        output_dir=output_dir,
        variant_dir_name="shelf_aware_axis_prior",
        overlay_name="09_shelf_aware_axis_path_overlay.png",
        local_axis_direction_map=axis_map,
        local_axis_confidence_map=confidence_map,
    )
    ctg_guided = run_shelf_aware_path_variant(
        study_input=study_input,
        geometry_result=geometry_result,
        output_dir=output_dir,
        variant_dir_name="shelf_aware_ctg_guided",
        overlay_name="12_shelf_aware_ctg_guided_path_overlay.png",
        local_edge_label_map=edge_label_map,
        ctg_guidance_enable=True,
    )
    comparison_overlay = write_path_comparison_image(
        axis_overlay_path=str(axis_prior.get("path_overlay", "")),
        baseline_overlay_path=str(baseline.get("path_overlay", "")),
        output_dir=output_dir,
    )
    guided_comparison_overlay = write_multi_path_comparison_image(
        (
            ("baseline", str(baseline.get("path_overlay", ""))),
            ("axis prior", str(axis_prior.get("path_overlay", ""))),
            ("ctg guided", str(ctg_guided.get("path_overlay", ""))),
        ),
        output_dir / "13_shelf_aware_ctg_guided_comparison.png",
    )
    return {
        "baseline": baseline,
        "axis_prior": axis_prior,
        "ctg_guided": ctg_guided,
        "comparison": {
            "path_point_delta": int(axis_prior.get("path_pixel_point_count", 0)) - int(baseline.get("path_pixel_point_count", 0)),
            "path_length_delta_m": float(axis_prior.get("path_length_m", 0.0)) - float(baseline.get("path_length_m", 0.0)),
            "ctg_guided_path_point_delta": int(ctg_guided.get("path_pixel_point_count", 0)) - int(baseline.get("path_pixel_point_count", 0)),
            "ctg_guided_path_length_delta_m": float(ctg_guided.get("path_length_m", 0.0)) - float(baseline.get("path_length_m", 0.0)),
            "comparison_overlay": comparison_overlay,
            "ctg_guided_comparison_overlay": guided_comparison_overlay,
        },
    }


def run_territory_study_area(
    project_path: Path,
    *,
    area_id: int | None,
    output_dir: Path,
    apply_boundary_smoothing: bool = True,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    study_input = build_study_input(project_path, area_id, output_dir)
    ctg = extract_ctg_territory(study_input, apply_boundary_smoothing=apply_boundary_smoothing)
    smoothing = ctg.get("boundary_smoothing")
    geometry_result = ctg["geometry_result"]
    graph_info = ctg["topology_result"].graph_info
    lane_info = tuple(ctg["coverage_lane_sweep_info"].coverage_lane_info)
    expanded = expand_dead_end_territories(geometry_result, graph_info, lane_info)
    direction_grid = build_direction_grid(
        geometry_result=geometry_result,
        graph_info=graph_info,
        expanded=expanded,
    )
    write_visualizations(study_input, ctg, expanded, direction_grid, output_dir)
    shelf_path_comparison = run_shelf_aware_path_comparison(study_input, geometry_result, direction_grid, expanded, output_dir)
    (output_dir / "direction_grid.json").write_text(
        json.dumps(
            {
                "summary": direction_grid.debug_info,
                "samples": list(direction_grid.samples),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    summary = build_summary(study_input, ctg, expanded, direction_grid, smoothing)
    summary["shelf_aware_baseline"] = shelf_path_comparison["baseline"]
    summary["shelf_aware_axis_prior"] = shelf_path_comparison["axis_prior"]
    summary["shelf_aware_ctg_guided"] = shelf_path_comparison["ctg_guided"]
    summary["shelf_aware_path_comparison"] = shelf_path_comparison["comparison"]
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_dir


def run_fourfloor_territory_study(
    project_dir: str | Path = DEFAULT_PROJECT_DIR,
    *,
    area_id: int | None = None,
    output_root: str | Path | None = None,
    apply_boundary_smoothing: bool = True,
) -> Path:
    project_path = Path(project_dir).expanduser().resolve()
    root = Path(output_root).expanduser().resolve() if output_root is not None else DEFAULT_OUTPUT_ROOT
    run_dir = root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    run_dir.mkdir(parents=True, exist_ok=True)

    return run_territory_study_area(
        project_path,
        area_id=area_id,
        output_dir=run_dir,
        apply_boundary_smoothing=apply_boundary_smoothing,
    )


def run_project_territory_study(
    project_dir: str | Path,
    *,
    output_root: str | Path | None = None,
    apply_boundary_smoothing: bool = True,
) -> Path:
    return run_projects_territory_study(
        [project_dir],
        output_root=output_root,
        apply_boundary_smoothing=apply_boundary_smoothing,
    )


def run_projects_territory_study(
    project_dirs: list[str | Path] | tuple[str | Path, ...],
    *,
    output_root: str | Path | None = None,
    apply_boundary_smoothing: bool = True,
) -> Path:
    if not project_dirs:
        raise ValueError("project_dirs must not be empty")
    root = Path(output_root).expanduser().resolve() if output_root is not None else DEFAULT_OUTPUT_ROOT
    run_dir = root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    run_dir.mkdir(parents=True, exist_ok=True)
    completed_projects: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    for project_dir in project_dirs:
        project_path = Path(project_dir).expanduser().resolve()
        _map_data, annotations = load_fourfloor_project(project_path)
        area_ids = [int(area.area_id) for area in sorted(annotations.area_labels, key=lambda item: int(item.area_id))]
        project_records: list[dict[str, Any]] = []
        for area_id in area_ids:
            area_dir = run_dir / f"{project_path.name}_area_{area_id}"
            run_territory_study_area(
                project_path,
                area_id=area_id,
                output_dir=area_dir,
                apply_boundary_smoothing=apply_boundary_smoothing,
            )
            summary = json.loads((area_dir / "summary.json").read_text(encoding="utf-8"))
            record = {
                "project_name": project_path.name,
                "area_id": int(area_id),
                "output_dir": str(area_dir),
                "node_count": int(summary["node_count"]),
                "edge_count": int(summary["edge_count"]),
                "direction_sample_count": int(summary["direction_grid"]["direction_sample_count"]),
            }
            completed.append(record)
            project_records.append(record)
        completed_projects.append(
            {
                "project_dir": str(project_path),
                "project_name": project_path.name,
                "area_count": int(len(area_ids)),
                "areas": project_records,
            }
        )
    (run_dir / "project_summary.json").write_text(
        json.dumps(
            {
                "project_count": int(len(completed_projects)),
                "projects": completed_projects,
                "area_count": int(len(completed)),
                "areas": completed,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return run_dir
