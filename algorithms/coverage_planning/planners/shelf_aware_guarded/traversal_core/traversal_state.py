"""遍历状态与摘要对象。

用途：持有遍历运行中的动态状态（当前节点、访问集合、步进计数）及其只读快照。
输入：可达节点集合和起始 cell id。
输出：供评分、复盘和 artifact 共享的状态视图。

约束：
 - 当前静态可通行集合来自 CoverageGraph，运行时仅在 TraversalState 内变更。
 - ``Node`` 上的 visited/counter 不作为遍历主链路真源，避免状态重复定义。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class TraversalStateSnapshot:
  """TraversalState 的只读快照。
  
  仅保留可序列化字段，便于 artifact 与调试对齐。
  """
  current_cell_id: str
  visited_cell_ids: frozenset[str]
  visit_count_items: tuple[tuple[str, int], ...]

  @classmethod
  def from_state(cls, state: "TraversalState") -> "TraversalStateSnapshot":
    """由运行时状态生成快照。
    
    将可变集合转为可序列化结构，避免快照外泄 live 对象。
    
    Args:
        state: 运行时状态。
    
    Returns:
        TraversalStateSnapshot: 可序列化快照。
    """
    return cls(
      current_cell_id=str(state.current_cell_id),
      visited_cell_ids=frozenset(str(cell_id) for cell_id in state.visited_cell_ids),
      visit_count_items=tuple(
        sorted((str(cell_id), int(count)) for cell_id, count in state.visit_counts.items())
      ),
    )

  def is_visited_cell(self, cell_id: str) -> bool:
    """检查快照中某 cell 是否已访问，用于恢复阶段与调试一致性判断。"""
    return str(cell_id) in self.visited_cell_ids

  def visit_count_for_cell(self, cell_id: str) -> int:
    """读取快照中指定 cell 的访问次数，未命中返回 0。"""
    target = str(cell_id)
    for item_cell_id, count in self.visit_count_items:
      if item_cell_id == target:
        return int(count)
    return 0


@dataclass
class TraversalState:
  """遍历运行态状态。
  
  维护当前位置信息、访问集合和步进计数，作为评分与决策输入。
  """
  current_cell_id: str
  visited_cell_ids: set[str]
  visit_counts: dict[str, int]
  path_cell_ids: list[str]
  previous_heading_rad: float | None
  step_index: int
  remaining_unvisited_count: int
  total_cell_count: int
  history_clearance_index_size: int = 0

  @classmethod
  def from_start(cls, *, accessible_cell_ids: Sequence[str], start_cell_id: str) -> "TraversalState":
    """从可达集合构造初始状态。
    
    校验起点合法性与唯一性，失败时快速报错以避免下游错乱。
    
    Args:
        accessible_cell_ids: 可达节点集合。
        start_cell_id: 起始 cell id。
    
    Returns:
      TraversalState: 初始化后的运行时状态。
    """
    cell_ids = tuple(str(cell_id) for cell_id in accessible_cell_ids)
    # 去重保证输入可达集合定义明确，避免 set 化后静默丢失节点导致状态口径错位。
    if len(set(cell_ids)) != len(cell_ids):
      raise AssertionError("TraversalState accessible_cell_ids must be unique")
    start_cell_id = str(start_cell_id)
    # 起点必须在可达集合内，否则后续访问检查会持续命中不存在节点。
    if start_cell_id not in set(cell_ids):
      raise AssertionError("TraversalState start cell must be accessible")
    state = cls(
      current_cell_id=start_cell_id,
      visited_cell_ids={start_cell_id},
      visit_counts={start_cell_id: 1},
      path_cell_ids=[start_cell_id],
      previous_heading_rad=None,
      step_index=0,
      remaining_unvisited_count=len(cell_ids) - 1,
      total_cell_count=len(cell_ids),
    )
    return state

  def record_move(self, *, to_cell_id: str, heading_rad: float, was_first_visit: bool, visit_count: int) -> None:
    """记录一次移动并更新相关计数。
    
    同步路径、角度与剩余未访问数，保证后续边界检查可重放。
    """
    cell_id = str(to_cell_id)
    # step 推进时同时更新路径、角度和剩余未访问计数，维持多处统计口径一致。
    self.step_index += 1
    self.current_cell_id = cell_id
    self.path_cell_ids.append(cell_id)
    self.previous_heading_rad = float(heading_rad)
    self.visit_counts[cell_id] = int(visit_count)
    self.visited_cell_ids.add(cell_id)
    # 仅当首次访问时才减少剩余计数，保证多次重访不会把 frontier 人为耗尽。
    if was_first_visit:
      self.remaining_unvisited_count -= 1
    # 下游统计默认剩余数非负，出现负数说明重复扣减，必须立即暴露。
    if self.remaining_unvisited_count < 0:
      raise AssertionError("TraversalState remaining_unvisited_count became negative")

  def advance_history_clearance_index_size(self) -> int:
    """推进历史索引更新序号。
    
    用于回放时判断索引是否与 fallback 触发次数对齐。
    
    Returns:
        int: 更新后的 history_clearance_index_size。
    """
    self.history_clearance_index_size += 1
    return self.history_clearance_index_size

  def is_visited_cell(self, cell_id: str) -> bool:
    """判断当前状态中是否已访问指定 cell。"""
    return str(cell_id) in self.visited_cell_ids

  def visit_count_for_cell(self, cell_id: str) -> int:
    """返回当前状态中某 cell 的访问次数，未命中返回 0。"""
    return int(self.visit_counts.get(str(cell_id), 0))

  def to_summary(self) -> dict[str, object]:
    """导出遍历状态摘要（artifact/log 可消费）。

    返回最小字段集用于跨阶段对齐：
    - 当前节点
    - 访问规模
    - 步数与剩余未访问数
    - 历史索引推进进度
    """
    return {
      "current_cell_id": self.current_cell_id,
      "visited_cell_count": len(self.visited_cell_ids),
      "path_cell_count": len(self.path_cell_ids),
      "step_index": int(self.step_index),
      "remaining_unvisited_count": int(self.remaining_unvisited_count),
      "total_cell_count": int(self.total_cell_count),
      "previous_heading_rad": self.previous_heading_rad,
      "history_clearance_index_size": int(self.history_clearance_index_size),
    }

  def to_snapshot(self) -> TraversalStateSnapshot:
    """创建运行时状态快照用于 artifact 与回放持久化。"""
    return TraversalStateSnapshot.from_state(self)
