"""遍历评分输入契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from ..models import PlannerConfig


@dataclass(frozen=True)
class TraversalScoringContext:
  """评分上下文值对象。
  
  集中封装路径、方向约束与策略参数，供评分流程共享。
  """
  point_path: Sequence[tuple[float, float]]
  coverage_width_px: int
  previous_travel_angle: float
  map_resolution: float
  config: PlannerConfig
  local_direction_map: np.ndarray
  local_direction_confidence: np.ndarray
  edge_label_map: np.ndarray | None
  local_residual_count: int
  history_clearance_index: Any = None


def build_traversal_scoring_context(
  *,
  point_path: Sequence[tuple[float, float]],
  coverage_width_px: int,
  previous_travel_angle: float,
  map_resolution: float,
  config: PlannerConfig,
  local_direction_map: np.ndarray,
  local_direction_confidence: np.ndarray,
  edge_label_map: np.ndarray | None,
  local_residual_count: int,
  history_clearance_index: Any = None,
) -> TraversalScoringContext:
  """从运行时参数构建评分上下文。
  
  统一类型转换与缺省边界，减少评分入口重复校验。评分上下文本身不承载副作用。
  
  Args:
      point_path: 已有路径点序列。
      coverage_width_px: 覆盖步幅（像素）。
      previous_travel_angle: 上一段的航向角（弧度）。
      map_resolution: 地图分辨率（m/pixel）。
      config: planner 配置快照。
      local_direction_map: 局部主轴方向图。
      local_direction_confidence: 方向图置信度。
      edge_label_map: 边语义图，可为空。
      local_residual_count: 当前局部剩余未访问残量。
      history_clearance_index: 可选历史贴近索引。
      
  Returns:
      TraversalScoringContext: 供评分阶段共享的只读上下文。
  """
  return TraversalScoringContext(
    point_path=point_path,
    coverage_width_px=coverage_width_px,
    previous_travel_angle=previous_travel_angle,
    map_resolution=map_resolution,
    config=config,
    local_direction_map=local_direction_map,
    local_direction_confidence=local_direction_confidence,
    edge_label_map=edge_label_map,
    local_residual_count=local_residual_count,
    history_clearance_index=history_clearance_index,
  )
