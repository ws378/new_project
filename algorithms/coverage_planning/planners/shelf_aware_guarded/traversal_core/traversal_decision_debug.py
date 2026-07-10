"""遍历决策调试载荷。

只序列化已评估好的阶段选择结果，不做候选枚举、评分或动作决策。
"""

from __future__ import annotations

from typing import Any, Sequence

from .traversal_candidate_summary import (
  CandidateEvaluationRecord,
  CandidatePhaseSelection,
  CandidatePhaseSummary,
)


def candidate_evaluation_record_payload(record: CandidateEvaluationRecord) -> dict[str, Any]:
  """导出单条候选评分记录的 artifact 字段，保持脚本可直接消费。"""
  # 保留原始字段名与类型，减少跨版本复盘脚本对兼容路径的假设。
  return {
    "cell_id": record.cell_id,
    "move_source": record.move_source,
    "accepted": bool(record.accepted),
    "total_energy": record.total_energy,
    "score_components": {
      str(key): float(value)
      for key, value in record.score_components
    },
    "score_component_sum_valid": bool(record.score_component_sum_valid),
    "rejected_reasons": list(record.rejected_reasons),
    "rejected_before_energy": bool(record.rejected_before_energy),
    "rank_in_phase": record.rank_in_phase,
  }


def candidate_phase_summary_payload(summary: CandidatePhaseSummary) -> dict[str, int]:
  """将候选阶段统计转为统一字典。
  
  字段名保持稳定，支持离线分析脚本无需按阶段结构分支。
  
  Args:
      summary: 阶段汇总对象。
  
  Returns:
      dict[str, int]: 统一字段统计字典。
  """
  return {
    "candidate_count": int(summary.candidate_count),
    "energy_evaluated_candidate_count": int(summary.energy_evaluated_candidate_count),
    "accepted_candidate_count": int(summary.accepted_candidate_count),
    "rejected_before_energy_count": int(summary.rejected_before_energy_count),
    "candidate_rank": int(summary.candidate_rank),
  }


def phase_selection_debug_payload(
  *,
  phase_name: str,
  selection: CandidatePhaseSelection,
  selected_cell_id: str | None,
) -> dict[str, Any]:
  """构造阶段选择的调试 payload。
  
  记录阶段名、候选来源与未选信息，便于复盘决策失败路径。
  
  Args:
      phase_name: 阶段名。
      selection: 阶段选择结果。
      selected_cell_id: 阶段最终选择的 cell id。
  
  Returns:
      dict[str, Any]: 阶段级调试信息。
  """
  return {
    "phase_name": str(phase_name),
    "has_selection": bool(selection.has_selection),
    "selected_cell_id": selected_cell_id,
    "selected_energy": None if not selection.has_selection else float(selection.selected_energy),
    "phase_summary": candidate_phase_summary_payload(selection.phase_summary),
    "candidate_records": [
      candidate_evaluation_record_payload(record)
      for record in selection.candidate_records
    ],
  }


def traversal_decision_event_payload(
  *,
  step_counter: int,
  path_index_before_selection: int,
  current_cell_id: str,
  local_residual_count: int,
  phase_selections: Sequence[tuple[str, CandidatePhaseSelection, str | None]],
  final_selection: CandidatePhaseSelection,
  final_selected_cell_id: str | None,
  selected_move_id: str | None = None,
) -> dict[str, Any]:
  """构造一次遍历决策事件的结构化记录。
  
  包含 step、路径索引与最终选择，用于 fallback 复盘。
  
  Args:
      step_counter: 当前步数。
      path_index_before_selection: 选择前路径索引。
      current_cell_id: 当前 cell。
      local_residual_count: 局部残量。
      phase_selections: 各阶段选择序列。
      final_selection: 最终选择。
      final_selected_cell_id: 最终落点。
      selected_move_id: 可选运动 id。
  
  Returns:
      dict[str, Any]: 可序列化的决策事件。
  """
  return {
    "step": int(step_counter),
    "path_index_before_selection": int(path_index_before_selection),
    "current_cell_id": str(current_cell_id),
    "local_residual_count": int(local_residual_count),
    "selected_phase": final_selection.move_source if final_selection.has_selection else None,
    "selected_cell_id": final_selected_cell_id,
    "selected_move_id": selected_move_id,
    "selected_energy": None if not final_selection.has_selection else float(final_selection.selected_energy),
    "phases": [
      phase_selection_debug_payload(
        phase_name=phase_name,
        selection=selection,
        selected_cell_id=selected_cell_id,
      )
      for phase_name, selection, selected_cell_id in phase_selections
    ],
  }
