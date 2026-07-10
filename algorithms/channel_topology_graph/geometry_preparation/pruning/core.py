"""基础几何准备中的短枝修剪正式实现。"""

from __future__ import annotations

from typing import Any

import numpy as np

from .neighbor_topology import (
    GROUP_COUNT_LUT,
    POPCOUNT_LUT,
    build_neighbor_mask_map,
    endpoint_mask_from_neighbor_masks,
)
from .trace import find_short_side_branches_once, update_neighbor_masks_local
from ..preprocessing import kernel_px_from_meters
from ..skeleton import SkeletonView, extract_pixels_rc


def build_initial_pruning_state(
    skeleton_view: SkeletonView,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """构造 pruning 循环的初始骨架与邻域状态。"""

    skeleton01 = np.where(skeleton_view.skeleton_mask > 0, 1, 0).astype(np.uint8)
    neighbor_masks = build_neighbor_mask_map(skeleton01)
    current01 = skeleton01.copy()
    current_neighbor_masks = neighbor_masks.copy()
    current_endpoint_mask = endpoint_mask_from_neighbor_masks(current01, current_neighbor_masks)
    # skeleton01 保留原始修剪输入，current01 才是循环内持续被修改的工作骨架。
    return skeleton01, current01, current_neighbor_masks, current_endpoint_mask


def build_pruning_iteration_record(
    *,
    endpoints_rc: list[tuple[int, int]],
    iteration_removed_mask: np.ndarray,
    iteration_items: list[dict[str, Any]],
    current01: np.ndarray,
) -> dict[str, Any]:
    """构造单轮 pruning debug 条目。"""

    return {
        "endpoint_count_before": len(endpoints_rc),
        "short_side_branch_count": len(iteration_items),
        "removed_pixels": int(np.count_nonzero(iteration_removed_mask)),
        "removed_mask": np.where(iteration_removed_mask > 0, 255, 0).astype(np.uint8),
        "skeleton_after_mask": np.where(current01 > 0, 255, 0).astype(np.uint8),
    }


def refresh_pruning_state_after_removal(
    *,
    current01: np.ndarray,
    current_neighbor_masks: np.ndarray,
    current_endpoint_mask: np.ndarray,
    iteration_removed_mask: np.ndarray,
) -> None:
    """把本轮删除建议写回骨架并局部刷新邻域/端点状态。"""

    current01[iteration_removed_mask > 0] = 0
    affected_mask = update_neighbor_masks_local(current01, current_neighbor_masks, iteration_removed_mask)
    current_endpoint_mask[iteration_removed_mask > 0] = 0
    for r, c in np.argwhere(affected_mask > 0):
        rr = int(r)
        cc = int(c)
        current_endpoint_mask[rr, cc] = 1 if (
            current01[rr, cc] > 0 and GROUP_COUNT_LUT[int(current_neighbor_masks[rr, cc])] == 1
        ) else 0


def build_pruned_skeleton_view(
    *,
    skeleton_view: SkeletonView,
    current01: np.ndarray,
) -> SkeletonView:
    """组装 pruning 结束后的正式 SkeletonView。"""

    skeleton_pruned_mask = np.where(current01 > 0, 255, 0).astype(np.uint8)
    return SkeletonView(
        skeleton_mask=skeleton_view.skeleton_mask,
        skeleton_pruned_mask=skeleton_pruned_mask,
        skeleton_pixels_rc=extract_pixels_rc(skeleton_pruned_mask),
        method=skeleton_view.method,
    )


def prune_short_side_branches(
    skeleton_view: SkeletonView,
    resolution_m_per_px: float,
    config: dict[str, Any] | None = None,
) -> tuple[SkeletonView, dict[str, Any]]:
    """对骨架做短枝修剪。

    真实职责：
        删除显著短于主通道的侧枝毛刺，同时保留真正接到交汇或断头路的主干。
        这一过程必须保守，宁可少删，也不能掐断主干通路。

    Args:
        skeleton_view:
            原始骨架视图。
        resolution_m_per_px:
            运行尺度米/像素分辨率。用于把米制门限换算成像素。
        config:
            修剪参数。支持：
            `short_side_branch_px`
            `short_side_branch_m`

    Returns:
        tuple[SkeletonView, dict[str, Any]]:
            修剪后的骨架视图，以及修剪过程调试信息。
    """

    if config is None:
        config = {}

    # 像素级短枝门限统一在入口解析，后续循环只处理纯像素语义。
    short_side_branch_px = derive_short_side_branch_px(config, resolution_m_per_px)
    skeleton01, current01, current_neighbor_masks, current_endpoint_mask = build_initial_pruning_state(
        skeleton_view
    )

    pruning_iterations: list[dict[str, Any]] = []
    removed_mask = np.zeros_like(current01, dtype=np.uint8)
    while True:
        # 每轮都基于当前骨架重算端点列表，确保删除结果会反馈到下一轮。
        endpoints_rc = [tuple(map(int, p)) for p in np.argwhere(current_endpoint_mask > 0)]
        iteration_removed_mask, iteration_items = find_short_side_branches_once(
            skeleton01=current01,
            neighbor_masks=current_neighbor_masks,
            endpoints_rc=endpoints_rc,
            short_side_branch_px=short_side_branch_px,
            resolution_m_per_px=resolution_m_per_px,
        )
        pruning_iterations.append(
            build_pruning_iteration_record(
                endpoints_rc=endpoints_rc,
                iteration_removed_mask=iteration_removed_mask,
                iteration_items=iteration_items,
                current01=current01,
            )
        )
        if int(np.count_nonzero(iteration_removed_mask)) == 0:
            break

        # 真正写回删除发生在这里，单轮 helper 只负责提出删除建议。
        removed_mask = np.maximum(removed_mask, iteration_removed_mask)
        refresh_pruning_state_after_removal(
            current01=current01,
            current_neighbor_masks=current_neighbor_masks,
            current_endpoint_mask=current_endpoint_mask,
            iteration_removed_mask=iteration_removed_mask,
        )
        # 删除造成的局部拓扑变化只在 affected 区域内重新解释。
        # 这样每轮删除都会在下一轮端点分布上得到真实反馈。
        # 这比整图重算端点与邻域表更稳也更省。
        # 端点图更新完成后，下一轮会在新的骨架状态上继续找短枝。
        # 这使整个修剪过程形成“删一点、局部刷新、再判断”的保守闭环。
        # 也因此循环退出条件必须建立在“本轮没有新删除”而不是“端点为空”。

    # 单像素孤点不会形成有效通道主干，最后再统一清掉。
    isolated_mask = np.where((current01 > 0) & (POPCOUNT_LUT[current_neighbor_masks] == 0), 1, 0).astype(np.uint8)
    if int(np.count_nonzero(isolated_mask)) > 0:
        # 单像素孤点已经不属于任何可追踪主干，保留它只会给下游制造伪边。
        current01[isolated_mask > 0] = 0
        removed_mask = np.maximum(removed_mask, isolated_mask)
        # 这里不再继续刷新邻域状态，因为流程已经到最终扫尾阶段，不会再进入下一轮判定。
        # 这里不再单独更新 endpoint 图，因为修剪流程已经结束。
        # 孤点清理属于最终扫尾，不会再触发下一轮 branch search。

    # 返回的 pruned_view 会成为 geometry_preparation 正式骨架真值，debug_info 只附加修剪轨迹。
    pruned_view = build_pruned_skeleton_view(
        skeleton_view=skeleton_view,
        current01=current01,
    )
    # debug_info 只记录关键过程计数和每轮中间产物，不复制整套运行状态。
    debug_info = {
        "short_side_branch_px": short_side_branch_px,
        "pruning_iterations": pruning_iterations,
        "removed_pixel_count": int(np.count_nonzero(removed_mask)),
    }
    # pruned_view 才是下游正式消费对象，debug_info 只是附加解释层。
    # 这种主对象/调试对象分离，也让 stage 结果更容易做基线 compare。
    # 两者一起返回，既保证主线对象干净，也保留足够的排查信息。
    # 调用方可以只消费 pruned_view，也可以在 detail 模式下展开 debug_info。
    return pruned_view, debug_info


def derive_short_side_branch_px(config: dict[str, Any], resolution_m_per_px: float) -> int:
    """把短枝门限转成运行尺度像素。"""

    # 显式像素门限优先级高于米制门限。
    if "short_side_branch_px" in config:
        return max(1, int(config["short_side_branch_px"]))
    short_side_branch_m = float(config.get("short_side_branch_m", 1.2))
    # 米制门限统一复用公共换算逻辑，避免不同 helper 各写一套比例规则。
    return kernel_px_from_meters(short_side_branch_m, resolution_m_per_px)
