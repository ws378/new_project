from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import time
from pathlib import Path
import sys
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.coverage_planning import (
    CoveragePlannerConfig,
    CoveragePlanningRequest,
    run_formal_planner_request,
)
from algorithms.coverage_planning.preprocessing import preprocess_total_map
from algorithms.coverage_planning.routing.adapters.shelf_aware_ctg_auxiliary import (
    build_shelf_aware_ctg_auxiliary_maps,
)
from maptools.models.annotations import Annotations
from maptools.models.map_data import MapData
from maptools.models.project import ProjectManager
from maptools.utils.coverage_repo_export import (
    build_area_region_mask,
    build_selected_area_planning_map,
    build_total_free_map,
    world_to_image_pixel,
)


def array_hash(value: np.ndarray) -> str:
    array = np.asarray(value)
    return hashlib.sha256(array.tobytes()).hexdigest()


def path_hash(points: tuple[tuple[float, float], ...]) -> str:
    rounded = [(round(float(x), 3), round(float(y), 3)) for x, y in points]
    payload = json.dumps(rounded, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def path_length_px(points: tuple[tuple[float, float], ...]) -> float:
    if len(points) < 2:
        return 0.0
    return float(
        sum(
            float(np.hypot(float(x2) - float(x1), float(y2) - float(y1)))
            for (x1, y1), (x2, y2) in zip(points, points[1:])
        )
    )


def load_project(project_dir: Path) -> tuple[MapData, Annotations]:
    map_data = MapData()
    annotations = Annotations()
    manager = ProjectManager(map_data, annotations)
    with contextlib.redirect_stdout(io.StringIO()):
        loaded = manager.load_project(str(project_dir))
    if not loaded:
        raise ValueError(f"failed to load project: {project_dir}")
    if map_data.metadata is None:
        raise ValueError(f"project has no map metadata: {project_dir}")
    return map_data, annotations


def centroid_start_px(map_data: MapData, area: Any) -> tuple[int, int]:
    assert map_data.metadata is not None
    resolution = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])
    height = int(map_data.height)
    center_x = sum(float(point[0]) for point in area.polygon) / len(area.polygon)
    center_y = sum(float(point[1]) for point in area.polygon) / len(area.polygon)
    return world_to_image_pixel(center_x, center_y, resolution, origin_x, origin_y, height)


def build_request(
    *,
    map_data: MapData,
    total_free_map: np.ndarray,
    area: Any,
    config: CoveragePlannerConfig,
) -> CoveragePlanningRequest:
    assert map_data.metadata is not None
    resolution = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])
    height = int(map_data.height)
    region_mask = build_area_region_mask(map_data, area)
    selected_area_map = build_selected_area_planning_map(total_free_map, region_mask)
    prepared_map = preprocess_total_map(
        raw_map=selected_area_map,
        resolution_m_per_px=resolution,
        open_kernel_m=float(config.open_kernel_m),
        obstacle_expand_m=float(config.obstacle_expand_m),
        region_mask=region_mask,
    )
    region_polygon_px = tuple(
        world_to_image_pixel(float(wx), float(wy), resolution, origin_x, origin_y, height)
        for wx, wy in area.polygon
    )
    return CoveragePlanningRequest(
        prepared_map=prepared_map,
        map_resolution=resolution,
        starting_position_px=centroid_start_px(map_data, area),
        map_origin_xy=(origin_x, origin_y),
        region_mask=region_mask,
        region_polygon_px=region_polygon_px,
        map_yaml_path=Path(map_data.yaml_path) if map_data.yaml_path else None,
        public_config=config,
    )


def build_config() -> CoveragePlannerConfig:
    config = CoveragePlannerConfig(
        planner_mode="shelf_aware_guarded",
        coverage_width_m=0.6,
        robot_width_m=0.4,
        open_kernel_m=0.6,
        obstacle_expand_m=0.6,
        shelf_ctg_auxiliary_enable=True,
        write_artifacts=False,
    )
    if hasattr(config, "shelf_ctg_auxiliary_build_sweeps"):
        config.shelf_ctg_auxiliary_build_sweeps = False
    return config


def collect_project_baseline(project_dir: Path) -> list[dict[str, Any]]:
    map_data, annotations = load_project(project_dir)
    total_free_map = build_total_free_map(map_data, annotations)
    config = build_config()
    items: list[dict[str, Any]] = []
    for area in sorted(annotations.area_labels, key=lambda item: int(item.area_id)):
        request = build_request(
            map_data=map_data,
            total_free_map=total_free_map,
            area=area,
            config=config,
        )
        aux_start = time.perf_counter()
        aux = build_shelf_aware_ctg_auxiliary_maps(request)
        aux_elapsed_s = time.perf_counter() - aux_start
        plan_start = time.perf_counter()
        result = run_formal_planner_request(request, "shelf_aware_guarded")
        plan_elapsed_s = time.perf_counter() - plan_start
        points = tuple((float(x), float(y)) for x, y in result.path_pixels)
        items.append(
            {
                "area_id": int(area.area_id),
                "area_name": str(area.name),
                "success": bool(result.success),
                "error": str(result.error_message or ""),
                "point_count": int(len(points)),
                "path_length_px": round(path_length_px(points), 3),
                "path_hash": path_hash(points),
                "edge_label_hash": array_hash(aux.edge_label_map),
                "junction_label_hash": array_hash(aux.junction_label_map),
                "graph_node_count": int(aux.debug_info.get("graph_node_count", -1)),
                "graph_edge_count": int(aux.debug_info.get("graph_edge_count", -1)),
                "coverage_lane_sweeps_built": bool(aux.debug_info.get("coverage_lane_sweeps_built", False)),
                "reasons": list(result.diagnostics.reasons),
                "warnings": list(result.diagnostics.warnings),
                "timing": {
                    "aux_elapsed_s": round(aux_elapsed_s, 4),
                    "plan_elapsed_s": round(plan_elapsed_s, 4),
                },
            }
        )
    return items


def compare_baselines(expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> list[str]:
    stable_keys = (
        "area_id",
        "area_name",
        "success",
        "error",
        "point_count",
        "path_length_px",
        "path_hash",
        "edge_label_hash",
        "junction_label_hash",
        "graph_node_count",
        "graph_edge_count",
    )
    failures: list[str] = []
    if len(expected) != len(actual):
        failures.append(f"area count changed: expected={len(expected)} actual={len(actual)}")
        return failures
    for expected_item, actual_item in zip(expected, actual):
        area_id = expected_item.get("area_id")
        for key in stable_keys:
            if expected_item.get(key) != actual_item.get(key):
                failures.append(
                    f"area={area_id} key={key} expected={expected_item.get(key)!r} actual={actual_item.get(key)!r}"
                )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or compare coverage semantic baseline.")
    parser.add_argument(
        "--project",
        default="examples/maptools_projects/beiguo_lanshan_0407",
        help="MapTools project directory.",
    )
    parser.add_argument("--output", help="Write baseline JSON to this path.")
    parser.add_argument("--compare", help="Compare current result with an existing baseline JSON.")
    args = parser.parse_args()

    current = collect_project_baseline(Path(args.project))
    if args.output:
        Path(args.output).write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.compare:
        expected = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        failures = compare_baselines(expected, current)
        if failures:
            for failure in failures:
                print(failure)
            raise SystemExit(1)
        print("semantic_baseline=OK")
    if not args.output and not args.compare:
        print(json.dumps(current, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
