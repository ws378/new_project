from __future__ import annotations

import argparse
import json
import shutil
import subprocess
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
from algorithms.coverage_planning.contracts import SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR
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
from maptools.views.coverage_dialog import coverage_dialog_config_from_values, merge_coverage_dialog_values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 UI-like shelfAware+CTG，并把覆盖节点生成切换为 turn_cost 规则网格。")
    parser.add_argument("--project-dir", required=True, help="MapTools 项目目录。")
    parser.add_argument("--area-id", type=int, required=True, help="区域 ID。")
    parser.add_argument(
        "--node-generation-mode",
        choices=("turn_cost_regular_grid", "turn_cost_repaired_grid"),
        default="turn_cost_repaired_grid",
        help="实验节点生成模式；默认使用规则网格加受控补点。",
    )
    parser.add_argument(
        "--repaired-grid-max-offset-factor",
        type=float,
        default=SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR,
        help="受控补点相对 coverage_width_px 的最大偏移倍率。",
    )
    parser.add_argument(
        "--output-root",
        default="algorithms/turn_cost_coverage_research/output",
        help="实验输出根目录。",
    )
    parser.add_argument("--skip-downstream", action="store_true", help="只生成原始 shelf 路径，不运行重连/质量守卫/诊断。")
    parser.add_argument("--batch-reconnect-passes", type=int, default=2, help="当前主线批量候选重连轮数。")
    parser.add_argument("--batch-reconnect-max-candidates", type=int, default=30, help="每轮最多尝试的候选窗口数量。")
    parser.add_argument("--batch-reconnect-max-coverage-drop-ratio", type=float, default=0.00025, help="单轮单步允许的最大覆盖率下降。")
    parser.add_argument("--batch-reconnect-max-total-coverage-drop-ratio", type=float, default=0.0005, help="单轮累计允许的最大覆盖率下降。")
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


def _run_script(script_path: Path, *script_args: str) -> Path:
    command = [sys.executable, str(script_path), *script_args]
    completed = subprocess.run(command, check=True, text=True, capture_output=True)
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"script produced no output: {script_path}")
    return Path(lines[-1]).expanduser().resolve()


def _copy_named(source: Path, target: Path) -> str:
    if not source.is_file():
        return ""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return str(target)


