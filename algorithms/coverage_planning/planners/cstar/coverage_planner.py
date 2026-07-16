"""
C* (C-Star) 全覆盖路径规划算法

论文: C*: A Coverage Path Planning Algorithm for Unknown Environments
      using Rapidly Covering Graphs (IEEE TRO, 2026)
作者: Zongyuan Shen, James P. Wilson, Shalabh Gupta

本实现遵循论文 Algorithm 1-4 的结构，在已知占据图上执行全覆盖路径规划。
"""

from __future__ import annotations

import logging
import math
import bisect
from collections import deque

import cv2
import numpy as np

from ...contracts import CoveragePlannerConfig, CoverageResult, Pose2D

logger = logging.getLogger(__name__)

Op = "Open"
Cl = "Closed"


class _RCGNode:
    """RCG 快速覆盖图里的一个节点"""

    __slots__ = ("x", "y", "id", "row", "col", "lap", "family", "component",
                 "state", "left", "right", "up", "down")

    def __init__(self, x: float, y: float, node_id: int, row: int, col: int):
        self.x = x
        self.y = y
        self.id = node_id
        self.row = row
        self.col = col
        self.lap = col
        self.family = 0
        self.component = 0
        self.state = Op
        self.left: _RCGNode | None = None
        self.right: _RCGNode | None = None
        self.up: _RCGNode | None = None
        self.down: _RCGNode | None = None

    def __repr__(self):
        return f"N{self.id}(r{self.row}c{self.col},{self.state})"


class _RCGGraph:
    """快速覆盖图——装着一堆节点，记录还有几个没走"""

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
    """欧氏距离"""
    return math.hypot(a.x - b.x, a.y - b.y)


def _detect_dominant_angle(binary: np.ndarray) -> float:
    """找地图里墙的主方向——先把边找出来，再看这些边大多朝着哪个角度"""
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


def _build_affine(angle_deg: float, w: int, h: int) -> tuple[np.ndarray, np.ndarray, int, int]:
    """做一个旋转矩阵，能把地图转成主方向朝上。算的时候保证转了之后不会被切掉"""
    c = (w / 2, h / 2)
    M = cv2.getRotationMatrix2D(c, angle_deg, 1.0)
    cos_a = abs(M[0, 0])
    sin_a = abs(M[0, 1])
    new_w = max(int(h * sin_a + w * cos_a), 1)
    new_h = max(int(h * cos_a + w * sin_a), 1)
    M[0, 2] += new_w / 2 - c[0]
    M[1, 2] += new_h / 2 - c[1]
    return M, cv2.invertAffineTransform(M), new_w, new_h


def _cell_best_point(free: np.ndarray, cx: int, cy: int,
                     cell_size: int) -> tuple[int, int] | None:
    """在一个小方格里找最好的"落脚点"。如果中心点不在自由空间里，就找离障碍物最远的地方"""
    h, w = free.shape
    if 0 <= cy < h and 0 <= cx < w and free[cy, cx]:
        return cx, cy

    half = cell_size // 2
    upper = half - 1 if cell_size % 2 == 0 else half
    x0 = max(0, cx - half)
    x1 = min(w, cx + upper + 1)
    y0 = max(0, cy - half)
    y1 = min(h, cy + upper + 1)

    if x1 <= x0 or y1 <= y0:
        return None

    cell = free[y0:y1, x0:x1]
    if not np.any(cell):
        return None

    cell_u8 = cell.astype(np.uint8) * 255
    dist_map = cv2.distanceTransform(cell_u8, cv2.DIST_L2, 5)
    max_dist = dist_map.max()
    candidates = np.argwhere(dist_map == max_dist)
    best_dy, best_dx = int(candidates[0, 0]), int(candidates[0, 1])
    best_sq = (best_dx - half) ** 2 + (best_dy - half) ** 2

    for row in candidates[1:]:
        dy, dx = int(row[0]), int(row[1])
        sq = (dx - half) ** 2 + (dy - half) ** 2
        if sq < best_sq:
            best_sq = sq
            best_dx, best_dy = dx, dy

    return x0 + best_dx, y0 + best_dy


