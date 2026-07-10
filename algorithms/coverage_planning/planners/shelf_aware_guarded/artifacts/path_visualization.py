"""覆盖路径可视化绘制工具。

本模块只负责把最终路径、连续清扫段、跳变段和点序号画到给定图像上。
坐标转换由调用方通过 transform 注入，因此同一套绘制逻辑可用于原图和旋转图。
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from ..final_path.postprocess import draw_dashed_line

Point = Tuple[int, int]
Segment = Sequence[Point]
JumpSegment = Tuple[Point, Point]
TransformFn = Callable[[Point], Optional[Point]]


def _identity_transform(point: Point) -> Point:
  """默认变换：点已经在目标图像坐标系中时直接返回。"""
  return point


def _draw_polyline(
  image: np.ndarray,
  points: Sequence[Point],
  color: Tuple[int, int, int],
  thickness: int,
  transform: TransformFn,
) -> None:
  """按分段点列绘制连续线段。

  transform 允许上游把点先映射到目标坐标系，绘制层不关心源坐标系。
  """
  transformed = [transform(point) for point in points]
  # transform 返回 None 表示该点在目标图上不可投影，直接丢弃避免越界错误。
  transformed = [point for point in transformed if point is not None]
  if len(transformed) >= 2:
    cv2.polylines(image, [np.array(transformed, dtype=np.int32)], False, color, thickness)


def _draw_jump_segments(
  image: np.ndarray,
  jump_segments: Sequence[JumpSegment],
  color: Tuple[int, int, int],
  thickness: int,
  transform: TransformFn,
) -> None:
  """绘制跳变段，用虚线与连续线区分移动语义。"""
  for start_point, end_point in jump_segments:
    start = transform(start_point)
    end = transform(end_point)
    if start is None or end is None:
      continue
    draw_dashed_line(image, start, end, color, thickness=thickness)


def _draw_point_labels(
  image: np.ndarray,
  path_points: Sequence[Point],
  transform: TransformFn,
  step: int,
) -> None:
  """按固定步长绘制点序号。

  文本仅作为人工检视锚点，步长可控可避免长路径拥挤。
  """
  if step <= 0:
    return
  for point_index in range(step - 1, len(path_points), step):
    point = transform(path_points[point_index])
    if point is None:
      continue
    # 标号锚点略微偏移，避免文字完全压住路径点。
    label_anchor = (point[0] + 4, point[1] - 4)
    cv2.circle(image, point, 3, (255, 255, 0), -1)
    cv2.putText(
      image,
      str(point_index + 1),
      label_anchor,
      cv2.FONT_HERSHEY_SIMPLEX,
      0.35,
      (30, 30, 180),
      1,
      cv2.LINE_AA,
    )


def _draw_start_end_markers(image: np.ndarray, path_points: Sequence[Point], transform: TransformFn) -> None:
  """绘制起点与终点标记，便于快速确认路径方向。"""
  if not path_points:
    return
  start = transform(path_points[0])
  end = transform(path_points[-1])
  if start is not None:
    cv2.circle(image, start, 5, (0, 255, 255), -1)
  if end is not None:
    cv2.circle(image, end, 5, (255, 0, 255), -1)


def draw_coverage_path(
  image: np.ndarray,
  path_points: Sequence[Point],
  path_segments: Sequence[Segment],
  jump_segments: Sequence[JumpSegment],
  *,
  sweep_color: Tuple[int, int, int] = (0, 0, 255),
  jump_color: Tuple[int, int, int] = (255, 0, 0),
  sweep_thickness: int = 1,
  jump_thickness: int = 1,
  label_every: int = 10,
  draw_labels: bool = True,
  draw_start_end: bool = True,
  transform: Optional[TransformFn] = None,
) -> None:
  """在图像上原地绘制路径、跳变、标签与起止点。

  函数不返回新图，是为了让调用方在同一张图上组合其他标注后统一持久化。
  """
  # 按绘制顺序先画连续段、再画跳变，避免跳变线被连续线遮挡。
  point_transform = transform or _identity_transform
  for segment in path_segments:
    _draw_polyline(image, segment, sweep_color, sweep_thickness, point_transform)
  _draw_jump_segments(image, jump_segments, jump_color, jump_thickness, point_transform)
  if draw_labels:
    _draw_point_labels(image, path_points, point_transform, label_every)
  if draw_start_end:
    _draw_start_end_markers(image, path_points, point_transform)
