"""shelf_aware 规划主编排层。

用途：
  - 串联方向场、图构建、遍历、语义路径、后处理和 artifact 写出阶段。
  - 将复杂 pipeline 划分为可回放阶段（每个阶段保留独立 stage_record）。

输入：
  - `room_map`: 输入占据图
  - `metadata`: 由上层注入的地图元信息（分辨率、原点等）
  - `output_dir`: artifacts 输出目录
  - `config`: 完整的 `PlannerConfig`

输出：
  - 世界坐标路径（List[Dict]）
  - `PlannerArtifacts`（文件产物与追踪信息）

设计约束：
  - 本文件不承载几何规则或评分公式，仅保持阶段边界与上下文传递。
  - 所有阶段副作用（artifact 文件、日志）集中在 `write_artifacts_stage`，便于排错与复现。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from .pipeline.artifact_write import ArtifactWriteStageInput, write_artifacts_stage
from .pipeline.coverage_graph import build_coverage_graph_stage
from .pipeline.direction_field import build_direction_field_stage
from .final_path.realization import FinalPathRealizationInput, realize_final_path
from .pipeline.graph_traversal import GraphTraversalStageInput, run_graph_traversal_stage
from .pipeline.input_validation import validate_planning_input
from .models import PlannerArtifacts, PlannerConfig
from .pipeline.output_assembly import OutputPathAssemblyInput, assemble_world_path
from .pipeline.trace import PipelineStageRecord
from .pipeline.room_rotation import rotate_room_stage
from .pipeline.start_cell import select_start_cell_stage


ROTATED_CROP_MIN_PADDING_PX = 8
ROTATED_CROP_COVERAGE_WIDTH_PADDING_FACTOR = 2


def plan_coverage_path(room_map: np.ndarray, metadata: Dict, output_dir: str, config: PlannerConfig) -> Tuple[List[Dict], PlannerArtifacts]:
  """运行 shelf-aware 覆盖规划流水线并返回结果。

  Args:
    room_map: 输入占据网格。
    metadata: 上层注入的元信息，透传到 artifact 与输出转换阶段。
    output_dir: artifact 根目录路径。
    config: 覆盖规划配置。

  Returns:
    Tuple[List[Dict], PlannerArtifacts]: 
      - 世界坐标路径点字典
      - artifacts 对象（文件路径与运行追踪）

  Notes:
    阶段顺序固定为：输入校验 -> 旋转 -> 方向场 -> 建图 -> 起点 -> 遍历 ->
    语义后处理 -> 输出组装 -> artifact 写出。
    固定顺序可保证方向场对齐、起点映射和后处理语义一致，便于重放。
  """

  # 先建立输出目录，保障后续所有阶段都能安全写入调试数据；不依赖默认当前目录。
  output_path = Path(output_dir)
  output_path.mkdir(parents=True, exist_ok=True)
  pipeline_trace: list[PipelineStageRecord] = []

  input_stage = validate_planning_input(
    room_map=room_map,
    metadata=metadata,
    config=config,
  )
  map_resolution = input_stage.map_resolution
  map_origin = input_stage.map_origin
  map_height = input_stage.map_height
  coverage_width_px = input_stage.coverage_width_px
  robot_half_width_px = input_stage.robot_half_width_px
  planning_room_map = input_stage.planning_room_map
  chosen_start_pixel = input_stage.chosen_start_pixel
  pipeline_trace.append(input_stage.stage_record)

  # 将房间旋转到主方向坐标系，目的是让 coverage cell 沿主要走廊方向更接近轴对齐，
  # 降低规则网格构建时的形变误差并减少后续补偿成本。
  rotation_stage = rotate_room_stage(
    planning_room_map=planning_room_map,
    map_resolution=map_resolution,
    crop_padding_px=max(
      ROTATED_CROP_MIN_PADDING_PX,
      int(coverage_width_px) * ROTATED_CROP_COVERAGE_WIDTH_PADDING_FACTOR,
    ),
  )
  rotation_matrix = rotation_stage.rotation_matrix
  bounding_rect = rotation_stage.bounding_rect
  rotated_room_map = rotation_stage.rotated_room_map
  pipeline_trace.append(rotation_stage.stage_record)

  # 方向场既支持外部输入，也支持内部梯度估计；两者统一到旋转坐标系后再入图。
  direction_stage = build_direction_field_stage(
    planning_room_map=planning_room_map,
    rotated_room_map=rotated_room_map,
    rotation_matrix=rotation_matrix,
    bounding_rect=bounding_rect,
    coverage_width_px=coverage_width_px,
    config=config,
  )
  pipeline_trace.append(direction_stage.stage_record)

  # 在统一坐标系内构建覆盖网格，可确保后续遍历评分与局部方向的边界约束保持同一尺度语义。
  graph_stage = build_coverage_graph_stage(
    rotated_room_map=rotated_room_map,
    coverage_width_px=coverage_width_px,
    robot_half_width_px=robot_half_width_px,
    config=config,
  )
  pipeline_trace.append(graph_stage.stage_record)

  # 起点从输入像素坐标转换到图节点坐标，可复用外部起点语义，同时避免直接落在不可通行点。
  start_cell_stage = select_start_cell_stage(
    graph_access=graph_stage.graph_access,
    chosen_start_pixel=chosen_start_pixel,
    rotation_matrix=rotation_matrix,
  )
  pipeline_trace.append(start_cell_stage.stage_record)
  # 只保留遍历循环产物中的原始几何和 fallback 诊断，后续重建/清理再做语义重写以隔离副作用。
  graph_traversal_stage = run_graph_traversal_stage(
    GraphTraversalStageInput(
      graph_access=graph_stage.graph_access,
      start_cell_id=start_cell_stage.start_cell_id,
      coverage_width_px=coverage_width_px,
      config=config,
      map_resolution=map_resolution,
      local_direction_map=direction_stage.local_direction_map,
      local_direction_confidence=direction_stage.local_direction_confidence,
      rotated_edge_label_map=direction_stage.rotated_edge_label_map,
    )
  )
  traversal_result = graph_traversal_stage.traversal_result
  fov_coverage_path = traversal_result.fov_coverage_path
  pipeline_trace.append(graph_traversal_stage.stage_record)

  # 遍历阶段只负责覆盖主循环；语义化重排与微调在独立阶段执行，防止评分与主覆盖状态互相污染。
  final_path_result = realize_final_path(
    FinalPathRealizationInput(
      fov_coverage_path=fov_coverage_path,
      graph_access=graph_stage.graph_access,
      planning_room_map=planning_room_map,
      rotated_room_map=rotated_room_map,
      inverse_rotation=rotation_stage.inverse_rotation,
      coverage_width_px=coverage_width_px,
      map_resolution=map_resolution,
      config=config,
    )
  )
  pipeline_trace.extend(final_path_result.pipeline_stage_records)

  # 输出装配统一在该阶段执行，避免上游阶段各自处理坐标变换导致重复误差。
  output_assembly_result = assemble_world_path(
    OutputPathAssemblyInput(
      pixel_poses=final_path_result.pixel_poses,
      map_resolution=map_resolution,
      map_origin=map_origin,
      map_height=map_height,
    )
  )
  pipeline_trace.append(output_assembly_result.stage_record)

  # artifact 写入放在单一阶段，主编排层只传递上下文，便于在日志中复查每步输入输出。
  # 即使 `config.write_artifacts=False`，该阶段仍返回可追踪结构，保证上层可读性。
  artifact_stage = write_artifacts_stage(
    ArtifactWriteStageInput(
      output_path=output_path,
      config=config,
      room_map=room_map,
      metadata=metadata,
      input_stage=input_stage,
      rotation_stage=rotation_stage,
      direction_stage=direction_stage,
      graph_stage=graph_stage,
      graph_traversal_stage=graph_traversal_stage,
      final_path_result=final_path_result,
      output_assembly_result=output_assembly_result,
      inverse_rotation=rotation_stage.inverse_rotation,
      pipeline_trace=pipeline_trace,
    )
  )
  return output_assembly_result.world_path, artifact_stage.artifacts
