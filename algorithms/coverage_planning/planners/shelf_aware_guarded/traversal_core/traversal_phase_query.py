"""遍历阶段选择器的查询上下文（只读）。"""

from __future__ import annotations

from dataclasses import dataclass

from .traversal_candidate_enumeration import (
  list_global_fallback_candidates,
  list_normal_neighbor_candidates,
  list_revisit_bridge_candidates,
)
from ..models import StrategyConfig
from .traversal_graph_access import TraversalGraphAccess
from .traversal_reachability import count_frontier_reachability, count_local_unvisited_nodes
from .traversal_state import TraversalState


@dataclass(frozen=True)
class TraversalPhaseQueryContext:
  """阶段查询上下文（只读）：冻结状态后给阶段选择提供统一数据入口。"""
  traversal_state: TraversalState
  graph_access: TraversalGraphAccess
  max_revisit_count: int
  revisit_frontier_depth: int
  local_residual_radius_steps: int
  local_residual_continue_weight: float

  def normal_neighbor_candidates(self, last_cell_id: str):
    """查询 normal 阶段候选列表，保持 stage 内查询口径固定。"""
    # normal 阶段只看当前可达邻接，保证阶段切换前后查询语义一致。
    return list_normal_neighbor_candidates(
      last_cell_id,
      traversal_state=self.traversal_state,
      graph_access=self.graph_access,
    )

  def revisit_bridge_candidates(self, last_cell_id: str):
    """查询 revisit 阶段候选，并按最大复用次数约束过滤。"""
    # revisit 阶段在可复用次数限制内选候选，避免重复回退失控。
    return list_revisit_bridge_candidates(
      last_cell_id,
      traversal_state=self.traversal_state,
      graph_access=self.graph_access,
      max_revisit_count=self.max_revisit_count,
    )

  def global_fallback_candidates(self):
    """查询全局 fallback 的候选集合，作为局部阶段失败后的兜底输入。"""
    # global fallback 查询整个未访问集合，用于从局部卡住时做全局跳转。
    return list_global_fallback_candidates(
      traversal_state=self.traversal_state,
      graph_access=self.graph_access,
    )

  def unvisited_accessible_cell_ids(self) -> list[str]:
    """返回可达且当前未访问的 cell，用于调试和全局 fallback 统计。"""
    # 不排除不可达残留时会把全局 fallback 变成“伪可达”目标，放大无效回跳。
    return self.graph_access.unvisited_accessible_cell_ids(self.traversal_state)

  def visit_count_for_cell(self, cell_id: str) -> int:
    """返回 cell 的历史访问次数，作为 revisit 约束的计数依据。"""
    return int(self.traversal_state.visit_count_for_cell(cell_id))

  def revisit_frontier_score(self, cell_id: str) -> int:
    """计算 cell 的 frontier 分数，低于 1 的候选不具备重新连接价值。"""
    # frontier 打分用于判断候选是否能接回未覆盖区域，过滤无意义 revisit。
    return count_frontier_reachability(
      cell_id,
      self.revisit_frontier_depth,
      traversal_state=self.traversal_state,
      graph_access=self.graph_access,
    )

  def candidate_local_residual_count(self, cell_id: str) -> int:
    """返回局部未访问计数；当配置关闭时固定返回 0，避免引入额外偏置。"""
    if self.local_residual_continue_weight <= 0.0:
      # 残留约束关闭时返回 0，便于上层保持统一接口。
      return 0
    # 局部残留统计默认可关闭，关闭时不引入额外偏置。
    return count_local_unvisited_nodes(
      cell_id,
      self.local_residual_radius_steps,
      traversal_state=self.traversal_state,
      graph_access=self.graph_access,
    )


def build_traversal_phase_query_context(
  *,
  traversal_state: TraversalState,
  graph_access: TraversalGraphAccess,
  strategy: StrategyConfig,
) -> TraversalPhaseQueryContext:
  """将 strategy 配置与运行状态组装为只读查询上下文。

  返回的上下文供本轮 traversals 全部阶段复用，避免不同阶段读取不同配置。
  """
  # 将 strategy 配置归一为 query_context，后续所有 phase 都基于同一快照减少行为漂移。
  return TraversalPhaseQueryContext(
    traversal_state=traversal_state,
    graph_access=graph_access,
    max_revisit_count=int(strategy.max_revisit_count),
    revisit_frontier_depth=int(strategy.revisit_frontier_depth),
    local_residual_radius_steps=int(strategy.local_residual_radius_steps),
    local_residual_continue_weight=float(strategy.local_residual_continue_weight),
  )
