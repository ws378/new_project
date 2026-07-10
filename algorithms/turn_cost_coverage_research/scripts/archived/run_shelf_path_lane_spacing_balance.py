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

from algorithms.turn_cost_coverage_research.src.experiments.path_lane_spacing_balancer import (  # noqa: E402
    LaneBalanceConfig,
    balance_lane_spacing,
)
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import normalize_points  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对 shelf-aware 已生成路径做局部轨迹线间距均匀化实验。")
    parser.add_argument("--input-run-dir", required=True, help="UI 正式链路 run 目录，需包含 path_pixels.json。")
    parser.add_argument("--path-pixels-path", default=None, help="可选：使用指定路径点文件；metadata 和 mask 仍从 input-run-dir 读取。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="实验输出根目录。")
    parser.add_argument("--coverage-width-m", type=float, default=None, help="覆盖宽度；默认从 summary diagnostics.applied_public_config 读取。")
    parser.add_argument("--resolution-m-per-px", type=float, default=None, help="地图分辨率；默认从 metadata 或 map yaml 读取。")
    parser.add_argument("--max-coverage-drop-ratio", type=float, default=0.002, help="允许覆盖率下降上限。")
    parser.add_argument("--max-shift-factor", type=float, default=0.75, help="单个窗口内允许横向移动的最大 coverage_width 倍率。")
    parser.add_argument("--bbox-margin-factor", type=float, default=2.0, help="异常窗口 bbox 外扩倍率，基准为 coverage_width_px。")
    parser.add_argument("--min-window-issue-count", type=int, default=5, help="参与均匀化的窗口最少异常点数。")
    parser.add_argument("--max-windows", type=int, default=3, help="最多处理的过密窗口数量。")
    parser.add_argument("--max-parallel-angle-deg", type=float, default=12.0, help="lane 聚类允许的最大轴向偏差。")
    parser.add_argument("--lane-cluster-factor", type=float, default=0.35, help="同一 lane 的横向聚类阈值倍率。")
    parser.add_argument("--min-improvement-dense-count", type=int, default=10, help="接受候选所需最小过密异常减少数。")
    parser.add_argument("--max-over-sparse-increase", type=int, default=0, help="允许过疏异常增加数。")
    parser.add_argument("--max-total-turn-increase-ratio", type=float, default=0.02, help="允许总转角增加比例。")
    parser.add_argument("--max-length-increase-ratio", type=float, default=0.02, help="允许路径长度增加比例。")
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
    default_path_pixels_path = (input_run_dir / "path_pixels.json").resolve()
    path_pixels_path = Path(args.path_pixels_path).expanduser().resolve() if args.path_pixels_path else default_path_pixels_path
    path_pixels = normalize_points(_load_json(path_pixels_path))

    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_path_lane_spacing_balance")
    run_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = run_dir / "lane_spacing_balance_overlay.png"

    result = balance_lane_spacing(
        path_pixels,
        free_mask,
        LaneBalanceConfig(
            coverage_width_px=coverage_width_px,
            resolution_m_per_px=resolution,
            max_coverage_drop_ratio=float(args.max_coverage_drop_ratio),
            max_shift_factor=float(args.max_shift_factor),
            bbox_margin_factor=float(args.bbox_margin_factor),
            min_window_issue_count=int(args.min_window_issue_count),
            max_windows=int(args.max_windows),
            max_parallel_angle_deg=float(args.max_parallel_angle_deg),
            lane_cluster_factor=float(args.lane_cluster_factor),
            min_improvement_dense_count=int(args.min_improvement_dense_count),
            max_over_sparse_increase=int(args.max_over_sparse_increase),
            max_total_turn_increase_ratio=float(args.max_total_turn_increase_ratio),
            max_length_increase_ratio=float(args.max_length_increase_ratio),
        ),
        overlay_path=str(overlay_path),
    )

    balanced_path = run_dir / "path_pixels_lane_spacing_balanced.json"
    balanced_path.write_text(json.dumps([[x, y] for x, y in result.points], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload = {
        "case_group": "shelf_aware_path_lane_spacing_balance",
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
            "type": "local_lane_spacing_balance_experiment",
            "description": "只对 shelf_aware_guarded 已生成路径的 lane spacing 过密异常窗口做局部横向均匀化；不重新预处理、不重跑完整覆盖规划、不接入正式 UI planner。",
            "source_note": "借鉴成熟 swath/lane 思想，但不复制 Fields2Cover、BCD 或 turn-cost 官方流程。",
        },
        "parameters": {
            "max_coverage_drop_ratio": float(args.max_coverage_drop_ratio),
            "max_shift_factor": float(args.max_shift_factor),
            "bbox_margin_factor": float(args.bbox_margin_factor),
            "min_window_issue_count": int(args.min_window_issue_count),
            "max_windows": int(args.max_windows),
            "max_parallel_angle_deg": float(args.max_parallel_angle_deg),
            "lane_cluster_factor": float(args.lane_cluster_factor),
            "min_improvement_dense_count": int(args.min_improvement_dense_count),
            "max_over_sparse_increase": int(args.max_over_sparse_increase),
            "max_total_turn_increase_ratio": float(args.max_total_turn_increase_ratio),
            "max_length_increase_ratio": float(args.max_length_increase_ratio),
        },
        "result": result.to_dict(),
        "artifacts": {
            "balanced_path_pixels": str(balanced_path),
            "overlay": str(overlay_path),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
