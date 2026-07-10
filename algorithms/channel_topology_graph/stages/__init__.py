"""Stage entrypoints for the channel topology graph pipeline.

这个壳层只负责暴露四个正式 stage 入口，
不承载任何默认求解策略、兼容分支或对象改写逻辑。
"""

from .geometry_preparation import build_geometry_preparation
from .junction_rebuild import build_junction_rebuild
from .topology_graph_build import build_topology_graph
from .coverage_planning import build_coverage_plan

__all__ = [
    # `__all__` 显式收口正式 stage 入口，避免内部 helper 被误当成稳定公共 API。
    "build_geometry_preparation",
    "build_junction_rebuild",
    "build_topology_graph",
    "build_coverage_plan",
]