def _build_graph(rotated: np.ndarray, step: int,
                 contour_layers: int = 0, layer_gap: float = 0.5,
                 start_offset: float = 0.3,
                 min_perimeter_factor: float = 5.0,
                 min_node_dist_factor: float = 0.4,
                 match_dist_factor: float = 2.0,
                 connection_dist_factor: float = 2.5) -> _RCGGraph:
    """建图核心——沿着等高线撒节点，再把节点连起来"""
    h, w = rotated.shape
    free = rotated > 0
    binary_u8 = free.astype(np.uint8) * 255
    dist = cv2.distanceTransform(binary_u8, cv2.DIST_L2, 5)
    max_d = float(dist.max())
    min_perimeter = float(step) * min_perimeter_factor
    min_node_dist = float(step) * min_node_dist_factor
    match_dist = float(step) * match_dist_factor
    conn_max_d2 = (float(step) * connection_dist_factor) ** 2

    graph = _RCGGraph()
    nid = 0
    d = float(step) * start_offset
    layer_interval = float(step) * layer_gap
    raw_layers: list[list[_RCGNode]] = []
    d_values: list[float] = []
    family_ids: list[int] = []
    prev_centroids: dict[int, tuple[float, float]] = {}
    next_fid = 0

    if contour_layers > 0:
        num_layers = contour_layers
    else:
        num_layers = max(1, min(int(max_d / layer_interval), 8))

    for _ in range(num_layers):
        if d >= max_d:
            break
        mask = (dist >= d).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        if not contours:
            d += layer_interval
            continue

        curr_centroids: dict[int, tuple[float, float]] = {}
        new_layers: list[list[_RCGNode]] = []
        new_families: list[int] = []

        for contour in contours:
            pts = contour.squeeze(axis=1)
            if len(pts.shape) != 2 or len(pts) < 4:
                continue

            cum = [0.0]
            for i in range(1, len(pts)):
                dx = float(pts[i, 0]) - float(pts[i - 1, 0])
                dy = float(pts[i, 1]) - float(pts[i - 1, 1])
                cum.append(cum[-1] + math.hypot(dx, dy))
            total = cum[-1]

            if total < min_perimeter:
                continue

            cx = float(pts[:, 0].mean())
            cy = float(pts[:, 1].mean())

            best_fid = -1
            best_d2 = float("inf")
            for fid, (pcx, pcy) in prev_centroids.items():
                d2 = (cx - pcx) ** 2 + (cy - pcy) ** 2
                if d2 < best_d2:
                    best_d2 = d2
                    best_fid = fid
            if best_fid >= 0 and math.sqrt(best_d2) < match_dist:
                fid = best_fid
            else:
                fid = next_fid
                next_fid += 1

            curr_centroids[fid] = (cx, cy)

            layer: list[_RCGNode] = []
            prev_x = prev_y = None
            t = 0.0
            pos = 0
            while t < total:
                idx = bisect.bisect_left(cum, t)
                idx = min(idx, len(pts) - 1)
                x, y = float(pts[idx, 0]), float(pts[idx, 1])
                yi, xi = int(round(y)), int(round(x))
                if 0 <= yi < h and 0 <= xi < w and free[yi, xi]:
                    too_close = False
                    if prev_x is not None and math.hypot(x - prev_x, y - prev_y) < min_node_dist:
                        too_close = True
                    if not too_close:
                        for existing in graph.nodes:
                            if math.hypot(x - existing.x, y - existing.y) < min_node_dist:
                                too_close = True
                                break
                    if not too_close:
                        node = _RCGNode(x, y, nid, 0, pos)
                        node.family = fid
                        nid += 1
                        graph.add_node(node)
                        layer.append(node)
                        pos += 1
                        prev_x, prev_y = x, y
                t += float(step)

            if len(layer) >= 2:
                new_layers.append(layer)
                new_families.append(fid)

        raw_layers.extend(new_layers)
        family_ids.extend(new_families)
        d_values.extend([d] * len(new_layers))
        prev_centroids = curr_centroids
        d += layer_interval

    if not raw_layers:
        return graph

    centroids: list[tuple[float, float]] = []
    for layer in raw_layers:
        cx = sum(n.x for n in layer) / len(layer)
        cy = sum(n.y for n in layer) / len(layer)
        centroids.append((cx, cy))

    band_h = float(step)
    band_map: dict[int, list[int]] = {}
    for i in range(len(raw_layers)):
        by = int(centroids[i][1] / band_h)
        band_map.setdefault(by, []).append(i)

    idx_list: list[int] = []
    for bi, by in enumerate(sorted(band_map.keys())):
        band = band_map[by]
        band.sort(key=lambda i: centroids[i][0])
        if bi % 2 == 1:
            band.reverse()
        idx_list.extend(band)

    layers = [raw_layers[i] for i in idx_list]
    for ri, layer in enumerate(layers):
        for n in layer:
            n.row = ri

    for layer in layers:
        for i in range(len(layer)):
            if i > 0:
                layer[i].left = layer[i - 1]
            if i < len(layer) - 1:
                layer[i].right = layer[i + 1]

    for k in range(len(layers) - 1):
        upper = layers[k]
        lower = layers[k + 1]
        for u in upper:
            best = min(lower, key=lambda n: (n.x - u.x) ** 2 + (n.y - u.y) ** 2)
            if (best.x - u.x) ** 2 + (best.y - u.y) ** 2 < conn_max_d2:
                u.down = best
                best.up = u

        if k % 2 == 0:
            p0, p1 = upper[-1], lower[-1]
            if (p1.x - p0.x) ** 2 + (p1.y - p0.y) ** 2 < (step * 2.5) ** 2:
                p0.down = p1
                p1.up = p0
        else:
            p0, p1 = upper[0], lower[0]
            if (p1.x - p0.x) ** 2 + (p1.y - p0.y) ** 2 < (step * 2.5) ** 2:
                p0.down = p1
                p1.up = p0

    return graph


