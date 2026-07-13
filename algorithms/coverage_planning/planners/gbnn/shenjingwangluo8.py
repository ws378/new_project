from __future__ import annotations

import bisect
import math
from collections import deque

import cv2
import numpy as np

from ...contracts import CoveragePlannerConfig, CoverageResult
from .gbnn_core import postprocess_path
from .._basic_compat import (
    rotate_room_auto,
    transform_path_back,
)

INF = float("inf")


class _Node:
    __slots__ = ("id", "x", "y", "layer", "right", "left", "up", "down", "angle")

    def __init__(self, nid, x, y, layer=0, angle=0.0):
        self.id = nid
        self.x = x
        self.y = y
        self.layer = layer
        self.right = None
        self.left = None
        self.up = None
        self.down = None
        self.angle = angle


class ContourDnnCoveragePlanner:
    def __init__(self, cfg: CoveragePlannerConfig):
        self.cfg = cfg

    def plan(
        self,
        effective_map,
        map_resolution,
        starting_position,
        map_origin=(0.0, 0.0),
    ):
        try:
            return self._run(
                effective_map,
                map_resolution,
                starting_position,
                map_origin,
            )
        except Exception as e:
            return CoverageResult.failure_result(1, error_message=str(e))

    def _run(self, map, map_resolution, start_xy, map_origin):
        h, w = map.shape[:2]
        cfg = self.cfg

        orig_h = h
        orig_w = w

        rotated = False
        R = np.eye(2, 3, dtype=np.float64)
        if cfg.auto_rotate:
            R, (new_w, new_h), rot_map = rotate_room_auto(map, map_resolution)
            sp = np.array([[start_xy[0], start_xy[1]]], dtype=np.float32)
            sp_rot = cv2.transform(sp.reshape(1, -1, 2), R)[0][0]
            ox = int(round(sp_rot[0]))
            oy = int(round(sp_rot[1]))
            if 0 <= ox < new_w and 0 <= oy < new_h and rot_map[oy, ox] > 0:
                map = rot_map
                start_xy = (ox, oy)
                h, w = map.shape[:2]
                rotated = True

        step = int(cfg.step / map_resolution)
        contour_start_offset = int(cfg.contour_start_offset / map_resolution)
        contour_layer_gap = int(cfg.contour_layer_gap / map_resolution)
        min_perimeter = int(step * cfg.min_perimeter_factor)
        min_node_dist = int(step * cfg.min_node_dist_factor)
        connection_dist = int(step * cfg.connection_dist_factor)

        binary_map = (map > 0).astype(np.uint8)
        binary_map = cv2.copyMakeBorder(binary_map, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
        dist = cv2.distanceTransform(binary_map, cv2.DIST_L2, 5)
        dist = dist[1:-1, 1:-1]
        max_dist_val = float(dist.max())

        # ------------------------------------------------------------------
        # C* 风格取节点: dist >= d 掩码 + bisect 周长采样
        # 同层所有轮廓合并到一层 (一层对应一个距离层), 保持距离层排序
        # contour_layers=0 自适应, >0 固定层数
        # ------------------------------------------------------------------
        nodes: list[_Node] = []
        next_id = 0
        raw_layers: list[list[_Node]] = []

        def _sample_one_layer(d_val, li) -> list[_Node]:
            nonlocal next_id
            mask = (dist >= d_val).astype(np.uint8)
            cts, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
            if not cts:
                return []
            layer_nodes: list[_Node] = []
            for cnt in cts:
                pts = cnt.squeeze(axis=1)
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
                prev_x = prev_y = None
                t = 0.0
                while t < total:
                    idx = bisect.bisect_left(cum, t)
                    idx = min(idx, len(pts) - 1)
                    x, y = float(pts[idx, 0]), float(pts[idx, 1])
                    yi, xi = int(round(y)), int(round(x))
                    if 0 <= yi < h and 0 <= xi < w and map[yi, xi] > 0:
                        too_close = False
                        if prev_x is not None and math.hypot(x - prev_x, y - prev_y) < min_node_dist:
                            too_close = True
                        if not too_close:
                            node = _Node(next_id, x, y, li)
                            next_id += 1
                            nodes.append(node)
                            layer_nodes.append(node)
                            prev_x, prev_y = x, y
                    t += float(step)
            return layer_nodes

        if cfg.contour_layers > 0:
            n = int(cfg.contour_layers)
            step_d = max_dist_val / float(max(n, 1))
            for li in range(n):
                d_val = float(contour_start_offset) + li * step_d
                if d_val >= max_dist_val:
                    d_val = max_dist_val - 0.5
                ln = _sample_one_layer(d_val, li)
                if ln:
                    raw_layers.append(ln)
        else:
            d_val = float(contour_start_offset)
            layer_interval = float(contour_layer_gap)
            num_layers = max(1, min(int(max_dist_val / max(1, layer_interval)), 50))
            empty_streak = 0
            for li in range(num_layers):
                if d_val >= max_dist_val:
                    break
                ln = _sample_one_layer(d_val, li)
                if ln:
                    raw_layers.append(ln)
                    empty_streak = 0
                else:
                    empty_streak += 1
                    if empty_streak >= 3:
                        break
                d_val += layer_interval

        if not nodes:
            return CoverageResult.failure_result(2, error_message="no contour nodes generated")

        # 保持距离层原始创建顺序, 确保层间连线逻辑正确
        for li, layer in enumerate(raw_layers):
            for n in layer:
                n.layer = li

        # --- build lateral connections (原逻辑) ---
        max_layer = max(n.layer for n in nodes)
        nodes_by_layer: list[list[_Node]] = [[] for _ in range(max_layer + 1)]
        for n in nodes:
            nodes_by_layer[n.layer].append(n)
        for layer in nodes_by_layer:
            layer.sort(key=lambda n: (n.x, n.y))
            for n in layer:
                candidates = sorted(
                    layer,
                    key=lambda o: (math.hypot(o.x - n.x, o.y - n.y), abs(o.x - n.x)),
                )
                for o in candidates:
                    if o.id == n.id:
                        continue
                    d = math.hypot(o.x - n.x, o.y - n.y)
                    if d > connection_dist:
                        break
                    dx = o.x - n.x
                    if dx > 0 and n.right is None:
                        n.right = o
                        o.left = n
                    elif dx < 0 and n.left is None:
                        n.left = o
                        o.right = n

        # --- build vertical connections (原逻辑) ---
        for i in range(len(nodes_by_layer) - 1):
            lower = nodes_by_layer[i]
            upper = nodes_by_layer[i + 1]
            for n in lower:
                candidates = sorted(
                    (o for o in upper if abs(o.x - n.x) < min_node_dist * 3),
                    key=lambda o: abs(o.y - n.y),
                )
                for o in candidates:
                    if n.up is None and o.down is None:
                        d = math.hypot(o.x - n.x, o.y - n.y)
                        if d < connection_dist * 2:
                            n.up = o
                            o.down = n
                            break

        act = np.ones(len(nodes), dtype=np.float64)

        # --- greedy walk (scoring-based) ---
        current = min(nodes, key=lambda n: math.hypot(n.x - start_xy[0], n.y - start_xy[1]))
        path_nodes = [current]
        visited_arr = np.zeros(len(nodes), dtype=bool)
        visited_arr[current.id] = True
        revisit = np.zeros(len(nodes), dtype=np.int32)

        def _score(n, current, vis, path_nodes, revisit):
            s = 0.0 if vis[n.id] else act[n.id]

            if len(path_nodes) >= 2:
                prev = path_nodes[-2]
                in_dx = current.x - prev.x
                in_dy = current.y - prev.y
                out_dx = n.x - current.x
                out_dy = n.y - current.y
                in_len = math.hypot(in_dx, in_dy)
                out_len = math.hypot(out_dx, out_dy)
                if in_len > 0 and out_len > 0:
                    dot = in_dx * out_dx + in_dy * out_dy
                    cos_a = max(-1.0, min(1.0, dot / (in_len * out_len)))
                    s += (cos_a + 1.0) / 2.0 * cfg.gbnn_straight_weight

            if cfg.gbnn_zigzag_weight > 0 and len(path_nodes) >= 2 and not vis[n.id]:
                prev = path_nodes[-2]
                in_dx = current.x - prev.x
                in_dy = current.y - prev.y
                if abs(in_dx) > abs(in_dy):
                    fwd = current.right if in_dx > 0 else current.left
                    if fwd is None or vis[fwd.id]:
                        if n is current.up or n is current.down:
                            s += cfg.gbnn_zigzag_weight
                elif abs(in_dy) > 0:
                    fwd = current.down if in_dy > 0 else current.up
                    if fwd is None or vis[fwd.id]:
                        if n is current.left or n is current.right:
                            s += cfg.gbnn_zigzag_weight

            frontier = 0
            for nb in (n.left, n.right, n.up, n.down):
                if nb is not None and not vis[nb.id]:
                    frontier += 1
            s += (frontier / 4.0) * cfg.gbnn_frontier_weight

            s -= min(revisit[n.id], 10) * 0.1

            return s

        for _ in range(len(nodes) * 4):
            candidates = [current.left, current.right, current.up, current.down]
            candidates = [nb for nb in candidates if nb is not None and not visited_arr[nb.id]]
            if not candidates:
                nb = _bfs_nearest_unvisited(current, nodes, visited_arr)
                if nb is not None:
                    candidates = [nb]
            if not candidates:
                rem = [i for i in range(len(nodes)) if not visited_arr[i]]
                if rem:
                    best_i = min(rem, key=lambda i: math.hypot(nodes[i].x - current.x, nodes[i].y - current.y))
                    candidates = [nodes[best_i]]
            if not candidates:
                break
            next_node = max(candidates, key=lambda nb: _score(nb, current, visited_arr, path_nodes, revisit))
            path_nodes.append(next_node)
            visited_arr[next_node.id] = True
            revisit[next_node.id] += 1
            current = next_node

        if rotated:
            fov = [(n.x, n.y) for n in path_nodes]
            fov_unrot = transform_path_back(fov, R)
            for n, (ux, uy) in zip(path_nodes, fov_unrot):
                n.x = max(0, min(orig_w - 1, int(round(ux))))
                n.y = max(0, min(orig_h - 1, int(round(uy))))
            h = orig_h

        return postprocess_path(path_nodes, map_resolution, map_origin, h)


def _bfs_nearest_unvisited(start, nodes, visited):
    q = deque([start])
    seen = {start.id}
    while q:
        cur = q.popleft()
        for nb in (cur.left, cur.right, cur.up, cur.down):
            if nb is None or nb.id in seen:
                continue
            seen.add(nb.id)
            if not visited[nb.id]:
                return nb
            q.append(nb)
    best, best_d = None, INF
    for nb in nodes:
        if not visited[nb.id]:
            d = math.hypot(nb.x - start.x, nb.y - start.y)
            if d < best_d:
                best_d = d
                best = nb
    return best
