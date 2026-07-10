"""节点和路径调试图渲染。

模块职责仅限渲染，不修改 planner 输入状态与核心路径。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .path_visualization import draw_coverage_path

NEAREST_RESAMPLE = getattr(getattr(Image, "Resampling", Image), "NEAREST")


def save_rotated_room_map_visual(rotated_room_map: np.ndarray, output_path: Path) -> None:
  """保存旋转后的栅格地图可视化图。

  这里直接写灰度数组，作为调试图的基础底图，供后续 overlay 复用。
  """
  cv2.imwrite(str(output_path), rotated_room_map)


def visualize_nodes_and_path(
  rotated_room_map: np.ndarray,
  original_room_map: np.ndarray,
  graph_access: Any,
  pixel_poses: Sequence[tuple[float, float, float]],
  pixel_segments: Sequence[Sequence[tuple[float, float]]],
  jump_segments: Sequence[tuple[tuple[float, float], tuple[float, float]]],
  output_nodes_path: Path,
  output_overlay_path: Path,
) -> None:
  """将覆盖图节点与路径 overlay 分别落盘到两张图。

  图像绘制在可视化层完成，不改变 planner 输出状态或路径语义。
  """
  # 节点层与路径层分离保存，便于单独检查节点稀疏性和路径完整性。
  nodes_image = cv2.cvtColor(rotated_room_map, cv2.COLOR_GRAY2BGR)
  # 先绘制节点状态：红色可见更容易和路径分离，便于人工检查图上孤立点。
  for cell in graph_access.coverage_graph.cells:
    color = (0, 90, 220) if cell.obstacle else (0, 200, 0)
    radius = 1 if cell.obstacle else 2
    cv2.circle(nodes_image, (int(cell.planning_point_px[0]), int(cell.planning_point_px[1])), radius, color, -1)
  cv2.imwrite(str(output_nodes_path), nodes_image)

  overlay = cv2.cvtColor(original_room_map, cv2.COLOR_GRAY2BGR)
  # 仅在有路径时绘制 overlay 图，避免空路径污染图像文件。
  if pixel_poses:
    path_points = np.array([[int(round(x)), int(round(y))] for x, y, _ in pixel_poses], dtype=np.int32)
    draw_coverage_path(
      overlay,
      [tuple(point) for point in path_points.tolist()],
      [
        [(int(round(x)), int(round(y))) for x, y in segment]
        for segment in pixel_segments
      ],
      [
        (
          (int(round(start_point[0])), int(round(start_point[1]))),
          (int(round(end_point[0])), int(round(end_point[1]))),
        )
        for start_point, end_point in jump_segments
      ],
      sweep_thickness=1,
      jump_thickness=1,
      label_every=10,
    )
  cv2.imwrite(str(output_overlay_path), overlay)


def visualize_node_obstacle_ratio_filter(
  rotated_room_map: np.ndarray,
  graph_access: Any,
  output_path: Path,
) -> None:
  """画出障碍比例过滤后的节点状态，沿用节点段诊断图的裁剪放大风格。"""

  # 当无可检验节点时，仍落盘一张无过滤覆盖图，保持产物链完整。
  checked_nodes = [
    cell
    for cell in graph_access.coverage_graph.cells
    if cell.obstacle_ratio is not None
  ]
  if not checked_nodes:
    cv2.imwrite(str(output_path), cv2.cvtColor(rotated_room_map, cv2.COLOR_GRAY2BGR))
    return

  xs = [int(round(cell.planning_point_px[0])) for cell in checked_nodes]
  ys = [int(round(cell.planning_point_px[1])) for cell in checked_nodes]
  margin = 40
  x0 = max(0, min(xs) - margin)
  y0 = max(0, min(ys) - margin)
  x1 = min(rotated_room_map.shape[1], max(xs) + margin + 1)
  y1 = min(rotated_room_map.shape[0], max(ys) + margin + 1)

  crop = rotated_room_map[y0:y1, x0:x1]
  rgb = np.zeros((crop.shape[0], crop.shape[1], 3), dtype=np.uint8)
  rgb[crop == 255] = (245, 245, 245)
  rgb[crop != 255] = (0, 0, 0)

  scale = 4
  image = Image.fromarray(rgb).resize(
    (rgb.shape[1] * scale, rgb.shape[0] * scale),
    NEAREST_RESAMPLE,
  )
  draw = ImageDraw.Draw(image)
  try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
    title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
  except Exception:
    font = ImageFont.load_default()
    title_font = ImageFont.load_default()

  filtered_count = sum(1 for cell in checked_nodes if cell.obstacle_ratio_filtered)
  draw.rectangle((0, 0, image.width - 1, 18), fill=(255, 255, 255))
  draw.text(
    (4, 2),
    f"node obstacle ratio filter: blue=kept red=filtered filtered={filtered_count}",
    fill=(0, 0, 0),
    font=title_font,
  )

  for cell in graph_access.coverage_graph.cells:
    if cell.obstacle_ratio is None:
      continue
    px = (int(round(cell.planning_point_px[0])) - x0) * scale
    py = (int(round(cell.planning_point_px[1])) - y0) * scale
    if px < 0 or py < 0 or px >= image.width or py >= image.height:
      continue
    label = f"{int(cell.grid_row)}:{int(cell.grid_col)}"
    if cell.obstacle_ratio_filtered:
      color = (255, 0, 0)
      radius = 3
    else:
      color = (0, 90, 255)
      radius = 2
    draw.ellipse(
      (px - radius, py - radius, px + radius, py + radius),
      fill=color,
    )
    draw.text(
      (px + 3, py - 5),
      label,
      fill=color,
      font=font,
    )
  image.save(output_path)
