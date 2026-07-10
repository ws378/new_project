from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from algorithms.coverage_planning import build_coverage_planning_request_configs
from algorithms.coverage_planning.preprocessing import preprocess_total_map
from maptools.models.annotations import Annotations, AreaLabel
from maptools.models.map_data import MapData
from maptools.models.project import ProjectManager
from maptools.utils.coverage_repo_export import build_area_region_mask, build_total_free_map, world_to_image_pixel


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]
DEFAULT_PROJECT_DIR = REPO_ROOT / "examples" / "maptools_projects" / "fourfloor"


@dataclass(frozen=True)
class StudyInput:
    project_dir: Path
    area: AreaLabel
    prepared_map: np.ndarray
    region_mask: np.ndarray
    map_resolution: float
    map_origin_xy: tuple[float, float]
    start_point_px: tuple[int, int]
    public_config: Any
    private_config: Any


def load_maptools_project(project_dir: Path) -> tuple[MapData, Annotations]:
    map_data = MapData()
    annotations = Annotations()
    manager = ProjectManager(map_data, annotations)
    if not manager.load_project(str(project_dir)):
        raise ValueError(f"failed to load maptools project: {project_dir}")
    if map_data.metadata is None or map_data.grid_map is None:
        raise ValueError(f"project has no loaded map: {project_dir}")
    return map_data, annotations


def select_area(annotations: Annotations, area_id: int | None) -> AreaLabel:
    areas = sorted(annotations.area_labels, key=lambda item: int(item.area_id))
    if not areas:
        raise ValueError("project has no area labels")
    if area_id is None:
        return areas[0]
    for area in areas:
        if int(area.area_id) == int(area_id):
            return area
    raise ValueError(f"area_id={area_id} not found")


def build_default_planner_configs() -> tuple[Any, Any]:
    planner_config = {
        "planner_mode": "channel_topology_graph",
        "open_kernel_m": 0.6,
        "obstacle_expand_m": 0.6,
        "coverage_width_m": 0.55,
        "robot_width_m": 0.55,
        "free_node_min_clearance_m": 0.35,
    }
    public_config, _, private_config = build_coverage_planning_request_configs(planner_config)
    return public_config, private_config


def area_centroid_start_px(map_data: MapData, area: AreaLabel) -> tuple[int, int]:
    if map_data.metadata is None:
        raise ValueError("map metadata is missing")
    resolution = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])
    height = int(map_data.height)
    centroid_x = sum(float(point[0]) for point in area.polygon) / len(area.polygon)
    centroid_y = sum(float(point[1]) for point in area.polygon) / len(area.polygon)
    start_x, start_y = world_to_image_pixel(centroid_x, centroid_y, resolution, origin_x, origin_y, height)
    return int(start_x), int(start_y)


def build_study_input(project_dir: Path, area_id: int | None, output_root: Path) -> StudyInput:
    map_data, annotations = load_maptools_project(project_dir)
    area = select_area(annotations, area_id)
    total_free_map = build_total_free_map(map_data, annotations)
    region_mask = build_area_region_mask(map_data, area)
    public_config, private_config = build_default_planner_configs()

    if map_data.metadata is None:
        raise ValueError("map metadata is missing")
    resolution = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])

    return StudyInput(
        project_dir=project_dir,
        area=area,
        prepared_map=preprocess_total_map(
            raw_map=total_free_map,
            resolution_m_per_px=resolution,
            open_kernel_m=float(public_config.open_kernel_m),
            obstacle_expand_m=float(public_config.obstacle_expand_m),
            output_root=output_root,
        ),
        region_mask=region_mask,
        map_resolution=resolution,
        map_origin_xy=(origin_x, origin_y),
        start_point_px=area_centroid_start_px(map_data, area),
        public_config=public_config,
        private_config=private_config,
    )

