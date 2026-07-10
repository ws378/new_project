"""短枝修剪中的邻域拓扑 helper。"""

from __future__ import annotations

import numpy as np

RING_OFFSETS: tuple[tuple[int, int], ...] = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
    (1, 0),
    (1, -1),
    (0, -1),
)


def build_ring_lookup_tables() -> tuple[np.ndarray, np.ndarray, list[list[int]]]:
    """构造邻域查表。"""

    # 8 邻域 bitmask 只有 256 种状态，预计算能显著减少修剪阶段重复开销。
    popcount = np.zeros(256, dtype=np.uint8)
    group_count = np.zeros(256, dtype=np.uint8)
    endpoint_start_indices: list[list[int]] = []
    for mask in range(256):
        # occupied 按环顺序保留占据方向，为后续连续段压缩提供稳定输入。
        occupied = [idx for idx in range(len(RING_OFFSETS)) if mask & (1 << idx)]
        popcount[mask] = int(mask.bit_count())
        groups = ring_groups_for_mask(occupied)
        group_count[mask] = len(groups)
        # 单连续段时记录其首个可追踪方向，供端点 trace 快速起步。
        endpoint_start_indices.append(groups[0][:2] if len(groups) == 1 and groups else [])
    # 三张表共同覆盖度数、连续段数和端点 trace 起步信息。
    return popcount, group_count, endpoint_start_indices


def ring_groups_for_mask(occupied: list[int]) -> list[list[int]]:
    """把 8 邻域占据方向压成环状连续段。"""

    # 空邻域没有任何连续段，直接返回。
    if not occupied:
        return []
    groups: list[list[int]] = []
    current = [occupied[0]]
    prev_idx = occupied[0]
    for idx in occupied[1:]:
        # 相邻方向继续归到同一段，否则切到下一段。
        if idx == prev_idx + 1:
            current.append(idx)
        else:
            groups.append(current)
            current = [idx]
        prev_idx = idx
    groups.append(current)

    # 首尾相连时要把跨边界段重新拼回一个环段。
    if len(groups) > 1 and occupied[0] == 0 and occupied[-1] == len(RING_OFFSETS) - 1:
        groups = [groups[-1] + groups[0]] + groups[1:-1]
    # 这是把环首尾的连续占据重新并回一段，否则 0 度附近的连续结构会被误拆成两组。
    # 返回的 groups 顺序仍然遵循环顺序，可被后续查表稳定消费。
    # 因而调用方既能看段数，也能稳定取第一段起始方向。
    # 这也是端点判定能在查表阶段直接完成的基础。
    return groups


POPCOUNT_LUT, GROUP_COUNT_LUT, ENDPOINT_START_INDEX_LUT = build_ring_lookup_tables()


def build_neighbor_mask_map(binary01: np.ndarray) -> np.ndarray:
    """为每个骨架像素建立 8 邻域 bitmask。"""

    # 先统一成 0/1 图，避免位运算时混入 255 数值。
    src = np.where(binary01 > 0, 1, 0).astype(np.uint8)
    height, width = src.shape
    masks = np.zeros((height, width), dtype=np.uint8)
    for idx, (dr, dc) in enumerate(RING_OFFSETS):
        # 通过切片对齐把每个邻居方向批量写进对应 bit 位。
        dst_r0 = max(0, -dr)
        dst_r1 = min(height, height - dr)
        dst_c0 = max(0, -dc)
        dst_c1 = min(width, width - dc)
        src_r0 = dst_r0 + dr
        src_r1 = dst_r1 + dr
        src_c0 = dst_c0 + dc
        src_c1 = dst_c1 + dc
        masks[dst_r0:dst_r1, dst_c0:dst_c1] |= (src[src_r0:src_r1, src_c0:src_c1] << idx)
    # 结果矩阵与原骨架同尺寸，每个像素各自保存 8 邻域占据 bitmask。
    # 后续端点判断和 trace 都直接复用这张表，而不是重复扫邻域。
    # 这张表也是 pruning 性能优化最核心的一层缓存。
    return masks


def endpoint_mask_from_neighbor_masks(binary01: np.ndarray, neighbor_masks: np.ndarray) -> np.ndarray:
    """从邻域掩膜中提取端点掩膜。"""

    # 端点定义固定为“骨架像素且邻域连续段数为 1”。
    return np.where((binary01 > 0) & (GROUP_COUNT_LUT[neighbor_masks] == 1), 1, 0).astype(np.uint8)


def endpoint_trace_starts(
    rc: tuple[int, int],
    neighbor_masks: np.ndarray,
) -> list[tuple[int, int]]:
    """给端点找可追踪起始方向。"""

    # 起始方向直接查表，避免每次从 bitmask 现算邻域结构。
    r, c = rc
    mask = int(neighbor_masks[r, c])
    # 返回的坐标是端点周围第一跳候选像素，而不是完整路径。
    # 若查表结果为空，调用方会把该端点视为不可追踪。
    return [(r + RING_OFFSETS[idx][0], c + RING_OFFSETS[idx][1]) for idx in ENDPOINT_START_INDEX_LUT[mask]]


def neighbor_mask_at(binary01: np.ndarray, rc: tuple[int, int]) -> np.uint8:
    """计算单个像素的 8 邻域 bitmask。"""

    # 这个 helper 用于局部更新场景，因此按单点显式扫描更直接。
    r, c = rc
    mask = 0
    for idx, (dr, dc) in enumerate(RING_OFFSETS):
        nr = r + dr
        nc = c + dc
        # 越界邻居直接跳过，只累计图内实际存在的骨架像素。
        if nr < 0 or nr >= binary01.shape[0] or nc < 0 or nc >= binary01.shape[1]:
            continue
        if binary01[nr, nc] > 0:
            mask |= 1 << idx
    # 单点重算出的 bitmask 会直接写回局部更新后的邻域表。
    # 返回 `uint8` 也与全图邻域表 dtype 保持一致。
    return np.uint8(mask)


__all__ = [
    "ENDPOINT_START_INDEX_LUT",
    "GROUP_COUNT_LUT",
    "POPCOUNT_LUT",
    "RING_OFFSETS",
    "build_neighbor_mask_map",
    "endpoint_mask_from_neighbor_masks",
    "endpoint_trace_starts",
    "neighbor_mask_at",
]
