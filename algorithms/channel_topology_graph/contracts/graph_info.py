"""图正式对象契约。

图对象只在 topology_graph_build 第一次建立，用于把节点和边组织成正式拓扑关系。
"""

from dataclasses import dataclass, field
from typing import Any

from .edge_info import EdgeInfo
from .node_info import NodeInfo


@dataclass(slots=True)
class GraphInfo:
    """描述正式图对象。

    真实职责：
        把 junction_rebuild 输出的 `node_info` 与 `edge_info` 聚合成第一个正式图对象，
        供 topology_graph_build 后半段以及 coverage_planning 直接消费。

    Args:
        nodes:
            正式节点集合。单位：无。
            约束：其中每个元素都必须是已 compact 后的有效节点对象。
        edges:
            正式边集合。单位：无。
            约束：其中每个元素都必须能通过 `src_node_id / dst_node_id`
            回指到 `nodes` 中的节点。
        meta:
            图级元信息。允许记录阶段名、统计值、配置摘要等。

    Returns:
        GraphInfo:
            topology_graph_build 第一次建立的正式图对象。
    """

    # `nodes` 是图层正式节点集合，必须来自 junction_rebuild compact 后的 node_info。
    nodes: tuple[NodeInfo, ...]
    # `edges` 是图层正式边集合，每条边都必须能通过 src/dst 回指到 nodes。
    edges: tuple[EdgeInfo, ...]
    # meta 允许挂局部排序、端点几何等派生视图，但这些派生视图不能替代 nodes/edges 成为新的主数据。
    meta: dict[str, Any] = field(default_factory=dict)
