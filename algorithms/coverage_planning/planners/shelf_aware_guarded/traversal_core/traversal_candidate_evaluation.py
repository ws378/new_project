"""遍历候选评分评估桥接模块。"""

from __future__ import annotations

from typing import Any

from .candidate_scoring import (
  CandidateScoreBreakdown,
  CandidateScoringContext,
  CandidateScoringGeometry,
  evaluate_candidate_score_for_geometry,
)
from .traversal_candidate_ref import TraversalCandidateRef
from .traversal_candidate_summary import CandidateEvaluationRecord
from .traversal_scoring_context import TraversalScoringContext


def score_candidate_for_selection(
  *,
  last_cell_id: str,
  candidate_ref: TraversalCandidateRef,
  graph_access: Any,
  context: TraversalScoringContext,
  is_global_fallback: bool,
  candidate_visit_count: int,
  candidate_local_residual_count: int,
  revisit_frontier_score: int = 0,
) -> CandidateScoreBreakdown:
  """对单个候选执行评分并返回原始评分结果。
  
  线上规划只需要 accepted/energy 来做选择；完整 `CandidateEvaluationRecord`
  只在 artifact 诊断打开时构造，避免主循环为不可见审计数据付出对象和排序成本。
  
  Args:
      last_cell_id: 当前游标所在 cell。
      candidate_ref: 待评估候选。
      graph_access: graph 访问器。
      context: 评分上下文（包含配置与路径）。
      is_global_fallback: 是否全局 fallback 分支。
      candidate_visit_count: 候选历史访问次数。
      candidate_local_residual_count: 候选相关局部残量。
      revisit_frontier_score: frontier 接近程度分。
      
  Returns:
      CandidateScoreBreakdown: 包含 accept/reject、能量分项和拒绝原因。
  """
  return evaluate_candidate_score_for_geometry(
    CandidateScoringGeometry.from_points(
      graph_access.planning_point_px_for_cell(last_cell_id),
      graph_access.planning_point_px_for_cell(candidate_ref.cell_id),
    ),
    context=CandidateScoringContext(
      point_path=context.point_path,
      coverage_width_px=context.coverage_width_px,
      previous_travel_angle=context.previous_travel_angle,
      map_resolution=context.map_resolution,
      is_global_fallback=is_global_fallback,
      turn_constraint=context.config.turn_constraint,
      local_direction_map=context.local_direction_map,
      local_direction_confidence=context.local_direction_confidence,
      local_direction_cfg=context.config.local_direction,
      edge_label_map=context.edge_label_map,
      ctg_guidance_cfg=context.config.ctg_guidance,
      strategy_cfg=context.config.strategy,
      local_residual_count=context.local_residual_count,
      history_clearance_index=context.history_clearance_index,
    ),
    candidate_local_residual_count=candidate_local_residual_count,
    candidate_visit_count=candidate_visit_count,
    revisit_frontier_score=revisit_frontier_score,
  )


def evaluate_candidate_for_selection(
  *,
  last_cell_id: str,
  candidate_ref: TraversalCandidateRef,
  graph_access: Any,
  context: TraversalScoringContext,
  move_source: str,
  is_global_fallback: bool,
  candidate_visit_count: int,
  candidate_local_residual_count: int,
  revisit_frontier_score: int = 0,
) -> CandidateEvaluationRecord:
  """对单个候选执行评分并返回完整审计记录。"""
  score = score_candidate_for_selection(
    last_cell_id=last_cell_id,
    candidate_ref=candidate_ref,
    graph_access=graph_access,
    context=context,
    is_global_fallback=is_global_fallback,
    candidate_visit_count=candidate_visit_count,
    candidate_local_residual_count=candidate_local_residual_count,
    revisit_frontier_score=revisit_frontier_score,
  )
  return CandidateEvaluationRecord.from_energy_result(
    cell_id=candidate_ref.cell_id,
    move_source=move_source,
    accepted=score.accepted,
    total_energy=score.total_energy,
    score_components=score.components,
    score_component_sum_valid=score.component_sum_valid,
    rejected_reasons=score.rejected_reasons,
  )
