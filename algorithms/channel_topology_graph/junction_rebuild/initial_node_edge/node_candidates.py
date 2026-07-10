"""初始交汇/断头路候选提取逻辑。"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from ...contracts import GeometryPreparationResult
from ...geometry_preparation.pruning import (
    GROUP_COUNT_LUT,
    POPCOUNT_LUT,
    build_neighbor_mask_map,
    endpoint_mask_from_neighbor_masks,
)


def derive_initial_junction_candidates(geometry_result: GeometryPreparationResult) -> list[dict[str, Any]]:
    """从修剪后骨架中提炼交汇候选视图。"""

    # 先把修剪后骨架压成 0/1 mask，便于直接跑邻域 LUT 规则。
    skeleton01 = np.where(geometry_result.skeleton_pruned_mask > 0, 1, 0).astype(np.uint8)
    neighbor_masks = build_neighbor_mask_map(skeleton01)

    # 交汇候选沿用旧研究代码的核心判据：
    # 至少 3 个邻居，并且 8 邻域在环上至少形成 3 个连续组。
    intersection_keep_mask = np.where(
        (skeleton01 > 0)
        & (POPCOUNT_LUT[neighbor_masks] >= 3)
        & (GROUP_COUNT_LUT[neighbor_masks] >= 3),
        255,
        0,
    ).astype(np.uint8)
    # 候选像素最后再压成连通分量代表点，避免一个交汇产生多个节点。
    # 这样返回结果天然就是“节点级候选”，而不再是像素级候选。
    return compress_point_components(intersection_keep_mask)


def derive_initial_dead_end_candidates(geometry_result: GeometryPreparationResult) -> list[dict[str, Any]]:
    """从修剪后骨架中提炼断头路候选视图。"""

    # 断头路候选沿用 endpoint 判据：在骨架上表现为单出口像素。
    skeleton01 = np.where(geometry_result.skeleton_pruned_mask > 0, 1, 0).astype(np.uint8)
    neighbor_masks = build_neighbor_mask_map(skeleton01)
    endpoint_mask = np.where(endpoint_mask_from_neighbor_masks(skeleton01, neighbor_masks) > 0, 255, 0).astype(
        np.uint8
    )
    # endpoint mask 同样会在下一步压成连通分量代表点。
    # 因而这里返回的也已经是节点级候选，而不是像素级列表。
    return compress_point_components(endpoint_mask)


def compress_point_components(mask255: np.ndarray) -> list[dict[str, Any]]:
    """把像素级候选点压成代表点。"""

    # 没有候选像素时直接返回空列表。
    if int(np.count_nonzero(mask255)) == 0:
        # 上游规则没保留下任何候选像素时，不在这里硬造 component。
        return []
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask255, 8)
    items: list[dict[str, Any]] = []
    for label in range(1, int(num_labels)):
        # 每个连通分量都会被压成一个代表点和一份 bbox/member 集。
        member_points_rc = [tuple(map(int, p)) for p in np.argwhere(labels == label)]
        centroid_xy = centroids[label]
        # representative 选离质心最近的真实像素，而不是直接取浮点质心。
        # 这样代表点始终落在原 mask 上，便于后续直接当节点像素使用。
        # 若多个点到质心距离相同，则继续按行列序稳定打破平局。
        # 因而 representative 的选择对基线结果是确定性的。
        # 这也是后续 node_id 稳定分配的前提之一。
        representative = min(
            member_points_rc,
            key=lambda p: (
                (p[1] - float(centroid_xy[0])) ** 2 + (p[0] - float(centroid_xy[1])) ** 2,
                p[0],
                p[1],
            ),
        )
        # 输出结构全部是 JSON 友好字段，方便直接写入 debug/runtime。
        # bbox 则为后续人工排查提供最小包围盒上下文。
        # component_id 保留原 connected component 标签，便于回溯。
        # member_points_rc 则保留完整像素真值，方便后续压测和排障。
        # 这一层不会筛掉任何 component，所有筛选都发生在上游 mask 构造阶段。
        # 因而 items 数量与 connected component 数量严格一致。
        # 返回列表顺序也跟 label 顺序一致，天然稳定。
        # 这对后续 node_id 稳定映射同样重要。
        items.append(
            {
                "component_id": int(label),
                "member_points_rc": [[int(r), int(c)] for r, c in member_points_rc],
                "representative_point_rc": [int(representative[0]), int(representative[1])],
                "bbox": {
                    "r_min": int(stats[label, cv2.CC_STAT_TOP]),
                    "c_min": int(stats[label, cv2.CC_STAT_LEFT]),
                    "r_max": int(stats[label, cv2.CC_STAT_TOP] + stats[label, cv2.CC_STAT_HEIGHT] - 1),
                    "c_max": int(stats[label, cv2.CC_STAT_LEFT] + stats[label, cv2.CC_STAT_WIDTH] - 1),
                },
            }
        )
    return items


__all__ = (
    "derive_initial_junction_candidates",
    "derive_initial_dead_end_candidates",
    "compress_point_components",
)
