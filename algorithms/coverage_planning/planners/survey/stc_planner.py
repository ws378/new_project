from __future__ import annotations

import math
from collections import defaultdict, deque

import numpy as np

from ...contracts import CoveragePlannerConfig, CoverageResult, Pose2D
from .._basic_compat import (
    compute_rotation_matrix,
    pixels_to_world,
    rotate_room_auto,
    transform_path_back,
)

INF = float("inf")


class SpanningTreeCoveragePlanner:
    """Spanning Tree Coverage (STC) path planner.

    Based on the spanning tree coverage algorithm described in
    Fevgas et al. 2022 (Sensors survey), Section 3.8.2.
    Decomposes area into 2x2 cells, builds a spanning tree,
    and traverses its perimeter.
    """

    def __init__(self, cfg: CoveragePlannerConfig | None = None):
        self.cfg = cfg or CoveragePlannerConfig()

    def plan(self, effective_map, map_resolution, starting_position, map_origin=(0.0, 0.0)):
        try:
            return self._run(effective_map, map_resolution, starting_position, map_origin)
        except Exception as e:
            return CoverageResult.failure_result(1, error_message=str(e))

    def _run(self, room_map, map_resolution, starting_position, map_origin):
        h, w = room_map.shape[:2]
        orig_h, orig_w = h, w

        R, new_size, rotated = None, None, room_map
        if self.cfg.auto_rotate:
            R, new_size, rotated = rotate_room_auto(room_map, map_resolution)
            h, w = rotated.shape[:2]

        cell_size = max(2, int(round(self.cfg.coverage_width_m / map_resolution)))
        half = cell_size // 2

        free_mask = (rotated > 0).astype(np.uint8)

        grid_h = (h + cell_size - 1) // cell_size
        grid_w = (w + cell_size - 1) // cell_size

        grid = np.zeros((grid_h, grid_w), dtype=np.int32)
        for gy in range(grid_h):
            for gx in range(grid_w):
                cx = gx * cell_size + half
                cy = gy * cell_size + half
                if 0 <= cy < h and 0 <= cx < w and free_mask[cy, cx] == 1:
                    grid[gy, gx] = 1

        start_gx = -1
        best_dist = INF
        for gy in range(grid_h):
            for gx in range(grid_w):
                if grid[gy, gx] == 1:
                    cx = gx * cell_size + half
                    cy = gy * cell_size + half
                    d = math.hypot(cx - starting_position[0], cy - starting_position[1])
                    if d < best_dist:
                        best_dist = d
                        start_gx = (gy, gx)

        if start_gx is None or start_gx == -1:
            return CoverageResult.failure_result(2, error_message="no free cells")

        parent = {}
        tree_children = defaultdict(list)
        stack = [start_gx]
        parent[start_gx] = None
        visited_tree = {start_gx}
        while stack:
            gy, gx = stack.pop()
            for dy, dx in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                ny, nx = gy + dy, gx + dx
                nb = (ny, nx)
                if 0 <= ny < grid_h and 0 <= nx < grid_w and grid[ny, nx] == 1 and nb not in visited_tree:
                    visited_tree.add(nb)
                    parent[nb] = (gy, gx)
                    tree_children[(gy, gx)].append(nb)
                    stack.append(nb)

        path_px = []
        self._traverse_tree(start_gx, tree_children, cell_size, path_px, free_mask)

        if not path_px:
            return CoverageResult.failure_result(3, error_message="no path generated")

        if R is not None:
            path_px = transform_path_back(path_px, R)

        clamped = []
        for x, y in path_px:
            cx = max(0, min(orig_w - 1, int(round(x))))
            cy = max(0, min(orig_h - 1, int(round(y))))
            clamped.append((float(cx), float(cy)))

        world = pixels_to_world(clamped, map_resolution, map_origin, orig_h)
        path = [Pose2D(wx, wy, theta) for wx, wy, theta in world]

        path_px_final = [(float(x), float(y)) for x, y in clamped]
        return CoverageResult.success_result(path=path, path_pixels=path_px_final)

    def _traverse_tree(self, node, tree_children, cell_size, path_px, free_mask):
        gy, gx = node
        cx = gx * cell_size + cell_size // 2
        cy = gy * cell_size + cell_size // 2

        path_px.append((float(cx), float(cy)))

        children = tree_children.get(node, [])
        while children:
            child = children.pop(0)
            self._traverse_tree(child, tree_children, cell_size, path_px, free_mask)
            path_px.append((float(cx), float(cy)))
