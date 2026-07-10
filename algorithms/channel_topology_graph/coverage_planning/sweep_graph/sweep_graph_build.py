"""Sweep graph 正式结果构造。"""

from __future__ import annotations

import math
from typing import Any

from algorithms.channel_topology_graph.contracts import (
    CoverageLaneInfoItem,
    CoverageLaneSweepBuildInfo,
    GraphInfo,
    SweepGraphBuildSummary,
    SweepGraphBuildInfo,
    SweepGraphInfo,
    SweepGraphNode,
    SweepGraphSweep,
    SweepGroupInfo,
    SweepGroupItem,
    SweepInfo,
    SweepPortViewInfo,
    SweepPortViewItem,
    SweepTransitionCandidateInfo,
    SweepTransitionCandidateItem,
)
from .sweep_transition_candidates import build_sweep_transition_candidates


def resolve_sweep_transition_candidates(
    source: SweepGraphBuildInfo | SweepTransitionCandidateInfo | dict[str, Any] | None,
) -> tuple[SweepTransitionCandidateItem, ...]:
    """统一解析正式 sweep 连接候选。"""

    if source is None:
        # 没有输入时，按“当前没有任何正式 candidate”解释，
        # 而不是抛错；这样调用方可以统一把它当空候选集处理。
        return ()
    if hasattr(source, 'sweep_transition_candidate_info'):
        # BuildInfo 对象场景下，正式候选挂在具名字段里；
        # 这里优先走这条主路径，避免调用方自己判断对象层级。
        return tuple(getattr(source, 'sweep_transition_candidate_info').get('items', ()))
    if isinstance(source, dict):
        if 'items' in source and 'summary' in source:
            # 直接传进来的若本身就是 candidate info 形状，就原样取 `items`。
            return tuple(source.get('items', ()))
        candidate_info = source.get('sweep_transition_candidate_info')
        if isinstance(candidate_info, dict):
            # dict 形状的 build_info 场景下，再从嵌套字段回退读取。
            return tuple(candidate_info.get('items', ()))
    # 走到这里说明输入对象不具备任何正式 candidate 真值入口。
    return ()


def build_transition_candidate_lookup(
    source: SweepGraphBuildInfo | SweepTransitionCandidateInfo | dict[str, Any] | None,
) -> dict[int, SweepTransitionCandidateItem]:
    """按 candidate_id 建立正式候选查表。"""

    # 这里把 candidate item 全部复制成 dict，
    # 是为了确保下游做局部读写或补字段时不会回头污染原始 build 结果。
    return {int(item['candidate_id']): dict(item) for item in resolve_sweep_transition_candidates(source)}


def build_graph_sweep_items(
    sweeps: tuple[SweepInfo, ...] | list[SweepInfo],
) -> list[SweepGraphSweep]:
    """把 stage A sweeps 提升为 stage B graph sweeps。"""

    # 只有 active sweep 才能进入正式 sweep graph。
    # 失效条带若混进来，后面 route/candidate 看到的就是一套已经不再参与规划的旧 sweep。
    active_sweeps: list[SweepGraphSweep] = [dict(item) for item in sweeps if bool(item.get('active', True))]
    grouped: dict[int, list[SweepGraphSweep]] = {}
    for item in active_sweeps:
        # 这里按 coverage_lane_id regroup，
        # 因为 `sweep_local_id` 的语义是“该条带在自己 coverage lane 内的局部序号”。
        grouped.setdefault(int(item['coverage_lane_id']), []).append(item)
    for lane_sweeps in grouped.values():
        # 局部序号按 mean_offset_m 排，是为了让同一 lane 内 sweep 从一侧到另一侧保持稳定横向顺序。
        # sweep_id 只作为同 offset 场景下的稳定 tie-break。
        ordered = sorted(lane_sweeps, key=lambda item: (float(item.get('mean_offset_m', 0.0)), int(item['sweep_id'])))
        for local_index, sweep in enumerate(ordered, start=1):
            # `sweep_global_id` 保留原始 sweep 标识；
            # `sweep_local_id` 则是 sweep graph 阶段新增的 lane 内局部序号。
            sweep['sweep_global_id'] = int(sweep['sweep_id'])
            sweep['sweep_local_id'] = int(local_index)
    return active_sweeps


