"""遍历、候选选择与评分域对外出口。"""

from .traversal import (
  TraversalResult,
  choose_initial_angle,
  choose_start_cell_id,
  is_start_pixel_valid,
  run_traversal_loop,
)
from .traversal_graph_access import TraversalGraphAccess

# 遍历能力暴露为稳定 API，避免调用方感知内部阶段文件组织细节。
__all__ = [
  "TraversalGraphAccess",
  "TraversalResult",
  "choose_initial_angle",
  "choose_start_cell_id",
  "is_start_pixel_valid",
  "run_traversal_loop",
]
