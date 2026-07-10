from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.turn_cost_coverage_research.src.experiments.path_local_reconnector import (  # noqa: E402
    ReconnectConfig,
    turn_aware_astar_bridge,
)
from algorithms.turn_cost_coverage_research.src.diagnostics.path_diagnostics import (  # noqa: E402
    diagnose_lane_balance,
    diagnose_lane_spacing,
)
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import (  # noqa: E402
    Point,
    normalize_points,
    path_metrics,
    segment_is_free,
)


@dataclass(frozen=True)
class TaggedPoint:
    point: Point
    original_index: int | None
    reconnect_candidate_rank: int | None = None
    reconnect_window_start_original_index: int | None = None
    reconnect_window_end_original_index: int | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按候选排序逐个尝试局部 turn-cost A* 重连，并输出守卫接受后的最好结果。")
    parser.add_argument("--diagnostics-run-dir", required=True, help="包含 optimization_candidate_windows.json 的诊断 run 目录。")
    parser.add_argument("--max-candidates", type=int, default=30, help="最多尝试的候选数量。")
    parser.add_argument("--candidate-source", choices=("top", "all"), default="top", help="候选来源：top_candidates 或 all_candidates。")
    parser.add_argument(
        "--source-policy",
        choices=("provenance_safe", "all"),
        default="provenance_safe",
        help="候选来源策略。provenance_safe 只处理 fallback/bridge/不可行/高风险交叉类局部段；all 保留历史行为。",
    )
    parser.add_argument(
        "--action-labels",
        default=None,
        help="逗号分隔的动作标签过滤，例如 optimize_candidate,unsafe_bad；默认不过滤。",
    )
    parser.add_argument("--output-root", default="algorithms/turn_cost_coverage_research/output", help="实验输出根目录。")
    parser.add_argument("--anchor-margin-points", type=int, default=1, help="候选窗口前后额外纳入的 anchor 点数量。")
    parser.add_argument("--max-coverage-drop-ratio", type=float, default=0.001, help="单步允许的最大覆盖率下降。")
    parser.add_argument("--max-total-coverage-drop-ratio", type=float, default=0.0015, help="相对原始路径允许的最大累计覆盖率下降。")
    parser.add_argument("--max-turn-increase-deg", type=float, default=0.0, help="单步允许的最大总转角增加量，默认不允许增加。")
    parser.add_argument("--max-lane-over-dense-increase", type=int, default=0, help="单步允许新增的过密 lane 计数，默认不允许增加。")
    parser.add_argument("--max-lane-over-sparse-increase", type=int, default=0, help="单步允许新增的过疏 lane 计数，默认不允许增加。")
    parser.add_argument("--max-lane-imbalance-increase", type=int, default=0, help="单步允许新增的左右不平衡计数，默认不允许增加。")
    parser.add_argument("--turn-penalty-px", type=float, default=3.0, help="局部 A* 每次换方向的像素代价。")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _points(tagged: list[TaggedPoint]) -> tuple[Point, ...]:
    return tuple(item.point for item in tagged)


def _find_current_position(tagged: list[TaggedPoint], original_index: int) -> int | None:
    for position, item in enumerate(tagged):
        if item.original_index == int(original_index):
            return position
    return None


def _count_infeasible_segments(points: tuple[Point, ...], free_mask: np.ndarray, *, coverage_width_px: int) -> int:
    clearance = max(1, int(round(float(coverage_width_px) * 0.35)))
    return sum(
        1
        for start, end in zip(points, points[1:])
        if not segment_is_free(free_mask, start, end, clearance_px=clearance)
    )


