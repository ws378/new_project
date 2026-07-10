"""批量测试 shelfAware 覆盖路径。"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import traceback
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PACKAGE_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.coverage_planning import CoveragePlanningRequest, run_formal_planner_request
from algorithms.coverage_planning.preprocessing import preprocess_total_map
from algorithms.turn_cost_coverage_research.src.diagnostics.path_diagnostics import (
    diagnose_lane_spacing,
    diagnose_local_quality,
    diagnose_path,
    diagnose_segment_crossings,
)
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
from maptools.views.coverage_dialog import coverage_dialog_config_from_values, coverage_dialog_default_values

DEFAULT_PROJECT_NAMES = (
    "beiguo_lanshan_1770397756",
    "beiguoshangcheng_floor_3",
    "fourfloor_20250923_8",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PACKAGE_ROOT / "output" / "baselines", help="输出根目录。")
    parser.add_argument("--project-name", action="append", choices=DEFAULT_PROJECT_NAMES, help="只运行指定项目，可重复。")
    parser.add_argument("--area-id", action="append", type=int, help="只运行指定 area_id，可重复；会应用到所有选中项目。")
    parser.add_argument(
        "--planner-mode",
        choices=("shelf_aware", "shelf_aware_turn_cost"),
        default="shelf_aware",
        help="正式 planner mode。默认 shelf_aware；候选补证时使用 shelf_aware_turn_cost。",
    )
    parser.add_argument("--min-coverage-ratio", type=float, default=0.90, help="shelfAware 质量守卫最小覆盖率阈值。")
    parser.add_argument("--write-artifacts", action="store_true", help="写出 planner 调试证据；默认关闭以匹配 UI 在线耗时口径。")
    parser.add_argument("--quality-guard", action="store_true", help="启用 shelfAware 质量守卫；默认关闭以匹配 UI 默认参数。")
    parser.add_argument("--ctg-auxiliary", action="store_true", help="启用 shelf/CTG 辅助图；默认关闭以避免历史保存参数污染耗时口径。")
    parser.add_argument("--readonly-quality", action="store_true", help="运行离线只读质量诊断；默认关闭，不计入在线规划耗时。")
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


def _load_area_ids(project_dir: Path, allowed_area_ids: set[int] | None) -> list[int]:
    payload = json.loads((project_dir / "areas.json").read_text(encoding="utf-8"))
    area_ids = sorted(int(item["area_id"]) for item in payload.get("areas", []))
    if allowed_area_ids is not None:
        area_ids = [area_id for area_id in area_ids if area_id in allowed_area_ids]
    return area_ids


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


def _project_config(
    project_dir: Path,
    *,
    planner_mode: str,
    min_coverage_ratio: float,
    quality_guard: bool,
    ctg_auxiliary: bool,
    write_artifacts: bool,
):
    saved_values = load_coverage_planner_params(project_dir)
    values = saved_values if saved_values is not None else coverage_dialog_default_values()
    config = coverage_dialog_config_from_values(values)
    return replace(
        config,
        planner_mode=str(planner_mode),
        shelf_ctg_auxiliary_enable=bool(ctg_auxiliary),
        shelf_quality_guard_enable=bool(quality_guard),
        shelf_quality_guard_min_coverage_ratio=float(min_coverage_ratio),
        write_artifacts=bool(write_artifacts),
    ), saved_values is not None


def _copy_if_exists(source_dir: Path, filename: str, target: Path) -> str:
    source = source_dir / filename
    if not source.is_file():
        return ""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return str(target)


def _readonly_quality_metrics(
    *,
    path_pixels: list[list[float]],
    prepared_map,
    resolution_m_per_px: float,
    coverage_width_m: float,
) -> dict[str, Any]:
    if not path_pixels:
        return {}
    coverage_width_px = max(1, int(round(float(coverage_width_m) / float(resolution_m_per_px))))
    points = [(float(point[0]), float(point[1])) for point in path_pixels]
    local_quality = diagnose_local_quality(
        points,
        prepared_map,
        coverage_width_px=coverage_width_px,
    )
    diagnostics = diagnose_path(
        points,
        resolution_m_per_px=float(resolution_m_per_px),
        coverage_width_px=coverage_width_px,
    )
    lane_spacing = diagnose_lane_spacing(
        points,
        coverage_width_px=coverage_width_px,
        resolution_m_per_px=float(resolution_m_per_px),
    )
    segment_crossing = diagnose_segment_crossings(
        points,
        coverage_width_px=coverage_width_px,
    )
    return {
        "coverage_width_px": int(coverage_width_px),
        "narrow_coverage_ratio": float(local_quality.narrow_coverage_ratio),
        "turn_hotspot_count": int(len(diagnostics.turn_hotspots)),
        "lane_over_dense_count": int(lane_spacing.over_dense_count),
        "lane_over_sparse_count": int(lane_spacing.over_sparse_count),
        "lane_spacing_issue_count": int(lane_spacing.over_dense_count + lane_spacing.over_sparse_count),
        "segment_crossing_count": int(segment_crossing.crossing_count),
    }


def _run_one(
    *,
    project_name: str,
    project_dir: Path,
    area_id: int,
    run_dir: Path,
    all_final_dir: Path,
    planner_mode: str,
    min_coverage_ratio: float,
    quality_guard: bool,
    ctg_auxiliary: bool,
    write_artifacts: bool,
    readonly_quality: bool,
) -> dict[str, Any]:
    area_dir = run_dir / "areas" / f"{project_name}_area_{int(area_id)}"
    preprocess_root = area_dir / "preprocess"
    planner_root = area_dir / "planner"
    area_dir.mkdir(parents=True, exist_ok=True)
    try:
        map_data, annotations = _load_project(project_dir)
        area = _select_area(annotations, int(area_id))
        config, used_saved_params = _project_config(
            project_dir,
            planner_mode=planner_mode,
            min_coverage_ratio=min_coverage_ratio,
            quality_guard=quality_guard,
            ctg_auxiliary=ctg_auxiliary,
            write_artifacts=write_artifacts,
        )
        config = replace(config, artifacts_output_root=str(planner_root))
        assert map_data.metadata is not None
        resolution = float(map_data.metadata.resolution)
        total_free_map = build_total_free_map(map_data, annotations)
        region_mask = build_area_region_mask(map_data, area)
        selected_area_planning_map = build_selected_area_planning_map(total_free_map, region_mask)
        prepared_map = preprocess_total_map(
            raw_map=selected_area_planning_map,
            resolution_m_per_px=resolution,
            open_kernel_m=float(config.open_kernel_m),
            obstacle_expand_m=float(config.obstacle_expand_m),
            region_mask=region_mask,
            output_root=preprocess_root,
        )
        request = CoveragePlanningRequest(
            prepared_map=prepared_map,
            map_resolution=resolution,
            starting_position_px=_area_start_px(map_data, area),
            map_origin_xy=(float(map_data.metadata.origin[0]), float(map_data.metadata.origin[1])),
            region_mask=region_mask,
            region_polygon_px=_area_polygon_px(map_data, area),
            map_yaml_path=Path(map_data.yaml_path) if map_data.yaml_path else None,
            public_config=config,
            artifacts_output_root=planner_root,
        )
        result = run_formal_planner_request(request, planner_mode)
        guard_meta: dict[str, Any] = {}
        ctg_meta: dict[str, Any] = {}
        if result.diagnostics.runtime is not None:
            guard_meta = dict(result.diagnostics.runtime.coverage_meta.get("shelf_quality_guard", {}))
            ctg_meta = dict(result.diagnostics.runtime.coverage_meta.get("shelf_ctg_auxiliary", {}))
        path_pixels = [[float(x), float(y)] for x, y in result.path_pixels]
        (area_dir / "path_pixels.json").write_text(json.dumps(path_pixels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        readonly_quality_metrics = (
            _readonly_quality_metrics(
                path_pixels=path_pixels,
                prepared_map=prepared_map,
                resolution_m_per_px=resolution,
                coverage_width_m=float(config.coverage_width_m),
            )
            if readonly_quality
            else {}
        )
        artifacts_dir = Path(result.diagnostics.artifacts_dir) if result.diagnostics.artifacts_dir else Path()
        coverage_image_name = f"{planner_mode}_coverage.png"
        overlay_path = _copy_if_exists(artifacts_dir, "path_overlay.png", area_dir / coverage_image_name)
        all_final_path = ""
        if overlay_path:
            all_final_path = _copy_if_exists(
                area_dir,
                coverage_image_name,
                all_final_dir / f"{planner_mode}_coverage_{project_name}_area{int(area_id)}.png",
            )
        record = {
            "planner_mode": planner_mode,
            "project_name": project_name,
            "area_id": int(area_id),
            "status": "success" if result.success and bool(result.path_pixels) else "failed",
            "error_message": result.error_message,
            "used_saved_params": bool(used_saved_params),
            "point_count": len(result.path_pixels),
            "coverage_ratio": guard_meta.get("coverage_ratio"),
            "narrow_coverage_ratio": readonly_quality_metrics.get("narrow_coverage_ratio"),
            "long_jump_count": guard_meta.get("long_jump_count"),
            "turn_hotspot_count": readonly_quality_metrics.get("turn_hotspot_count"),
            "infeasible_segment_count": guard_meta.get("infeasible_segment_count"),
            "total_turn_angle_deg": guard_meta.get("total_turn_angle_deg"),
            "length_px": guard_meta.get("length_px"),
            "lane_over_dense_count": readonly_quality_metrics.get("lane_over_dense_count"),
            "lane_over_sparse_count": readonly_quality_metrics.get("lane_over_sparse_count"),
            "lane_spacing_issue_count": readonly_quality_metrics.get("lane_spacing_issue_count"),
            "segment_crossing_count": readonly_quality_metrics.get("segment_crossing_count"),
            "readonly_quality_metrics": readonly_quality_metrics,
            "quality_guard_status": guard_meta.get("status"),
            "quality_guard_warnings": guard_meta.get("warnings", []),
            "planner_reasons": list(result.diagnostics.reasons),
            "planner_warnings": list(result.diagnostics.warnings),
            "ctg_auxiliary": ctg_meta,
            "area_run_dir": str(area_dir),
            "overlay_path": overlay_path,
            "all_final_overlay_path": all_final_path,
            "planner_artifacts_dir": str(artifacts_dir) if artifacts_dir else "",
        }
        (area_dir / "summary.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return record
    except Exception as exc:
        record = {
            "project_name": project_name,
            "area_id": int(area_id),
            "status": "failed",
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
            "area_run_dir": str(area_dir),
        }
        (area_dir / "summary.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return record


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fieldnames = (
        "planner_mode",
        "project_name",
        "area_id",
        "status",
        "used_saved_params",
        "point_count",
        "coverage_ratio",
        "narrow_coverage_ratio",
        "long_jump_count",
        "turn_hotspot_count",
        "infeasible_segment_count",
        "total_turn_angle_deg",
        "length_px",
        "lane_over_dense_count",
        "lane_over_sparse_count",
        "lane_spacing_issue_count",
        "segment_crossing_count",
        "quality_guard_status",
        "quality_guard_warnings",
        "ctg_auxiliary_enabled",
        "ctg_auxiliary_reason",
        "planner_warnings",
        "error_message",
        "area_run_dir",
        "all_final_overlay_path",
    )
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["quality_guard_warnings"] = "|".join(str(item) for item in record.get("quality_guard_warnings", []))
            ctg_meta = record.get("ctg_auxiliary", {}) or {}
            row["ctg_auxiliary_enabled"] = ctg_meta.get("enabled", "")
            row["ctg_auxiliary_reason"] = ctg_meta.get("reason", "")
            row["planner_warnings"] = "|".join(str(item) for item in record.get("planner_warnings", []))
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def main() -> None:
    args = parse_args()
    planner_mode = str(args.planner_mode)
    run_dir = Path(args.output_root).expanduser().resolve() / (
        "run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + f"_{planner_mode}_all_areas"
    )
    all_final_dir = run_dir / f"全部最终{planner_mode}_coverage"
    run_dir.mkdir(parents=True, exist_ok=True)
    all_final_dir.mkdir(parents=True, exist_ok=True)
    project_names = tuple(args.project_name) if args.project_name else DEFAULT_PROJECT_NAMES
    allowed_area_ids = set(int(value) for value in args.area_id) if args.area_id else None
    records: list[dict[str, Any]] = []
    for project_name in project_names:
        project_dir = REPO_ROOT / "examples" / "maptools_projects" / project_name
        for area_id in _load_area_ids(project_dir, allowed_area_ids):
            record = _run_one(
                project_name=project_name,
                project_dir=project_dir,
                area_id=int(area_id),
                run_dir=run_dir,
                all_final_dir=all_final_dir,
                planner_mode=planner_mode,
                min_coverage_ratio=float(args.min_coverage_ratio),
                quality_guard=bool(args.quality_guard),
                ctg_auxiliary=bool(args.ctg_auxiliary),
                write_artifacts=bool(args.write_artifacts),
                readonly_quality=bool(args.readonly_quality),
            )
            records.append(record)
            print(f"{project_name} area {area_id}: {record['status']}")
            sys.stdout.flush()
    payload = {
        "runner": "run_shelf_aware_all_areas",
        "planner_mode": planner_mode,
        "project_names": list(project_names),
        "area_count": len(records),
        "success_count": sum(1 for item in records if item.get("status") == "success"),
        "failed_count": sum(1 for item in records if item.get("status") != "success"),
        "min_coverage_ratio": float(args.min_coverage_ratio),
        "quality_guard": bool(args.quality_guard),
        "ctg_auxiliary": bool(args.ctg_auxiliary),
        "write_artifacts": bool(args.write_artifacts),
        "readonly_quality": bool(args.readonly_quality),
        "areas": records,
        "artifacts": {
            "summary": str(run_dir / "summary.json"),
            "summary_csv": str(run_dir / f"{planner_mode}批量区域指标.csv"),
            "all_final_overlays": str(all_final_dir),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(run_dir / f"{planner_mode}批量区域指标.csv", records)
    print(run_dir)
    if payload["failed_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
