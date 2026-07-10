"""遍历调试载荷构建工具。

从图与 traversal state 快照生成 artifact 级诊断，不写盘，不参与算法决策。
"""

from __future__ import annotations

from typing import Any


def _cell_is_visited(cell_id: str, *, traversal_state: Any) -> bool:
  """读取 traversal_state 的访问标记，避免直接依赖节点镜像字段。"""
  # 通过 traversal_state 而非节点镜像读取访问状态，避免旧对象字段污染。
  return bool(traversal_state.is_visited_cell(cell_id))


def _cell_visit_count(cell_id: str, *, traversal_state: Any) -> int:
  """读取 traversal_state 的访问计数，保证与当前 run 的决策口径一致。"""
  # 访问次数从动态状态拿，保证与本轮 run 的实际决策同步。
  return int(traversal_state.visit_count_for_cell(cell_id))


def node_debug_payload(
  cell_id: str,
  *,
  include_neighbors: bool = False,
  traversal_state: Any,
  graph_access: Any,
) -> dict[str, Any]:
  """生成单个节点的调试负载，用于 artifact 与诊断回放。

  返回值仅用于追踪，不驱动策略判定。
  """
  cell = graph_access.cell(str(cell_id))
  node_id = str(cell.cell_id)
  grid_row = int(cell.grid_row)
  grid_col = int(cell.grid_col)
  planning_point_px = (int(cell.planning_point_px[0]), int(cell.planning_point_px[1]))
  grid_center_px = (int(cell.grid_center_px[0]), int(cell.grid_center_px[1]))
  adjusted_from_grid_center_px = bool(cell.adjusted_from_grid_center_px)
  generated_planning_point_px = (
    int(cell.generated_planning_point_px[0]),
    int(cell.generated_planning_point_px[1]),
  )
  generation_offset_from_grid_center_px = (
    int(cell.generation_offset_from_grid_center_px[0]),
    int(cell.generation_offset_from_grid_center_px[1]),
  )
  generation_offset_distance_px = float(cell.generation_offset_distance_px)
  generation_mode = str(cell.generation_mode)
  generation_status = str(cell.generation_status)
  endpoint_alignment_applied = bool(cell.endpoint_alignment_applied)
  endpoint_alignment_offset_px = (
    int(cell.endpoint_alignment_offset_px[0]),
    int(cell.endpoint_alignment_offset_px[1]),
  )
  obstacle = bool(cell.obstacle)
  obstacle_ratio = float(cell.obstacle_ratio) if cell.obstacle_ratio is not None else None
  obstacle_ratio_filtered = bool(cell.obstacle_ratio_filtered)
  non_obstacle_neighbor_count = int(len(cell.accessible_neighbor_cell_ids))
  obstacle_neighbor_count = int(len(cell.neighbor_cell_ids) - len(cell.accessible_neighbor_cell_ids))
  neighbor_ids = list(cell.accessible_neighbor_cell_ids)
  payload = {
    "node_id": node_id,
    "grid_row": grid_row,
    "grid_col": grid_col,
    "planning_point_px_rotated": [planning_point_px[0], planning_point_px[1]],
    "grid_center_px_rotated": [grid_center_px[0], grid_center_px[1]],
    "adjusted_from_grid_center_px": adjusted_from_grid_center_px,
    "generated_planning_point_px_rotated": [generated_planning_point_px[0], generated_planning_point_px[1]],
    "generation_offset_from_grid_center_px": [
      generation_offset_from_grid_center_px[0],
      generation_offset_from_grid_center_px[1],
    ],
    "generation_offset_distance_px": generation_offset_distance_px,
    "generation_mode": generation_mode,
    "generation_status": generation_status,
    "endpoint_alignment_applied": endpoint_alignment_applied,
    "endpoint_alignment_offset_px": [
      endpoint_alignment_offset_px[0],
      endpoint_alignment_offset_px[1],
    ],
    "obstacle": obstacle,
    "visited": _cell_is_visited(node_id, traversal_state=traversal_state),
    "visit_count": _cell_visit_count(node_id, traversal_state=traversal_state),
    "obstacle_ratio": obstacle_ratio,
    "obstacle_ratio_filtered": obstacle_ratio_filtered,
    "non_obstacle_neighbor_count": non_obstacle_neighbor_count,
    "obstacle_neighbor_count": obstacle_neighbor_count,
  }
  if include_neighbors:
    # 调试层按需附加邻接关系，避免默认 payload 过大影响传输和归档体积。
    payload["neighbor_ids"] = neighbor_ids
  return payload


def collect_unvisited_node_ids(*, traversal_state: Any, graph_access: Any) -> list[str]:
  """返回当前遍历状态下可达且未访问节点 id 列表，供外部一致复用。"""
  # 统一从 graph_access 获取未访问节点，避免上层重复实现各自定义“未访问”口径。
  return graph_access.unvisited_accessible_cell_ids(traversal_state)


def candidate_debug_payload(
  cell_id: str,
  energy: float,
  *,
  traversal_state: Any,
  graph_access: Any,
) -> dict[str, Any]:
  """构建候选节点诊断负载，附带 energy 便于 fallback/selection 回放。"""
  # 同一候选的候选评分需要附带节点状态，方便后续按能量排序回溯。
  payload = node_debug_payload(
    str(cell_id),
    traversal_state=traversal_state,
    graph_access=graph_access,
  )
  payload["energy"] = float(energy)
  return payload
