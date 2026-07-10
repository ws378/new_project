"""覆盖规划输入校验阶段。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..models import PlannerConfig
from .trace import PipelineStageRecord
from ..region import polygon_to_mask
from .summaries import InputValidationStageSummary
from ..traversal_core.traversal import is_start_pixel_valid


@dataclass(frozen=True)
class InputValidationStageResult:
  """输入校验阶段结果。
  
  通过该结构固定原始地图解析、分辨率、地图区域与起点约束的边界。
  """
  map_resolution: float
  map_origin: tuple[float, float]
  map_height: int
  planning_room_map: np.ndarray
  region_mask: np.ndarray | None
  chosen_start_pixel: tuple[int, int]
  coverage_width_px: int
  robot_half_width_px: float
  stage_record: PipelineStageRecord


def validate_planning_input(
  *,
  room_map: np.ndarray,
  metadata: dict[str, Any],
  config: PlannerConfig,
) -> InputValidationStageResult:
  """解析并校验规划入口参数，拒绝不满足路径生成前置条件的输入。"""

  # metadata 使用 ROS/map server 的常见语义：resolution 为米/像素，origin 为地图左下角世界坐标。
  map_resolution = float(metadata["resolution"])
  map_origin = (float(metadata["origin"][0]), float(metadata["origin"][1]))
  map_height = int(room_map.shape[0])
  # 覆盖宽度转像素后作为网格步长，至少 2 像素避免退化成过密单像素图。
  coverage_width_px = max(2, int(math.floor(config.coverage_width_m / map_resolution)))
  robot_half_width_px = max(1.0, 0.5 * float(config.robot_width_m) / map_resolution)
  planning_room_map = room_map

  region_mask = None
  if config.region_mask is not None:
    # region_mask 只接受原图尺寸；后续 artifact 会基于同一真值渲染区域边界。
    region_mask = np.where(np.asarray(config.region_mask) > 0, 255, 0).astype(np.uint8)
    if region_mask.shape != planning_room_map.shape[:2]:
      raise ValueError("区域掩膜必须与房间地图尺寸一致")
  elif config.region_polygon:
    # 没有 mask 但有 polygon 时，在 planner 内转换成二值 mask，避免渲染层重复解析 polygon。
    region_mask = polygon_to_mask(planning_room_map.shape[:2], config.region_polygon)

  free_pixel_count = int(np.count_nonzero(planning_room_map == 255))
  if free_pixel_count == 0:
    # 无可达像素会导致遍历与几何阶段全部退化为空，提前中止可避免错误链路传播。
    raise ValueError("区域内没有可通行空间，无法生成覆盖路径。")

  if config.start_pixel is None:
    # 起点是覆盖任务的硬前置，缺失时不能进入图遍历以避免空引用错误。
    raise ValueError("第一阶段要求手动选择起点，当前未提供起点像素。")
  if not is_start_pixel_valid(planning_room_map, config.start_pixel):
    # 起点不在可通行栅格会直接造成后续 traversal 无法挂接，需在输入层截断。
    raise ValueError("起点不在区域内可通行空间中。")

  chosen_start_pixel = (int(config.start_pixel[0]), int(config.start_pixel[1]))
  stage_record = InputValidationStageSummary(
    free_pixel_count=free_pixel_count,
    has_region_mask=region_mask is not None,
    start_pixel=chosen_start_pixel,
    coverage_width_px=int(coverage_width_px),
    robot_half_width_px=float(robot_half_width_px),
  ).to_stage_record()
  return InputValidationStageResult(
    map_resolution=float(map_resolution),
    map_origin=map_origin,
    map_height=map_height,
    planning_room_map=planning_room_map,
    region_mask=region_mask,
    chosen_start_pixel=chosen_start_pixel,
    coverage_width_px=int(coverage_width_px),
    robot_half_width_px=float(robot_half_width_px),
    stage_record=stage_record,
  )
