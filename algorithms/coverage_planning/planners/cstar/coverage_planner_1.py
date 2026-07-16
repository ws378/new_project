"""
C* (C-Star) 全覆盖路径规划算法

论文: C*: A Coverage Path Planning Algorithm for Unknown Environments
      using Rapidly Covering Graphs (IEEE TRO, 2026)
作者: Zongyuan Shen, James P. Wilson, Shalabh Gupta

本实现遵循论文 Algorithm 1-4 的结构，在已知占据图上执行全覆盖路径规划。
"""

from __future__ import annotations

import math
import bisect
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


def _build_affine(angle_deg: float, w: int, h: int) -> tuple[np.ndarray, np.ndarray, int, int]:
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
                 connection_dist_factor: float = 2.5,
                 gap_fill_threshold_m: float = 0.3,
                 gap_fill_node_count: int = 5) -> _RCGGraph:
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

        curr_centroids = {}
        new_layers = []

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

        raw_layers.extend(new_layers)
        prev_centroids = curr_centroids
        d += layer_interval

    # ── 窄通道检测与车道线层 ──
    gap_fill_node_count = max(2, gap_fill_node_count)
    passage_midlines = _detect_narrow_passages(dist, step, gap_fill_threshold_m)
    passage_layer_flags = [False] * len(raw_layers)
    for midline in passage_midlines:
        if len(midline) < 2:
            continue
        lane: list[_RCGNode] = []
        for i in range(len(midline)):
            x, y = float(midline[i, 0]), float(midline[i, 1])
            yi, xi = int(round(y)), int(round(x))
            if 0 <= yi < h and 0 <= xi < w and free[yi, xi]:
                node = _RCGNode(x, y, nid, 0, i)
                node.family = -1
                nid += 1
                graph.add_node(node)
                lane.append(node)
        if len(lane) >= 2:
            passage_layer_flags.append(True)
            raw_layers.append(lane)
        else:
            passage_layer_flags.append(False)

    if not raw_layers:
        return graph

    centroids = []
    for li, layer in enumerate(raw_layers):
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

    # ── 修复车道线层 up/down：只保留两端连接 ──
    passage_in_layers = [
        idx_list.index(pi) for pi, flag in enumerate(passage_layer_flags)
        if flag and pi in idx_list
    ]
    for li in passage_in_layers:
        lane = layers[li]
        for n in lane[1:-1]:
            n.up = None
            n.down = None
        if li > 0:
            _connect_to_nearest(lane[0], layers[li - 1], conn_max_d2, upward=True)
        if li < len(layers) - 1:
            _connect_to_nearest(lane[-1], layers[li + 1], conn_max_d2, upward=False)

    return graph


def _connect_to_nearest(node: _RCGNode, target_layer: list[_RCGNode],
                        max_d2: float, upward: bool) -> None:
    best = min(target_layer, key=lambda n: (n.x - node.x) ** 2 + (n.y - node.y) ** 2)
    if (best.x - node.x) ** 2 + (best.y - node.y) ** 2 < max_d2:
        if upward:
            node.up = best
            best.down = node
        else:
            node.down = best
            best.up = node


def _detect_narrow_passages(dist: np.ndarray, step: int,
                            gap_fill_threshold_m: float) -> list[np.ndarray]:
    """检测窄通道，返回中线点列（已排序）列表"""
    h, w = dist.shape
    gap_px = max(3, int(round(gap_fill_threshold_m)))

    narrow = (dist > 0) & (dist < gap_px)
    narrow = narrow.astype(np.uint8)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    narrow = cv2.morphologyEx(narrow, cv2.MORPH_CLOSE, kernel)
    narrow = cv2.morphologyEx(narrow, cv2.MORPH_OPEN, kernel)

    num_labels, labels = cv2.connectedComponents(narrow)
    if num_labels <= 1:
        return []

    passages: list[np.ndarray] = []
    for label_id in range(1, num_labels):
        mask = (labels == label_id).astype(np.uint8) * 255

        erosion_kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
        skelet = mask.copy()
        while True:
            eroded = cv2.erode(skelet, erosion_kernel)
            if cv2.countNonZero(eroded) < 2:
                break
            skelet = eroded

        pts = np.argwhere(skelet > 0)
        if len(pts) < 4:
            continue

        ordered = _order_skeleton_pts(pts)

        valid: list[list[float]] = []
        for y, x in ordered:
            yi, xi = int(round(y)), int(round(x))
            if 0 <= yi < h and 0 <= xi < w and _obstacle_on_both_sides(xi, yi, dist):
                valid.append([float(x), float(y)])
        if len(valid) >= 3:
            passages.append(np.array(valid))

    return passages


