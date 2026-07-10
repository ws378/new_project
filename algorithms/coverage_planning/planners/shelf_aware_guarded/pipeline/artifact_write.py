"""调试产物写出阶段。

本阶段只负责把前序 stage result 组装成 ``PlannerArtifactContext`` 并调用现有
writer。artifact 文件名、schema 和 manifest 由 writer 统一维护；本阶段不改变
路径、节点状态或 pipeline trace 语义。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from ..artifacts import PlannerArtifactContext, write_planner_artifacts
from .coverage_graph import CoverageGraphBuildResult
from .direction_field import DirectionFieldStageResult
from ..final_path.realization import FinalPathRealizationResult
from .graph_traversal import GraphTraversalStageResult
from .input_validation import InputValidationStageResult
from ..models import PlannerArtifacts, PlannerConfig
from .output_assembly import OutputPathAssemblyResult
from .trace import PipelineStageRecord
from .room_rotation import RoomRotationStageResult
from .summaries import ArtifactWriteStageSummary


@dataclass(frozen=True)
class ArtifactWriteStageInput:
  """Artifact 写出阶段的入参容器。
  
  汇总上游各阶段结果与配置，并由此决定是否写入中间产物。
  """
  output_path: Path
  config: PlannerConfig
  room_map: np.ndarray
  metadata: dict[str, Any]
  input_stage: InputValidationStageResult
  rotation_stage: RoomRotationStageResult
  direction_stage: DirectionFieldStageResult
  graph_stage: CoverageGraphBuildResult
  graph_traversal_stage: GraphTraversalStageResult
  final_path_result: FinalPathRealizationResult
  output_assembly_result: OutputPathAssemblyResult
  inverse_rotation: np.ndarray
  pipeline_trace: Sequence[PipelineStageRecord]


@dataclass(frozen=True)
class ArtifactWriteStageResult:
  """Artifact 写出阶段输出。
  
  副作用：可能触发文件输出；同时返回可追踪记录用于下游审计。
  """
  artifacts: PlannerArtifacts
  stage_record: PipelineStageRecord


def build_planner_artifact_context(
  stage_input: ArtifactWriteStageInput,
  *,
  pipeline_trace: Sequence[PipelineStageRecord] | None = None,
) -> PlannerArtifactContext:
  """构建 writer 入参的 artifact 上下文，保持下游写入字段完整可回放。"""

  traversal_result = stage_input.graph_traversal_stage.traversal_result
  # 将所有阶段产物拼成 writer 可序列化上下文，避免逐阶段重复读取导致字段缺失。
  return PlannerArtifactContext(
    output_path=stage_input.output_path,
    config=stage_input.config,
    room_map=stage_input.room_map,
    planning_room_map=stage_input.input_stage.planning_room_map,
    rotated_room_map=stage_input.rotation_stage.rotated_room_map,
    graph_access=stage_input.graph_stage.graph_access,
    metadata=stage_input.metadata,
    map_resolution=stage_input.input_stage.map_resolution,
    map_origin=stage_input.input_stage.map_origin,
    map_height=stage_input.input_stage.map_height,
    coverage_width_px=stage_input.input_stage.coverage_width_px,
    rotation_angle=stage_input.rotation_stage.rotation_angle_rad,
    rotation_matrix=stage_input.rotation_stage.rotation_matrix,
    inverse_rotation=stage_input.inverse_rotation,
    full_rotation_matrix=stage_input.rotation_stage.full_rotation_matrix,
    full_bounding_rect=stage_input.rotation_stage.full_bounding_rect,
    crop_rect=stage_input.rotation_stage.crop_rect,
    rotated_crop_offset_px=stage_input.rotation_stage.rotated_crop_offset_px,
    full_rotated_shape=stage_input.rotation_stage.full_rotated_shape,
    local_direction_map=stage_input.direction_stage.local_direction_map,
    local_direction_confidence=stage_input.direction_stage.local_direction_confidence,
    local_direction_source=stage_input.direction_stage.local_direction_source,
    chosen_start_pixel=stage_input.input_stage.chosen_start_pixel,
    region_mask=stage_input.input_stage.region_mask,
    rotated_edge_label_map=stage_input.direction_stage.rotated_edge_label_map,
    pixel_points_raw=stage_input.final_path_result.pixel_points_raw,
    baseline_pixel_points=stage_input.final_path_result.baseline_pixel_points,
    pixel_points=stage_input.final_path_result.pixel_points,
    pixel_poses=stage_input.final_path_result.pixel_poses,
    pixel_segments=stage_input.final_path_result.pixel_segments,
    pixel_segment_indices=stage_input.final_path_result.pixel_segment_indices,
    jump_segments=stage_input.final_path_result.jump_segments,
    jump_segment_indices=stage_input.final_path_result.jump_segment_indices,
    world_path=stage_input.output_assembly_result.world_path,
    fallback_debug_trace=traversal_result.fallback_debug_trace,
    candidate_decision_debug_trace=traversal_result.candidate_decision_debug_trace,
    fov_coverage_path=traversal_result.fov_coverage_path,
    traversal_move_trace=traversal_result.move_trace,
    traversal_state_snapshot=traversal_result.traversal_state_snapshot,
    min_room=stage_input.graph_stage.min_room,
    max_room=stage_input.graph_stage.max_room,
    node_semantics_payload=stage_input.final_path_result.node_semantics_payload,
    semantic_path_payload=stage_input.final_path_result.semantic_path_payload,
    jump_cleanup_result=stage_input.final_path_result.jump_cleanup_result,
    final_path_transform_records=stage_input.final_path_result.transform_records,
    pipeline_trace=tuple(pipeline_trace if pipeline_trace is not None else stage_input.pipeline_trace),
  )


def write_artifacts_stage(stage_input: ArtifactWriteStageInput) -> ArtifactWriteStageResult:
  """触发 artifact 入库阶段并返回本阶段追踪记录。"""

  # artifact 阶段仅负责入库触发，不改变路径行为本体，便于回滚与验证。
  stage_record = ArtifactWriteStageSummary(
    enabled=bool(stage_input.config.write_artifacts),
    output_path=str(stage_input.output_path),
  ).to_stage_record()
  context = build_planner_artifact_context(
    stage_input,
    pipeline_trace=[*stage_input.pipeline_trace, stage_record],
  )
  return ArtifactWriteStageResult(
    artifacts=write_planner_artifacts(context),
    stage_record=stage_record,
  )
