"""节点正式对象契约。

这里定义的是 junction_rebuild 之后唯一允许进入主线的节点对象。
后续阶段只能更新该对象的字段，不允许再发明并列节点身份。
"""

from dataclasses import dataclass, field
from typing import Any, Literal

# 当前主线只保留两类主节点语义。
# `junction` / `dead_end` 仍然是主分类，不再为 pure cycle cut 另起并列 node_type。
# 特殊节点统一通过 `is_virtual / virtual_reason` 补充说明。
#
# 这样做的目的是保持 node_type 的消费口径稳定，把特殊来源语义压到附加字段而不是主枚举里。
# 后续任何“来源特殊”的节点，如果不改变主消费语义，也应优先落到 virtual 字段而不是扩主枚举。
NodeType = Literal["junction", "dead_end"]
VirtualReason = Literal["pure_cycle_cut", "dead_end"]


@dataclass(slots=True)
class NodeInfo:
    """描述单个正式节点的最小稳定信息。

    真实职责：
        承载主线中单个节点的稳定身份、几何位置、关联边以及节点 polygon。
        junction_rebuild 开始先建立该对象，后续阶段只允许更新字段，不允许更换 `node_id`。

    Args:
        node_id:
            节点正式主键。单位：无。
            约束：在整条主线内必须唯一，且下游阶段不得重编号。
        point_rc:
            节点当前运行尺度坐标，格式为 `(row, col)`。单位：像素。
            约束：必须处于运行尺度坐标系，而不是渲染放大后的坐标系。
        node_type:
            节点语义类型，当前只允许 `junction` 或 `dead_end`。
        incident_edge_ids:
            与该节点相连的边 id 集合。单位：无。
            约束：这里记录的是唯一正式边 id 集，不展开 self-loop 的双端口。
        degree:
            节点当前可连接 traversal 端口数。单位：无。
            约束：普通节点通常等于 `incident_edge_ids` 的长度；
            self-loop 节点允许大于唯一边 id 个数。
        is_virtual:
            当前节点是否为虚拟节点。单位：无。
            约束：普通节点默认为 `False`。
        virtual_reason:
            虚拟节点来源原因。单位：无。
            约束：仅在 `is_virtual = True` 时才有意义。
        polygon_vertices_rc:
            节点 polygon 顶点序列。单位：像素。
            约束：交汇节点通常需要提供；断头路节点可为空。
        debug_info:
            调试信息。仅用于算法内部追踪，不属于主线最小语义。
        validation_info:
            校验信息。用于记录对象闭环校验结果，不参与算法决策。

    Returns:
        NodeInfo:
            一个可被 junction_rebuild 写出、并被 topology_graph_build / coverage_planning 继续消费的正式节点对象。
    """

    # 正式节点身份。一旦写出，下游只允许继承，不允许再造并列主键。
    node_id: int
    # 运行尺度下的节点几何中心位置。
    point_rc: tuple[float, float]
    # 当前节点只保留最小业务语义，不提前发散更多类型。
    node_type: NodeType
    # 关联边集合由 junction_rebuild 输出前和 topology_graph_build 建图时反复刷新。
    # 但一旦进入正式 stage result，它就应与 graph/edge 回指关系保持闭环。
    incident_edge_ids: tuple[int, ...] = ()
    # `degree` 是显式字段，便于做对象级闭环校验。
    degree: int = 0
    # `is_virtual` 表示该节点是否为算法补建节点，普通真实节点必须保持 False。
    is_virtual: bool = False
    # `virtual_reason` 记录虚拟节点来源，例如 pure cycle 切口或 dead-end 补点。
    virtual_reason: VirtualReason | None = None
    # polygon 不是调试中间量，而是后续边有效区域生成、边路径切分的正式约束。
    polygon_vertices_rc: tuple[tuple[float, float], ...] | None = None
    # 调试信息允许带研究过程痕迹，但不能替代正式字段。
    debug_info: dict[str, Any] | None = field(default=None)
    # 校验信息用于记录契约是否满足，例如 traversal degree 与端口展开语义是否一致。
    validation_info: dict[str, Any] | None = field(default=None)