def _order_skeleton_pts(pts: np.ndarray) -> list[tuple[float, float]]:
    """贪心最近邻排序骨架点"""
    if len(pts) < 3:
        return [(float(p[1]), float(p[0])) for p in pts]

    ordered = [pts[0]]
    used = {0}
    curr = pts[0]
    while len(used) < len(pts):
        best_d = float("inf")
        best_i = -1
        for i in range(len(pts)):
            if i in used:
                continue
            d = (pts[i][0] - curr[0]) ** 2 + (pts[i][1] - curr[1]) ** 2
            if d < best_d:
                best_d = d
                best_i = i
        if best_i < 0:
            break
        used.add(best_i)
        curr = pts[best_i]
        ordered.append(curr)

    return [(float(p[1]), float(p[0])) for p in ordered]


def _obstacle_on_both_sides(x: int, y: int, dist: np.ndarray) -> bool:
    """检查自由点 (x,y) 是否两侧皆有障碍物。"""
    h, w = dist.shape
    d = float(dist[y, x])
    if d <= 1.0:
        return False

    margin = max(2.0, d * 0.5)
    check_d = d + margin

    has_obstacle = [False, False, False, False]
    for i, (dx, dy) in enumerate([(1, 0), (0, 1), (-1, 0), (0, -1)]):
        xx = int(round(x + dx * check_d))
        yy = int(round(y + dy * check_d))
        if 0 <= yy < h and 0 <= xx < w and dist[yy, xx] < 0.5:
            has_obstacle[i] = True

    return (has_obstacle[0] and has_obstacle[2]) or (has_obstacle[1] and has_obstacle[3])


def _boustrophedon_order(graph: _RCGGraph,
                         start: _RCGNode | None = None) -> list[_RCGNode]:
    rows_dict: dict[int, list[tuple[int, _RCGNode]]] = {}
    for n in graph.nodes:
        rows_dict.setdefault(n.row, []).append((n.col, n))
    sorted_ris = sorted(rows_dict.keys())
    order: list[_RCGNode] = []
    for idx, ri in enumerate(sorted_ris):
        row = sorted(rows_dict[ri], key=lambda x: x[0])
        if idx % 2 == 0:
            order.extend(n for _, n in row)
        else:
            order.extend(n for _, n in reversed(row))
    if start is not None:
        try:
            idx = order.index(start)
            order = order[idx:] + order[:idx]
        except ValueError:
            pass
    return order


def _label_connected_components(graph: _RCGGraph):
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
    h, w = free.shape
    step = max(2, step)
    ais, ajs = int(round(ay / step)), int(round(ax / step))
    bis, bjs = int(round(by / step)), int(round(bx / step))

    def _valid(i, j):
        y = i * step
        x = j * step
        return 0 <= y < h and 0 <= x < w and free[int(y), int(x)]

    if not _valid(ais, ajs) or not _valid(bis, bjs):
        return []

    open_set = [(0.0, (ais, ajs))]
    came_from: dict[tuple[int, int], tuple[int, int] | None] = {(ais, ajs): None}
    g: dict[tuple[int, int], float] = {(ais, ajs): 0.0}

    while open_set:
        _, cur = heapq.heappop(open_set)
        if cur == (bis, bjs):
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


def _optimize_jumps(order: list[_RCGNode], window: int = 3) -> list[_RCGNode]:
    """对牛耕顺序中的跳点做局部 TSP 优化替换。"""
    jumps = []
    for i in range(1, len(order)):
        prev = order[i - 1]
        cur = order[i]
        if not any(cur is nb for nb in (prev.left, prev.right, prev.up, prev.down)):
            jumps.append(i)

    if not jumps:
        return order

    result = list(order)
    for j in range(len(jumps) - 1, -1, -1):
        i = jumps[j]
        L = max(0, i - window)
        R = min(len(result), i + window + 1)
        segment = result[L:R]
        best = list(segment)
        best_cost = sum(_dist(segment[k], segment[k + 1]) for k in range(len(segment) - 1))
        for k in range(1, len(segment)):
            rotated = segment[k:] + segment[:k]
            cost = sum(_dist(rotated[k], rotated[k + 1]) for k in range(len(rotated) - 1))
            if cost < best_cost:
                best_cost = cost
                best = rotated
        result[L:R] = best

    return result


def _compute_tangent_field(rotated: np.ndarray, sigma: float = 10.0) -> np.ndarray:
    """计算切线方向场，用于路径平滑"""
    free = (rotated > 0).astype(np.float64)
    dy, dx = np.gradient(free)
    mag = np.hypot(dx, dy)
    mask = mag > 1e-6
    dx = np.where(mask, dx / mag, 0.0)
    dy = np.where(mask, dy / mag, 0.0)
    tangent = np.stack([-dy, dx], axis=-1)
    if sigma > 0:
        tangent_x = cv2.GaussianBlur(tangent[:, :, 0], (0, 0), sigma)
        tangent_y = cv2.GaussianBlur(tangent[:, :, 1], (0, 0), sigma)
        mag = np.hypot(tangent_x, tangent_y)
        mask = mag > 1e-6
        tangent = np.stack([
            np.where(mask, tangent_x / mag, 0.0),
            np.where(mask, tangent_y / mag, 0.0),
        ], axis=-1)
    return tangent


