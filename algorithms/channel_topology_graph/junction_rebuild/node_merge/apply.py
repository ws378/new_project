"""交汇节点合并应用与对象失效逻辑。"""

from __future__ import annotations

from typing import Any

from ...contracts import EdgeInfo, NodeInfo
from ...contracts.node_degree import traversal_degree_for_node
from .groups import pick_group_survivor, solve_group_anchor_point


def apply_node_merges(
    node_map: dict[int, NodeInfo],
    edge_map: dict[int, EdgeInfo],
    node_runtime: dict[int, dict[str, Any]],
    edge_runtime: dict[int, dict[str, Any]],
    merge_groups: list[list[int]],
    *,
    internal_inactive_reason: str = "internal_after_node_merge",
) -> dict[str, Any]:
    """执行节点合并，并同步处理边重定向与边失效。

    真实职责：
        节点合并不是只改节点位置。它一定会带来：
        1. 被吞并节点失效；
        2. 内部边失效；
        3. 外连边端点重定向到 survivor。
        这里先保留失效对象的 runtime 状态，最终 compact 时再真正从输出剔除。
    """

    merge_summary: list[dict[str, Any]] = []
    merge_target_by_node_id: dict[int, int] = {}
    for group in merge_groups:
        # 单点组不需要真正合并，直接跳过。
        if len(group) <= 1:
            continue
        # survivor 由 group 内部策略决定，anchor 则表达合并后的新位置。
        survivor_id = pick_group_survivor(group, node_map)
        survivor_point_rc = solve_group_anchor_point(group, node_map)
        # survivor 位置更新到组锚点，作为合并后的正式节点位置。
        node_map[survivor_id].point_rc = survivor_point_rc
        node_runtime[survivor_id]["merged_member_node_ids"] = tuple(sorted(group))
        # merge_target_by_node_id 会成为所有节点和边重映射的统一真值。
        # 因而只要这张表稳定，后续重定向就不会漂移。
        for node_id in group:
            merge_target_by_node_id[int(node_id)] = int(survivor_id)
            if int(node_id) == int(survivor_id):
                # survivor 自己保持 active，只更新位置与成员信息。
                continue
            # 非 survivor 节点只做失效标记，不立刻从 node_map 删除。
            node_runtime[node_id]["active"] = False
            node_runtime[node_id]["merge_target_node_id"] = int(survivor_id)
        # 每个真正执行的 merge 组都记入摘要，供后续 runtime/debug 使用。
        # 摘要里保留成员列表和锚点，便于回溯一次合并的输入输出。
        # 这里不额外记录旧位置，旧位置仍可从 node_runtime/debug 中追溯。
        # merge_summary 的粒度就是“一次 group merge”。
        merge_summary.append(
            {
                "survivor_node_id": int(survivor_id),
                "member_node_ids": [int(node_id) for node_id in sorted(group)],
                "anchor_point_rc": [float(survivor_point_rc[0]), float(survivor_point_rc[1])],
            }
        )

    for node_id in list(node_map):
        # 没参与合并的节点默认把自己映到自己。
        merge_target_by_node_id.setdefault(int(node_id), int(node_id))
        # 这样后续所有边都能统一通过 merge_target_by_node_id 做重定向。

    for edge_id, edge in edge_map.items():
        if not bool(edge_runtime.get(edge_id, {}).get("active", True)):
            # 已经失效的边不再参与本轮 merge 后重定向，避免重复覆盖失效原因。
            continue

        # 边两端先按 merge target 做节点 id 重定向。
        # 这里直接改 EdgeInfo，本轮之后 edge 端点就以 survivor 为准。
        edge_was_self_loop = int(edge.src_node_id) == int(edge.dst_node_id)
        src_after = int(merge_target_by_node_id[int(edge.src_node_id)])
        dst_after = int(merge_target_by_node_id[int(edge.dst_node_id)])
        edge.src_node_id = src_after
        edge.dst_node_id = dst_after
        # 重定向之后，边路径几何本身暂不重算，后续 edge geometry 阶段再处理。
        # 这让节点合并和边几何重建保持职责分离。

        # 若一条边因为节点合并才退化成同节点内部边，它应失效；
        # 但纯回环 self-loop 本来就是合法正式边，不能在这里误杀。
        if src_after == dst_after and not edge_was_self_loop:
            edge_runtime[edge_id]["active"] = False
            edge_runtime[edge_id]["inactive_reason"] = str(internal_inactive_reason)
            # 失效后这条边仍保留在 runtime 中，方便后续统计与调试。
            # 这样 compact 之前仍然可以追踪它为何失效。

    # 合并后还可能产生平行重复边，需再清一次。
    duplicate_edge_ids = deactivate_duplicate_edges(edge_map=edge_map, edge_runtime=edge_runtime)

    # 节点 incident 集合最后统一刷新，保证拓扑闭环。
    refresh_incident_edge_ids_after_merge(
        node_map=node_map,
        edge_map=edge_map,
        node_runtime=node_runtime,
        edge_runtime=edge_runtime,
    )

    # 汇总结果只保留运行时统计，不直接返回变更后的对象本体。
    # 调用方若需要对象本体，应直接查看传入的 map/runtime。
    # 这样 apply_node_merges 的副作用边界很清楚：原对象原地修改，返回摘要。
    # 这也方便过程记录里直接引用统计结果。
    # merge 之后的真实对象状态以 map/runtime 为准。
    # 返回摘要只是为了让上层少做一轮统计汇总。
    return {
        "merge_groups_applied": merge_summary,
        "inactive_node_count_after_merge": int(
            sum(1 for item in node_runtime.values() if not bool(item.get("active", False)))
        ),
        "inactive_edge_count_after_merge": int(
            sum(1 for item in edge_runtime.values() if not bool(item.get("active", False)))
        ),
        "duplicate_edge_ids_after_merge": duplicate_edge_ids,
    }


