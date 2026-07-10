"""CoveragePlanning stage 入口。"""

from typing import Any

from ..coverage_planning import attach_edge_coverage_info
from ..coverage_planning import build_coverage_lane_sweep_info
from ..coverage_planning import build_final_coverage_path_build_info
from ..coverage_planning import build_sweep_cadence_info
from ..coverage_planning import build_sweep_graph_info
from ..coverage_planning import validate_sweep_graph
from ..contracts import CoveragePlanningResult
from ..contracts import GeometryPreparationResult
from ..contracts import TopologyGraphBuildResult


def attach_graph_edge_coverage_info(
    topology_graph_build_result: TopologyGraphBuildResult,
    coverage_lane_sweep_info: Any,
) -> Any:
    """把 coverage lane sweep 真值挂回 graph edge 视图。"""

    # 这里只补 edge-level coverage 摘要，保持 graph 主体身份不变。
    # coverage lane / sweep / route 真值仍然停留在 coverage planning 子域对象里。
    return attach_edge_coverage_info(
        graph_info=topology_graph_build_result.graph_info,
        coverage_lane_info=coverage_lane_sweep_info.coverage_lane_info,
    )


def build_coverage_plan(
    topology_graph_build_result: TopologyGraphBuildResult,
    config: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> CoveragePlanningResult:
    """基于正式图生成覆盖规划结果。

    真实职责：
        在不回写图对象的前提下，基于 topology_graph_build 建立的 `graph_info`
        和其图层派生结果生成当前正式主线：
        `coverage_lane_info + sweeps + SweepGraph + greedy SweepCadence + FinalCoveragePath`。

    Args:
        topology_graph_build_result:
            topology_graph_build 输出，至少包含正式 `graph_info`。
        config:
            CoveragePlanning 阶段配置。后续将承载路径选择和覆盖策略参数。
        context:
            运行时上下文。仅用于传递必要元信息。

    Returns:
        CoveragePlanningResult:
            CoveragePlanning 正式输出。

    副作用:
        当前函数不应写文件、不应修改全局状态；它只负责返回内存对象。
    """
    # CoveragePlanning helper 全部按普通 dict 读取配置与上下文，因此入口先规整类型。
    config = dict(config or {})
    context = dict(context or {})
    geometry_result = require_geometry_preparation_result(context)

    # CoveragePlanning 严格按 coverage lane sweep -> sweep graph -> sweep cadence -> final path 串行推进。
    # 这也是 CoveragePlanning 内部职责边界保持清晰的前提。
    coverage_lane_sweep_info = build_coverage_lane_sweep_info(
        graph_info=topology_graph_build_result.graph_info,
        geometry_result=geometry_result,
        config=config,
    )
    # 把 coverage lane 摘要挂回 graph 后，后续 final path/debug 就能同时看到图和覆盖宽度摘要。
    graph_info = attach_graph_edge_coverage_info(
        topology_graph_build_result=topology_graph_build_result,
        coverage_lane_sweep_info=coverage_lane_sweep_info,
    )

    # 当前 sweep graph 直接从 formal node-local hypotheses 展开，不再经过旧 directed-lane 图层。
    sweep_graph_build_info = build_sweep_graph_info(
        graph_info=graph_info,
        node_local_connection_hypothesis_info=topology_graph_build_result.node_local_connection_hypothesis_info or {},
        coverage_lane_sweep_info=coverage_lane_sweep_info,
    )
    sweep_cadence_build_info = build_sweep_cadence_info(
        coverage_lane_sweep_info=coverage_lane_sweep_info,
        sweep_graph_build_info=sweep_graph_build_info,
        config={
            # sweep cadence 的配置在这里显式收口，避免 helper 直接耦合外部大配置对象。
            # 这些参数都属于 cadence 求解策略，而不是 coverage lane sweep / sweep graph 的几何真值。
            # 因此它们统一作为 cadence 私有配置传入。
            # 这样基线 compare 一旦漂移，就能先判断是几何输入还是求解策略变化。
            'covered_connector_max_depth': int(config.get('sweep_cadence_covered_connector_max_depth', 2)),
            'covered_connector_max_cost': float(config.get('sweep_cadence_covered_connector_max_cost', 12.0)),
            'foldback_risk_limit': float(config.get('sweep_cadence_foldback_risk_limit', 5.0)),
            # route_edit_trace 是显式注入的调试旁路，只用于外部审计写盘，不参与 cadence 决策。
            'route_edit_trace': config.get('sweep_cadence_route_edit_trace'),
        },
    )

    # final coverage path 的连接宽度推导依赖明确的物理清洁宽度。
    # 因此这里即使其它 coverage 子域能跑，也不能继续容忍缺省 0 值进入最终路径层。
    robot_width_m = float(config.get('robot_width_m', 0.0))
    if robot_width_m <= 0.0:
        raise ValueError('coverage planning requires explicit positive robot_width_m for FinalCoveragePath')
    final_coverage_path_build_info = build_final_coverage_path_build_info(
        graph_info=graph_info,
        geometry_result=geometry_result,
        coverage_lane_sweep_info=coverage_lane_sweep_info,
        sweep_graph_build_info=sweep_graph_build_info,
        sweep_cadence_build_info=sweep_cadence_build_info,
        config={
            # final coverage path 必须显式带清洁宽度，因为节点区连接的覆盖支持宽度依赖这个物理量。
            # 这里把 resolution 一起写死到 final coverage path 配置，避免下游重复向 geometry_result 取值。
            # final coverage path 同时读取前三个 coverage planning 子域真值，因此这里是 CoveragePlanning 主装配的最后汇聚点。
            # 也是最终路径真值首次完整物化的地方。
            # 最终路径一旦在这里生成，后续 stage 只允许做写出和 compare，不再重算。
            'coverage_width_m': float(config.get('coverage_width_m', 0.55)),
            'robot_width_m': float(robot_width_m),
            'resolution_m_per_px': float(geometry_result.resolution_m_per_px),
        },
    )

    # validation_info 仍按 coverage planning 子域分层保留，便于基线 compare 后快速定位漂移来源。
    validation_info = {
        # 子域级校验分层保留，方便后续直接定位失败发生在哪一层。
        'coverage_lane_generation': coverage_lane_sweep_info.validation_info,
        'sweep_graph': validate_sweep_graph(
            sweep_group_info=sweep_graph_build_info.sweep_group_info,
            sweep_transition_candidate_info=sweep_graph_build_info.sweep_transition_candidate_info,
            sweep_graph_info=sweep_graph_build_info.sweep_graph_info,
            sweep_cadence_info=sweep_cadence_build_info.sweep_cadence_info,
        ),
        'final_coverage_path': final_coverage_path_build_info.validation_info,
    }

    # debug_info 聚焦阶段摘要，而不是把每层大对象原样抄回结果树。
    # 返回对象继续沿用四个 coverage planning 子域分层结构，不在主装配层重新发明字段树。
    # 这样 compare 工具可以分别锁每一层真值，而不是只看最终路径。
    # meta 则只放人工最常核对的计数，保持结果对象主干简洁。
    return CoveragePlanningResult(
        graph_info=graph_info,
        coverage_lane_sweep_info=coverage_lane_sweep_info,
        sweep_graph_build_info=sweep_graph_build_info,
        sweep_cadence_build_info=sweep_cadence_build_info,
        final_coverage_path_build_info=final_coverage_path_build_info,
        debug_info={
            'coverage_lane_generation_summary': dict(coverage_lane_sweep_info.summary),
            'sweep_graph_summary': {
                **dict(sweep_graph_build_info.summary),
                **dict(sweep_cadence_build_info.summary),
                **dict(final_coverage_path_build_info.summary),
            },
        },
        validation_info=validation_info,
        meta={
            # meta 只保留人工和回归最常看的 stage 级计数，不重复挂完整 payload。
            # 这些计数也是 real-case summary 会直接消费的最小摘要层。
            # 因此这里要同时覆盖四个 coverage planning 子域的关键规模指标。
            'stage': 'coverage_planning',
            'coverage_lane_unit_count': int(coverage_lane_sweep_info.summary.get('coverage_lane_count', 0)),
            'sweep_count': int(coverage_lane_sweep_info.summary.get('sweep_count', 0)),
            'sweep_group_count': int(sweep_graph_build_info.summary.get('sweep_group_count', 0)),
            'sweep_port_view_count': int(sweep_graph_build_info.summary.get('sweep_port_view_count', 0)),
            'sweep_transition_candidate_count': int(sweep_graph_build_info.summary.get('sweep_transition_candidate_count', 0)),
            'sweep_transition_fallback_candidate_count': int(
                sweep_graph_build_info.sweep_transition_candidate_info.get('summary', {}).get('fallback_candidate_count', 0)
            ),
            'sweep_cadence_count': int(sweep_cadence_build_info.summary.get('sweep_cadence_count', 0)),
            'final_coverage_path_route_count': int(final_coverage_path_build_info.summary.get('route_count', 0)),
            'junction_connection_count': int(final_coverage_path_build_info.summary.get('junction_connection_count', 0)),
        },
    )


def require_geometry_preparation_result(context: dict[str, Any]) -> GeometryPreparationResult:
    """读取并校验 geometry_preparation 结果。"""

    # CoveragePlanning 一定要读 geometry_preparation 的 free_mask/world geometry，因此这里把缺失视为硬错误。
    geometry_result = context.get('geometry_preparation_result')
    if not isinstance(geometry_result, GeometryPreparationResult):
        # final path 节点连接宽度和 geometry free space 都依赖它，缺失时不能靠其它 stage 结果硬猜。
        raise ValueError('coverage planning requires geometry_preparation_result in context')
    return geometry_result
