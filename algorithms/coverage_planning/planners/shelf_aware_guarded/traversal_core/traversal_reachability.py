"""遍历可达性查询。

该模块在静态覆盖图与动态遍历状态上做可达性统计，不做评分，不改写遍历状态。
"""

from __future__ import annotations


def count_frontier_reachability(start_cell_id: str, max_depth: int, *, traversal_state, graph_access) -> int:
  """统计从起点在限定深度内可达且未访问 frontier 的数量。

  用于给 revisit 候选提供“接回未覆盖区域”的强制门槛。

  Args:
    start_cell_id: 起点格子 id
    max_depth: BFS 深度上界
    traversal_state: 当前遍历状态
    graph_access: 覆盖图访问适配层

  Returns:
    可达 frontier 未访问节点数。
  """
  # 深度上界 <= 0 不形成搜索，避免把空约束误判成可达 frontier 为 0。
  # revisit bridge 候选必须能通向未访问 frontier，否则只是无意义重复访问。
  if max_depth <= 0:
    return 0
  seen = {str(start_cell_id)}
  frontier = [(str(start_cell_id), 0)]
  score = 0
  while frontier:
    current_cell_id, depth = frontier.pop(0)
    # 达到深度上界后不再向外扩张，但当前节点前置贡献已在入队时保持。
    if depth >= max_depth:
      continue
    for neighbor_cell_id in graph_access.accessible_neighbor_cell_ids(current_cell_id):
      # 已出现节点不再重复入队，防止环路在 frontier 中无限扩散。
      if neighbor_cell_id in seen:
        continue
      seen.add(neighbor_cell_id)
      # 只统计未访问 frontier，访问过的节点保留为通路权重，但不贡献 frontier 计数。
      if not traversal_state.is_visited_cell(neighbor_cell_id):
        # score 只统计尚未访问节点，已访问节点只作为桥接通路。
        score += 1
      frontier.append((neighbor_cell_id, depth + 1))
  return score


def count_local_unvisited_nodes(start_cell_id: str, max_depth: int, *, traversal_state, graph_access) -> int:
  """统计起点附近在给定深度内的未覆盖节点数量。

  该值用于给阶段评分增加局部保留约束，避免过早走向全局 fallback。

  Args:
    start_cell_id: 起点格子 id
    max_depth: BFS 深度上界
    traversal_state: 当前遍历状态
    graph_access: 覆盖图访问适配层

  Returns:
    指定范围内尚未访问格子数。
  """
  # 当半径参数关闭时返回 0，保持配置关闭时不引入额外偏置。
  # 用 BFS 估算当前位置附近还剩多少未覆盖节点，帮助策略避免过早 fallback 离开。
  if max_depth <= 0:
    return 0
  seen = {str(start_cell_id)}
  frontier = [(str(start_cell_id), 0)]
  score = 0
  while frontier:
    current_cell_id, depth = frontier.pop(0)
    # 深度大于 0 的节点若未访问，视作局部残留未覆盖，作为 stay 策略依据。
    if depth > 0 and not traversal_state.is_visited_cell(current_cell_id):
      score += 1
    if depth >= max_depth:
      continue
    for neighbor_cell_id in graph_access.accessible_neighbor_cell_ids(current_cell_id):
      # 统一按 BFS 去重集防环路，保持计数只增量一次。
      if neighbor_cell_id in seen:
        continue
      seen.add(neighbor_cell_id)
      frontier.append((neighbor_cell_id, depth + 1))
  return score
