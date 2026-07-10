"""Coverage lane territory / effective-region 相关 helper。"""

from __future__ import annotations

from collections import deque

import cv2
import numpy as np

from ...contracts import GraphInfo, NodeInfo
from .lane_common import EIGHT_NEIGHBORS, to_path_tuple


def fill_polygon_points_into_mask(mask: np.ndarray, polygon: tuple[tuple[float, float], ...]) -> None:
    """把一个 `(row, col)` polygon 填充到现有 mask。"""

    polygon_pts = np.array([[int(round(point_rc[1])), int(round(point_rc[0]))] for point_rc in polygon], dtype=np.int32)
    cv2.fillPoly(mask, [polygon_pts], 255)


def build_allowed_domain_mask(
    shape: tuple[int, int],
    territory_pixels: tuple[tuple[int, int], ...],
    src_node: NodeInfo,
    dst_node: NodeInfo,
) -> np.ndarray:
    """构造单条 coverage lane 的横向区间允许域。"""

    mask = np.zeros(shape, dtype=np.uint8)
    for row, col in territory_pixels:
        if 0 <= row < shape[0] and 0 <= col < shape[1]:
            # territory 像素定义了这条 coverage lane 在全局图上的主要归属区域。
            mask[int(row), int(col)] = 255
    for node in (src_node, dst_node):
        polygon = tuple(node.polygon_vertices_rc or ())
        if len(polygon) >= 3:
            # 两端节点 polygon 要并入允许域，
            # 否则靠近节点腹地的 sweep 中心会被错误裁掉。
            fill_polygon_points_into_mask(mask, polygon)
    return mask


def derive_outer_path_territory_pixels(
    graph_info: GraphInfo,
    constrained_free_mask: np.ndarray,
) -> dict[int, tuple[tuple[int, int], ...]]:
    """为每条 `outer_path_rc` 生成全局 territory 归属区域。"""

    owner_map = derive_outer_path_owner_map(
        graph_info=graph_info,
        constrained_free_mask=constrained_free_mask,
    )
    territory_pixels_by_edge_id: dict[int, list[tuple[int, int]]] = {int(edge.edge_id): [] for edge in graph_info.edges}
    rows, cols = np.where(owner_map >= 0)
    for row, col in zip(rows.tolist(), cols.tolist()):
        territory_pixels_by_edge_id[int(owner_map[row, col])].append((int(row), int(col)))
    return {int(edge_id): tuple(points) for edge_id, points in territory_pixels_by_edge_id.items()}


def derive_outer_path_owner_map(
    graph_info: GraphInfo,
    constrained_free_mask: np.ndarray,
) -> np.ndarray:
    """为每个自由像素生成所属 edge id，避免实时辅助链路重复物化点列表。"""

    owner_map = np.full(constrained_free_mask.shape, -1, dtype=np.int32)
    height, width = constrained_free_mask.shape
    component_count, component_labels = cv2.connectedComponents(
        np.where(constrained_free_mask > 0, 255, 0).astype(np.uint8),
        connectivity=8,
    )
    seed_items: list[tuple[int, int, int, int]] = []
    edge_ids_by_component: dict[int, set[int]] = {}
    for edge in graph_info.edges:
        edge_id = int(edge.edge_id)
        for row, col in find_seed_points_in_mask(to_path_tuple(edge.outer_path_rc), constrained_free_mask):
            component_id = int(component_labels[row, col])
            if component_id <= 0:
                continue
            seed_items.append((int(row), int(col), edge_id, component_id))
            edge_ids_by_component.setdefault(component_id, set()).add(edge_id)

    multi_seed_components: set[int] = set()
    for component_id in range(1, int(component_count)):
        edge_ids = edge_ids_by_component.get(component_id, set())
        if not edge_ids:
            continue
        if len(edge_ids) == 1:
            # 单 edge seed 连通分量没有竞争者，旧多源 BFS 最终也会把整个分量归给该 edge。
            owner_map[component_labels == component_id] = int(next(iter(edge_ids)))
            continue
        multi_seed_components.add(component_id)
    if not multi_seed_components:
        return owner_map

    max_queue_size = int(constrained_free_mask.size)
    queue_indices = np.empty(max_queue_size, dtype=np.int32)
    queue_read = 0
    queue_write = 0
    owner_flat = owner_map.ravel()
    free_flat = constrained_free_mask.ravel()

    for row, col, edge_id, component_id in seed_items:
        if component_id not in multi_seed_components:
            continue
        if owner_map[row, col] >= 0:
            # 同一个 seed 像素一旦已经被更早 edge 占用，
            # 就不再让后来的 edge 覆写它，避免 territory 初始归属出现非确定性抖动。
            continue
        owner_map[row, col] = edge_id
        queue_indices[queue_write] = int(row * width + col)
        queue_write += 1

    while queue_read < queue_write:
        index = int(queue_indices[queue_read])
        queue_read += 1
        row = index // width
        col = index - row * width
        owner_edge_id = int(owner_flat[index])
        if row > 0 and col > 0:
            next_index = index - width - 1
            if free_flat[next_index] > 0 and owner_flat[next_index] < 0:
                owner_flat[next_index] = owner_edge_id
                queue_indices[queue_write] = next_index
                queue_write += 1
        if row > 0:
            next_index = index - width
            if free_flat[next_index] > 0 and owner_flat[next_index] < 0:
                owner_flat[next_index] = owner_edge_id
                queue_indices[queue_write] = next_index
                queue_write += 1
        if row > 0 and col + 1 < width:
            next_index = index - width + 1
            if free_flat[next_index] > 0 and owner_flat[next_index] < 0:
                owner_flat[next_index] = owner_edge_id
                queue_indices[queue_write] = next_index
                queue_write += 1
        if col > 0:
            next_index = index - 1
            if free_flat[next_index] > 0 and owner_flat[next_index] < 0:
                owner_flat[next_index] = owner_edge_id
                queue_indices[queue_write] = next_index
                queue_write += 1
        if col + 1 < width:
            next_index = index + 1
            if free_flat[next_index] > 0 and owner_flat[next_index] < 0:
                owner_flat[next_index] = owner_edge_id
                queue_indices[queue_write] = next_index
                queue_write += 1
        if row + 1 < height and col > 0:
            next_index = index + width - 1
            if free_flat[next_index] > 0 and owner_flat[next_index] < 0:
                owner_flat[next_index] = owner_edge_id
                queue_indices[queue_write] = next_index
                queue_write += 1
        if row + 1 < height:
            next_index = index + width
            if free_flat[next_index] > 0 and owner_flat[next_index] < 0:
                owner_flat[next_index] = owner_edge_id
                queue_indices[queue_write] = next_index
                queue_write += 1
        if row + 1 < height and col + 1 < width:
            next_index = index + width + 1
            if free_flat[next_index] > 0 and owner_flat[next_index] < 0:
                owner_flat[next_index] = owner_edge_id
                queue_indices[queue_write] = next_index
                queue_write += 1
    return owner_map


