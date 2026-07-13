"""Algorithm 1: 轮廓法+矩阵

Distance transform contour extraction → serpentine traversal → inter-layer
connections  → A* / local TSP jump optimization.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from ...contracts import CoveragePlannerConfig, CoverageResult, Pose2D
from .._basic_compat import (
    rotate_room_auto,
    transform_path_back,
    pixels_to_world,
)

INF = float("inf")


class _Node:
    __slots__ = ("id", "x", "y", "layer", "next", "prev")

    def __init__(self, nid, x, y, layer):
        self.id = nid
        self.x = x
        self.y = y
        self.layer = layer
        self.next = None
        self.prev = None


class ContourMatrixCoveragePlanner:
    def __init__(self, cfg: CoveragePlannerConfig):
        self.cfg = cfg

    def plan(self, effective_map, map_resolution, starting_position, map_origin=(0.0, 0.0)):
        try:
            return self._run(effective_map, map_resolution, starting_position, map_origin)
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

        binary_map = (map > 0).astype(np.uint8)
        binary_map = cv2.copyMakeBorder(binary_map, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
        dist = cv2.distanceTransform(binary_map, cv2.DIST_L2, 5)
        dist = dist[1:-1, 1:-1]

        max_dist = int(np.minimum(np.max(dist), max(h, w)))

        layers: list[list[list[_Node]]] = []
        added_positions: set[tuple[int, int]] = set()
        next_id = 0

        if cfg.contour_layers > 0:
            n = int(cfg.contour_layers)
            step_d = float(max_dist) / float(max(n, 1))
            n_layers = n
        else:
            n_layers = max(1, int(math.ceil(float(max_dist) / max(1, contour_layer_gap))))
            n_layers = min(n_layers, 50)

        for li in range(n_layers):
            if cfg.contour_layers > 0:
                d = contour_start_offset + int(round(li * step_d))
            else:
                d = contour_start_offset + li * contour_layer_gap
            if d > max_dist:
                break
            mask = cv2.inRange(dist, d, d + 1).astype(np.uint8)
            contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
            chains: list[list[_Node]] = []
            for cnt in contours:
                if cv2.arcLength(cnt, closed=True) < min_perimeter:
                    continue
                pts = cnt.reshape(-1, 2)
                n_sample = min(len(pts), 120)
                step_n = max(1, len(pts) // n_sample)
                chain: list[_Node] = []
                for i in range(0, len(pts), step_n):
                    x, y = int(pts[i][0]), int(pts[i][1])
                    if not (0 <= x < w and 0 <= y < h and map[y, x] > 0):
                        continue
                    key = (x, y)
                    if key in added_positions:
                        continue
                    added_positions.add(key)
                    node = _Node(next_id, x, y, li)
                    next_id += 1
                    chain.append(node)
                if len(chain) >= 5:
                    for j in range(len(chain)):
                        chain[j].next = chain[(j + 1) % len(chain)]
                        chain[j].prev = chain[(j - 1) % len(chain)]
                    chains.append(chain)
            if chains:
                layers.append(chains)
            total_nodes = sum(len(ch) for ch in chains)
            if total_nodes > 2000:
                break

        if not layers:
            return CoverageResult.failure_result(2, error_message="no contour nodes")

        all_nodes = [n for layer in layers for ch in layer for n in ch]
        grid = {(n.x, n.y): n for n in all_nodes}

        # --- serpentine path through all chains ---
        path_nodes: list[_Node] = []
        for li, chains in enumerate(layers):
            if not chains:
                continue
            if path_nodes:
                last = path_nodes[-1]
                chains_sorted = sorted(chains, key=lambda ch: min(math.hypot(n.x - last.x, n.y - last.y) for n in ch))
            else:
                chains_sorted = sorted(chains, key=lambda ch: min(math.hypot(n.x - start_xy[0], n.y - start_xy[1]) for n in ch))

            forward = (li % 2 == 0)
            for ci, ch in enumerate(chains_sorted):
                if not ch:
                    continue
                if path_nodes and ci > 0:
                    last = path_nodes[-1]
                    start = min(ch, key=lambda n: math.hypot(n.x - last.x, n.y - last.y))
                elif not path_nodes and ci == 0:
                    start = min(ch, key=lambda n: math.hypot(n.x - start_xy[0], n.y - start_xy[1]))
                else:
                    start = ch[0]

                cur = start
                seen_ids = {n.id for n in path_nodes}
                for _ in range(len(ch)):
                    if cur.id in seen_ids:
                        break
                    seen_ids.add(cur.id)
                    path_nodes.append(cur)
                    cur = cur.next if forward else cur.prev
                    if cur is None:
                        break

        # --- build path pixels ---
        path_px = []
        seen = set()
        for n in path_nodes:
            key = (n.x, n.y)
            if key not in seen:
                seen.add(key)
                path_px.append(key)

        if rotated:
            path_px = transform_path_back(path_px, R)
            path_px = [(max(0.0, min(orig_w - 1, x)), max(0.0, min(orig_h - 1, y))) for x, y in path_px]
            h = orig_h

        world = pixels_to_world(path_px, map_resolution, map_origin, h)
        path = [Pose2D(wx, wy, theta) for wx, wy, theta in world]
        path_px_final = [(float(x), float(y)) for x, y in path_px]
        return CoverageResult.success_result(path=path, path_pixels=path_px_final)
