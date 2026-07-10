"""edge-like 扇区端点的邻域裁剪与吸附修正。"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from .common import SectorModel
from .sector_line import pca_linearity, project_point_to_line


def snap_endpoint_to_hit_if_needed(
    endpoint_rc: tuple[int, int],
    hit_points_rc: list[tuple[int, int]],
    free_mask: np.ndarray,
) -> tuple[int, int]:
    """在 edge-like 端点落入自由区时，把它吸附回最近命中点。"""

    # 落到图外时不修，直接返回原端点。
    rr, cc = endpoint_rc
    if rr < 0 or rr >= free_mask.shape[0] or cc < 0 or cc >= free_mask.shape[1]:
        return endpoint_rc
    if free_mask[rr, cc] == 0 or not hit_points_rc:
        # 端点已经在障碍上，或者根本没有 hit，可直接接受。
        return endpoint_rc

    # 否则从 hit 点里找一个最近替身，把端点吸附回真实边界。
    # 这一步避免 edge 端点落在自由区内部，导致 polygon 过度外扩。
    # 吸附范围被限制在当前扇区命中点集合内，避免跨扇区串边。
    endpoint_xy = np.asarray([float(endpoint_rc[1]), float(endpoint_rc[0])], dtype=np.float64)
    best_point = endpoint_rc
    best_dist = float("inf")
    for hit_rc in hit_points_rc:
        # 最近邻只在当前扇区的命中点里选，避免跨扇区把端点吸到错误边上。
        hit_xy = np.asarray([float(hit_rc[1]), float(hit_rc[0])], dtype=np.float64)
        dist = float(np.linalg.norm(hit_xy - endpoint_xy))
        if dist < best_dist:
            best_dist = dist
            best_point = hit_rc
    # 返回值一定来自真实 hit 集，因此天然位于当前扇区的边界支撑上。
    return best_point


def refine_edge_endpoints_from_neighbors(
    sectors: list[SectorModel],
    free_mask: np.ndarray,
) -> list[SectorModel]:
    """用相邻 corner 位置裁剪 edge-like 端点，并保证端点落在真实支撑边界上。"""

    # 没有 sector 时自然无需修正。
    if not sectors:
        return sectors

    refined: list[SectorModel] = []
    count = len(sectors)
    for index, sector in enumerate(sectors):
        # 只有 edge-like 且 hit 足够多的扇区，才值得进一步修边端点。
        # 其余扇区直接原样透传。
        if sector.chosen_type != "edge-like" or len(sector.hit_points_rc) < 3:
            refined.append(sector)
            continue

        prev_sector = sectors[(index - 1) % count]
        next_sector = sectors[(index + 1) % count]
        neighbor_refs: list[tuple[int, int]] = []
        if prev_sector.chosen_type == "corner-like" and prev_sector.representative_point_rc is not None:
            neighbor_refs.append(prev_sector.representative_point_rc)
        if next_sector.chosen_type == "corner-like" and next_sector.representative_point_rc is not None:
            neighbor_refs.append(next_sector.representative_point_rc)
        # 没有两侧 corner 参考时，就无法可靠裁剪 edge 端点。
        # 因而这里要求至少两个邻角参考。
        if len(neighbor_refs) < 2:
            refined.append(sector)
            continue

        # 重新在 hit 点上拟合主线，并把相邻 corner 投影到该线。
        pts = np.asarray([[float(c), float(r)] for r, c in sector.hit_points_rc], dtype=np.float64)
        line_center_xy = np.mean(pts, axis=0)
        _, _, _, line_dir_xy = pca_linearity(sector.hit_points_rc)
        proj = (pts - line_center_xy) @ line_dir_xy
        q0 = float(np.percentile(proj, 10.0))
        q1 = float(np.percentile(proj, 90.0))
        if q1 < q0:
            q0, q1 = q1, q0
        # q0/q1 描述当前 edge-like hit 在主方向上的主体区间。

        # 相邻 corner 的投影坐标会被裁剪进当前 edge-like span 区间。
        # 这相当于让角点来“截断”边段的两端。
        clipped_scalars: list[float] = []
        for ref_rc in neighbor_refs:
            _, scalar = project_point_to_line(ref_rc, line_center_xy, line_dir_xy)
            clipped_scalars.append(float(np.clip(scalar, q0, q1)))
        clipped_scalars.sort()
        # 两个投影太近时，不足以形成稳定 edge 段，直接保留原端点。
        # 这样可以避免极短边段把 polygon 顶点挤得过密。
        if len(clipped_scalars) < 2 or abs(clipped_scalars[1] - clipped_scalars[0]) < 6.0:
            # 相邻角点投影跨度太小时，裁出来的 edge 端点会非常不稳，这里宁可保留原端点。
            refined.append(sector)
            continue

        # 先按裁剪后的投影值恢复新端点，再吸附回真实 hit 边界。
        # 这里先在连续空间算端点，再离散化到像素。
        # 两步拆开做的原因是：角点负责裁 span，hit 点负责保真边界落点。
        point0_xy = line_center_xy + clipped_scalars[0] * line_dir_xy
        point1_xy = line_center_xy + clipped_scalars[1] * line_dir_xy
        new_endpoints = [
            (int(round(point0_xy[1])), int(round(point0_xy[0]))),
            (int(round(point1_xy[1])), int(round(point1_xy[0]))),
        ]
        new_endpoints = [
            snap_endpoint_to_hit_if_needed(new_endpoints[0], sector.hit_points_rc, free_mask),
            snap_endpoint_to_hit_if_needed(new_endpoints[1], sector.hit_points_rc, free_mask),
        ]
        # 这里只替换端点，其它 sector 统计值保持原样。
        # replace 能保证 SectorModel 其余字段原封不动保留下来。
        # 因而 refine 阶段只修边界几何，不改动判型结论本身。
        refined.append(replace(sector, edge_endpoints_rc=new_endpoints))
    return refined


__all__ = (
    "refine_edge_endpoints_from_neighbors",
)
