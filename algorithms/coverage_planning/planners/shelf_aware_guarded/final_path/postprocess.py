"""覆盖路径输出前的几何后处理工具。

职责是把遍历结果整理为“可执行、可诊断、可视化友好”的形态，不改写节点访问状态。
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

import cv2
import numpy as np

from ..models import StrategyConfig


def point_distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
  """像素平面两点距离，用于所有后处理几何判断。"""
  # 所有几何阈值在后处理阶段统一用像素口径，避免 m 与 px 混算产生偏差。
  return math.hypot(b[0] - a[0], b[1] - a[1])


def segment_angle_deg(a: Tuple[float, float], b: Tuple[float, float]) -> float:
  """返回两点在图像坐标系下的连线角度（度）。

  Args:
    a: 起点坐标。
    b: 终点坐标。

  Returns:
    float: 用 ``atan2`` 计算后的角度值，单位为度。
  """
  # 图像坐标系 y 轴向下，但相对转角只依赖同一坐标系内的 atan2 差值。
  return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def normalized_angle_deg(angle: float) -> float:
  """把角度归一到 [-180, 180]，便于阈值比较。"""
  # 若不归一，跨越 +/-180 的转角会被误判为大转向，影响短折返识别。
  while angle < -180.0:
    # 小于 -180 的情况加一圈，回到等价主值区间，避免误分段。
    angle += 360.0
  while angle > 180.0:
    # 大于 180 的情况减一圈，对齐最短转角判断口径。
    angle -= 360.0
  return angle


def turn_delta_deg(a: Tuple[float, float], b: Tuple[float, float], c: Tuple[float, float]) -> float:
  """计算 b 点处转角，保留有符号方向后的最小角差。"""
  # b 点处的转角：上一段 a->b 和下一段 b->c 的方向差。
  return normalized_angle_deg(segment_angle_deg(b, c) - segment_angle_deg(a, b))


def violates_shape_constraints(
  path_points: Sequence[Tuple[float, float]],
  candidate_point: Tuple[float, float],
  coverage_width_px: int,
  strategy_cfg: StrategyConfig,
) -> bool:
  """判断候选点是否应因短距大角折返而被剔除。"""
  # 剪枝只看最近两段，避免全路径回溯，控制在线插入路径的复杂度上限。
  if len(path_points) < 2:
    return False

  previous_point = path_points[-2]
  current_point = path_points[-1]
  incoming_turn_deg = abs(turn_delta_deg(previous_point, current_point, candidate_point))
  outgoing_dist = point_distance(current_point, candidate_point)
  incoming_dist = point_distance(previous_point, current_point)

  if (
    strategy_cfg.near_reverse_enable
    and outgoing_dist <= coverage_width_px * strategy_cfg.near_reverse_max_dist_factor
    and incoming_turn_deg >= strategy_cfg.near_reverse_prohibit_deg
  ):
    # 很短距离内接近掉头，通常会产生锯齿轨迹或控制器难以平滑执行的局部折返。
    return True

  if (
    strategy_cfg.short_zigzag_enable
    and max(incoming_dist, outgoing_dist) <= coverage_width_px * strategy_cfg.short_zigzag_seg_factor
    and incoming_turn_deg >= strategy_cfg.short_zigzag_prohibit_deg
  ):
    # 两段都很短且转角过大时，视为短锯齿，提前禁止进入候选。
    return True

  return False


def compute_transition_break(
  point_path: Sequence[Tuple[float, float]],
  current_index: int,
  coverage_width_px: int,
  strategy_cfg: StrategyConfig,
) -> bool:
  """判断是否需要在 current_index 处分段（转角/跳变阈值触发）。"""
  # 分段阈值同时影响可执行性（跳变提示）与诊断输出（jump segment 标注）。
  turn_deg = abs(turn_delta_deg(point_path[current_index - 2], point_path[current_index - 1], point_path[current_index]))
  jump_dist = point_distance(point_path[current_index - 1], point_path[current_index])
  return turn_deg >= strategy_cfg.split_turn_deg or jump_dist >= coverage_width_px * strategy_cfg.split_jump_dist_factor


def simplify_point_path(
  point_path: Sequence[Tuple[float, float]],
  coverage_width_px: int,
  strategy_cfg: StrategyConfig,
) -> List[Tuple[float, float]]:
  """反复剔除短距离大转角的中间点，降低路径抖动。"""
  # 不做全局重采样，避免影响长距离趋势，只修复局部“毛刺”和折返点。
  simplified = list(point_path)
  if not strategy_cfg.simplify_enable:
    # 简化开关关闭时保留原始路径，避免引入非预期抖动。
    return simplified

  # 任何一次迭代只处理一遍局部窗口，删点后进入下一轮可捕捉连锁抖点。
  changed = True
  while changed and len(simplified) >= 3:
    # 一轮仅处理一次扫描，所有点都重试后若仍可变化则继续下一轮。
    changed = False
    next_points = [simplified[0]]
    index = 1
    while index < len(simplified) - 1:
      # 滑窗覆盖前中后三点，局部满足条件则先标记删除后继续扫描。
      prev_point = next_points[-1]
      current_point = simplified[index]
      next_point = simplified[index + 1]
      seg_a = point_distance(prev_point, current_point)
      seg_b = point_distance(current_point, next_point)
      turn_deg = abs(turn_delta_deg(prev_point, current_point, next_point))
      if (
        max(seg_a, seg_b) <= coverage_width_px * strategy_cfg.simplify_short_seg_factor
        and turn_deg >= strategy_cfg.simplify_turn_deg
      ):
        # 简化后要重算局部三点关系，否则会遗漏连锁的噪点。
        changed = True
        index += 1
        continue
      next_points.append(current_point)
      index += 1
    next_points.append(simplified[-1])
    simplified = next_points
  return simplified


def split_point_path(
  point_path: Sequence[Tuple[float, float]],
  coverage_width_px: int,
  strategy_cfg: StrategyConfig,
) -> List[List[Tuple[float, float]]]:
  """按转角/跳变规则拆分为多个连续清扫段。"""
  # 单点段会被并回前一段，避免输出中出现无法执行的长度 1 段。
  if len(point_path) <= 2:
    # 两点以下无法构造完整段间断判断，直接返回不变。
    return [list(point_path)] if point_path else []
  segments: List[List[Tuple[float, float]]] = [[point_path[0], point_path[1]]]
  for index in range(2, len(point_path)):
    if compute_transition_break(point_path, index, coverage_width_px, strategy_cfg):
      # 命中转角/跳变阈值时开启新 segment，保留 jump 语义。
      segments.append([point_path[index]])
    else:
      # 非 jump 的点继续延展当前 segment。
      segments[-1].append(point_path[index])
  normalized_segments: List[List[Tuple[float, float]]] = []
  for segment in segments:
    if len(segment) == 1 and normalized_segments:
      # 单点段只能作为缓冲，合并到前段减少长度 1 段输出。
      normalized_segments[-1].append(segment[0])
      continue
    normalized_segments.append(segment)
  return [segment for segment in normalized_segments if len(segment) >= 2]


def build_jump_segments(
  point_path: Sequence[Tuple[float, float]],
  coverage_width_px: int,
  strategy_cfg: StrategyConfig,
) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
  """提取跳变段列表（用于虚线绘制和诊断导出）。"""
  # jump segment 是跨段连接线，渲染时用虚线强调“非连续清扫移动”。
  if len(point_path) <= 2:
    # 不足 3 点时无 jump 段可识别，直接空返回。
    return []
  jump_segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
  for index in range(2, len(point_path)):
    if compute_transition_break(point_path, index, coverage_width_px, strategy_cfg):
      # 记录 jump 前后的端点，供可视化和诊断输出。
      jump_segments.append((point_path[index - 1], point_path[index]))
  return jump_segments


def build_segment_index_groups(
  point_path: Sequence[Tuple[float, float]],
  coverage_width_px: int,
  strategy_cfg: StrategyConfig,
) -> List[List[int]]:
  """返回 1-based 的路径点分段索引。"""
  # 1-based 索引与现有 path_world.csv 对齐，避免人工核对时出现偏差。
  if len(point_path) <= 2:
    return [[index + 1 for index in range(len(point_path))]] if point_path else []
  groups: List[List[int]] = [[1, 2]]
  for index in range(2, len(point_path)):
    if compute_transition_break(point_path, index, coverage_width_px, strategy_cfg):
      # 分段点用于输出对齐索引，保证与 path/world 坐标索引一致。
      groups.append([index + 1])
    else:
      groups[-1].append(index + 1)
  normalized_groups: List[List[int]] = []
  for group in groups:
    if len(group) == 1 and normalized_groups:
      # 1 点段会被提前并回前段，减少消费端对零长度分段的误判。
      normalized_groups[-1].append(group[0])
      continue
    normalized_groups.append(group)
  return [group for group in normalized_groups if len(group) >= 2]


def build_jump_segment_indices(
  point_path: Sequence[Tuple[float, float]],
  coverage_width_px: int,
  strategy_cfg: StrategyConfig,
) -> List[Tuple[int, int]]:
  """返回跳变段的 1-based 点索引区间，便于 json/csv 对齐。"""
  # 与 build_jump_segments 对齐同一个分段定义，避免导出工具按两个口径解释索引。
  if len(point_path) <= 2:
    return []
  jump_segments: List[Tuple[int, int]] = []
  for index in range(2, len(point_path)):
    if compute_transition_break(point_path, index, coverage_width_px, strategy_cfg):
      # 同样使用分段口径产出 jump index，避免和 segment 索引定义不一致。
      jump_segments.append((index, index + 1))
  return jump_segments


def draw_dashed_line(
  image: np.ndarray,
  start: Tuple[int, int],
  end: Tuple[int, int],
  color: Tuple[int, int, int],
  thickness: int = 1,
  dash_length: int = 8,
  gap_length: int = 5,
) -> None:
  """按 dash/gap 渐进绘制线段用于调试可视化。"""
  # 虚线只用于诊断层，避免误导执行层把它当作实际覆盖轨迹。
  dx = float(end[0] - start[0])
  dy = float(end[1] - start[1])
  line_length = math.hypot(dx, dy)
  if line_length <= 1e-6:
    # 退化线段不绘制，避免 step 计算造成无意义循环。
    return
  step = max(1.0, float(dash_length + gap_length))
  ux = dx / line_length
  uy = dy / line_length
  cursor = 0.0
  while cursor < line_length:
    # 每次前进一个 dash+gap，形成固定图案而不依赖几何总长度。
    # 每轮只画 dash_length，再跳过 gap_length。
    dash_start = cursor
    dash_end = min(line_length, cursor + dash_length)
    x0 = int(round(start[0] + ux * dash_start))
    y0 = int(round(start[1] + uy * dash_start))
    x1 = int(round(start[0] + ux * dash_end))
    y1 = int(round(start[1] + uy * dash_end))
    cv2.line(image, (x0, y0), (x1, y1), color, thickness, cv2.LINE_AA)
    cursor += step
