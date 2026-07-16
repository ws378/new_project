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
    """牛耕往复式扫描线取样建图"""
    h, w = free_mask.shape
    free_ys, free_xs = np.where(free_mask)
    if len(free_ys) == 0:
        return []

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

    nodes: list[_Node] = []
    nid = 0
    raw_layers: list[list[_Node]] = []

    for i in range(num_sweeps + 1):
        if sweep_static:
            line_x = min_x + i * spacing
            pts = _sample_col(free_mask, int(round(line_x)), min_y, max_y, step)
        else:
            line_y = min_y + i * spacing
            pts = _sample_row(free_mask, int(round(line_y)), min_x, max_x, step)
        if not pts:
            continue
        layer = [_Node(x, y, nid + j) for j, (x, y) in enumerate(pts)]
        for n in layer:
            nid += 1
        nodes.extend(layer)
        raw_layers.append(layer)

    if not raw_layers:
        return nodes

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

    return nodes


def _sample_row(free_mask: np.ndarray, row_y: int, x0: int, x1: int, step: int) -> list[tuple[float, float]]:
    if row_y < 0 or row_y >= free_mask.shape[0]:
        return []
    free_indices = np.where(free_mask[row_y, x0:x1 + 1])[0]
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


def _sample_col(free_mask: np.ndarray, col_x: int, y0: int, y1: int, step: int) -> list[tuple[float, float]]:
    if col_x < 0 or col_x >= free_mask.shape[1]:
        return []
    free_indices = np.where(free_mask[y0:y1 + 1, col_x])[0]
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
