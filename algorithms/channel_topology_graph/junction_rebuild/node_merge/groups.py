"""交汇节点合并组推导逻辑。"""

from __future__ import annotations

from collections import deque

import numpy as np

from ...contracts import GeometryPreparationResult, NodeInfo

_RING_OFFSETS: tuple[tuple[int, int], ...] = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
    (1, 0),
    (1, -1),
    (0, -1),
)


def derive_merge_groups(
    geometry_result: GeometryPreparationResult,
    node_map: dict[int, NodeInfo],
    node_runtime: dict[int, dict[str, object]],
    config: dict[str, object] | None = None,
) -> tuple[list[list[int]], dict[str, object]]:
    """在初始节点上求交汇合并组。

    真实职责：
        这一层只决定“哪些初始交汇节点应该并成一个节点”，不直接改对象。
        合并依据沿用旧研究算法的核心语义：在骨架上 geodesic 足够近，就认为
        它们属于同一交汇结构。
    """

    if config is None:
        config = {}

    # 合并阈值使用骨架 geodesic 像素距离，而不是欧氏直线距离。
    threshold_px = int(config.get("intersection_merge_geodesic_px", 20))
    skeleton01 = np.where(geometry_result.skeleton_pruned_mask > 0, 1, 0).astype(np.uint8)

    # 只把当前仍然 active 的 junction 节点纳入合并判定。
    junction_ids = [
        int(node_id)
        for node_id, node in node_map.items()
        if node.node_type == "junction" and bool(node_runtime.get(node_id, {}).get("active", True))
    ]
    adjacency = {node_id: set() for node_id in junction_ids}
    pair_distance_px: dict[tuple[int, int], int] = {}
    # adjacency 会被后续连通分量求解直接消费。
    # pair_distance_px 只是一份解释性附加信息。
    for index, src_id in enumerate(junction_ids):
        # 以 src_id 为种子做一次限长 geodesic BFS，再查看后续 junction 是否可达。
        # 这样每对节点只会检查一次，不会重复做双向 BFS。
        src_rc = tuple(map(int, np.round(node_map[src_id].point_rc)))
        dist_map = geodesic_distances_from_seed(src_rc, skeleton01, max_distance_px=threshold_px)
        # 只有 index 之后的节点会被检查，避免重复统计 pair。
        for dst_id in junction_ids[index + 1 :]:
            dst_rc = tuple(map(int, np.round(node_map[dst_id].point_rc)))
            distance_px = dist_map.get(dst_rc)
            if distance_px is None or int(distance_px) > threshold_px:
                # geodesic 超阈值或不可达都表示这对 junction 不应在这一轮被归到同一结构里。
                continue
            # geodesic 足够近的两点在邻接图上连边，之后统一取连通分量。
            # 这比直接按欧氏邻近更符合骨架上的真实连通关系。
            adjacency[src_id].add(dst_id)
            adjacency[dst_id].add(src_id)
            pair_distance_px[(min(src_id, dst_id), max(src_id, dst_id))] = int(distance_px)
            # pair_distance_px 只记录真正入图的成对距离。

    groups = graph_components(adjacency)
    # 返回分组本身及一份轻量调试统计，便于后续写 runtime。
    # 统计里保留 pair_distance，可用于解释为什么两节点被并到一起。
    # merge_group_count 则方便评估这轮合并压缩了多少 junction。
    # 没有任何近邻边时，groups 也会自然退化为单点分量列表。
    # 这样调用方不需要对“无可合并节点”做特殊分支。
    # 调试统计与正式分组在这里一次性同步产出。
    # 最终返回的 groups 顺序也保持稳定，便于基线比对。
    return groups, {
        "merge_threshold_px": threshold_px,
        "junction_node_count_before_merge": len(junction_ids),
        "merge_group_count": len(groups),
        "pair_distance_px": {f"{key[0]}-{key[1]}": int(value) for key, value in pair_distance_px.items()},
    }


