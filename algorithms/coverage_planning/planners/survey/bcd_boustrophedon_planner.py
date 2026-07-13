"""BCD-style boustrophedon coverage path planner.

Enhanced boustrophedon planner that decomposes free space into connected
components (cells), generates optimized sweep paths within each cell, and
connects cells with shortest paths. Inspired by ETH's polygon_coverage_planning
BCD algorithm but implemented with opencv + shapely for Python.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import cv2
import numpy as np
from shapely.geometry import Point, Polygon, LineString, MultiPoint
from shapely.ops import unary_union

from ...contracts import CoveragePlannerConfig, CoverageResult, Pose2D
from .._basic_compat import (
    compute_rotation_matrix,
    pixels_to_world,
    rotate_room_auto,
    transform_path_back,
)

INF = float("inf")


class BcdBoustrophedonCoveragePlanner:
    """BCD-style boustrophedon coverage path planner.

    Decomposes free space into connected components, generates boustrophedon
    sweep paths within each cell, and connects cells with shortest paths.
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

        step_px = max(1, int(round(self.cfg.step / map_resolution)))
        coverage_px = max(1, int(round(self.cfg.coverage_width_m / map_resolution)))

        free_mask = (rotated > 0).astype(np.uint8) * 255

        kernel_size = max(3, coverage_px)
        if kernel_size % 2 == 0:
            kernel_size += 1
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
        )
        eroded = cv2.erode(free_mask, kernel, iterations=1)

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
            eroded, connectivity=8
        )

        min_area = max(10, int(coverage_px * coverage_px * 0.1))
        cells = []
        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if area < min_area:
                continue
            cell_mask = (labels == i).astype(np.uint8) * 255
            contour_pts = self._extract_contour(cell_mask)
            if contour_pts is not None and len(contour_pts) >= 3:
                cells.append((i, cell_mask, contour_pts, centroids[i]))

        if not cells:
            return CoverageResult.failure_result(2, error_message="no cells found")

        cell_order = self._order_cells(cells, starting_position, map_resolution, R, orig_h, orig_w)

        all_path_px: List[Tuple[float, float]] = []
        prev_end = None

        for cell_idx in cell_order:
            label_id, cell_mask, contour_pts, centroid = cells[cell_idx]
            cell_sweep = self._generate_cell_sweep(
                cell_mask, contour_pts, coverage_px, step_px
            )
            if not cell_sweep:
                continue

            if prev_end is not None and all_path_px:
                bridge = self._bridge_path(prev_end, cell_sweep[0], free_mask)
                all_path_px.extend(bridge)

            all_path_px.extend(cell_sweep)
            prev_end = cell_sweep[-1] if cell_sweep else prev_end

        if not all_path_px:
            return CoverageResult.failure_result(3, error_message="no path generated")

        if R is not None:
            all_path_px = transform_path_back(all_path_px, R)

        clamped = []
        for x, y in all_path_px:
            cx = max(0, min(orig_w - 1, round(x)))
            cy = max(0, min(orig_h - 1, round(y)))
            clamped.append((float(cx), float(cy)))

        world = pixels_to_world(clamped, map_resolution, map_origin, orig_h)
        path = [Pose2D(wx, wy, theta) for wx, wy, theta in world]
        path_px_final = [(float(x), float(y)) for x, y in clamped]

        return CoverageResult.success_result(path=path, path_pixels=path_px_final)

    def _extract_contour(self, cell_mask: np.ndarray) -> np.ndarray | None:
        contours, _ = cv2.findContours(cell_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        largest = max(contours, key=cv2.contourArea)
        if len(largest) < 3:
            return None
        epsilon = 0.005 * cv2.arcLength(largest, True)
        approx = cv2.approxPolyDP(largest, epsilon, True)
        pts = approx.reshape(-1, 2)
        return pts

    def _generate_cell_sweep(
        self,
        cell_mask: np.ndarray,
        contour_pts: np.ndarray,
        coverage_px: int,
        step_px: int,
    ) -> List[Tuple[float, float]]:
        h, w = cell_mask.shape[:2]
        free_ys, free_xs = np.where(cell_mask > 0)
        if len(free_ys) == 0:
            return []

        min_y, max_y = int(free_ys.min()), int(free_ys.max())
        min_x, max_x = int(free_xs.min()), int(free_xs.max())

        best_path = []
        best_score = -1

        angles = [0, 45, 90, 135]
        for angle_deg in angles:
            path = self._sweep_at_angle(
                cell_mask, angle_deg, coverage_px, step_px,
                min_x, max_x, min_y, max_y
            )
            if not path:
                continue

            covered = self._count_covered_cells(path, cell_mask, coverage_px)
            path_len = self._path_length(path)
            score = covered - 0.001 * path_len

            if score > best_score:
                best_score = score
                best_path = path

        return best_path

    def _sweep_at_angle(
        self,
        cell_mask: np.ndarray,
        angle_deg: float,
        coverage_px: int,
        step_px: int,
        min_x: int, max_x: int,
        min_y: int, max_y: int,
    ) -> List[Tuple[float, float]]:
        h, w = cell_mask.shape[:2]
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0

        angle_rad = math.radians(angle_deg)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        corners = [
            (min_x, min_y), (max_x, min_y),
            (max_x, max_y), (min_x, max_y)
        ]
        local_pts = []
        for px, py in corners:
            lx = (px - cx) * cos_a + (py - cy) * sin_a
            ly = -(px - cx) * sin_a + (py - cy) * cos_a
            local_pts.append((lx, ly))

        local_min_x = min(p[0] for p in local_pts)
        local_max_x = max(p[0] for p in local_pts)
        local_min_y = min(p[1] for p in local_pts)
        local_max_y = max(p[1] for p in local_pts)

        area_h = local_max_y - local_min_y
        if area_h <= 0:
            return []

        num_sweeps = max(1, int(area_h / coverage_px) + 1)
        spacing = area_h / num_sweeps

        path = []
        for i in range(num_sweeps + 1):
            sweep_y_local = local_min_y + i * spacing

            sweep_pts_world = []
            test_x = local_min_x - 1
            while test_x <= local_max_x + 1:
                wx = test_x * cos_a - sweep_y_local * sin_a + cx
                wy = test_x * sin_a + sweep_y_local * cos_a + cy
                ix, iy = int(round(wx)), int(round(wy))
                if 0 <= iy < h and 0 <= ix < w and cell_mask[iy, ix] > 0:
                    sweep_pts_world.append((wx, wy))
                test_x += 1

            if sweep_pts_world:
                segments = self._split_by_gaps(sweep_pts_world)
                for seg in segments:
                    if i % 2 == 1:
                        seg.reverse()
                    path.extend(seg)

        return path

    def _split_by_gaps(self, points: List[Tuple[float, float]], max_gap: float = 3.0) -> List[List[Tuple[float, float]]]:
        if not points:
            return []
        segments = [[points[0]]]
        for i in range(1, len(points)):
            dx = points[i][0] - points[i - 1][0]
            dy = points[i][1] - points[i - 1][1]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist > max_gap:
                segments.append([])
            segments[-1].append(points[i])
        return [s for s in segments if len(s) >= 2]

    def _count_covered_cells(
        self, path: List[Tuple[float, float]], cell_mask: np.ndarray, coverage_px: int
    ) -> int:
        if not path:
            return 0
        h, w = cell_mask.shape[:2]
        coverage = np.zeros((h, w), dtype=np.uint8)
        radius = coverage_px // 2
        for px, py in path:
            ix, iy = int(round(px)), int(round(py))
            x0 = max(0, ix - radius)
            x1 = min(w, ix + radius + 1)
            y0 = max(0, iy - radius)
            y1 = min(h, iy + radius + 1)
            coverage[y0:y1, x0:x1] = 255
        covered = np.logical_and(coverage > 0, cell_mask > 0)
        return int(np.sum(covered))

    def _path_length(self, path: List[Tuple[float, float]]) -> float:
        total = 0.0
        for i in range(1, len(path)):
            dx = path[i][0] - path[i - 1][0]
            dy = path[i][1] - path[i - 1][1]
            total += math.sqrt(dx * dx + dy * dy)
        return total

    def _order_cells(
        self,
        cells: List[Tuple[int, np.ndarray, np.ndarray, np.ndarray]],
        starting_position: Tuple[float, float],
        map_resolution: float,
        R: np.ndarray | None,
        orig_h: int,
        orig_w: int,
    ) -> List[int]:
        if len(cells) <= 1:
            return list(range(len(cells)))

        if R is not None:
            R_inv = cv2.invertAffineTransform(R)
            sp = np.array([[starting_position[0], starting_position[1]]], dtype=np.float32)
            sp_rot = cv2.transform(sp.reshape(1, -1, 2), R_inv)[0][0]
            start_px = (float(sp_rot[0]), float(sp_rot[1]))
        else:
            start_px = (
                starting_position[0] / map_resolution,
                orig_h - starting_position[1] / map_resolution,
            )

        centroids = []
        for _, _, _, c in cells:
            centroids.append((float(c[0]), float(c[1])))

        n = len(cells)
        used = [False] * n
        order = []

        dists = [
            math.sqrt((c[0] - start_px[0]) ** 2 + (c[1] - start_px[1]) ** 2)
            for c in centroids
        ]
        current = min(range(n), key=lambda i: dists[i])
        used[current] = True
        order.append(current)

        for _ in range(n - 1):
            best_j = -1
            best_d = INF
            for j in range(n):
                if used[j]:
                    continue
                dx = centroids[j][0] - centroids[current][0]
                dy = centroids[j][1] - centroids[current][1]
                d = math.sqrt(dx * dx + dy * dy)
                if d < best_d:
                    best_d = d
                    best_j = j
            if best_j < 0:
                break
            used[best_j] = True
            order.append(best_j)
            current = best_j

        return order

    def _bridge_path(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        free_mask: np.ndarray,
    ) -> List[Tuple[float, float]]:
        h, w = free_mask.shape[:2]
        sx, sy = int(round(start[0])), int(round(start[1]))
        ex, ey = int(round(end[0])), int(round(end[1]))

        sx = max(0, min(w - 1, sx))
        sy = max(0, min(h - 1, sy))
        ex = max(0, min(w - 1, ex))
        ey = max(0, min(h - 1, ey))

        if sx == ex and sy == ey:
            return []

        path = self._bfs_path(free_mask, sx, sy, ex, ey)
        if path:
            return path[1:-1]

        steps = max(abs(ex - sx), abs(ey - sy))
        if steps == 0:
            return []
        bridge = []
        for i in range(1, steps):
            t = i / steps
            bx = sx + t * (ex - sx)
            by = sy + t * (ey - sy)
            bridge.append((bx, by))
        return bridge

    def _bfs_path(
        self, free_mask: np.ndarray, sx: int, sy: int, ex: int, ey: int
    ) -> List[Tuple[float, float]]:
        h, w = free_mask.shape[:2]
        if free_mask[sy, sx] == 0 or free_mask[ey, ex] == 0:
            return []

        visited = np.zeros((h, w), dtype=bool)
        parent = np.full((h, w, 2), -1, dtype=np.int32)
        queue = [(sx, sy)]
        visited[sy, sx] = True

        dirs = [
            (1, 0), (-1, 0), (0, 1), (0, -1),
            (1, 1), (1, -1), (-1, 1), (-1, -1),
        ]

        while queue:
            cx, cy = queue.pop(0)
            if cx == ex and cy == ey:
                break
            for dx, dy in dirs:
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx] and free_mask[ny, nx] > 0:
                    if dx != 0 and dy != 0:
                        if free_mask[cy, cx + dx] == 0 or free_mask[cy + dy, cx] == 0:
                            continue
                    visited[ny, nx] = True
                    parent[ny, nx] = [cx, cy]
                    queue.append((nx, ny))

        if not visited[ey, ex]:
            return []

        path = []
        cx, cy = ex, ey
        while cx != sx or cy != sy:
            path.append((float(cx), float(cy)))
            px, py = parent[cy, cx]
            cx, cy = int(px), int(py)
        path.append((float(sx), float(sy)))
        path.reverse()
        return path
