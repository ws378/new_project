from __future__ import annotations

import math
from collections import deque

import cv2
import numpy as np

from ...contracts import CoveragePlannerConfig, CoverageResult
from .gbnn_core import gbnn_dynamics_step, postprocess_path
from .._basic_compat import (
    rotate_room_auto,
    transform_path_back,
)

INF = float("inf")


class _Node:
    __slots__ = ("x", "y", "id", "left", "right", "up", "down")

    def __init__(self, x: float, y: float, nid: int):
        self.x = x
        self.y = y
        self.id = nid
        self.left: _Node | None = None
        self.right: _Node | None = None
        self.up: _Node | None = None
        self.down: _Node | None = None


class EcdCoveragePlanner:
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
        except Exception as exc:
            return CoverageResult.failure_result(1, f"ECD+GBNN error: {exc}")

    def _run(
        self,
        room_map: np.ndarray,
        map_resolution: float,
        start_px: tuple[float, float],
        map_origin: tuple[float, float],
    ) -> CoverageResult:
        h, w = room_map.shape
        cfg = self.cfg

        orig_h = h
        orig_w = w

        rotated = False
        R = np.eye(2, 3, dtype=np.float64)
        if cfg.auto_rotate:
            R, (new_w, new_h), rot_map = rotate_room_auto(room_map, map_resolution)
            sp = np.array([[start_px[0], start_px[1]]], dtype=np.float32)
            sp_rot = cv2.transform(sp.reshape(1, -1, 2), R)[0][0]
            ox = int(round(sp_rot[0]))
            oy = int(round(sp_rot[1]))
            if 0 <= ox < new_w and 0 <= oy < new_h and rot_map[oy, ox] > 0:
                room_map = rot_map
                start_px = (ox, oy)
                h, w = room_map.shape[:2]
                rotated = True
        step = max(2, int(cfg.coverage_width_m / map_resolution))
        nodes = _ecd_sample_nodes(room_map > 0, step)

        if len(nodes) < 2:
            return CoverageResult.failure_result(3, "Not enough free cells")

        step_sq = float(step * step)
        act = np.array([1.0 / step_sq for _ in nodes], dtype=np.float64)
        visited_arr = np.zeros(len(nodes), dtype=bool)
        A_val = cfg.gbnn_A
        B_val = cfg.gbnn_B
        D_val = cfg.gbnn_D
        E_val = cfg.gbnn_E
        iters = cfg.gbnn_iters

        for _ in range(iters):
            act = gbnn_dynamics_step(act, nodes, step_sq, A_val, B_val, D_val, E_val, visited_arr)

        nearest = min(nodes, key=lambda n:
                      (n.x - start_px[0]) ** 2 + (n.y - start_px[1]) ** 2)
        current = nearest
        visited_arr[current.id] = True

        path_nodes: list[_Node] = [current]

        def _score(n, current_node, act_arr, vis_arr, pn):
            s = act_arr[n.id] if not vis_arr[n.id] else 0.0
            frontier = sum(1 for nb in (n.left, n.right, n.up, n.down)
                           if nb is not None and not vis_arr[nb.id])
            s += frontier * 0.3
            if len(pn) >= 2:
                prev = pn[-2]
                in_dx = current_node.x - prev.x
                in_dy = current_node.y - prev.y
                out_dx = n.x - current_node.x
                out_dy = n.y - current_node.y
                dot = in_dx * out_dx + in_dy * out_dy
                in_len = math.hypot(in_dx, in_dy)
                out_len = math.hypot(out_dx, out_dy)
                if in_len > 0 and out_len > 0:
                    cos_a = max(-1.0, min(1.0, dot / (in_len * out_len)))
                    s -= (math.acos(cos_a) / math.pi) * 0.5
            return s

        for _ in range(len(nodes) * 4):
            candidates = [nb for nb in (current.left, current.right, current.up, current.down)
                          if nb is not None and not visited_arr[nb.id]]
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
                candidates = [nb for nb in (current.left, current.right, current.up, current.down)
                              if nb is not None]
            if not candidates:
                break

            best = max(candidates, key=lambda nb: _score(nb, current, act, visited_arr, path_nodes))
            path_nodes.append(best)
            visited_arr[best.id] = True
            current = best

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


def _ecd_sample_nodes(
    free_mask: np.ndarray,
    step: int,
) -> list[_Node]:
    h, w = free_mask.shape

    obstacles = (free_mask == 0).astype(np.uint8)
    critical_x: set[int] = set()
    cnts, _ = cv2.findContours(obstacles, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in cnts:
        peri = cv2.arcLength(cnt, True)
        eps = max(2.0, min(5.0, 0.003 * peri))
        approx = cv2.approxPolyDP(cnt, eps, True)
        for pt in approx[:, 0]:
            x = pt[0]
            if 0 < x < w - 1:
                critical_x.add(x)

    for x in range(0, w, max(step * 2, 8)):
        critical_x.add(x)
    critical_x = sorted(critical_x)
    if not critical_x or critical_x[0] > 0:
        critical_x.insert(0, 0)
    if critical_x[-1] < w:
        critical_x.append(w)
    deduped = [critical_x[0]]
    for cx in critical_x[1:]:
        if cx - deduped[-1] >= 2:
            deduped.append(cx)
    critical_x = deduped

    cell_id = np.full((h, w), -1, dtype=np.int32)
    ncells = 0
    for i in range(len(critical_x) - 1):
        x1, x2 = critical_x[i], critical_x[i + 1]
        if x2 - x1 < 1:
            continue
        col_any = np.any(free_mask[:, x1:x2] > 0, axis=1)
        in_free = False
        y_start = 0
        for y in range(h):
            if not in_free and col_any[y]:
                y_start = y
                in_free = True
            elif in_free and not col_any[y]:
                cell_id[y_start:y, x1:x2] = ncells
                ncells += 1
                in_free = False
        if in_free:
            cell_id[y_start:h, x1:x2] = ncells
            ncells += 1

    nodes: list[_Node] = []
    nid = 0
    node_grid: list[list[_Node | None]] = [[None] * w for _ in range(h)]

    for y in range(0, h, step):
        for x in range(0, w, step):
            cid = cell_id[y, x]
            if cid < 0:
                continue
            if free_mask[y, x] == 0:
                continue
            n = _Node(float(x), float(y), nid)
            nid += 1
            nodes.append(n)
            node_grid[y][x] = n

    for y in range(0, h, step):
        for x in range(0, w, step):
            n = node_grid[y][x]
            if n is None:
                continue
            if x + step < w and node_grid[y][x + step] is not None:
                n.right = node_grid[y][x + step]
                node_grid[y][x + step].left = n
            if y + step < h and node_grid[y + step][x] is not None:
                n.down = node_grid[y + step][x]
                node_grid[y + step][x].up = n

    return nodes
