"""
C* (C-Star) 全覆盖路径规划算法

论文: C*: A Coverage Path Planning Algorithm for Unknown Environments
      using Rapidly Covering Graphs (IEEE TRO, 2026)
作者: Zongyuan Shen, James P. Wilson, Shalabh Gupta

本实现遵循论文 Algorithm 1-4 的结构，在已知占据图上执行全覆盖路径规划。
"""

from __future__ import annotations

import math
import heapq
from collections import deque

import cv2
import numpy as np

from ...contracts import CoveragePlannerConfig, CoverageResult, Pose2D

Op = "Open"
Cl = "Closed"


class _RCGNode:
    """RCG 快速覆盖图节点"""

    def __init__(self, x: float, y: float, node_id: int, row: int, col: int):
        self.x = x
        self.y = y
        self.id = node_id
        self.row = row
        self.col = col
        self.lap = col
        self.state = Op
        self.left: _RCGNode | None = None
        self.right: _RCGNode | None = None
        self.up: _RCGNode | None = None
        self.down: _RCGNode | None = None

    def __repr__(self):
        return f"N{self.id}(r{self.row}c{self.col},{self.state})"


class _RCGGraph:
    """快速覆盖图"""

    def __init__(self):
        self.nodes: list[_RCGNode] = []
        self._unvisited = 0

    def add_node(self, n: _RCGNode):
        self.nodes.append(n)
        self._unvisited += 1

    def close_node(self, n: _RCGNode):
        if n.state == Op:
            n.state = Cl
            self._unvisited -= 1

    def done(self) -> bool:
        return self._unvisited <= 0