def derive_effective_region_mask(
    outer_path: tuple[tuple[float, float], ...],
    lane_free_mask: np.ndarray,
) -> np.ndarray:
    """从 outer_path 种子在约束自由区内提取局部有效区域。"""

    seed_points = find_seed_points_in_mask(outer_path, lane_free_mask)
    if not seed_points:
        # outer_path 连一个合法 seed 都找不到时，说明这条 lane 在当前自由区内没有可恢复的局部有效域。
        return np.zeros_like(lane_free_mask, dtype=np.uint8)
    visited = np.zeros_like(lane_free_mask, dtype=np.uint8)
    queue: deque[tuple[int, int]] = deque(seed_points)
    for row, col in seed_points:
        visited[row, col] = 1
    height, width = lane_free_mask.shape
    while queue:
        row, col = queue.popleft()
        for d_row, d_col in EIGHT_NEIGHBORS:
            next_row = row + d_row
            next_col = col + d_col
            if next_row < 0 or next_row >= height or next_col < 0 or next_col >= width:
                continue
            if visited[next_row, next_col] > 0 or lane_free_mask[next_row, next_col] == 0:
                # 已访问像素不用重复入队；非 lane_free 区域也不能被当前 outer_path 有效域继续吞并。
                continue
            visited[next_row, next_col] = 1
            queue.append((next_row, next_col))
    return np.where(visited > 0, 255, 0).astype(np.uint8)


def build_node_polygon_mask(shape: tuple[int, int], nodes: tuple[NodeInfo, ...] | list[NodeInfo]) -> np.ndarray:
    """把所有节点 polygon 填成掩膜。"""

    mask = np.zeros(shape, dtype=np.uint8)
    for node in nodes:
        polygon = tuple(node.polygon_vertices_rc or ())
        if len(polygon) >= 3:
            # 少于 3 个点的 polygon 不能形成有效面域，因此不参与 mask 填充。
            fill_polygon_points_into_mask(mask, polygon)
    return mask


def build_endpoint_polygon_block_mask(shape: tuple[int, int], src_node: NodeInfo, dst_node: NodeInfo) -> np.ndarray:
    """只构造当前 edge 两端节点 polygon 的阻塞掩膜。"""

    mask = np.zeros(shape, dtype=np.uint8)
    for node in (src_node, dst_node):
        polygon = tuple(node.polygon_vertices_rc or ())
        if len(polygon) >= 3:
            fill_polygon_points_into_mask(mask, polygon)
    return mask


def find_seed_points_in_mask(path_rc: tuple[tuple[float, float], ...], mask: np.ndarray) -> list[tuple[int, int]]:
    """在约束 mask 中为 outer_path 找可用种子。"""

    seed_points: list[tuple[int, int]] = []
    for row_f, col_f in path_rc:
        row = int(round(float(row_f)))
        col = int(round(float(col_f)))
        if row < 0 or row >= mask.shape[0] or col < 0 or col >= mask.shape[1]:
            # path 点落到图像外时，不能拿来做有效 seed，直接跳过。
            continue
        if mask[row, col] > 0:
            # path 本体若已经落在可用 mask 内，就直接把它当作正式 seed。
            seed_points.append((row, col))
            continue
        for d_row, d_col in EIGHT_NEIGHBORS:
            next_row = row + d_row
            next_col = col + d_col
            if 0 <= next_row < mask.shape[0] and 0 <= next_col < mask.shape[1] and mask[next_row, next_col] > 0:
                # path 点若刚好压在线边界外，只允许吸附到 8 邻域内最近的可用像素，
                # 不做更远距离搜索，避免 seed 被吸进错误区域。
                seed_points.append((next_row, next_col))
                break
    return list(dict.fromkeys(seed_points))


__all__ = (
    'build_allowed_domain_mask',
    'build_endpoint_polygon_block_mask',
    'build_node_polygon_mask',
    'derive_effective_region_mask',
    'derive_outer_path_owner_map',
    'derive_outer_path_territory_pixels',
    'fill_polygon_points_into_mask',
    'find_seed_points_in_mask',
)
