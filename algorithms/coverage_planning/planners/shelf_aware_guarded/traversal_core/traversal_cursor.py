"""遍历位置游标：仅承载当前遍历单元位置。

用途：承载当前遍历位置的最小不变标识。
输出：类型稳定的 `cell_id`，供主循环与状态断言共享。
约束：仅表达位置，不承担运行时动态状态，所有动态字段由 TraversalState 管理。
"""

from __future__ import annotations

from dataclasses import dataclass

from .traversal_state import TraversalState


@dataclass(frozen=True)
class TraversalCursor:
  """遍历游标对象：仅持有当前节点标识。

  只保存当前 `cell_id`，用于状态迁移和断言；避免在游标里携带可变状态导致共享错误。
  """
  cell_id: str

  @classmethod
  def from_cell_id(cls, cell_id: str) -> "TraversalCursor":
    """构造游标并规范化 cell id。
    
    防止来源字段（int/str）混用导致断言和字典查找错配。
    
    Args:
        cell_id: 任意可转换为字符串的 cell 标识。
        
    Returns:
        TraversalCursor: 规范化后的轻量游标。
    """
    normalized_cell_id = str(cell_id)
    return cls(cell_id=normalized_cell_id)

  def assert_matches_state(self, traversal_state: TraversalState) -> None:
    """校验游标与当前状态一致。
    
    不一致表示回放/重试链路偏移，快速失败避免后续越界。
    
    Args:
        traversal_state: 当前遍历状态。
    """
    # 游标与状态必须同源，否则说明有阶段切换或回放偏移，立即 fail-fast 防止后续错链。
    if self.cell_id != str(traversal_state.current_cell_id):
      raise AssertionError("TraversalCursor cell_id diverged from TraversalState current_cell_id")