def build_sweep_graph(
    graph_info: GraphInfo,
    sweeps: tuple[SweepInfo, ...] | list[SweepInfo],
) -> SweepGraphInfo:
    """构造只承载 sweep 静态骨架的最小 graph。"""

    # 这里故意只装配 sweep 静态骨架，不在这一步混入 transition candidate。
    # 原因是 group/port/candidate 都有各自的中间真值对象，不能把 sweep graph 本体搞成“大杂烩”。
    active_sweeps = build_graph_sweep_items(sweeps)
    nodes: tuple[SweepGraphNode, ...] = tuple(
        {
            'node_id': int(node.node_id),
            'node_type': str(node.node_type),
            # point_rc 只保留节点中心几何，供后续 port 排序和连接物化做局部几何引用。
            'point_rc': [float(node.point_rc[0]), float(node.point_rc[1])],
        }
        for node in graph_info.nodes
    )
    return {
        'nodes': nodes,
        'sweeps': tuple(active_sweeps),
        # sweep graph 本体的 summary 只关心骨架规模，
        # group/port/candidate 的规模统计留给外层 build_info.summary 汇总。
        'summary': {'sweep_count': int(len(active_sweeps))},
    }


def build_sweep_groups(
    graph_info: GraphInfo,
    coverage_lane_info: tuple[CoverageLaneInfoItem, ...] | list[CoverageLaneInfoItem],
    sweeps: tuple[SweepInfo, ...] | list[SweepInfo],
) -> SweepGroupInfo:
    """按 coverage lane 聚合 sweep，得到后续候选直接消费的组真值。"""

    # edge_by_id 把 group 构建里需要的 edge 真值先拉平，
    # 后面每条 lane 只需要按 source_edge_id O(1) 取边语义，不再反复扫 graph edges。
    edge_by_id = {int(edge.edge_id): edge for edge in graph_info.edges}
    sweeps_by_lane: dict[int, list[SweepInfo]] = {}
    for sweep in sweeps:
        if not bool(sweep.get('active', True)):
            # 非 active sweep 已经退出正式 coverage 主线，
            # 这里不再把它们混入 group 聚合，避免后续 port 排序和 candidate 展开读到失效条带。
            continue
        sweeps_by_lane.setdefault(int(sweep['coverage_lane_id']), []).append(sweep)

    groups: list[SweepGroupItem] = []
    group_by_edge_id: dict[int, SweepGroupItem] = {}
    group_by_lane_id: dict[int, SweepGroupItem] = {}
    for lane in coverage_lane_info:
        if not bool(lane.get('active', True)):
            # 非 active coverage lane 不能再生成正式 sweep group，
            # 否则后续会把已经失效的 lane 当成仍可连接的主线结构。
            continue
        lane_id = int(lane['coverage_lane_id'])
        lane_sweeps = sorted(
            sweeps_by_lane.get(lane_id, ()),
            key=lambda item: (float(item.get('mean_offset_m', 0.0)), int(item['sweep_id'])),
        )
        if not lane_sweeps:
            # 某条 lane 没有任何 active sweep 时，说明它在当前 sweep 世界里没有可承载的覆盖条带，
            # 这里直接不建 group，避免后续出现“有组名义、无 sweep 实体”的空壳 group。
            continue
        edge = edge_by_id[int(lane['source_edge_id'])]
        # ordered_ids 是 group 内 sweep 的正式横向顺序；
        # 后面的 port 视图与 group_internal lateral 候选都建立在这个局部顺序之上。
        ordered_ids = [int(item['sweep_id']) for item in lane_sweeps]
        center_index = min(
            range(len(lane_sweeps)),
            # center sweep 选“最接近 lane 主中心”的那一条。
            # 先看 mean_offset_m 是否更接近 0，再用 side_level 作为弱 tie-break，
            # 目的是给 port 中心秩和中心对齐映射提供一个稳定锚点。
            key=lambda idx: (abs(float(lane_sweeps[idx].get('mean_offset_m', 0.0))), abs(int(lane_sweeps[idx].get('side_level', 0)))),
        )
        group: SweepGroupItem = {
            # group_id 是 sweep graph 阶段自己的稳定组编号，不等于 coverage_lane_id。
            'group_id': int(len(groups) + 1),
            'coverage_lane_id': lane_id,
            'source_edge_id': int(lane['source_edge_id']),
            # edge_type 直接继承 edge 真值；缺字段时保守按双端连通解释，
            # 让后续 group_internal 规则优先沿正式主线类型工作。
            'edge_type': str(edge.edge_type or 'connected_both_ends'),
            'src_node_id': int(edge.src_node_id),
            'dst_node_id': int(edge.dst_node_id),
            'ordered_sweep_ids': ordered_ids,
            'center_sweep_id': int(ordered_ids[center_index]),
            'center_sweep_index': int(center_index),
            'sweep_count': int(len(ordered_ids)),
            # main_direction 用外层边的整体走向表示 group 主方向，
            # 供后续解释端口/连接几何时作为轻量方向真值使用。
            'main_direction': list(infer_main_direction(edge.outer_path_rc)),
        }
        groups.append(group)
        # 两张 lookup 分别服务于“按 edge 回 group”和“按 coverage lane 回 group”两类调用方。
        group_by_edge_id[int(group['source_edge_id'])] = group
        group_by_lane_id[int(group['coverage_lane_id'])] = group

    return {
        'groups': tuple(groups),
        'group_by_edge_id': group_by_edge_id,
        'group_by_lane_id': group_by_lane_id,
        'summary': {
            # 这里的 active_sweep_count 是“成功进入正式 group 的 sweep 总数”，
            # 不是原始 sweeps 输入长度。
            'group_count': int(len(groups)),
            'active_sweep_count': int(sum(int(item['sweep_count']) for item in groups)),
        },
    }