def _lane_guard_metrics(
    points: tuple[Point, ...],
    *,
    coverage_width_px: int,
    resolution_m_per_px: float,
) -> dict[str, int | float]:
    spacing = diagnose_lane_spacing(
        points,
        coverage_width_px=coverage_width_px,
        resolution_m_per_px=resolution_m_per_px,
    )
    balance = diagnose_lane_balance(
        points,
        coverage_width_px=coverage_width_px,
        resolution_m_per_px=resolution_m_per_px,
    )
    return {
        "over_dense_count": int(spacing.over_dense_count),
        "over_sparse_count": int(spacing.over_sparse_count),
        "imbalanced_count": int(balance.imbalanced_count),
        "median_nearest_spacing_px": float(spacing.median_nearest_spacing_px),
    }


def _source_segment_by_original_index(summary: dict[str, Any]) -> dict[int, dict[str, Any]]:
    mapping = summary.get("generation_segment_mapping", {})
    if not isinstance(mapping, dict) or not mapping.get("loaded"):
        return {}
    result: dict[int, dict[str, Any]] = {}
    for item in mapping.get("segment_items", []):
        if not isinstance(item, dict):
            continue
        try:
            segment_index = int(item.get("segment_index"))
        except (TypeError, ValueError):
            continue
        result[segment_index] = item
    return result


