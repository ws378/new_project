"""CoveragePlanning 纯算法导出。

本包当前采用“包根正式入口 + 业务语义内部目录”结构：

1. `coverage_planning/__init__.py`
   - 本子系统唯一正式公开入口。
2. `coverage_lane_sweep/`、`sweep_graph/`、`sweep_cadence/`、`final_coverage_path/`
   - 各业务子域的内部实现层，按职责继续拆分。

约束：
    包根 `__init__.py` 只负责暴露本子系统的稳定对外能力，不新增跨子系统桥接逻辑。
    各业务子域目录继续作为内部实现目录存在，但不会被抬升成新的公开包根。
    后续若继续重构，只允许在保持对外导出语义稳定的前提下细化内部阶段边界。
"""

# coverage_lane_sweep
from .coverage_lane_sweep.coverage_lane_sweep_build import (
    build_coverage_lane_sweep_info,
    build_coverage_lanes_and_sweeps,
)
from .coverage_lane_sweep.lane_sweep_results import (
    attach_edge_coverage_info,
    validate_coverage_lane_generation,
)

# sweep_graph
from .sweep_graph.sweep_graph_build import (
    build_sweep_graph,
    build_sweep_graph_info,
    build_sweep_groups,
    build_sweep_port_views,
    build_sweep_transition_candidates,
)
from .sweep_graph.sweep_graph_validation import validate_sweep_graph

# sweep_cadence
from .sweep_cadence.sweep_cadence_build import (
    build_sweep_cadence,
    build_sweep_cadence_info,
    build_sweep_coverage_stats,
)

# final_coverage_path
from .final_coverage_path.final_path_core import (
    build_final_coverage_path,
    build_final_coverage_path_build_info,
    validate_final_coverage_path,
)

__all__ = (
    # coverage_lane_sweep
    "attach_edge_coverage_info",
    "build_coverage_lane_sweep_info",
    "build_coverage_lanes_and_sweeps",
    "validate_coverage_lane_generation",
    # sweep_graph
    "build_sweep_graph",
    "build_sweep_graph_info",
    "build_sweep_groups",
    "build_sweep_port_views",
    "build_sweep_transition_candidates",
    "validate_sweep_graph",
    # sweep_cadence
    "build_sweep_cadence",
    "build_sweep_cadence_info",
    "build_sweep_coverage_stats",
    # final_coverage_path
    "build_final_coverage_path",
    "build_final_coverage_path_build_info",
    "validate_final_coverage_path",
)