def _boustrophedon_order(graph: _RCGGraph,
                         start: _RCGNode | None = None,
                         turn_weight: float = 0.0) -> list[_RCGNode]:
    """分层贪心顺序：走完一层后，全局找最近未访问节点，跳到那一层继续走。"""
    rows: dict[int, list[_RCGNode]] = {}
    for n in graph.nodes:
        rows.setdefault(n.row, []).append(n)
    for ri in rows:
        rows[ri].sort(key=lambda n: n.col)

    remaining = set(rows.keys())
    if not remaining:
        return []

    current_ri = start.row if start is not None and start.row in rows else min(remaining)
    order: list[_RCGNode] = []

    while remaining:
        row = rows[current_ri]
        if not order:
            if start is not None and start in row:
                ci = row.index(start)
                order.extend(row[ci:])
                order.extend(row[:ci])
            else:
                order.extend(row)
        else:
            prev_last = order[-1]
            prev_dir = _prev_direction(order)
            closest = _best_entry(prev_last, row, prev_dir, turn_weight)
            ci = row.index(closest)
            order.extend(row[ci:])
            order.extend(reversed(row[:ci]))

        remaining.discard(current_ri)
        if not remaining:
            break

        prev_last = order[-1]
        current_ri = min(remaining,
                         key=lambda ri: min(_dist(prev_last, n) for n in rows[ri]))

    return order


def _prev_direction(order: list[_RCGNode]) -> float | None:
    if len(order) < 2:
        return None
    dx = order[-1].x - order[-2].x
    dy = order[-1].y - order[-2].y
    if dx == 0.0 and dy == 0.0:
        return None
    return math.atan2(dy, dx)


def _best_entry(prev_last: _RCGNode, candidates: list[_RCGNode],
                prev_dir: float | None, turn_weight: float) -> _RCGNode:
    if turn_weight <= 0 or prev_dir is None:
        return min(candidates, key=lambda n: _dist(prev_last, n))

    def _score(n):
        d = _dist(prev_last, n)
        a = math.atan2(n.y - prev_last.y, n.x - prev_last.x)
        diff = abs(a - prev_dir)
        if diff > math.pi:
            diff = 2 * math.pi - diff
        return d * (1.0 + (1.0 - math.cos(diff)) * turn_weight)

    return min(candidates, key=_score)


