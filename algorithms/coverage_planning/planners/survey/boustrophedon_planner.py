from __future__ import annotations

import math

import cv2
import numpy as np

from ...contracts import CoveragePlannerConfig, CoverageResult, Pose2D
from .._basic_compat import (
    compute_rotation_matrix,
    pixels_to_world,
    rotate_room_auto,
    transform_path_back,
)

INF = float("inf")


class BoustrophedonCoveragePlanner:
    """Boustrophedon (back-and-forth) coverage path planner.

    Based on the classic boustrophedon pattern described in
    Fevgas et al. 2022 (Sensors survey), Section 3.1.
    Sweeps the area perpendicular to its main axis.
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

        free_mask = (rotated > 0).astype(np.uint8)
        free_ys, free_xs = np.where(free_mask == 1)
        if len(free_ys) == 0:
            return CoverageResult.failure_result(2, error_message="no free space")

        min_y, max_y = int(free_ys.min()), int(free_ys.max())
        min_x, max_x = int(free_xs.min()), int(free_xs.max())

        area_w = max_x - min_x + 1
        area_h = max_y - min_y + 1

        if area_w >= area_h:
            sweep_static = False
            num_sweeps = max(1, area_h // coverage_px)
            spacing = area_h / num_sweeps if num_sweeps > 0 else coverage_px
        else:
            sweep_static = True
            num_sweeps = max(1, area_w // coverage_px)
            spacing = area_w / num_sweeps if num_sweeps > 0 else coverage_px

        path_px = []
        for i in range(num_sweeps + 1):
            if sweep_static:
                line_x = min_x + i * spacing
            else:
                line_y = min_y + i * spacing

            if sweep_static:
                sweep_pts = self._sample_col(free_mask, int(round(line_x)), min_y, max_y, step_px)
            else:
                sweep_pts = self._sample_row(free_mask, int(round(line_y)), min_x, max_x, step_px)

            if i % 2 == 1:
                sweep_pts.reverse()

            path_px.extend(sweep_pts)

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

    def _sample_row(self, mask, row_y, x0, x1, step_px):
        if row_y < 0 or row_y >= mask.shape[0]:
            return []
        row = mask[row_y, x0:x1 + 1]
        free_indices = np.where(row == 1)[0]
        if len(free_indices) == 0:
            return []
        segs = self._segments(free_indices)
        pts = []
        for seg_start, seg_end in segs:
            for px in range(seg_start, seg_end + 1, step_px):
                pts.append((float(x0 + px), float(row_y)))
            last = (float(x0 + seg_end), float(row_y))
            if not pts or pts[-1] != last:
                pts.append(last)
        return pts

    def _sample_col(self, mask, col_x, y0, y1, step_px):
        if col_x < 0 or col_x >= mask.shape[1]:
            return []
        col = mask[y0:y1 + 1, col_x]
        free_indices = np.where(col == 1)[0]
        if len(free_indices) == 0:
            return []
        segs = self._segments(free_indices)
        pts = []
        for seg_start, seg_end in segs:
            for py in range(seg_start, seg_end + 1, step_px):
                pts.append((float(col_x), float(y0 + py)))
            last = (float(col_x), float(y0 + seg_end))
            if not pts or pts[-1] != last:
                pts.append(last)
        return pts

    @staticmethod
    def _segments(indices):
        if len(indices) == 0:
            return []
        segs = []
        start = indices[0]
        prev = indices[0]
        for i in indices[1:]:
            if i != prev + 1:
                segs.append((int(start), int(prev)))
                start = i
            prev = i
        segs.append((int(start), int(prev)))
        return segs