def _write_experiment_bundle(
    *,
    output_root: Path,
    area_id: int,
    raw_run_dir: Path,
    batch_reconnect_run_dirs: list[Path],
    diagnostics_run_dirs: list[Path],
) -> Path:
    bundle_dir = output_root / (
        "替换覆盖节点生成实验_area"
        + str(int(area_id))
        + "_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    bundle_dir.mkdir(parents=True, exist_ok=True)
    _copy_named(raw_run_dir / "path_pixels.json", bundle_dir / "实验1_规则节点_shelf原链路_原始完整路径_pixels.json")
    _copy_named(raw_run_dir / "path_overlay.png", bundle_dir / "实验1_规则节点_shelf原链路_原始完整路径.png")
    for index, batch_dir in enumerate(batch_reconnect_run_dirs, start=1):
        _copy_named(
            batch_dir / "batch_candidate_reconnect_path_pixels.json",
            bundle_dir / f"实验1_规则节点_shelf原链路_批量候选重连第{index}轮完整路径_pixels.json",
        )
        _copy_named(
            batch_dir / "batch_candidate_reconnect_overlay.png",
            bundle_dir / f"实验1_规则节点_shelf原链路_批量候选重连第{index}轮完整路径.png",
        )
        _copy_named(
            batch_dir / "summary.json",
            bundle_dir / f"实验1_规则节点_shelf原链路_批量候选重连第{index}轮_summary.json",
        )
    if diagnostics_run_dirs:
        diagnostics_run_dir = diagnostics_run_dirs[-1]
        _copy_named(diagnostics_run_dir / "path_turn_cost_diagnostics_overlay.png", bundle_dir / "实验1_规则节点_shelf原链路_最终诊断总览.png")
        _copy_named(diagnostics_run_dir / "path_stroke_quality_overlay.png", bundle_dir / "实验1_规则节点_shelf原链路_最终路径质量.png")
        _copy_named(diagnostics_run_dir / "lane_spacing_overlay.png", bundle_dir / "实验1_规则节点_shelf原链路_最终线距诊断.png")
        _copy_named(diagnostics_run_dir / "lane_balance_overlay.png", bundle_dir / "实验1_规则节点_shelf原链路_最终左右均衡诊断.png")
        _copy_named(diagnostics_run_dir / "summary.json", bundle_dir / "实验1_规则节点_shelf原链路_最终诊断_summary.json")
    return bundle_dir


def main() -> None:
    args = parse_args()
    project_dir = Path(args.project_dir).expanduser().resolve()
    map_data, annotations = _load_project(project_dir)
    area = _select_area(annotations, int(args.area_id))
    saved_values = load_coverage_planner_params(project_dir)
    saved_project_params_used = saved_values is not None
    dialog_values = saved_values if saved_project_params_used else merge_coverage_dialog_values({})
    base_config = coverage_dialog_config_from_values(dialog_values)
    experiment_config = replace(
        base_config,
        planner_mode="shelf_aware_turn_cost",
        shelf_ctg_auxiliary_enable=True,
        shelf_node_generation_mode=str(args.node_generation_mode),
        shelf_repaired_grid_max_offset_factor=float(args.repaired_grid_max_offset_factor),
        isolated_jump_cleanup_enable=False,
        write_artifacts=True,
    )

    run_dir = (
        Path(args.output_root).expanduser().resolve()
        / (
            "run_"
            + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            + f"_ui_shelf_{str(args.node_generation_mode)}_area{int(args.area_id)}"
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
    result = run_formal_planner_request(request, "shelf_aware_turn_cost")
    if not result.success or not result.path_pixels:
        payload = result.to_summary_dict()
        payload["experiment"] = {
            "node_generation_mode": str(args.node_generation_mode),
            "repaired_grid_max_offset_factor": float(args.repaired_grid_max_offset_factor),
            "formal_planner_mode": "shelf_aware_turn_cost",
            "saved_project_params_used": bool(saved_project_params_used),
            "fallback_to_dialog_defaults": not bool(saved_project_params_used),
            "ctg_auxiliary_expected_enabled": True,
            "scope": "实验1：只替换 shelfAware 覆盖节点生成，后续路径组织仍走 shelfAware 原链路。",
        }
        (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(f"coverage planning failed: {result.error_message}")

    path_pixels = [[float(x), float(y)] for x, y in result.path_pixels]
    (run_dir / "path_pixels.json").write_text(json.dumps(path_pixels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifacts_dir = Path(result.diagnostics.artifacts_dir) if result.diagnostics.artifacts_dir else Path()
    copied_overlay = _copy_artifact_if_exists(artifacts_dir, "path_overlay.png", run_dir)
    copied_node_debug = _copy_artifact_if_exists(artifacts_dir, "node_debug_enriched.json", run_dir)
    copied_nodes_debug_png = _copy_artifact_if_exists(artifacts_dir, "nodes_debug.png", run_dir)
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
            "case_group": "ui_shelf_aware_turn_cost_node_generation_experiment",
            "project_dir": str(project_dir),
            "project_name": project_dir.name,
            "area_id": int(args.area_id),
            "area_name": str(getattr(area, "name", "")),
            "experiment": {
                "node_generation_mode": str(args.node_generation_mode),
                "repaired_grid_max_offset_factor": float(args.repaired_grid_max_offset_factor),
                "formal_planner_mode": "shelf_aware_turn_cost",
                "mode_defaults_applied": True,
                "node_generation_replacement_only": True,
                "shelf_downstream_pipeline_preserved": True,
                "isolated_jump_cleanup_disabled_for_experiment": True,
                "saved_project_params_used": bool(saved_project_params_used),
                "fallback_to_dialog_defaults": not bool(saved_project_params_used),
                "ctg_auxiliary_expected_enabled": True,
                "downstream_pipeline": "diagnostics_then_batch_candidate_reconnect",
                "batch_reconnect_passes": int(args.batch_reconnect_passes),
                "batch_reconnect_max_candidates": int(args.batch_reconnect_max_candidates),
                "batch_reconnect_max_coverage_drop_ratio": float(args.batch_reconnect_max_coverage_drop_ratio),
                "batch_reconnect_max_total_coverage_drop_ratio": float(args.batch_reconnect_max_total_coverage_drop_ratio),
                "formal_planner_migration": (
                    "节点生成 profile 可由正式 shelf_aware_turn_cost 管理；"
                    "本脚本的诊断和批量重连后处理不得迁入正式默认行为。"
                ),
            },
            "artifacts": {
                "run_dir": str(run_dir),
                "path_pixels": str(run_dir / "path_pixels.json"),
                "path_overlay": copied_overlay,
                "node_debug_enriched": copied_node_debug,
                "nodes_debug_png": copied_nodes_debug_png,
                "path_jump_segments_pixels": copied_jump_segments,
                "semantic_global_path": copied_semantic_path,
                "path_generation_provenance": copied_generation_provenance,
                "planner_artifacts_dir": str(artifacts_dir),
                "prepared_map": str(prepared_map_path),
            },
        }
    )
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.skip_downstream:
        scripts_root = Path(__file__).resolve().parents[1]
        diagnostics_scripts_dir = scripts_root / "diagnostics"
        experiments_scripts_dir = scripts_root / "experiments"
        output_root = Path(args.output_root).expanduser().resolve()
        diagnostics_dirs: list[Path] = []
        batch_reconnect_dirs: list[Path] = []
        current_path_pixels = run_dir / "path_pixels.json"
        for _ in range(max(0, int(args.batch_reconnect_passes))):
            diagnostics_dir = _run_script(
                diagnostics_scripts_dir / "run_shelf_path_turn_cost_diagnostics.py",
                "--input-run-dir",
                str(run_dir),
                "--path-pixels-path",
                str(current_path_pixels),
                "--output-root",
                str(output_root),
            )
            diagnostics_dirs.append(diagnostics_dir)
            batch_dir = _run_script(
                experiments_scripts_dir / "run_shelf_path_batch_candidate_reconnect.py",
                "--diagnostics-run-dir",
                str(diagnostics_dir),
                "--max-candidates",
                str(int(args.batch_reconnect_max_candidates)),
                "--max-coverage-drop-ratio",
                str(float(args.batch_reconnect_max_coverage_drop_ratio)),
                "--max-total-coverage-drop-ratio",
                str(float(args.batch_reconnect_max_total_coverage_drop_ratio)),
                "--output-root",
                str(output_root),
            )
            batch_reconnect_dirs.append(batch_dir)
            current_path_pixels = batch_dir / "batch_candidate_reconnect_path_pixels.json"
        final_diagnostics_dir = _run_script(
            diagnostics_scripts_dir / "run_shelf_path_turn_cost_diagnostics.py",
            "--input-run-dir",
            str(run_dir),
            "--path-pixels-path",
            str(current_path_pixels),
            "--output-root",
            str(output_root),
        )
        diagnostics_dirs.append(final_diagnostics_dir)
        bundle_dir = _write_experiment_bundle(
            output_root=output_root,
            area_id=int(args.area_id),
            raw_run_dir=run_dir,
            batch_reconnect_run_dirs=batch_reconnect_dirs,
            diagnostics_run_dirs=diagnostics_dirs,
        )
        payload["downstream"] = {
            "pipeline": "diagnostics_then_batch_candidate_reconnect",
            "batch_reconnect_passes": int(args.batch_reconnect_passes),
            "batch_reconnect_run_dirs": [str(path) for path in batch_reconnect_dirs],
            "diagnostics_run_dirs": [str(path) for path in diagnostics_dirs],
            "final_path_pixels": str(current_path_pixels),
            "final_diagnostics_run_dir": str(final_diagnostics_dir),
            "bundle_dir": str(bundle_dir),
        }
        (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
