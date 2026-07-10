"""局部方向场和外部 edge label 对齐阶段。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..direction import resolve_local_direction_maps, rotate_external_edge_label_map
from ..models import PlannerConfig
from .trace import PipelineStageRecord
from .summaries import LocalDirectionFieldStageSummary


@dataclass(frozen=True)
class DirectionFieldStageResult:
  """方向场阶段输出。
  
  记录方向来源、置信度与边界标签，用于后续候选评分中的角度约束。
  """
  local_direction_map: np.ndarray
  local_direction_confidence: np.ndarray
  local_direction_source: str
  rotated_edge_label_map: np.ndarray | None
  stage_record: PipelineStageRecord


def build_direction_field_stage(
  *,
  planning_room_map: np.ndarray,
  rotated_room_map: np.ndarray,
  rotation_matrix: np.ndarray,
  bounding_rect: tuple[int, int, int, int],
  coverage_width_px: int,
  config: PlannerConfig,
) -> DirectionFieldStageResult:
  """构建局部方向场并完成外部边标签对齐，输出供遍历与追踪复用的约束。"""

  # 方向场用于控制局部运动偏好，先统一构建并记录来源，以免后续评分不可追溯。
  local_direction_map, local_direction_confidence, local_direction_source = resolve_local_direction_maps(
    room_map=planning_room_map,
    rotated_room_map=rotated_room_map,
    rotation_matrix=rotation_matrix,
    bounding_rect=bounding_rect,
    coverage_width_px=coverage_width_px,
    config=config,
  )
  stage_record = LocalDirectionFieldStageSummary(
    source=str(local_direction_source),
    enabled=bool(config.local_direction.enable),
    mean_confidence=(
      float(local_direction_confidence[rotated_room_map == 255].mean())
      if np.any(rotated_room_map == 255)
      else 0.0
    ),
    external_guidance_inputs={
      "has_axis_direction_map": config.external_axis_direction_map is not None,
      "has_axis_confidence_map": config.external_axis_confidence_map is not None,
      "axis_blend_with_image_gradient": bool(config.external_axis_blend_with_image_gradient),
      "has_edge_label_map": config.external_edge_label_map is not None,
      "has_junction_label_map": config.external_junction_label_map is not None,
    },
  ).to_stage_record()

  rotated_edge_label_map = None
  if config.external_edge_label_map is not None:
    external_labels = np.asarray(config.external_edge_label_map, dtype=np.int32)
    if external_labels.shape != planning_room_map.shape[:2]:
      raise ValueError("外部边标签图必须与房间地图尺寸一致")
    # traversal 只消费 cropped rotated frame 标签；原图标签保留在 config 中供语义阶段使用。
    rotated_edge_label_map = rotate_external_edge_label_map(
      edge_label_map=external_labels,
      rotation_matrix=rotation_matrix,
      bounding_rect=bounding_rect,
      rotated_room_map=rotated_room_map,
    )

  return DirectionFieldStageResult(
    local_direction_map=local_direction_map,
    local_direction_confidence=local_direction_confidence,
    local_direction_source=str(local_direction_source),
    rotated_edge_label_map=rotated_edge_label_map,
    stage_record=stage_record,
  )
