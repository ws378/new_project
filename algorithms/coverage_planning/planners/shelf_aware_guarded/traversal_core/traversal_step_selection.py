"""单步遍历候选选择。

按单步阶段顺序处理：优先 normal neighbor，其次可选 revisit bridge，最后 global fallback。
本模块不提交动作、不改写路径、不直接写入 legacy 镜像。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..models import PlannerConfig
from .traversal_candidate_summary import CandidatePhaseSelection
from .traversal_cursor import TraversalCursor
from .traversal_history_clearance import build_history_clearance_index
from .traversal_phase_selectors import (
  select_global_fallback_phase,
  select_normal_neighbor_phase,
  select_revisit_bridge_phase,
)
from .traversal_phase_query import build_traversal_phase_query_context
from .traversal_reachability import count_local_unvisited_nodes
from .traversal_graph_access import TraversalGraphAccess
from .traversal_roles import (
  MOVE_SOURCE_GLOBAL_FALLBACK,
  MOVE_SOURCE_NORMAL_NEIGHBOR,
  MOVE_SOURCE_REVISIT_BRIDGE,
)
from .traversal_scoring_context import build_traversal_scoring_context
from .traversal_state import TraversalState


@dataclass(frozen=True)
class TraversalStepDecision:
  """单步遍历决策结果。
  
  包含最终选择、尝试序列与 fallback 事件，供决策链路审计。
  """
  selection: CandidatePhaseSelection
  attempted_phase_selections: tuple[tuple[str, CandidatePhaseSelection], ...]
  fallback_debug_event: dict[str, Any] | None
  local_residual_count: int


@dataclass(frozen=True)
class TraversalStepContext:
  """单步选择上下文。
  
  聚合路径、状态与索引，避免参数在调用链内重复透传。
  """
  fov_coverage_path: list[tuple[float, float]]
  previous_travel_angle: float
  traversal_state: TraversalState
  graph_access: TraversalGraphAccess
  history_clearance_index: Any
  coverage_width_px: int
  config: PlannerConfig
  map_resolution: float
  local_direction_map: np.ndarray
  local_direction_confidence: np.ndarray
  edge_label_map: np.ndarray | None
  step_counter: int


def make_history_clearance_index(coverage_width_px: int, config: PlannerConfig):
  """创建用于步骤决策的历史贴近索引。

  先用空路径构建基础实例，后续按当前遍历路径同步。
  """
  return build_history_clearance_index((), coverage_width_px, config.strategy)


def sync_history_clearance_index(
  *,
  history_clearance_index: Any,
  fov_coverage_path: list[tuple[float, float]],
  traversal_state: TraversalState,
):
  """按当前状态同步历史贴近索引。
  
  返回可用索引或 None，fallback 阶段统一消费。
  """
  if history_clearance_index is None:
    return None
  # 排除最新路径尾段，避免全局 fallback 评分时把局部连续移动误判成历史重复。
  target_size = max(0, len(fov_coverage_path) - 12)
  while traversal_state.history_clearance_index_size < target_size:
    # 只追加新增长度部分，避免每次 fallback 重建历史索引。
    history_clearance_index.add_point(fov_coverage_path[traversal_state.history_clearance_index_size])
    traversal_state.advance_history_clearance_index_size()
  return history_clearance_index


def select_next_traversal_candidate(
  *,
  cursor: TraversalCursor,
  context: TraversalStepContext,
) -> TraversalStepDecision:
  """在不提交动作的前提下选择下一步遍历候选。

  保留原有 fallback 分支对 history_clearance 索引的同步时机：只有在
  normal/revisit 阶段失效后、执行 global fallback 打分前才推进索引。
  函数本身不写入路径点，也不回写 legacy node 镜像。
  """
  cursor.assert_matches_state(context.traversal_state)
  # 校验 state 与 cursor 对齐后再计算候选，避免在重放/重试场景下读取错位邻接关系。

  query_context = build_traversal_phase_query_context(
    traversal_state=context.traversal_state,
    graph_access=context.graph_access,
    strategy=context.config.strategy,
  )
  # 所有 phase 都在同一份 query_context 上执行，确保候选可比性与回放一致性。
  # 第一优先级：直接走未访问的邻接节点，保持路径连续。
  not_visited_neighbors = query_context.normal_neighbor_candidates(cursor.cell_id)
  # local_residual_count 表示当前位置附近剩余未访问节点，用于抑制过早离开局部区域。
  local_residual_count = count_local_unvisited_nodes(
    cursor.cell_id,
    context.config.strategy.local_residual_radius_steps,
    traversal_state=context.traversal_state,
    graph_access=context.graph_access,
  )
  scoring_context = build_traversal_scoring_context(
    point_path=context.fov_coverage_path,
    coverage_width_px=context.coverage_width_px,
    previous_travel_angle=context.previous_travel_angle,
    map_resolution=context.map_resolution,
    config=context.config,
    local_direction_map=context.local_direction_map,
    local_direction_confidence=context.local_direction_confidence,
    edge_label_map=context.edge_label_map,
    local_residual_count=local_residual_count,
  )
  # 用同一套 scoring_context 复用参数，避免 phase 切换引入隐式权重漂移。
  next_selection = select_normal_neighbor_phase(
    last_cell_id=cursor.cell_id,
    not_visited_neighbors=not_visited_neighbors,
    query_context=query_context,
    context=scoring_context,
  )
  attempted_phase_selections: list[tuple[str, CandidatePhaseSelection]] = [
    (MOVE_SOURCE_NORMAL_NEIGHBOR, next_selection),
  ]

  if not next_selection.has_selection and context.config.strategy.allow_revisit_bridge:
    # 当 normal 邻接失效时，允许一次可控“重复访问桥接”，目的是连回 frontier 并减少无谓大跳。
    next_selection = select_revisit_bridge_phase(
      last_cell_id=cursor.cell_id,
      query_context=query_context,
      context=scoring_context,
    )
    attempted_phase_selections.append((MOVE_SOURCE_REVISIT_BRIDGE, next_selection))

  fallback_debug_event: dict[str, Any] | None = None
  if not next_selection.has_selection:
    # 只有在邻接与桥接都无解时才触发全局 fallback，避免过早离开局部区域导致路径抖动。
    current_history_clearance_index = sync_history_clearance_index(
      history_clearance_index=context.history_clearance_index,
      fov_coverage_path=context.fov_coverage_path,
      traversal_state=context.traversal_state,
    )
    fallback_context = build_traversal_scoring_context(
      point_path=context.fov_coverage_path,
      coverage_width_px=context.coverage_width_px,
      previous_travel_angle=context.previous_travel_angle,
      map_resolution=context.map_resolution,
      config=context.config,
      local_direction_map=context.local_direction_map,
      local_direction_confidence=context.local_direction_confidence,
      edge_label_map=context.edge_label_map,
      local_residual_count=local_residual_count,
      history_clearance_index=current_history_clearance_index,
    )
    fallback_result = select_global_fallback_phase(
      last_cell_id=cursor.cell_id,
      query_context=query_context,
      context=fallback_context,
      step_counter=context.step_counter,
      write_artifacts=context.config.write_artifacts,
    )
    next_selection = fallback_result.selection
    attempted_phase_selections.append((MOVE_SOURCE_GLOBAL_FALLBACK, next_selection))
    fallback_debug_event = fallback_result.debug_event

  return TraversalStepDecision(
    selection=next_selection,
    attempted_phase_selections=tuple(attempted_phase_selections),
    fallback_debug_event=fallback_debug_event,
    local_residual_count=local_residual_count,
  )