def build_sweep_port_views(
    graph_info: GraphInfo,
    sweep_group_info: SweepGroupInfo,
    sweeps: tuple[SweepInfo, ...] | list[SweepInfo],
) -> SweepPortViewInfo:
    """建立每个 group 在 src/dst 两端的 sweep 口部排序视图。"""

    # sweeps_by_id 提供 port 排序时的 sweep 几何读取入口；
    # node_center_by_id 提供“当前端口围绕哪个节点中心做横向投影”的几何基准。
    sweeps_by_id = {int(item['sweep_id']): item for item in sweeps}
    node_center_by_id = {int(node.node_id): tuple(node.point_rc) for node in graph_info.nodes}
    items: list[SweepPortViewItem] = []
    lookup: dict[tuple[int, int, str], SweepPortViewItem] = {}

    for group in sweep_group_info.get('groups', ()):
        for end_type, node_id in (('src', int(group['src_node_id'])), ('dst', int(group['dst_node_id']))):
            node_center = node_center_by_id.get(node_id)
            if node_center is None:
                # port 排序依赖节点中心点定义“端口横向法向坐标”。
                # 缺节点中心时，这一端的 sweep 顺序就没有正式几何基准，因此整端直接跳过。
                continue
            ordered_ids = sorted(
                (int(item) for item in group['ordered_sweep_ids']),
                key=lambda sweep_id: port_rank_coord_for_sweep(
                    sweeps_by_id[sweep_id],
                    at_start=(end_type == 'src'),
                    node_center=node_center,
                ),
            )
            # 这里的排序结果表达的是：
            # “站在当前 node 的当前端口看出去，这些 sweep 在端口横向上的正式先后顺序”。
            port_view: SweepPortViewItem = {
                'group_id': int(group['group_id']),
                'coverage_lane_id': int(group['coverage_lane_id']),
                'node_id': int(node_id),
                # `port_side` 明确这份排序视图对应 group 的哪一端；
                # 同一个 group 会各自产生 src / dst 两份独立排序。
                'port_side': str(end_type),
                'ordered_port_sweep_ids': ordered_ids,
                # rank lookup 供后续 pair 对齐、rank-gap 评分和中心口秩读取直接复用。
                'port_rank_by_sweep_id': {int(sweep_id): int(rank) for rank, sweep_id in enumerate(ordered_ids)},
                # center_port_rank 表示 group 中心 sweep 在当前端口序里的位置。
                # 若中心 sweep 没出现在该端口序中，则记 -1，避免伪造中心秩。
                'center_port_rank': int(ordered_ids.index(int(group['center_sweep_id'])) if int(group['center_sweep_id']) in ordered_ids else -1),
            }
            items.append(port_view)
            # lookup 使用 `(group_id, node_id, end_type)` 三元键，
            # 是为了显式区分同一 group 在 src/dst 两端的两份 port 序视图。
            lookup[(int(group['group_id']), int(node_id), str(end_type))] = port_view

    return {
        'items': tuple(items),
        'lookup': lookup,
        # 这里的 port_view_count 是“实际成功建立了多少端口视图”，
        # 因而会自然反映掉那些因缺 node center 而被跳过的端口。
        'summary': {'port_view_count': int(len(items))},
    }


