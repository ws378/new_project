"""货架感知覆盖图构建与节点域的导出入口。"""

from .coverage_graph import CoverageCell, CoverageGraphView, build_coverage_graph_view_from_cell_rows
from .grid_builder import (
  CellCandidate,
  CoverageCellGrid,
  build_cell_candidates,
  build_coverage_graph,
  build_legacy_node_matrix,
  complete_cell_test,
  repair_regular_grid_cell,
)

# 覆盖图构建是整个规划链路的基础层，导出时保持关键入口完整可追溯。
__all__ = [
  "CellCandidate",
  "CoverageCell",
  "CoverageCellGrid",
  "CoverageGraphView",
  "build_cell_candidates",
  "build_coverage_graph",
  "build_coverage_graph_view_from_cell_rows",
  "build_legacy_node_matrix",
  "complete_cell_test",
  "repair_regular_grid_cell",
]
