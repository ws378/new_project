from __future__ import annotations

"""Sweep graph 的 TypedDict 契约。"""

from typing import TypedDict


class SweepGroupItem(TypedDict, total=False):
    # `group_id` 是 sweep group 在当前 stage 内的稳定标识，不等同于 coverage_lane_id。
    group_id: int
    # `coverage_lane_id` 表示这组 sweeps 来源于哪条 coverage lane，供回查 lane 级区域和宽度摘要。
    coverage_lane_id: int
    # `source_edge_id` 表示这组 sweeps 映射回的正式 graph edge，是 topology hypothesis 投影到 group 的依据。
    source_edge_id: int
    # `edge_type` 继承 edge 连接类型，供 group 内横移和特殊边处理判断适用范围。
    edge_type: str
    # `src_node_id` 是 source edge 的 src 端节点，供构造 src 端口 sweep 排列视图。
    src_node_id: int
    # `dst_node_id` 是 source edge 的 dst 端节点，供构造 dst 端口 sweep 排列视图。
    dst_node_id: int
    # `ordered_sweep_ids` 明确组内 sweep 的正式横向顺序，是端口视图和 cadence 的基础。
    ordered_sweep_ids: tuple[int, ...] | list[int]
    # `center_sweep_id` 是组内最接近 lane 中心参考线的 sweep，用于中心对齐和解释候选偏离程度。
    center_sweep_id: int
    # `center_sweep_index` 是 center_sweep_id 在 ordered_sweep_ids 中的位置。
    center_sweep_index: int
    # `sweep_count` 是该 group 当前承载的 active sweep 数量。
    sweep_count: int
    # `main_direction` 给出这组 sweeps 的主方向向量，供端口排序和连接几何解释使用。
    main_direction: tuple[float, float] | list[float]


class SweepGroupSummary(TypedDict, total=False):
    # `group_count` 是成功建立的 sweep group 数量，不包含 inactive lane。
    group_count: int
    # `active_sweep_count` 是所有正式 group 内 active sweep 的合计数量。
    active_sweep_count: int


class SweepGroupInfo(TypedDict, total=False):
    # `groups` 是完整正式 group 列表，后续 port/candidate 构造从这里读取 group 真值。
    groups: tuple[SweepGroupItem, ...]
    # `group_by_edge_id` 支持从 topology edge_id 快速定位 sweep group。
    group_by_edge_id: dict[int, SweepGroupItem]
    # `group_by_lane_id` 支持从 coverage_lane_id 快速定位 sweep group。
    group_by_lane_id: dict[int, SweepGroupItem]
    # `summary` 是 group 层规模摘要，不替代 groups 主体。
    summary: SweepGroupSummary


class SweepPortViewItem(TypedDict, total=False):
    # `group_id` 表示这份端口视图属于哪个 sweep group。
    group_id: int
    # `coverage_lane_id` 保留端口视图对应的 lane 来源，便于调试横向排序。
    coverage_lane_id: int
    # `node_id` 表示当前端口视图围绕哪个正式节点观察 sweep 排列。
    node_id: int
    # `port_side` 表示当前视图对应 group 的 src 端还是 dst 端。
    port_side: str
    # `ordered_port_sweep_ids` 表示站在当前节点端口看到的 sweep 横向排列顺序。
    ordered_port_sweep_ids: tuple[int, ...] | list[int]
    # `port_rank_by_sweep_id` 是 sweep_id 到端口序位的反查表，供候选生成快速算 rank_gap。
    port_rank_by_sweep_id: dict[int, int]
    # `center_port_rank` 把 group 中心 sweep 映射到当前端口序中，便于中心对齐候选生成。
    center_port_rank: int


class SweepPortViewSummary(TypedDict, total=False):
    # `port_view_count` 是成功建立的端口视图数量，通常最多为 group 数量的两倍。
    port_view_count: int


class SweepPortViewInfo(TypedDict, total=False):
    # `items` 是完整端口视图列表，是 candidate 生成的正式排序输入。
    items: tuple[SweepPortViewItem, ...]
    # `lookup` 是按 group/node/端型回查端口视图的索引，主线优先使用三元键。
    lookup: dict[tuple[int, int], SweepPortViewItem] | dict[tuple[int, int, str], SweepPortViewItem]
    # `summary` 是端口视图规模摘要，不替代 items/lookup 主体。
    summary: SweepPortViewSummary


