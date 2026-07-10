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

from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import (
    SimplifyConfig,
    normalize_points,
    path_metrics,
    simplify_path_turn_cost,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对 shelf-aware 已生成覆盖路径做 turn-cost 后处理实验。")
    parser.add_argument("--input-run-dir", required=True, help="UI 正式链路生成的 run 目录，需包含 path_pixels.json。")
    parser.add_argument("--path-pixels-path", default=None, help="可选：使用指定路径点文件；metadata 和 mask 仍从 input-run-dir 读取。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="后处理实验输出根目录。")
    parser.add_argument("--coverage-width-m", type=float, default=None, help="覆盖宽度；默认从 summary diagnostics.applied_public_config 读取。")
    parser.add_argument("--resolution-m-per-px", type=float, default=None, help="地图分辨率；默认从 preprocess 或 summary 推导失败时报错。")
    parser.add_argument("--max-coverage-drop-ratio", type=float, default=0.002, help="允许覆盖率下降上限。")
    parser.add_argument("--min-turn-improvement-deg", type=float, default=5.0, help="删点所需最小局部转角收益。")
    parser.add_argument("--max-shortcut-factor", type=float, default=2.5, help="候选 shortcut 相对原两段长度的最大倍率。")
    parser.add_argument("--allow-long-jump-increase", action="store_true", help="允许后处理增加长跳跃数量或最大段长；默认禁止。")
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
    config = (
        summary.get("diagnostics", {})
        .get("applied_public_config", {})
    )
    if "coverage_width_m" not in config:
        raise ValueError("缺少 coverage_width_m；请通过 --coverage-width-m 显式传入。")
    return float(config["coverage_width_m"])


def _resolution_m_per_px(summary: dict[str, Any], input_run_dir: Path, explicit: float | None) -> float:
    if explicit is not None:
        return float(explicit)
    metadata_path = next(input_run_dir.glob("run_*/metadata.json"), None)
    if metadata_path is not None:
        metadata = _load_json(metadata_path)
        if isinstance(metadata, dict) and "resolution" in metadata:
            return float(metadata["resolution"])
    diagnostics = summary.get("diagnostics", {})
    config = diagnostics.get("applied_public_config", {})
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


def _draw_overlay(free_mask: np.ndarray, before: tuple[tuple[float, float], ...], after: tuple[tuple[float, float], ...], out_path: Path) -> None:
    image = cv2.cvtColor(np.where(free_mask > 0, 245, 0).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    before_points = [(int(round(x)), int(round(y))) for x, y in before]
    after_points = [(int(round(x)), int(round(y))) for x, y in after]
    for start, end in zip(before_points, before_points[1:]):
        cv2.line(image, start, end, (180, 180, 180), 1, cv2.LINE_AA)
    for start, end in zip(after_points, after_points[1:]):
        cv2.line(image, start, end, (0, 0, 255), 2, cv2.LINE_AA)
    if after_points:
        cv2.circle(image, after_points[0], 7, (0, 180, 0), -1, cv2.LINE_AA)
        cv2.circle(image, after_points[-1], 7, (255, 0, 0), -1, cv2.LINE_AA)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), image)


def _improvement(before: dict[str, Any], after: dict[str, Any], key: str) -> float:
    old = float(before[key])
    new = float(after[key])
    return float(old - new)


def main() -> None:
    args = parse_args()
    input_run_dir = Path(args.input_run_dir).expanduser().resolve()
    if not input_run_dir.is_dir():
        raise FileNotFoundError(f"input run dir not found: {input_run_dir}")
    path_pixels_path = Path(args.path_pixels_path).expanduser().resolve() if args.path_pixels_path else input_run_dir / "path_pixels.json"
    path_pixels = normalize_points(_load_json(path_pixels_path))
    summary = _find_summary(input_run_dir)
    resolution = _resolution_m_per_px(summary, input_run_dir, args.resolution_m_per_px)
    coverage_width_m = _coverage_width_m(summary, args.coverage_width_m)
    coverage_width_px = max(2, int(round(float(coverage_width_m) / float(resolution))))
    free_mask, free_mask_source = _load_free_mask(input_run_dir)
    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_path_turn_cost_post_opt")
    run_dir.mkdir(parents=True, exist_ok=True)
    metrics_only = path_metrics(path_pixels, free_mask, coverage_width_px=coverage_width_px)
    result = simplify_path_turn_cost(
        path_pixels,
        free_mask,
        SimplifyConfig(
            coverage_width_px=coverage_width_px,
            max_coverage_drop_ratio=float(args.max_coverage_drop_ratio),
            min_turn_improvement_deg=float(args.min_turn_improvement_deg),
            max_shortcut_factor=float(args.max_shortcut_factor),
            allow_long_jump_increase=bool(args.allow_long_jump_increase),
        ),
    )
    optimized_path = [[float(x), float(y)] for x, y in result.points]
    optimized_path_path = run_dir / "post_opt_experiment_path_pixels.json"
    optimized_path_path.write_text(
        json.dumps(optimized_path, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    overlay_path = run_dir / "turn_cost_post_opt_overlay.png"
    _draw_overlay(free_mask, path_pixels, result.points, overlay_path)
    before = result.before.to_dict()
    after = result.after.to_dict()
    payload = {
        "case_group": "shelf_aware_path_turn_cost_post_optimization",
        "status": "success",
        "input": {
            "input_run_dir": str(input_run_dir),
            "path_pixels": str(path_pixels_path),
            "resolution_m_per_px": float(resolution),
            "coverage_width_m": float(coverage_width_m),
            "coverage_width_px": int(coverage_width_px),
            "free_mask_source": str(free_mask_source),
        },
        "algorithm_scope": {
            "type": "non_official_post_processing_experiment",
            "description": "只对 shelf_aware_guarded 已生成路径做碰撞安全、覆盖保持的删点与 turn-cost 指标优化；不重新生成覆盖点，不进入官方 fractional/atomic/cycle 流程。",
            "coverage_metric_note": "coverage_ratio 为路径 buffer 近似值，用于实验比较，不等价于正式覆盖率验收。",
            "formal_planner_migration": "不得直接迁入正式 planner；需先完成多 case 覆盖保持、转角收益和形态 A/B。",
        },
        "parameters": {
            "max_coverage_drop_ratio": float(args.max_coverage_drop_ratio),
            "min_turn_improvement_deg": float(args.min_turn_improvement_deg),
            "max_shortcut_factor": float(args.max_shortcut_factor),
            "allow_long_jump_increase": bool(args.allow_long_jump_increase),
        },
        "metrics_only_baseline": metrics_only.to_dict(),
        "optimization": result.to_dict(),
        "improvement": {
            "length_px_reduction": _improvement(before, after, "length_px"),
            "length_m_reduction": _improvement(before, after, "length_px") * float(resolution),
            "turn_angle_deg_reduction": _improvement(before, after, "total_turn_angle_deg"),
            "coverage_ratio_delta": float(after["coverage_ratio"]) - float(before["coverage_ratio"]),
            "point_count_reduction": int(before["point_count"]) - int(after["point_count"]),
            "long_jump_count_reduction": int(before["long_jump_count"]) - int(after["long_jump_count"]),
        },
        "artifacts": {
            "post_opt_experiment_path_pixels": str(optimized_path_path),
            "overlay": str(overlay_path),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
