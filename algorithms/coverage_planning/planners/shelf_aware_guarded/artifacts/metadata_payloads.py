"""元信息载荷构建。

聚合规划输出的可复核摘要，避免通过日志逆向推断参数。
该模块只做统计口径收敛，不改写图状态或路径语义。
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from ..models import PlannerConfig
from ..pipeline.trace import PipelineStageRecord, pipeline_trace_payload
from .paths import PlannerArtifactPaths


def node_obstacle_ratio_filter_metadata(
  *,
  graph_access: Any,
  config: PlannerConfig,
) -> dict[str, Any]:
  """计算节点障碍比例过滤的统计摘要。

  Args:
    graph_access: 当前覆盖图遍历对象，已包含图节点缓存快照。
    config: planner 配置，约束过滤功能开关与阈值。

  Returns:
    包含 enable、threshold、命中计数与过滤后计数的字典。
  """
  # 使用 graph_access 当前快照聚合统计，避免过滤后再二次查询导致口径漂移。
  graph_cells = list(graph_access.coverage_graph.cells)
  return {
    "enable": bool(config.node_obstacle_ratio_filter_enable),
    "threshold": float(config.node_obstacle_ratio_threshold),
    "checked_node_count": int(sum(
      1
      for cell in graph_cells
      if cell.obstacle_ratio is not None
    )),
    "filtered_node_count": int(sum(
      1
      for cell in graph_cells
      if cell.obstacle_ratio_filtered
    )),
  }


def planner_metadata_payload(
  *,
  paths: PlannerArtifactPaths,
  config: PlannerConfig,
  map_resolution: float,
  map_origin: tuple[float, float],
  coverage_width_px: int,
  rotation_angle: float,
  rotation_matrix: np.ndarray,
  full_rotation_matrix: np.ndarray,
  full_bounding_rect: tuple[int, int, int, int],
  crop_rect: tuple[int, int, int, int],
  rotated_crop_offset_px: tuple[int, int],
  full_rotated_shape: tuple[int, int],
  local_direction_confidence: np.ndarray,
  rotated_room_map: np.ndarray,
  local_direction_source: str,
  rotated_edge_label_map: np.ndarray | None,
  semantic_path_payload: dict[str, Any] | None,
  node_semantics_payload: dict[str, Any] | None,
  jump_cleanup_result: Any,
  final_path_transform_records: Sequence[dict[str, Any]],
  pipeline_trace: Sequence[PipelineStageRecord],
  chosen_start_pixel: tuple[int, int],
  pixel_points_raw: Sequence[tuple[float, float]],
  world_path: list[dict[str, float | int]],
  pixel_segments: Sequence[Sequence[tuple[float, float]]],
  jump_segments: Sequence[tuple[tuple[float, float], tuple[float, float]]],
  fallback_debug_trace: list[dict[str, Any]],
  candidate_decision_debug_trace: list[dict[str, Any]],
  traversal_move_trace: Sequence[dict[str, Any]],
  region_mask: np.ndarray | None,
  planning_room_map: np.ndarray,
  graph_access: Any,
) -> dict[str, Any]:
  """构造 metadata.json 的统一摘要。

  约束：
  - 仅存储运行态可复核参数，不接收临时计算对象；
  - 指标全部围绕 map_resolution 与 path 事实统一口径，避免单位混淆。
  """
  # 元数据集中统一口径输出，便于仅凭 metadata 一份文件完成回放复核。
  planner_params = config.planner_params_dict()
  strategy_dict = config.strategy.to_dict()
  local_direction_dict = config.local_direction.to_dict()
  return {
    "map_resolution": map_resolution,
    "map_origin": {"x": map_origin[0], "y": map_origin[1]},
    "coverage_width_m": config.coverage_width_m,
    "coverage_width_px": coverage_width_px,
    "rotation_angle_rad": rotation_angle,
    "rotated_frame": {
      "frame_id": "cropped_rotated_room",
      "semantics": "graph, traversal, direction field, and *_rotated debug fields use cropped rotated coordinates; final path_pixels/path_world and node_debug planning_point_pixel use original image/world coordinates",
      "crop_rect_in_full_rotated_px": [int(value) for value in crop_rect],
      "crop_offset_in_full_rotated_px": [
        int(rotated_crop_offset_px[0]),
        int(rotated_crop_offset_px[1]),
      ],
      "cropped_shape": [int(rotated_room_map.shape[0]), int(rotated_room_map.shape[1])],
      "full_rotated_shape": [int(full_rotated_shape[0]), int(full_rotated_shape[1])],
      "full_bounding_rect": [int(value) for value in full_bounding_rect],
      "original_to_full_rotated_matrix": full_rotation_matrix.tolist(),
    },
    "rotation_matrix": rotation_matrix.tolist(),
    "local_direction": {
      **local_direction_dict,
      "source": local_direction_source,
      "semantics": "undirected_axis_mod_pi",
      "mean_confidence": float(local_direction_confidence[rotated_room_map == 255].mean())
      if np.any(rotated_room_map == 255)
      else 0.0,
    },
    "ctg_guidance": config.ctg_guidance.to_dict(),
    "node_obstacle_ratio_filter": node_obstacle_ratio_filter_metadata(
      graph_access=graph_access,
      config=config,
    ),
    "rotated_edge_label_enabled": rotated_edge_label_map is not None,
    "external_junction_label_enabled": config.external_junction_label_map is not None,
    "semantic_path": semantic_path_payload["summary"] if semantic_path_payload is not None else {"enabled": False},
    "node_semantics": node_semantics_payload["summary"] if node_semantics_payload is not None else {"enabled": False},
    "isolated_jump_cleanup": jump_cleanup_result.to_summary_dict(map_resolution),
    "final_path_transform_records": [
      dict(record)
      for record in final_path_transform_records
    ],
    "pipeline_trace": pipeline_trace_payload(pipeline_trace),
    "strategy": strategy_dict,
    "start_pixel": {"x": chosen_start_pixel[0], "y": chosen_start_pixel[1]},
    "path_points_raw": len(pixel_points_raw),
    "path_points": len(world_path),
    "path_segment_count": len(pixel_segments),
    "path_jump_segment_count": len(jump_segments),
    "fallback_debug_event_count": len(fallback_debug_trace),
    "candidate_decision_debug": {
      "available": True,
      "path": str(paths.candidate_decision_debug),
      "event_count": int(len(candidate_decision_debug_trace)),
    },
    "path_generation_provenance_count": len(traversal_move_trace),
    "region_polygon": [[int(x), int(y)] for x, y in (config.region_polygon or [])],
    "planning_area_pixel_count": int(np.count_nonzero(region_mask == 255)) if region_mask is not None else None,
    "planning_free_pixel_count": int(np.count_nonzero(planning_room_map == 255)),
  }