def _select_goal(graph: _RCGGraph, cur: _RCGNode) -> tuple[_RCGNode | None, bool]:
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


def _smooth_path(path: list[tuple[float, float]], free: np.ndarray,
                 iterations: int = 50, rate: float = 0.1,
                 dir_field: np.ndarray | None = None,
                 dir_strength: float = 0.0) -> list[tuple[float, float]]:
    """梯度下降路径平滑"""
    pts = np.array(path, dtype=np.float64)
    if len(pts) < 3:
        return path
    h, w = free.shape
    for _ in range(iterations):
        prev = np.roll(pts, 1, axis=0)
        next_ = np.roll(pts, -1, axis=0)
        smooth = 0.5 * (prev + next_)
        delta = smooth - pts

        if dir_field is not None and dir_strength > 0:
            idxs = np.round(pts).astype(np.int32)
            idxs[:, 0] = np.clip(idxs[:, 0], 0, w - 1)
            idxs[:, 1] = np.clip(idxs[:, 1], 0, h - 1)
            tangent = dir_field[idxs[:, 1], idxs[:, 0]]
            delta += tangent * dir_strength

        pts += delta * rate

        idxs = np.round(pts).astype(np.int32)
        idxs[:, 0] = np.clip(idxs[:, 0], 0, w - 1)
        idxs[:, 1] = np.clip(idxs[:, 1], 0, h - 1)
        in_free = free[idxs[:, 1], idxs[:, 0]]
        if not np.all(in_free):
            pts[~in_free] = path[~in_free]

        pts[0] = path[0]
        pts[-1] = path[-1]

    return [(float(p[0]), float(p[1])) for p in pts]


class CStarCircleCoveragePlanner:
    """C* 全覆盖路径规划器（圆形算法版，含切线场平滑）"""

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
        angle = _detect_dominant_angle(binary)
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
        gf = float(getattr(self.cfg, "gap_fill_threshold_m", 0.3))
        gn = int(getattr(self.cfg, "gap_fill_node_count", 5))
        graph = _build_graph(rotated, step, contour_layers=cl, layer_gap=lg,
                             start_offset=so, min_perimeter_factor=mp,
                             min_node_dist_factor=nd, match_dist_factor=mf,
                             connection_dist_factor=cf,
                             gap_fill_threshold_m=gf, gap_fill_node_count=gn)
        if not graph.nodes:
            return CoverageResult.failure_result(1, "C*: 自由空间无节点")

        _label_connected_components(graph)

        if getattr(self.cfg, "debug_show_nodes_only", False):
            debug_node_coords = []
            for n in graph.nodes:
                p = M_inv @ np.array([n.x, n.y, 1.0])
                debug_node_coords.append((float(p[0]), float(p[1])))
            return CoverageResult.success_result(
                [], [], runtime_metadata={"debug_all_nodes": debug_node_coords})

        # ── 计算切线场 ──
        tangent_field = _compute_tangent_field(rotated, sigma=10.0)

        sp = M_fwd @ np.array([start[0], start[1], 1.0])
        cur = min(graph.nodes, key=lambda n: _dist(n, _RCGNode(sp[0], sp[1], -1, 0, 0)))

        comps: dict[int, list[_RCGNode]] = {}
        for n in graph.nodes:
            comps.setdefault(n.component, []).append(n)
        comp_order = sorted(comps.keys(),
                            key=lambda c: min(_dist(n, cur) for n in comps[c]))
        bridge_astar = getattr(self.cfg, "bridge_astar_enable", False)
        path_nodes: list[_RCGNode] = []
        for ci in comp_order:
            sg = _RCGGraph()
            sg.nodes = comps[ci]
            part = _boustrophedon_order(sg,
                                        start=cur if not path_nodes else None)
            if bridge_astar and path_nodes and part:
                a, b = path_nodes[-1], part[0]
                bridge = _grid_path(a.x, a.y, b.x, b.y, rotated > 0, step)
                if bridge:
                    for bx, by in bridge[1:]:
                        path_nodes.append(_RCGNode(bx, by, -1, -1, -1))
            path_nodes.extend(part)

        path_px = _to_coords(path_nodes)

        # ── 路径平滑 ──
        smooth_enable = getattr(self.cfg, "path_smooth_enable", False)
        if smooth_enable and len(path_px) >= 3:
            smooth_iter = int(getattr(self.cfg, "path_smooth_iterations", 50))
            smooth_rate = float(getattr(self.cfg, "path_smooth_rate", 0.1))
            path_px = _smooth_path(path_px, rotated > 0,
                                   iterations=smooth_iter, rate=smooth_rate,
                                   dir_field=tangent_field, dir_strength=0.0)

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
