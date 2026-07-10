"""遍历与最终路径段 provenance 载荷工具。

该模块把 traversal move trace 与最终几何路径对齐，生成可追溯的来源证据，
用于定位“路径段是如何产生的”。
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Sequence

import cv2
import numpy as np

from ..traversal_core.traversal_roles import (
  EDGE_ROLE_DERIVED_FINAL_SEGMENT,
  MOVE_SOURCE_DERIVED_FINAL_PATH,
  RAW_EDGE_ROLE_VALUES,
  RAW_MOVE_SOURCE_VALUES,
)
from .schema_registry import FINAL_SEGMENT_PROVENANCE_VERSION, TRAVERSAL_MOVE_TRACE_VERSION


FINAL_SEGMENT_SOURCE_POLICY_TRAVERSAL_MOVE_TRACE = "traversal_move_trace"
FINAL_SEGMENT_SOURCE_POLICY_FINAL_PATH_GEOMETRY = "final_path_geometry"
FINAL_SEGMENT_SOURCE_POLICY_VALUES = (
  FINAL_SEGMENT_SOURCE_POLICY_TRAVERSAL_MOVE_TRACE,
  FINAL_SEGMENT_SOURCE_POLICY_FINAL_PATH_GEOMETRY,
)

FINAL_SEGMENT_EVIDENCE_LEVEL_MATCHED_TRAVERSAL_EDGE = "matched_traversal_edge"
FINAL_SEGMENT_EVIDENCE_LEVEL_FINAL_SEGMENT_SIDECAR = "final_segment_sidecar"
FINAL_SEGMENT_EVIDENCE_LEVEL_VALUES = (
  FINAL_SEGMENT_EVIDENCE_LEVEL_MATCHED_TRAVERSAL_EDGE,
  FINAL_SEGMENT_EVIDENCE_LEVEL_FINAL_SEGMENT_SIDECAR,
)

FINAL_SEGMENT_SOURCE_PATH_ARTIFACT = "path_pixels.json"
FINAL_SEGMENT_SOURCE_MOVE_TRACE_ARTIFACT = "path_generation_provenance.json"


def _point_payload_from_rotated(
  point: Sequence[float] | None,
  *,
  inverse_rotation: np.ndarray,
) -> dict[str, float] | None:
  """把旋转坐标系中的点转换回原图坐标并返回可序列化结构。

  下游分析通常以原图像素坐标为起点复核，因此在源头补齐坐标对照。
  """
  if point is None:
    return None
  transformed = cv2.transform(
    np.asarray([[[float(point[0]), float(point[1])]]], dtype=np.float32),
    inverse_rotation,
  )[0][0]
  return {
    "rotated_x": float(point[0]),
    "rotated_y": float(point[1]),
    "pixel_x": float(transformed[0]),
    "pixel_y": float(transformed[1]),
  }


def _move_trace_items_payload(
  move_trace: Sequence[dict[str, Any]],
  *,
  inverse_rotation: np.ndarray,
) -> list[dict[str, Any]]:
  """将 traversal move trace 统一反投影后打包。

  这样可以让 payload 消费方直接使用原图坐标，不再重复执行 transform。
  """
  # 先统一做坐标反变换，payload 下游直接消费，避免重复转换逻辑分散。
  payload: list[dict[str, Any]] = []
  for item in move_trace:
    payload.append(
      {
        **item,
        "from_point": _point_payload_from_rotated(
          item.get("from_point_rotated_px"),
          inverse_rotation=inverse_rotation,
        ),
        "to_point": _point_payload_from_rotated(
          item.get("to_point_rotated_px"),
          inverse_rotation=inverse_rotation,
        ),
      }
    )
  return payload


def path_generation_provenance_payload(
  traversal_move_trace: Sequence[dict[str, Any]],
  *,
  inverse_rotation: np.ndarray,
) -> dict[str, Any]:
  """输出原始 traversal move trace 的原始证据负载。"""
  return {
    "version": TRAVERSAL_MOVE_TRACE_VERSION,
    "coordinate_note": (
      "path_index aligns to raw fov_coverage_path before simplify/semantic/jump-cleanup; "
      "pixel coords are inverse-rotated to original image frame."
    ),
    "move_source_values": RAW_MOVE_SOURCE_VALUES,
    "edge_role_values": RAW_EDGE_ROLE_VALUES,
    "items": _move_trace_items_payload(traversal_move_trace, inverse_rotation=inverse_rotation),
  }


def _distance_px(a: Sequence[float], b: Sequence[float]) -> float:
  """计算两点的欧氏距离并返回 float。"""
  return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _transformed_move_segments(
  move_trace: Sequence[dict[str, Any]],
  *,
  inverse_rotation: np.ndarray,
) -> list[dict[str, Any]]:
  """反向映射 move trace 到原图坐标，只保留可追溯的位姿段。

  缺点是旋转源坐标为空时会被丢弃，以避免在后处理阶段把不完整输入当成有效来源。
  """
  # 只保留可反投影段，防止坐标缺失导致匹配误判为“无来源”。
  segments: list[dict[str, Any]] = []
  for item in move_trace:
    from_point = _point_payload_from_rotated(item.get("from_point_rotated_px"), inverse_rotation=inverse_rotation)
    to_point = _point_payload_from_rotated(item.get("to_point_rotated_px"), inverse_rotation=inverse_rotation)
    if from_point is None or to_point is None:
      continue
    segments.append(
      {
        "move_id": str(item.get("move_id", "")),
        "path_index": int(item.get("path_index", 0) or 0),
        "move_source": str(item.get("move_source", "unknown")),
        "edge_role": str(item.get("edge_role", "unknown")),
        "from_node_id": item.get("from_node_id"),
        "to_node_id": item.get("to_node_id"),
        "selected_energy": item.get("selected_energy"),
        "distance_px": item.get("distance_px"),
        "heading_rad": item.get("heading_rad"),
        "turn_angle_deg": item.get("turn_angle_deg"),
        "phase_candidate_count": item.get("phase_candidate_count"),
        "phase_energy_evaluated_candidate_count": item.get("phase_energy_evaluated_candidate_count"),
        "phase_accepted_candidate_count": item.get("phase_accepted_candidate_count"),
        "phase_rejected_before_energy_count": item.get("phase_rejected_before_energy_count"),
        "phase_candidate_rank": item.get("phase_candidate_rank"),
        "from_point_px": (float(from_point["pixel_x"]), float(from_point["pixel_y"])),
        "to_point_px": (float(to_point["pixel_x"]), float(to_point["pixel_y"])),
      }
    )
  return segments


def _match_final_segment_to_move_trace(
  start_xy: Sequence[float],
  end_xy: Sequence[float],
  move_segments: Sequence[dict[str, Any]],
  *,
  tolerance_px: float = 1.0,
) -> tuple[dict[str, Any] | None, float]:
  """按起止端点误差匹配最终段与 raw move 段。

  使用端点距离和作为匹配标准，可在不完整来源信息下保留可解释降级。
  """
  best_segment: dict[str, Any] | None = None
  best_error = float("inf")
  for segment in move_segments:
    error = (
      _distance_px(start_xy, segment["from_point_px"])
      + _distance_px(end_xy, segment["to_point_px"])
    )
    if error < best_error:
      best_error = error
      best_segment = segment
  if best_segment is None or best_error > float(tolerance_px):
    return None, best_error
  return best_segment, best_error


def _counter_dict(values: Sequence[str]) -> dict[str, int]:
  """统计枚举值出现频次，作为 segment 汇总统计。"""
  return {key: int(count) for key, count in sorted(Counter(values).items())}


def final_segment_provenance_payload(
  *,
  pixel_points: Sequence[tuple[float, float]],
  pixel_poses: Sequence[tuple[float, float, float]],
  traversal_move_trace: Sequence[dict[str, Any]],
  inverse_rotation: np.ndarray,
  map_resolution: float,
  semantic_path_payload: dict[str, Any] | None,
  jump_cleanup_result: Any,
) -> dict[str, Any]:
  """输出 final_path 逐段 provenance。

  优先从 raw traversal move trace 匹配段来源，匹配失败则回退到几何段来源，
  这样可以在对齐失败场景下仍保留可解释的降级产物。
  """
  items: list[dict[str, Any]] = []
  move_segments = _transformed_move_segments(traversal_move_trace, inverse_rotation=inverse_rotation)
  for segment_index, (start, end) in enumerate(zip(pixel_poses, pixel_poses[1:]), start=1):
    match, match_error = _match_final_segment_to_move_trace(
      (float(start[0]), float(start[1])),
      (float(end[0]), float(end[1])),
      move_segments,
    )
    generation_move = None
    source_policy = FINAL_SEGMENT_SOURCE_POLICY_FINAL_PATH_GEOMETRY
    evidence_level = FINAL_SEGMENT_EVIDENCE_LEVEL_FINAL_SEGMENT_SIDECAR
    move_source = MOVE_SOURCE_DERIVED_FINAL_PATH
    edge_role = EDGE_ROLE_DERIVED_FINAL_SEGMENT
    if match is not None:
      source_policy = FINAL_SEGMENT_SOURCE_POLICY_TRAVERSAL_MOVE_TRACE
      evidence_level = FINAL_SEGMENT_EVIDENCE_LEVEL_MATCHED_TRAVERSAL_EDGE
      move_source = str(match["move_source"])
      edge_role = str(match["edge_role"])
      generation_move = {
        "move_id": str(match["move_id"]),
        "path_index": int(match["path_index"]),
        "move_source": move_source,
        "edge_role": edge_role,
        "from_node_id": match["from_node_id"],
        "to_node_id": match["to_node_id"],
        "selected_energy": match["selected_energy"],
        "distance_px": match["distance_px"],
        "heading_rad": match["heading_rad"],
        "turn_angle_deg": match["turn_angle_deg"],
        "phase_candidate_count": match["phase_candidate_count"],
        "phase_energy_evaluated_candidate_count": match["phase_energy_evaluated_candidate_count"],
        "phase_accepted_candidate_count": match["phase_accepted_candidate_count"],
        "phase_rejected_before_energy_count": match["phase_rejected_before_energy_count"],
        "phase_candidate_rank": match["phase_candidate_rank"],
        "match_error_px": float(match_error),
      }
    items.append(
      {
        "segment_index": segment_index,
        "from_index": segment_index,
        "to_index": segment_index + 1,
        "from_point_px": {
          "x": float(start[0]),
          "y": float(start[1]),
          "theta": float(start[2]),
        },
        "to_point_px": {
          "x": float(end[0]),
          "y": float(end[1]),
          "theta": float(end[2]),
        },
        "source_policy": source_policy,
        "evidence_level": evidence_level,
        "move_source": move_source,
        "edge_role": edge_role,
        "generation_move": generation_move,
      }
    )
  matched_count = sum(1 for item in items if item["generation_move"] is not None)
  return {
    "version": FINAL_SEGMENT_PROVENANCE_VERSION,
    "coordinate_note": (
      "Segments align to final path_pixels.json after simplify/semantic/jump-cleanup; "
      "coordinates are original image pixels. generation_move is populated only when "
      "a final segment can be matched to the raw traversal move trace within 1 px."
    ),
    "source_path_artifact": FINAL_SEGMENT_SOURCE_PATH_ARTIFACT,
    "source_move_trace_artifact": FINAL_SEGMENT_SOURCE_MOVE_TRACE_ARTIFACT,
    "point_count": len(pixel_points),
    "segment_count": max(0, len(pixel_points) - 1),
    "map_resolution_m_per_px": float(map_resolution),
    "stage_summary": {
      "semantic_path": semantic_path_payload["summary"] if semantic_path_payload is not None else {"enabled": False},
      "isolated_jump_cleanup": jump_cleanup_result.to_summary_dict(map_resolution),
    },
    "source_summary": {
      "matched_traversal_segment_count": int(matched_count),
      "derived_final_geometry_segment_count": int(len(items) - matched_count),
      "move_source_counts": _counter_dict([str(item["move_source"]) for item in items]),
      "edge_role_counts": _counter_dict([str(item["edge_role"]) for item in items]),
    },
    "items": items,
  }