class SweepTransitionCandidateItem(TypedDict, total=False):
    """单条正式 sweep transition 候选的最小真值。"""

    # `candidate_id` 是候选层稳定标识，不等于最终是否入选 cadence/final path。
    candidate_id: int
    # `source_topology_lane_id` 是 sweep_graph 层内部投影 lane 的编号，group_internal 候选可使用负值表示无 topology lane。
    source_topology_lane_id: int
    # `source_hypothesis_id` 回指 topology node-local hypothesis；组内横移候选为空。
    source_hypothesis_id: int | None
    # `candidate_source` 说明候选来自 node-local hypothesis 投影还是 group 内横移补充。
    candidate_source: str
    # `via_node_id` 表示该 transition 候选依托哪个节点或端口位置生成。
    via_node_id: int
    # `from_group_id` 表示 transition 起点 sweep 所在 group。
    from_group_id: int
    # `to_group_id` 表示 transition 终点 sweep 所在 group。
    to_group_id: int
    # `from_sweep_id` 是 transition 起点 sweep。
    from_sweep_id: int
    # `to_sweep_id` 是 transition 目标 sweep。
    to_sweep_id: int
    # `from_end_type` 表示从起点 sweep 的 src/dst 哪一端离开。
    from_end_type: str
    # `to_end_type` 表示进入目标 sweep 的 src/dst 哪一端。
    to_end_type: str
    # `same_sweep` 标记该候选是否在同一条 sweep 内翻端。
    same_sweep: bool
    # `same_edge` 标记 from/to 是否仍属于同一条正式 edge，用于区分跨边连接和边内横移。
    same_edge: bool
    # `connection_kind` 是 cadence 主线消费的连接方向语义，当前收敛为 forward / foldback。
    connection_kind: str
    # `motion_type` 是候选的运动形态解释，如 straight / left_turn / right_turn / lateral / foldback。
    motion_type: str
    # `mapping_type` 记录候选形成方式，如 endpoint_geometry、same_sweep_foldback、adjacent_same_side。
    mapping_type: str
    # `mapping_pair_index` 是当前 mapping 内第几组 pair，便于调试候选来源和可视化标注。
    mapping_pair_index: int
    # `from_port_rank` 是 from_sweep 在 from 端口视图中的横向序位。
    from_port_rank: int
    # `to_port_rank` 是 to_sweep 在 to 端口视图中的横向序位。
    to_port_rank: int
    # `rank_gap` 是同 group 横移候选的端口序位差；跨 group 候选仅保留为解释字段。
    rank_gap: int
    # `endpoint_distance_m` 是候选指定 from/to 端型之间端点距离的米制表达，禁止主消费层直接读取像素距离。
    endpoint_distance_m: float
    # `sweep_turn_delta_deg` 是指定 from/to 端型下的 sweep 级端点方向夹角。
    sweep_turn_delta_deg: float
    # `local_feasibility_score` 是 candidate 层对局部连接质量的归一化摘要，值越大越优。
    local_feasibility_score: float
    # `risk_score` 是候选局部风险代理分；跨 group 主要由端点距离、端点转角和局部可行性构成。
    risk_score: float
    # `coverage_gain_score` 表示这条候选对连续覆盖的收益倾向，值越高越像主线可保留连接。
    coverage_gain_score: float
    # `total_score` 是候选层统一排序分，组合米制距离和局部风险，不是 cadence 最终 route 代价。
    total_score: float
    # `confidence_score` 是候选生成阶段对该候选可靠性的置信度摘要。
    confidence_score: float
    # `selection_level` 表示候选强弱档位；当前正式主线一般写 strong_keep，旧多层候选不再展开。
    selection_level: str
    # `trace_tags` 保留候选来源规则标签，只用于解释和调试，不参与主线裁决。
    trace_tags: tuple[str, ...]
    # `source_trace_label` 保留上游原始连接标签，便于回溯 cycle/dead_end 等历史来源语义。
    source_trace_label: str


class SweepTransitionCandidateSummary(TypedDict, total=False):
    # `candidate_count` 是正式 transition candidate 总数。
    candidate_count: int
    # `strong_candidate_count` 是 strong_keep 档位候选数量。
    strong_candidate_count: int
    # `weak_candidate_count` 当前保留摘要口径，主线不再生成旧的弱候选树。
    weak_candidate_count: int
    # `fallback_candidate_count` 当前保留摘要口径，主线不再生成旧 fallback 候选树。
    fallback_candidate_count: int
    # `forward_candidate_count` 是 forward 连接候选数量。
    forward_candidate_count: int
    # `foldback_candidate_count` 是 foldback 连接候选数量。
    foldback_candidate_count: int


class SweepTransitionCandidateInfo(TypedDict, total=False):
    # `items` 是 cadence 唯一正式读取的 transition 候选集合。
    items: tuple[SweepTransitionCandidateItem, ...]
    # `summary` 是 candidate 层规模与类别摘要，不替代 items 主体。
    summary: SweepTransitionCandidateSummary


