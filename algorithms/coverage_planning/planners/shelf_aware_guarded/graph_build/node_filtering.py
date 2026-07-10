"""ShelfAware 覆盖节点过滤工具。"""

from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np

from ..models import Node


def filter_nodes_by_obstacle_ratio(
  room_map: np.ndarray,
  nodes: Sequence[Sequence[Node]],
  *,
  robot_width_px: float,
  threshold: float,
) -> None:
  """按机器人宽度窗口统计障碍比例并更新节点状态。
  
  过滤发生在 alignment 之后，使用 planning_point_px 作为窗口中心，保持“几何微调后的最终点”作为判断依据。
  只更新对象字段，不改动矩阵维度，便于调试 id 与邻接引用稳定。
  
  Args:
      room_map: 0 表示障碍、255 表示 free 的地图栅格。
      nodes: 行列结构的节点矩阵，按原引用更新。
      robot_width_px: 过滤窗口边长依据（像素）。
      threshold: 障碍比例阈值，超过则将节点标记为 obstacle。
  """

  window_size = max(1, int(round(float(robot_width_px))))
  # 双层循环只做矩阵级别扫描，不做算法判定，避免把几何策略分散到此层。
  for row in nodes:
    # 每一行从左到右处理，保持可复现顺序。
    for node in row:
      # 已有障碍节点不再重算比例，保留原始状态并保持障碍语义稳定。
      if node.obstacle:
        node.obstacle_ratio = None
        node.obstacle_ratio_filtered = False
        continue
      ratio = obstacle_ratio_around_point(room_map, node.planning_point_px, window_size)
      node.obstacle_ratio = float(ratio)
      node.obstacle_ratio_filtered = bool(ratio > float(threshold))
      if node.obstacle_ratio_filtered:
        node.obstacle = True


def obstacle_ratio_around_point(room_map: np.ndarray, planning_point_px: Tuple[int, int], window_size_px: int) -> float:
  """统计 planning_point_px 周围窗口中的障碍比例。

  约束边界时将越界区域按障碍计入，可避免地图边缘被错误低估为可通行。
  
  Args:
      room_map: 0/255 的旋转地图栅格。
      planning_point_px: 以该点为窗口中心（像素坐标）。
      window_size_px: 正方形窗口边长（像素）。
      
  Returns:
      float: 0~1 之间的障碍比例。
  """

  window_size = max(1, int(window_size_px))
  x, y = int(round(planning_point_px[0])), int(round(planning_point_px[1]))
  # 越界按障碍补齐，避免边缘位置被错误判定为更高可达率。
  left = x - (window_size // 2)
  top = y - (window_size // 2)
  right = left + window_size
  bottom = top + window_size

  src_left = max(0, left)
  src_top = max(0, top)
  src_right = min(room_map.shape[1], right)
  src_bottom = min(room_map.shape[0], bottom)

  total_pixels = window_size * window_size
  free_pixels = 0
  # 无法落在窗口内时直接返回全障碍比例，确保边界区域不被低估为可行。
  if src_left < src_right and src_top < src_bottom:
    patch = np.asarray(room_map[src_top:src_bottom, src_left:src_right])
    free_pixels = int(np.count_nonzero(patch == 255))
  obstacle_pixels = int(total_pixels - free_pixels)
  return float(obstacle_pixels / total_pixels)