def infer_main_direction(path_rc: object) -> tuple[float, float]:
    """从 path 首尾估计组的主方向。"""

    path = tuple(tuple(map(float, point)) for point in (path_rc or ()))
    if len(path) < 2:
        # 路径点不足时，无法定义稳定方向，退回零向量让调用方按“未知方向”解释。
        return (0.0, 0.0)
    delta_r = float(path[-1][0] - path[0][0])
    delta_c = float(path[-1][1] - path[0][1])
    # 这里取的是整条 edge outer_path 的首尾位移，
    # 目标不是还原局部曲率，而是提供一个稳定的“整体朝向”近似。
    norm = math.hypot(delta_r, delta_c)
    if norm <= 1e-6:
        # 首尾几乎重合时，边的整体走向不可判，继续返回零向量而不是伪造单位方向。
        return (0.0, 0.0)
    return (delta_r / norm, delta_c / norm)


def endpoint_tangent(path_rc: tuple[tuple[float, float], ...], *, at_start: bool) -> tuple[float, float]:
    """估计 sweep 在起点或终点处的一阶切向。"""

    if len(path_rc) < 2:
        # 点数不足时，没有可估的一阶切向，只能给一个稳定默认值防止后续投影崩掉。
        return (0.0, 1.0)
    # 起点端取前两个点，终点端取后两个点；
    # 这表达的是“就在端口附近，这条 sweep 正朝哪个方向离开/进入节点”。
    a, b = (path_rc[0], path_rc[1]) if at_start else (path_rc[-2], path_rc[-1])
    delta_r = float(b[0] - a[0])
    delta_c = float(b[1] - a[1])
    norm = math.hypot(delta_r, delta_c)
    if norm <= 1e-6:
        # 局部端点段退化成零长度时，同样回退到稳定默认切向。
        return (0.0, 1.0)
    return (delta_r / norm, delta_c / norm)


def port_rank_coord_for_sweep(
    sweep: SweepInfo,
    *,
    at_start: bool,
    node_center: tuple[float, float],
) -> float:
    """把端点投影到端口法向，得到节点口横向排序坐标。"""

    path_rc = tuple(tuple(map(float, point)) for point in sweep.get('path_rc', ()))
    if not path_rc:
        # 缺路径时无法取端点几何，这里返回 0 只是为了让排序可继续，
        # 同时把这类 sweep 自然压到“缺正式几何依据”的保守口径里。
        return 0.0
    endpoint = path_rc[0] if at_start else path_rc[-1]
    # 端口横向坐标不是直接拿 endpoint 的行列值，而是：
    # 1. 先估 endpoint 处切向；
    # 2. 再取其法向；
    # 3. 把 endpoint 相对 node center 的位移投影到法向上。
    # 这样得到的值才真正对应“同一个端口截面上的左右顺序”。
    tangent = endpoint_tangent(path_rc, at_start=at_start)
    # 端口排序要比的是“同一端口截面上的左右位置”，
    # 所以这里取切向的法向作为投影轴，而不是直接用地图全局行/列坐标。
    normal = (-float(tangent[1]), float(tangent[0]))
    relative = (float(endpoint[0]) - float(node_center[0]), float(endpoint[1]) - float(node_center[1]))
    # 点积结果越小/越大，就表示这个 sweep 端点在当前端口法向上的位置越靠一侧。
    return float(relative[0] * normal[0] + relative[1] * normal[1])


