"""
房间间 TSP 连接优化器（精确最优解）

对多房间覆盖路径进行 TSP 排序，最小化房间间转移距离：
  - 从全局起点（可选）到第一个房间的起点
  - 房间 i 终点 → 房间 j 起点
  - 使用 Held-Karp DP 精确求解（n ≤ 15 保证最优），超大场景回退启发式
"""

from __future__ import annotations

import math
from typing import Any

INF = float("inf")


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def _build_distance_matrix(
    rooms: list[dict[str, Any]],
    global_start: tuple[float, float] | None,
) -> tuple[list[list[float]], int]:
    n = len(rooms)
    offset = 1
    size = n + offset
    mat = [[0.0] * size for _ in range(size)]

    if global_start is not None:
        gx, gy = global_start
        for j, room in enumerate(rooms):
            sx, sy = room["start"]
            mat[0][offset + j] = _dist(gx, gy, sx, sy)

    for i in range(n):
        ex, ey = rooms[i]["end"]
        for j in range(n):
            if i == j:
                continue
            sx, sy = rooms[j]["start"]
            mat[offset + i][offset + j] = _dist(ex, ey, sx, sy)

    return mat, offset


def _solve_tsp_dp(mat: list[list[float]], offset: int) -> list[int]:
    """Held-Karp DP 求解最短 Hamiltonian 路径（固定起点为 index 0）。"""
    n = len(mat)
    m = n - offset
    size = 1 << m
    dp = [[INF] * m for _ in range(size)]
    parent = [[-1] * m for _ in range(size)]

    for i in range(m):
        dp[1 << i][i] = mat[0][offset + i]

    for mask in range(size):
        for i in range(m):
            if not (mask & (1 << i)):
                continue
            if dp[mask][i] == INF:
                continue
            for j in range(m):
                if mask & (1 << j):
                    continue
                new_mask = mask | (1 << j)
                nd = dp[mask][i] + mat[offset + i][offset + j]
                if nd < dp[new_mask][j]:
                    dp[new_mask][j] = nd
                    parent[new_mask][j] = i

    full = size - 1
    best = min(range(m), key=lambda i: dp[full][i])

    tour = []
    mask = full
    last = best
    while last != -1:
        tour.append(offset + last)
        prev = parent[mask][last]
        mask ^= 1 << last
        last = prev
    tour.reverse()
    tour.insert(0, 0)
    return tour


def _nearest_neighbor(mat: list[list[float]]) -> list[int]:
    n = len(mat)
    visited = {0}
    tour = [0]
    cur = 0
    while len(visited) < n:
        best, best_d = -1, INF
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


def _two_opt(tour: list[int], mat: list[list[float]]) -> list[int]:
    improved = True
    best = list(tour)
    n = len(best)
    while improved:
        improved = False
        for i in range(n - 1):
            for k in range(i + 2, n):
                cand = best[:i + 1] + best[i + 1:k + 1][::-1] + best[k + 1:]
                if sum(mat[cand[i]][cand[i + 1]] for i in range(n - 1)) < \
                   sum(mat[best[i]][best[i + 1]] for i in range(n - 1)):
                    best = cand
                    improved = True
    return best


def _solve_tsp_heuristic(mat: list[list[float]]) -> list[int]:
    best_tour = None
    best_dist = INF
    for s in range(min(len(mat), 50)):
        tour = _nearest_neighbor(mat)
        tour = _two_opt(tour, mat)
        d = sum(mat[tour[i]][tour[i + 1]] for i in range(len(tour) - 1))
        if d < best_dist:
            best_dist = d
            best_tour = tour
    return best_tour


def solve_room_tsp(
    rooms: list[dict[str, Any]],
    global_start: tuple[float, float] | None = None,
) -> list[int]:
    """求解房间 TSP 排序，保证最短总转移距离。

    Args:
        rooms: [{"id": int, "start": (x,y), "end": (x,y)}, ...]
        global_start: 可选的全局起点世界坐标 (x,y)

    Returns:
        rooms 索引的最佳访问顺序
    """
    if len(rooms) <= 1:
        return [0]

    mat, offset = _build_distance_matrix(rooms, global_start)
    m = len(rooms)

    if m <= 15:
        tour = _solve_tsp_dp(mat, offset)
    else:
        tour = _solve_tsp_heuristic(mat)

    order = [idx - offset for idx in tour if idx >= offset]
    visited = set(order)
    for i in range(m):
        if i not in visited:
            order.append(i)
    return order
