"""有效节点/边 compact 与闭环校验。"""

from __future__ import annotations

from typing import Any, TypeVar

from ..contracts import EdgeInfo, NodeInfo
from ..contracts.node_degree import traversal_degree_for_node


T = TypeVar("T")


def collect_active_objects(
    object_map: dict[int, T],
    runtime_map: dict[int, dict[str, Any]],
) -> dict[int, T]:
    """按运行时 active 标记筛出正式对象。"""

    # junction_rebuild 内部允许 inactive 对象继续存在，便于保留 lineage 和调试信息。
    # compact 阶段才真正决定哪些对象进入正式输出。
    # 这个 helper 因而只尊重 runtime 状态，不额外引入结构判断。
    return {
        int(object_id): item
        for object_id, item in object_map.items()
        if bool(runtime_map.get(object_id, {}).get("active", False))
    }


def filter_edges_with_live_endpoints(
    active_nodes: dict[int, NodeInfo],
    active_edges: dict[int, EdgeInfo],
) -> dict[int, EdgeInfo]:
    """剔除端点已经失效的边。"""

    filtered_edges: dict[int, EdgeInfo] = {}
    for edge_id, edge in active_edges.items():
        # 正式图里不允许边引用已经被合并/删除的节点。
        if int(edge.src_node_id) not in active_nodes or int(edge.dst_node_id) not in active_nodes:
            # 这类边虽然 runtime 上仍可能是 active，但从正式对象视角已经失去闭环资格。
            continue
        filtered_edges[int(edge_id)] = edge
    # 过滤后的边集才是 incident 刷新的唯一可信来源。
    # 因而它也是后续正式 edge 输出列表的直接基础。
    # 被过滤掉的边不会继续参与任何正式闭环校验。
    return filtered_edges


def collect_active_node_and_edge_objects(
    node_map: dict[int, NodeInfo],
    edge_map: dict[int, EdgeInfo],
    node_runtime: dict[int, dict[str, Any]],
    edge_runtime: dict[int, dict[str, Any]],
) -> tuple[dict[int, NodeInfo], dict[int, EdgeInfo]]:
    """基于 runtime active 标记筛出当前有效节点和边。"""

    active_nodes = collect_active_objects(node_map, node_runtime)
    active_edges = collect_active_objects(edge_map, edge_runtime)
    return active_nodes, active_edges


def build_incident_map(
    active_nodes: dict[int, NodeInfo],
    filtered_edges: dict[int, EdgeInfo],
) -> dict[int, list[int]]:
    """按当前有效边重建节点 incident 集。"""

    incident_map: dict[int, list[int]] = {int(node_id): [] for node_id in active_nodes}
    for edge_id, edge in filtered_edges.items():
        # incident 只由当前保留下来的正式边决定。
        incident_map[int(edge.src_node_id)].append(int(edge_id))
        if int(edge.dst_node_id) != int(edge.src_node_id):
            incident_map[int(edge.dst_node_id)].append(int(edge_id))
    # incident map 在这里保持无向语义；
    # self-loop 仍只保留一份 edge id，双端 port 由 topology 层再展开。
    # 这样节点 degree 就可以直接由 incident 数量推导出来。
    return incident_map


def sync_node_incidents(
    active_nodes: dict[int, NodeInfo],
    incident_map: dict[int, list[int]],
    filtered_edges: dict[int, EdgeInfo],
) -> list[int]:
    """把 incident 结果写回节点，并识别要删除的孤立断头路。"""

    dropped_dead_end_node_ids: list[int] = []
    for node_id, node in active_nodes.items():
        # 节点对象本身是正式输出载体，因此 incident 与 traversal degree 都要原地刷新。
        incident_edge_ids = tuple(sorted(set(incident_map.get(int(node_id), []))))
        node.incident_edge_ids = incident_edge_ids
        node.degree = traversal_degree_for_node(node, filtered_edges)
        # 没有任何 incident 边的断头路节点，不属于正式图结构。
        # 这类点只是在初始 endpoint 提取时被观测到，但并未进入最终边集合。
        if node.node_type == "dead_end" and node.degree == 0:
            dropped_dead_end_node_ids.append(int(node_id))
    # 返回待删除列表，由主流程统一执行删除，避免 helper 里隐式改字典。
    return dropped_dead_end_node_ids


def refresh_active_node_incidents(
    active_nodes: dict[int, NodeInfo],
    filtered_edges: dict[int, EdgeInfo],
) -> list[int]:
    """按当前有效边刷新节点 incident，并返回待删除孤立断头路。"""

    incident_map = build_incident_map(active_nodes, filtered_edges)
    return sync_node_incidents(active_nodes, incident_map, filtered_edges)


def drop_inactive_dead_end_nodes(
    active_nodes: dict[int, NodeInfo],
    dropped_dead_end_node_ids: list[int],
) -> None:
    """删除在正式图中没有任何 incident 边的断头路节点。"""

    for node_id in dropped_dead_end_node_ids:
        # 这里只删已经确认“正式图里完全孤立”的 dead_end，不动其它类型节点。
        active_nodes.pop(int(node_id), None)