def _load_source_segment_by_original_index(diagnostics_run_dir: Path, summary: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """读取诊断阶段的完整 segment 来源映射。

    `summary.json` 只保存聚合统计，避免把大列表塞进摘要；批量重连需要
    segment 级来源时，应优先读取同目录的完整 artifact。
    """

    artifact = summary.get("artifacts", {}).get("generation_segment_mapping")
    candidates: list[Path] = []
    if artifact:
        candidates.append(Path(str(artifact)).expanduser())
    candidates.append(diagnostics_run_dir / "generation_segment_mapping.json")
    for candidate in candidates:
        path = candidate if candidate.is_absolute() else diagnostics_run_dir / candidate
        if not path.exists():
            continue
        payload = _load_json(path)
        result = _source_segment_by_original_index({"generation_segment_mapping": payload})
        if result:
            return result
    return _source_segment_by_original_index(summary)


def _point_payload(point: Point) -> dict[str, float]:
    return {
        "pixel_x": float(point[0]),
        "pixel_y": float(point[1]),
    }


def _segment_source_for_final_edge(
    current: list[TaggedPoint],
    *,
    edge_index: int,
    source_by_original_segment: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """给重连后的最终线段保留来源。

    original_index 使用 0-based 路径点索引；原始 segment_index 使用 1-based，
    因此相邻原始点 i -> i+1 对应 source segment i+1。
    """

    start = current[edge_index]
    end = current[edge_index + 1]
    reconnect_candidate_rank = start.reconnect_candidate_rank if start.reconnect_candidate_rank is not None else end.reconnect_candidate_rank
    reconnect_window_start = (
        start.reconnect_window_start_original_index
        if start.reconnect_window_start_original_index is not None
        else end.reconnect_window_start_original_index
    )
    reconnect_window_end = (
        start.reconnect_window_end_original_index
        if start.reconnect_window_end_original_index is not None
        else end.reconnect_window_end_original_index
    )
    if start.original_index is not None and end.original_index is not None:
        source_segment_index = int(start.original_index) + 1
        if int(end.original_index) == int(start.original_index) + 1:
            source = source_by_original_segment.get(source_segment_index)
            if source is not None:
                return {
                    "move_source": str(source.get("move_source", "unknown")),
                    "edge_role": str(source.get("edge_role", "unknown")),
                    "source_kind": "preserved_original_segment",
                    "source_segment_index": source_segment_index,
                    "source_raw_path_index": source.get("raw_path_index"),
                    "source_match_distance_px": source.get("distance_px"),
                    "mapped": bool(source.get("mapped", False)),
                }
        return {
            "move_source": "original_nonconsecutive_after_reconnect",
            "edge_role": "local_reconnect_bridge",
            "source_kind": "original_points_nonconsecutive",
            "source_segment_index": source_segment_index,
            "reconnect_candidate_rank": reconnect_candidate_rank,
            "reconnect_window_start_original_index": reconnect_window_start,
            "reconnect_window_end_original_index": reconnect_window_end,
            "mapped": False,
        }
    return {
        "move_source": "turn_aware_reconnect",
        "edge_role": "local_reconnect_bridge",
        "source_kind": "inserted_bridge_segment",
        "source_segment_index": None,
        "reconnect_candidate_rank": reconnect_candidate_rank,
        "reconnect_window_start_original_index": reconnect_window_start,
        "reconnect_window_end_original_index": reconnect_window_end,
        "mapped": False,
    }


def _write_batch_generation_provenance(
    *,
    path: Path,
    current: list[TaggedPoint],
    source_by_original_segment: dict[int, dict[str, Any]],
    source_diagnostics_run_dir: Path,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    move_counts: dict[str, int] = {}
    edge_counts: dict[str, int] = {}
    source_kind_counts: dict[str, int] = {}
    for edge_index in range(max(0, len(current) - 1)):
        start = current[edge_index]
        end = current[edge_index + 1]
        source = _segment_source_for_final_edge(
            current,
            edge_index=edge_index,
            source_by_original_segment=source_by_original_segment,
        )
        move_source = str(source["move_source"])
        edge_role = str(source["edge_role"])
        source_kind = str(source["source_kind"])
        move_counts[move_source] = move_counts.get(move_source, 0) + 1
        edge_counts[edge_role] = edge_counts.get(edge_role, 0) + 1
        source_kind_counts[source_kind] = source_kind_counts.get(source_kind, 0) + 1
        items.append(
            {
                "path_index": int(edge_index + 2),
                "segment_index": int(edge_index + 1),
                "move_source": move_source,
                "edge_role": edge_role,
                "source_kind": source_kind,
                "source_segment_index": source.get("source_segment_index"),
                "source_raw_path_index": source.get("source_raw_path_index"),
                "source_match_distance_px": source.get("source_match_distance_px"),
                "reconnect_candidate_rank": source.get("reconnect_candidate_rank"),
                "reconnect_window_start_original_index": source.get("reconnect_window_start_original_index"),
                "reconnect_window_end_original_index": source.get("reconnect_window_end_original_index"),
                "mapped": bool(source.get("mapped", False)),
                "from_point": _point_payload(start.point),
                "to_point": _point_payload(end.point),
                "from_original_index": start.original_index,
                "to_original_index": end.original_index,
            }
        )
    payload = {
        "version": "turn_cost_research_batch_reconnect_segment_provenance_v1",
        "coordinate_note": "path_index/segment_index align to the batch reconnect output path; points are in original image pixel frame.",
        "source_diagnostics_run_dir": str(source_diagnostics_run_dir),
        "move_source_values": sorted(move_counts),
        "edge_role_values": sorted(edge_counts),
        "source_kind_values": sorted(source_kind_counts),
        "summary": {
            "item_count": len(items),
            "move_source_counts": move_counts,
            "edge_role_counts": edge_counts,
            "source_kind_counts": source_kind_counts,
        },
        "items": items,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload["summary"]


def _is_beneficial(before_metrics: dict[str, Any], after_metrics: dict[str, Any], before_infeasible: int, after_infeasible: int) -> bool:
    return bool(
        int(after_metrics["long_jump_count"]) < int(before_metrics["long_jump_count"])
        or int(after_infeasible) < int(before_infeasible)
        or float(after_metrics["total_turn_angle_deg"]) < float(before_metrics["total_turn_angle_deg"]) - 1e-6
        or float(after_metrics["coverage_ratio"]) > float(before_metrics["coverage_ratio"]) + 1e-9
        or float(after_metrics["length_px"]) < float(before_metrics["length_px"]) - 1e-6
    )


def _draw_batch_overlay(
    free_mask: np.ndarray,
    before: tuple[Point, ...],
    after: tuple[Point, ...],
    accepted_attempts: list[dict[str, Any]],
    *,
    out_path: Path,
) -> None:
    image = cv2.cvtColor(np.where(free_mask > 0, 245, 25).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    before_points = [(int(round(x)), int(round(y))) for x, y in before]
    after_points = [(int(round(x)), int(round(y))) for x, y in after]
    for start, end in zip(before_points, before_points[1:]):
        cv2.line(image, start, end, (190, 190, 190), 1, cv2.LINE_AA)
    for start, end in zip(after_points, after_points[1:]):
        cv2.line(image, start, end, (0, 145, 255), 2, cv2.LINE_AA)
    for attempt in accepted_attempts:
        centroid = attempt.get("candidate", {}).get("centroid", [0.0, 0.0])
        point = (int(round(float(centroid[0]))), int(round(float(centroid[1]))))
        cv2.circle(image, point, 8, (0, 0, 255), -1, cv2.LINE_AA)
        cv2.putText(
            image,
            str(attempt.get("candidate_rank")),
            point,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
    cv2.imwrite(str(out_path), image)


def _metric_delta(before: dict[str, Any], after: dict[str, Any], key: str) -> float:
    return float(after[key]) - float(before[key])


def _candidate_allowed_by_source_policy(candidate: dict[str, Any], *, source_policy: str) -> bool:
    if source_policy == "all":
        return True
    candidate_kind = str(candidate.get("candidate_kind", ""))
    if candidate_kind in {"fallback_reconnect", "revisit_bridge_reconnect", "infeasible_reconnect", "crossing_reconnect"}:
        return True
    generation = candidate.get("generation_source", {})
    if isinstance(generation, dict) and int(generation.get("high_risk_transfer_count", 0)) > 0:
        return True
    metrics = candidate.get("metrics", {})
    if not isinstance(metrics, dict):
        return False
    segment_type = str(candidate.get("segment_type", ""))
    if int(metrics.get("infeasible_segment_count", 0)) > 0:
        return True
    if int(metrics.get("high_risk_crossing_count", 0)) > 0 and segment_type in {"connector", "fragment"}:
        return True
    return False


def _select_candidates(
    payload: dict[str, Any],
    *,
    source: str,
    source_policy: str,
    action_labels: str | None,
    max_candidates: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    key = "all_candidates" if source == "all" else "top_candidates"
    raw_candidates = list(payload.get(key, []))
    candidates = [
        candidate
        for candidate in raw_candidates
        if _candidate_allowed_by_source_policy(candidate, source_policy=source_policy)
    ]
    if action_labels:
        allowed = {label.strip() for label in str(action_labels).split(",") if label.strip()}
        candidates = [candidate for candidate in candidates if str(candidate.get("action_label")) in allowed]
    selected = candidates[: int(max_candidates)]
    return selected, {
        "candidate_source_key": key,
        "source_policy": source_policy,
        "raw_candidate_count": len(raw_candidates),
        "source_policy_candidate_count": len(candidates),
        "selected_candidate_count": len(selected),
        "selected_candidate_kinds": _count_values(str(candidate.get("candidate_kind", "unknown")) for candidate in selected),
    }


def _count_values(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return counts


def main() -> None:
    args = parse_args()
    diagnostics_run_dir = Path(args.diagnostics_run_dir).expanduser().resolve()
    summary = _load_json(diagnostics_run_dir / "summary.json")
    source_by_original_segment = _load_source_segment_by_original_index(diagnostics_run_dir, summary)
    candidates_payload = _load_json(diagnostics_run_dir / "optimization_candidate_windows.json")
    candidates, candidate_selection = _select_candidates(
        candidates_payload,
        source=str(args.candidate_source),
        source_policy=str(args.source_policy),
        action_labels=args.action_labels,
        max_candidates=int(args.max_candidates),
    )

    input_run_dir = Path(str(summary["input"]["input_run_dir"])).expanduser().resolve()
    path_pixels_path = Path(str(summary["input"]["path_pixels"])).expanduser().resolve()
    resolution = float(summary["input"]["resolution_m_per_px"])
    coverage_width_px = int(summary["input"]["coverage_width_px"])
    free_mask, free_mask_source = _load_free_mask(input_run_dir)
    original_points = normalize_points(_load_json(path_pixels_path))
    current = [TaggedPoint(point=point, original_index=index) for index, point in enumerate(original_points)]

    config = ReconnectConfig(
        coverage_width_px=coverage_width_px,
        resolution_m_per_px=resolution,
        turn_penalty_px=float(args.turn_penalty_px),
        search_margin_factor=10.0,
    )
    original_metrics = path_metrics(original_points, free_mask, coverage_width_px=coverage_width_px).to_dict()
    original_infeasible = _count_infeasible_segments(original_points, free_mask, coverage_width_px=coverage_width_px)
    attempts: list[dict[str, Any]] = []
    accepted_attempts: list[dict[str, Any]] = []

    for rank, candidate in enumerate(candidates, start=1):
        start_original = max(0, int(candidate["start_point_index"]) - int(args.anchor_margin_points))
        end_original = min(len(original_points) - 1, int(candidate["end_point_index"]) + int(args.anchor_margin_points))
        start_position = _find_current_position(current, start_original)
        end_position = _find_current_position(current, end_original)
        if start_position is None or end_position is None or end_position <= start_position:
            attempts.append(
                {
                    "candidate_rank": rank,
                    "candidate": candidate,
                    "status": "skipped_anchor_missing_or_overlapped",
                }
            )
            continue

        before_points = _points(current)
        before_metrics = path_metrics(before_points, free_mask, coverage_width_px=coverage_width_px).to_dict()
        before_infeasible = _count_infeasible_segments(before_points, free_mask, coverage_width_px=coverage_width_px)
        before_lane_metrics = _lane_guard_metrics(
            before_points,
            coverage_width_px=coverage_width_px,
            resolution_m_per_px=resolution,
        )
        bridge = turn_aware_astar_bridge(free_mask, current[start_position].point, current[end_position].point, config=config)
        if bridge is None:
            attempts.append(
                {
                    "candidate_rank": rank,
                    "candidate": candidate,
                    "status": "failed_no_bridge",
                }
            )
            continue

        replacement = [
            TaggedPoint(
                point=current[start_position].point,
                original_index=current[start_position].original_index,
                reconnect_candidate_rank=rank,
                reconnect_window_start_original_index=start_original,
                reconnect_window_end_original_index=end_original,
            )
        ]
        replacement.extend(
            TaggedPoint(
                point=point,
                original_index=None,
                reconnect_candidate_rank=rank,
                reconnect_window_start_original_index=start_original,
                reconnect_window_end_original_index=end_original,
            )
            for point in bridge[1:-1]
        )
        replacement.append(
            TaggedPoint(
                point=current[end_position].point,
                original_index=current[end_position].original_index,
                reconnect_candidate_rank=rank,
                reconnect_window_start_original_index=start_original,
                reconnect_window_end_original_index=end_original,
            )
        )
        candidate_tagged = current[:start_position] + replacement + current[end_position + 1 :]
        candidate_points = _points(candidate_tagged)
        candidate_metrics = path_metrics(candidate_points, free_mask, coverage_width_px=coverage_width_px).to_dict()
        candidate_infeasible = _count_infeasible_segments(candidate_points, free_mask, coverage_width_px=coverage_width_px)
        candidate_lane_metrics = _lane_guard_metrics(
            candidate_points,
            coverage_width_px=coverage_width_px,
            resolution_m_per_px=resolution,
        )
        step_coverage_drop = float(before_metrics["coverage_ratio"]) - float(candidate_metrics["coverage_ratio"])
        total_coverage_drop = float(original_metrics["coverage_ratio"]) - float(candidate_metrics["coverage_ratio"])
        guards = {
            "step_coverage_drop_ok": bool(step_coverage_drop <= float(args.max_coverage_drop_ratio)),
            "total_coverage_drop_ok": bool(total_coverage_drop <= float(args.max_total_coverage_drop_ratio)),
            "long_jump_count_ok": bool(int(candidate_metrics["long_jump_count"]) <= int(before_metrics["long_jump_count"])),
            "infeasible_count_ok": bool(candidate_infeasible <= before_infeasible),
            "turn_increase_ok": bool(
                float(candidate_metrics["total_turn_angle_deg"]) - float(before_metrics["total_turn_angle_deg"])
                <= float(args.max_turn_increase_deg)
            ),
            "lane_over_dense_count_ok": bool(
                int(candidate_lane_metrics["over_dense_count"]) - int(before_lane_metrics["over_dense_count"])
                <= int(args.max_lane_over_dense_increase)
            ),
            "lane_over_sparse_count_ok": bool(
                int(candidate_lane_metrics["over_sparse_count"]) - int(before_lane_metrics["over_sparse_count"])
                <= int(args.max_lane_over_sparse_increase)
            ),
            "lane_imbalance_count_ok": bool(
                int(candidate_lane_metrics["imbalanced_count"]) - int(before_lane_metrics["imbalanced_count"])
                <= int(args.max_lane_imbalance_increase)
            ),
            "beneficial_ok": _is_beneficial(before_metrics, candidate_metrics, before_infeasible, candidate_infeasible),
        }
        attempt = {
            "candidate_rank": rank,
            "candidate": candidate,
            "status": "accepted" if all(guards.values()) else "rejected_by_guards",
            "guards": guards,
            "window": {
                "start_original_index": int(start_original),
                "end_original_index": int(end_original),
                "start_current_position": int(start_position),
                "end_current_position": int(end_position),
                "replaced_point_count": int(end_position - start_position + 1),
                "bridge_point_count": int(len(bridge)),
            },
            "before_metrics": before_metrics,
            "candidate_metrics": candidate_metrics,
            "before_lane_guard_metrics": before_lane_metrics,
            "candidate_lane_guard_metrics": candidate_lane_metrics,
            "before_infeasible_segment_count": int(before_infeasible),
            "candidate_infeasible_segment_count": int(candidate_infeasible),
            "candidate_delta": {
                "length_px_delta": _metric_delta(before_metrics, candidate_metrics, "length_px"),
                "turn_angle_deg_delta": _metric_delta(before_metrics, candidate_metrics, "total_turn_angle_deg"),
                "coverage_ratio_delta": _metric_delta(before_metrics, candidate_metrics, "coverage_ratio"),
                "long_jump_count_delta": int(candidate_metrics["long_jump_count"]) - int(before_metrics["long_jump_count"]),
                "infeasible_segment_count_delta": int(candidate_infeasible) - int(before_infeasible),
                "lane_over_dense_count_delta": int(candidate_lane_metrics["over_dense_count"])
                - int(before_lane_metrics["over_dense_count"]),
                "lane_over_sparse_count_delta": int(candidate_lane_metrics["over_sparse_count"])
                - int(before_lane_metrics["over_sparse_count"]),
                "lane_imbalance_count_delta": int(candidate_lane_metrics["imbalanced_count"])
                - int(before_lane_metrics["imbalanced_count"]),
            },
        }
        attempts.append(attempt)
        if all(guards.values()):
            current = candidate_tagged
            accepted_attempts.append(attempt)

    final_points = _points(current)
    final_metrics = path_metrics(final_points, free_mask, coverage_width_px=coverage_width_px).to_dict()
    final_infeasible = _count_infeasible_segments(final_points, free_mask, coverage_width_px=coverage_width_px)

    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = output_root / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_batch_candidate_reconnect")
    run_dir.mkdir(parents=True, exist_ok=True)
    path_path = run_dir / "batch_candidate_reconnect_path_pixels.json"
    path_path.write_text(
        json.dumps([[float(x), float(y)] for x, y in final_points], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    provenance_path = run_dir / "path_generation_provenance.json"
    provenance_summary = _write_batch_generation_provenance(
        path=provenance_path,
        current=current,
        source_by_original_segment=source_by_original_segment,
        source_diagnostics_run_dir=diagnostics_run_dir,
    )
    overlay_path = run_dir / "batch_candidate_reconnect_overlay.png"
    _draw_batch_overlay(
        free_mask,
        original_points,
        final_points,
        accepted_attempts,
        out_path=overlay_path,
    )
    payload = {
        "case_group": "batch_candidate_local_reconnect",
        "status": "success",
        "input": {
            "diagnostics_run_dir": str(diagnostics_run_dir),
            "source_input_run_dir": str(input_run_dir),
            "path_pixels": str(path_pixels_path),
            "max_candidates": int(args.max_candidates),
            "candidate_source": str(args.candidate_source),
            "source_policy": str(args.source_policy),
            "action_labels": args.action_labels,
            "coverage_width_px": int(coverage_width_px),
            "resolution_m_per_px": float(resolution),
            "free_mask_source": str(free_mask_source),
        },
        "algorithm_scope": {
            "type": "non_official_batch_window_experiment",
            "description": "按候选排序逐个尝试局部 turn-aware A* 重连；每个窗口必须通过守卫才接受，不接入正式 planner。",
        },
        "parameters": {
            "anchor_margin_points": int(args.anchor_margin_points),
            "max_coverage_drop_ratio": float(args.max_coverage_drop_ratio),
            "max_total_coverage_drop_ratio": float(args.max_total_coverage_drop_ratio),
            "max_turn_increase_deg": float(args.max_turn_increase_deg),
            "max_lane_over_dense_increase": int(args.max_lane_over_dense_increase),
            "max_lane_over_sparse_increase": int(args.max_lane_over_sparse_increase),
            "max_lane_imbalance_increase": int(args.max_lane_imbalance_increase),
            "turn_penalty_px": float(args.turn_penalty_px),
        },
        "attempt_count": int(len(attempts)),
        "candidate_selection": candidate_selection,
        "accepted_count": int(len(accepted_attempts)),
        "rejected_count": int(sum(1 for attempt in attempts if str(attempt["status"]).startswith("rejected"))),
        "failed_count": int(sum(1 for attempt in attempts if str(attempt["status"]).startswith("failed"))),
        "skipped_count": int(sum(1 for attempt in attempts if str(attempt["status"]).startswith("skipped"))),
        "accepted_candidate_ranks": [int(attempt["candidate_rank"]) for attempt in accepted_attempts],
        "attempts": attempts,
        "before_metrics": original_metrics,
        "after_metrics": final_metrics,
        "before_infeasible_segment_count": int(original_infeasible),
        "after_infeasible_segment_count": int(final_infeasible),
        "delta": {
            "length_px_delta": _metric_delta(original_metrics, final_metrics, "length_px"),
            "turn_angle_deg_delta": _metric_delta(original_metrics, final_metrics, "total_turn_angle_deg"),
            "coverage_ratio_delta": _metric_delta(original_metrics, final_metrics, "coverage_ratio"),
            "long_jump_count_delta": int(final_metrics["long_jump_count"]) - int(original_metrics["long_jump_count"]),
            "infeasible_segment_count_delta": int(final_infeasible) - int(original_infeasible),
        },
        "artifacts": {
            "path_pixels": str(path_path),
            "path_generation_provenance": str(provenance_path),
            "overlay": str(overlay_path),
            "summary": str(run_dir / "summary.json"),
        },
        "generation_provenance": {
            "loaded_source_segment_mapping": bool(source_by_original_segment),
            "source_segment_mapping_count": int(len(source_by_original_segment)),
            "output": provenance_summary,
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
