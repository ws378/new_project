"""
房间间 TSP 连接优化器

对多房间覆盖路径进行 TSP 排序，最小化房间间转移距离：
  - 从全局起点（可选）到第一个房间的起点
  - 房间 i 终点 → 房间 j 起点
  - 使用 nearest-neighbor + 2-opt 求解
"""

from __future__ import annotations

import math
import random
from typing import Any


def _distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def _build_distance_matrix(
    rooms: list[dict[str, Any]],
    global_start: tuple[float, float] | None,
) -> tuple[list[list[float]], int]:
    """构建距离矩阵。

    Args:
        rooms: [{"id": int, "start": (x,y), "end": (x,y)}, ...]
        global_start: 全局起点 (x,y)，为 None 时以第一个房间为起点

    Returns:
        (matrix, offset)
        matrix[i][j] = i→j 的转移距离
        offset: 矩阵前 offset 行/列对应虚拟节点（全局起点）
    """
    n = len(rooms)
    offset = 1 if global_start is not None else 0
    size = n + offset
    mat = [[0.0] * size for _ in range(size)]

    # 全局起点 → 各房间起点
    if global_start is not None:
        gx, gy = global_start
        for j, room in enumerate(rooms):
            sx, sy = room["start"]
            mat[0][offset + j] = _distance(gx, gy, sx, sy)

    # 房间 i 终点 → 房间 j 起点
    for i in range(n):
        ex, ey = rooms[i]["end"]
        for j in range(n):
            if i == j:
                continue
            sx, sy = rooms[j]["start"]
            mat[offset + i][offset + j] = _distance(ex, ey, sx, sy)

    return mat, offset


def _nearest_neighbor(
    mat: list[list[float]],
    start_idx: int = 0,
) -> list[int]:
    """贪心最近邻构造初始解。"""
    n = len(mat)
    visited = {start_idx}
    tour = [start_idx]
    cur = start_idx
    while len(visited) < n:
        best, best_d = -1, float("inf")
        for j in range(n):
            if j not in visited and mat[cur][j] < best_d:
                best_d = mat[cur][j]
                best = j
        if best == -1:
            break
        tour.append(best)
        visited.add(best)
        cur = best
    return tour


def _tour_distance(tour: list[int], mat: list[list[float]]) -> float:
    return sum(mat[tour[i]][tour[i + 1]] for i in range(len(tour) - 1))


def _two_opt(tour: list[int], mat: list[list[float]]) -> list[int]:
    """2-opt 局部搜索优化。"""
    improved = True
    best = list(tour)
    n = len(best)
    while improved:
        improved = False
        for i in range(n - 1):
            for k in range(i + 2, n):
                new_tour = best[:i + 1] + best[i + 1:k + 1][::-1] + best[k + 1:]
                if _tour_distance(new_tour, mat) < _tour_distance(best, mat):
                    best = new_tour
                    improved = True
    return best


def _solve_tsp(mat: list[list[float]]) -> list[int]:
    """TSP 主求解器。"""
    best_tour = None
    best_dist = float("inf")
    starts = [0] if len(mat) < 50 else random.sample(range(len(mat)), min(50, len(mat)))
    for s in starts:
        tour = _nearest_neighbor(mat, start_idx=s)
        tour = _two_opt(tour, mat)
        d = _tour_distance(tour, mat)
        if d < best_dist:
            best_dist = d
            best_tour = tour
    return best_tour


def solve_room_tsp(
    rooms: list[dict[str, Any]],
    global_start: tuple[float, float] | None = None,
) -> list[int]:
    """求解房间 TSP 排序。

    Args:
        rooms: [{"id": int, "start": (x,y), "end": (x,y)}, ...]
        global_start: 可选的全局起点世界坐标 (x,y)

    Returns:
        rooms 索引的最佳访问顺序（排除了虚拟起点节点）
    """
    if len(rooms) <= 1:
        return [0]

    mat, offset = _build_distance_matrix(rooms, global_start)
    tour = _solve_tsp(mat)

    # 去掉虚拟节点偏移，返回原始房间索引
    room_order: list[int] = []
    for idx in tour:
        if idx >= offset:
            room_order.append(idx - offset)

    # 补全遗漏的房间
    visited = set(room_order)
    for i in range(len(rooms)):
        if i not in visited:
            room_order.append(i)

    return room_order
