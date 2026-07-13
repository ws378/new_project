from __future__ import annotations

import math
from collections import deque

import numpy as np

from ...contracts import CoveragePlannerConfig, CoverageResult, Pose2D
from .._basic_compat import (
    compute_rotation_matrix,
    pixels_to_world,
    rotate_room_auto,
    transform_path_back,
)

INF = float("inf")


class WavefrontCoveragePlanner:
    """Wavefront coverage path planner.

    Based on the wavefront algorithm described in
    Fevgas et al. 2022 (Sensors survey), Section 3.8.1.
    Propagates a wavefront from the start and follows descending values.
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

        cell_size = max(1, int(round(self.cfg.coverage_width_m / map_resolution)))
        step_px = max(1, int(round(self.cfg.step / map_resolution)))

        free_mask = (rotated > 0).astype(np.uint8)

        grid_h = (h + cell_size - 1) // cell_size
        grid_w = (w + cell_size - 1) // cell_size

        grid = np.zeros((grid_h, grid_w), dtype=np.int32)
        cell_centers = {}

        for gy in range(grid_h):
            for gx in range(grid_w):
                cx = gx * cell_size + cell_size // 2
                cy = gy * cell_size + cell_size // 2
                if 0 <= cy < h and 0 <= cx < w and free_mask[cy, cx] == 1:
                    grid[gy, gx] = -1
                    cell_centers[(gy, gx)] = (float(cx), float(cy))

        if not cell_centers:
            return CoverageResult.failure_result(2, error_message="no free cells")

        start_gx = min(cell_centers.keys(), key=lambda k: (
            (k[1] * cell_size + cell_size // 2 - starting_position[0]) ** 2 +
            (k[0] * cell_size + cell_size // 2 - starting_position[1]) ** 2
        ))
        grid[start_gx] = 1

        q = deque([start_gx])
        while q:
            gy, gx = q.popleft()
            val = grid[gy, gx]
            for dy, dx in [(0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]:
                ny, nx = gy + dy, gx + dx
                if 0 <= ny < grid_h and 0 <= nx < grid_w and grid[ny, nx] == -1:
                    grid[ny, nx] = val + 1
                    q.append((ny, nx))

        unvisited = set(cell_centers.keys())
        path_px = []

        current = start_gx
        if current in unvisited:
            unvisited.discard(current)
            path_px.append(cell_centers[current])

        while unvisited:
            neighbors = []
            gy, gx = current
            for dy, dx in [(0, 1), (0, -1), (1, 0), (-1, 0),
                           (1, 1), (1, -1), (-1, 1), (-1, -1)]:
                ny, nx = gy + dy, gx + dx
                if (ny, nx) in unvisited:
                    neighbors.append((ny, nx))

            if neighbors:
                best = min(neighbors, key=lambda n: grid[n])
                if best != current:
                    gy0, gx0 = current
                    gy1, gx1 = best
                    self._line_path(
                        path_px, cell_centers[current], cell_centers[best],
                        step_px, free_mask,
                    )
                    current = best
                    unvisited.discard(current)
                    continue

            if unvisited:
                best_dist = INF
                best_cell = None
                for cell in unvisited:
                    d = math.hypot(
                        cell_centers[cell][0] - cell_centers[current][0],
                        cell_centers[cell][1] - cell_centers[current][1],
                    )
                    if d < best_dist:
                        best_dist = d
                        best_cell = cell
                if best_cell is not None:
                    self._line_path(
                        path_px, cell_centers[current], cell_centers[best_cell],
                        step_px, free_mask,
                    )
                    current = best_cell
                    unvisited.discard(current)

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

    def _line_path(self, path_px, pt_a, pt_b, step_px, free_mask):
        x0, y0 = pt_a
        x1, y1 = pt_b
        dx = x1 - x0
        dy = y1 - y0
        dist = math.hypot(dx, dy)
        if dist < 1:
            return
        steps = max(1, int(dist / step_px))
        for i in range(1, steps + 1):
            t = i / steps
            x = x0 + dx * t
            y = y0 + dy * t
            ix = int(round(x))
            iy = int(round(y))
            if 0 <= iy < free_mask.shape[0] and 0 <= ix < free_mask.shape[1]:
                if free_mask[iy, ix] == 1:
                    path_px.append((float(ix), float(iy)))
