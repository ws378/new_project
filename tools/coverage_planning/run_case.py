#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_case_dir(path: Path) -> Path:
    case_dir = path.resolve()
    if not case_dir.exists():
        raise FileNotFoundError(f"case_dir 不存在: {case_dir}")
    return case_dir


def _prepare_run_dir(case_dir: Path) -> Path:
    runs_dir = case_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_name = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = runs_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _sync_latest(case_dir: Path, run_dir: Path) -> None:
    latest = case_dir / "latest"
    if latest.is_symlink() or latest.exists():
        if latest.is_symlink() or latest.is_file():
            latest.unlink()
        else:
            shutil.rmtree(latest)
    latest.symlink_to(run_dir, target_is_directory=True)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"缺少文件: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"文件必须是 JSON object: {path}")
    return payload


def _resolve_map_yaml(case_dir: Path, region_payload: dict[str, Any]) -> Path:
    map_yaml = Path(str(region_payload.get("map_yaml") or ""))
    if not map_yaml.is_absolute():
        map_yaml = case_dir / map_yaml
    if not map_yaml.exists():
        fallback = case_dir / "map.yaml"
        if fallback.exists():
            return fallback.resolve()
        yaml_files = sorted(case_dir.glob("*.yaml"))
        if yaml_files:
            return yaml_files[0].resolve()
        raise FileNotFoundError(f"map yaml 未找到: {map_yaml}")
    return map_yaml.resolve()


def _load_map(map_yaml: Path) -> tuple[np.ndarray, float, tuple[float, float]]:
    with map_yaml.open("r", encoding="utf-8") as handle:
        meta = yaml.safe_load(handle) or {}
    image_name = str(meta.get("image") or "")
    image_path = (map_yaml.parent / image_name).resolve()
    if not image_path.exists():
        raise FileNotFoundError(f"map image 未找到: {image_path}")
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"map image 读取失败: {image_path}")
    resolution = float(meta.get("resolution", 0.05))
    origin = meta.get("origin", [0.0, 0.0, 0.0])
    return image.astype(np.uint8), resolution, (float(origin[0]), float(origin[1]))


def _region_polygon(region_payload: dict[str, Any]) -> tuple[tuple[int, int], ...]:
    points = region_payload.get("polygon_points") or region_payload.get("polygon") or []
    polygon: list[tuple[int, int]] = []
    for point in points:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            polygon.append((int(round(float(point[0]))), int(round(float(point[1])))))
    return tuple(polygon)


def _start_point(region_payload: dict[str, Any], config_payload: dict[str, Any]) -> tuple[int, int]:
    point = region_payload.get("start_point_px") or region_payload.get("start_pixel") or config_payload.get("start_point_px")
    if not (isinstance(point, (list, tuple)) and len(point) >= 2):
        raise ValueError("case 缺少 start_point_px / start_pixel")
    return int(round(float(point[0]))), int(round(float(point[1])))


def _planner_config(raw_config: dict[str, Any], algorithm: str) -> dict[str, Any]:
    turn = dict(raw_config.get("turn_constraint") or {})
    local = dict(raw_config.get("local_direction") or {})
    strategy = dict(raw_config.get("strategy") or {})
    foundation = dict(strategy.get("foundation") or {})
    continuity = dict(strategy.get("continuity") or {})
    postprocess = dict(strategy.get("postprocess") or {})
    coverage_width_m = _require_stage2_public_scalar(raw_config, "coverage_width_m")
    open_kernel_m = _require_stage2_public_scalar(raw_config, "open_kernel_m")
    obstacle_expand_m = _require_stage2_public_scalar(raw_config, "obstacle_expand_m")
    robot_width_m = _require_stage2_public_scalar(raw_config, "robot_width_m")
    return {
        "planner_mode": "basic" if algorithm == "basic" else algorithm,
        "coverage_width_m": coverage_width_m,
        "open_kernel_m": open_kernel_m,
        "obstacle_expand_m": obstacle_expand_m,
        "robot_width_m": robot_width_m,
        "auto_rotate": bool(raw_config.get("auto_rotate", True)),
        "write_artifacts": bool(raw_config.get("write_artifacts", raw_config.get("save_debug_csv", True))),
        "turn_constraint_enable": bool(turn.get("enable_prohibit", raw_config.get("turn_constraint_enable", True))),
        "turn_constraint_near_max_turn_deg": float(turn.get("near_max_turn_deg", 20.0)),
        "turn_constraint_neighbor_max_turn_deg": float(turn.get("neighbor_max_turn_deg", 100.0)),
        "turn_constraint_fallback_max_turn_deg": float(turn.get("fallback_max_turn_deg", 135.0)),
        "turn_constraint_fallback_relax_dist_m": float(turn.get("fallback_relax_dist_m", 2.0)),
        "local_direction_enable": bool(local.get("enable", raw_config.get("local_direction_enable", True))),
        "local_direction_energy_weight": float(local.get("energy_weight", 2.8)),
        "fallback_jump_weight": float(foundation.get("fallback_jump_weight", 5.8)),
        "local_lateral_weight": float(foundation.get("local_lateral_weight", 0.8)),
        "allow_revisit_bridge": bool(foundation.get("allow_revisit_bridge", True)),
        "history_clearance_weight": float(continuity.get("history_clearance_weight", 4.0)),
        "split_jump_dist_factor": float(postprocess.get("split_jump_dist_factor", 10.0)),
    }


