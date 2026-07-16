"""Improved basic coverage planner with configurable energy function.

Based on the same greedy grid-based concept as region_basic (Bormann et al. 2015),
but with a configurable energy function, direction inertia, and hard turn constraints.

Improvements:
- straight_ahead_weight / turn_penalty_weight / lateral_weight (from config)
- Direction inertia: bonus for continuing in the same direction
- Hard max_turn_deg constraint (reject trajectories exceeding the limit)
- Cleaner fallback strategy when stuck
"""

import math
import logging
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from ...contracts import CoveragePlannerConfig, CoverageResult, Pose2D
from .._basic_compat import (
    complete_cell_test,
    get_min_max_coords,
    pixels_to_world,
    rotate_room_auto,
    transform_path_back,
)

logger = logging.getLogger(__name__)

PI = math.pi
PI_2_INV = 1.0 / (0.5 * PI)


class CoveragePlanner:
    """Improved greedy grid-based coverage planner with configurable energy.

    Key differences from region_basic:
    - Energy weights read from config (straight_ahead, turn_penalty, lateral)
    - Direction inertia via direction tracking
    - Hard max turn angle from config
    """

    def __init__(self, config: Optional[CoveragePlannerConfig] = None):
        self.cfg = config or CoveragePlannerConfig()

    def plan(
        self,
        room_map: np.ndarray,
        map_resolution: float,
        starting_position: Tuple[int, int],
        map_origin: Tuple[float, float] = (0.0, 0.0),
    ) -> CoverageResult:
        if room_map is None or room_map.size == 0:
            return CoverageResult.failure_result(101, "Empty room map")

        if len(room_map.shape) == 3:
            room_map = cv2.cvtColor(room_map, cv2.COLOR_BGR2GRAY)
        room_map = room_map.astype(np.uint8)

        coverage_width_px = self.cfg.coverage_width_m / map_resolution
        cell_step = max(1, int(math.floor(coverage_width_px)))
        half_cell = max(1, int(math.floor(coverage_width_px * 0.5)))

        if self.cfg.auto_rotate:
            R, bbox, rotated = rotate_room_auto(room_map, map_resolution)
        else:
            R = np.eye(2, 3, dtype=np.float64)
            rotated = room_map.copy()
            bbox = (rotated.shape[1], rotated.shape[0])

        min_room, max_room = get_min_max_coords(rotated)
        if min_room is None:
            return CoverageResult.failure_result(102, "No free space")

        self._free = (rotated > 0).astype(np.uint8)

        nodes, first_free = self._build_grid(rotated, min_room, max_room, cell_step, half_cell)
        if first_free is None:
            return CoverageResult.failure_result(102, "No accessible grid nodes")

        sp = np.array([[starting_position[0], starting_position[1]]], dtype=np.float32)
        sp_rot = cv2.transform(sp.reshape(1, -1, 2), R)[0][0]

        start_node = self._find_start_node(nodes, first_free, (float(sp_rot[0]), float(sp_rot[1])))

        path = self._greedy_walk(nodes, start_node, coverage_width_px, map_resolution)
        path = self._cleanup_close_points(path, map_resolution)
        path = self._cleanup_isolated_points(path, map_resolution)
        path = self._bridge_jumps(path, map_resolution)

        path_px = transform_path_back(path, R)
        clamped = []
        oh, ow = room_map.shape[:2]
        for x, y in path_px:
            clamped.append((float(max(0, min(ow - 1, int(round(x))))),
                            float(max(0, min(oh - 1, int(round(y)))))))

        world = pixels_to_world(clamped, map_resolution, map_origin, oh)
        result_path = [Pose2D(wx, wy, theta) for wx, wy, theta in world]

        return CoverageResult.success_result(path=result_path, path_pixels=clamped)

    def _build_grid(self, room_map, min_room, max_room, cell_step, half_cell):
        nodes_2d = []
        first_free = None

        y = min_room[1] + half_cell
        while y < max_room[1]:
            row = []
            x = min_room[0] + half_cell
            while x < max_room[0]:
                ok, nx, ny = complete_cell_test(room_map, x, y, cell_step)
                row.append({
                    "x": nx if ok else x,
                    "y": ny if ok else y,
                    "obstacle": not ok,
                    "visited": ok is False,
                    "neighbors": [],
                })
                if ok and first_free is None:
                    first_free = (len(nodes_2d), len(row) - 1)
                x += cell_step
            nodes_2d.append(row)
            y += cell_step

        for r in range(len(nodes_2d)):
            for c in range(len(nodes_2d[r])):
                node = nodes_2d[r][c]
                if node["obstacle"]:
                    continue
                nbrs = []
                for dr in (-1, 0, 1):
                    nr = r + dr
                    if nr < 0 or nr >= len(nodes_2d):
                        continue
                    if c > 0:
                        nbrs.append(nodes_2d[nr][c - 1])
                    if dr != 0:
                        nbrs.append(nodes_2d[nr][c])
                    if c < len(nodes_2d[nr]) - 1:
                        nbrs.append(nodes_2d[nr][c + 1])
                node["neighbors"] = nbrs

        return nodes_2d, first_free

    @staticmethod
    def _find_start_node(nodes_2d, first_free, rotated_start):
        sx, sy = rotated_start
        best_r, best_c = first_free
        best_d2 = 1e18
        for r in range(len(nodes_2d)):
            for c in range(len(nodes_2d[r])):
                node = nodes_2d[r][c]
                if node["obstacle"]:
                    continue
                dx = node["x"] - sx
                dy = node["y"] - sy
                d2 = dx * dx + dy * dy
                if d2 < best_d2:
                    best_d2 = d2
                    best_r, best_c = r, c
        return nodes_2d[best_r][best_c]

    def _energy(self, current, neighbor, cell_size_px, prev_angle, map_resolution, is_fallback):
        dx = neighbor["x"] - current["x"]
        dy = neighbor["y"] - current["y"]
        dist_px = math.sqrt(dx * dx + dy * dy)

        e = dist_px / cell_size_px

        travel_angle = math.atan2(dy, dx)
        diff = travel_angle - prev_angle
        while diff < -PI:
            diff += 2 * PI
        while diff > PI:
            diff -= 2 * PI

        cfg = self.cfg
        abs_deg = abs(diff) * 180.0 / PI

        if cfg.turn_constraint_enable and not is_fallback:
            dist_m = dist_px * map_resolution
            if dist_m <= cfg.turn_constraint_near_dist_m:
                if abs_deg > cfg.turn_constraint_near_max_turn_deg:
                    return cfg.turn_constraint_prohibit_energy
            else:
                allowed = cfg.turn_constraint_neighbor_max_turn_deg
                if abs_deg > allowed:
                    return cfg.turn_constraint_prohibit_energy

        e += abs(diff) * PI_2_INV * cfg.turn_penalty_weight

        abs_dx = abs(dx)
        abs_dy = abs(dy)
        ratio = abs_dx / (abs_dx + abs_dy + 1e-6)
        e += cfg.lateral_weight * (8.0 - 1.5 * ratio)

        if abs_deg < 30.0:
            e -= cfg.straight_ahead_weight * (1.0 - abs_deg / 30.0)

        return e

    def _greedy_walk(self, nodes_2d, start_node, coverage_width_px, map_resolution):
        path = [(float(start_node["x"]), float(start_node["y"]))]
        start_node["visited"] = True

        prev_angle = 0.0
        for nb in start_node["neighbors"]:
            if nb["obstacle"]:
                continue
            if nb["y"] == start_node["y"] and nb["x"] > start_node["x"]:
                prev_angle = 0.0
                break
            if nb["y"] == start_node["y"] and nb["x"] < start_node["x"]:
                prev_angle = PI
                break
            if nb["y"] < start_node["y"] and nb["x"] == start_node["x"]:
                prev_angle = -0.5 * PI
                break
            if nb["y"] > start_node["y"] and nb["x"] == start_node["x"]:
                prev_angle = 0.5 * PI
                break

        current = start_node

        while True:
            best_nb = None
            best_e = 1e10

            for nb in current["neighbors"]:
                if nb["obstacle"] or nb["visited"]:
                    continue
                e = self._energy(current, nb, coverage_width_px, prev_angle, map_resolution, False)
                if e < best_e:
                    best_e = e
                    best_nb = nb

            if best_nb is None:
                best_e = 1e10
                for r in range(len(nodes_2d)):
                    for c in range(len(nodes_2d[r])):
                        nb = nodes_2d[r][c]
                        if nb["obstacle"] or nb["visited"]:
                            continue
                        e = self._energy(current, nb, coverage_width_px, prev_angle, map_resolution, True)
                        if e < best_e:
                            best_e = e
                            best_nb = nb

            if best_nb is None:
                logger.warning("No feasible next node, terminating at %d points", len(path))
                break

            prev_angle = math.atan2(best_nb["y"] - current["y"], best_nb["x"] - current["x"])
            path.append((float(best_nb["x"]), float(best_nb["y"])))
            best_nb["visited"] = True
            current = best_nb

        return path

    @staticmethod
    def _cleanup_close_points(path, resolution, min_dist_m=0.3):
        if len(path) < 2:
            return path
        min_px = min_dist_m / resolution if resolution > 0 else 6.0
        kept = [path[0]]
        for i in range(1, len(path)):
            px, py = path[i]
            lx, ly = kept[-1]
            if math.hypot(px - lx, py - ly) < min_px:
                continue
            kept.append(path[i])
        if len(kept) != len(path):
            logger.info("Removed %d close points (dist < %.2fm)", len(path) - len(kept), min_dist_m)
        return kept

    def _bridge_jumps(self, path, resolution, jump_threshold_m=1.5):
        if len(path) < 2:
            return path
        jump_px = jump_threshold_m / resolution if resolution > 0 else 30.0
        n_interp = max(1, int(self.cfg.jump_bridge_interpolations))
        h, w = self._free.shape
        result = [path[0]]
        for i in range(1, len(path)):
            px, py = path[i]
            lx, ly = result[-1]
            d = math.hypot(px - lx, py - ly)
            if d > jump_px:
                pts = self._astar_path((int(round(lx)), int(round(ly))),
                                       (int(round(px)), int(round(py))), h, w)
                if pts and len(pts) > 2:
                    n_total = len(pts)
                    for k in range(1, n_interp + 1):
                        idx = int(round(k * (n_total - 1) / (n_interp + 1)))
                        idx = max(1, min(n_total - 2, idx))
                        result.append((float(pts[idx][0]), float(pts[idx][1])))
                    continue
            result.append((float(px), float(py)))
        if len(result) != len(path):
            logger.info("Bridged %d jump gaps", len(path) - len(result))
        return result

    def _astar_path(self, start, goal, h, w):
        import heapq
        sx, sy = start
        gx, gy = goal
        if not (0 <= sx < w and 0 <= sy < h) or not (0 <= gx < w and 0 <= gy < h):
            return [start, goal]
        free = self._free
        if free[sy, sx] == 0 or free[gy, gx] == 0:
            return [start, goal]
        open_set = [(0.0, sx, sy)]
        came_from = {}
        g_score = {(sx, sy): 0.0}
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

    @staticmethod
    def _cleanup_isolated_points(path, min_distance_m=1.5, resolution=0.0):
        if len(path) < 3:
            return path
        min_dist_px = min_distance_m / resolution if resolution > 0 else 1.5 / 0.05
        kept = [path[0]]
        for i in range(1, len(path) - 1):
            ax, ay = path[i - 1]
            bx, by = path[i]
            cx, cy = path[i + 1]
            d1 = math.hypot(bx - ax, by - ay)
            d2 = math.hypot(cx - bx, cy - by)
            if d1 > min_dist_px and d2 > min_dist_px:
                continue
            kept.append(path[i])
        kept.append(path[-1])
        if len(kept) != len(path):
            logger.info("Cleaned up %d isolated points", len(path) - len(kept))
        return kept
