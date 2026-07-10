"""历史清空索引：用于全局 fallback 的距离可达性评分。"""

from __future__ import annotations

import math
from typing import Dict, Sequence, Tuple

from ..models import StrategyConfig


class HistoryClearanceIndex:
  """基于网格桶的历史路径最小距离索引。
  
  通过 skip_recent 机制避免最近轨迹参与惩罚，保留局部连续性。
  """
  def __init__(self, path_points: Sequence[Tuple[float, float]], clearance_limit_px: float, skip_recent: int = 12):
    """建立历史路径网格桶索引。
    
    采用固定网格桶规避每个 fallback 候选 O(N) 全量扫描，提升评分阶段性能。
    
    Args:
        path_points: 历史路径点序列（原始路径像素坐标）。
        clearance_limit_px: 贴近度查询窗口边界（像素）。
        skip_recent: 最近 skip_recent 个路径点不参与索引构建，避免干扰局部连续性。
    """
    self.clearance_limit_px = float(clearance_limit_px)
    self.cell_size_px = max(1.0, self.clearance_limit_px)
    usable_points = path_points[:-skip_recent] if len(path_points) > skip_recent else []
    # 最近 skip_recent 点不参与索引，避免 fallback 刚离开当前位置就被“历史惩罚”干扰。
    self.cells: Dict[Tuple[int, int], list[Tuple[float, float]]] = {}
    for point in usable_points:
      # 只对可复用点建桶，后续 min_distance 才能在 O(1) 邻域完成。
      key = self._cell_key(point)
      self.cells.setdefault(key, []).append((float(point[0]), float(point[1])))

  def _cell_key(self, point: Tuple[float, float]) -> Tuple[int, int]:
    """按固定网格尺寸映射到桶坐标，用于后续仅检索邻域桶。"""
    return int(math.floor(float(point[0]) / self.cell_size_px)), int(math.floor(float(point[1]) / self.cell_size_px))

  def add_point(self, point: Tuple[float, float]) -> None:
    """向索引新增路径点并更新桶映射，供后续增量查询复用。"""
    # 增量更新替代重建，避免全量 rebuild 带来的 O(N) 抖动。
    key = self._cell_key(point)
    self.cells.setdefault(key, []).append((float(point[0]), float(point[1])))

  def min_distance(self, candidate_point: Tuple[float, float]) -> float:
    """查询候选点到历史路径集合的最小欧氏距离。
    
    仅遍历 candidate 周围 3x3 桶以复用网格桶稀疏性，未命中历史点时返回 inf。
    
    Args:
        candidate_point: 候选点像素坐标。
        
    Returns:
        float: 距离值；无历史点时为 inf。
    """
    if not self.cells:
      # 无历史索引时直接返回 inf，让评分路径天然退化为“远离历史”。
      return float("inf")
    base_x, base_y = self._cell_key(candidate_point)
    best_sq = float("inf")
    cx, cy = float(candidate_point[0]), float(candidate_point[1])
    for dy in (-1, 0, 1):
      for dx in (-1, 0, 1):
        # 仅检索邻近 3x3 桶，兼顾精度和查询性能。
        for px, py in self.cells.get((base_x + dx, base_y + dy), ()):
          # 先比较平方距离，最后再开方，减少重复 sqrt。
          delta_x = cx - px
          delta_y = cy - py
          distance_sq = delta_x * delta_x + delta_y * delta_y
          if distance_sq < best_sq:
            # 逐点更新最近距离的平方值，最终再开方避免重复 sqrt。
            best_sq = distance_sq
    return math.sqrt(best_sq) if best_sq < float("inf") else float("inf")


def build_history_clearance_index(
  path_points: Sequence[Tuple[float, float]],
  coverage_width_px: int,
  strategy_cfg: StrategyConfig,
) -> HistoryClearanceIndex | None:
  """按策略权重构建历史贴近索引。
  
  权重关闭时返回 None，调用方可直接走统一分支。
  
  Args:
      path_points: 历史路径点序列。
      coverage_width_px: 覆盖宽度（像素），用于生成查询半径。
      strategy_cfg: 策略配置（history_clearance_weight/ radius factor）。
      
  Returns:
      HistoryClearanceIndex | None: 权重启用时返回索引实例，否则返回 None。
  """
  if strategy_cfg.history_clearance_weight <= 0.0:
    # 历史贴近约束关闭时返回 None，避免每步分支都重复判定。
    return None
  clearance_limit = float(coverage_width_px) * float(strategy_cfg.history_clearance_radius_factor)
  return HistoryClearanceIndex(path_points, clearance_limit)
