"""TopologyGraphBuild 的图装配与节点局部顺时针排序。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ...contracts import EdgeInfo, GraphInfo, NodeInfo
from ...contracts.node_degree import traversal_degree_for_node
from .endpoint_geometry import build_edge_endpoint_geometry


def assemble_graph_info(
    node_info_list: tuple[NodeInfo, ...] | list[NodeInfo],
    edge_info_list: tuple[EdgeInfo, ...] | list[EdgeInfo],
) -> GraphInfo:
    """把 junction_rebuild 输出的节点和边装配成正式图对象。

    真实职责：
        topology_graph_build 第一次正式建立 `graph_info`。这里不新造核心节点或核心边，
        只把 junction_rebuild 已经 compact 完成的 `node_info / edge_info` 聚合起来。

    Args:
        node_info_list:
            junction_rebuild 输出的正式节点集合。
        edge_info_list:
            junction_rebuild 输出的正式边集合。

    Returns:
        GraphInfo:
            topology_graph_build 第一次建立的正式图对象。
    """

    # topology_graph_build 不改写 node/edge，只把 junction_rebuild 正式输出冻结成 tuple。
    nodes = tuple(node_info_list)
    edges = tuple(edge_info_list)
    # meta 只记录“这是 topology_graph_build 首次建图”这个阶段级事实。
    # 这里故意不复制 junction_rebuild debug/validation，避免 graph 对象职责膨胀。
    # 图对象从这里开始成为后续 candidate/lane/coverage 共同消费的正式入口。
    # 因此 assemble 本身必须保持极薄，不夹带新的规则推导。
    return GraphInfo(
        nodes=nodes,
        edges=edges,
        meta={
            "stage": "topology_graph_build",
            "node_count": int(len(nodes)),
            "edge_count": int(len(edges)),
        },
    )


def validate_graph_info(graph_info: GraphInfo) -> dict[str, Any]:
    """校验正式图对象的基本闭环。

    真实职责：
        topology_graph_build 后续 candidate/lane 全都建立在图闭环正确的前提上。
        如果节点 incident 边、边两端节点、边路径长度这些基础事实是脏的，
        就不能继续往下推导。

    Args:
        graph_info:
            topology_graph_build 装配后的正式图对象。

    Returns:
        dict[str, Any]:
            图闭环校验摘要。

    Raises:
        ValueError:
            当节点/边关系断裂，或边路径明显非法时抛出。
    """

    # 正式图至少要有节点和边，否则后续所有拓扑派生都失去意义。
    if not graph_info.nodes:
        raise ValueError("graph_info.nodes is empty")
    if not graph_info.edges:
        raise ValueError("graph_info.edges is empty")

    # 先冻结 id 集，后续所有关系校验都只在正式主键空间内完成。
    node_ids = {int(node.node_id) for node in graph_info.nodes}
    edge_ids = {int(edge.edge_id) for edge in graph_info.edges}
    for edge in graph_info.edges:
        # 边两端必须能回指到正式节点，否则图对象不是闭环。
        if int(edge.src_node_id) not in node_ids:
            raise ValueError(f"edge {edge.edge_id} src node missing")
        if int(edge.dst_node_id) not in node_ids:
            raise ValueError(f"edge {edge.edge_id} dst node missing")
        # junction_rebuild 已经写出完整边路径，topology_graph_build 不能继续接受空路径或单点路径。
        # 这一条也是后续端点几何恢复和 lane 方向推导的前置条件。
        if len(edge.path_rc) < 2:
            raise ValueError(f"edge {edge.edge_id} path too short")

    edge_by_id = {int(edge.edge_id): edge for edge in graph_info.edges}
    for node in graph_info.nodes:
        # `degree` 使用 traversal 端口数语义，普通节点与 incident 条数一致，self-loop 节点允许更大。
        if int(node.degree) != int(traversal_degree_for_node(node, edge_by_id)):
            raise ValueError(f"node {node.node_id} degree mismatch")
        for edge_id in node.incident_edge_ids:
            # incident edge 必须能回指到正式边对象，不能引用 runtime 中间 id。
            if int(edge_id) not in edge_ids:
                raise ValueError(f"node {node.node_id} incident edge missing: {edge_id}")

    # 校验通过后只返回最小摘要，不重复抄整张图。
    # 这份摘要会直接进入 stage validation_info，供 compare 稳定消费。
    return {
        "node_count": int(len(graph_info.nodes)),
        "edge_count": int(len(graph_info.edges)),
        "valid": True,
    }


def build_ordered_incident_edges(graph_info: GraphInfo) -> GraphInfo:
    """为每个节点整理 incident 边的顺时针顺序与局部几何。

    真实职责：
        旧研究主线里，`08_connection_candidates` 不是任意两条边瞎配对，
        而是严格依赖节点内部 incident 边的顺时针顺序。这里要先把每个节点
        看作一个局部圆盘，再把 incident edge 的接触点、朝向、相邻关系整理出来。

    Args:
        graph_info:
            topology_graph_build 刚装配好的正式图对象。

    Returns:
        GraphInfo:
            在 `meta` 中补入节点局部顺时针 incident 视图后的图对象。
    """

    # edge 端点几何会在多个节点上复用，因此先按 edge_id 预计算一份。
    edge_by_id = {int(edge.edge_id): edge for edge in graph_info.edges}
    ordered_incident_edges_by_node: dict[int, list[dict[str, Any]]] = {}
    endpoint_geometry_by_edge: dict[int, dict[str, Any]] = {}

    for edge in graph_info.edges:
        # 端点几何与节点无关，先独立算好可以避免在双端节点上重复恢复。
        endpoint_geometry_by_edge[int(edge.edge_id)] = build_edge_endpoint_geometry(edge)

    for node in graph_info.nodes:
        node_id = int(node.node_id)
        incident_edges: list[dict[str, Any]] = []
        node_point_rc = (float(node.point_rc[0]), float(node.point_rc[1]))
        # 单节点局部视图从这里开始构造，后续 candidate 层不会再回看原始 edge path。

        for edge_id in node.incident_edge_ids:
            edge = edge_by_id[int(edge_id)]
            # self-loop 必须在同一节点上同时暴露 `src/dst` 两个 incident port，
            # 否则 pure cycle cut 无法形成可区分的 through 语义。
            if int(edge.src_node_id) == node_id and int(edge.dst_node_id) == node_id:
                for role in ("src", "dst"):
                    endpoint = endpoint_geometry_by_edge[int(edge.edge_id)][role]
                    incident_edges.append(
                        {
                            "edge_id": int(edge.edge_id),
                            "role": role,
                            "end_type": role,
                            "peer_node_id": int(node_id),
                            "contact_rc": endpoint["contact_rc"],
                            "tangent_vec_rc": endpoint["tangent_vec_rc"],
                            "heading_deg_image": endpoint["heading_deg_image"],
                            "node_point_rc": [float(node_point_rc[0]), float(node_point_rc[1])],
                        }
                    )
                continue
            # 当前节点在 edge 上可能是 src 也可能是 dst，角色不同会影响切向读取。
            if int(edge.src_node_id) == node_id:
                role = "src"
                peer_node_id = int(edge.dst_node_id)
                endpoint = endpoint_geometry_by_edge[int(edge.edge_id)]["src"]
            else:
                role = "dst"
                peer_node_id = int(edge.src_node_id)
                endpoint = endpoint_geometry_by_edge[int(edge.edge_id)]["dst"]

            incident_edges.append(
                {
                    "edge_id": int(edge.edge_id),
                    "role": role,
                    "end_type": role,
                    "peer_node_id": peer_node_id,
                    "contact_rc": endpoint["contact_rc"],
                    "tangent_vec_rc": endpoint["tangent_vec_rc"],
                    "heading_deg_image": endpoint["heading_deg_image"],
                    "node_point_rc": [float(node_point_rc[0]), float(node_point_rc[1])],
                }
            )

        # 旧研究代码就是按 `heading_deg_image` 排 incident edge。
        # `None` 视为最末位，保证有明确几何方向的边优先参与顺时针序。
        # 排序后的列表就是单节点内部唯一允许被 candidate 层消费的局部顺时针视图。
        incident_edges.sort(
            key=lambda item: 9999.0 if item["heading_deg_image"] is None else float(item["heading_deg_image"])
        )
        # `None` heading 被排到最后，含义不是“这些边不重要”，而是“先让有方向证据的边稳定成环序”。
        degree = int(len(incident_edges))
        # degree 可能为 0，但此时下面两项 prev/next 都退成 None。
        for index, item in enumerate(incident_edges):
            # 这里显式写出 prev/next，后续 candidate 层就不必再重复转圈计算。
            item["cw_order_index"] = int(index)
            item["cw_prev_edge_id"] = int(incident_edges[(index - 1) % degree]["edge_id"]) if degree > 0 else None
            item["cw_next_edge_id"] = int(incident_edges[(index + 1) % degree]["edge_id"]) if degree > 0 else None

        # 节点级排序结果按 node_id 收口，保持后续查找是 O(1) 字典访问。
        # 空 incident 列表也原样保留，避免节点视图与正式图节点集合脱节。
        # 这样即便某节点没有有效边，也能在 compare 时看见其局部空视图。
        ordered_incident_edges_by_node[node_id] = incident_edges

    # 新图对象只是在 meta 中补派生视图，nodes/edges 主体保持原值不变。
    # 这样 graph_info 仍然是不可变正式对象，而不是可写 runtime 容器。
    # 后续 candidate/lane 层只会读这些派生视图，不会再写回 nodes/edges。
    return replace(
        graph_info,
        meta={
            **graph_info.meta,
            "ordered_incident_edges_by_node": ordered_incident_edges_by_node,
            "edge_endpoint_geometry_by_edge": endpoint_geometry_by_edge,
        },
    )
