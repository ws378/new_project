from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.coverage_planning import CoveragePlanningRequest, run_formal_planner_request
from algorithms.coverage_planning.preprocessing import preprocess_total_map
from maptools.models.annotations import Annotations
from maptools.models.map_data import MapData
from maptools.models.project import ProjectManager
from maptools.utils.coverage_planner_params import load_coverage_planner_params
from maptools.utils.coverage_repo_export import (
    build_area_region_mask,
    build_selected_area_planning_map,
    build_total_free_map,
    world_to_image_pixel,
)
from maptools.views.coverage_dialog import coverage_dialog_config_from_values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 UI-like shelfAware+CTG，但实验性关闭孤立跳变点治理。")
    parser.add_argument("--project-dir", required=True, help="MapTools 项目目录。")
    parser.add_argument("--area-id", type=int, required=True, help="区域 ID。")
    parser.add_argument(
        "--output-root",
        default="algorithms/turn_cost_coverage_research/output",
        help="实验输出根目录。",
    )
    return parser.parse_args()


def _load_project(project_dir: Path) -> tuple[MapData, Annotations]:
    map_data = MapData()
    annotations = Annotations()
    manager = ProjectManager(map_data, annotations)
    if not manager.load_project(str(project_dir)):
        raise ValueError(f"failed to load maptools project: {project_dir}")
    if map_data.metadata is None or map_data.grid_map is None:
        raise ValueError(f"project has no loaded map: {project_dir}")
    return map_data, annotations


def _select_area(annotations: Annotations, area_id: int):
    for area in annotations.area_labels:
        if int(area.area_id) == int(area_id):
            return area
    raise ValueError(f"area_id={area_id} not found")


def _area_start_px(map_data: MapData, area: Any) -> tuple[int, int]:
    assert map_data.metadata is not None
    centroid_x = sum(float(point[0]) for point in area.polygon) / len(area.polygon)
    centroid_y = sum(float(point[1]) for point in area.polygon) / len(area.polygon)
    return world_to_image_pixel(
        centroid_x,
        centroid_y,
        float(map_data.metadata.resolution),
        float(map_data.metadata.origin[0]),
        float(map_data.metadata.origin[1]),
        int(map_data.height),
    )


def _area_polygon_px(map_data: MapData, area: Any) -> tuple[tuple[int, int], ...]:
    assert map_data.metadata is not None
    return tuple(
        world_to_image_pixel(
            float(wx),
            float(wy),
            float(map_data.metadata.resolution),
            float(map_data.metadata.origin[0]),
            float(map_data.metadata.origin[1]),
            int(map_data.height),
        )
        for wx, wy in area.polygon
    )


def _copy_artifact_if_exists(source_dir: Path, filename: str, target_dir: Path) -> str:
    source = source_dir / filename
    if not source.is_file():
        return ""
    target = target_dir / filename
    shutil.copy2(source, target)
    return str(target)