def deactivate_duplicate_edges(
    edge_map: dict[int, EdgeInfo],
    edge_runtime: dict[int, dict[str, Any]],
) -> list[int]:
    """清理节点合并后产生的重复边。"""

    # 键只看无向端点对，忽略边方向。
    seen_by_key: dict[tuple[int, int], int] = {}
    duplicate_edge_ids: list[int] = []
    for edge_id in sorted(edge_map):
        if not bool(edge_runtime.get(edge_id, {}).get("active", False)):
            continue
        edge = edge_map[edge_id]
        key = tuple(sorted((int(edge.src_node_id), int(edge.dst_node_id))))
        if key not in seen_by_key:
            seen_by_key[key] = int(edge_id)
            # 第一条出现的边保留，后续同键边视为重复。
            continue
        # 后遇到的同端点对边失效，保留先出现的那条。
        edge_runtime[edge_id]["active"] = False
        edge_runtime[edge_id]["inactive_reason"] = "duplicate_after_node_merge"
        duplicate_edge_ids.append(int(edge_id))
    # duplicate_edge_ids 可直接写入 merge 摘要或调试输出。
    # 这一步不会真的删除边对象，只做失效标记。
    # 因而 edge_id 的稳定性不会被“去重”动作破坏。
    # 保留第一条边的策略也让结果具备确定性。
    return duplicate_edge_ids


def refresh_incident_edge_ids_after_merge(
    node_map: dict[int, NodeInfo],
    edge_map: dict[int, EdgeInfo],
    node_runtime: dict[int, dict[str, Any]],
    edge_runtime: dict[int, dict[str, Any]],
) -> None:
    """在节点合并后刷新一次 incident 边集合。"""

    # 先按 active edge 重新收集每个节点的 incident 关系列表。
    # 这一轮完全丢弃旧 incident 信息，按当前 active edge 重新构建。
    incident_map: dict[int, list[int]] = {int(node_id): [] for node_id in node_map}
    for edge_id, edge in edge_map.items():
        if not bool(edge_runtime.get(edge_id, {}).get("active", False)):
            continue
        incident_map[int(edge.src_node_id)].append(int(edge_id))
        if int(edge.dst_node_id) != int(edge.src_node_id):
            # 非 self-loop 才在 dst 侧再挂一次；self-loop 的双端 traversal 语义交给 degree helper 解释。
            incident_map[int(edge.dst_node_id)].append(int(edge_id))
        # 只有 active edge 才会重新挂回节点。
        # merge 后失效或重复失效的边不会再影响 degree。

    for node_id, node in node_map.items():
        # 已失效节点 incident 直接清空，避免残留旧边关系。
        if not bool(node_runtime.get(node_id, {}).get("active", False)):
            node.incident_edge_ids = ()
            node.degree = 0
            continue
        # 仍活跃的节点按排序后的 incident 边回填。
        # `incident_edge_ids` 保留唯一边 id，`degree` 则按可连接 traversal 端口数重算。
        incident_edge_ids = tuple(sorted(set(incident_map.get(int(node_id), []))))
        node.incident_edge_ids = incident_edge_ids
        node.degree = traversal_degree_for_node(node, {int(edge.edge_id): edge for edge in edge_map.values()})
        # self-loop 节点会在这里自然得到双端口 degree，而不是被压成 1。
        # 更新后节点对象即可直接参与后续 compact 或 geometry 阶段。
        # 因而 refresh 后的 node_map 就是合并后的最新拓扑视图。
        # 上层无需再单独推导 degree。
        # incident_edge_ids 与 degree 的同步关系在这里一次性收口。


__all__ = (
    "apply_node_merges",
    "deactivate_duplicate_edges",
    "refresh_incident_edge_ids_after_merge",
)
