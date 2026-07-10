"""局部方向场可视化。

仅用于人工检查方向场质量，不参与规划决策。
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np


def visualize_local_direction(
  rotated_room_map: np.ndarray,
  direction_map: np.ndarray,
  confidence_map: np.ndarray,
  coverage_width_px: int,
  output_path: Path,
) -> None:
  """生成局部方向场调试图并写入磁盘。

  仅在低置信度区域抑制绘制，避免把边界噪声误解成有效航向信息。
  """
  debug_image = cv2.cvtColor(rotated_room_map, cv2.COLOR_GRAY2BGR)
  # 网格步长按覆盖宽度约束显示密度，兼顾可读性与性能。
  step = max(10, coverage_width_px)
  line_len = max(6, int(round(step * 0.45)))

  for y in range(step // 2, rotated_room_map.shape[0], step):
    for x in range(step // 2, rotated_room_map.shape[1], step):
      if rotated_room_map[y, x] != 255:
        # 只在可通行区域画方向场，防止障碍区噪声被误读为航向信息。
        continue
      confidence = float(confidence_map[y, x])
      if confidence < 0.08:
        # 低置信度舍弃可避免在边界抖动区域输出无意义箭头。
        continue
      angle = float(direction_map[y, x])
      dx = int(round(math.cos(angle) * line_len))
      dy = int(round(math.sin(angle) * line_len))
      color_scale = int(round(80 + 175 * min(1.0, confidence)))
      cv2.line(debug_image, (x - dx, y - dy), (x + dx, y + dy), (0, color_scale, 255 - color_scale // 3), 1)
      cv2.circle(debug_image, (x, y), 1, (255, 255, 0), -1)

  cv2.imwrite(str(output_path), debug_image)
