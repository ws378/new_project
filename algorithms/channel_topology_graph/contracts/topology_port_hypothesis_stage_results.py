from __future__ import annotations

"""TopologyGraphBuild 第一层 port / node-local hypothesis TypedDict 契约。"""

from typing import TypedDict


class IncidentPortItem(TypedDict, total=False):
    # `port_id` 是 incident port 层的稳定主键，供 hypothesis 用 in/out port 回指。
    port_id: int
    # `via_node_id` 指明这个端口属于哪个正式节点，所有 node-local 枚举都围绕该节点发生。
    via_node_id: int
    # `node_type` 继承节点主分类，用于区分 junction / dead_end 等局部连接语义。
    node_type: str
    # `edge_id` 指明该端口来自哪条正式 edge，是端口回指拓扑边的主键。
    edge_id: int
    # `end_type` 指明端口对应 edge 的 src 端还是 dst 端，self-loop 会因此展开成两个 traversal 端口。
    end_type: str
    # `peer_node_id` 指向这条 edge 另一端节点，便于判断该端口进入/离开后的拓扑去向。
    peer_node_id: int
    # `contact_rc` 是该端口在节点边界附近的接触点估计，供端口排序和连接几何解释使用。
    contact_rc: list[float] | tuple[float, float] | None
    # `heading_deg_image` 表示端口朝向，用图像坐标系角度表达；为空时说明方向证据不足。
    heading_deg_image: float | None
    # `cw_order_index` 是节点 incident 顺时针序中的位置，是后续本地连接假设和转角解释的基础。
    cw_order_index: int


class IncidentPortSummary(TypedDict, total=False):
    # `port_count` 是本阶段成功展开的 traversal port 总数，不等同于唯一 incident edge 数。
    port_count: int
    # `node_with_ports_count` 是至少拥有一个 port 的节点数量，用于快速发现孤立节点。
    node_with_ports_count: int


class IncidentPortInfo(TypedDict, total=False):
    # `items` 是完整端口列表，是 node-local hypothesis 枚举的正式输入。
    items: tuple[IncidentPortItem, ...]
    # `items_by_node` 是按节点聚合的端口视图，避免下游反复全表扫描 items。
    items_by_node: dict[int, list[IncidentPortItem]]
    # `summary` 只保留计数摘要，不替代 items/items_by_node 成为主数据来源。
    summary: IncidentPortSummary


class NodeLocalConnectionHypothesisItem(TypedDict, total=False):
    # `hypothesis_id` 是 node-local hypothesis 层稳定主键，供 sweep transition 回溯拓扑来源。
    hypothesis_id: int
    # `via_node_id` 表示这条局部连接假设发生在哪个节点内部。
    via_node_id: int
    # `in_port_id` 是进入该节点的 traversal port 主键。
    in_port_id: int
    # `out_port_id` 是离开该节点的 traversal port 主键。
    out_port_id: int
    # `in_edge_id` 是入口端口所属正式 edge，后续 sweep group 会按它查 from group。
    in_edge_id: int
    # `in_end_type` 表示入口发生在 in_edge 的 src/dst 哪一端。
    in_end_type: str
    # `in_peer_node_id` 表示沿入口 edge 反向看到的另一端节点，用于拓扑解释和调试。
    in_peer_node_id: int
    # `out_edge_id` 是出口端口所属正式 edge，后续 sweep group 会按它查 to group。
    out_edge_id: int
    # `out_end_type` 表示出口发生在 out_edge 的 src/dst 哪一端。
    out_end_type: str
    # `out_peer_node_id` 表示沿出口 edge 走出后看到的另一端节点。
    out_peer_node_id: int
    # `turn_delta_deg_image` 给出入口端到出口端的局部转角估计，仅作 hypothesis 几何解释和 motion 标注来源。
    turn_delta_deg_image: float | None
    # `cw_steps_from_in_to_out` 表示顺时针从入口 port 走到出口 port 跨过的端口步数。
    cw_steps_from_in_to_out: int
    # `ccw_steps_from_in_to_out` 表示逆时针从入口 port 走到出口 port 跨过的端口步数。
    ccw_steps_from_in_to_out: int
    # `connection_kind` 是 topology 层主连接语义，目前主线收敛为 forward / foldback 等有限类别。
    connection_kind: str
    # `base_confidence` 是尚未进入 coverage 子域前的拓扑先验置信度，不是 cadence 最终得分。
    base_confidence: float
    # `reason_tags` 保存形成该 hypothesis 的规则标签，只用于解释来源，不参与主线排序。
    reason_tags: tuple[str, ...]


class NodeLocalConnectionHypothesisSummary(TypedDict, total=False):
    # `hypothesis_count` 是 topology 层生成的 node-local 连接假设总数。
    hypothesis_count: int
    # `node_with_hypotheses_count` 是至少产生一条局部连接假设的节点数量。
    node_with_hypotheses_count: int
    # `forward_count` 是 forward 类连接假设数量，用于检查正常通过连接是否存在。
    forward_count: int
    # `foldback_count` 是 foldback 类连接假设数量，用于检查 dead-end / 回折语义是否进入主线。
    foldback_count: int


class NodeLocalConnectionHypothesisInfo(TypedDict, total=False):
    # `items` 是 topology 层输出给 sweep transition candidate 的正式 hypothesis 列表。
    items: tuple[NodeLocalConnectionHypothesisItem, ...]
    # `items_by_node` 是按节点聚合的 hypothesis 视图，便于调试单个节点内部连接枚举。
    items_by_node: dict[int, list[NodeLocalConnectionHypothesisItem]]
    # `summary` 是 hypothesis 层规模与类别摘要，不替代 items 主体。
    summary: NodeLocalConnectionHypothesisSummary


__all__ = (
    "IncidentPortItem",
    "IncidentPortSummary",
    "IncidentPortInfo",
    "NodeLocalConnectionHypothesisItem",
    "NodeLocalConnectionHypothesisSummary",
    "NodeLocalConnectionHypothesisInfo",
)
