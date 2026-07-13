from __future__ import annotations

import math

import numpy as np

from ...contracts import CoverageResult, Pose2D

INF = float("inf")


def gbnn_dynamics_step(act, nodes, step_sq, A, B, D, E, visited):
    n = len(nodes)
    new_act = np.empty_like(act)
    for i, node in enumerate(nodes):
        xi = act[i]
        I_i = E if not visited[i] else -E
        exc_sum = 0.0
        inh_sum = 0.0
        for nb in (node.left, node.right, node.up, node.down):
            if nb is None:
                continue
            d2 = (nb.x - node.x) ** 2 + (nb.y - node.y) ** 2
            w = math.exp(-d2 / step_sq)
            xj = act[nb.id]
            if xj > 0:
                exc_sum += w * xj
            else:
                inh_sum += w * (-xj)
        dxi = -A * xi + (B - xi) * (I_i + exc_sum) - (D + xi) * inh_sum
        new_act[i] = xi + dxi
    np.clip(new_act, -D, B, out=new_act)
    return new_act


def postprocess_path(path_nodes, map_resolution, map_origin, map_h):
    """Post-processing per document: merge <0.3m, angle cleanup.
    
    像素坐标 Y 向下, ROS 世界坐标 Y 向上, 需要翻转.
    """
    path_px = []
    seen = set()
    for n in path_nodes:
        key = (n.x, n.y)
        if key not in seen:
            seen.add(key)
            path_px.append(key)

    world = []
    for x, y in path_px:
        wx = x * map_resolution + map_origin[0]
        wy = (map_h - y) * map_resolution + map_origin[1]
        world.append((wx, wy))

    if not world:
        return CoverageResult.success_result(path=[], path_pixels=[])

    path = [Pose2D(x, y, 0.0) for x, y in world]
    for i in range(len(path)):
        if i < len(path) - 1:
            dx = path[i + 1].x - path[i].x
            dy = path[i + 1].y - path[i].y
            path[i].theta = math.atan2(dy, dx)
        else:
            path[i].theta = path[i - 1].theta if i > 0 else 0.0

    path_px_final = [(float(x), float(y)) for x, y in path_px]
    return CoverageResult.success_result(path=path, path_pixels=path_px_final)