def build_sweep_graph_info(
    *,
    graph_info: GraphInfo,
    coverage_lane_sweep_info: CoverageLaneSweepBuildInfo,
    node_local_connection_hypothesis_info: dict[str, Any] | None = None,
) -> SweepGraphBuildInfo:
    """构造 CoveragePlanning 的 SweepGraph 正式结果。"""

    # 这四块结果按依赖顺序串起来：
    # 1. 先从 sweep/lane 建 group；
    # 2. 再从 group 建两端 port 序视图；
    # 3. 再基于 group + port + topology hypothesis 展开 transition candidate；
    # 4. 最后回填最小 sweep graph 静态骨架。
    sweep_group_info = build_sweep_groups(
        graph_info=graph_info,
        coverage_lane_info=coverage_lane_sweep_info.coverage_lane_info,
        sweeps=coverage_lane_sweep_info.sweeps,
    )
    sweep_port_view_info = build_sweep_port_views(
        graph_info=graph_info,
        sweep_group_info=sweep_group_info,
        sweeps=coverage_lane_sweep_info.sweeps,
    )
    sweep_transition_candidate_info = build_sweep_transition_candidates(
        sweep_group_info=sweep_group_info,
        sweep_port_view_info=sweep_port_view_info,
        sweeps=coverage_lane_sweep_info.sweeps,
        # hypothesis 缺省时按空集处理，表示“当前没有 topology 主线连接可投影”，
        # 但 group/port/sweep graph 骨架仍然要正常构造出来。
        node_local_connection_hypothesis_info=node_local_connection_hypothesis_info or {},
    )
    sweep_graph_info = build_sweep_graph(graph_info=graph_info, sweeps=coverage_lane_sweep_info.sweeps)
    # summary 只做规模级统计，不承载额外推导语义；
    # 它的作用是让基线、调试和工作流记录能快速看到这一轮 sweep graph 产物规模。
    summary: SweepGraphBuildSummary = {
        # 这里四个计数分别对应 sweep graph build 的四块正式产物规模。
        'sweep_group_count': int(len(tuple(sweep_group_info.get('groups', ())))),
        'sweep_port_view_count': int(len(tuple(sweep_port_view_info.get('items', ())))),
        'sweep_transition_candidate_count': int(len(tuple(sweep_transition_candidate_info.get('items', ())))),
        'sweep_count': int(len(tuple(sweep_graph_info.get('sweeps', ())))),
    }
    # 最终 BuildInfo 把中间真值和最小骨架统一打包。
    # 这样 cadence/final-path/文档比对工具都可以围绕同一份正式 stage 输出工作。
    return SweepGraphBuildInfo(
        sweep_group_info=sweep_group_info,
        sweep_port_view_info=sweep_port_view_info,
        sweep_transition_candidate_info=sweep_transition_candidate_info,
        sweep_graph_info=sweep_graph_info,
        summary=summary,
    )


__all__ = (
    'build_graph_sweep_items',
    'build_sweep_graph',
    'build_sweep_graph_info',
    'build_sweep_groups',
    'build_sweep_port_views',
    'build_transition_candidate_lookup',
    'endpoint_tangent',
    'infer_main_direction',
    'port_rank_coord_for_sweep',
    'resolve_sweep_transition_candidates',
)
