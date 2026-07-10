from __future__ import annotations

"""Sweep cadence 的 TypedDict 契约。"""

from typing import TypedDict


class SweepCadenceSegment(TypedDict, total=False):
    # `segment_index` 是 route 内稳定顺序，不跨 route 复用语义。
    segment_index: int
    # `primitive_type` 区分 sweep 段、transition 段等 route 原语类别，是 final path 展开分支的主依据。
    primitive_type: str
    # `connection_kind` 表示该 segment 使用 forward 还是 foldback 等主连接语义。
    connection_kind: str
    # `candidate_source` 记录该 transition 来源于 node_projected 还是 group_internal 等 candidate 来源。
    candidate_source: str
    # `from_sweep_id` 是该 segment 连接或覆盖动作的起点 sweep。
    from_sweep_id: int
    # `to_sweep_id` 是该 segment 连接或覆盖动作的目标 sweep。
    to_sweep_id: int
    # `transition_id` 回指正式 sweep_transition_candidate；纯 sweep 段或局部辅助段可为空。
    transition_id: int | None
    # `via_node_id` 记录该连接依托的节点；组内横移或无节点连接可为空。
    via_node_id: int | None
    # `entry_end_type` 表示进入当前 sweep 或连接段时对应的 src/dst 端。
    entry_end_type: str
    # `exit_end_type` 表示离开当前 sweep 或连接段时对应的 src/dst 端。
    exit_end_type: str
    # `requires_junction_connection` 说明 final path 是否需要在路口区补一段显式连接几何。
    requires_junction_connection: bool
    # `is_repeat_coverage_transition` 标记该连接是否为了接回未覆盖 sweep 而重复经过已覆盖区域。
    is_repeat_coverage_transition: bool
    # `same_sweep` 标记该 segment 是否发生在同一条 sweep 内，通常对应 foldback 类语义。
    same_sweep: bool
    # `same_edge` 标记该 segment 的 from/to sweep 是否来自同一条正式 edge。
    same_edge: bool
    # `rank_gap` 保留 candidate 阶段的端口秩差，用于解释这段连接的局部错位风险。
    rank_gap: int
    # `selection_level` 保留 candidate 强弱档位，便于回看 cadence 选择是否依赖弱候选。
    selection_level: str
    # `motion_type` 保留运动形态解释，如 straight / lateral / foldback，供 route 排序和 debug 使用。
    motion_type: str
    # `trace_tags` 透传 candidate 来源规则标签，只用于解释，不作为 final path 几何真值。
    trace_tags: tuple[str, ...]
    # `source_trace_label` 保留上游原始连接标签，便于排查 cycle/dead_end 等来源。
    source_trace_label: str
    # `foldback_penalty` 保留这段 transition 因折返风险被加了多少惩罚。
    foldback_penalty: float


class SweepCadenceRoute(TypedDict, total=False):
    """单条 cadence route 的正式真值。"""

    # `route_id` 是 cadence 层 route 主键，final path 会按它组织最终路径 route。
    route_id: int
    # `sweep_sequence` 是 route 级主序列，只回答“按什么 sweep 顺序覆盖”。
    sweep_sequence: list[int]
    # `segments` 保留每一步进入/离开端型、候选来源与连接语义，是 final path 的直接输入。
    segments: tuple[SweepCadenceSegment, ...]
    # `start_sweep_id` 是 route 覆盖的第一条 sweep。
    start_sweep_id: int
    # `end_sweep_id` 是 route 覆盖的最后一条 sweep。
    end_sweep_id: int
    # `start_end_type` 表示 route 从首条 sweep 的哪一端进入。
    start_end_type: str
    # `end_end_type` 表示 route 最终停在末条 sweep 的哪一端。
    end_end_type: str
    # `sweep_count` 是 route 内覆盖的 sweep 数量。
    sweep_count: int
    # `transition_count` 是 route 内正式 transition segment 数量，不把普通 sweep 段计入。
    transition_count: int
    # `segment_count` 是 route 内所有 segment 的数量。
    segment_count: int
    # `connector_depth` 是 route 求解中允许/使用的重复覆盖连接器深度摘要。
    connector_depth: int
    # `transition_cost` 是 route 中 transition 选择累计代价，用于比较不同 route 结果。
    transition_cost: float
    # `connector_cost` 是重复覆盖连接器累计代价，与 transition_cost 分开记录便于调试。
    connector_cost: float


class SweepCadenceSummary(TypedDict, total=False):
    # `solver` 记录当前 route 生成器/修复器实现名，便于回归比较不同策略。
    solver: str
    # `cadence_count` 是生成的 route 数量。
    cadence_count: int
    # `covered_sweep_count` 是 cadence routes 实际覆盖到的 sweep 去重数量。
    covered_sweep_count: int


class SweepCoverageStats(TypedDict, total=False):
    # `total_sweep_count` 是 sweep graph 中应覆盖的 sweep 总数。
    total_sweep_count: int
    # `covered_sweep_count` 是 cadence 成功覆盖的 sweep 去重数量。
    covered_sweep_count: int
    # `uncovered_sweep_count` 是仍未被 cadence 覆盖的 sweep 数量。
    uncovered_sweep_count: int
    # `coverage_ratio` 是 covered / total 的阶段完成度比例。
    coverage_ratio: float
    # `is_complete` 表示 cadence 是否覆盖了所有应覆盖 sweep。
    is_complete: bool


class SweepCadenceBuildSummary(TypedDict, total=False):
    # `sweep_cadence_count` 是最终输出 route 数量。
    sweep_cadence_count: int
    # `covered_sweep_count` 是 build info 层汇总的已覆盖 sweep 数。
    covered_sweep_count: int
    # `total_sweep_count` 是 build info 层汇总的应覆盖 sweep 总数。
    total_sweep_count: int
    # `coverage_ratio` 是 build info 层暴露给外部 summary 的覆盖比例。
    coverage_ratio: float
    # `is_complete` 表示本阶段是否完成全部 sweep 覆盖。
    is_complete: bool


class SweepCadenceInfo(TypedDict, total=False):
    """sweep cadence 层的正式真值容器。"""

    # `routes` 是 cadence 层正式主输出，后续 final path 只允许从这里读取 route 顺序与 segment 语义。
    routes: tuple[SweepCadenceRoute, ...]
    # `summary` 是 cadence route 规模摘要，不替代 routes 主体。
    summary: SweepCadenceSummary


__all__ = (
    "SweepCadenceSegment",
    "SweepCadenceRoute",
    "SweepCadenceSummary",
    "SweepCoverageStats",
    "SweepCadenceBuildSummary",
    "SweepCadenceInfo",
)
