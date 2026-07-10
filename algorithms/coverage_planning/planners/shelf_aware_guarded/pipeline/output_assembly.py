"""最终输出路径装配。

本模块只负责把最终像素 pose 转换为正式返回的世界坐标 path。它不改变像素路径、
分段、provenance 或 artifact 内容。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .trace import PipelineStageRecord
from .summaries import OutputAssemblyStageSummary


PosePoint = tuple[float, float, float]


@dataclass(frozen=True)
class OutputPathAssemblyResult:
  """世界路径装配结果。
  
  副作用：当前仅返回结果对象，不直接做持久化。
  """
  world_path: list[dict[str, Any]]
  stage_record: PipelineStageRecord


@dataclass(frozen=True)
class OutputPathAssemblyInput:
  """像素路径到世界路径装配的入参。
  
  绑定像素级路径与地图位姿元信息，为最终坐标变换提供足够约束。
  """
  pixel_poses: Sequence[PosePoint]
  map_resolution: float
  map_origin: tuple[float, float]
  map_height: int


def assemble_world_path(stage_input: OutputPathAssemblyInput) -> OutputPathAssemblyResult:
  """把像素 pose 转为世界坐标 path，保持每个点的一致索引映射。"""

  world_path: list[dict[str, Any]] = []
  resolution = float(stage_input.map_resolution)
  origin_x, origin_y = float(stage_input.map_origin[0]), float(stage_input.map_origin[1])
  height = int(stage_input.map_height)
  for index, (x_pixel, y_pixel, theta) in enumerate(stage_input.pixel_poses, start=1):
    # 世界坐标需显式做 y 轴翻转，匹配图像->地图坐标的约定。
    world_path.append(
      {
        "index": index,
        "x": float(x_pixel) * resolution + origin_x,
        "y": (height - float(y_pixel)) * resolution + origin_y,
        "theta": -float(theta),
      }
    )
  return OutputPathAssemblyResult(
    world_path=world_path,
    stage_record=OutputAssemblyStageSummary(
      input_pose_count=len(stage_input.pixel_poses),
      world_path_count=len(world_path),
    ).to_stage_record(),
  )
