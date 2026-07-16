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
import bisect
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
        self.family = -1
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
    new_w = max(int(h * sin_a + w * cos_a), 1)
    new_h = max(int(h * cos_a + w * sin_a), 1)
    M[0, 2] += new_w / 2 - c[0]
    M[1, 2] += new_h / 2 - c[1]
    return M, cv2.invertAffineTransform(M)


def _build_graph(rotated: np.ndarray, step: int) -> _RCGGraph:
    """牛耕往复式扫描线取样建图"""
    h, w = rotated.shape
    free = rotated > 0
    free_ys, free_xs = np.where(free)
    if len(free_ys) == 0:
        return _RCGGraph()

    min_y, max_y = int(free_ys.min()), int(free_ys.max())
    min_x, max_x = int(free_xs.min()), int(free_xs.max())
    area_w = max_x - min_x + 1
    area_h = max_y - min_y + 1

    sweep_static = area_w < area_h
    if sweep_static:
        num_sweeps = max(1, area_w // step)
        spacing = area_w / num_sweeps if num_sweeps > 0 else step
    else:
        num_sweeps = max(1, area_h // step)
        spacing = area_h / num_sweeps if num_sweeps > 0 else step

    graph = _RCGGraph()
    nid = 0
    raw_layers: list[list[_RCGNode]] = []

    for i in range(num_sweeps + 1):
        if sweep_static:
            line_x = min_x + i * spacing
            pts = _sample_col(free, int(round(line_x)), min_y, max_y, step)
        else:
            line_y = min_y + i * spacing
            pts = _sample_row(free, int(round(line_y)), min_x, max_x, step)
        if not pts:
            continue
        layer = [_RCGNode(x, y, nid + j, i, j) for j, (x, y) in enumerate(pts)]
        for n in layer:
            graph.add_node(n)
        nid += len(layer)
        raw_layers.append(layer)

    if not raw_layers:
        return graph

    for layer in raw_layers:
        for i in range(len(layer)):
            if i > 0:
                layer[i].left = layer[i - 1]
            if i < len(layer) - 1:
                layer[i].right = layer[i + 1]

    conn_max_d2 = (float(step) * 2.5) ** 2
    for k in range(len(raw_layers) - 1):
        upper = raw_layers[k]
        lower = raw_layers[k + 1]
        for u in upper:
            best = min(lower, key=lambda n: (n.x - u.x) ** 2 + (n.y - u.y) ** 2)
            if (best.x - u.x) ** 2 + (best.y - u.y) ** 2 < conn_max_d2:
                u.down = best
                best.up = u

    return graph


def _sample_row(free: np.ndarray, row_y: int, x0: int, x1: int, step: int) -> list[tuple[float, float]]:
    if row_y < 0 or row_y >= free.shape[0]:
        return []
    free_indices = np.where(free[row_y, x0:x1 + 1])[0]
    if len(free_indices) == 0:
        return []
    segs = _segments(free_indices)
    pts: list[tuple[float, float]] = []
    for seg_start, seg_end in segs:
        for px in range(seg_start, seg_end + 1, step):
            pts.append((float(x0 + px), float(row_y)))
        last = (float(x0 + seg_end), float(row_y))
        if not pts or pts[-1] != last:
            pts.append(last)
    return pts


def _sample_col(free: np.ndarray, col_x: int, y0: int, y1: int, step: int) -> list[tuple[float, float]]:
    if col_x < 0 or col_x >= free.shape[1]:
        return []
    free_indices = np.where(free[y0:y1 + 1, col_x])[0]
    if len(free_indices) == 0:
        return []
    segs = _segments(free_indices)
    pts: list[tuple[float, float]] = []
    for seg_start, seg_end in segs:
        for py in range(seg_start, seg_end + 1, step):
            pts.append((float(col_x), float(y0 + py)))
        last = (float(col_x), float(y0 + seg_end))
        if not pts or pts[-1] != last:
            pts.append(last)
    return pts


def _segments(indices: np.ndarray) -> list[tuple[int, int]]:
    if len(indices) == 0:
        return []
    segs: list[tuple[int, int]] = []
    start = int(indices[0])
    prev = int(indices[0])
    for i in indices[1:]:
        i_int = int(i)
        if i_int != prev + 1:
            segs.append((start, prev))
            start = i_int
        prev = i_int
    segs.append((start, prev))
    return segs


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


def _remove_close_nodes(path: list[_RCGNode], res: float,
                        min_dist_m: float = 0.5) -> list[_RCGNode]:
    """Remove nodes that are too close to their predecessor (距离 < min_dist_m)."""
    if len(path) < 2:
        return path
    thresh_px = min_dist_m / res
    out = [path[0]]
    for i in range(1, len(path)):
        if math.hypot(path[i].x - out[-1].x, path[i].y - out[-1].y) >= thresh_px:
            out.append(path[i])
    if out[-1] is not path[-1]:
        out.append(path[-1])
    return out




def _remove_isolated_nodes(path: list[_RCGNode], res: float,
                           max_jump_m: float = 3.0) -> list[_RCGNode]:
    """Remove isolated nodes whose predecessor and successor distances both exceed threshold.

    A → B → C: if AB > max_jump AND BC > max_jump, remove B.
    After removal, A → C → D is re-checked recursively.
    """
    if len(path) < 3:
        return path
    thresh_px = max_jump_m / res
    out = [path[0]]
    for i in range(1, len(path) - 1):
        prev = out[-1]
        cur = path[i]
        nxt = path[i + 1]
        d_prev = math.hypot(cur.x - prev.x, cur.y - prev.y)
        d_next = math.hypot(nxt.x - cur.x, nxt.y - cur.y)
        if d_prev <= thresh_px or d_next <= thresh_px:
            out.append(cur)
    out.append(path[-1])
    return out


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
        step_m = float(getattr(self.cfg, "step", 0.5))
        step = max(int(round(step_m / res)), 2)

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
        turn_weight = float(getattr(self.cfg, "turn_weight", 0.0))
        prev_dir = None
        while remaining:
            current = tsp_order[-1]

            if prev_dir is not None and turn_weight > 0:

                def _cost(n, _c=current, _p=prev_dir):
                    dx = n.x - _c.x
                    dy = n.y - _c.y
                    d = math.hypot(dx, dy)
                    a = math.atan2(dy, dx)
                    diff = abs(a - _p)
                    if diff > math.pi:
                        diff = 2 * math.pi - diff
                    return d + diff * diff * turn_weight

                best = min(remaining, key=_cost)
            else:
                best = min(remaining, key=lambda n: _dist(current, n))

            dx = best.x - current.x
            dy = best.y - current.y
            if dx != 0.0 or dy != 0.0:
                prev_dir = math.atan2(dy, dx)

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

        tsp_order = _remove_close_nodes(tsp_order, res, min_dist_m=0.5)
        tsp_order = _remove_isolated_nodes(tsp_order, res,
                                           max_jump_m=1.5)
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
