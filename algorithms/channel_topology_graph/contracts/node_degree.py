"""节点度数语义 helper。

这里把“唯一 incident 边数”和“可连接 traversal 端口数”区分开，避免 pure cycle cut
这类 self-loop 节点继续被强行压回 `degree == len(incident_edge_ids)` 的旧口径。
"""

from __future__ import annotations

from .edge_info import EdgeInfo
from .node_info import NodeInfo


def traversal_degree_for_node(
    node: NodeInfo,
    edge_by_id: dict[int, EdgeInfo],
) -> int:
    """按当前节点可连接的 traversal 端口数计算 degree。"""

    degree = 0
    node_id = int(node.node_id)
    for edge_id in node.incident_edge_ids:
        edge = edge_by_id.get(int(edge_id))
        if edge is None:
            # 缺失 edge 在正式闭环里应被上游校验拦下；这里仅保守跳过，避免 helper 自己崩掉。
            continue
        is_src = int(edge.src_node_id) == node_id
        is_dst = int(edge.dst_node_id) == node_id
        if is_src:
            degree += 1
        if is_dst:
            degree += 1
    return int(degree)


__all__ = ("traversal_degree_for_node",)
