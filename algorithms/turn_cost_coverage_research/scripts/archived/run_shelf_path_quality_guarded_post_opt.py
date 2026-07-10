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

from algorithms.turn_cost_coverage_research.src.experiments.path_quality_guarded_optimizer import (
    QualityGuardedConfig,
    quality_guarded_simplify_path,
)
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import normalize_points


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="局部质量守卫的 shelf-aware 路径 turn-cost 后处理实验。")
    parser.add_argument("--input-run-dir", required=True, help="UI 正式链路 run 目录，需包含 path_pixels.json 或作为 metadata/mask 来源。")
    parser.add_argument("--path-pixels-path", default=None, help="可选：使用指定路径点文件。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="输出根目录。")
    parser.add_argument("--coverage-width-m", type=float, default=None, help="覆盖宽度；默认从 summary 读取。")
    parser.add_argument("--resolution-m-per-px", type=float, default=None, help="地图分辨率；默认从 metadata 或 map yaml 读取。")
    parser.add_argument("--max-coverage-drop-ratio", type=float, default=0.001, help="允许覆盖率下降上限。")
    parser.add_argument("--max-narrow-coverage-drop-ratio", type=float, default=0.001, help="允许窄通道覆盖率下降上限。")
    parser.add_argument("--max-shortcut-factor", type=float, default=2.5, help="候选 shortcut 相对原两段长度的最大倍率。")
    parser.add_argument("--min-score-improvement", type=float, default=1.0, help="接受删点所需最小综合分数收益。")
    parser.add_argument("--max-quality-evaluations", type=int, default=300, help="最多执行多少次昂贵的全图局部质量评估。")
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


def _draw_overlay(free_mask: np.ndarray, before: tuple[tuple[float, float], ...], after: tuple[tuple[float, float], ...], out_path: Path) -> None:
    image = cv2.cvtColor(np.where(free_mask > 0, 245, 0).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    before_points = [(int(round(x)), int(round(y))) for x, y in before]
    after_points = [(int(round(x)), int(round(y))) for x, y in after]
    for start, end in zip(before_points, before_points[1:]):
        cv2.line(image, start, end, (185, 185, 185), 1, cv2.LINE_AA)
    for start, end in zip(after_points, after_points[1:]):
        cv2.line(image, start, end, (0, 80, 255), 2, cv2.LINE_AA)
    cv2.imwrite(str(out_path), image)


def main() -> None:
    args = parse_args()
    input_run_dir = Path(args.input_run_dir).expanduser().resolve()
    if not input_run_dir.is_dir():
        raise FileNotFoundError(f"input run dir not found: {input_run_dir}")
    path_pixels_path = Path(args.path_pixels_path).expanduser().resolve() if args.path_pixels_path else input_run_dir / "path_pixels.json"
    points = normalize_points(_load_json(path_pixels_path))
    summary = _find_summary(input_run_dir)
    resolution = _resolution_m_per_px(summary, input_run_dir, args.resolution_m_per_px)
    coverage_width_m = _coverage_width_m(summary, args.coverage_width_m)
    coverage_width_px = max(2, int(round(float(coverage_width_m) / float(resolution))))
    free_mask, free_mask_source = _load_free_mask(input_run_dir)

    result = quality_guarded_simplify_path(
        points,
        free_mask,
        QualityGuardedConfig(
            coverage_width_px=coverage_width_px,
            max_coverage_drop_ratio=float(args.max_coverage_drop_ratio),
            max_narrow_coverage_drop_ratio=float(args.max_narrow_coverage_drop_ratio),
            max_shortcut_factor=float(args.max_shortcut_factor),
            min_score_improvement=float(args.min_score_improvement),
            max_quality_evaluations=int(args.max_quality_evaluations),
        ),
    )
    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_path_quality_guarded_post_opt")
    run_dir.mkdir(parents=True, exist_ok=True)
    path_path = run_dir / "quality_guarded_post_opt_path_pixels.json"
    path_path.write_text(
        json.dumps([[float(x), float(y)] for x, y in result.points], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    overlay_path = run_dir / "quality_guarded_post_opt_overlay.png"
    _draw_overlay(free_mask, points, result.points, overlay_path)
    before_metrics = result.before_metrics.to_dict()
    after_metrics = result.after_metrics.to_dict()
    before_quality = result.before_quality.to_dict()
    after_quality = result.after_quality.to_dict()
    payload = {
        "case_group": "shelf_aware_path_quality_guarded_post_optimization",
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
            "type": "non_official_quality_guarded_post_processing_experiment",
            "description": "只对已有路径做局部质量守卫的 turn-cost 删点实验，不重新生成覆盖条带，不接入正式 planner。",
        },
        "parameters": {
            "max_coverage_drop_ratio": float(args.max_coverage_drop_ratio),
            "max_narrow_coverage_drop_ratio": float(args.max_narrow_coverage_drop_ratio),
            "max_shortcut_factor": float(args.max_shortcut_factor),
            "min_score_improvement": float(args.min_score_improvement),
            "max_quality_evaluations": int(args.max_quality_evaluations),
        },
        "optimization": result.to_dict(),
        "delta": {
            "point_count_delta": int(after_metrics["point_count"]) - int(before_metrics["point_count"]),
            "length_m_delta": (float(after_metrics["length_px"]) - float(before_metrics["length_px"])) * float(resolution),
            "turn_angle_deg_delta": float(after_metrics["total_turn_angle_deg"]) - float(before_metrics["total_turn_angle_deg"]),
            "coverage_ratio_delta": float(after_metrics["coverage_ratio"]) - float(before_metrics["coverage_ratio"]),
            "narrow_coverage_ratio_delta": float(after_quality["narrow_coverage_ratio"]) - float(before_quality["narrow_coverage_ratio"]),
            "repeated_coverage_ratio_delta": float(after_quality["repeated_coverage_ratio"]) - float(before_quality["repeated_coverage_ratio"]),
            "over_dense_coverage_ratio_delta": float(after_quality["over_dense_coverage_ratio"]) - float(before_quality["over_dense_coverage_ratio"]),
            "long_jump_count_delta": int(after_metrics["long_jump_count"]) - int(before_metrics["long_jump_count"]),
            "infeasible_segment_count_delta": int(after_quality["infeasible_segment_count"]) - int(before_quality["infeasible_segment_count"]),
        },
        "artifacts": {
            "quality_guarded_post_opt_path_pixels": str(path_path),
            "overlay": str(overlay_path),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
