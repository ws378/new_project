"""区域多边形 mask 构造。"""

from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np


Point = tuple[int, int]


def polygon_to_mask(shape: tuple[int, int], polygon_points: Sequence[Point]) -> np.ndarray:
  """将 polygon 点序列转换为二值掩码。
  
  当点数不足时返回空掩码，避免 cv2.fillPoly 因异常输入抛错影响调用链。
  
  Args:
      shape: 目标掩码尺寸（height, width）。
      polygon_points: 输入多边形点集。
      
  Returns:
      np.ndarray: uint8 掩码，free 区域填充为 255。
  """
  mask = np.zeros(shape, dtype=np.uint8)
  if len(polygon_points) < 3:
    return mask
  polygon = np.array(polygon_points, dtype=np.int32)
  cv2.fillPoly(mask, [polygon], 255)
  return mask