class SweepGraphBuildSummary(TypedDict, total=False):
    # `sweep_group_count` 是 sweep group 数量。
    sweep_group_count: int
    # `sweep_port_view_count` 是端口排序视图数量。
    sweep_port_view_count: int
    # `sweep_transition_candidate_count` 是正式 transition candidate 数量。
    sweep_transition_candidate_count: int
    # `sweep_count` 是进入 sweep graph 静态骨架的 sweep 数量。
    sweep_count: int


class SweepGraphNode(TypedDict, total=False):
    # `node_id` 是 sweep graph 静态骨架里保留的 topology node 主键。
    node_id: int
    # `node_type` 保留节点主分类，供 cadence 判断 dead-end-like / junction 语境。
    node_type: str
    # `point_rc` 是节点中心点运行尺度坐标，供渲染和端口几何解释使用。
    point_rc: list[float]


class SweepGraphSweep(TypedDict, total=False):
    # `sweep_id` 是 sweep graph 静态骨架中的正式 sweep 主键。
    sweep_id: int
    # `sweep_global_id` 保留 coverage_lane_sweep 阶段原始 sweep id，通常与 sweep_id 一致。
    sweep_global_id: int
    # `sweep_local_id` 是同一 coverage lane 内的局部序号，用于解释 lane 内横向顺序。
    sweep_local_id: int
    # `coverage_lane_id` 表示该 sweep 来源 lane，供 cadence 优先同 lane 串联。
    coverage_lane_id: int
    # `source_edge_id` 表示该 sweep 来源 edge，供 same_edge 和 group 回溯使用。
    source_edge_id: int
    # `side_level` 是 sweep 离中心线的离散层级，cadence 用它区分中心/边缘优先级。
    side_level: int
    # `mean_offset_m` 是 sweep 相对中心线的米制平均偏移，禁止再使用像素偏移参与主线排序。
    mean_offset_m: float
    # `path_length_m` 是 sweep 主路径长度米制摘要，用于起点选择和覆盖统计。
    path_length_m: float
    # `path_rc` 是 sweep 静态骨架路径点，坐标仍为运行尺度 row/col。
    path_rc: tuple[tuple[float, float], ...]


class SweepGraphSummary(TypedDict, total=False):
    # `sweep_count` 是 sweep_graph_info 静态骨架中保留的 sweep 数量。
    sweep_count: int


class SweepGraphInfo(TypedDict, total=False):
    """Sweep graph 正式 contract。

    当前对象只承载 sweep 静态骨架：
    - nodes
    - sweeps

    正式连接真值不再保留在本对象里，统一收敛到
    `sweep_transition_candidate_info.items`。
    """

    # `nodes` 给出参与 sweep graph 的节点真值子集，只保留 cadence 需要的静态节点摘要。
    nodes: tuple[SweepGraphNode, ...]
    # `sweeps` 给出最终纳入静态 sweep graph 的 sweep 集合，不混入 transition 真值。
    sweeps: tuple[SweepGraphSweep, ...]
    # `summary` 是静态骨架规模摘要，不替代 nodes/sweeps 主体。
    summary: SweepGraphSummary


class SweepGraphValidation(TypedDict, total=False):
    # `valid` 表示 sweep graph 静态骨架和 candidate 集是否满足 cadence 输入前提。
    valid: bool
    # `error_count` 是 sweep graph validation 发现的结构错误数量。
    error_count: int
    # `errors` 保存具体错误描述，用于定位缺 group、缺 sweep、缺 candidate 等问题。
    errors: list[str]
    # `group_count` 是 validation 看到的 group 数量。
    group_count: int
    # `sweep_count` 是 validation 看到的 sweep 数量。
    sweep_count: int
    # `candidate_count` 是 validation 看到的 transition candidate 数量。
    candidate_count: int
    # `strong_candidate_count` 是 validation 看到的 strong candidate 数量。
    strong_candidate_count: int
    # `weak_candidate_count` 是兼容摘要字段，当前主线不应依赖旧弱候选数量。
    weak_candidate_count: int
    # `fallback_candidate_count` 是兼容摘要字段，当前主线不应依赖旧 fallback 候选数量。
    fallback_candidate_count: int


__all__ = (
    "SweepGroupItem",
    "SweepGroupSummary",
    "SweepGroupInfo",
    "SweepPortViewItem",
    "SweepPortViewSummary",
    "SweepPortViewInfo",
    "SweepTransitionCandidateItem",
    "SweepTransitionCandidateSummary",
    "SweepTransitionCandidateInfo",
    "SweepGraphBuildSummary",
    "SweepGraphNode",
    "SweepGraphSweep",
    "SweepGraphSummary",
    "SweepGraphInfo",
    "SweepGraphValidation",
)
