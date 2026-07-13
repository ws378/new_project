from __future__ import annotations

import math

import numpy as np

from ...contracts import CoveragePlannerConfig, CoverageResult, Pose2D
from .._basic_compat import (
    compute_rotation_matrix,
    pixels_to_world,
    rotate_room_auto,
    transform_path_back,
)


class SpiralCoveragePlanner:
    """Spiral coverage path planner.

    Based on the square/spiral pattern described in
    Fevgas et al. 2022 (Sensors survey), Section 3.1/3.18.
    Starts from the centroid and spirals outward.
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
        spacing_px = max(1, int(round(self.cfg.coverage_width_m / map_resolution)))

        free_mask = (rotated > 0).astype(np.uint8)
        free_ys, free_xs = np.where(free_mask == 1)
        if len(free_ys) == 0:
            return CoverageResult.failure_result(2, error_message="no free space")

        cx = int(round(free_xs.mean()))
        cy = int(round(free_ys.mean()))

        path_px = [(float(cx), float(cy))]

        layer = 1
        max_layers = max(h, w) // spacing_px + 2
        for _ in range(max_layers):
            x0 = cx - layer * spacing_px
            x1 = cx + layer * spacing_px
            y0 = cy - layer * spacing_px
            y1 = cy + layer * spacing_px

            top = self._scan_row(free_mask, y0, x0, x1, step_px)
            right = self._scan_col(free_mask, x1, y0 + spacing_px, y1, step_px)
            bottom = self._scan_row(free_mask, y1, x1, x0, step_px)
            left = self._scan_col(free_mask, x0, y1 - spacing_px, y0 + spacing_px, step_px)

            for seg in (top, right, bottom, left):
                if seg:
                    last = seg[-1]
                    if path_px and (seg[0] != path_px[-1]):
                        path_px.extend(seg)
                    else:
                        path_px.extend(seg[1:] if len(seg) > 1 else seg)
                    if (abs(last[0] - cx) <= spacing_px and abs(last[1] - cy) <= spacing_px):
                        pass

            layer += 1
            if x0 < 0 and x1 >= w and y0 < 0 and y1 >= h:
                break

        if len(path_px) <= 1:
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

    def _scan_row(self, mask, row_y, x_start, x_end, step_px):
        if row_y < 0 or row_y >= mask.shape[0]:
            return []
        if x_start > x_end:
            x_start, x_end = x_end, x_start
        x0 = max(0, int(round(x_start)))
        x1 = min(mask.shape[1] - 1, int(round(x_end)))
        if x1 <= x0:
            return []
        row = mask[row_y, x0:x1 + 1]
        free = np.where(row == 1)[0]
        if len(free) == 0:
            return []
        segs = self._segments(free)
        pts = []
        for s, e in segs:
            for px in range(x0 + s, x0 + e + 1, step_px):
                if 0 <= px < mask.shape[1]:
                    pts.append((float(px), float(row_y)))
            last_x = x0 + e
            if 0 <= last_x < mask.shape[1]:
                last = (float(last_x), float(row_y))
                if not pts or pts[-1] != last:
                    pts.append(last)
        return pts

    def _scan_col(self, mask, col_x, y_start, y_end, step_px):
        if col_x < 0 or col_x >= mask.shape[1]:
            return []
        if y_start > y_end:
            y_start, y_end = y_end, y_start
        y0 = max(0, int(round(y_start)))
        y1 = min(mask.shape[0] - 1, int(round(y_end)))
        if y1 <= y0:
            return []
        col = mask[y0:y1 + 1, col_x]
        free = np.where(col == 1)[0]
        if len(free) == 0:
            return []
        segs = self._segments(free)
        pts = []
        for s, e in segs:
            for py in range(y0 + s, y0 + e + 1, step_px):
                if 0 <= py < mask.shape[0]:
                    pts.append((float(col_x), float(py)))
            last_y = y0 + e
            if 0 <= last_y < mask.shape[0]:
                last = (float(col_x), float(last_y))
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
