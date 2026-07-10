"""基于候选格构建静态覆盖图视图。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


class CoverageCellLike(Protocol):
  """用于构建 ``CoverageGraphView`` 的候选格能力约束。"""

  @property
  def stable_id(self) -> str:
    """返回用于日志与图索引的稳定 cell ID。
    
    该 ID 基于网格坐标和偏移信息稳定化，跨阶段重建时可作为主键。
    """
    ...

  @property
  def adjusted_from_grid_center_px(self) -> bool:
    """指示规划点是否从网格中心做过偏移修正。
    
    该标记用于区分“原始可行点”与“偏移候选点”的来源边界。
    """
    ...

  planning_point_px: tuple[int, int]
  grid_center_px: tuple[int, int]
  obstacle: bool
  neighbors: Sequence["CoverageCellLike"]
  grid_row: int
  grid_col: int
  obstacle_ratio: float | None
  obstacle_ratio_filtered: bool
  generation_mode: str
  generation_status: str
  generated_planning_point_px: tuple[int, int] | None
  endpoint_alignment_applied: bool

  @property
  def generation_offset_from_grid_center_px(self) -> tuple[int, int]:
    """返回生成阶段记录的平移偏移量（x, y）。
    
    偏移用于提升可达性边界时的点质量，后续评分与边界检测共享该约束。
    """
    ...

  @property
  def generation_offset_distance_px(self) -> float:
    """返回当前点到网格中心的偏移距离。
    
    当偏移异常偏大时会触发异常路径筛选，避免偏移过度导致几何退化。
    """
    ...

  @property
  def endpoint_alignment_offset_px(self) -> tuple[int, int]:
    """返回端点对齐时的额外像素偏移。
    
    该值用于末端候选融合，保证路径端点不会因局部重采样造成断裂。
    """
    ...


@dataclass(frozen=True)
class CoverageCell:
  """静态 coverage cell 的几何与拓扑元数据。"""

  cell_id: str
  grid_row: int
  grid_col: int
  grid_center_px: tuple[int, int]
  planning_point_px: tuple[int, int]
  obstacle: bool
  obstacle_ratio: float | None
  obstacle_ratio_filtered: bool
  adjusted_from_grid_center_px: bool
  generated_planning_point_px: tuple[int, int]
  generation_offset_from_grid_center_px: tuple[int, int]
  generation_offset_distance_px: float
  generation_mode: str
  generation_status: str
  endpoint_alignment_applied: bool
  endpoint_alignment_offset_px: tuple[int, int]
  neighbor_cell_ids: tuple[str, ...]
  accessible_neighbor_cell_ids: tuple[str, ...]


@dataclass(frozen=True)
class CoverageGraphView:
  """基于静态覆盖记录构建的只读覆盖图视图。"""

  cells: tuple[CoverageCell, ...]
  cells_by_id: Mapping[str, CoverageCell]
  row_count: int
  cell_count: int
  accessible_cell_count: int
  edge_count: int
  accessible_edge_count: int

  def cell(self, cell_id: str) -> CoverageCell:
    """按 id 取 cell，缺失时立即失败避免隐式回退导致追溯丢失。"""

    try:
      return self.cells_by_id[str(cell_id)]
    except KeyError as exc:
      raise AssertionError(f"Coverage graph cell missing: {cell_id}") from exc

  def accessible_cell_ids(self) -> tuple[str, ...]:
    """仅返回非障碍 cell id，作为 traverser 的可达节点白名单。"""

    return tuple(cell.cell_id for cell in self.cells if not cell.obstacle)

  def summary(self) -> dict[str, int]:
    """聚合当前阶段拓扑规模统计，给审计与回归提供固定字段。"""

    return {
      "row_count": int(self.row_count),
      "cell_count": int(self.cell_count),
      "accessible_cell_count": int(self.accessible_cell_count),
      "edge_count": int(self.edge_count),
      "accessible_edge_count": int(self.accessible_edge_count),
    }


def build_coverage_graph_view_from_cell_rows(cell_rows: Sequence[Sequence[CoverageCellLike]]) -> CoverageGraphView:
  """从静态 coverage cell 记录构建覆盖图视图。"""

  cells: list[CoverageCell] = []
  edge_count = 0
  # 行优先扫描保障与上游构建时的网格次序一致，便于复现和追溯 id 对齐。
  for row in cell_rows:
    # 每个 cell 都要走同一套校验与转换流程，避免不同来源数据混合时行为分叉。
    for cell_candidate in row:
      # 仅接受静态候选格，避免 legacy Node 混入后边序列与可追溯元数据口径错位。
      if hasattr(cell_candidate, "visited") or hasattr(cell_candidate, "visit_count"):
        raise AssertionError("CoverageGraphView expects static cell candidates, not legacy Node mirrors")
      neighbor_ids = tuple(str(neighbor.stable_id) for neighbor in cell_candidate.neighbors)
      accessible_neighbor_ids = (
        tuple(
          str(neighbor.stable_id)
          for neighbor in cell_candidate.neighbors
          if not bool(neighbor.obstacle)
        )
        if not bool(cell_candidate.obstacle)
        else tuple()
      )
      edge_count += len(neighbor_ids)
      generated_planning_point_px = cell_candidate.generated_planning_point_px
      # 生成点缺失会让几何约束和 trace 不能回放同一来源，必须显式阻断。
      if generated_planning_point_px is None:
        raise AssertionError(f"Coverage cell missing generated planning point: {cell_candidate.stable_id}")
      cells.append(
        CoverageCell(
          cell_id=str(cell_candidate.stable_id),
          grid_row=int(cell_candidate.grid_row),
          grid_col=int(cell_candidate.grid_col),
          grid_center_px=(int(cell_candidate.grid_center_px[0]), int(cell_candidate.grid_center_px[1])),
          planning_point_px=(int(cell_candidate.planning_point_px[0]), int(cell_candidate.planning_point_px[1])),
          obstacle=bool(cell_candidate.obstacle),
          obstacle_ratio=None
          if cell_candidate.obstacle_ratio is None
          else float(cell_candidate.obstacle_ratio),
          obstacle_ratio_filtered=bool(cell_candidate.obstacle_ratio_filtered),
          adjusted_from_grid_center_px=bool(cell_candidate.adjusted_from_grid_center_px),
          generated_planning_point_px=(
            int(generated_planning_point_px[0]),
            int(generated_planning_point_px[1]),
          ),
          generation_offset_from_grid_center_px=(
            int(cell_candidate.generation_offset_from_grid_center_px[0]),
            int(cell_candidate.generation_offset_from_grid_center_px[1]),
          ),
          generation_offset_distance_px=float(cell_candidate.generation_offset_distance_px),
          generation_mode=str(cell_candidate.generation_mode),
          generation_status=str(cell_candidate.generation_status),
          endpoint_alignment_applied=bool(cell_candidate.endpoint_alignment_applied),
          endpoint_alignment_offset_px=(
            int(cell_candidate.endpoint_alignment_offset_px[0]),
            int(cell_candidate.endpoint_alignment_offset_px[1]),
          ),
          neighbor_cell_ids=neighbor_ids,
          accessible_neighbor_cell_ids=accessible_neighbor_ids,
        )
      )
  cells_tuple = tuple(cells)
  cells_by_id: dict[str, CoverageCell] = {}
  # 汇总为 id 索引时必须拒绝重复主键，避免邻接引用出现模糊写入。
  for cell in cells_tuple:
    # 严格单值映射可防止同 id 在不同步骤被重复写入导致邻接引用漂移。
    if cell.cell_id in cells_by_id:
      raise AssertionError(f"Duplicate coverage cell id: {cell.cell_id}")
    cells_by_id[cell.cell_id] = cell
  return CoverageGraphView(
    cells=cells_tuple,
    cells_by_id=cells_by_id,
    row_count=len(cell_rows),
    cell_count=len(cells_tuple),
    accessible_cell_count=sum(1 for cell in cells_tuple if not cell.obstacle),
    edge_count=int(edge_count),
    accessible_edge_count=sum(len(cell.accessible_neighbor_cell_ids) for cell in cells_tuple),
  )
