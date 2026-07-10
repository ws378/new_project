"""房间旋转与坐标变换工具。

主流程在旋转后的坐标系里生成规则清扫路径；主流程结束后统一反变换回原图坐标。
本模块统一维护旋转矩阵与路径点变换，避免几何实现分散在 planner 里。
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

import cv2
import numpy as np


def get_min_max_coordinates(room_map: np.ndarray) -> Tuple[Tuple[int, int], Tuple[int, int]]:
  """提取可通行区域边界框，供旋转与重采样对齐。

  只围绕 free 区域求边界，避免外部空白把旋转中心偏移到地图外侧。
  """

  # 仅围绕可通行像素算 bbox，避免空白边缘把旋转中心拉偏。
  ys, xs = np.where(room_map == 255)
  if len(xs) == 0:
    raise ValueError("地图中没有可通行像素")
  return (int(xs.min()), int(ys.min())), (int(xs.max()), int(ys.max()))


def compute_room_main_direction(room_map: np.ndarray, map_resolution: float) -> float:
  """估计 room 的主方向角，用于统一旋转到规则网格坐标系。"""

  # 先提边缘再做 Hough，主方向对噪声更稳，减少单条伪边界误导。
  edge_map = cv2.Canny(room_map, 50, 150, apertureSize=3)
  lines = None
  min_line_length = 1.0
  map_resolution_inverse = 1.0 / map_resolution
  while min_line_length > 0.1:
    # 阈值按米转像素归一化，保证不同地图分辨率下 Hough 判别口径一致。
    detected = cv2.HoughLinesP(
      edge_map,
      rho=1,
      theta=np.pi / 180.0,
      threshold=max(1, int(min_line_length * map_resolution_inverse)),
      minLineLength=max(1, int(min_line_length * map_resolution_inverse)),
      maxLineGap=max(1, int(1.5 * min_line_length * map_resolution_inverse)),
    )
    # 至少 4 条线时才认为方向足够稳，减少偶发噪声线主导。
    if detected is not None and len(detected) >= 4:
      lines = detected[:, 0, :]
      break
    # 小房间或边缘缺段时降级阈值，避免方向估计因输入稀疏直接中断。
    min_line_length -= 0.2

  if lines is None:
    # 估计失败时回退 0，保证流程仍可继续而不是因主方向缺失中断。
    return 0.0

  # 折叠到 [0, π] 后再投票，避免 180° 镜像差异导致主轴翻倍判断。
  bins = np.linspace(0.0, np.pi, 37)
  weights = np.zeros(36, dtype=np.float64)
  for x1, y1, x2, y2 in lines:
    dx = float(x2 - x1)
    dy = float(y2 - y1)
    length = math.hypot(dx, dy)
    # 长度 0 代表重复采样点，不参与主方向统计。
    if length == 0.0:
      continue
    direction = math.atan2(dy, dx)
    # 方向去符号后比较同一主轴，避免把反向线段当作两类方向分裂。
    while direction < 0.0:
      direction += np.pi
    while direction > np.pi:
      direction -= np.pi
    index = min(35, np.digitize(direction, bins) - 1)
    # 长线段权重更高，减少短边缘碎片带来的方向抖动。
    weights[index] += length

  max_index = int(np.argmax(weights))
  # 用桶中点回传角度，保证相同输入的离散可复现性。
  return float((bins[max_index] + bins[max_index + 1]) * 0.5)


def compute_room_rotation(room_map: np.ndarray, map_resolution: float) -> Tuple[float, np.ndarray, Tuple[int, int, int, int]]:
  """计算 room 旋转矩阵与旋转后画布 bbox。

  返回的是用于后续 warpAffine 的统一仿射矩阵和 bbox，后处理阶段按该尺寸回写像素。
  """

  rotation_angle = compute_room_main_direction(room_map, map_resolution)
  min_room, max_room = get_min_max_coordinates(room_map)
  # 以可通行 bbox 中心为旋转中心，抑制地图外空白导致的平移跳变。
  center = (
    0.5 * (min_room[0] + max_room[0]),
    0.5 * (min_room[1] + max_room[1]),
  )
  rotation_degrees = rotation_angle * 180.0 / np.pi
  rotation_matrix = cv2.getRotationMatrix2D(center, rotation_degrees, 1.0)

  # 先算外接矩形，确保旋转后的图像完整纳入新画布。
  height, width = room_map.shape[:2]
  corners = np.array(
    [[0, 0], [width, 0], [width, height], [0, height]],
    dtype=np.float32,
  )
  rotated_corners = cv2.transform(np.array([corners]), rotation_matrix)[0]
  x, y, w, h = cv2.boundingRect(rotated_corners.astype(np.float32))
  # 平移项对齐到矩形中心，便于后续 warpAffine 与 transform 使用同一几何基准。
  rotation_matrix[0, 2] += 0.5 * w - center[0]
  rotation_matrix[1, 2] += 0.5 * h - center[1]
  return rotation_angle, rotation_matrix, (x, y, w, h)


def rotate_room(room_map: np.ndarray, rotation_matrix: np.ndarray, bounding_rect: Tuple[int, int, int, int]) -> np.ndarray:
  """按给定仿射矩阵旋转 room，保持离散语义值不被插值污染。"""

  # 最近邻插值保留二值语义，避免标签/占据信息被插值平均污染。
  _, _, width, height = bounding_rect
  rotated = cv2.warpAffine(
    room_map,
    rotation_matrix,
    (width, height),
    flags=cv2.INTER_NEAREST,
    borderMode=cv2.BORDER_CONSTANT,
    borderValue=0,
  )
  return rotated


def transform_points(points: Sequence[Tuple[float, float]], matrix: np.ndarray) -> List[Tuple[float, float]]:
  """应用仿射矩阵变换一组点，并输出 Python tuple 供后续流水线使用。"""

  # 统一用 OpenCV transform 接口可避免自行拼接齐次坐标导致的偏移误差。
  if not points:
    return []
  array = np.array(points, dtype=np.float32).reshape(-1, 1, 2)
  transformed = cv2.transform(array, matrix).reshape(-1, 2)
  return [(float(x), float(y)) for x, y in transformed]


def invert_affine_transform(matrix: np.ndarray) -> np.ndarray:
  """计算仿射矩阵逆矩阵，用于从旋转坐标系回到原图坐标。"""

  # 使用 OpenCV 求逆，避免手工求逆带来的数值漂移与坐标偏差。
  return cv2.invertAffineTransform(matrix)


def point_path_to_pose_path(points: Sequence[Tuple[float, float]]) -> List[Tuple[float, float, float]]:
  """将二维路径点序列转为 pose 序列，姿态由邻接点方向估计。"""

  # 仅在有稳定方向时产生 pose，避免孤立点产生 0 向量扰动执行器。
  poses: List[Tuple[float, float, float]] = []
  for index, current_point in enumerate(points):
    # 每个点都尝试构造与前后点连接的方向向量，缺失方向时保守跳过该点。
    vector = (0.0, 0.0)
    if index > 0:
      # 与前一点连线给出方向，可保证段内朝向连续，避免突变点。
      previous_point = points[index - 1]
      vector = (current_point[0] - previous_point[0], current_point[1] - previous_point[1])
    elif len(points) >= 2:
      # 起点缺前驱时用后继方向，避免首点出现 0 向量。
      next_point = points[index + 1]
      vector = (next_point[0] - current_point[0], next_point[1] - current_point[1])

    # 方向为零向量说明该点无法贡献姿态，不输出 pose 防止下游出现错误停顿。
    if vector[0] != 0.0 or vector[1] != 0.0:
      theta = math.atan2(vector[1], vector[0])
      poses.append((float(current_point[0]), float(current_point[1]), float(theta)))
  return poses