def _label_connected_components(graph: _RCGGraph):
    """对图的节点按边连通性标上分量 ID。"""
    cid = 0
    for n in graph.nodes:
        if n.component != 0:
            continue
        cid += 1
        stack = [n]
        n.component = cid
        while stack:
            cur = stack.pop()
            for nb in (cur.left, cur.right, cur.up, cur.down):
                if nb is not None and nb.component == 0:
                    nb.component = cid
                    stack.append(nb)


def _grid_path(ax: float, ay: float, bx: float, by: float,
               free: np.ndarray, step: int) -> list[tuple[float, float]]:
    """像素级 A*：在 free 地图上从 (ax,ay) 走到 (bx,by)，步长 step。"""
    h, w = free.shape
    step = max(2, step)
    ais, ajs = int(round(ay / step)), int(round(ax / step))
    bis, bjs = int(round(by / step)), int(round(bx / step))

    def _valid(i, j):
        y = i * step
        x = j * step
        return 0 <= y < h and 0 <= x < w and free[int(y), int(x)]

    start = (ais, ajs)
    goal = (bis, bjs)

    if not _valid(ais, ajs) or not _valid(bis, bjs):
        return []

    import heapq
    open_set = [(0.0, start)]
    came_from: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    g: dict[tuple[int, int], float] = {start: 0.0}

    while open_set:
        _, cur = heapq.heappop(open_set)
        if cur == goal:
            path: list[tuple[int, int]] = []
            while cur is not None:
                path.append(cur)
                cur = came_from[cur]
            path.reverse()
            return [(j * step + step / 2.0, i * step + step / 2.0) for i, j in path]

        ci, cj = cur
        for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1),
                       (-1, -1), (-1, 1), (1, -1), (1, 1)]:
            ni, nj = ci + di, cj + dj
            if not _valid(ni, nj):
                continue
            cost = g[cur] + (1.0 if di == 0 or dj == 0 else 1.414)
            key = (ni, nj)
            if cost < g.get(key, float("inf")):
                g[key] = cost
                h_cost = math.hypot(nj - bjs, ni - bis)
                heapq.heappush(open_set, (cost + h_cost, key))
                came_from[key] = cur

    return []


def _select_goal(graph: _RCGGraph, cur: _RCGNode,
                 prefer_dir: str | None = None) -> tuple[_RCGNode | None, bool]:
    """Algorithm 1: 目标节点选择——优先走没走过的邻居，优先级左 > 上 > 下 > 右。
    返回 (goal, 是否发生撤退)"""
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

    best = min((n for n in graph.nodes if n.state == Op),
               key=lambda n: n.id, default=None)
    if best is not None:
        return best, True
    return None, False


def _update_state(graph: _RCGGraph, cur: _RCGNode):
    """Algorithm 2: 节点状态更新——标记当前节点已关闭，
    如果所有邻居都已关闭则创建链接节点（向后退一格）"""
    graph.close_node(cur)
    has_open = any(nb is not None and nb.state == Op
                   for nb in (cur.left, cur.right, cur.up, cur.down))
    if not has_open:
        candidates = [nb for nb in (cur.left, cur.right, cur.up, cur.down)
                      if nb is not None]
        if candidates:
            return min(candidates, key=lambda nb: _dist(nb, cur))
    return None


def _astar(start: _RCGNode, goal: _RCGNode) -> list[_RCGNode] | None:
    """A* 在图边上找路径"""
    if start is goal:
        return [start]

    def _heu(a, b):
        return _dist(a, b)

    import heapq
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
    """Algorithm 3: 覆盖孔洞检测——在 cur 周围 radius 范围内找未访问节点"""
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


