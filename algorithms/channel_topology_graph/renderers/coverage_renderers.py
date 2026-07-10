"""CoveragePlanning 渲染正式入口。

真实职责：
    对外稳定暴露 coverage 领域的 summary/debug/detail 渲染能力，
    具体绘图与状态组合继续下沉到 `renderers.coverage/` 内部实现子包。

约束：
    本文件是领域级正式入口，不是临时兼容层；
    可以整理导出说明，但不在这里新增跨领域聚合逻辑。
"""

# 顶层渲染入口统一按“写盘入口 / summary / sweep debug / cadence debug / final debug”分组。
# 这样调用方无需下钻子包，也能直接看清 coverage 领域正式公开面。
from .coverage.coverage_render_output import write_coverage_planning_visualizations
from .coverage.coverage_render_summary import (
    render_coverage_lane_effective_region_summary,
    render_coverage_lane_territory_summary,
    render_coverage_lanes_summary,
    render_coverage_sweeps_summary,
)
from .coverage.coverage_render_sweep_debug import (
    render_sweep_node_chain_debug,
    render_sweep_node_snap_overlay,
    render_sweep_port_view_debug,
    render_sweep_transition_candidate_debug,
)
from .coverage.coverage_render_cadence_debug import (
    render_sweep_cadence_classification_inputs_debug,
    render_sweep_cadence_connection_rule_focus_debug,
    render_sweep_cadence_connection_rules_debug,
    render_sweep_cadence_debug,
)
from .coverage.coverage_render_final_debug import (
    render_final_coverage_path_debug,
    render_junction_connection_detail_for_node,
    render_junction_connection_summary,
    write_junction_connection_detail_visualizations,
)

__all__ = (
    # 写盘入口
    "write_coverage_planning_visualizations",
    # summary
    "render_coverage_lanes_summary",
    "render_coverage_lane_territory_summary",
    "render_coverage_lane_effective_region_summary",
    "render_coverage_sweeps_summary",
    # sweep debug
    "render_sweep_node_chain_debug",
    "render_sweep_node_snap_overlay",
    "render_sweep_port_view_debug",
    "render_sweep_transition_candidate_debug",
    # cadence debug
    "render_sweep_cadence_debug",
    "render_sweep_cadence_classification_inputs_debug",
    "render_sweep_cadence_connection_rules_debug",
    "render_sweep_cadence_connection_rule_focus_debug",
    # final debug
    "render_final_coverage_path_debug",
    "render_junction_connection_summary",
    "write_junction_connection_detail_visualizations",
    "render_junction_connection_detail_for_node",
)
