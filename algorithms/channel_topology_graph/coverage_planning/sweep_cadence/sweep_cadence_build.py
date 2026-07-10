"""Sweep cadence 正式结果构造。"""

from __future__ import annotations

from typing import Any

from ...contracts import (
    CoverageLaneSweepBuildInfo,
    SweepCadenceBuildInfo,
    SweepCadenceBuildSummary,
    SweepCadenceInfo,
    SweepCoverageStats,
    SweepGraphBuildInfo,
    SweepInfo,
)
from .cadence_greedy import build_sweep_cadence_routes_greedy
from .cadence_route_repair import optimize_greedy_routes
from .cadence_types import build_cadence_context, count_transition_segments


def build_sweep_cadence(
    sweep_graph_build_info: SweepGraphBuildInfo,
    *,
    config: dict[str, Any] | None = None,
) -> SweepCadenceInfo:
    """在 sweep 图上生成最终 sweep 连接节拍骨架。"""

    # cadence 求解只直接消费 sweep graph build 的正式产物。
    # 这里先把它收口成只读上下文，避免 greedy/repair 主链再各自重复建索引。
    context = build_cadence_context(sweep_graph_build_info)
    # solver_config 是 cadence 求解期的唯一配置入口。
    # 后面 greedy、connector 预算、foldback 风险限制都从这一份 dict 读取。
    solver_config = dict(config or {})
    # 第一阶段先用 greedy 铺出“每条 sweep 至少被首次覆盖一次”的初始 routes。
    routes = list(build_sweep_cadence_routes_greedy(context, solver_config=solver_config))
    # 第二阶段再做结构整理：
    # merge、absorb、repair 都发生在 optimize_greedy_routes 里，
    # 但不会重跑 sweep 覆盖顺序主求解。
    routes = optimize_greedy_routes(
        routes,
        context,
        route_edit_trace=solver_config.get('route_edit_trace'),
    )

    for route_id, route in enumerate(routes, start=1):
        # route_id 在后处理后统一重排一次，
        # 避免 merge/split/absorb 之后沿用旧 id 造成结果集合出现空洞或重复。
        route['route_id'] = int(route_id)
        segments = tuple(route.get('segments', ()))
        # transition_count 只统计正式 transition，不把 foldback 计成图连接次数。
        route['transition_count'] = int(count_transition_segments(segments))
        # segment_count 则保留 route 里全部 primitive 数量，供 final-path/debug 看真实动作长度。
        route['segment_count'] = int(len(segments))

    # covered_sweep_ids 按 route.sweep_sequence 汇总，
    # 表达的是“当前 cadence 结果最终覆盖到了哪些 sweep”，而不是几何意义上的路径点数量。
    covered_sweep_ids = {int(sweep_id) for route in routes for sweep_id in route.get('sweep_sequence', ())}
    return {
        'routes': tuple(routes),
        'summary': {
            # 当前实现的求解器口径固定写成 greedy，供基线和工作记录识别本轮 cadence 来源。
            'solver': 'greedy',
            # cadence_count 对应最终 route 条数，不是 transition 数，也不是覆盖条带数。
            'cadence_count': int(len(routes)),
            'covered_sweep_count': int(len(covered_sweep_ids)),
        },
    }


def build_sweep_cadence_info(
    *,
    coverage_lane_sweep_info: CoverageLaneSweepBuildInfo,
    sweep_graph_build_info: SweepGraphBuildInfo,
    config: dict[str, Any] | None = None,
) -> SweepCadenceBuildInfo:
    """构造 CoveragePlanning 的 SweepCadence 正式结果。"""

    # 先得到 cadence 主结果，再基于它回算 coverage stats。
    # 这样 summary 和完整 build_info 都围绕同一份正式 route 集对齐。
    sweep_cadence_info = build_sweep_cadence(sweep_graph_build_info, config=config)
    coverage_stats = build_sweep_coverage_stats(
        sweeps=coverage_lane_sweep_info.sweeps,
        sweep_cadence_info=sweep_cadence_info,
    )
    # 这里的 summary 只做规模与完成度统计，
    # 让 pipeline 上游不用深入 routes 结构也能快速判断 cadence 是否完整覆盖。
    summary: SweepCadenceBuildSummary = {
        # cadence route 条数直接取最终 routes 数量，不再区分 greedy 前后中间形态。
        'sweep_cadence_count': int(len(tuple(sweep_cadence_info.get('routes', ())))),
        'covered_sweep_count': int(coverage_stats.get('covered_sweep_count', 0)),
        'total_sweep_count': int(coverage_stats.get('total_sweep_count', 0)),
        'coverage_ratio': float(coverage_stats.get('coverage_ratio', 0.0)),
        'is_complete': bool(coverage_stats.get('is_complete', False)),
    }
    # BuildInfo 是 cadence 阶段对 pipeline 暴露的正式总包，
    # 下游统一从这里取主结果、覆盖统计和摘要，而不是自行拼装三份对象。
    return SweepCadenceBuildInfo(
        sweep_cadence_info=sweep_cadence_info,
        coverage_stats=coverage_stats,
        summary=summary,
    )


def build_sweep_coverage_stats(
    *,
    sweeps: list[SweepInfo] | tuple[SweepInfo, ...],
    sweep_cadence_info: SweepCadenceInfo,
) -> SweepCoverageStats:
    """从 coverage lane sweep 的 sweeps 与 cadence 生成覆盖统计。"""

    # total_sweep_count 以 stage A 的正式 sweep 数为准，
    # 这里统计的是“cadence 是否把这些正式 sweep 都至少覆盖到一次”。
    total_sweep_count = int(len(tuple(sweeps or ())))
    covered_sweep_ids = {
        int(sweep_id)
        for route in tuple(sweep_cadence_info.get('routes', ()))
        for sweep_id in route.get('sweep_sequence', ())
    }
    # covered_sweep_count 按集合去重后统计，
    # 因为同一 sweep 在 route 中被重复经过，仍然只算“覆盖到一次”。
    covered_sweep_count = int(len(covered_sweep_ids))
    if total_sweep_count <= 0:
        # cadence 覆盖统计必须建立在“正式 sweep 总数有效”这个前提上。
        # 若总数非正，继续算比例没有业务意义，直接报错更利于发现上游异常。
        raise ValueError('total sweep count must be positive')
    coverage_ratio = float(covered_sweep_count) / float(total_sweep_count)
    return {
        'total_sweep_count': int(total_sweep_count),
        'covered_sweep_count': int(covered_sweep_count),
        # uncovered_sweep_count 明确给出剩余缺口，避免调用方自己再做减法。
        'uncovered_sweep_count': int(max(0, total_sweep_count - covered_sweep_count)),
        'coverage_ratio': float(coverage_ratio),
        # is_complete 的语义是“正式 sweep 是否全部至少覆盖一次”，不是路径是否最优、也不是没有重复覆盖。
        'is_complete': bool(covered_sweep_count == total_sweep_count),
    }


__all__ = (
    'build_sweep_cadence',
    'build_sweep_cadence_info',
    'build_sweep_cadence_routes_greedy',
    'build_sweep_coverage_stats',
)
