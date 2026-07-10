"""房间旋转阶段：统一方向坐标归一化。

用途：将地图旋转到主方向坐标系，减少后续网格方向偏置。
输入：原始规划地图、地图分辨率。
输出：旋转后的地图、旋转矩阵、逆变换矩阵和阶段记录。

约束：旋转参数由统一算法计算，避免多个阶段各自推导导致边界不一致。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .trace import PipelineStageRecord
from ..geometry.room_rotation import compute_room_rotation, invert_affine_transform, rotate_room
from .summaries import RoomRotationStageSummary


@dataclass(frozen=True)
class RoomRotationStageResult:
  """房间旋转阶段结果。
  
  下游正式坐标系是 cropped rotated frame；full rotated frame 只作为审计事实保留。
  """
  rotation_angle_rad: float
  rotation_matrix: np.ndarray
  inverse_rotation: np.ndarray
  full_rotation_matrix: np.ndarray
  bounding_rect: tuple[int, int, int, int]
  full_bounding_rect: tuple[int, int, int, int]
  crop_rect: tuple[int, int, int, int]
  rotated_crop_offset_px: tuple[int, int]
  full_rotated_shape: tuple[int, int]
  rotated_room_map: np.ndarray
  frame_id: str
  stage_record: PipelineStageRecord


def rotate_room_stage(
  *,
  planning_room_map: np.ndarray,
  map_resolution: float,
  crop_padding_px: int,
) -> RoomRotationStageResult:
  """计算统一旋转并收束到 cropped rotated frame，作为下游唯一规划坐标系。"""

  # 先生成 full rotated frame，再按 free bbox 裁剪；下游不直接消费 full frame。
  rotation_angle, full_rotation_matrix, full_bounding_rect = compute_room_rotation(planning_room_map, map_resolution)
  full_rotated_room_map = rotate_room(planning_room_map, full_rotation_matrix, full_bounding_rect)
  ys, xs = np.where(full_rotated_room_map == 255)
  if len(xs) == 0:
    raise ValueError("旋转后的地图中没有可通行像素")
  padding = max(0, int(crop_padding_px))
  x0 = max(0, int(xs.min()) - padding)
  y0 = max(0, int(ys.min()) - padding)
  x1 = min(full_rotated_room_map.shape[1], int(xs.max()) + padding + 1)
  y1 = min(full_rotated_room_map.shape[0], int(ys.max()) + padding + 1)
  rotated_room_map = full_rotated_room_map[y0:y1, x0:x1].copy()
  rotation_matrix = np.array(full_rotation_matrix, dtype=np.float64, copy=True)
  rotation_matrix[0, 2] -= float(x0)
  rotation_matrix[1, 2] -= float(y0)
  bounding_rect = (0, 0, int(rotated_room_map.shape[1]), int(rotated_room_map.shape[0]))
  stage_record = RoomRotationStageSummary(
    rotation_angle_rad=float(rotation_angle),
    full_bounding_rect=tuple(int(value) for value in full_bounding_rect),
    crop_rect=(int(x0), int(y0), int(x1 - x0), int(y1 - y0)),
    crop_padding_px=int(padding),
    rotated_crop_offset_px=(int(x0), int(y0)),
    full_rotated_shape=(int(full_rotated_room_map.shape[0]), int(full_rotated_room_map.shape[1])),
    rotated_shape=(int(rotated_room_map.shape[0]), int(rotated_room_map.shape[1])),
  ).to_stage_record()
  return RoomRotationStageResult(
    rotation_angle_rad=float(rotation_angle),
    rotation_matrix=rotation_matrix,
    inverse_rotation=invert_affine_transform(rotation_matrix),
    full_rotation_matrix=full_rotation_matrix,
    bounding_rect=tuple(int(value) for value in bounding_rect),
    full_bounding_rect=tuple(int(value) for value in full_bounding_rect),
    crop_rect=(int(x0), int(y0), int(x1 - x0), int(y1 - y0)),
    rotated_crop_offset_px=(int(x0), int(y0)),
    full_rotated_shape=(int(full_rotated_room_map.shape[0]), int(full_rotated_room_map.shape[1])),
    rotated_room_map=rotated_room_map,
    frame_id="cropped_rotated_room",
    stage_record=stage_record,
  )