def assign_edge_types(
    active_nodes: dict[int, NodeInfo],
    filtered_edges: dict[int, EdgeInfo],
) -> None:
    """按当前正式端点语义给边写回最小 `edge_type`。"""

    for edge in filtered_edges.values():
        src_node = active_nodes[int(edge.src_node_id)]
        dst_node = active_nodes[int(edge.dst_node_id)]
        # 回环边优先级最高；一旦两端是同一节点，就不再按 dead_end 规则继续细分。
        if int(edge.src_node_id) == int(edge.dst_node_id):
            edge.edge_type = "cycle"
            continue
        src_is_dead_end = str(src_node.node_type) == "dead_end"
        dst_is_dead_end = str(dst_node.node_type) == "dead_end"
        if src_is_dead_end and dst_is_dead_end:
            edge.edge_type = "dead_end_both_sides"
        elif src_is_dead_end or dst_is_dead_end:
            edge.edge_type = "dead_end_one_side"
        else:
            # 两端都不是 dead_end 时，最小语义就是“连接两端都成立”。
            edge.edge_type = "connected_both_ends"


def finalize_compact_objects(
    active_nodes: dict[int, NodeInfo],
    filtered_edges: dict[int, EdgeInfo],
) -> tuple[tuple[NodeInfo, ...], tuple[EdgeInfo, ...]]:
    """按稳定 id 顺序装箱正式 node/edge 输出。"""

    node_info_list = tuple(active_nodes[node_id] for node_id in sorted(active_nodes))
    edge_info_list = tuple(filtered_edges[edge_id] for edge_id in sorted(filtered_edges))
    return node_info_list, edge_info_list


def build_compact_summary(
    node_info_list: tuple[NodeInfo, ...],
    edge_info_list: tuple[EdgeInfo, ...],
    node_runtime: dict[int, dict[str, Any]],
    edge_runtime: dict[int, dict[str, Any]],
    dropped_dead_end_node_ids: list[int],
) -> dict[str, Any]:
    """构造 compact 阶段正式摘要。"""

    return {
        "active_node_count": len(node_info_list),
        "active_edge_count": len(edge_info_list),
        "dropped_dead_end_node_ids": dropped_dead_end_node_ids,
        "inactive_node_count": int(sum(1 for item in node_runtime.values() if not bool(item.get("active", False)))),
        "inactive_edge_count": int(sum(1 for item in edge_runtime.values() if not bool(item.get("active", False)))),
    }


def validate_unique_ids(node_info_list: tuple[NodeInfo, ...], edge_info_list: tuple[EdgeInfo, ...]) -> set[int]:
    """校验正式输出里的 node_id / edge_id 唯一性。"""

    node_ids = [int(node.node_id) for node in node_info_list]
    edge_ids = [int(edge.edge_id) for edge in edge_info_list]
    # 节点和边都必须在各自命名空间内唯一。
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("node_id must be unique in junction rebuild output")
    # 边 id 冲突会直接破坏 incident 与 debug 字段的可追踪性。
    if len(edge_ids) != len(set(edge_ids)):
        raise ValueError("edge_id must be unique in junction rebuild output")
    # 返回节点 id 集供后续边闭环校验直接复用。
    return set(node_ids)


def validate_edges_and_collect_incidents(
    edge_info_list: tuple[EdgeInfo, ...],
    node_id_set: set[int],
) -> dict[int, list[int]]:
    """校验边端点闭环，并同步构造 incident map。"""

    incident_map: dict[int, list[int]] = {node_id: [] for node_id in node_id_set}
    for edge in edge_info_list:
        # 正式边必须完整引用正式节点。
        if int(edge.src_node_id) not in node_id_set or int(edge.dst_node_id) not in node_id_set:
            raise ValueError("edge endpoint must refer to active node")
        # 完整路径为空意味着边几何尚未落地，这不允许进入正式输出。
        if not edge.path_rc:
            raise ValueError("edge.path_rc must not be empty")
        incident_map[int(edge.src_node_id)].append(int(edge.edge_id))
        if int(edge.dst_node_id) != int(edge.src_node_id):
            incident_map[int(edge.dst_node_id)].append(int(edge.edge_id))
    # incident_map 后续用于核对节点侧登记是否与边表一致。
    # 因而它在这里既是校验副产物，也是下一步节点对账真值。
    # 这样节点校验阶段就不必再次扫描整张边表。
    return incident_map


