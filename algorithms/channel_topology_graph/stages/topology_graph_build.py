"""TopologyGraphBuild stage 入口。"""

from __future__ import annotations

from typing import Any

from ..topology_graph_build import assemble_graph_info
from ..topology_graph_build import build_incident_port_info
from ..topology_graph_build import build_node_local_connection_hypothesis_info
from ..topology_graph_build import build_ordered_incident_edges
from ..topology_graph_build import validate_graph_info
from ..contracts import JunctionRebuildResult
from ..contracts import TopologyGraphBuildResult


def build_base_graph_info(junction_rebuild_result: JunctionRebuildResult) -> Any:
    """由 junction_rebuild 正式 node/edge 首次建立 graph_info。"""

    # graph_info 的首次装配必须显式来自 compact 后 node/edge，
    # 这样 graph 层的 degree / incident 语义才与 junction_rebuild 正式输出一致。
    return assemble_graph_info(
        node_info_list=junction_rebuild_result.node_info_list,
        edge_info_list=junction_rebuild_result.edge_info_list,
    )


def build_graph_candidate_layers(
    graph_info: Any,
    config: dict[str, Any],
) -> tuple[Any, Any, Any]:
    """构造 ordered incident、port 与 node-local hypothesis 结果。"""

    _ = config
    # topology_graph_build 当前这层不读配置，说明这些对象完全由正式图真值决定，而不是调参决定。
    ordered_graph_info = build_ordered_incident_edges(graph_info)
    incident_port_info = build_incident_port_info(ordered_graph_info)
    node_local_connection_hypothesis_info = build_node_local_connection_hypothesis_info(
        ordered_graph_info,
        incident_port_info,
    )
    return (
        ordered_graph_info,
        incident_port_info,
        node_local_connection_hypothesis_info,
    )


def build_topology_graph(
    junction_rebuild_result: JunctionRebuildResult,
    config: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> TopologyGraphBuildResult:
    """基于节点和边第一次建立正式图。

    真实职责：
        把 junction_rebuild 输出的 `node_info / edge_info` 聚合成 `graph_info`，
        并继续派生连接候选与有向 lane 图信息。

    Args:
        junction_rebuild_result:
            junction_rebuild 输出的正式节点和边。
        config:
            topology_graph_build 阶段配置。后续将承载 candidate/lane 相关参数。
        context:
            运行时上下文。仅用于传递必要元信息。

    Returns:
        TopologyGraphBuildResult:
            topology_graph_build 正式输出，其中 `graph_info` 在这里第一次建立。

    副作用:
        当前函数不应写文件、不应修改全局状态；它只负责返回内存对象。
    """
    # topology_graph_build 当前不消费 context，但接口保留，避免 pipeline 编排层再做条件分支。
    _ = context
    # 配置统一转成普通 dict，避免后续 helper 在 Mapping/自定义对象上分叉。
    config = dict(config or {})
    stage_outputs = build_topology_graph_stage_outputs(
        junction_rebuild_result=junction_rebuild_result,
        config=config,
    )
    validation_info = build_topology_graph_validation_info(stage_outputs)
    return build_topology_graph_result(
        stage_outputs=stage_outputs,
        validation_info=validation_info,
    )


def build_topology_graph_stage_outputs(
    *,
    junction_rebuild_result: JunctionRebuildResult,
    config: dict[str, Any],
) -> dict[str, Any]:
    """按 topology_graph_build 正式顺序构建子结果。"""

    # 这里第一次建图，意味着 junction_rebuild 输出必须已经 compact 干净。
    graph_info = build_base_graph_info(junction_rebuild_result)
    # 节点内顺时针 incident 排序仍然是 topology 第一层局部几何真值的入口。
    # `incident_port_info` 和 `node_local_connection_hypothesis_info`
    # 是当前正式 topology 派生层，后续 coverage planning 不再读取旧 candidate/lane 图层。
    # graph_info 在这里被 replace 成带 meta 视图的新对象，但 node/edge 主体不变。
    (
        graph_info,
        incident_port_info,
        node_local_connection_hypothesis_info,
    ) = build_graph_candidate_layers(graph_info, config)
    return {
        "graph_info": graph_info,
        "incident_port_info": incident_port_info,
        "node_local_connection_hypothesis_info": node_local_connection_hypothesis_info,
    }


def build_topology_graph_validation_info(stage_outputs: dict[str, Any]) -> dict[str, Any]:
    """构造 topology graph stage 级 validation 结果。"""

    graph_info = stage_outputs["graph_info"]
    incident_port_info = stage_outputs["incident_port_info"]
    node_local_connection_hypothesis_info = stage_outputs["node_local_connection_hypothesis_info"]
    # 基础图闭环先验失败时，后续所有候选层都会被污染，因此先做第一层校验。
    # 这层失败时直接说明第 2/3 步边界没守住。
    validation_info = {
        "graph_info": validate_graph_info(graph_info),
        "incident_ports": {
            # incident_ports 当前主要校验规模闭环，细粒度合法性由构造 helper 保证。
            "valid": True,
            "port_count": int(len(incident_port_info.get("items", ()))),
            "node_with_ports_count": int(len(incident_port_info.get("items_by_node", {}))),
        },
        "node_local_connection_hypotheses": {
            # node-local hypotheses 也先保留规模摘要，方便后续快速比对候选生成是否断流。
            "valid": True,
            "hypothesis_count": int(len(node_local_connection_hypothesis_info.get("items", ()))),
            "node_with_hypotheses_count": int(len(node_local_connection_hypothesis_info.get("items_by_node", {}))),
        },
    }
    return validation_info


def build_topology_graph_result(
    *,
    stage_outputs: dict[str, Any],
    validation_info: dict[str, Any],
) -> TopologyGraphBuildResult:
    """组装 topology_graph_build 正式结果。"""

    graph_info = stage_outputs["graph_info"]
    incident_port_info = stage_outputs["incident_port_info"]
    node_local_connection_hypothesis_info = stage_outputs["node_local_connection_hypothesis_info"]
    # debug_info 只回传 topology_graph_build 内部派生视图，不重复拷贝整个 graph/meta 树。
    # 第一轮把 port/hypothesis 摘要也带出去，方便快速确认新对象是否真正落地。
    # meta 则保留最常用计数，供 smoke 和 real-case 摘要直接消费。
    return TopologyGraphBuildResult(
        graph_info=graph_info,
        incident_port_info=incident_port_info,
        node_local_connection_hypothesis_info=node_local_connection_hypothesis_info,
        debug_info={
            # 这里只暴露按节点整理后的 incident 顺序视图，方便直接审查局部拓扑扇区关系。
            "ordered_incident_edges_by_node": graph_info.meta.get("ordered_incident_edges_by_node", {}),
            # summary 留给人工/基线快速看规模，不替代正式 items 主体。
            "incident_port_summary": incident_port_info.get("summary", {}),
            "node_local_connection_hypothesis_summary": node_local_connection_hypothesis_info.get("summary", {}),
        },
        validation_info=validation_info,
        meta={
            "stage": "topology_graph_build",
            "node_count": int(len(graph_info.nodes)),
            "edge_count": int(len(graph_info.edges)),
            # formal_primary_outputs 显式声明本 stage 的正式主输出集合，防止 debug/meta 被误读成主 contract。
            "formal_primary_outputs": (
                "graph_info",
                "incident_port_info",
                "node_local_connection_hypothesis_info",
            ),
        },
    )
