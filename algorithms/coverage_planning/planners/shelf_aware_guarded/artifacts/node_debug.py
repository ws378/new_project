"""节点和候选点调试载荷构造。

把 traversal 的节点状态映射为可回放 JSON，供 node_debug_enriched 的离线分析。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..geometry.room_rotation import transform_points
from ..traversal_core.traversal_debug_payloads import (
  candidate_debug_payload,
  collect_unvisited_node_ids,
  node_debug_payload,
)


def save_node_debug_json(
  json_path: Path,
  rotated_room_map: np.ndarray,
  map_resolution: float,
  inverse_rotation: np.ndarray,
  map_origin: tuple[float, float],
  map_height: int,
  *,
  graph_access: Any,
  traversal_state: Any,
) -> None:
  """导出覆盖节点调试载荷。

  输出内容用于 node_debug_enriched，保持与 graph 的节点状态一致，不参与策略计算。
  """
  # 写入前一次性计算距离图，供每个节点复用，减少导出阶段重复计算。
  # 只在当前图像上计算一次距离变换，节点记录复用，避免重复耗时。
  dist_map = cv2.distanceTransform(rotated_room_map, cv2.DIST_L2, 3)
  payload = []
  for cell in graph_access.coverage_graph.cells:
    # 复用 node_debug_payload 保证字段一致性；collect 的信息可直接用于回放脚本归档。
    item = node_debug_payload(
      str(cell.cell_id),
      include_neighbors=True,
      traversal_state=traversal_state,
      graph_access=graph_access,
    )
    planning_point_px = graph_access.planning_point_px_for_cell(str(cell.cell_id))
    planning_x = int(planning_point_px[0])
    planning_y = int(planning_point_px[1])
    transformed = transform_points([(planning_x, planning_y)], inverse_rotation)[0]
    item["planning_point_pixel"] = [float(transformed[0]), float(transformed[1])]
    item["planning_point_world"] = [
      float(transformed[0] * map_resolution + map_origin[0]),
      float((map_height - transformed[1]) * map_resolution + map_origin[1]),
    ]
    item["min_distance_m"] = float(dist_map[planning_y, planning_x]) * map_resolution if not item["obstacle"] else 0.0
    payload.append(item)
  json_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
