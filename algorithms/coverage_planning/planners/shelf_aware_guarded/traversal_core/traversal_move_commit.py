"""应用已选遍历动作。

该模块负责候选确认后的确定性写入行为，不参与候选选择、不修改评分与回退策略。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .traversal_candidate_summary import CandidatePhaseSelection
from .traversal_cursor import TraversalCursor
from .traversal_graph_access import TraversalGraphAccess
from .traversal_move import TraversalMove
from .traversal_roles import edge_role_for_move_source
from .traversal_state import TraversalState


@dataclass(frozen=True)
class CommittedTraversalMove:
  """单次提交后返回的确定性移动快照，承载下游 trace 与定位信息。"""
  next_cursor: TraversalCursor
  heading_rad: float
  trace_item: dict[str, Any]


def commit_selected_traversal_move(
  *,
  last_cursor: TraversalCursor,
  next_selection: CandidatePhaseSelection,
  fov_coverage_path: list[tuple[float, float]],
  move_trace: list[dict[str, Any]],
  traversal_state: TraversalState,
  graph_access: TraversalGraphAccess,
  previous_travel_angle: float,
  step_counter: int,
  local_residual_count: int,
) -> CommittedTraversalMove:
  """将选中的候选写入 traversal_state 并生成 trace 片段。

  副作用：
    - 推进 cursor 与 traversal_state 路径
    - 追加一次 trace 条目
    - 不更改候选评分策略
  """
  if not next_selection.has_selection or next_selection.selected_cell_id is None:
    # 未命中候选却进入 commit 代表上游流程失序，提前失败避免写入污染状态。
    raise AssertionError("Cannot commit an empty traversal selection")
  last_cursor.assert_matches_state(traversal_state)

  # commit 阶段只做确定性状态前移，不参与任何候选打分逻辑。
  from_cell_id = str(last_cursor.cell_id)
  next_cell_id = str(next_selection.selected_cell_id)
  next_cursor = TraversalCursor.from_cell_id(next_cell_id)
  from_point_px = graph_access.planning_point_px_for_cell(from_cell_id)
  to_point_px = graph_access.planning_point_px_for_cell(next_cell_id)
  from_point = (float(from_point_px[0]), float(from_point_px[1]))
  to_point = (float(to_point_px[0]), float(to_point_px[1]))
  current_travel_angle = math.atan2(
    to_point[1] - from_point[1],
    to_point[0] - from_point[0],
  )
  fov_coverage_path.append(to_point)

  move_source = str(next_selection.move_source or "unknown")
  edge_role = edge_role_for_move_source(move_source)
  was_first_visit = not traversal_state.is_visited_cell(next_cell_id)
  next_visit_count = traversal_state.visit_count_for_cell(next_cell_id) + 1
  traversal_state.record_move(
    to_cell_id=next_cell_id,
    heading_rad=current_travel_angle,
    was_first_visit=was_first_visit,
    visit_count=next_visit_count,
  )
  if len(traversal_state.path_cell_ids) != len(fov_coverage_path):
    # 路径与路径点数应严格一致，偏离说明点转换或状态记录口径错位。
    raise AssertionError("TraversalState path length diverged from emitted path")

  trace_item = TraversalMove.from_legacy_step(
    path_index=len(fov_coverage_path),
    step_index=step_counter,
    move_source=move_source,
    edge_role=edge_role,
    from_node_id=from_cell_id,
    to_node_id=next_cell_id,
    from_point_rotated_px=from_point,
    to_point_rotated_px=to_point,
    selected_energy=float(next_selection.selected_energy),
    local_residual_count=int(local_residual_count),
    revisit_frontier_score=int(next_selection.revisit_frontier_score),
    heading_rad=current_travel_angle,
    previous_heading_rad=previous_travel_angle,
    phase_candidate_count=next_selection.phase_summary.candidate_count,
    phase_energy_evaluated_candidate_count=next_selection.phase_summary.energy_evaluated_candidate_count,
    phase_accepted_candidate_count=next_selection.phase_summary.accepted_candidate_count,
    phase_rejected_before_energy_count=next_selection.phase_summary.rejected_before_energy_count,
    phase_candidate_rank=next_selection.phase_summary.candidate_rank,
  ).to_trace_item()
  move_trace.append(trace_item)

  return CommittedTraversalMove(
    next_cursor=next_cursor,
    heading_rad=current_travel_angle,
    trace_item=trace_item,
  )
