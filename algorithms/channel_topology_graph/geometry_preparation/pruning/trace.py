"""短枝修剪中的 trace 与局部更新 helper。"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from .neighbor_topology import (
    POPCOUNT_LUT,
    RING_OFFSETS,
    endpoint_trace_starts,
    neighbor_mask_at,
)


def select_best_endpoint_trace(
    *,
    start_rc: tuple[int, int],
    trace_starts: list[tuple[int, int]],
    neighbor_masks: np.ndarray,
    short_side_branch_px: int,
    reason_priority: dict[str, int],
) -> dict[str, Any]:
    """为单个端点选择最具代表性的 trace 结果。"""

    return max(
        (
            trace_from_node(
                start_rc=start_rc,
                next_rc=next_rc,
                neighbor_masks=neighbor_masks,
                max_trace_px=short_side_branch_px,
            )
            for next_rc in trace_starts
        ),
        key=lambda item: (int(item["path_length_px"]), reason_priority.get(str(item["end_reason"]), -1)),
    )


def record_short_side_branch(
    side_branch_items: list[dict[str, Any]],
    traced: dict[str, Any],
    resolution_m_per_px: float,
) -> None:
    """把单条短侧枝 trace 写入 debug 条目。"""

    path_rc = traced["path_rc"]
    length_px = int(traced["path_length_px"])
    side_branch_items.append(
        {
            "path_rc": [[int(r), int(c)] for r, c in path_rc],
            "length_px": length_px,
            "length_m": float(length_px * resolution_m_per_px),
            "end_reason": str(traced["end_reason"]),
        }
    )


def mark_branch_pixels_for_removal(removed_mask: np.ndarray, path_rc: list[tuple[int, int]]) -> None:
    """把确认删除的短枝像素写入 removed_mask。"""

    for r, c in path_rc[:-1]:
        removed_mask[int(r), int(c)] = 255


def find_short_side_branches_once(
    skeleton01: np.ndarray,
    neighbor_masks: np.ndarray,
    endpoints_rc: list[tuple[int, int]],
    short_side_branch_px: int,
    resolution_m_per_px: float,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """执行一轮短枝搜索。"""

    # 每一轮只记录本轮删除结果，不直接改传入 skeleton，真正写回由外层统一处理。
    removed_mask = np.zeros_like(skeleton01, dtype=np.uint8)
    side_branch_items: list[dict[str, Any]] = []
    reason_priority = {"junction": 3, "endpoint": 2, "max_len": 1, "isolated": 0}
    for start_rc in endpoints_rc:
        # 端点可能有多个合法 trace 起步方向，这里把每个起步都追一遍再选最优。
        trace_starts = endpoint_trace_starts(start_rc, neighbor_masks)
        if not trace_starts:
            # 没有起步方向通常表示这个端点在当前邻域表里已经退化成不可追踪孤点。
            continue

        # 优先保留更长路径，其次按结束原因稳定打破并列。
        # 这里的“最优”只服务判定，不代表一定会删除。
        traced = select_best_endpoint_trace(
            start_rc=start_rc,
            trace_starts=trace_starts,
            neighbor_masks=neighbor_masks,
            short_side_branch_px=short_side_branch_px,
            reason_priority=reason_priority,
        )
        # traced 只是“当前端点最值得参考的一条 trace”，还未决定是否删除。
        # 这种先挑代表路径再判定的方式，可以避免同一端点重复删同一簇像素。
        # 也让每个端点在单轮里只产出一条候选记录，调试输出更稳定。
        # 外层最终会把这些候选按端点顺序收进本轮 pruning debug。
        end_reason = str(traced["end_reason"])
        length_px = int(traced["path_length_px"])
        # 只有真的在短阈值内结束于 junction/endpoint 的路径才视为短侧枝。
        if end_reason in {"junction", "endpoint"} and length_px <= short_side_branch_px:
            record_short_side_branch(
                side_branch_items=side_branch_items,
                traced=traced,
                resolution_m_per_px=resolution_m_per_px,
            )
            # 末端停止点保留不删，避免把主干交点或真正端点一起抹掉。
            mark_branch_pixels_for_removal(removed_mask, traced["path_rc"])
        # 其余 trace 只参与判断，不会进入 side_branch_items。
        # 因此 removed_mask 永远只记录“确认要删”的像素。
        # 一轮结束后，外层会把这些删除建议统一写回骨架。
        # 这保证单轮 helper 的职责始终停留在“发现短枝”而不是“修改骨架”。
        # 也避免单轮内部提前改骨架导致同轮其它端点判断漂移。
    return removed_mask, side_branch_items


def trace_from_node(
    start_rc: tuple[int, int],
    next_rc: tuple[int, int],
    neighbor_masks: np.ndarray,
    max_trace_px: int,
) -> dict[str, Any]:
    """从端点沿骨架追踪一条分支。"""

    # 路径从“端点 + 第一个候选邻居”起步，后续只允许单路前进。
    path_rc = [start_rc, next_rc]
    prev = start_rc
    current = next_rc
    steps = 1
    end_reason = "isolated"
    while steps < max_trace_px:
        r, c = current
        mask = int(neighbor_masks[r, c])
        neighbors = []
        # 这里只看 bitmask 记录的骨架邻居，不重新扫整幅骨架图。
        # 这样单条 trace 的复杂度基本只与路径长度成正比。
        for idx in range(len(RING_OFFSETS)):
            if not (mask & (1 << idx)):
                continue
            nr = r + RING_OFFSETS[idx][0]
            nc = c + RING_OFFSETS[idx][1]
            # 回退到上一像素不算新的前进分支。
            if (nr, nc) == prev:
                continue
            neighbors.append((nr, nc))
        if not neighbors:
            end_reason = "isolated"
            break
        if len(neighbors) > 1:
            # 当前像素出现多路分叉，说明已经撞到 junction。
            end_reason = "junction"
            break
        nxt = neighbors[0]
        # 单路前进时，把下一点并入路径，然后继续向前追。
        path_rc.append(nxt)
        steps += 1
        prev = current
        current = nxt
        degree = int(POPCOUNT_LUT[int(neighbor_masks[current])])
        # 度数变化是判断是否进入 junction/endpoint 的另一条稳定信号。
        # 这样即便局部拓扑非常短，也能在第一时间稳定终止。
        # 这里读取的是预计算度数，而不是重新扫描 8 邻域。
        # 因而 trace 的热点开销主要落在路径步进本身，而不是邻域统计。
        if degree >= 3:
            end_reason = "junction"
            break
        if degree <= 1:
            end_reason = "endpoint"
            break
    else:
        # 超过追踪上限时直接以 max_len 结束，交给外层判断是否删除。
        end_reason = "max_len"

    # 返回轻量 trace 摘要，外层据此决定是否把这条路径记为短枝。
    # path_length_px 采用边数语义，因此等于路径点数减一。
    # end_point_rc 永远等于路径尾点，便于调试层直接标注停止位置。
    # trace helper 本身不写任何删除状态，只描述路径事实。
    # 这也让它可以被不同修剪策略复用，而不耦合某个删除规则。
    # 返回结构里的字段名也尽量贴近 pruning debug，减少后续再映射。
    return {
        "path_rc": path_rc,
        "end_reason": end_reason,
        "end_point_rc": path_rc[-1],
        "path_length_px": max(0, len(path_rc) - 1),
    }


def update_neighbor_masks_local(
    binary01: np.ndarray,
    neighbor_masks: np.ndarray,
    changed_mask01: np.ndarray,
) -> np.ndarray:
    """局部更新邻域掩膜。"""

    # 当前轮没有删除像素时，不需要刷新任何邻域状态。
    if int(np.count_nonzero(changed_mask01)) == 0:
        return np.zeros_like(changed_mask01, dtype=np.uint8)

    # 删除像素周围 1-ring 范围内的邻域 bitmask 都可能受影响，因此先做一次膨胀。
    kernel = np.ones((3, 3), dtype=np.uint8)
    affected = cv2.dilate(np.where(changed_mask01 > 0, 255, 0).astype(np.uint8), kernel, iterations=1)
    for r, c in np.argwhere(affected > 0):
        # 受影响位置逐点重算 bitmask，比整图重算更省成本。
        neighbor_masks[int(r), int(c)] = neighbor_mask_at(binary01, (int(r), int(c)))
    # 返回值只标记“哪些位置需要重新看端点状态”。
    return np.where(affected > 0, 1, 0).astype(np.uint8)
