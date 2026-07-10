"""最终路径实现阶段。

将 traversal 层输出的路径按固定流水线收敛为可发布路径，并产出完整的审计元数据。
仅拼装已有逻辑，不新增优化策略，不回写 traversal 图状态。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..models import PlannerConfig
from .transform_record import (
  FINAL_PATH_PROVENANCE_POLICY_ISOLATED_JUMP_CLEANUP_ARTIFACT,
  FINAL_PATH_PROVENANCE_POLICY_PATH_PIXELS_AND_SEGMENTS,
  FINAL_PATH_PROVENANCE_POLICY_SEMANTIC_PATH_ARTIFACT,
  FINAL_PATH_TRANSFORM_FINAL_PATH_GEOMETRY,
  FINAL_PATH_TRANSFORM_ISOLATED_JUMP_CLEANUP,
  FINAL_PATH_TRANSFORM_SEMANTIC_GLOBAL_PATH,
  FINAL_PATH_TRANSFORM_SIMPLIFY_ROTATED_PATH,
  FINAL_PATH_TRANSFORM_TYPE_GEOMETRIC_FORMATTING,
  FINAL_PATH_TRANSFORM_TYPE_LIGHTWEIGHT_SAFETY_GUARD,
  FINAL_PATH_TRANSFORM_TYPE_SEMANTIC_PATH_EXPRESSION,
  FinalPathTransformRecord,
  build_final_path_transform_record,
)
from .jump_cleanup import IsolatedJumpCleanupResult, cleanup_isolated_jump_fragments
from .postprocess import (
  build_jump_segment_indices,
  build_jump_segments,
  build_segment_index_groups,
  simplify_point_path,
  split_point_path,
)
from ..pipeline.trace import PipelineStageRecord
from ..geometry.room_rotation import point_path_to_pose_path, transform_points
from ..pipeline.summaries import (
  FinalPathGeometryStageSummary,
  IsolatedJumpCleanupStageSummary,
  SemanticGlobalPathStageSummary,
  SimplifyRotatedPathStageSummary,
)
from ..traversal_core.traversal_graph_access import TraversalGraphAccess
from .node_semantics import build_node_semantics
from .semantic_path import build_semantic_global_path


Point = tuple[float, float]
PosePoint = tuple[float, float, float]


@dataclass(frozen=True)
class FinalPathRealizationInput:
  """final path 生成所需输入的不可变参数集合。"""
  fov_coverage_path: list[Point]
  graph_access: TraversalGraphAccess
  planning_room_map: np.ndarray
  rotated_room_map: np.ndarray
  inverse_rotation: np.ndarray
  coverage_width_px: int
  map_resolution: float
  config: PlannerConfig


@dataclass(frozen=True)
class FinalPathRealizationResult:
  """final path realization 的完整输出，包含路径与审计元数据。"""
  simplified_fov_path: list[Point]
  pixel_points_raw: list[Point]
  baseline_pixel_points: list[Point]
  pixel_points: list[Point]
  pixel_poses: list[PosePoint]
  pixel_segments: list[list[Point]]
  pixel_segment_indices: list[list[int]]
  jump_segments: list[tuple[Point, Point]]
  jump_segment_indices: list[tuple[int, int]]
  node_semantics_payload: dict[str, Any] | None
  semantic_path_payload: dict[str, Any] | None
  jump_cleanup_result: IsolatedJumpCleanupResult
  pipeline_stage_records: list[PipelineStageRecord]
  transform_records: tuple[FinalPathTransformRecord, ...] = ()


def realize_final_path(stage_input: FinalPathRealizationInput) -> FinalPathRealizationResult:
  """执行最终路径实现流水线。

  阶段顺序固定为：简化 -> 语义表达（可选）-> 孤立跳变清理 -> 几何分段与姿态生成。
  所有中间结果记录为 pipeline stage 和 transform record。
  """
  stage_records: list[PipelineStageRecord] = []
  transform_records: list[FinalPathTransformRecord] = []

  # 第一阶段先做几何简化，压掉微小抖动，避免后续语义判断和几何拆分把噪声放大。
  simplified_fov_path = simplify_point_path(
    stage_input.fov_coverage_path,
    stage_input.coverage_width_px,
    stage_input.config.strategy,
  )
  stage_records.append(SimplifyRotatedPathStageSummary(
    input_point_count=len(stage_input.fov_coverage_path),
    output_point_count=len(simplified_fov_path),
  ).to_stage_record())
  transform_records.append(build_final_path_transform_record(
    name=FINAL_PATH_TRANSFORM_SIMPLIFY_ROTATED_PATH,
    transform_type=FINAL_PATH_TRANSFORM_TYPE_LIGHTWEIGHT_SAFETY_GUARD,
    enabled=bool(stage_input.config.strategy.simplify_enable),
    input_point_count=len(stage_input.fov_coverage_path),
    output_point_count=len(simplified_fov_path),
    changes_path_points=stage_input.fov_coverage_path != simplified_fov_path,
  ))

  # 保留原始和简化点序列两份，便于语义重建阶段判断输入变更是否实质发生。
  pixel_points_raw = transform_points(stage_input.fov_coverage_path, stage_input.inverse_rotation)
  pixel_points = transform_points(simplified_fov_path, stage_input.inverse_rotation)
  baseline_pixel_points = list(pixel_points)
  node_semantics_payload = None
  semantic_path_payload = None

  if stage_input.config.semantic_path_enable:
    # 语义路径在配置开启时才执行，默认关闭以避免额外语义过滤对基线可执行路径产生影响。
    node_semantics_payload = build_node_semantics(
      graph_access=stage_input.graph_access,
      free_mask=stage_input.planning_room_map,
      territory_label_map=stage_input.config.external_edge_label_map,
      junction_label_map=stage_input.config.external_junction_label_map,
      inverse_rotation_matrix=stage_input.inverse_rotation,
      rotated_room_map=stage_input.rotated_room_map,
      coverage_width_px=stage_input.coverage_width_px,
      coverage_width_m=float(stage_input.config.coverage_width_m),
      resolution_m_per_px=stage_input.map_resolution,
    )
    semantic_path_payload = build_semantic_global_path(
      pixel_points=[(float(x), float(y)) for x, y in baseline_pixel_points],
      node_semantics_payload=node_semantics_payload,
      coverage_width_px=stage_input.coverage_width_px,
      actual_clean_width_m=float(stage_input.config.semantic_actual_clean_width_m),
      resolution_m_per_px=stage_input.map_resolution,
    )
    pixel_points = [(float(x), float(y)) for x, y in semantic_path_payload["path_points"]]
    # semantic 重建改变点序列时记录变更，用于 provenance 与复测可复核。
    stage_records.append(SemanticGlobalPathStageSummary(
      enabled=True,
      input_point_count=len(baseline_pixel_points),
      output_point_count=len(pixel_points),
      summary=semantic_path_payload["summary"],
    ).to_stage_record())
    transform_records.append(build_final_path_transform_record(
      name=FINAL_PATH_TRANSFORM_SEMANTIC_GLOBAL_PATH,
      transform_type=FINAL_PATH_TRANSFORM_TYPE_SEMANTIC_PATH_EXPRESSION,
      enabled=True,
      input_point_count=len(baseline_pixel_points),
      output_point_count=len(pixel_points),
      changes_path_points=baseline_pixel_points != pixel_points,
      provenance_policy=FINAL_PATH_PROVENANCE_POLICY_SEMANTIC_PATH_ARTIFACT,
    ))
  else:
    stage_records.append(SemanticGlobalPathStageSummary(
      enabled=False,
      input_point_count=len(baseline_pixel_points),
      output_point_count=len(pixel_points),
      summary={"enabled": False},
    ).to_stage_record())
    transform_records.append(build_final_path_transform_record(
      name=FINAL_PATH_TRANSFORM_SEMANTIC_GLOBAL_PATH,
      transform_type=FINAL_PATH_TRANSFORM_TYPE_SEMANTIC_PATH_EXPRESSION,
      enabled=False,
      input_point_count=len(baseline_pixel_points),
      output_point_count=len(pixel_points),
      changes_path_points=False,
    ))

  jump_cleanup_result = cleanup_isolated_jump_fragments(
    pixel_points,
    resolution_m_per_px=stage_input.map_resolution,
    config=stage_input.config.isolated_jump_cleanup,
  )
  # 孤立长跳清理默认可开关；记录处理前后点数用于判定结构性变化是否发生。
  before_jump_cleanup_count = len(pixel_points)
  pixel_points = list(jump_cleanup_result.path_points)
  jump_cleanup_summary = jump_cleanup_result.to_summary_dict(stage_input.map_resolution)
  stage_records.append(IsolatedJumpCleanupStageSummary(
    input_point_count=before_jump_cleanup_count,
    output_point_count=len(pixel_points),
    summary=jump_cleanup_summary,
  ).to_stage_record())
  transform_records.append(build_final_path_transform_record(
    name=FINAL_PATH_TRANSFORM_ISOLATED_JUMP_CLEANUP,
    transform_type=FINAL_PATH_TRANSFORM_TYPE_LIGHTWEIGHT_SAFETY_GUARD,
    enabled=bool(stage_input.config.isolated_jump_cleanup.enable),
    input_point_count=before_jump_cleanup_count,
    output_point_count=len(pixel_points),
    changes_path_points=bool(jump_cleanup_summary.get("changed", False)),
    provenance_policy=FINAL_PATH_PROVENANCE_POLICY_ISOLATED_JUMP_CLEANUP_ARTIFACT,
  ))

  pixel_poses = point_path_to_pose_path(pixel_points)
  # 最终分段与跳变计算在清理完成后做，确保导出的几何形状与可执行路径一致。
  pixel_segments = split_point_path(pixel_points, stage_input.coverage_width_px, stage_input.config.strategy)
  jump_segments = build_jump_segments(pixel_points, stage_input.coverage_width_px, stage_input.config.strategy)
  pixel_segment_indices = build_segment_index_groups(
    pixel_points,
    stage_input.coverage_width_px,
    stage_input.config.strategy,
  )
  jump_segment_indices = build_jump_segment_indices(
    pixel_points,
    stage_input.coverage_width_px,
    stage_input.config.strategy,
  )
  stage_records.append(FinalPathGeometryStageSummary(
    input_point_count=len(pixel_points),
    output_point_count=len(pixel_poses),
    segment_count=max(0, len(pixel_points) - 1),
    split_segment_count=len(pixel_segments),
    jump_segment_count=len(jump_segments),
  ).to_stage_record())
  transform_records.append(build_final_path_transform_record(
    name=FINAL_PATH_TRANSFORM_FINAL_PATH_GEOMETRY,
    transform_type=FINAL_PATH_TRANSFORM_TYPE_GEOMETRIC_FORMATTING,
    enabled=True,
    input_point_count=len(pixel_points),
    output_point_count=len(pixel_poses),
    changes_path_points=False,
    provenance_policy=FINAL_PATH_PROVENANCE_POLICY_PATH_PIXELS_AND_SEGMENTS,
  ))

  return FinalPathRealizationResult(
    simplified_fov_path=simplified_fov_path,
    pixel_points_raw=pixel_points_raw,
    baseline_pixel_points=baseline_pixel_points,
    pixel_points=pixel_points,
    pixel_poses=pixel_poses,
    pixel_segments=pixel_segments,
    pixel_segment_indices=pixel_segment_indices,
    jump_segments=jump_segments,
    jump_segment_indices=jump_segment_indices,
    node_semantics_payload=node_semantics_payload,
    semantic_path_payload=semantic_path_payload,
    jump_cleanup_result=jump_cleanup_result,
    pipeline_stage_records=stage_records,
    transform_records=tuple(transform_records),
  )
