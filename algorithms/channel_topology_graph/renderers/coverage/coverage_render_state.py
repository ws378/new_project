"""Coverage 规划渲染共享状态读取 helper。"""

from __future__ import annotations

from ...contracts import (
    CoveragePlanningResult,
    EdgeCoverageInfo,
    EdgeInfo,
    FinalCoveragePathConnection,
    FinalCoveragePathInfo,
    SweepCadenceInfo,
    SweepGraphInfo,
    SweepInfo,
    SweepPortViewInfo,
    SweepTransitionCandidateInfo,
)


def sweep_items(result: CoveragePlanningResult) -> tuple[SweepInfo, ...]:
    """提取 coverage lane sweep 真值里的正式 sweep 列表。"""

    # coverage lane sweep 结果缺失时，说明 coverage 规划还没生成任何 sweep 真值。
    # 渲染层在这里统一回空元组，避免上层分支判断散落。
    coverage_lane_sweep_info = result.coverage_lane_sweep_info
    if coverage_lane_sweep_info is None:
        return ()
    return tuple(coverage_lane_sweep_info.sweeps)


def sweep_port_view_info(result: CoveragePlanningResult) -> SweepPortViewInfo:
    """提取节点口 sweep 排序调试真值。"""

    # sweep graph 结果缺失时，节点口排序视图自然不存在。
    # 渲染逻辑统一按空字典处理“无调试真值”场景。
    sweep_graph_build_info = result.sweep_graph_build_info
    if sweep_graph_build_info is None:
        return {}
    return sweep_graph_build_info.sweep_port_view_info


def sweep_transition_candidate_info(result: CoveragePlanningResult) -> SweepTransitionCandidateInfo:
    """提取 sweep transition 候选调试真值。"""

    # transition candidate 只在 sweep graph 建图后才有意义。
    # 因此缺 sweep graph 时直接回空表，而不是抛异常。
    sweep_graph_build_info = result.sweep_graph_build_info
    if sweep_graph_build_info is None:
        return {}
    return sweep_graph_build_info.sweep_transition_candidate_info


def sweep_graph_info(result: CoveragePlanningResult) -> SweepGraphInfo:
    """提取正式 sweep graph 真值。"""

    # sweep graph 也是 sweep graph build 的正式产物。
    # 这里的空字典语义是“尚未建图”，不是“图为空”。
    sweep_graph_build_info = result.sweep_graph_build_info
    if sweep_graph_build_info is None:
        return {}
    return sweep_graph_build_info.sweep_graph_info


def sweep_cadence_info(result: CoveragePlanningResult) -> SweepCadenceInfo:
    """提取 SweepCadence 真值。"""

    # SweepCadence 属于 sweep cadence build 结果。
    # 若 sweep cadence 未执行，渲染层直接收到空字典占位。
    sweep_cadence_build_info = result.sweep_cadence_build_info
    if sweep_cadence_build_info is None:
        return {}
    return sweep_cadence_build_info.sweep_cadence_info


def final_coverage_path_info(result: CoveragePlanningResult) -> FinalCoveragePathInfo:
    """提取 FinalCoveragePath 正式真值。"""

    # FinalCoveragePath 只在 final coverage path build 后成立。
    # 空字典让后续 detail 渲染能自然退化成“无最终路径”。
    final_coverage_path_build_info = result.final_coverage_path_build_info
    if final_coverage_path_build_info is None:
        return {}
    return final_coverage_path_build_info.final_coverage_path_info


def junction_connections(result: CoveragePlanningResult) -> tuple[FinalCoveragePathConnection, ...]:
    """提取 FinalCoveragePath 中全部节点连接条目。"""

    # junction_connections 是 FinalCoveragePathInfo 里的稳定字段名。
    return tuple(final_coverage_path_info(result).get("junction_connections", ()))


def edge_coverage_info_by_edge_id(result: CoveragePlanningResult) -> dict[int, EdgeCoverageInfo]:
    """按 edge_id 收集 graph 上已经投影好的边级 coverage 真值。"""

    # 这里按 edge_id 建索引，是为了让渲染层能 O(1) 回查某条正式边的 coverage 真值。
    collected: dict[int, EdgeCoverageInfo] = {}
    for edge in result.graph_info.edges:
        # 只收已经挂载 coverage_info 的正式边。
        if edge.coverage_info is None:
            continue
        collected[int(edge.edge_id)] = edge.coverage_info
    # 返回结果只表达“哪些边已经有 coverage 投影”，不补空值占位。
    return collected


def find_edge(result: CoveragePlanningResult, edge_id: int) -> EdgeInfo | None:
    """按 edge_id 查正式边对象。"""

    # 渲染层偶尔只拿到外部 id，需要回查完整边对象。
    # 这里保持线性扫描，避免额外维护渲染专用索引状态。
    for edge in result.graph_info.edges:
        if int(edge.edge_id) == int(edge_id):
            return edge
    return None


def edge_by_coverage_lane_id(result: CoveragePlanningResult) -> dict[int, EdgeInfo]:
    """按 coverage_lane_id 建立边对象索引。"""

    # 某些 summary 图以 coverage_lane_id 为主键，而正式图结构仍以 edge_id 为主键。
    # 这里做一次显式映射，避免上游反复扫描全部边。
    edge_by_lane_id: dict[int, EdgeInfo] = {}
    for edge in result.graph_info.edges:
        coverage_info = edge.coverage_info
        # 没有 coverage_info 的边不可能带 coverage_lane_id。
        if coverage_info is None:
            continue
        edge_by_lane_id[int(coverage_info["coverage_lane_id"])] = edge
    # 返回结果只包含已经进入 coverage 主链的边。
    return edge_by_lane_id



__all__ = [
    "edge_by_coverage_lane_id",
    "edge_coverage_info_by_edge_id",
    "final_coverage_path_info",
    "find_edge",
    "junction_connections",
    "sweep_cadence_info",
    "sweep_graph_info",
    "sweep_items",
    "sweep_port_view_info",
    "sweep_transition_candidate_info",
]