def pick_group_survivor(group: list[int], node_map: dict[int, NodeInfo]) -> int:
    """给一个合并组挑 survivor。"""

    # 当前策略保持最简单稳定：直接取最小 node_id 作为 survivor。
    return min(int(node_id) for node_id in group)


def solve_group_anchor_point(group: list[int], node_map: dict[int, NodeInfo]) -> tuple[float, float]:
    """求合并组锚点。"""

    # 合并锚点取组内节点坐标均值，作为后续 survivor 新位置。
    # 这里不做 geodesic 重心之类复杂估计，优先保证稳定与可解释。
    rows = [float(node_map[node_id].point_rc[0]) for node_id in group]
    cols = [float(node_map[node_id].point_rc[1]) for node_id in group]
    return (float(sum(rows) / len(rows)), float(sum(cols) / len(cols)))


def geodesic_distances_from_seed(
    seed_rc: tuple[int, int],
    skeleton01: np.ndarray,
    max_distance_px: int,
) -> dict[tuple[int, int], int]:
    """在骨架上从单个种子做限长 BFS。"""

    # BFS 只在 skeleton 上扩张，并且超过阈值就不再继续向外传播。
    queue: deque[tuple[int, int]] = deque([seed_rc])
    dist: dict[tuple[int, int], int] = {seed_rc: 0}
    height, width = skeleton01.shape
    while queue:
        cur = queue.popleft()
        if dist[cur] >= max_distance_px:
            # 超出阈值后不再向外扩，控制搜索范围。
            continue
        for dr, dc in _RING_OFFSETS:
            nr = cur[0] + dr
            nc = cur[1] + dc
            nxt = (nr, nc)
            # 搜索严格限制在图像范围内且只能走 skeleton 像素。
            if nr < 0 or nr >= height or nc < 0 or nc >= width:
                continue
            if skeleton01[nr, nc] == 0:
                continue
            if nxt in dist:
                continue
            dist[nxt] = dist[cur] + 1
            queue.append(nxt)
            # 首次写入 dist 的距离就是最短 geodesic 层数。
            # 后续若再次遇到该点，会被 `nxt in dist` 直接拦下。
            # 因而 dist 本身就兼任 visited 标记。
            # 这也是 BFS 在无权图上最自然的实现方式。
    # 返回的是“在阈值内可达的 geodesic 距离表”。
    # 调用方只需要关心可达 junction 及其最短距离。
    # 不可达或超阈值的点则不会出现在结果里。
    return dist


def graph_components(adjacency: dict[int, set[int]]) -> list[list[int]]:
    """求邻接表上的连通分量。"""

    # 邻接图上的每个连通分量就对应一个待合并节点组。
    visited: set[int] = set()
    components: list[list[int]] = []
    for node_id in sorted(adjacency):
        if node_id in visited:
            continue
        # 从当前未访问节点启动一次 BFS，收完整个分量。
        queue: deque[int] = deque([node_id])
        visited.add(node_id)
        component: list[int] = []
        while queue:
            cur = queue.popleft()
            component.append(cur)
            for nxt in sorted(adjacency[cur]):
                if nxt in visited:
                    continue
                visited.add(nxt)
                queue.append(nxt)
                # BFS 保证每个节点只会被并入一次当前分量。
        # 分量内部也统一排序，保证输出稳定。
        # components 本身则按最小 node_id 的自然顺序产生。
        # 后续 merge apply 就按这个稳定顺序逐组处理。
        # 这种稳定顺序也有利于基线结果保持一致。
        # 空邻接的孤立点也会自然形成单点分量。
        # 因而这个 helper 同时兼容稠密图和稀疏图场景。
        components.append(sorted(component))
    return components


__all__ = (
    "derive_merge_groups",
    "pick_group_survivor",
    "solve_group_anchor_point",
    'geodesic_distances_from_seed',
    'graph_components',
)
