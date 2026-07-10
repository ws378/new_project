"""ShelfAware 覆盖网格拓扑连接工具。"""

from __future__ import annotations

from typing import Sequence

from ..models import Node


def connect_grid_neighbors(nodes: Sequence[Sequence[Node]]) -> None:
  """按 8 邻接规则为节点矩阵填充 neighbors。

  障碍节点也保留在邻接表中，评分阶段再统一过滤，便于调试节点拓扑。
  """

  # 逐行遍历是稳定的拓扑生成策略，避免依赖哈希顺序导致邻接不确定。
  for row_index, row in enumerate(nodes):
    # 保持列扫描顺序与后续可视化/调试一致，减少 row/col 颠倒造成定位差异。
    for col_index, node in enumerate(row):
      # 以 row/col 扫描保证拓扑顺序稳定，便于后续邻接可复现。
      for dy in (-1, 0, 1):
        neighbor_row = row_index + dy
        # 越界行不形成邻接，提前剪枝可减少无效写入。
        if neighbor_row < 0 or neighbor_row >= len(nodes):
          continue
        # 左边界必须有空间时才补左邻接。
        if col_index > 0:
          node.neighbors.append(nodes[neighbor_row][col_index - 1])
        # 非同一行时添加上下邻接，避免重复添加当前格子自身。
        if dy != 0:
          node.neighbors.append(nodes[neighbor_row][col_index])
        # 右边界有空间时补右邻接，避免越界导致异常引用。
        if col_index < len(nodes[row_index]) - 1:
          node.neighbors.append(nodes[neighbor_row][col_index + 1])
