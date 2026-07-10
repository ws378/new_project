"""区域 mask 和 overlay 调试图渲染。"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import cv2
import numpy as np

from .masks import Point, polygon_to_mask


def save_region_visualizations(
  original_room_map: np.ndarray,
  polygon_points: Sequence[Point],
  start_pixel: Point | None,
  region_mask_path: str,
  region_overlay_path: str,
  region_mask: np.ndarray | None = None,
) -> None:
  """输出区域可视化图像。
  
  当未提供 region_mask 时由 polygon 重建，避免输出函数依赖上游副产物。
  同时写入原图与 overlay，方便人工核对区域提取与变换结果。

  Args:
      original_room_map: 原始旋转图像（灰度）。
      polygon_points: 区域 polygon 点序列。
      start_pixel: 起点像素坐标，可为空。
      region_mask_path: mask 输出路径。
      region_overlay_path: overlay 输出路径。
      region_mask: 可选的已生成 mask。缺省时从 polygon 重建。
  """
  mask = (
    np.where(np.asarray(region_mask) > 0, 255, 0).astype(np.uint8)
    if region_mask is not None
    else polygon_to_mask(original_room_map.shape, polygon_points)
  )
  # 写图前先确保输出目录存在，避免中断时留下部分可视化缺失。
  Path(region_mask_path).parent.mkdir(parents=True, exist_ok=True)
  cv2.imwrite(region_mask_path, mask)

  overlay = cv2.cvtColor(original_room_map, cv2.COLOR_GRAY2BGR)
  # 有 region_mask 时直接用已知 mask 着色，避免重复重建导致可视化与原始 polygon 口径不同。
  if region_mask is not None:
    shaded = overlay.copy()
    shaded[mask > 0] = (0, 120, 255)
    overlay = cv2.addWeighted(shaded, 0.25, overlay, 0.75, 0.0)
  # polygon 至少 2 点时可画轮廓线，4 点以上才形成可闭合多边形。
  if len(polygon_points) >= 2:
    polygon = np.array(polygon_points, dtype=np.int32)
    cv2.polylines(overlay, [polygon], isClosed=len(polygon_points) >= 3, color=(0, 255, 255), thickness=2)
  # region_mask 未给出但 polygon 可靠时重建填充，保证可视化至少有一次可复现的参考底图。
  if region_mask is None and len(polygon_points) >= 3:
    shaded = overlay.copy()
    cv2.fillPoly(shaded, [np.array(polygon_points, dtype=np.int32)], (0, 120, 255))
    overlay = cv2.addWeighted(shaded, 0.25, overlay, 0.75, 0.0)
    cv2.polylines(
      overlay,
      [np.array(polygon_points, dtype=np.int32)],
      isClosed=True,
      color=(0, 255, 255),
      thickness=2,
    )
  # 每个 polygon 点都要可视化为锚点，方便核对点顺序与闭合误差。
  for point in polygon_points:
    cv2.circle(overlay, (int(point[0]), int(point[1])), 4, (0, 255, 0), -1)
  # 起点高亮用于复核外部输入是否被正确吸附到区域内。
  if start_pixel is not None:
    cv2.circle(overlay, (int(start_pixel[0]), int(start_pixel[1])), 6, (255, 0, 0), -1)
  cv2.imwrite(region_overlay_path, overlay)