def _snap_to_free(path: list[tuple[float, float]],
                  free_mask: np.ndarray) -> list[tuple[float, float]]:
    """把路径里落在障碍物上的点拉到最近的自由像素上"""
    h, w = free_mask.shape
    out: list[tuple[float, float]] = []
    i = 0
    for x, y in path:
        xi, yi = int(round(x)), int(round(y))
        if 0 <= yi < h and 0 <= xi < w and free_mask[yi, xi]:
            out.append((float(x), float(y)))
        else:
            snapped = _nearest_free(xi, yi, free_mask)
            if snapped is not None:
                out.append((float(snapped[0]), float(snapped[1])))
            else:
                if i > 0:
                    out.append(out[-1])
    return out


def _nearest_free(cx: int, cy: int, free: np.ndarray) -> tuple[int, int] | None:
    """从 (cx, cy) 螺旋向外搜索，找最近的自由像素"""
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
    """把节点列表转成坐标列表"""
    return [(n.x, n.y) for n in path]


class CStarRectCoveragePlanner:
    """C* 全覆盖路径规划器（矩形算法版）"""

    def __init__(self, config: CoveragePlannerConfig):
        self.cfg = config
        self._free_bin: np.ndarray | None = None
        self._res: float = 0.05

    def _astar_path(self, start: tuple[int, int],
                    goal: tuple[int, int]) -> list[tuple[int, int]]:
        """像素级 4-方向 A*，匹配 region_basic_improved 实现。"""
        import heapq
        sx, sy = start
        gx, gy = goal
        h, w = self._free_bin.shape
        if not (0 <= sx < w and 0 <= sy < h) or not (0 <= gx < w and 0 <= gy < h):
            return [start, goal]
        free = self._free_bin
        if free[sy, sx] == 0 or free[gy, gx] == 0:
            return [start, goal]
        open_set = [(0.0, sx, sy)]
        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        g_score: dict[tuple[int, int], float] = {(sx, sy): 0.0}
        while open_set:
            _, cx, cy = heapq.heappop(open_set)
            if (cx, cy) == (gx, gy):
                pts = [(gx, gy)]
                while (cx, cy) in came_from:
                    cx, cy = came_from[(cx, cy)]
                    pts.append((cx, cy))
                pts.reverse()
                if pts[0] != (sx, sy):
                    pts.insert(0, (sx, sy))
                return pts
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cx + dx, cy + dy
                if nx < 0 or nx >= w or ny < 0 or ny >= h:
                    continue
                if free[ny, nx] == 0:
                    continue
                ng = g_score[(cx, cy)] + 1.0
                if (nx, ny) not in g_score or ng < g_score[(nx, ny)]:
                    came_from[(nx, ny)] = (cx, cy)
                    g_score[(nx, ny)] = ng
                    heapq.heappush(open_set, (ng + math.hypot(gx - nx, gy - ny), nx, ny))
        return [start, goal]

    def _bridge_jumps(self, nodes: list[_RCGNode]) -> list[_RCGNode]:
        """桥接：距离 > 3.5m 时 A* 寻路 + 插值，保留两端点。"""
        if len(nodes) < 2:
            return nodes
        layer_bridge = getattr(self.cfg, "layer_bridge_enable", True)
        if not layer_bridge:
            logger.info("bridge_jumps disabled by layer_bridge_enable=False")
            return nodes
        n_interp = max(1, int(getattr(self.cfg, "jump_bridge_interpolations", 2)))
        jump_px = 3.5 / self._res if self._res > 0 else 70.0
        result: list[_RCGNode] = [nodes[0]]
        bridge_count = 0
        for i in range(1, len(nodes)):
            b = nodes[i]
            a = result[-1]
            d = math.hypot(a.x - b.x, a.y - b.y)
            if d > jump_px:
                pts = self._astar_path(
                    (int(round(a.x)), int(round(a.y))),
                    (int(round(b.x)), int(round(b.y))),
                )
                if pts and len(pts) > 2:
                    n_total = len(pts)
                    for k in range(1, n_interp + 1):
                        idx = int(round(k * (n_total - 1) / (n_interp + 1)))
                        idx = max(1, min(n_total - 2, idx))
                        result.append(_RCGNode(
                            float(pts[idx][0]), float(pts[idx][1]), -1, -1, -1))
                    bridge_count += 1
            result.append(_RCGNode(b.x, b.y, -1, b.row, b.col))
        if bridge_count:
            logger.info("bridge_jumps: %d gaps > %.1fm bridged, %d→%d nodes",
                        bridge_count, 3.5, len(nodes), len(result))
        return result

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
        if getattr(self.cfg, "auto_rotate", True):
            angle = _detect_dominant_angle(binary)
        else:
            angle = 0.0
        M_fwd, M_inv, out_w, out_h = _build_affine(angle, binary.shape[1], binary.shape[0])
        rotated = cv2.warpAffine(binary, M_fwd, (out_w, out_h),
                                 flags=cv2.INTER_NEAREST,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=0)

        cl = int(getattr(self.cfg, "contour_layers", 0))
        lg = float(getattr(self.cfg, "contour_layer_gap", 0.5))
        so = float(getattr(self.cfg, "contour_start_offset", 0.3))
        mp = float(getattr(self.cfg, "min_perimeter_factor", 5.0))
        nd = float(getattr(self.cfg, "min_node_dist_factor", 0.4))
        mf = float(getattr(self.cfg, "match_dist_factor", 2.0))
        cf = float(getattr(self.cfg, "connection_dist_factor", 2.5))
        graph = _build_graph(rotated, step, contour_layers=cl, layer_gap=lg,
                             start_offset=so, min_perimeter_factor=mp,
                             min_node_dist_factor=nd, match_dist_factor=mf,
                             connection_dist_factor=cf)
        if not graph.nodes:
            return CoverageResult.failure_result(1, "C*: 自由空间无节点")

        sp = M_fwd @ np.array([start[0], start[1], 1.0])
        sx, sy = float(sp[0]), float(sp[1])
        free_rotated = rotated > 0
        cur = None
        if (0 <= int(round(sy)) < out_h and 0 <= int(round(sx)) < out_w and
            free_rotated[int(round(sy)), int(round(sx))]):
            nearest = min(graph.nodes, key=lambda n: _dist(n, _RCGNode(sx, sy, -1, 0, 0)))
            col = nearest.col - 0.5 if nearest.left is None else (nearest.left.col + nearest.col) / 2.0
            cur = _RCGNode(sx, sy, max(n.id for n in graph.nodes) + 1, nearest.row, col)
            cur.family = nearest.family
            graph.add_node(cur)

        if cur is None:
            cur = min(graph.nodes, key=lambda n: _dist(n, _RCGNode(sx, sy, -1, 0, 0)))

        if getattr(self.cfg, "debug_show_nodes_only", False):
            debug_node_coords = []
            for n in graph.nodes:
                p = M_inv @ np.array([n.x, n.y, 1.0])
                debug_node_coords.append((float(p[0]), float(p[1])))
            return CoverageResult.success_result(
                [], [], runtime_metadata={"debug_all_nodes": debug_node_coords})

        groups: dict[int, list[_RCGNode]] = {}
        for n in graph.nodes:
            groups.setdefault(n.family, []).append(n)
        group_order = sorted(groups.keys(),
                             key=lambda g: min(_dist(n, cur) for n in groups[g]))
        bridge_astar = getattr(self.cfg, "bridge_astar_enable", False)
        turn_weight = float(getattr(self.cfg, "boustrophedon_turn_weight", 0.0))
        path_nodes: list[_RCGNode] = []
        for gi in group_order:
            sg = _RCGGraph()
            sg.nodes = groups[gi]
            part = _boustrophedon_order(sg,
                                        start=cur if not path_nodes else None,
                                        turn_weight=turn_weight)

            if bridge_astar and path_nodes and part:
                a, b = path_nodes[-1], part[0]
                bridge = _grid_path(a.x, a.y, b.x, b.y, rotated > 0, step)
                if bridge:
                    for bx, by in bridge[1:]:
                        path_nodes.append(_RCGNode(bx, by, -1, -1, -1))
            path_nodes.extend(part)

        self._free_bin = rotated > 0
        self._res = res
        path_nodes = self._bridge_jumps(path_nodes)

        path_px = _to_coords(path_nodes)

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