def validate_nodes_against_incidents(
    node_info_list: tuple[NodeInfo, ...],
    edge_info_list: tuple[EdgeInfo, ...],
    incident_map: dict[int, list[int]],
) -> None:
    """校验节点侧 incident / degree / polygon 字段自洽。"""

    # 这里逐节点对账，确保节点表没有脱离边表各自演化。
    for node in node_info_list:
        expected_incident = tuple(sorted(incident_map[int(node.node_id)]))
        # 节点记录的 incident 必须与边表反推结果完全一致。
        if tuple(node.incident_edge_ids) != expected_incident:
            raise ValueError("node incident_edge_ids does not match edge table")
        # `degree` 采用 traversal 端口数语义；普通节点通常等于 incident 数，self-loop 节点允许更大。
        expected_degree = traversal_degree_for_node(node, {int(edge.edge_id): edge for edge in edge_info_list})
        if int(node.degree) != int(expected_degree):
            raise ValueError("node degree does not match traversal endpoint semantics")
        # junction 节点若缺 polygon，后续 edge split 就无法可靠求交。
        if node.node_type == "junction" and not node.polygon_vertices_rc:
            raise ValueError("junction node must carry polygon_vertices_rc")
    # 全部通过后，说明节点表和边表已经形成完整闭环。
    # 这里不返回额外结果，因为校验的唯一职责就是在异常时中断。
    # 调用方只需要知道“是否抛错”，不需要额外的逐节点确认表。


def compact_active_objects(
    node_map: dict[int, NodeInfo],
    edge_map: dict[int, EdgeInfo],
    node_runtime: dict[int, dict[str, Any]],
    edge_runtime: dict[int, dict[str, Any]],
) -> tuple[tuple[NodeInfo, ...], tuple[EdgeInfo, ...], dict[str, Any]]:
    """把 junction_rebuild 内部对象收成正式输出。

    真实职责：
        junction_rebuild 内部允许存在 inactive 节点/边，便于保留合并 lineage。
        但对外正式输出前，必须只保留仍然有效的对象，并刷新 incident 关系。

    Args:
        node_map:
            节点对象表。
        edge_map:
            边对象表。
        node_runtime:
            节点运行时状态。
        edge_runtime:
            边运行时状态。

    Returns:
        tuple[tuple[NodeInfo, ...], tuple[EdgeInfo, ...], dict[str, Any]]:
            有效节点、有效边以及 compact 摘要。
    """

    # 第一步只按照 runtime 的 active 标记筛对象，不掺杂其它结构规则。
    active_nodes, active_edges = collect_active_node_and_edge_objects(
        node_map=node_map,
        edge_map=edge_map,
        node_runtime=node_runtime,
        edge_runtime=edge_runtime,
    )

    # 第二步再剔除“边仍 active，但端点节点已失效”的脏数据。
    filtered_edges = filter_edges_with_live_endpoints(active_nodes, active_edges)

    # 第三步把当前有效边重新投影回节点 incident 集，并识别孤立断头路。
    # 这一步还不删除节点，只先得到候选删除列表。
    dropped_dead_end_node_ids = refresh_active_node_incidents(active_nodes, filtered_edges)
    drop_inactive_dead_end_nodes(active_nodes, dropped_dead_end_node_ids)

    # 剔除孤立断头路后要再刷一次 incident，保证正式输出完全自洽。
    # 否则节点侧 degree / incident 会保留删除前的旧值。
    refresh_active_node_incidents(active_nodes, filtered_edges)

    # edge_type 在 compact 末尾统一写回，避免上游初始建边阶段过早绑定端点语义。
    assign_edge_types(active_nodes, filtered_edges)

    # 最终输出顺序统一按 id 排序，避免测试基线受字典遍历顺序影响。
    # 这也让 compact 后的 node/edge 列表在过程记录里更容易比对。
    # 稳定排序同样有助于后续 JSON 基线差分更干净。
    node_info_list, edge_info_list = finalize_compact_objects(active_nodes, filtered_edges)
    summary = build_compact_summary(
        node_info_list=node_info_list,
        edge_info_list=edge_info_list,
        node_runtime=node_runtime,
        edge_runtime=edge_runtime,
        dropped_dead_end_node_ids=dropped_dead_end_node_ids,
    )
    return node_info_list, edge_info_list, summary


def validate_junction_rebuild_result(
    node_info_list: tuple[NodeInfo, ...],
    edge_info_list: tuple[EdgeInfo, ...],
) -> dict[str, Any]:
    """校验 junction_rebuild 输出的 node/edge 闭环。"""

    # 唯一性是所有后续闭环检查的前提。
    node_id_set = validate_unique_ids(node_info_list, edge_info_list)
    # 边表是图连接关系的权威来源，因此先由边反推 incident。
    incident_map = validate_edges_and_collect_incidents(edge_info_list, node_id_set)
    # 再拿节点表逐条对账，确认 degree / incident / polygon 都落稳。
    validate_nodes_against_incidents(node_info_list, edge_info_list, incident_map)
    # 走到这里说明 junction_rebuild 正式输出已经满足最基本的结构一致性约束。
    return {
        "node_count": len(node_info_list),
        "edge_count": len(edge_info_list),
    }