def main() -> None:
    args = parse_args()
    project_dir = Path(args.project_dir).expanduser().resolve()
    map_data, annotations = _load_project(project_dir)
    area = _select_area(annotations, int(args.area_id))
    saved_values = load_coverage_planner_params(project_dir)
    if saved_values is None:
        raise ValueError(f"project has no coverage_planner_params.json: {project_dir}")

    base_config = coverage_dialog_config_from_values(saved_values)
    experiment_config = replace(
        base_config,
        planner_mode="shelf_aware",
        shelf_ctg_auxiliary_enable=True,
        isolated_jump_cleanup_enable=False,
        write_artifacts=True,
    )

    run_dir = (
        Path(args.output_root).expanduser().resolve()
        / (
            "run_"
            + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            + f"_ui_shelf_no_isolated_jump_area{int(args.area_id)}"
        )
    )
    preprocess_root = run_dir / "preprocess"
    planner_root = run_dir / "planner"
    run_dir.mkdir(parents=True, exist_ok=True)

    assert map_data.metadata is not None
    resolution = float(map_data.metadata.resolution)
    origin = (float(map_data.metadata.origin[0]), float(map_data.metadata.origin[1]))
    total_free_map = build_total_free_map(map_data, annotations)
    region_mask = build_area_region_mask(map_data, area)
    selected_area_planning_map = build_selected_area_planning_map(total_free_map, region_mask)
    prepared_map = preprocess_total_map(
        raw_map=selected_area_planning_map,
        resolution_m_per_px=resolution,
        open_kernel_m=float(experiment_config.open_kernel_m),
        obstacle_expand_m=float(experiment_config.obstacle_expand_m),
        region_mask=region_mask,
        output_root=preprocess_root,
    )

    request = CoveragePlanningRequest(
        prepared_map=prepared_map,
        map_resolution=resolution,
        starting_position_px=_area_start_px(map_data, area),
        map_origin_xy=origin,
        region_mask=region_mask,
        region_polygon_px=_area_polygon_px(map_data, area),
        map_yaml_path=Path(map_data.yaml_path) if map_data.yaml_path else None,
        public_config=replace(experiment_config, artifacts_output_root=str(planner_root)),
        artifacts_output_root=planner_root,
    )
    result = run_formal_planner_request(request, "shelf_aware")
    if not result.success or not result.path_pixels:
        payload = result.to_summary_dict()
        payload["experiment"] = {
            "isolated_jump_cleanup_disabled_for_experiment": True,
            "saved_project_params_used": True,
        }
        (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(f"coverage planning failed: {result.error_message}")

    path_pixels = [[float(x), float(y)] for x, y in result.path_pixels]
    (run_dir / "path_pixels.json").write_text(json.dumps(path_pixels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifacts_dir = Path(result.diagnostics.artifacts_dir) if result.diagnostics.artifacts_dir else Path()
    copied_overlay = _copy_artifact_if_exists(artifacts_dir, "path_overlay.png", run_dir)
    copied_jump_cleanup = _copy_artifact_if_exists(artifacts_dir, "isolated_jump_cleanup.json", run_dir)
    copied_jump_segments = _copy_artifact_if_exists(artifacts_dir, "path_jump_segments_pixels.json", run_dir)
    copied_semantic_path = _copy_artifact_if_exists(artifacts_dir, "semantic_global_path.json", run_dir)
    copied_generation_provenance = _copy_artifact_if_exists(artifacts_dir, "path_generation_provenance.json", run_dir)
    prepared_map_path = preprocess_root / "prepare_map" / "05_prepared_map.png"
    if prepared_map_path.is_file():
        image = cv2.imread(str(prepared_map_path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError(f"failed to read prepared map: {prepared_map_path}")

    payload = result.to_summary_dict()
    payload.update(
        {
            "case_group": "ui_shelf_aware_no_isolated_jump_cleanup_experiment",
            "project_dir": str(project_dir),
            "project_name": project_dir.name,
            "area_id": int(args.area_id),
            "area_name": str(getattr(area, "name", "")),
            "experiment": {
                "isolated_jump_cleanup_disabled_for_experiment": True,
                "saved_project_params_used": True,
                "ctg_auxiliary_expected_enabled": True,
                "formal_planner_migration": "不得迁入正式默认行为；只作为 turn-cost 后处理对照输入。",
            },
            "artifacts": {
                "run_dir": str(run_dir),
                "path_pixels": str(run_dir / "path_pixels.json"),
                "path_overlay": copied_overlay,
                "isolated_jump_cleanup": copied_jump_cleanup,
                "path_jump_segments_pixels": copied_jump_segments,
                "semantic_global_path": copied_semantic_path,
                "path_generation_provenance": copied_generation_provenance,
                "planner_artifacts_dir": str(artifacts_dir),
                "prepared_map": str(prepared_map_path),
            },
        }
    )
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
