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

from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import normalize_points


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="保持 shelf 路径连接顺序，只把路径点吸附到 turn_cost 规则节点的辅助实验。")
    parser.add_argument("--input-run-dir", required=True, help="同一 case 的 UI/shelf run 目录，用于读取 mask 和 summary。")
    parser.add_argument("--path-pixels-path", required=True, help="要保持连接顺序的 shelf 路径点。")
    parser.add_argument("--turn-cost-grid-run-dir", required=True, help="实验 1 规则节点 run 目录，用于读取 node_debug_enriched.json。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="输出根目录。")
    parser.add_argument("--snap-threshold-factor", type=float, default=0.75, help="吸附门限倍率，基准为 coverage_width_px。")
    parser.add_argument("--nearest-candidate-count", type=int, default=8, help="多对一冲突时最多查看的候选节点数。")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_summary(input_run_dir: Path) -> dict[str, Any]:
    candidates = sorted(input_run_dir.glob("*summary.json"))
    if not candidates:
        return {}
    payload = _load_json(candidates[0])
    return dict(payload) if isinstance(payload, dict) else {}


def _coverage_width_px(summary: dict[str, Any], input_run_dir: Path) -> int:
    config = summary.get("diagnostics", {}).get("applied_public_config", {})
    coverage_width_m = float(config.get("coverage_width_m", 0.6))
    resolution = None
    metadata_path = next(input_run_dir.glob("run_*/metadata.json"), None)
    if metadata_path is not None:
        metadata = _load_json(metadata_path)
        if isinstance(metadata, dict):
            resolution = metadata.get("map_resolution", metadata.get("resolution"))
    if resolution is None:
        resolution = 0.05
    return max(2, int(round(float(coverage_width_m) / float(resolution))))


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


def _find_node_debug(turn_cost_grid_run_dir: Path) -> Path:
    direct = turn_cost_grid_run_dir / "node_debug_enriched.json"
    if direct.is_file():
        return direct
    candidates = sorted(turn_cost_grid_run_dir.glob("planner/run_*/node_debug_enriched.json"))
    if not candidates:
        raise FileNotFoundError(f"node_debug_enriched.json not found under {turn_cost_grid_run_dir}")
    return candidates[-1]


def _load_accessible_nodes(node_debug_path: Path) -> np.ndarray:
    payload = _load_json(node_debug_path)
    points: list[tuple[float, float]] = []
    for item in payload:
        if item.get("obstacle"):
            continue
        point = item.get("planning_point_pixel")
        if not isinstance(point, list) or len(point) < 2:
            continue
        points.append((float(point[0]), float(point[1])))
    if not points:
        raise ValueError(f"没有可吸附的非障碍规则节点：{node_debug_path}")
    return np.asarray(points, dtype=np.float64)


def _snap_path_to_nodes(
    points: tuple[tuple[float, float], ...],
    nodes: np.ndarray,
    *,
    threshold_px: float,
    nearest_candidate_count: int,
) -> tuple[tuple[tuple[float, float], ...], dict[str, Any]]:
    snapped: list[tuple[float, float]] = []
    used_node_indices: set[int] = set()
    snap_distances: list[float] = []
    rejected_too_far = 0
    rejected_conflict = 0
    reused_consecutive = 0
    candidate_count = max(1, int(nearest_candidate_count))

    for index, point in enumerate(points):
        point_array = np.asarray(point, dtype=np.float64)
        distances = np.linalg.norm(nodes - point_array, axis=1)
        order = np.argsort(distances)[:candidate_count]
        chosen_index = None
        chosen_distance = None
        for node_index in order:
            distance = float(distances[int(node_index)])
            if distance > float(threshold_px):
                continue
            # 允许连续点吸附到同一节点，后续保留为零长度局部证据；非连续复用会改变局部结构，先拒绝。
            if int(node_index) in used_node_indices and not (
                snapped and tuple(nodes[int(node_index)]) == snapped[-1]
            ):
                continue
            chosen_index = int(node_index)
            chosen_distance = distance
            break
        if chosen_index is None:
            nearest_distance = float(distances[int(order[0])])
            if nearest_distance > float(threshold_px):
                rejected_too_far += 1
            else:
                rejected_conflict += 1
            snapped.append((float(point[0]), float(point[1])))
            continue
        chosen_point = (float(nodes[chosen_index, 0]), float(nodes[chosen_index, 1]))
        if snapped and snapped[-1] == chosen_point:
            reused_consecutive += 1
        used_node_indices.add(chosen_index)
        snap_distances.append(float(chosen_distance))
        snapped.append(chosen_point)

    summary = {
        "input_point_count": len(points),
        "output_point_count": len(snapped),
        "node_count": int(nodes.shape[0]),
        "snapped_count": len(snap_distances),
        "kept_original_count": len(points) - len(snap_distances),
        "rejected_too_far_count": rejected_too_far,
        "rejected_conflict_count": rejected_conflict,
        "consecutive_reuse_count": reused_consecutive,
        "snap_threshold_px": float(threshold_px),
        "mean_snap_distance_px": float(np.mean(snap_distances)) if snap_distances else None,
        "max_snap_distance_px": float(np.max(snap_distances)) if snap_distances else None,
    }
    return tuple(snapped), summary


def _draw_overlay(
    free_mask: np.ndarray,
    before: tuple[tuple[float, float], ...],
    after: tuple[tuple[float, float], ...],
    nodes: np.ndarray,
    out_path: Path,
) -> None:
    image = cv2.cvtColor(np.where(free_mask > 0, 245, 20).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    for node in nodes:
        cv2.circle(image, (int(round(node[0])), int(round(node[1]))), 1, (80, 80, 80), -1, cv2.LINE_AA)
    before_points = [(int(round(x)), int(round(y))) for x, y in before]
    after_points = [(int(round(x)), int(round(y))) for x, y in after]
    for start, end in zip(before_points, before_points[1:]):
        cv2.line(image, start, end, (180, 180, 180), 1, cv2.LINE_AA)
    for start, end in zip(after_points, after_points[1:]):
        cv2.line(image, start, end, (0, 130, 255), 2, cv2.LINE_AA)
    for point in after_points:
        cv2.circle(image, point, 2, (0, 80, 255), -1, cv2.LINE_AA)
    cv2.imwrite(str(out_path), image)


def main() -> None:
    args = parse_args()
    input_run_dir = Path(args.input_run_dir).expanduser().resolve()
    path_pixels_path = Path(args.path_pixels_path).expanduser().resolve()
    turn_cost_grid_run_dir = Path(args.turn_cost_grid_run_dir).expanduser().resolve()
    summary = _find_summary(input_run_dir)
    coverage_width_px = _coverage_width_px(summary, input_run_dir)
    threshold_px = float(coverage_width_px) * float(args.snap_threshold_factor)
    points = normalize_points(_load_json(path_pixels_path))
    free_mask, free_mask_source = _load_free_mask(input_run_dir)
    node_debug_path = _find_node_debug(turn_cost_grid_run_dir)
    nodes = _load_accessible_nodes(node_debug_path)
    snapped_points, snap_summary = _snap_path_to_nodes(
        points,
        nodes,
        threshold_px=threshold_px,
        nearest_candidate_count=int(args.nearest_candidate_count),
    )

    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_path_turn_cost_node_snap")
    run_dir.mkdir(parents=True, exist_ok=True)
    path_path = run_dir / "node_snap_path_pixels.json"
    path_path.write_text(
        json.dumps([[float(x), float(y)] for x, y in snapped_points], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    overlay_path = run_dir / "node_snap_overlay.png"
    _draw_overlay(free_mask, points, snapped_points, nodes, overlay_path)
    payload = {
        "case_group": "shelf_path_turn_cost_node_snap_experiment",
        "status": "success",
        "input": {
            "input_run_dir": str(input_run_dir),
            "path_pixels": str(path_pixels_path),
            "turn_cost_grid_run_dir": str(turn_cost_grid_run_dir),
            "node_debug_enriched": str(node_debug_path),
            "free_mask_source": str(free_mask_source),
            "coverage_width_px": int(coverage_width_px),
        },
        "algorithm_scope": {
            "type": "experiment_2_topology_preserving_node_snap",
            "description": "保持当前 shelf 路径访问顺序和连接拓扑，只在门限内把点吸附到实验 1 生成的 turn_cost 规则节点。",
            "formal_planner_migration": "不得迁入正式 planner；该实验只判断几何吸附是否足够。",
        },
        "parameters": {
            "snap_threshold_factor": float(args.snap_threshold_factor),
            "snap_threshold_px": float(threshold_px),
            "nearest_candidate_count": int(args.nearest_candidate_count),
        },
        "snap": snap_summary,
        "artifacts": {
            "node_snap_path_pixels": str(path_path),
            "overlay": str(overlay_path),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
