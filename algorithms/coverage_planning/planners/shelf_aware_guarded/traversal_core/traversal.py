"""主规划循环使用的遍历状态和候选选择逻辑。

这里负责在节点图上推进访问状态：优先走未访问邻居，其次按配置允许 revisit
bridge，最后才做全局 fallback。输出仍是旋转坐标系下的节点中心路径。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..models import PlannerConfig
from .traversal_cursor import TraversalCursor
from .traversal_decision_debug import traversal_decision_event_payload
from .traversal_move import TraversalMove
from .traversal_move_commit import commit_selected_traversal_move
from .traversal_graph_access import TraversalGraphAccess
from .traversal_state import TraversalState, TraversalStateSnapshot
from .traversal_step_selection import (
  TraversalStepContext,
  make_history_clearance_index,
  select_next_traversal_candidate,
)


def choose_start_cell_id(*, graph_access: TraversalGraphAccess, rotated_start: tuple[int, int]) -> str:
  """从可达节点中选择离起点像素最近的 cell。
  
  当手动点不在网格中心时，选择距离最小节点以降低首步代价；无可达节点时抛异常。
  
  Args:
      graph_access: 可访问节点图访问器。
      rotated_start: 旋转坐标系下的起点像素。
  
  Returns:
      str: 最近可达 cell id。
  """
  accessible_cell_ids = graph_access.accessible_cell_ids()
  # 无可达单元时立即中断，避免后续用空集合取首元素引发难以定位的异常。
  if not accessible_cell_ids:
    raise ValueError("房间内没有可通行节点")
  best_cell_id = accessible_cell_ids[0]
  min_distance = float("inf")
  # 按距离扫描全部可达节点，避免从任意可达点起步导致首步方向偏置放大。
  for cell_id in accessible_cell_ids:
    point = graph_access.planning_point_px_for_cell(cell_id)
    dx = point[0] - rotated_start[0]
    dy = point[1] - rotated_start[1]
    # 比较平方距离即可，避免每个节点开方。
    squared_distance = dx * dx + dy * dy
    if squared_distance <= min_distance:
      min_distance = squared_distance
      best_cell_id = cell_id
  return str(best_cell_id)


def choose_initial_angle(start_cell_id: str, *, graph_access: TraversalGraphAccess) -> float:
  """推断起始朝向（弧度）。

  优先沿可通行邻居方向取一个轴向，减少首步转角引入的评分偏置。
  若当前起点无可通行邻居，返回默认朝向，避免因缺失邻接直接中断流程。
  
  Args:
    start_cell_id: 起始 cell id。
    graph_access: 可访问节点图访问器。
  
  Returns:
    float: 朝向弧度值。
  """
  start_point = graph_access.planning_point_px_for_cell(start_cell_id)
  # 仅当存在与起点正交/同轴邻接时返回确定朝向，避免后续评分依赖随机初始值。
  for neighbor_cell_id in graph_access.accessible_neighbor_cell_ids(start_cell_id):
    neighbor_point = graph_access.planning_point_px_for_cell(neighbor_cell_id)
    if neighbor_point[1] == start_point[1] and neighbor_point[0] > start_point[0]:
      return 0.0
    if neighbor_point[1] == start_point[1] and neighbor_point[0] < start_point[0]:
      return math.pi
    if neighbor_point[1] < start_point[1] and neighbor_point[0] == start_point[0]:
      return -0.5 * math.pi
    if neighbor_point[1] > start_point[1] and neighbor_point[0] == start_point[0]:
      return 0.5 * math.pi
  # 没有可通行邻居时兜底为向右，后续通常会直接 fallback 或结束。
  return 0.0


def is_start_pixel_valid(room_map: np.ndarray, start_pixel: tuple[int, int]) -> bool:
  """校验起点像素是否在原始地图内且可通行。
  
  起点校验放在原始 room_map 坐标系，避免用户坐标与旋转坐标混用。
  
  Args:
      room_map: 原始地图像素栅格。
      start_pixel: 起点像素坐标。
  
  Returns:
      bool: 坐标合法且可通行返回 True。
  """
  x, y = start_pixel
  # 边界越界或黑障点都视为非法起点，保证后续路径不会从不可达像素发散。
  if x < 0 or x >= room_map.shape[1] or y < 0 or y >= room_map.shape[0]:
    return False
  return bool(room_map[y, x] == 255)


@dataclass(frozen=True)
class TraversalResult:
  """遍历主流程输出对象。
  
  记录覆盖路径、移动轨迹与调试事件，作为 artifact 与装配阶段输入。
  
  属性:
    fov_coverage_path: 旋转坐标系下的原始遍历路径。
    move_trace: 逐段移动记录。
    fallback_debug_trace: fallback 评分调试轨迹。
    traversal_state_summary: TraversalState 只读摘要。
    traversal_state_snapshot: 可选快照。
    candidate_decision_debug_trace: 每步阶段候选决策明细。
  """
  fov_coverage_path: list[tuple[float, float]]
  # move_trace 与 fov_coverage_path 对齐，记录每个点/边来自 normal、revisit 还是 global fallback。
  move_trace: list[dict[str, Any]]
  # fallback_debug_trace 仅在 write_artifacts=True 时记录完整候选评分明细。
  fallback_debug_trace: list[dict[str, Any]]
  # traversal_state_summary 是 TraversalState 的只读摘要，不参与候选选择。
  traversal_state_summary: dict[str, object]
  # traversal_state_snapshot 是 artifact-only 动态状态快照，不参与候选选择。
  traversal_state_snapshot: TraversalStateSnapshot | None = None
  # candidate_decision_debug_trace 仅在 write_artifacts=True 时记录每步 phase-level 候选概览。
  candidate_decision_debug_trace: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TraversalRuntime:
  """遍历运行时可变状态快照。
  
  持有路径、日志和状态对象，便于遍历循环内持续更新。
  """
  fov_coverage_path: list[tuple[float, float]]
  move_trace: list[dict[str, Any]]
  fallback_debug_trace: list[dict[str, Any]]
  cursor: TraversalCursor
  previous_travel_angle: float
  accessible_cell_ids: tuple[str, ...]
  traversal_state: TraversalState
  max_total_steps: int
  candidate_decision_debug_trace: list[dict[str, Any]]


def initialize_traversal_runtime(
  *,
  start_cell_id: str,
  config: PlannerConfig,
  graph_access: TraversalGraphAccess,
) -> TraversalRuntime:
  """初始化遍历运行时。
  
  以起点为第一采样点并预置 move_trace，确保计数与路径统计口径一致。
  """
  start_cell_id = str(start_cell_id)
  # 起点立即记录到 TraversalState，路径中的第一个点就是实际起始节点中心。
  start_point = graph_access.planning_point_px_for_cell(start_cell_id)
  fov_coverage_path = [(float(start_point[0]), float(start_point[1]))]
  move_trace: list[dict[str, Any]] = [
    TraversalMove.start(
      to_node_id=start_cell_id,
      to_point_rotated_px=(
        float(start_point[0]),
        float(start_point[1]),
      ),
    ).to_trace_item()
  ]
  previous_travel_angle = choose_initial_angle(start_cell_id, graph_access=graph_access)
  accessible_cell_ids = graph_access.accessible_cell_ids()
  traversal_state = TraversalState.from_start(
    accessible_cell_ids=accessible_cell_ids,
    start_cell_id=start_cell_id,
  )
  cursor = TraversalCursor.from_cell_id(start_cell_id)
  cursor.assert_matches_state(traversal_state)
  # max_total_steps 是防御性上限，避免 revisit 策略配置异常时进入无限循环。
  max_total_steps = max(
    len(accessible_cell_ids) * max(2, config.strategy.max_revisit_count + 1),
    len(accessible_cell_ids) + 1,
  )
  return TraversalRuntime(
    fov_coverage_path=fov_coverage_path,
    move_trace=move_trace,
    fallback_debug_trace=[],
    cursor=cursor,
    previous_travel_angle=previous_travel_angle,
    accessible_cell_ids=accessible_cell_ids,
    traversal_state=traversal_state,
    max_total_steps=max_total_steps,
    candidate_decision_debug_trace=[],
  )


def run_traversal_loop(
  *,
  graph_access: TraversalGraphAccess,
  start_cell_id: str,
  coverage_width_px: int,
  config: PlannerConfig,
  map_resolution: float,
  local_direction_map: np.ndarray,
  local_direction_confidence: np.ndarray,
  edge_label_map: np.ndarray | None,
) -> TraversalResult:
  """执行主遍历循环并返回 TraversalResult。
  
  约束：步数超过上限或无候选时终止；起点非法会直接报错。
  """
  start_cell_id = str(start_cell_id)
  # 起点必须在图内，否则后续 assert 无法阻止越界 id 蔓延。
  if start_cell_id not in set(graph_access.accessible_cell_ids()):
    raise AssertionError("start_cell_id must be accessible in coverage graph")
  runtime = initialize_traversal_runtime(
    start_cell_id=start_cell_id,
    config=config,
    graph_access=graph_access,
  )
  step_counter = 0
  history_clearance_index = make_history_clearance_index(coverage_width_px, config)

  # 以步数上限保护遍历循环，确保参数异常时仍可退出。
  while step_counter < runtime.max_total_steps:
    step_counter += 1
    runtime.cursor.assert_matches_state(runtime.traversal_state)
    step_decision = select_next_traversal_candidate(
      cursor=runtime.cursor,
      context=TraversalStepContext(
        fov_coverage_path=runtime.fov_coverage_path,
        previous_travel_angle=runtime.previous_travel_angle,
        traversal_state=runtime.traversal_state,
        graph_access=graph_access,
        history_clearance_index=history_clearance_index,
        coverage_width_px=coverage_width_px,
        config=config,
        map_resolution=map_resolution,
        local_direction_map=local_direction_map,
        local_direction_confidence=local_direction_confidence,
        edge_label_map=edge_label_map,
        step_counter=step_counter,
      ),
    )
    next_selection = step_decision.selection
    local_residual_count = step_decision.local_residual_count
    if step_decision.fallback_debug_event is not None:
      runtime.fallback_debug_trace.append(step_decision.fallback_debug_event)

    decision_debug_event: dict[str, Any] | None = None
    if config.write_artifacts:
      # artifacts 打开时才落盘 phase 级复盘数据，避免生产场景生成大量中间对象。
      debug_phase_selections = [
        (
          phase_name,
          selection,
          selection.selected_cell_id,
        )
        for phase_name, selection in step_decision.attempted_phase_selections
      ]
      decision_debug_event = traversal_decision_event_payload(
        step_counter=step_counter,
        path_index_before_selection=len(runtime.fov_coverage_path),
        current_cell_id=runtime.cursor.cell_id,
        local_residual_count=local_residual_count,
        phase_selections=debug_phase_selections,
        final_selection=next_selection,
        final_selected_cell_id=(
          None
          if not next_selection.has_selection
          else next_selection.selected_cell_id
        ),
      )

    # 无可选时既可能是覆盖完成，也可能是全局约束阻断，统一在此点退出主循环。
    if not next_selection.has_selection:
      # 没有任何可走候选，说明所有可达/允许节点已经处理完或被约束过滤。
      if decision_debug_event is not None:
        runtime.candidate_decision_debug_trace.append(decision_debug_event)
      break

    committed_move = commit_selected_traversal_move(
      last_cursor=runtime.cursor,
      next_selection=next_selection,
      fov_coverage_path=runtime.fov_coverage_path,
      move_trace=runtime.move_trace,
      traversal_state=runtime.traversal_state,
      graph_access=graph_access,
      previous_travel_angle=runtime.previous_travel_angle,
      step_counter=step_counter,
      local_residual_count=local_residual_count,
    )
    if decision_debug_event is not None:
      decision_debug_event["selected_move_id"] = committed_move.trace_item["move_id"]
      runtime.candidate_decision_debug_trace.append(decision_debug_event)
    # 上一步到下一节点的方向会成为下一轮评分的 previous_travel_angle。
    runtime.previous_travel_angle = committed_move.heading_rad
    runtime.cursor = committed_move.next_cursor
    runtime.cursor.assert_matches_state(runtime.traversal_state)

    if runtime.traversal_state.remaining_unvisited_count <= 0:
      # 所有非障碍节点都至少访问一次后结束遍历。
      break

  return TraversalResult(
    fov_coverage_path=runtime.fov_coverage_path,
    move_trace=runtime.move_trace,
    fallback_debug_trace=runtime.fallback_debug_trace,
    traversal_state_summary=runtime.traversal_state.to_summary(),
    traversal_state_snapshot=runtime.traversal_state.to_snapshot(),
    candidate_decision_debug_trace=runtime.candidate_decision_debug_trace,
  )
