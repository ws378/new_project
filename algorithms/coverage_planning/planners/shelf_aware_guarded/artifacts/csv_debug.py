"""能量规划调试 CSV 写出。

用于生成可人工阅读的离散节点快照，供回放复核时做
“路径点—节点属性—是否已访问”对照验证。
"""

from __future__ import annotations

import csv
from typing import Any
from pathlib import Path
import cv2
import numpy as np

from ..geometry.room_rotation import transform_points


def save_debug_csv(
  csv_path: Path,
  graph_access: Any,
  visited_points: set[tuple[int, int]],
  rotated_room_map: np.ndarray,
  map_resolution: float,
  inverse_rotation: np.ndarray,
  min_room: tuple[int, int],
  max_room: tuple[int, int],
  map_origin: tuple[float, float],
  map_height: int,
) -> None:
  """把覆盖图节点级调试信息写为 CSV。

  只写出非障碍且在 ROI 内的节点，减少无关记录，降低人工排查成本。
  遇到非法索引时降级为 0，避免导出阶段因边界异常中断。
  """
  # 预先计算距离图，避免在循环内重复做像素级距离变换。
  dist_map = cv2.distanceTransform(rotated_room_map, cv2.DIST_L2, 3)
  with csv_path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow([
      "node_id",
      "grid_row",
      "grid_col",
      "planning_point_px_rotated_x",
      "planning_point_px_rotated_y",
      "grid_center_px_rotated_x",
      "grid_center_px_rotated_y",
      "adjusted_from_grid_center_px",
      "generated_planning_point_px_rotated_x",
      "generated_planning_point_px_rotated_y",
      "generation_offset_from_grid_center_px_x",
      "generation_offset_from_grid_center_px_y",
      "generation_offset_distance_px",
      "generation_mode",
      "generation_status",
      "endpoint_alignment_applied",
      "endpoint_alignment_offset_px_x",
      "endpoint_alignment_offset_px_y",
      "obstacle_ratio",
      "obstacle_ratio_filtered",
      "x",
      "y",
      "status",
      "obstacle_neighbor_count",
      "non_obstacle_neighbor_count",
      "min_distance_m",
    ])
    for cell in graph_access.coverage_graph.cells:
      planning_point_px = (int(cell.planning_point_px[0]), int(cell.planning_point_px[1]))
      grid_center_px = (int(cell.grid_center_px[0]), int(cell.grid_center_px[1]))
      # 障碍节点不会进入覆盖路径，也不会作为调试主线条目。
      if cell.obstacle:
        continue
      # 仅保留地图窗口内节点，避免无效像素污染调试结果。
      if not (min_room[0] <= planning_point_px[0] <= max_room[0] and min_room[1] <= planning_point_px[1] <= max_room[1]):
        continue
      transformed = transform_points([(planning_point_px[0], planning_point_px[1])], inverse_rotation)[0]
      x_world = transformed[0] * map_resolution + map_origin[0]
      y_world = (map_height - transformed[1]) * map_resolution + map_origin[1]
      # 用 0/1 而不是 bool，减少外部统计脚本兼容问题。
      status = 1 if planning_point_px in visited_points else 0
      obstacle_neighbors = int(len(cell.neighbor_cell_ids) - len(cell.accessible_neighbor_cell_ids))
      # 距离图存在边界风险，越界时降级成 0，保障导出过程可复现。
      if 0 <= planning_point_px[1] < dist_map.shape[0] and 0 <= planning_point_px[0] < dist_map.shape[1]:
        d_m = float(dist_map[planning_point_px[1], planning_point_px[0]]) * map_resolution
      else:
        d_m = 0.0
      writer.writerow([
        str(cell.cell_id),
        int(cell.grid_row),
        int(cell.grid_col),
        int(planning_point_px[0]),
        int(planning_point_px[1]),
        int(grid_center_px[0]),
        int(grid_center_px[1]),
        int(bool(cell.adjusted_from_grid_center_px)),
        int(cell.generated_planning_point_px[0]),
        int(cell.generated_planning_point_px[1]),
        int(cell.generation_offset_from_grid_center_px[0]),
        int(cell.generation_offset_from_grid_center_px[1]),
        f"{float(cell.generation_offset_distance_px):.6f}",
        str(cell.generation_mode),
        str(cell.generation_status),
        int(bool(cell.endpoint_alignment_applied)),
        int(cell.endpoint_alignment_offset_px[0]),
        int(cell.endpoint_alignment_offset_px[1]),
        "" if cell.obstacle_ratio is None else f"{float(cell.obstacle_ratio):.6f}",
        int(bool(cell.obstacle_ratio_filtered)),
        f"{x_world:.6f}",
        f"{y_world:.6f}",
        status,
        obstacle_neighbors,
        int(len(cell.accessible_neighbor_cell_ids)),
        f"{d_m:.6f}",
      ])
