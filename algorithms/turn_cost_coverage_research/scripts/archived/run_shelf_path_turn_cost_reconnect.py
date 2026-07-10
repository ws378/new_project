from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.turn_cost_coverage_research.src.experiments.path_local_reconnector import ReconnectConfig, reconnect_long_jumps
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import normalize_points


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对 shelf-aware 已生成路径的长跳跃做 turn-cost 局部重连实验。")
    parser.add_argument("--input-run-dir", required=True, help="UI 正式链路 run 目录，需包含 path_pixels.json。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="重连实验输出根目录。")
    parser.add_argument("--coverage-width-m", type=float, default=None, help="覆盖宽度；默认从 summary diagnostics.applied_public_config 读取。")
    parser.add_argument("--resolution-m-per-px", type=float, default=None, help="地图分辨率；默认从 metadata 或 map yaml 读取。")
    parser.add_argument("--long-jump-factor", type=float, default=4.0, help="长跳跃阈值倍率。")
    parser.add_argument("--turn-penalty-px", type=float, default=3.0, help="局部 A* 每次换方向的像素代价。")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_summary(input_run_dir: Path) -> dict[str, Any]:
    candidates = sorted(input_run_dir.glob("*summary.json"))
    if not candidates:
        return {}
    payload = _load_json(candidates[0])
    return dict(payload) if isinstance(payload, dict) else {}


def _coverage_width_m(summary: dict[str, Any], explicit: float | None) -> float:
    if explicit is not None:
        return float(explicit)
    config = summary.get("diagnostics", {}).get("applied_public_config", {})
    if "coverage_width_m" not in config:
        raise ValueError("缺少 coverage_width_m；请通过 --coverage-width-m 显式传入。")
    return float(config["coverage_width_m"])


def _resolution_m_per_px(summary: dict[str, Any], input_run_dir: Path, explicit: float | None) -> float:
    if explicit is not None:
        return float(explicit)
    metadata_path = next(input_run_dir.glob("run_*/metadata.json"), None)
    if metadata_path is not None:
        metadata = _load_json(metadata_path)
        if isinstance(metadata, dict) and "map_resolution" in metadata:
            return float(metadata["map_resolution"])
        if isinstance(metadata, dict) and "resolution" in metadata:
            return float(metadata["resolution"])
    config = summary.get("diagnostics", {}).get("applied_public_config", {})
    if "map_yaml_path" in config:
        import yaml

        map_yaml = Path(str(config["map_yaml_path"]))
        if map_yaml.is_file():
            meta = yaml.safe_load(map_yaml.read_text(encoding="utf-8")) or {}
            if "resolution" in meta:
                return float(meta["resolution"])
    raise ValueError("缺少 resolution_m_per_px；请通过 --resolution-m-per-px 显式传入。")


def _load_free_mask(input_run_dir: Path) -> tuple[np.ndarray, str]:
    candidates = [
        input_run_dir / "preprocess" / "prepare_map" / "05_prepared_map.png",
        input_run_dir / "preprocess" / "prepare_map" / "04_after_obstacle_expand.png",
    ]
    for candidate in candidates:
        image = cv2.imread(str(candidate), cv2.IMREAD_GRAYSCALE)
        if image is not None:
            return np.where(image > 127, 255, 0).astype(np.uint8), str(candidate)
    raise ValueError(f"无法在 {input_run_dir} 下找到同 frame 的 prepared/free mask 图像。")


def _draw_reconnect_overlay(free_mask: np.ndarray, before: tuple[tuple[float, float], ...], after: tuple[tuple[float, float], ...], out_path: Path) -> None:
    image = cv2.cvtColor(np.where(free_mask > 0, 245, 25).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    before_points = [(int(round(x)), int(round(y))) for x, y in before]
    after_points = [(int(round(x)), int(round(y))) for x, y in after]
    for start, end in zip(before_points, before_points[1:]):
        cv2.line(image, start, end, (165, 165, 165), 1, cv2.LINE_AA)
    for start, end in zip(after_points, after_points[1:]):
        cv2.line(image, start, end, (0, 90, 255), 2, cv2.LINE_AA)
    if after_points:
        cv2.circle(image, after_points[0], 7, (0, 180, 0), -1, cv2.LINE_AA)
        cv2.circle(image, after_points[-1], 7, (255, 0, 0), -1, cv2.LINE_AA)
    cv2.imwrite(str(out_path), image)


def _metric_delta(before: dict[str, Any], after: dict[str, Any], key: str) -> float:
    return float(after[key]) - float(before[key])


def main() -> None:
    args = parse_args()
    input_run_dir = Path(args.input_run_dir).expanduser().resolve()
    if not input_run_dir.is_dir():
        raise FileNotFoundError(f"input run dir not found: {input_run_dir}")
    summary = _find_summary(input_run_dir)
    resolution = _resolution_m_per_px(summary, input_run_dir, args.resolution_m_per_px)
    coverage_width_m = _coverage_width_m(summary, args.coverage_width_m)
    coverage_width_px = max(2, int(round(float(coverage_width_m) / float(resolution))))
    free_mask, free_mask_source = _load_free_mask(input_run_dir)
    path_pixels = normalize_points(_load_json(input_run_dir / "path_pixels.json"))
    result = reconnect_long_jumps(
        path_pixels,
        free_mask,
        ReconnectConfig(
            coverage_width_px=coverage_width_px,
            resolution_m_per_px=resolution,
            long_jump_factor=float(args.long_jump_factor),
            turn_penalty_px=float(args.turn_penalty_px),
        ),
    )

    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_path_turn_cost_reconnect")
    run_dir.mkdir(parents=True, exist_ok=True)
    path_path = run_dir / "reconnect_experiment_path_pixels.json"
    path_path.write_text(
        json.dumps([[float(x), float(y)] for x, y in result.points], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    overlay_path = run_dir / "path_reconnect_overlay.png"
    _draw_reconnect_overlay(free_mask, path_pixels, result.points, overlay_path)

    payload = {
        "case_group": "shelf_aware_path_turn_cost_local_reconnect",
        "status": "success",
        "input": {
            "input_run_dir": str(input_run_dir),
            "path_pixels": str(input_run_dir / "path_pixels.json"),
            "resolution_m_per_px": float(resolution),
            "coverage_width_m": float(coverage_width_m),
            "coverage_width_px": int(coverage_width_px),
            "free_mask_source": str(free_mask_source),
        },
        "algorithm_scope": {
            "type": "non_official_local_reconnect_experiment",
            "description": "只对 shelf_aware_guarded 已生成路径中的长跳跃段做局部 turn-aware A* 重连；不重新生成覆盖条带，不接入正式 planner。",
            "formal_planner_migration": "不得直接迁入正式 planner；需先完成多 case 形态和覆盖率 A/B。",
        },
        "parameters": {
            "long_jump_factor": float(args.long_jump_factor),
            "turn_penalty_px": float(args.turn_penalty_px),
        },
        "reconnect": result.to_dict(),
        "delta": {
            "length_px_delta": _metric_delta(result.before_metrics, result.after_metrics, "length_px"),
            "length_m_delta": _metric_delta(result.before_metrics, result.after_metrics, "length_px") * float(resolution),
            "turn_angle_deg_delta": _metric_delta(result.before_metrics, result.after_metrics, "total_turn_angle_deg"),
            "coverage_ratio_delta": _metric_delta(result.before_metrics, result.after_metrics, "coverage_ratio"),
            "point_count_delta": int(result.after_metrics["point_count"]) - int(result.before_metrics["point_count"]),
            "long_jump_count_delta": int(result.after_long_jump_count) - int(result.before_long_jump_count),
        },
        "artifacts": {
            "reconnect_experiment_path_pixels": str(path_path),
            "overlay": str(overlay_path),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
