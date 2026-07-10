"""路径类产物载荷工具。

所有路径载荷均输出 1 起始索引，便于与图像与外部调试脚本保持一致。
"""

from __future__ import annotations

from typing import Sequence


def indexed_points_payload(points: Sequence[tuple[float, float]]) -> list[dict[str, float | int]]:
  """将二维点列表转为带 index 的 JSON 结构。

  约束为 1-based index，维持外部脚本和历史产物口径一致。
  """
  # index 从 1 开始是为了与现有外部脚本及调试表述一致，减少人工对齐成本。
  return [{"index": index + 1, "x": x, "y": y} for index, (x, y) in enumerate(points)]


def path_pixels_payload(pixel_poses: Sequence[tuple[float, float, float]]) -> list[dict[str, float | int]]:
  """将像素级 pose 列表转为可序列化字典数组。

  同时保留 index 与 theta，避免后续从坐标反推出朝向时产生歧义。
  """
  # 同步对 index、坐标、朝向一起落库，避免后续组装时再倒推缺省值。
  return [
    {"index": index + 1, "x": x, "y": y, "theta": theta}
    for index, (x, y, theta) in enumerate(pixel_poses)
  ]


def path_segments_pixels_payload(
  *,
  pixel_points: Sequence[tuple[float, float]],
  pixel_segment_indices: Sequence[Sequence[int]],
) -> list[list[dict[str, float | int]]]:
  """按 segment 索引将像素点组装成多段轨迹。

  输入是全局点编号索引，可直接映射回共享的像素点列表，避免复制坐标字段。
  """
  # segment 索引使用全局 1 起始，保持与其他 payload 的坐标口径统一。
  return [
    [
      {
        "index": point_index,
        "x": pixel_points[point_index - 1][0],
        "y": pixel_points[point_index - 1][1],
      }
      for point_index in group
    ]
    for group in pixel_segment_indices
  ]


def path_jump_segments_pixels_payload(
  *,
  pixel_points: Sequence[tuple[float, float]],
  jump_segment_indices: Sequence[tuple[int, int]],
) -> list[list[dict[str, float | int]]]:
  """按跳变索引构建断续路径起止点载荷。

  只保存每段端点是有意为之：跳变段需要的是接续关系而非中间采样点。
  """
  # 只保留每段起止点索引，能保持跳变诊断轻量同时保留可追溯边界。
  return [
    [
      {
        "index": start_index,
        "x": pixel_points[start_index - 1][0],
        "y": pixel_points[start_index - 1][1],
      },
      {
        "index": end_index,
        "x": pixel_points[end_index - 1][0],
        "y": pixel_points[end_index - 1][1],
      },
    ]
    for start_index, end_index in jump_segment_indices
  ]
