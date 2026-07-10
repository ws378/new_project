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

from algorithms.turn_cost_coverage_research.src.diagnostics.path_diagnostics import (
    diagnose_lane_balance,
    diagnose_lane_spacing,
    diagnose_local_quality,
    diagnose_path,
    diagnose_path_strokes,
    diagnose_segment_crossings,
    draw_lane_balance_overlay,
    draw_lane_spacing_overlay,
    draw_local_quality_overlay,
    draw_path_diagnostic_overlay,
    draw_path_stroke_segments_overlay,
    draw_path_stroke_quality_overlay,
    draw_segment_crossing_overlay,
    group_lane_balance_windows,
    group_lane_spacing_windows,
    group_segment_crossing_windows,
    select_lane_issue_windows,
    semantic_by_baseline_index,
)
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import normalize_points


def _axis_angle_deg(start: tuple[float, float], end: tuple[float, float]) -> float | None:
    dx = float(end[0]) - float(start[0])
    dy = float(end[1]) - float(start[1])
    if dx * dx + dy * dy <= 1e-9:
        return None
    angle = float(np.degrees(np.arctan2(dy, dx)) % 180.0)
    return angle


def _axis_angle_distance_deg(a: float, b: float) -> float:
    diff = abs(float(a) - float(b)) % 180.0
    return float(min(diff, 180.0 - diff))


def _dominant_axis_deg(angles: list[float]) -> float | None:
    if not angles:
        return None
    doubled = np.radians(np.asarray(angles, dtype=np.float64) * 2.0)
    mean_sin = float(np.mean(np.sin(doubled)))
    mean_cos = float(np.mean(np.cos(doubled)))
    if abs(mean_sin) + abs(mean_cos) <= 1e-9:
        return None
    return float((np.degrees(np.arctan2(mean_sin, mean_cos)) * 0.5) % 180.0)


def _endpoint_alignment_for_side(
    path_pixels: tuple[tuple[float, float], ...],
    *,
    coverage_width_px: int,
    side: str,
    sample_segment_count: int = 30,
    max_angle_error_deg: float = 20.0,
) -> dict[str, Any]:
    if len(path_pixels) < 3:
        return {
            "side": side,
            "status": "insufficient_points",
            "aligned": False,
        }
    points = path_pixels if side == "start" else tuple(reversed(path_pixels))
    entry_angle = _axis_angle_deg(points[0], points[1])
    entry_length = float(np.linalg.norm(np.asarray(points[1], dtype=np.float64) - np.asarray(points[0], dtype=np.float64)))
    reference_angles: list[float] = []
    min_reference_length = max(1.0, float(coverage_width_px) * 0.5)
    for start, end in zip(points[1:], points[2:]):
        length = float(np.linalg.norm(np.asarray(end, dtype=np.float64) - np.asarray(start, dtype=np.float64)))
        if length < min_reference_length:
            continue
        angle = _axis_angle_deg(start, end)
        if angle is not None:
            reference_angles.append(angle)
        if len(reference_angles) >= int(sample_segment_count):
            break
    reference_angle = _dominant_axis_deg(reference_angles)
    if entry_angle is None or reference_angle is None:
        return {
            "side": side,
            "status": "insufficient_reference",
            "aligned": False,
            "entry_segment_length_px": entry_length,
            "reference_segment_count": len(reference_angles),
        }
    angle_error = _axis_angle_distance_deg(entry_angle, reference_angle)
    return {
        "side": side,
        "status": "ok",
        "aligned": bool(angle_error <= float(max_angle_error_deg)),
        "entry_axis_deg": float(entry_angle),
        "reference_axis_deg": float(reference_angle),
        "angle_error_deg": float(angle_error),
        "max_allowed_angle_error_deg": float(max_angle_error_deg),
        "entry_segment_length_px": entry_length,
        "reference_segment_count": len(reference_angles),
    }


def diagnose_endpoint_alignment(
    path_pixels: tuple[tuple[float, float], ...],
    *,
    coverage_width_px: int,
) -> dict[str, Any]:
    """判断起始/收尾接入段是否和邻近 coverage lane 主轴一致。"""

    start = _endpoint_alignment_for_side(path_pixels, coverage_width_px=coverage_width_px, side="start")
    end = _endpoint_alignment_for_side(path_pixels, coverage_width_px=coverage_width_px, side="end")
    return {
        "method": "entry_or_exit_segment_axis_vs_next_local_segments_axis",
        "start": start,
        "end": end,
        "both_aligned": bool(start.get("aligned") and end.get("aligned")),
    }


