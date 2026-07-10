"""遍历候选源枚举模块。

按 ``TraversalState`` 的动态访问信息扫描候选项，保持原 traversal_loop 的候选顺序，
不负责评分、不负责淘汰、不负责状态变更。
"""

from __future__ import annotations

from .traversal_candidate_ref import TraversalCandidateRef


def _candidate_ref(cell_id: str) -> TraversalCandidateRef:
  """把 cell id 统一转换为可复用的候选引用对象。"""
  return TraversalCandidateRef.from_cell_id(cell_id)


def list_normal_neighbor_candidates(
  last_cell_id: str,
  *,
  traversal_state,
  graph_access,
) -> list[TraversalCandidateRef]:
  """列举未访问的邻接候选。
  
  仅包含未访问邻接节点，维持局部覆盖优先策略，避免提前回溯导致清扫被打断。
  
  Args:
      last_cell_id: 当前所在 cell。
      traversal_state: 遍历状态。
      graph_access: 图访问器。

  Returns:
      list[TraversalCandidateRef]: 邻接未访问候选列表。
  """
  return [
    _candidate_ref(neighbor_cell_id)
    for neighbor_cell_id in graph_access.accessible_neighbor_cell_ids(last_cell_id)
    if not traversal_state.is_visited_cell(neighbor_cell_id)
  ]


def list_revisit_bridge_candidates(
  last_cell_id: str,
  *,
  traversal_state,
  graph_access,
  max_revisit_count: int,
) -> list[TraversalCandidateRef]:
  """列举有限次 revisit 桥接候选。
  
  在局部受阻时允许少量重复访问来突破死角并接回 frontier。
  
  Args:
      last_cell_id: 当前所在 cell。
      traversal_state: 遍历状态。
      graph_access: 图访问器。
      max_revisit_count: 可复用重复访问的上限。
      
  Returns:
      list[TraversalCandidateRef]: 限制访问次数后的桥接候选。
  """
  return [
    _candidate_ref(neighbor_cell_id)
    for neighbor_cell_id in graph_access.accessible_neighbor_cell_ids(last_cell_id)
    if traversal_state.visit_count_for_cell(neighbor_cell_id) < max_revisit_count
  ]


def list_global_fallback_candidates(
  *,
  traversal_state,
  graph_access,
) -> list[TraversalCandidateRef]:
  """列举全局 fallback 候选。
  
  当局部和 bridge 不足时，退回未访问集合搜索可达桥接。
  
  Args:
      traversal_state: 遍历状态。
      graph_access: 图访问器。
      
  Returns:
      list[TraversalCandidateRef]: 全局未访问可达候选列表。
  """
  return [
    _candidate_ref(cell_id)
    for cell_id in graph_access.unvisited_accessible_cell_ids(traversal_state)
  ]
