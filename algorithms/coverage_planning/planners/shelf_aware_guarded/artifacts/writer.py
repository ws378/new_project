"""货架感知规划器的调试产物写出逻辑。

这里的函数只负责序列化和渲染规划结果，不能改变路径点、节点 visit 状态、
语义载荷或清理摘要。把副作用边界固定在写出层，可以保证调试产物开关
不会影响语义回归和性能对比。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from ..models import PlannerArtifacts, PlannerConfig
from ..pipeline.trace import PipelineStageRecord, pipeline_trace_payload
from ..region import save_region_file, save_region_visualizations
from ..traversal_core.traversal_graph_access import TraversalGraphAccess
from ..direction import visualize_local_direction
from ..final_path.transform_record import FinalPathTransformRecord, final_path_transform_records_payload
from .cleanup_payloads import isolated_jump_cleanup_payload
from .csv_debug import save_debug_csv
from .decision_debug_payloads import candidate_decision_debug_payload
from .manifest import planner_artifact_manifest_entries, write_artifact_manifest
from .metadata_payloads import planner_metadata_payload
from .node_debug import save_node_debug_json
from .path_payloads import (
  indexed_points_payload,
  path_jump_segments_pixels_payload,
  path_pixels_payload,
  path_segments_pixels_payload,
)
from .paths import PlannerArtifactPaths
from .provenance_payloads import (
  final_segment_provenance_payload,
  path_generation_provenance_payload,
)
from .visualization import (
  save_rotated_room_map_visual,
  visualize_node_obstacle_ratio_filter,
  visualize_nodes_and_path,
)


@dataclass(frozen=True)
class PlannerArtifactContext:
  """planner artifact 写出上下文。

  约束：所有字段在 write_planner_artifacts 内只读消费，不在 writer 中修改状态。
  """

  output_path: Path
  config: PlannerConfig
  room_map: np.ndarray
  planning_room_map: np.ndarray
  rotated_room_map: np.ndarray
  graph_access: TraversalGraphAccess
  metadata: dict[str, Any]
  map_resolution: float
  map_origin: tuple[float, float]
  map_height: int
  coverage_width_px: int
  rotation_angle: float
  rotation_matrix: np.ndarray
  inverse_rotation: np.ndarray
  full_rotation_matrix: np.ndarray
  full_bounding_rect: tuple[int, int, int, int]
  crop_rect: tuple[int, int, int, int]
  rotated_crop_offset_px: tuple[int, int]
  full_rotated_shape: tuple[int, int]
  local_direction_map: np.ndarray
  local_direction_confidence: np.ndarray
  local_direction_source: str
  chosen_start_pixel: tuple[int, int]
  region_mask: np.ndarray | None
  rotated_edge_label_map: np.ndarray | None
  pixel_points_raw: Sequence[tuple[float, float]]
  baseline_pixel_points: Sequence[tuple[float, float]]
  pixel_points: Sequence[tuple[float, float]]
  pixel_poses: Sequence[tuple[float, float, float]]
  pixel_segments: Sequence[Sequence[tuple[float, float]]]
  pixel_segment_indices: Sequence[Sequence[int]]
  jump_segments: Sequence[tuple[tuple[float, float], tuple[float, float]]]
  jump_segment_indices: Sequence[tuple[int, int]]
  world_path: list[dict[str, float | int]]
  fallback_debug_trace: list[dict[str, Any]]
  candidate_decision_debug_trace: list[dict[str, Any]]
  fov_coverage_path: Sequence[tuple[float, float]]
  traversal_move_trace: Sequence[dict[str, Any]]
  traversal_state_snapshot: Any | None
  min_room: tuple[int, int]
  max_room: tuple[int, int]
  node_semantics_payload: dict[str, Any] | None
  semantic_path_payload: dict[str, Any] | None
  jump_cleanup_result: Any
  final_path_transform_records: Sequence[FinalPathTransformRecord]
  pipeline_trace: Sequence[PipelineStageRecord]


def _write_json(path: Path, payload: Any) -> None:
  """将任意可 JSON 化 payload 写到目标路径。

  统一编码与缩进是为了让 artifact 可人工比对，调用方只需传入序列化对象。
  """
  with path.open("w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=True, indent=2)


def write_planner_artifacts(context: PlannerArtifactContext) -> PlannerArtifacts:
  """按配置写出 artifacts 与 manifest。

  artifacts_written 为 False 时仅返回路径字符串占位，不产生文件写入；
  这样可以让测试和批量运行控制产物开关，不污染性能基准。
  """
  output_path = context.output_path
  paths = PlannerArtifactPaths.from_output_dir(output_path)
  config = context.config
  room_map = context.room_map
  planning_room_map = context.planning_room_map
  rotated_room_map = context.rotated_room_map
  graph_access = context.graph_access
  metadata = context.metadata
  map_resolution = context.map_resolution
  map_origin = context.map_origin
  map_height = context.map_height
  coverage_width_px = context.coverage_width_px
  rotation_angle = context.rotation_angle
  rotation_matrix = context.rotation_matrix
  inverse_rotation = context.inverse_rotation
  local_direction_map = context.local_direction_map
  local_direction_confidence = context.local_direction_confidence
  local_direction_source = context.local_direction_source
  chosen_start_pixel = context.chosen_start_pixel
  region_mask = context.region_mask
  rotated_edge_label_map = context.rotated_edge_label_map
  pixel_points_raw = context.pixel_points_raw
  baseline_pixel_points = context.baseline_pixel_points
  pixel_points = context.pixel_points
  pixel_poses = context.pixel_poses
  pixel_segments = context.pixel_segments
  pixel_segment_indices = context.pixel_segment_indices
  jump_segments = context.jump_segments
  jump_segment_indices = context.jump_segment_indices
  world_path = context.world_path
  fallback_debug_trace = context.fallback_debug_trace
  candidate_decision_debug_trace = context.candidate_decision_debug_trace
  fov_coverage_path = context.fov_coverage_path
  traversal_move_trace = context.traversal_move_trace
  traversal_state_snapshot = context.traversal_state_snapshot
  min_room = context.min_room
  max_room = context.max_room
  node_semantics_payload = context.node_semantics_payload
  semantic_path_payload = context.semantic_path_payload
  jump_cleanup_result = context.jump_cleanup_result
  final_path_transform_records = final_path_transform_records_payload(context.final_path_transform_records)
  pipeline_trace = list(context.pipeline_trace)
  debug_csv_path = paths.energy_debug if config.write_artifacts and config.save_debug_csv else None

  artifacts_written = bool(config.write_artifacts)
  if artifacts_written:
    # 写出前置可视化与区域产物：不包含算法状态变更，仅用于复核。
    save_rotated_room_map_visual(rotated_room_map, paths.rotated_map)
    visualize_nodes_and_path(
      rotated_room_map,
      planning_room_map,
      graph_access,
      pixel_poses,
      pixel_segments,
      jump_segments,
      paths.nodes_debug,
      paths.path_overlay,
    )
    visualize_local_direction(
      rotated_room_map,
      local_direction_map,
      local_direction_confidence,
      coverage_width_px,
      paths.local_direction_debug,
    )
    if config.node_obstacle_ratio_filter_enable:
      # 节点过滤图只在功能开启时输出，避免无效产物充斥输出目录。
      visualize_node_obstacle_ratio_filter(
        rotated_room_map,
        graph_access,
        paths.node_obstacle_ratio_filter_debug,
      )

    planner_params = config.planner_params_dict()
    if region_mask is not None:
      # 区域输入与区域覆盖图是可复现输入快照，需与 metadata 一起归档。
      save_region_visualizations(
        room_map,
        config.region_polygon or [],
        chosen_start_pixel,
        str(paths.region_mask),
        str(paths.region_overlay),
        region_mask=region_mask,
      )
      save_region_file(
        str(paths.region_json),
        metadata.get("map_yaml", ""),
        metadata.get("image_path", ""),
        config.region_polygon or [],
        chosen_start_pixel,
        planner_params,
      )

    _write_json(paths.path_pixels_raw, indexed_points_payload(pixel_points_raw))
    _write_json(paths.path_pixels_baseline_before_semantics, indexed_points_payload(baseline_pixel_points))
    _write_json(paths.path_pixels, path_pixels_payload(pixel_poses))
    _write_json(
      paths.path_segments_pixels,
      path_segments_pixels_payload(
        pixel_points=pixel_points,
        pixel_segment_indices=pixel_segment_indices,
      ),
    )
    _write_json(
      paths.path_jump_segments_pixels,
      path_jump_segments_pixels_payload(
        pixel_points=pixel_points,
        jump_segment_indices=jump_segment_indices,
      ),
    )
    _write_json(paths.path_world, world_path)
    # path/metadata 统一结构输出，保留原始像素、简化像素与语义来源链路，便于离线复核。
    _write_json(
      paths.metadata,
      planner_metadata_payload(
        paths=paths,
        config=config,
        map_resolution=map_resolution,
        map_origin=map_origin,
        coverage_width_px=coverage_width_px,
        rotation_angle=rotation_angle,
        rotation_matrix=rotation_matrix,
        full_rotation_matrix=context.full_rotation_matrix,
        full_bounding_rect=context.full_bounding_rect,
        crop_rect=context.crop_rect,
        rotated_crop_offset_px=context.rotated_crop_offset_px,
        full_rotated_shape=context.full_rotated_shape,
        local_direction_confidence=local_direction_confidence,
        rotated_room_map=rotated_room_map,
        local_direction_source=local_direction_source,
        rotated_edge_label_map=rotated_edge_label_map,
        semantic_path_payload=semantic_path_payload,
        node_semantics_payload=node_semantics_payload,
        jump_cleanup_result=jump_cleanup_result,
        final_path_transform_records=final_path_transform_records,
        pipeline_trace=pipeline_trace,
        chosen_start_pixel=chosen_start_pixel,
        pixel_points_raw=pixel_points_raw,
        world_path=world_path,
        pixel_segments=pixel_segments,
        jump_segments=jump_segments,
        fallback_debug_trace=fallback_debug_trace,
        candidate_decision_debug_trace=candidate_decision_debug_trace,
        traversal_move_trace=traversal_move_trace,
        region_mask=region_mask,
        planning_room_map=planning_room_map,
        graph_access=graph_access,
      ),
    )
    _write_json(paths.fallback_debug_trace, fallback_debug_trace)
    _write_json(
      paths.candidate_decision_debug,
      candidate_decision_debug_payload(candidate_decision_debug_trace),
    )
    _write_json(
      paths.path_generation_provenance,
      path_generation_provenance_payload(
        traversal_move_trace,
        inverse_rotation=inverse_rotation,
      ),
    )
    _write_json(
      paths.final_segment_provenance,
      final_segment_provenance_payload(
        pixel_points=pixel_points,
        pixel_poses=pixel_poses,
        traversal_move_trace=traversal_move_trace,
        inverse_rotation=inverse_rotation,
        map_resolution=map_resolution,
        semantic_path_payload=semantic_path_payload,
        jump_cleanup_result=jump_cleanup_result,
      ),
    )
    _write_json(paths.pipeline_trace, pipeline_trace_payload(pipeline_trace))
    # 额外保留节点级补充产物，便于单独回放和问题归档。
    save_node_debug_json(
      paths.node_debug_enriched,
      rotated_room_map,
      map_resolution,
      inverse_rotation,
      map_origin,
      map_height,
      graph_access=graph_access,
      traversal_state=traversal_state_snapshot,
    )
    if node_semantics_payload is not None:
      _write_json(paths.node_semantics, node_semantics_payload)
    if semantic_path_payload is not None:
      _write_json(paths.semantic_global_path, semantic_path_payload)
    _write_json(
      paths.isolated_jump_cleanup,
      isolated_jump_cleanup_payload(
        config=config.isolated_jump_cleanup,
        jump_cleanup_result=jump_cleanup_result,
        map_resolution=map_resolution,
      ),
    )

    if debug_csv_path is not None:
      # debug_csv 通过开关控制，避免在默认路径下产生大体积中间结果。
      visited_points = {(int(round(x)), int(round(y))) for x, y in fov_coverage_path}
      save_debug_csv(
        debug_csv_path,
        graph_access,
        visited_points,
        rotated_room_map,
        map_resolution,
        inverse_rotation,
        min_room,
        max_room,
        map_origin,
        map_height,
      )
    write_artifact_manifest(
      paths.artifact_manifest,
      planner_artifact_manifest_entries(
        paths=paths,
        region_mask_available=region_mask is not None,
        node_obstacle_ratio_filter_enabled=bool(config.node_obstacle_ratio_filter_enable),
        debug_csv_enabled=debug_csv_path is not None,
        node_semantics_available=node_semantics_payload is not None,
        semantic_path_available=semantic_path_payload is not None,
      ),
    )

  return PlannerArtifacts(
    output_dir=str(output_path),
    rotated_map_path=str(paths.rotated_map) if artifacts_written else None,
    overlay_path=str(paths.path_overlay) if artifacts_written else None,
    nodes_path=str(paths.nodes_debug) if artifacts_written else None,
    path_pixels_path=str(paths.path_pixels) if artifacts_written else None,
    path_world_path=str(paths.path_world) if artifacts_written else None,
    debug_csv_path=str(debug_csv_path) if debug_csv_path is not None else None,
    local_direction_path=str(paths.local_direction_debug) if artifacts_written else None,
    baseline_path_pixels_path=str(paths.path_pixels_baseline_before_semantics) if artifacts_written else None,
    node_semantics_path=str(paths.node_semantics) if artifacts_written and node_semantics_payload is not None else None,
    semantic_path_path=str(paths.semantic_global_path) if artifacts_written and semantic_path_payload is not None else None,
    isolated_jump_cleanup_path=str(paths.isolated_jump_cleanup) if artifacts_written else None,
    node_obstacle_ratio_filter_path=str(paths.node_obstacle_ratio_filter_debug) if artifacts_written and config.node_obstacle_ratio_filter_enable else None,
    path_generation_provenance_path=str(paths.path_generation_provenance) if artifacts_written else None,
    final_segment_provenance_path=str(paths.final_segment_provenance) if artifacts_written else None,
    candidate_decision_debug_path=str(paths.candidate_decision_debug) if artifacts_written else None,
    pipeline_trace_path=str(paths.pipeline_trace) if artifacts_written else None,
    artifact_manifest_path=str(paths.artifact_manifest) if artifacts_written else None,
    final_path_transform_records=[dict(record) for record in final_path_transform_records],
  )