def _dist(a: _RCGNode, b: _RCGNode) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _detect_dominant_angle(binary: np.ndarray) -> float:
    edges = cv2.Canny(binary, 50, 150)
    lines = None
    for thresh in (100, 80, 60, 40, 20):
        lines = cv2.HoughLinesP(edges, 1, math.pi / 180, thresh, minLineLength=30)
        if lines is not None and len(lines) >= 4:
            break
    if lines is None or len(lines) < 4:
        return 0.0
    buckets: dict[int, float] = {}
    for line in lines:
        x1, y1, x2, y2 = line[0]
        L = math.hypot(x2 - x1, y2 - y1)
        a = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
        b = int(a // 5) * 5
        buckets[b] = buckets.get(b, 0) + L
    if not buckets:
        return 0.0
    dom = max(buckets, key=buckets.get)
    if dom > 90:
        dom -= 180
    return dom


def _build_affine(angle_deg: float, w: int, h: int) -> tuple[np.ndarray, np.ndarray]:
    c = (w / 2, h / 2)
    M = cv2.getRotationMatrix2D(c, angle_deg, 1.0)
    cos_a = abs(M[0, 0])
    sin_a = abs(M[0, 1])
    new_w = int(h * sin_a + w * cos_a)
    new_h = int(h * cos_a + w * sin_a)
    M[0, 2] += new_w / 2 - c[0]
    M[1, 2] += new_h / 2 - c[1]
    return M, cv2.invertAffineTransform(M)


def _build_graph(rotated: np.ndarray, step: int) -> _RCGGraph:
    """在旋转后的地图上铺网格建图"""
    h, w = rotated.shape
    free = rotated > 0
    graph = _RCGGraph()
    nid = 0

    ys = range(0, h, step)
    for ri, y in enumerate(ys):
        xs = range(0, w, step)
        for ci, x in enumerate(xs):
            yi = min(y, h - 1)
            xi = min(x, w - 1)
            if free[yi, xi]:
                node = _RCGNode(float(xi), float(yi), nid, ri, ci)
                nid += 1
                graph.add_node(node)

    for n in graph.nodes:
        right = next((m for m in graph.nodes if m.row == n.row and m.col == n.col + 1), None)
        if right is not None:
            n.right = right
            right.left = n
        down = next((m for m in graph.nodes if m.col == n.col and m.row == n.row + 1), None)
        if down is not None:
            n.down = down
            down.up = n

    return graph


def _select_goal(graph: _RCGGraph, cur: _RCGNode,
                 prefer_dir: str | None = None) -> tuple[_RCGNode | None, bool]:
    if graph.done():
        return None, False
    ordered = []
    for d in ("left", "up", "down", "right"):
        nb = getattr(cur, d, None)
        if nb is not None:
            ordered.append(nb)
    for nb in ordered:
        if nb.state == Op:
            return nb, False
    best, best_d = None, float("inf")
    for n in graph.nodes:
        if n.state == Op:
            d = _dist(cur, n)
            if d < best_d:
                best_d = d
                best = n
    if best is not None:
        return best, True
    return None, False


def _update_state(graph: _RCGGraph, cur: _RCGNode) -> _RCGNode | None:
    graph.close_node(cur)
    has_open = any(nb is not None and nb.state == Op
                   for nb in (cur.left, cur.right, cur.up, cur.down))
    if not has_open:
        candidates = [nb for nb in (cur.left, cur.right, cur.up, cur.down) if nb is not None]
        if candidates:
            return min(candidates, key=lambda nb: _dist(nb, cur))
    return None


def _astar(start: _RCGNode, goal: _RCGNode) -> list[_RCGNode] | None:
    if start is goal:
        return [start]

    def _heu(a, b):
        return _dist(a, b)

    open_set = [(_heu(start, goal), start.id, start)]
    came_from: dict[int, _RCGNode | None] = {start.id: None}
    g_score: dict[int, float] = {start.id: 0.0}

    while open_set:
        _, _, cur = heapq.heappop(open_set)
        if cur is goal:
            path: list[_RCGNode] = []
            while cur is not None:
                path.append(cur)
                cur = came_from[cur.id]
            return path[::-1]

        for nb in (cur.left, cur.right, cur.up, cur.down):
            if nb is None:
                continue
            dist = _dist(cur, nb)
            tentative = g_score[cur.id] + dist
            if nb.id not in g_score or tentative < g_score[nb.id]:
                g_score[nb.id] = tentative
                heapq.heappush(open_set, (tentative + _heu(nb, goal), nb.id, nb))
                came_from[nb.id] = cur

    return None


def _detect_holes(graph: _RCGGraph, cur: _RCGNode,
                  goal: _RCGNode | None, radius: int = 5) -> list[_RCGNode]:
    seen: set[int] = set()
    q: deque[_RCGNode] = deque([cur])
    seen.add(cur.id)
    holes: list[_RCGNode] = []
    depth = 0
    while q and depth < radius:
        for _ in range(len(q)):
            n = q.popleft()
            for nb in (n.left, n.right, n.up, n.down):
                if nb is not None and nb.id not in seen:
                    seen.add(nb.id)
                    if nb.state == Op:
                        holes.append(nb)
                    q.append(nb)
        depth += 1
    return holes


def _tsp(nodes: list[_RCGNode], start: _RCGNode) -> list[_RCGNode]:
    """贪心 TSP 排序"""
    if not nodes:
        return []
    remaining = set(nodes)
    current = start if start in remaining else nodes[0]
    remaining.discard(current)
    order = [current]
    while remaining:
        best = min(remaining, key=lambda n: _dist(current, n))
        order.append(best)
        remaining.remove(best)
        current = best
    return order


def _snap_to_free(path: list[tuple[float, float]],
                  free_mask: np.ndarray) -> list[tuple[float, float]]:
    h, w = free_mask.shape
    out: list[tuple[float, float]] = []
    for x, y in path:
        xi, yi = int(round(x)), int(round(y))
        if 0 <= yi < h and 0 <= xi < w and free_mask[yi, xi]:
            out.append((float(x), float(y)))
        else:
            snapped = _nearest_free(xi, yi, free_mask)
            if snapped is not None:
                out.append((float(snapped[0]), float(snapped[1])))
            else:
                if out:
                    out.append(out[-1])
    return out


def _nearest_free(cx: int, cy: int, free: np.ndarray) -> tuple[int, int] | None:
    h, w = free.shape
    if 0 <= cx < w and 0 <= cy < h and free[cy, cx]:
        return cx, cy
    for r in range(1, max(w, h)):
        for dx in range(-r, r + 1):
            for dy in (-r, r):
                x, y = cx + dx, cy + dy
                if 0 <= x < w and 0 <= y < h and free[y, x]:
                    return x, y
        for dy in range(-r + 1, r):
            for dx in (-r, r):
                x, y = cx + dx, cy + dy
                if 0 <= x < w and 0 <= y < h and free[y, x]:
                    return x, y
    return None


def _to_coords(path: list[_RCGNode]) -> list[tuple[float, float]]:
    return [(n.x, n.y) for n in path]


class CStarTspCoveragePlanner:
    """C* 全覆盖路径规划器（TSP 版本）"""

    def __init__(self, config: CoveragePlannerConfig):
        self.cfg = config

    def plan(
        self,
        room_map: np.ndarray,
        map_resolution: float,
        starting_position: tuple[float, float],
        map_origin: tuple[float, float] = (0.0, 0.0),
    ) -> CoverageResult:
        try:
            return self._run(room_map, map_resolution, starting_position, map_origin)
        except Exception as e:
            return CoverageResult.failure_result(1, f"C* 错误: {e}")

    def _run(self, room_map: np.ndarray, res: float,
             start: tuple[float, float],
             origin: tuple[float, float] = (0.0, 0.0)) -> CoverageResult:
        cov_w = float(getattr(self.cfg, "coverage_width_m", 0.5))
        step = max(int(round(cov_w / res)), 2)

        binary = (room_map > 0).astype(np.uint8) * 255
        angle = 0.0
        M_fwd, M_inv = _build_affine(angle, binary.shape[1], binary.shape[0])
        rotated = cv2.warpAffine(binary, M_fwd, (binary.shape[1], binary.shape[0]),
                                 flags=cv2.INTER_NEAREST,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=0)

        graph = _build_graph(rotated, step)
        if not graph.nodes:
            return CoverageResult.failure_result(1, "C*: 自由空间无节点")

        sp = M_fwd @ np.array([start[0], start[1], 1.0])
        cur = min(graph.nodes, key=lambda n: _dist(n, _RCGNode(sp[0], sp[1], -1, 0, 0)))

        tsp_order = [cur]
        visited = {cur.id}
        remaining = [n for n in graph.nodes if n.id != cur.id]
        while remaining:
            current = tsp_order[-1]
            best = min(remaining, key=lambda n: _dist(current, n))
            path = _astar(current, best)
            if path and len(path) > 1:
                for n in path[1:]:
                    if n.id not in visited:
                        tsp_order.append(n)
                        visited.add(n.id)
            else:
                tsp_order.append(best)
                visited.add(best.id)
            remaining = [n for n in remaining if n.id not in visited]

        path_px = _to_coords(tsp_order)

        out_px: list[tuple[float, float]] = []
        for x, y in path_px:
            p = M_inv @ np.array([x, y, 1.0])
            out_px.append((float(p[0]), float(p[1])))

        original_free = room_map > 0
        out_px = _snap_to_free(out_px, original_free)

        map_h = room_map.shape[0]
        ox, oy = origin
        out_world = []
        for i, (x, y) in enumerate(out_px):
            theta = 0.0
            if i < len(out_px) - 1:
                nx, ny = out_px[i + 1]
                theta = math.atan2(-(ny - y), nx - x)
            elif i > 0:
                px, py = out_px[i - 1]
                theta = math.atan2(-(y - py), x - px)
            wx = x * res + ox
            wy = (map_h - y) * res + oy
            out_world.append(Pose2D(wx, wy, theta))

        return CoverageResult.success_result(out_world, out_px)