def _stroke_segments_payload(
    path_pixels: tuple[tuple[float, float], ...],
    stroke_quality: Any,
    *,
    segment_generation_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """输出截断后的每个连续段点列；只读产物，不改变路径。"""

    segments: list[dict[str, Any]] = []
    generation_items = list(segment_generation_items or [])
    for stroke in stroke_quality.strokes:
        start = max(0, int(stroke.start_point_index))
        end = min(len(path_pixels) - 1, int(stroke.end_point_index))
        if end < start:
            points: list[list[float]] = []
        else:
            points = [[float(x), float(y)] for x, y in path_pixels[start : end + 1]]
        segments.append(
            {
                "stroke_id": int(stroke.stroke_id),
                "segment_type": stroke.segment_type,
                "problem_location": stroke.problem_location,
                "action_label": stroke.action_label,
                "classification": stroke.classification,
                "score": float(stroke.score),
                "reasons": list(stroke.reasons),
                "start_point_index": int(stroke.start_point_index),
                "end_point_index": int(stroke.end_point_index),
                "start_segment_index": int(stroke.start_segment_index),
                "end_segment_index": int(stroke.end_segment_index),
                "point_count": int(stroke.point_count),
                "length_px": float(stroke.length_px),
                "total_turn_deg": float(stroke.total_turn_deg),
                "crossing_count": int(stroke.crossing_count),
                "high_risk_crossing_count": int(stroke.high_risk_crossing_count),
                "connector_like_crossing_count": int(stroke.connector_like_crossing_count),
                "endpoint_crossing_count": int(stroke.endpoint_crossing_count),
                "interior_crossing_count": int(stroke.interior_crossing_count),
                "infeasible_segment_count": int(stroke.infeasible_segment_count),
                "max_infeasible_segment_length_px": float(stroke.max_infeasible_segment_length_px),
                "lane_spacing_issue_count": int(stroke.lane_spacing_issue_count),
                "lane_balance_issue_count": int(stroke.lane_balance_issue_count),
                "generation_source": _stroke_generation_counts(stroke, generation_items) if generation_items else None,
                "points": points,
            }
        )
    return {
        "scope": "path_cut_only",
        "note": "该文件只记录按连续性截断后的路径段，不做重连、不删除、不移动路径点。",
        "cut_boundaries": [boundary.to_dict() for boundary in stroke_quality.cut_boundaries],
        "segments": segments,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="诊断 shelf-aware 已生成路径的长跳跃和急转密集问题。")
    parser.add_argument("--input-run-dir", required=True, help="UI 正式链路 run 目录，需包含 path_pixels.json。")
    parser.add_argument("--path-pixels-path", default=None, help="可选：使用指定路径点文件；metadata 和 mask 仍从 input-run-dir 读取。")
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="诊断输出根目录。")
    parser.add_argument("--coverage-width-m", type=float, default=None, help="覆盖宽度；默认从 summary diagnostics.applied_public_config 读取。")
    parser.add_argument("--resolution-m-per-px", type=float, default=None, help="地图分辨率；默认从 metadata 或 map yaml 读取。")
    parser.add_argument("--long-jump-factor", type=float, default=4.0, help="长跳跃阈值倍率，阈值为 coverage_width_px * factor。")
    parser.add_argument("--turn-hotspot-angle-deg", type=float, default=70.0, help="单点急转阈值。")
    parser.add_argument("--turn-hotspot-window-radius", type=int, default=2, help="急转窗口统计半径。")
    parser.add_argument("--uncovered-min-area-factor", type=float, default=1.0, help="漏扫连通块最小面积倍率，基准为 coverage_width_px^2。")
    parser.add_argument("--lane-min-spacing-factor", type=float, default=0.65, help="小于 coverage_width_px 该倍率视为轨迹线过密。")
    parser.add_argument("--lane-max-spacing-factor", type=float, default=1.35, help="大于 coverage_width_px 该倍率视为轨迹线过疏。")
    parser.add_argument("--lane-window-merge-factor", type=float, default=3.0, help="lane spacing 异常点聚合窗口半径倍率，基准为 coverage_width_px。")
    parser.add_argument("--lane-window-min-issues", type=int, default=3, help="形成 lane spacing 异常窗口所需最少异常点数。")
    parser.add_argument("--lane-balance-window-merge-factor", type=float, default=3.0, help="lane balance 异常点聚合窗口半径倍率，基准为 coverage_width_px。")
    parser.add_argument("--lane-balance-window-min-issues", type=int, default=3, help="形成 lane balance 异常窗口所需最少异常点数。")
    parser.add_argument("--lane-issue-window-merge-factor", type=float, default=4.0, help="spacing/balance 交集窗口质心合并半径倍率，基准为 coverage_width_px。")
    parser.add_argument("--lane-issue-window-max-count", type=int, default=10, help="输出的 spacing/balance 交集窗口最大数量。")
    parser.add_argument("--crossing-window-merge-factor", type=float, default=4.0, help="交叉线异常点聚合窗口半径倍率，基准为 coverage_width_px。")
    parser.add_argument("--crossing-window-min-issues", type=int, default=2, help="形成交叉窗口所需最少交叉数。")
    parser.add_argument("--crossing-window-max-count", type=int, default=10, help="输出的交叉窗口最大数量。")
    parser.add_argument("--stroke-split-turn-deg", type=float, default=70.0, help="路径截断阶段的急转阈值。")
    parser.add_argument("--stroke-split-turn-delta-deg", type=float, default=30.0, help="相邻转角变化超过该阈值时作为截断边界。")
    parser.add_argument("--stroke-split-window-turn-deg", type=float, default=30.0, help="窗口级方向变化超过该阈值时作为截断边界。")
    parser.add_argument("--stroke-split-window-point-count", type=int, default=7, help="窗口级方向变化检测使用的点数，默认 7 点窗口。")
    parser.add_argument("--stroke-split-high-risk-crossings", type=int, default=2, help="单段达到该高风险交叉数时作为截断边界。")
    parser.add_argument("--stroke-split-connector-like-crossings", type=int, default=3, help="单段达到该 connector-like 交叉数时作为截断边界。")
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


