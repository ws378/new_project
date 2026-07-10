"""已有覆盖路径长跳跃的局部重连实验工具。"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np

from algorithms.turn_cost_coverage_research.src.diagnostics.path_diagnostics import SegmentIssue, diagnose_path
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import Point, path_metrics


_NEIGHBORS: tuple[tuple[int, int], ...] = (
    (-1, -1),
    (0, -1),
    (1, -1),
    (-1, 0),
    (1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
)


@dataclass(frozen=True)
class ReconnectConfig:
    coverage_width_px: int
    resolution_m_per_px: float
    long_jump_factor: float = 4.0
    clearance_factor: float = 0.35
    search_margin_factor: float = 6.0
    turn_penalty_px: float = 3.0
    max_inserted_points_per_jump: int = 6000


@dataclass(frozen=True)
class ReconnectAttempt:
    start_index: int
    end_index: int
    original_length_px: float
    inserted_point_count: int
    status: str

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            "start_index": int(self.start_index),
            "end_index": int(self.end_index),
            "original_length_px": float(self.original_length_px),
            "inserted_point_count": int(self.inserted_point_count),
            "status": self.status,
        }


@dataclass(frozen=True)
class ReconnectResult:
    points: tuple[Point, ...]
    attempts: tuple[ReconnectAttempt, ...]
    before_metrics: dict[str, float | int]
    after_metrics: dict[str, float | int]
    before_long_jump_count: int
    after_long_jump_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "before_metrics": self.before_metrics,
            "after_metrics": self.after_metrics,
            "before_long_jump_count": int(self.before_long_jump_count),
            "after_long_jump_count": int(self.after_long_jump_count),
            "fixed_long_jump_count": int(self.before_long_jump_count - self.after_long_jump_count),
        }


def _nearest_free(mask: np.ndarray, point: Point, radius: int) -> tuple[int, int] | None:
    height, width = mask.shape[:2]
    x0 = int(round(point[0]))
    y0 = int(round(point[1]))
    if 0 <= x0 < width and 0 <= y0 < height and mask[y0, x0] > 0:
        return x0, y0
    best: tuple[int, int] | None = None
    best_dist = float("inf")
    for y in range(max(0, y0 - radius), min(height, y0 + radius + 1)):
        for x in range(max(0, x0 - radius), min(width, x0 + radius + 1)):
            if mask[y, x] <= 0:
                continue
            dist = math.hypot(float(x - x0), float(y - y0))
            if dist < best_dist:
                best = (x, y)
                best_dist = dist
    return best


def _compress_polyline(points: Sequence[tuple[int, int]]) -> list[Point]:
    if len(points) <= 2:
        return [(float(x), float(y)) for x, y in points]
    result: list[tuple[int, int]] = [points[0]]
    last_dir = (points[1][0] - points[0][0], points[1][1] - points[0][1])
    for prev, curr in zip(points[1:], points[2:]):
        curr_dir = (curr[0] - prev[0], curr[1] - prev[1])
        if curr_dir != last_dir:
            result.append(prev)
            last_dir = curr_dir
    result.append(points[-1])
    return [(float(x), float(y)) for x, y in result]


def _densify_polyline(points: Sequence[Point], max_segment_px: float) -> list[Point]:
    if len(points) <= 1:
        return list(points)
    result: list[Point] = [points[0]]
    for start, end in zip(points, points[1:]):
        length = math.hypot(float(end[0] - start[0]), float(end[1] - start[1]))
        steps = max(1, int(math.ceil(length / float(max_segment_px))))
        for step in range(1, steps + 1):
            ratio = float(step) / float(steps)
            result.append(
                (
                    float(start[0] + (end[0] - start[0]) * ratio),
                    float(start[1] + (end[1] - start[1]) * ratio),
                )
            )
    return result


def _turn_aware_astar(mask: np.ndarray, start: Point, goal: Point, *, config: ReconnectConfig) -> list[Point] | None:
    radius = max(1, int(round(float(config.coverage_width_px) * float(config.clearance_factor))))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
    safe_mask = cv2.erode((mask > 0).astype(np.uint8), kernel, iterations=1)
    start_xy = _nearest_free(safe_mask, start, radius=int(config.coverage_width_px))
    goal_xy = _nearest_free(safe_mask, goal, radius=int(config.coverage_width_px))
    if start_xy is None or goal_xy is None:
        return None

    margin = max(int(round(float(config.coverage_width_px) * float(config.search_margin_factor))), 20)
    min_x = max(0, min(start_xy[0], goal_xy[0]) - margin)
    max_x = min(mask.shape[1] - 1, max(start_xy[0], goal_xy[0]) + margin)
    min_y = max(0, min(start_xy[1], goal_xy[1]) - margin)
    max_y = min(mask.shape[0] - 1, max(start_xy[1], goal_xy[1]) + margin)
    roi = safe_mask[min_y : max_y + 1, min_x : max_x + 1]
    local_start = (start_xy[0] - min_x, start_xy[1] - min_y)
    local_goal = (goal_xy[0] - min_x, goal_xy[1] - min_y)

    queue: list[tuple[float, float, int, int, int]] = []
    heapq.heappush(queue, (math.hypot(local_goal[0] - local_start[0], local_goal[1] - local_start[1]), 0.0, local_start[0], local_start[1], -1))
    best_cost: dict[tuple[int, int, int], float] = {(local_start[0], local_start[1], -1): 0.0}
    parent: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    goal_state: tuple[int, int, int] | None = None

    while queue:
        _, cost, x, y, direction = heapq.heappop(queue)
        state = (x, y, direction)
        if cost > best_cost.get(state, float("inf")) + 1e-9:
            continue
        if (x, y) == local_goal:
            goal_state = state
            break
        for next_dir, (dx, dy) in enumerate(_NEIGHBORS):
            nx = x + dx
            ny = y + dy
            if nx < 0 or ny < 0 or nx >= roi.shape[1] or ny >= roi.shape[0] or roi[ny, nx] <= 0:
                continue
            step = math.hypot(float(dx), float(dy))
            turn = 0.0 if direction in (-1, next_dir) else float(config.turn_penalty_px)
            next_cost = cost + step + turn
            next_state = (nx, ny, next_dir)
            if next_cost >= best_cost.get(next_state, float("inf")):
                continue
            best_cost[next_state] = next_cost
            parent[next_state] = state
            heuristic = math.hypot(float(local_goal[0] - nx), float(local_goal[1] - ny))
            heapq.heappush(queue, (next_cost + heuristic, next_cost, nx, ny, next_dir))

    if goal_state is None:
        return None

    reversed_points: list[tuple[int, int]] = []
    state = goal_state
    while True:
        reversed_points.append((state[0] + min_x, state[1] + min_y))
        if state not in parent:
            break
        state = parent[state]
    reversed_points.reverse()
    compressed = _compress_polyline(reversed_points)
    compressed = _densify_polyline(
        compressed,
        max_segment_px=max(1.0, float(config.coverage_width_px) * float(config.long_jump_factor) * 0.8),
    )
    if len(compressed) > int(config.max_inserted_points_per_jump):
        return None
    return [start] + compressed[1:-1] + [goal]


def turn_aware_astar_bridge(mask: np.ndarray, start: Point, goal: Point, *, config: ReconnectConfig) -> tuple[Point, ...] | None:
    """公开的局部 turn-aware A* 桥接入口，供单窗口重连实验复用。"""

    bridge = _turn_aware_astar(mask, start, goal, config=config)
    return tuple(bridge) if bridge is not None else None


def reconnect_long_jumps(points: Sequence[Point], free_mask: np.ndarray, config: ReconnectConfig) -> ReconnectResult:
    before_metrics = path_metrics(points, free_mask, coverage_width_px=config.coverage_width_px).to_dict()
    before_diagnostics = diagnose_path(
        points,
        resolution_m_per_px=config.resolution_m_per_px,
        coverage_width_px=config.coverage_width_px,
        long_jump_factor=config.long_jump_factor,
    )
    long_jumps_by_start = {issue.start_index: issue for issue in before_diagnostics.long_jumps}
    rebuilt: list[Point] = []
    attempts: list[ReconnectAttempt] = []
    baseline_index = 1
    while baseline_index <= len(points):
        point = points[baseline_index - 1]
        rebuilt.append(point)
        issue: SegmentIssue | None = long_jumps_by_start.get(baseline_index)
        if issue is not None and baseline_index < len(points):
            bridge = _turn_aware_astar(free_mask, issue.start, issue.end, config=config)
            if bridge is None:
                attempts.append(ReconnectAttempt(issue.start_index, issue.end_index, issue.length_px, 0, "failed"))
            else:
                inserted = bridge[1:-1]
                rebuilt.extend(inserted)
                attempts.append(ReconnectAttempt(issue.start_index, issue.end_index, issue.length_px, len(inserted), "reconnected"))
        baseline_index += 1

    after_metrics = path_metrics(rebuilt, free_mask, coverage_width_px=config.coverage_width_px).to_dict()
    after_diagnostics = diagnose_path(
        rebuilt,
        resolution_m_per_px=config.resolution_m_per_px,
        coverage_width_px=config.coverage_width_px,
        long_jump_factor=config.long_jump_factor,
    )
    return ReconnectResult(
        points=tuple(rebuilt),
        attempts=tuple(attempts),
        before_metrics=before_metrics,
        after_metrics=after_metrics,
        before_long_jump_count=len(before_diagnostics.long_jumps),
        after_long_jump_count=len(after_diagnostics.long_jumps),
    )