def _require_stage2_public_scalar(raw_config: dict[str, Any], key: str) -> float:
    """Require a stage2 public scalar from case planning_config."""

    if key not in raw_config:
        raise ValueError(f"planning_config 缺少阶段2正式字段: {key}")
    return float(raw_config[key])


def _draw_overlay(room_map: np.ndarray, path_pixels: tuple[tuple[float, float], ...], run_dir: Path) -> str:
    overlay = cv2.cvtColor(room_map, cv2.COLOR_GRAY2BGR)
    points = [(int(round(x)), int(round(y))) for x, y in path_pixels]
    for start, end in zip(points, points[1:]):
        cv2.line(overlay, start, end, (0, 0, 255), 2, cv2.LINE_AA)
    if points:
        cv2.circle(overlay, points[0], 6, (0, 255, 0), -1, cv2.LINE_AA)
        cv2.circle(overlay, points[-1], 6, (255, 0, 0), -1, cv2.LINE_AA)
    out_path = run_dir / "run_case_visualization.png"
    cv2.imwrite(str(out_path), overlay)
    return str(out_path)


def _run_formal_case(case_dir: Path, run_dir: Path, algorithm: str) -> dict[str, Any]:
    from algorithms.coverage_planning import (
        build_coverage_planning_request_configs,
        CoveragePlannerConfig,
        CoveragePlanningRequest,
        run_formal_planner_request,
        route_coverage_plan,
    )
    from algorithms.coverage_planning.preprocessing import build_region_mask_from_polygon, preprocess_total_map

    region_payload = _load_json(case_dir / "region.json")
    config_payload = _load_json(case_dir / "planning_config.json")
    map_yaml = _resolve_map_yaml(case_dir, region_payload)
    raw_map, resolution, origin_xy = _load_map(map_yaml)
    polygon = _region_polygon(region_payload)
    region_mask = build_region_mask_from_polygon(shape=raw_map.shape[:2], polygon_px=polygon)
    start_px = _start_point(region_payload, config_payload)
    planner_config = _planner_config(config_payload, algorithm)
    planner_config["artifacts_output_root"] = str(run_dir)
    public_config, public_config_source_keys, private_config = build_coverage_planning_request_configs(
        planner_config
    )

    request = CoveragePlanningRequest(
        prepared_map=preprocess_total_map(
            raw_map=raw_map,
            resolution_m_per_px=resolution,
            open_kernel_m=float(planner_config.get("open_kernel_m", 0.6)),
            obstacle_expand_m=float(planner_config.get("obstacle_expand_m", 0.6)),
            output_root=run_dir,
        ),
        map_resolution=resolution,
        starting_position_px=start_px,
        map_origin_xy=origin_xy,
        region_mask=region_mask,
        region_polygon_px=polygon,
        map_yaml_path=map_yaml,
        public_config=public_config,
        public_config_source_keys=public_config_source_keys,
        private_config=private_config,
        artifacts_output_root=run_dir,
    )
    if algorithm == "route":
        result = route_coverage_plan(request)
    else:
        formal_config = CoveragePlannerConfig(
            **{
                **{
                    key: getattr(public_config, key)
                    for key in public_config_source_keys
                    if hasattr(public_config, key)
                },
                "planner_mode": "basic" if algorithm == "basic" else "shelf_aware_guarded",
                "region_polygon_px": list(polygon),
                "map_yaml_path": str(map_yaml),
            }
        )
        explicit_request = CoveragePlanningRequest(
            prepared_map=request.prepared_map,
            map_resolution=request.map_resolution,
            starting_position_px=request.starting_position_px,
            map_origin_xy=request.map_origin_xy,
            region_mask=request.region_mask,
            region_polygon_px=request.region_polygon_px,
            map_yaml_path=request.map_yaml_path,
            public_config=formal_config,
            public_config_source_keys=request.public_config_source_keys,
            private_config=request.private_config,
            artifacts_output_root=request.artifacts_output_root,
        )
        result = run_formal_planner_request(
            explicit_request,
            "basic" if algorithm == "basic" else "shelf_aware_guarded",
        )
    path_pixels = tuple((float(x), float(y)) for x, y in result.path_pixels)
    global_path = [
        {
            "x": int(round(x)),
            "y": int(round(y)),
            "group_id": 1,
            "channel_id": -1,
            "sweep_id": -1,
            "point_type": "path",
        }
        for x, y in path_pixels
    ]
    visualization_path = _draw_overlay(raw_map, path_pixels, run_dir)
    return {
        "algorithm": algorithm,
        "selected_planner": result.diagnostics.selected_planner,
        "status": result.status.value,
        "success": result.success,
        "error_message": result.error_message,
        "case_dir": str(case_dir),
        "run_dir": str(run_dir),
        "map_yaml": str(map_yaml),
        "global_path": global_path,
        "global_path_meta": {"path_points": len(global_path)},
        "diagnostics": result.diagnostics.to_summary_dict(),
        "visualization_path": visualization_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Case runner backed by formal coverage_planning algorithms")
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument(
        "--algorithm",
        choices=["basic", "shelf_aware_guarded", "route"],
        default="basic",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    case_dir = _resolve_case_dir(args.case_dir)
    run_dir = _prepare_run_dir(case_dir)
    summary = _run_formal_case(case_dir, run_dir, str(args.algorithm))
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _sync_latest(case_dir, run_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