def _load_semantic_payload(input_run_dir: Path) -> dict[str, Any] | None:
    path = input_run_dir / "semantic_global_path.json"
    if not path.is_file():
        path = next(input_run_dir.glob("run_*/semantic_global_path.json"), None)
    if path is None:
        return None
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else None


def _load_generation_provenance(input_run_dir: Path, path_pixels_path: Path | None = None) -> dict[str, Any] | None:
    candidates: list[Path] = []
    if path_pixels_path is not None:
        candidates.append(path_pixels_path.parent / "path_generation_provenance.json")
    candidates.append(input_run_dir / "path_generation_provenance.json")
    nested = next(input_run_dir.glob("run_*/path_generation_provenance.json"), None)
    if nested is not None:
        candidates.append(nested)
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        return None
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return None
    payload.setdefault("_loaded_from", str(path))
    return payload


def _summarize_generation_provenance(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {
            "loaded": False,
            "note": "path_generation_provenance.json unavailable; quality labels rely on geometry and postprocess artifacts only.",
        }
    items = payload.get("items", [])
    if not isinstance(items, list):
        items = []
    move_counts: dict[str, int] = {}
    edge_counts: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        move_source = str(item.get("move_source", "unknown"))
        edge_role = str(item.get("edge_role", "unknown"))
        move_counts[move_source] = move_counts.get(move_source, 0) + 1
        edge_counts[edge_role] = edge_counts.get(edge_role, 0) + 1
    return {
        "loaded": True,
        "loaded_from": payload.get("_loaded_from"),
        "version": payload.get("version"),
        "item_count": len(items),
        "move_source_counts": move_counts,
        "edge_role_counts": edge_counts,
        "alignment_scope": "raw_fov_path_before_simplify_semantic_and_jump_cleanup",
        "use_for_quality": "diagnostic_hint_only_until_final_path_index_mapping_is_added",
    }


def _point_from_provenance(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    if "pixel_x" not in value or "pixel_y" not in value:
        return None
    return float(value["pixel_x"]), float(value["pixel_y"])


def _point_to_segment_distance(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
    px, py = float(point[0]), float(point[1])
    sx, sy = float(start[0]), float(start[1])
    ex, ey = float(end[0]), float(end[1])
    dx = ex - sx
    dy = ey - sy
    denom = dx * dx + dy * dy
    if denom <= 1e-9:
        return float(np.hypot(px - sx, py - sy))
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / denom))
    qx = sx + t * dx
    qy = sy + t * dy
    return float(np.hypot(px - qx, py - qy))


def _map_generation_provenance_to_final_segments(
    path_pixels: tuple[tuple[float, float], ...],
    payload: dict[str, Any] | None,
    *,
    coverage_width_px: int,
) -> dict[str, Any]:
    """把 shelf 生成阶段 move 近似映射到最终路径线段。

    该映射只用于诊断。raw fov path 到最终 path_pixels 之间可能经过 simplify、
    semantic global path 和 isolated jump cleanup，因此这里必须记录匹配距离和
    mapped/unmapped 数量，不能静默当作严格索引。
    """

    if not payload:
        return {
            "loaded": False,
            "note": "path_generation_provenance.json unavailable.",
            "segment_items": [],
        }
    raw_segments: list[dict[str, Any]] = []
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        start = _point_from_provenance(item.get("from_point"))
        end = _point_from_provenance(item.get("to_point"))
        if start is None or end is None:
            continue
        raw_segments.append(
            {
                "path_index": int(item.get("path_index", -1)),
                "move_source": str(item.get("move_source", "unknown")),
                "edge_role": str(item.get("edge_role", "unknown")),
                "start": start,
                "end": end,
            }
        )
    max_match_distance = float(max(1, int(coverage_width_px))) * 1.5
    segment_items: list[dict[str, Any]] = []
    move_source_counts: dict[str, int] = {}
    edge_role_counts: dict[str, int] = {}
    mapped_count = 0
    for segment_index in range(1, len(path_pixels)):
        start = path_pixels[segment_index - 1]
        end = path_pixels[segment_index]
        midpoint = ((float(start[0]) + float(end[0])) * 0.5, (float(start[1]) + float(end[1])) * 0.5)
        best: dict[str, Any] | None = None
        best_distance = float("inf")
        for raw in raw_segments:
            distance = _point_to_segment_distance(midpoint, raw["start"], raw["end"])
            if distance < best_distance:
                best_distance = distance
                best = raw
        mapped = bool(best is not None and best_distance <= max_match_distance)
        if mapped and best is not None:
            mapped_count += 1
            move_source = str(best["move_source"])
            edge_role = str(best["edge_role"])
            move_source_counts[move_source] = move_source_counts.get(move_source, 0) + 1
            edge_role_counts[edge_role] = edge_role_counts.get(edge_role, 0) + 1
            segment_items.append(
                {
                    "segment_index": int(segment_index),
                    "mapped": True,
                    "distance_px": float(best_distance),
                    "raw_path_index": int(best["path_index"]),
                    "move_source": move_source,
                    "edge_role": edge_role,
                }
            )
        else:
            segment_items.append(
                {
                    "segment_index": int(segment_index),
                    "mapped": False,
                    "distance_px": float(best_distance if np.isfinite(best_distance) else -1.0),
                    "raw_path_index": None,
                    "move_source": "unmapped",
                    "edge_role": "unmapped",
                }
            )
    return {
        "loaded": True,
        "loaded_from": payload.get("_loaded_from"),
        "method": "nearest_raw_move_segment_by_final_segment_midpoint",
        "max_match_distance_px": float(max_match_distance),
        "raw_segment_count": len(raw_segments),
        "final_segment_count": max(0, len(path_pixels) - 1),
        "mapped_segment_count": int(mapped_count),
        "unmapped_segment_count": int(max(0, len(path_pixels) - 1) - mapped_count),
        "move_source_segment_counts": move_source_counts,
        "edge_role_segment_counts": edge_role_counts,
        "segment_items": segment_items,
    }


def _stroke_generation_counts(stroke: Any, segment_generation_items: list[dict[str, Any]]) -> dict[str, Any]:
    start = int(stroke.start_segment_index)
    end = int(stroke.end_segment_index)
    selected = [
        item
        for item in segment_generation_items
        if start <= int(item.get("segment_index", -1)) <= end
    ]
    move_counts: dict[str, int] = {}
    edge_counts: dict[str, int] = {}
    mapped_distances: list[float] = []
    for item in selected:
        move_source = str(item.get("move_source", "unmapped"))
        edge_role = str(item.get("edge_role", "unmapped"))
        move_counts[move_source] = move_counts.get(move_source, 0) + 1
        edge_counts[edge_role] = edge_counts.get(edge_role, 0) + 1
        if item.get("mapped"):
            mapped_distances.append(float(item.get("distance_px", 0.0)))
    return {
        "mapped_segment_count": sum(1 for item in selected if item.get("mapped")),
        "unmapped_segment_count": sum(1 for item in selected if not item.get("mapped")),
        "move_source_counts": move_counts,
        "edge_role_counts": edge_counts,
        "high_risk_transfer_count": int(move_counts.get("global_fallback", 0) + move_counts.get("revisit_bridge", 0)),
        "max_match_distance_px": float(max(mapped_distances) if mapped_distances else 0.0),
    }


def _candidate_allowed_scope(action_label: str) -> str:
    if action_label == "endpoint_fix_candidate":
        return "只允许动 stroke 两端附近连接点，主体 coverage lane 不动。"
    if action_label == "local_fix_candidate":
        return "只允许动局部问题窗口，长平滑主体不整段重连。"
    if action_label == "optimize_candidate":
        return "允许在前后稳定 anchor 之间做局部重连或替换。"
    if action_label == "unsafe_bad":
        return "优先进入局部重连；允许替换问题段，但必须通过覆盖和可行性守卫。"
    return "不进入自动优化。"


def _candidate_kind(stroke: Any, generation: dict[str, Any]) -> str:
    move_counts = generation.get("move_source_counts", {})
    if int(move_counts.get("global_fallback", 0)) > 0:
        return "fallback_reconnect"
    if int(stroke.infeasible_segment_count) > 0:
        return "infeasible_reconnect"
    if int(stroke.high_risk_crossing_count) > 0:
        return "crossing_reconnect"
    if int(move_counts.get("revisit_bridge", 0)) > 0:
        return "revisit_bridge_reconnect"
    if int(stroke.lane_spacing_issue_count) + int(stroke.lane_balance_issue_count) > 0:
        return "lane_uniformity_local_fix"
    if stroke.action_label == "endpoint_fix_candidate":
        return "endpoint_alignment_fix"
    return "turn_cost_local_fix"


def _candidate_score(stroke: Any, generation: dict[str, Any]) -> float:
    action_base = {
        "unsafe_bad": 1000.0,
        "optimize_candidate": 700.0,
        "local_fix_candidate": 420.0,
        "endpoint_fix_candidate": 180.0,
        "keep": -1000.0,
    }.get(str(stroke.action_label), 0.0)
    move_counts = generation.get("move_source_counts", {})
    lane_issue_count = int(stroke.lane_spacing_issue_count) + int(stroke.lane_balance_issue_count)
    length_norm = max(1.0, float(stroke.length_px) / 100.0)
    lane_issue_density = float(lane_issue_count) / length_norm
    score = action_base
    score += float(move_counts.get("global_fallback", 0)) * 140.0
    score += float(move_counts.get("revisit_bridge", 0)) * 70.0
    score += float(stroke.infeasible_segment_count) * 75.0
    score += float(stroke.high_risk_crossing_count) * 85.0
    score += float(stroke.connector_like_crossing_count) * 35.0
    score += min(160.0, lane_issue_density * 8.0)
    score += min(120.0, float(stroke.max_turn_deg) * 0.8)
    if str(stroke.segment_type) in {"connector", "fragment"}:
        score += 80.0
    if str(stroke.action_label) == "local_fix_candidate" and float(stroke.length_px) > 300.0:
        score -= 120.0
    return float(score)


def _optimization_candidate_payload(
    path_pixels: tuple[tuple[float, float], ...],
    stroke_quality: Any,
    *,
    segment_generation_items: list[dict[str, Any]],
    max_count: int = 30,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for stroke in stroke_quality.strokes:
        if stroke.action_label == "keep":
            continue
        start = max(0, int(stroke.start_point_index))
        end = min(len(path_pixels) - 1, int(stroke.end_point_index))
        points = path_pixels[start : end + 1] if end >= start else ()
        if points:
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            bbox = [min(xs), min(ys), max(xs), max(ys)]
            centroid = [float(np.mean(xs)), float(np.mean(ys))]
        else:
            bbox = [0.0, 0.0, 0.0, 0.0]
            centroid = [0.0, 0.0]
        generation = _stroke_generation_counts(stroke, segment_generation_items) if segment_generation_items else {
            "mapped_segment_count": 0,
            "unmapped_segment_count": int(max(0, end - start)),
            "move_source_counts": {},
            "edge_role_counts": {},
            "high_risk_transfer_count": 0,
            "max_match_distance_px": 0.0,
        }
        score = _candidate_score(stroke, generation)
        candidates.append(
            {
                "candidate_id": 0,
                "stroke_id": int(stroke.stroke_id),
                "priority_score": score,
                "candidate_kind": _candidate_kind(stroke, generation),
                "allowed_scope": _candidate_allowed_scope(stroke.action_label),
                "action_label": stroke.action_label,
                "segment_type": stroke.segment_type,
                "problem_location": stroke.problem_location,
                "classification": stroke.classification,
                "start_point_index": int(stroke.start_point_index),
                "end_point_index": int(stroke.end_point_index),
                "start_segment_index": int(stroke.start_segment_index),
                "end_segment_index": int(stroke.end_segment_index),
                "bbox_xyxy": bbox,
                "centroid": centroid,
                "metrics": {
                    "point_count": int(stroke.point_count),
                    "length_px": float(stroke.length_px),
                    "total_turn_deg": float(stroke.total_turn_deg),
                    "mean_turn_deg": float(stroke.mean_turn_deg),
                    "max_turn_deg": float(stroke.max_turn_deg),
                    "crossing_count": int(stroke.crossing_count),
                    "high_risk_crossing_count": int(stroke.high_risk_crossing_count),
                    "connector_like_crossing_count": int(stroke.connector_like_crossing_count),
                    "infeasible_segment_count": int(stroke.infeasible_segment_count),
                    "max_infeasible_segment_length_px": float(stroke.max_infeasible_segment_length_px),
                    "lane_spacing_issue_count": int(stroke.lane_spacing_issue_count),
                    "lane_balance_issue_count": int(stroke.lane_balance_issue_count),
                },
                "generation_source": generation,
                "reasons": list(stroke.reasons),
            }
        )
    candidates.sort(key=lambda item: float(item["priority_score"]), reverse=True)
    for index, item in enumerate(candidates, start=1):
        item["candidate_id"] = index
    return {
        "scope": "readonly_optimization_candidate_ranking",
        "note": "该文件只排序后续局部优化候选窗口，不移动、不删除、不重连路径点。",
        "selection_policy": [
            "优先 unsafe_bad，其次 optimize_candidate，再到 local_fix_candidate 和 endpoint_fix_candidate。",
            "优先 global_fallback / revisit_bridge / infeasible / high_risk_crossing 来源。",
            "长而平滑的 coverage core 只作为局部修复候选，不能整段替换。",
        ],
        "candidate_count": len(candidates),
        "top_candidate_count": min(int(max_count), len(candidates)),
        "top_candidates": candidates[: int(max_count)],
        "all_candidates": candidates,
    }


def _draw_optimization_candidate_overlay(
    free_mask: np.ndarray,
    points: tuple[tuple[float, float], ...],
    candidate_payload: dict[str, Any],
    *,
    out_path: str,
) -> None:
    image = cv2.cvtColor(np.where(np.asarray(free_mask) > 0, 245, 25).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    pixel_points = [(int(round(x)), int(round(y))) for x, y in points]
    for start, end in zip(pixel_points, pixel_points[1:]):
        cv2.line(image, start, end, (190, 190, 190), 1, cv2.LINE_AA)
    colors = {
        "fallback_reconnect": (0, 0, 255),
        "infeasible_reconnect": (0, 40, 255),
        "crossing_reconnect": (0, 100, 255),
        "revisit_bridge_reconnect": (0, 165, 255),
        "lane_uniformity_local_fix": (0, 210, 255),
        "endpoint_alignment_fix": (80, 220, 120),
        "turn_cost_local_fix": (180, 180, 0),
    }
    for candidate in candidate_payload.get("top_candidates", [])[:20]:
        color = colors.get(str(candidate.get("candidate_kind")), (0, 120, 255))
        start = max(0, int(candidate.get("start_segment_index", 1)) - 1)
        end = min(len(pixel_points) - 1, int(candidate.get("end_segment_index", 0)))
        thickness = 5 if int(candidate.get("candidate_id", 99)) <= 10 else 3
        for index in range(start, end):
            cv2.line(image, pixel_points[index], pixel_points[index + 1], color, thickness, cv2.LINE_AA)
        centroid = candidate.get("centroid", [0.0, 0.0])
        label_point = (int(round(float(centroid[0]))), int(round(float(centroid[1]))))
        cv2.putText(
            image,
            f"{candidate.get('candidate_id')}:{candidate.get('stroke_id')}",
            label_point,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )
    cv2.imwrite(out_path, image)


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
    semantic_payload = _load_semantic_payload(input_run_dir) if path_pixels_path == default_path_pixels_path else None
    semantic_index = semantic_by_baseline_index(semantic_payload)
    generation_provenance = _load_generation_provenance(input_run_dir, path_pixels_path=path_pixels_path)
    generation_provenance_summary = _summarize_generation_provenance(generation_provenance)
    segment_generation_mapping = _map_generation_provenance_to_final_segments(
        path_pixels,
        generation_provenance,
        coverage_width_px=coverage_width_px,
    )

    diagnostics = diagnose_path(
        path_pixels,
        resolution_m_per_px=resolution,
        coverage_width_px=coverage_width_px,
        long_jump_factor=float(args.long_jump_factor),
        turn_hotspot_angle_deg=float(args.turn_hotspot_angle_deg),
        turn_hotspot_window_radius=int(args.turn_hotspot_window_radius),
        semantic_index=semantic_index,
    )
    local_quality = diagnose_local_quality(
        path_pixels,
        free_mask,
        coverage_width_px=coverage_width_px,
        uncovered_min_area_px=max(1, int(round(float(coverage_width_px * coverage_width_px) * float(args.uncovered_min_area_factor)))),
    )
    lane_spacing = diagnose_lane_spacing(
        path_pixels,
        coverage_width_px=coverage_width_px,
        resolution_m_per_px=resolution,
        min_spacing_factor=float(args.lane_min_spacing_factor),
        max_spacing_factor=float(args.lane_max_spacing_factor),
    )
    lane_balance = diagnose_lane_balance(
        path_pixels,
        coverage_width_px=coverage_width_px,
        resolution_m_per_px=resolution,
    )
    lane_balance_windows = group_lane_balance_windows(
        lane_balance,
        merge_radius_px=float(coverage_width_px) * float(args.lane_balance_window_merge_factor),
        min_issue_count=int(args.lane_balance_window_min_issues),
    )
    lane_spacing_windows = group_lane_spacing_windows(
        lane_spacing,
        merge_radius_px=float(coverage_width_px) * float(args.lane_window_merge_factor),
        min_issue_count=int(args.lane_window_min_issues),
    )
    lane_issue_windows = select_lane_issue_windows(
        lane_spacing_windows,
        lane_balance_windows,
        centroid_merge_radius_px=float(coverage_width_px) * float(args.lane_issue_window_merge_factor),
        max_windows=int(args.lane_issue_window_max_count),
    )
    endpoint_alignment = diagnose_endpoint_alignment(
        path_pixels,
        coverage_width_px=coverage_width_px,
    )
    segment_crossings = diagnose_segment_crossings(
        path_pixels,
        coverage_width_px=coverage_width_px,
    )
    segment_crossing_windows = group_segment_crossing_windows(
        segment_crossings,
        merge_radius_px=float(coverage_width_px) * float(args.crossing_window_merge_factor),
        min_issue_count=int(args.crossing_window_min_issues),
        max_windows=int(args.crossing_window_max_count),
    )
    stroke_quality = diagnose_path_strokes(
        path_pixels,
        coverage_width_px=coverage_width_px,
        crossings=segment_crossings,
        lane_spacing=lane_spacing,
        lane_balance=lane_balance,
        free_mask=free_mask,
        split_turn_deg=float(args.stroke_split_turn_deg),
        split_turn_delta_deg=float(args.stroke_split_turn_delta_deg),
        split_window_turn_deg=float(args.stroke_split_window_turn_deg),
        split_window_point_count=int(args.stroke_split_window_point_count),
        split_high_risk_crossings=int(args.stroke_split_high_risk_crossings),
        split_connector_like_crossings=int(args.stroke_split_connector_like_crossings),
    )

    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_shelf_path_turn_cost_diagnostics")
    run_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = run_dir / "path_turn_cost_diagnostics_overlay.png"
    draw_path_diagnostic_overlay(free_mask, path_pixels, diagnostics, str(overlay_path))
    local_quality_overlay_path = run_dir / "local_quality_overlay.png"
    draw_local_quality_overlay(
        free_mask,
        path_pixels,
        coverage_width_px=coverage_width_px,
        out_path=str(local_quality_overlay_path),
    )
    lane_spacing_overlay_path = run_dir / "lane_spacing_overlay.png"
    draw_lane_spacing_overlay(
        free_mask,
        path_pixels,
        lane_spacing,
        out_path=str(lane_spacing_overlay_path),
    )
    lane_balance_overlay_path = run_dir / "lane_balance_overlay.png"
    draw_lane_balance_overlay(
        free_mask,
        path_pixels,
        lane_balance,
        out_path=str(lane_balance_overlay_path),
    )
    segment_crossing_overlay_path = run_dir / "segment_crossing_overlay.png"
    draw_segment_crossing_overlay(
        free_mask,
        path_pixels,
        segment_crossings,
        out_path=str(segment_crossing_overlay_path),
    )
    stroke_quality_overlay_path = run_dir / "path_stroke_quality_overlay.png"
    draw_path_stroke_quality_overlay(
        free_mask,
        path_pixels,
        stroke_quality,
        out_path=str(stroke_quality_overlay_path),
    )
    stroke_segments_overlay_path = run_dir / "path_stroke_segments_overlay.png"
    draw_path_stroke_segments_overlay(
        free_mask,
        path_pixels,
        stroke_quality,
        out_path=str(stroke_segments_overlay_path),
    )
    stroke_segments_path = run_dir / "path_stroke_segments.json"
    segment_generation_items = list(segment_generation_mapping.get("segment_items", []))
    optimization_candidates = _optimization_candidate_payload(
        path_pixels,
        stroke_quality,
        segment_generation_items=segment_generation_items,
        max_count=30,
    )
    stroke_segments_path.write_text(
        json.dumps(
            _stroke_segments_payload(path_pixels, stroke_quality, segment_generation_items=segment_generation_items),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    generation_segment_mapping_path = run_dir / "generation_segment_mapping.json"
    generation_segment_mapping_path.write_text(
        json.dumps(segment_generation_mapping, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    optimization_candidates_path = run_dir / "optimization_candidate_windows.json"
    optimization_candidates_path.write_text(
        json.dumps(optimization_candidates, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    optimization_candidates_overlay_path = run_dir / "optimization_candidate_windows_overlay.png"
    _draw_optimization_candidate_overlay(
        free_mask,
        path_pixels,
        optimization_candidates,
        out_path=str(optimization_candidates_overlay_path),
    )

    payload = {
        "case_group": "shelf_aware_path_turn_cost_diagnostics",
        "status": "success",
        "input": {
            "input_run_dir": str(input_run_dir),
            "path_pixels": str(path_pixels_path),
            "resolution_m_per_px": float(resolution),
            "coverage_width_m": float(coverage_width_m),
            "coverage_width_px": int(coverage_width_px),
            "free_mask_source": str(free_mask_source),
            "semantic_global_path_loaded": bool(semantic_index),
            "semantic_global_path_note": (
                "loaded_for_original_path"
                if semantic_index
                else "disabled_for_derived_path_or_unavailable"
            ),
            "generation_provenance_loaded": bool(generation_provenance_summary.get("loaded")),
            "generation_provenance_note": (
                "mapped_to_final_segments_for_readonly_quality_context"
                if segment_generation_mapping.get("loaded")
                else generation_provenance_summary.get("note")
            ),
        },
        "algorithm_scope": {
            "type": "diagnostics_only",
            "description": "只诊断 shelf_aware_guarded 已生成路径的长跳跃与急转密集段，不改变路径，不接入正式 planner。",
        },
        "parameters": {
            "long_jump_factor": float(args.long_jump_factor),
            "turn_hotspot_angle_deg": float(args.turn_hotspot_angle_deg),
            "turn_hotspot_window_radius": int(args.turn_hotspot_window_radius),
            "uncovered_min_area_factor": float(args.uncovered_min_area_factor),
            "lane_min_spacing_factor": float(args.lane_min_spacing_factor),
            "lane_max_spacing_factor": float(args.lane_max_spacing_factor),
            "lane_window_merge_factor": float(args.lane_window_merge_factor),
            "lane_window_min_issues": int(args.lane_window_min_issues),
            "lane_balance_window_merge_factor": float(args.lane_balance_window_merge_factor),
            "lane_balance_window_min_issues": int(args.lane_balance_window_min_issues),
            "lane_issue_window_merge_factor": float(args.lane_issue_window_merge_factor),
            "lane_issue_window_max_count": int(args.lane_issue_window_max_count),
            "crossing_window_merge_factor": float(args.crossing_window_merge_factor),
            "crossing_window_min_issues": int(args.crossing_window_min_issues),
            "crossing_window_max_count": int(args.crossing_window_max_count),
            "stroke_split_turn_deg": float(args.stroke_split_turn_deg),
            "stroke_split_turn_delta_deg": float(args.stroke_split_turn_delta_deg),
            "stroke_split_window_turn_deg": float(args.stroke_split_window_turn_deg),
            "stroke_split_window_point_count": int(args.stroke_split_window_point_count),
            "stroke_split_high_risk_crossings": int(args.stroke_split_high_risk_crossings),
            "stroke_split_connector_like_crossings": int(args.stroke_split_connector_like_crossings),
        },
        "diagnostics": diagnostics.to_dict(),
        "local_quality": local_quality.to_dict(),
        "lane_spacing_quality": lane_spacing.to_dict(),
        "lane_spacing_windows": [window.to_dict() for window in lane_spacing_windows],
        "lane_balance_quality": lane_balance.to_dict(),
        "lane_balance_windows": [window.to_dict() for window in lane_balance_windows],
        "lane_issue_windows": [window.to_dict() for window in lane_issue_windows],
        "endpoint_alignment": endpoint_alignment,
        "generation_provenance": generation_provenance_summary,
        "generation_segment_mapping": {key: value for key, value in segment_generation_mapping.items() if key != "segment_items"},
        "segment_crossing_quality": segment_crossings.to_dict(),
        "segment_crossing_windows": [window.to_dict() for window in segment_crossing_windows],
        "path_stroke_quality": stroke_quality.to_dict(),
        "optimization_candidate_windows": {
            key: value
            for key, value in optimization_candidates.items()
            if key not in {"top_candidates", "all_candidates"}
        },
        "artifacts": {
            "overlay": str(overlay_path),
            "local_quality_overlay": str(local_quality_overlay_path),
            "lane_spacing_overlay": str(lane_spacing_overlay_path),
            "lane_balance_overlay": str(lane_balance_overlay_path),
            "segment_crossing_overlay": str(segment_crossing_overlay_path),
            "path_stroke_quality_overlay": str(stroke_quality_overlay_path),
            "path_stroke_segments_overlay": str(stroke_segments_overlay_path),
            "path_stroke_segments": str(stroke_segments_path),
            "generation_segment_mapping": str(generation_segment_mapping_path),
            "optimization_candidate_windows": str(optimization_candidates_path),
            "optimization_candidate_windows_overlay": str(optimization_candidates_overlay_path),
            "summary": str(run_dir / "summary.json"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
