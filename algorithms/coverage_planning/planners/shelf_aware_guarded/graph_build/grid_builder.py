"""把旋转后的可通行区域离散成覆盖网格节点。

能量规划器不直接在像素级别搜索，而是按 coverage_width_px 生成近似覆盖 footprint
的节点图。这里负责把每个网格单元映射到一个代表点，并建立 8 邻接关系。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterator, Sequence, Tuple

import cv2
import numpy as np

from ..models import Node
from .coverage_graph import CoverageGraphView, build_coverage_graph_view_from_cell_rows
from algorithms.coverage_planning.node_generation_profiles import (
  SHELF_CELL_ADJUSTED,
  TURN_COST_REGULAR_GRID,
  TURN_COST_REPAIRED_GRID,
  NodeGenerationSettings,
)
from .node_alignment import align_grid_segments_to_free_endpoints as _align_grid_segments_to_free_endpoints
from .node_filtering import filter_nodes_by_obstacle_ratio as _filter_nodes_by_obstacle_ratio
from .grid_topology import connect_grid_neighbors as _connect_grid_neighbors


GENERATION_STATUS_CENTER_FREE = "center_free"
GENERATION_STATUS_CELL_ADJUSTED = "cell_adjusted"
GENERATION_STATUS_CELL_ADJUST_FAILED = "cell_adjust_failed"
GENERATION_STATUS_REGULAR_GRID_BLOCKED = "regular_grid_blocked"
GENERATION_STATUS_BOUNDED_REPAIRED = "bounded_repaired"
GENERATION_STATUS_REPAIR_FAILED = "repair_failed"


@dataclass
class CellCandidate:
  """用于生成覆盖图的静态候选格，尚未绑定 legacy Node 镜像。"""

  planning_point_px: Tuple[int, int]
  grid_center_px: Tuple[int, int]
  obstacle: bool = True
  neighbors: list["CellCandidate"] = field(default_factory=list)
  grid_row: int = -1
  grid_col: int = -1
  obstacle_ratio: float | None = None
  obstacle_ratio_filtered: bool = False
  generation_mode: str = "unspecified"
  generation_status: str = "unspecified"
  generated_planning_point_px: Tuple[int, int] | None = None
  endpoint_alignment_applied: bool = False

  def __post_init__(self) -> None:
    """确保 generated_planning_point_px 默认回填，避免下游缺 None。"""

    # 下游会直接读取 generated_planning_point_px，先回填避免空值进入可复现链路。
    if self.generated_planning_point_px is None:
      self.generated_planning_point_px = (
        int(self.planning_point_px[0]),
        int(self.planning_point_px[1]),
      )

  @property
  def stable_id(self) -> str:
    """使用行列坐标固定 cell 的身份语义，避免后续重建时 id 漂移。"""

    return f"r{self.grid_row}_c{self.grid_col}"

  @property
  def adjusted_from_grid_center_px(self) -> bool:
    """判断该格是否因修正算法偏离规则中心。"""

    return self.planning_point_px != self.grid_center_px

  @property
  def generation_offset_from_grid_center_px(self) -> Tuple[int, int]:
    """把实际生成点相对规则中心的偏移作为诊断基础，辅助审计修正规模。"""

    generated = self.generated_planning_point_px
    if generated is None:
      generated = self.planning_point_px
    return (
      int(generated[0] - self.grid_center_px[0]),
      int(generated[1] - self.grid_center_px[1]),
    )

  @property
  def generation_offset_distance_px(self) -> float:
    """用欧式距离量化规则中心偏离量，超偏移将触发生成模式异常判断。"""

    dx, dy = self.generation_offset_from_grid_center_px
    return float(math.hypot(float(dx), float(dy)))

  @property
  def endpoint_alignment_offset_px(self) -> Tuple[int, int]:
    """记录端点对齐产生的规划点位修正量，便于追溯是否触发对齐分支。"""

    generated = self.generated_planning_point_px
    if generated is None:
      generated = self.planning_point_px
    return (
      int(self.planning_point_px[0] - generated[0]),
      int(self.planning_point_px[1] - generated[1]),
    )


@dataclass(frozen=True)
class CoverageCellGrid:
  """legacy Node 镜像前的静态 coverage-cell 网格。"""

  rows: tuple[tuple[CellCandidate, ...], ...]

  @classmethod
  def from_rows(cls, rows: Sequence[Sequence[CellCandidate]]) -> "CoverageCellGrid":
    """把可变行列表冻结为静态行网格，并校验 id 唯一。"""

    frozen_rows: list[tuple[CellCandidate, ...]] = []
    seen_ids: set[str] = set()
    for row in rows:
      frozen_row: list[CellCandidate] = []
      for cell in row:
        if not isinstance(cell, CellCandidate):
          raise AssertionError("CoverageCellGrid expects CellCandidate static source")
        cell_id = cell.stable_id
        if cell_id in seen_ids:
          raise AssertionError(f"Duplicate coverage cell id: {cell_id}")
        seen_ids.add(cell_id)
        frozen_row.append(cell)
      frozen_rows.append(tuple(frozen_row))
    return cls(rows=tuple(frozen_rows))

  def iter_cells(self) -> Iterator[CellCandidate]:
    """按行优先枚举 CellCandidate。
    
    用途：供图构建与可视化阶段遍历覆盖，保持与网格输入顺序一致，便于复现。
    """
    for row in self.rows:
      yield from row


def complete_cell_test(room_map: np.ndarray, grid_center_px: Tuple[int, int], cell_size: int) -> Tuple[bool, Tuple[int, int]]:
  """在规则网格步长内为单元格找一个稳定可用的规划点。
  
  以 grid_center_px 为首选，并且限制搜索在当前 cell 的采样窗口内，避免跨 cell 重排导致拓扑漂移。
  
  Args:
      room_map: 0 表示障碍、255 表示可通行的旋转图像栅格。
      grid_center_px: 规则网格中心点（像素坐标）。
      cell_size: 网格边长（像素），用于定义候选搜索范围。
      
  Returns:
      Tuple[bool, Tuple[int, int]]: 第一个元素表示是否找到可行点；第二个元素为修正后规划点坐标。
      找不到可行点时，返回 (False, grid_center_px) 并保留原坐标用于问题定位。
  """

  # 中心点可通行时保持不动，可减少后续路径抖动并保持局部拓扑稳定。
  x, y = grid_center_px
  if room_map[y, x] == 255:
    return True, (x, y)

  # 中心不可用时只在同一 cell 的局部窗口内回退，避免跨 cell 抢占导致拓扑错配。
  half_cell_size = cell_size // 2
  even_grid_size = (cell_size % 2) == 0
  upper_bound = half_cell_size - 1 if even_grid_size else half_cell_size
  # 越界像素视作障碍，避免把地图边缘误当成可通行空间。
  cell_pixels = np.zeros((cell_size, cell_size), dtype=np.uint8)
  src_left = max(0, x - half_cell_size)
  src_top = max(0, y - half_cell_size)
  src_right = min(room_map.shape[1], x + upper_bound + 1)
  src_bottom = min(room_map.shape[0], y + upper_bound + 1)
  if src_left < src_right and src_top < src_bottom:
    dst_left = src_left - (x - half_cell_size)
    dst_top = src_top - (y - half_cell_size)
    window = np.where(room_map[src_top:src_bottom, src_left:src_right] == 255, 255, 0).astype(np.uint8)
    cell_pixels[dst_top:dst_top + window.shape[0], dst_left:dst_left + window.shape[1]] = window

  accessible_pixels = int(np.count_nonzero(cell_pixels))

  if accessible_pixels == 0:
    return False, (x, y)

  # 选距离障碍最远点可保留更大安全裕度；等值点再选最近中心点降低位移波动。
  distances = cv2.distanceTransform(cell_pixels, cv2.DIST_L2, 5)
  max_distance = float(distances.max())
  candidate_indices = np.argwhere(distances == max_distance)
  best_point = None
  min_squared_grid_distance = float("inf")
  for row, col in candidate_indices:
    candidate = (x - half_cell_size + int(col), y - half_cell_size + int(row))
    squared_grid_distance = (candidate[0] - x) ** 2 + (candidate[1] - y) ** 2
    if squared_grid_distance < min_squared_grid_distance:
      min_squared_grid_distance = squared_grid_distance
      best_point = candidate

  return True, best_point if best_point is not None else (x, y)


def repair_regular_grid_cell(
  room_map: np.ndarray,
  grid_center_px: Tuple[int, int],
  cell_size: int,
  robot_half_width_px: float,
  max_offset_factor: float,
) -> Tuple[bool, Tuple[int, int]]:
  """在规则网格中心不可通行时做受控补点，减少拓扑抖动。
  
  与 complete_cell_test 的区别是：这里优先保持临近中心，同时保留最小清障裕量，避免补点过于激进改变转向节拍。
  
  Args:
      room_map: 0 表示障碍、255 表示可通行的旋转图像栅格。
      grid_center_px: 规则网格中心点（像素坐标）。
      cell_size: 网格边长（像素），用于限制候选边界。
      robot_half_width_px: 机器人半宽（像素），用于估计可接受的清障门槛。
      max_offset_factor: 限制修正点偏离中心的系数，避免跳出单元格节奏。
      
  Returns:
      Tuple[bool, Tuple[int, int]]: 第一个元素表示补点是否成功；第二个元素为修正点坐标。
      当单元格内无可行 free 像素时返回 (False, grid_center_px)。
  """

  x, y = grid_center_px
  if room_map[y, x] == 255:
    return True, (x, y)

  half_cell_size = cell_size // 2
  even_grid_size = (cell_size % 2) == 0
  upper_bound = half_cell_size - 1 if even_grid_size else half_cell_size
  src_left = max(0, x - half_cell_size)
  src_top = max(0, y - half_cell_size)
  src_right = min(room_map.shape[1], x + upper_bound + 1)
  src_bottom = min(room_map.shape[0], y + upper_bound + 1)
  if src_left >= src_right or src_top >= src_bottom:
    return False, (x, y)

  source_window = room_map[src_top:src_bottom, src_left:src_right]
  # floor3 area5 这类大画布裁剪后仍有大量规则中心落在全障碍 cell。
  # 先用轻量 any 早退，避免为空窗口分配二值图、argwhere 和 distanceTransform。
  if not bool(np.any(source_window == 255)):
    return False, (x, y)

  window = np.where(source_window == 255, 255, 0).astype(np.uint8)
  free_indices = np.argwhere(window == 255)
  if free_indices.size == 0:
    return False, (x, y)

  distances = cv2.distanceTransform(window, cv2.DIST_L2, 5)
  # 预过滤清障约束仅用于实验模式修正，不替代主安全判定以避免语义重叠。
  preferred_clearance = max(1.0, min(float(robot_half_width_px) * 0.5, float(cell_size) * 0.25))
  candidate_indices = free_indices[distances[free_indices[:, 0], free_indices[:, 1]] >= preferred_clearance]
  if candidate_indices.size == 0:
    candidate_indices = free_indices

  # 修复候选可能覆盖整个 cell；用向量化计算保持原评分公式与 row-major tie-break，
  # 避免在 Python 层逐像素循环拖慢线上 TurnCost 节点生成。
  rows = candidate_indices[:, 0].astype(np.int32, copy=False)
  cols = candidate_indices[:, 1].astype(np.int32, copy=False)
  candidate_x = src_left + cols
  candidate_y = src_top + rows
  dx = candidate_x - int(x)
  dy = candidate_y - int(y)
  center_distances = dx * dx + dy * dy
  max_offset_px = float(cell_size) * float(max_offset_factor)
  offset_mask = center_distances <= max_offset_px * max_offset_px
  if not bool(np.any(offset_mask)):
    return False, (x, y)
  candidate_clearances = distances[rows, cols]
  scores = center_distances.astype(np.float64) - 0.05 * candidate_clearances.astype(np.float64)
  valid_indices = np.flatnonzero(offset_mask)
  best_index = int(valid_indices[int(np.argmin(scores[valid_indices]))])
  return True, (int(candidate_x[best_index]), int(candidate_y[best_index]))


def _generation_status_for_result(
  *,
  mode: str,
  ok: bool,
  grid_center_px: Tuple[int, int],
  planning_point_px: Tuple[int, int],
) -> str:
  """统一计算生成状态码，保持不同策略在日志与统计中的可比较性。"""

  if mode == SHELF_CELL_ADJUSTED:
    # SHELF_CELL_ADJUSTED 允许本单元在邻域内修正坐标，失败会在状态里保留 adjust_failed。
    if not ok:
      return GENERATION_STATUS_CELL_ADJUST_FAILED
    # 未修正时视为中心点可用，保留 center_free 口径。
    if planning_point_px == grid_center_px:
      return GENERATION_STATUS_CENTER_FREE
    # 成功修正后标记为 cell_adjusted，供后续统计观察偏移占比。
    return GENERATION_STATUS_CELL_ADJUSTED
  if mode == TURN_COST_REGULAR_GRID:
    # regular 网格以中心点可达性为主，失败时归类到 regular_grid_blocked。
    return GENERATION_STATUS_CENTER_FREE if ok else GENERATION_STATUS_REGULAR_GRID_BLOCKED
  if mode == TURN_COST_REPAIRED_GRID:
    # repaired_grid 允许在同 cell 内修复，失败则记录 repair_failed。
    if not ok:
      return GENERATION_STATUS_REPAIR_FAILED
    # 未发生偏移表示未触发修复逻辑。
    if planning_point_px == grid_center_px:
      return GENERATION_STATUS_CENTER_FREE
    # 偏移成功说明走的是 bounded_repaired 分支。
    return GENERATION_STATUS_BOUNDED_REPAIRED
  raise AssertionError(f"unexpected node generation mode: {mode}")


def build_cell_candidates(
  inflated_rotated_room_map: np.ndarray,
  min_room: Tuple[int, int],
  max_room: Tuple[int, int],
  coverage_width_px: int,
  robot_half_width_px: float,
  *,
  node_generation_mode: str = "shelf_cell_adjusted",
  repaired_grid_max_offset_factor: float = 0.35,
  row_endpoint_alignment_enable: bool = False,
  node_obstacle_ratio_filter_enable: bool = False,
  node_obstacle_ratio_threshold: float = 0.45,
) -> CoverageCellGrid:
  """按节点生成模式批量构建覆盖候选网格并冻结为不可变结构。
  
  该过程只完成“几何生成 + 拓扑连接 + 可选校正”，不直接参与评分或路径选择。
  
  Args:
      inflated_rotated_room_map: 经过膨胀后的旋转地图（0/255 栅格）。
      min_room: 有效区域左上边界（含），供遍历起止锚点。
      max_room: 有效区域右下边界（含外扩），供遍历终止锚点。
      coverage_width_px: 覆盖步长（像素），同时决定 Cell 的采样间距。
      robot_half_width_px: 机器人半宽（像素），用于修复策略阈值计算。
      node_generation_mode: 生成策略，决定是否修复中心或允许端点对齐。
      repaired_grid_max_offset_factor: 正常网格修复时的最大偏移系数。
      row_endpoint_alignment_enable: 是否启用行内端点对齐。
      node_obstacle_ratio_filter_enable: 是否启用 obstacle ratio 过滤。
      node_obstacle_ratio_threshold: obstacle ratio 阈值，超过则标记为 obstacle。
      
  Returns:
      CoverageCellGrid: 冻结后的候选网格。其 cell 仅包含几何与状态快照，不承载运行时动态状态。
  """

  settings = NodeGenerationSettings.from_public_values(
    node_generation_mode=node_generation_mode,
    repaired_grid_max_offset_factor=repaired_grid_max_offset_factor,
    row_endpoint_alignment_enable=row_endpoint_alignment_enable,
    node_obstacle_ratio_filter_enable=node_obstacle_ratio_filter_enable,
    node_obstacle_ratio_threshold=node_obstacle_ratio_threshold,
  )

  # 覆盖宽度作为步长让节点落在规则采样网格上，便于覆盖率和 turn-cost 语义一致。
  half_coverage_width_px = int(np.floor(coverage_width_px * 0.5))
  cells: list[list[CellCandidate]] = []

  for row_index, y in enumerate(range(min_room[1] + half_coverage_width_px, max_room[1], coverage_width_px)):
    # 按行构建 cell 行缓存，后续再一次性冻结，避免被外部误改。
    row: list[CellCandidate] = []
    for col_index, x in enumerate(range(min_room[0] + half_coverage_width_px, max_room[0], coverage_width_px)):
      grid_center_px = (x, y)
      if settings.mode == TURN_COST_REGULAR_GRID:
        # TURN_COST_REGULAR_GRID 只验证规则中心是否可达，不做局部重投影，避免改变节点源头行为。
        ok = bool(inflated_rotated_room_map[y, x] == 255)
        adjusted_point_px = grid_center_px
      elif settings.mode == TURN_COST_REPAIRED_GRID:
        # TURN_COST_REPAIRED_GRID 仅当中心不可达时在同 cell 内补点，保持规则网格节拍不被大幅打断。
        ok, adjusted_point_px = repair_regular_grid_cell(
          inflated_rotated_room_map,
          grid_center_px,
          coverage_width_px,
          robot_half_width_px,
          settings.repaired_grid_max_offset_factor,
        )
      else:
        # 非预期模式说明上游配置不合法，不能静默回退到某个 fallback 行为。
        if settings.mode != SHELF_CELL_ADJUSTED:
          raise AssertionError(f"unexpected node generation mode: {settings.mode}")
        # SHELF_CELL_ADJUSTED 允许同 cell 内偏移，用于对齐贴边可通行点减少伪不可达。
        ok, adjusted_point_px = complete_cell_test(inflated_rotated_room_map, grid_center_px, coverage_width_px)
      row.append(
        CellCandidate(
          planning_point_px=adjusted_point_px,
          obstacle=not ok,
          grid_row=row_index,
          grid_col=col_index,
          grid_center_px=grid_center_px,
          generation_mode=settings.mode,
          generation_status=_generation_status_for_result(
            mode=settings.mode,
            ok=bool(ok),
            grid_center_px=grid_center_px,
            planning_point_px=adjusted_point_px,
          ),
          generated_planning_point_px=adjusted_point_px,
        )
      )
    cells.append(row)
  # 先用可变容器构建中间矩阵，后续再统一冻结。

  if settings.row_endpoint_alignment_enable:
    # 端点对齐在构建邻接前执行，保证拓扑维持一致，只改 planning_point。
    _align_grid_segments_to_free_endpoints(
      inflated_rotated_room_map,
      cells,
      coverage_width_px,
      robot_half_width_px,
    )

  if settings.node_obstacle_ratio_filter_enable:
    # 过滤放在邻接后执行，可保留拓扑主干后再裁剪可行性。
    # obstacle ratio 过滤放在邻接后，避免在生成阶段就失去拓扑结构上下文。
    _filter_nodes_by_obstacle_ratio(
      inflated_rotated_room_map,
      cells,
      robot_width_px=float(robot_half_width_px) * 2.0,
      threshold=settings.node_obstacle_ratio_threshold,
    )

  _connect_grid_neighbors(cells)

  return CoverageCellGrid.from_rows(cells)


def build_legacy_node_matrix(cell_grid: CoverageCellGrid) -> list[list[Node]]:
  """基于静态候选格构建 legacy Node 镜像二维矩阵。"""

  node_rows: list[list[Node]] = []
  nodes_by_id: dict[str, Node] = {}
  for row in cell_grid.rows:
    node_row: list[Node] = []
    for cell in row:
      # 仅保留 planning/状态快照，不直接沿用 CellCandidate 引用。
      node = Node(
        planning_point_px=(int(cell.planning_point_px[0]), int(cell.planning_point_px[1])),
        obstacle=bool(cell.obstacle),
        grid_row=int(cell.grid_row),
        grid_col=int(cell.grid_col),
        grid_center_px=(int(cell.grid_center_px[0]), int(cell.grid_center_px[1])),
        obstacle_ratio=None if cell.obstacle_ratio is None else float(cell.obstacle_ratio),
        obstacle_ratio_filtered=bool(cell.obstacle_ratio_filtered),
      )
      nodes_by_id[node.stable_id] = node
      node_row.append(node)
    node_rows.append(node_row)

  for row, node_row in zip(cell_grid.rows, node_rows):
    for cell, node in zip(row, node_row):
      # 只通过 stable_id 还原邻接，避免直接复用列表索引导致引用到过期对象。
      node.neighbors = [nodes_by_id[neighbor.stable_id] for neighbor in cell.neighbors]
  return node_rows


def build_coverage_graph(cell_grid: CoverageCellGrid) -> CoverageGraphView:
  """把静态覆盖格网转换为只读覆盖图视图。"""

  if not isinstance(cell_grid, CoverageCellGrid):
    raise AssertionError("build_coverage_graph expects CoverageCellGrid static source")
  return build_coverage_graph_view_from_cell_rows(cell_grid.rows)
