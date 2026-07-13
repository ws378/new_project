from __future__ import annotations

import heapq
import math
from collections import deque

import cv2
import numpy as np

from ...contracts import CoveragePlannerConfig, CoverageResult
from .gbnn_core import postprocess_path
from .._basic_compat import (
    complete_cell_test,
    compute_rotation_matrix,
    rotate_room_auto,
    transform_path_back,
)

INF = float("inf")


class _Node:
    __slots__ = ("id", "x", "y", "row", "pos", "left", "right", "up", "down")

    def __init__(self, nid, x, y, row, pos):
        self.id = nid
        self.x = x
        self.y = y
        self.row = row
        self.pos = pos
        self.left = None
        self.right = None
        self.up = None
        self.down = None


class GbnnCoveragePlanner:
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

        cell_size = int(round(cfg.coverage_width_m / map_resolution))
        if cell_size < 2:
            cell_size = 2

        # 基础算法风格取节点: 自由空间包围盒 + complete_cell_test
        free_ys, free_xs = np.where(map > 0)
        if len(free_ys) == 0:
            return CoverageResult.failure_result(2, error_message="no free space")
        min_y, max_y = int(free_ys.min()), int(free_ys.max())
        min_x, max_x = int(free_xs.min()), int(free_xs.max())

        nodes: list[_Node] = []
        grid: dict[tuple[int, int], _Node] = {}
        next_id = 0

        y = min_y + cell_size // 2
        row_idx = 0
        while y < max_y:
            x = min_x + cell_size // 2
            col_idx = 0
            while x < max_x:
                ok, new_x, new_y = complete_cell_test(map, x, y, cell_size)
                if ok:
                    node = _Node(next_id, new_x, new_y, row_idx, col_idx)
                    nodes.append(node)
                    grid[(row_idx, col_idx)] = node
                    next_id += 1
                col_idx += 1
                x += cell_size
            row_idx += 1
            y += cell_size

        if not nodes:
            return CoverageResult.failure_result(2, error_message="no free cells in map")

        for (r, c), n in grid.items():
            n.right = grid.get((r, c + 1))
            n.left = grid.get((r, c - 1))
            n.down = grid.get((r + 1, c))
            n.up = grid.get((r - 1, c))

        # --- GBNN dynamics ---
        N = len(nodes)
        step_px = cfg.step / map_resolution
        neighbor_idx = np.full((N, 4), -1, dtype=np.int32)
        neighbor_w = np.zeros((N, 4), dtype=np.float64)
        for i, n in enumerate(nodes):
            for k, nb in enumerate([n.left, n.right, n.up, n.down]):
                if nb is not None:
                    neighbor_idx[i, k] = nb.id
                    d = math.hypot(n.x - nb.x, n.y - nb.y)
                    neighbor_w[i, k] = math.exp(-d*d / (step_px*step_px))

        act = np.zeros(N, dtype=np.float64)
        I_ext = np.full(N, cfg.gbnn_E, dtype=np.float64)
        dt_val = 0.01
        for _ in range(cfg.gbnn_iters):
            n_act = act[neighbor_idx]
            mask = neighbor_idx != -1
            n_act[~mask] = 0.0
            n_pos = neighbor_w * np.maximum(n_act, 0.0)
            n_neg = neighbor_w * np.maximum(-n_act, 0.0)
            pos_sum = n_pos.sum(axis=1)
            neg_sum = n_neg.sum(axis=1)
            act += dt_val * (
                -cfg.gbnn_A * act
                + (cfg.gbnn_B - act) * (I_ext + pos_sum)
                - (cfg.gbnn_D + act) * neg_sum
            )
            act = np.clip(act, 0.0, cfg.gbnn_B)

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

        current = min(nodes, key=lambda n: math.hypot(n.x - start_xy[0], n.y - start_xy[1]))
        path_nodes = [current]
        visited = np.zeros(len(nodes), dtype=bool)
        visited[current.id] = True
        revisit = np.zeros(len(nodes), dtype=np.int32)

        use_backtrack = cfg.gbnn_backtrack_enable

        for _ in range(len(nodes) * 4):
            candidates = [nb for nb in (current.left, current.right, current.up, current.down)
                          if nb is not None and not visited[nb.id]]

            if not candidates and use_backtrack:
                bfs_nb = _bfs_nearest_unvisited(current, nodes, visited)
                if bfs_nb is not None:
                    astar = _astar_path(current, bfs_nb, nodes, visited)
                    if astar and len(astar) >= 2:
                        candidates = [astar[1]]
                    else:
                        candidates = [bfs_nb]

            # BFS failed → graph may be disconnected; jump to nearest unvisited globally
            if not candidates and use_backtrack:
                rem = [i for i in range(len(nodes)) if not visited[i]]
                if rem:
                    best_i = min(rem, key=lambda i: math.hypot(nodes[i].x - current.x, nodes[i].y - current.y))
                    candidates = [nodes[best_i]]

            if not candidates:
                candidates = [nb for nb in (current.left, current.right, current.up, current.down)
                              if nb is not None]

            if not candidates:
                break

            next_node = max(candidates, key=lambda nb: _score(nb, current, visited, path_nodes, revisit))
            path_nodes.append(next_node)
            visited[next_node.id] = True
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
    return None


def _astar_path(start_node, goal_node, nodes, visited):
    pq = [(0, start_node.id, [start_node])]
    seen = {start_node.id}
    while pq:
        cost, _, path = heapq.heappop(pq)
        cur = path[-1]
        if cur.id == goal_node.id:
            return path
        for nb in (cur.left, cur.right, cur.up, cur.down):
            if nb is None or nb.id in seen:
                continue
            seen.add(nb.id)
            h = math.sqrt((nb.x - goal_node.x) ** 2 + (nb.y - goal_node.y) ** 2)
            heapq.heappush(pq, (cost + 1 + h, nb.id, path + [nb]))
    return None
