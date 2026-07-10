"""路径局部窗口形态诊断。

该模块只读取路径点并输出窗口级风险字段，不修改路径。
字段口径对应 docs/01_主题/03_机器人几何与覆盖定义/04_转角窗口字段计算说明.md。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

Point = tuple[float, float]


@dataclass(frozen=True)
class PathWindowDiagnosticConfig:
    resolution_m: float
    window_sizes: tuple[int, ...] = (3, 5, 7)
    straight_angle_tol_deg: float = 20.0
    sharp_turn_deg: float = 70.0
    direction_change_deg: float = 45.0
    zigzag_turn_sum_deg: float = 95.0
    zigzag_direction_change_max_deg: float = 35.0
    zigzag_max_window_length_m: float = 2.0
    long_jump_threshold_m: float = 2.0
    merge_gap_points: int = 1
    threshold_source: str = "default"

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolution_m": float(self.resolution_m),
            "window_sizes": [int(value) for value in self.window_sizes],
            "straight_angle_tol_deg": float(self.straight_angle_tol_deg),
            "sharp_turn_deg": float(self.sharp_turn_deg),
            "direction_change_deg": float(self.direction_change_deg),
            "zigzag_turn_sum_deg": float(self.zigzag_turn_sum_deg),
            "zigzag_direction_change_max_deg": float(self.zigzag_direction_change_max_deg),
            "zigzag_max_window_length_m": float(self.zigzag_max_window_length_m),
            "long_jump_threshold_m": float(self.long_jump_threshold_m),
            "merge_gap_points": int(self.merge_gap_points),
            "threshold_source": self.threshold_source,
        }


def normalize_angle_deg(angle: float) -> float:
    """把角度归一到 [-180, 180)。"""

    return (float(angle) + 180.0) % 360.0 - 180.0


def heading_deg(a: Point, b: Point) -> float:
    return math.degrees(math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0])))


def euclidean_distance_px(a: Point, b: Point) -> float:
    return math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))


def segment_lengths_m(points: Sequence[Point], resolution_m: float) -> list[float]:
    return [euclidean_distance_px(a, b) * float(resolution_m) for a, b in zip(points[:-1], points[1:])]


def principal_heading_deg(points: Sequence[Point]) -> float:
    """用窗口端到端位移估计局部主方向。

    当前路径窗口是有序折线，不是无序点云；端到端位移比单段 heading 更稳定，
    也能避免 7 点窗口被首末两个短小毛刺主导。
    """

    if len(points) < 2:
        return 0.0
    return heading_deg(points[0], points[-1])


def turn_delta_deg(prev_point: Point, current_point: Point, next_point: Point) -> float:
    return normalize_angle_deg(heading_deg(current_point, next_point) - heading_deg(prev_point, current_point))


def estimate_straight_length_m(
    points: Sequence[Point],
    *,
    center_index: int,
    direction: int,
    resolution_m: float,
    straight_angle_tol_deg: float,
) -> float:
    """估计窗口前后可用近似直线长度。

    direction=-1 表示向前追溯；direction=1 表示向后延伸。
    一旦相邻段方向变化超过 straight_angle_tol_deg，就停止累计。
    """

    if direction not in (-1, 1):
        raise ValueError(f"direction must be -1 or 1: {direction}")
    if len(points) < 2:
        return 0.0

    length_m = 0.0
    if direction < 0:
        if center_index <= 0:
            return 0.0
        base_heading = heading_deg(points[center_index - 1], points[center_index])
        idx = center_index - 1
        while idx > 0:
            segment_heading = heading_deg(points[idx - 1], points[idx])
            if abs(normalize_angle_deg(segment_heading - base_heading)) > straight_angle_tol_deg:
                break
            length_m += euclidean_distance_px(points[idx - 1], points[idx]) * resolution_m
            idx -= 1
    else:
        if center_index >= len(points) - 1:
            return 0.0
        base_heading = heading_deg(points[center_index], points[center_index + 1])
        idx = center_index + 1
        while idx < len(points):
            segment_heading = heading_deg(points[idx - 1], points[idx])
            if abs(normalize_angle_deg(segment_heading - base_heading)) > straight_angle_tol_deg:
                break
            length_m += euclidean_distance_px(points[idx - 1], points[idx]) * resolution_m
            idx += 1
    return float(length_m)


def compute_window_metrics(
    points: Sequence[Point],
    *,
    center_index: int,
    window_size: int,
    config: PathWindowDiagnosticConfig,
) -> dict[str, Any]:
    if window_size % 2 == 0 or window_size < 3:
        raise ValueError(f"window_size must be odd and >= 3: {window_size}")
    half = window_size // 2
    if center_index - half < 0 or center_index + half >= len(points):
        raise ValueError(f"center_index out of range for window: {center_index}")

    start = center_index - half
    end = center_index + half
    window_points = list(points[start : end + 1])
    lengths_m = segment_lengths_m(window_points, config.resolution_m)
    local_turns = [
        turn_delta_deg(window_points[offset - 1], window_points[offset], window_points[offset + 1])
        for offset in range(1, len(window_points) - 1)
    ]
    if window_size == 3:
        entry_heading = heading_deg(window_points[0], window_points[1])
        exit_heading = heading_deg(window_points[-2], window_points[-1])
    else:
        entry_heading = principal_heading_deg(window_points[: half + 1])
        exit_heading = principal_heading_deg(window_points[half:])
    turn_abs = [abs(value) for value in local_turns]
    turn_angle = max(turn_abs) if turn_abs else 0.0
    turn_sum = sum(turn_abs)
    direction_change = abs(normalize_angle_deg(exit_heading - entry_heading))
    max_segment_length = max(lengths_m) if lengths_m else 0.0

    reasons: list[str] = []
    if turn_angle >= config.sharp_turn_deg:
        reasons.append("sharp_turn")
    if direction_change >= config.direction_change_deg:
        reasons.append("direction_change")
    turn_signs = [1 if value > 0 else -1 for value in local_turns if abs(value) >= config.straight_angle_tol_deg]
    has_alternating_turns = any(a != b for a, b in zip(turn_signs[:-1], turn_signs[1:]))
    if (
        window_size >= 5
        and sum(lengths_m) <= config.zigzag_max_window_length_m
        and turn_sum >= config.zigzag_turn_sum_deg
        and direction_change <= config.zigzag_direction_change_max_deg
        and has_alternating_turns
    ):
        reasons.append("short_zigzag")
    if max_segment_length >= config.long_jump_threshold_m:
        reasons.append("long_jump_nearby")

    return {
        "window_start_index": int(start),
        "window_end_index": int(end),
        "center_index": int(center_index),
        "window_size": int(window_size),
        "window_length_m": float(sum(lengths_m)),
        "entry_heading_deg": float(normalize_angle_deg(entry_heading)),
        "exit_heading_deg": float(normalize_angle_deg(exit_heading)),
        "turn_angle_deg": float(turn_angle),
        "turn_angle_sum_deg": float(turn_sum),
        "direction_change_deg": float(direction_change),
        "straight_length_before_m": float(
            estimate_straight_length_m(
                points,
                center_index=center_index,
                direction=-1,
                resolution_m=config.resolution_m,
                straight_angle_tol_deg=config.straight_angle_tol_deg,
            )
        ),
        "straight_length_after_m": float(
            estimate_straight_length_m(
                points,
                center_index=center_index,
                direction=1,
                resolution_m=config.resolution_m,
                straight_angle_tol_deg=config.straight_angle_tol_deg,
            )
        ),
        "max_segment_length_m": float(max_segment_length),
        "local_turns_deg": [float(value) for value in local_turns],
        "risk_reason": reasons or ["normal_reference"],
        "requires_turn_swept_check": bool(reasons),
    }


def _risk_score(window: dict[str, Any]) -> float:
    return (
        float(window.get("turn_angle_deg", 0.0)) * 1.0
        + float(window.get("turn_angle_sum_deg", 0.0)) * 0.35
        + float(window.get("direction_change_deg", 0.0)) * 0.6
        + float(window.get("max_segment_length_m", 0.0)) * 10.0
    )


def _merge_windows(candidates: Sequence[dict[str, Any]], merge_gap_points: int) -> list[dict[str, Any]]:
    if not candidates:
        return []
    ordered = sorted(candidates, key=lambda item: (int(item["window_start_index"]), int(item["window_end_index"])))
    groups: list[list[dict[str, Any]]] = [[ordered[0]]]
    for item in ordered[1:]:
        previous_end = max(int(value["window_end_index"]) for value in groups[-1])
        if int(item["window_start_index"]) <= previous_end + merge_gap_points:
            groups[-1].append(item)
        else:
            groups.append([item])

    merged: list[dict[str, Any]] = []
    for window_id, group in enumerate(groups):
        representative = max(group, key=_risk_score)
        reasons = sorted(
            {
                str(reason)
                for item in group
                for reason in item.get("risk_reason", [])
                if str(reason) != "normal_reference"
            }
        )
        merged_item = dict(representative)
        merged_item.update(
            {
                "window_id": int(window_id),
                "window_start_index": int(min(int(item["window_start_index"]) for item in group)),
                "window_end_index": int(max(int(item["window_end_index"]) for item in group)),
                "center_index": int(representative["center_index"]),
                "risk_reason": reasons,
                "requires_turn_swept_check": True,
                "source_window_sizes": sorted({int(item["window_size"]) for item in group}),
                "merged_window_count": int(len(group)),
                "representative_window_size": int(representative["window_size"]),
                "risk_score": float(_risk_score(representative)),
            }
        )
        merged.append(merged_item)
    return merged


def detect_path_windows(points: Sequence[Point], config: PathWindowDiagnosticConfig) -> dict[str, Any]:
    """输出原始窗口、合并窗口和汇总指标。"""

    raw_windows: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for window_size in config.window_sizes:
        half = int(window_size) // 2
        if window_size % 2 == 0 or window_size < 3:
            raise ValueError(f"invalid window size: {window_size}")
        if len(points) < window_size:
            continue
        for center_index in range(half, len(points) - half):
            window = compute_window_metrics(points, center_index=center_index, window_size=window_size, config=config)
            raw_windows.append(window)
            if window["requires_turn_swept_check"]:
                candidates.append(window)

    merged = _merge_windows(candidates, config.merge_gap_points)
    reason_counts: dict[str, int] = {}
    for item in merged:
        for reason in item.get("risk_reason", []):
            reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + 1

    return {
        "version": "path_window_diagnostics.v1",
        "config": config.to_dict(),
        "path_point_count": int(len(points)),
        "raw_window_count": int(len(raw_windows)),
        "candidate_window_count": int(len(candidates)),
        "merged_window_count": int(len(merged)),
        "sharp_turn_window_count": int(reason_counts.get("sharp_turn", 0)),
        "continuous_zigzag_count": int(reason_counts.get("short_zigzag", 0)),
        "direction_change_window_count": int(reason_counts.get("direction_change", 0)),
        "long_jump_nearby_window_count": int(reason_counts.get("long_jump_nearby", 0)),
        "risk_reason_counts": reason_counts,
        "windows": merged,
        "candidate_windows": candidates,
        "raw_windows": raw_windows,
    }
