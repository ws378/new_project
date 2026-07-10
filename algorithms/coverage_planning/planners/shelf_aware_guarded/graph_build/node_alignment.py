"""ShelfAware 覆盖节点端点对齐工具。"""

from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np

from ..models import Node


def _continuous_accessible_segments(row: Sequence[Node]) -> List[List[Node]]:
  """按 row 顺序提取同一行连续可通行段，保持顺序可复现。"""

  segments: List[List[Node]] = []
  current: List[Node] = []
  for node in row:
    # 按行顺序持续收集连续可通行节点，任何障碍都作为段边界。
    if node.obstacle:
      # 遇到障碍必须切断段落，否则会把两个通道误拼到同一对齐段。
      if current:
        segments.append(current)
        current = []
      continue
    current.append(node)
  if current:
    # 收尾时补齐最后一段，避免尾端可达段被忽略。
    segments.append(current)
  return segments


def _segment_target_x_bounds(
  room_map: np.ndarray,
  segment: Sequence[Node],
  coverage_width_px: int,
  robot_half_width_px: float,
) -> Tuple[int, int] | None:
  """计算单行连续段对齐后在 x 轴上的左右目标边界。"""

  # 用首尾侧向最近障碍推边界，防止端点越过可行廊道。
  left_boundary = _horizontal_obstacle_boundary(
    room_map,
    x=int(segment[0].planning_point_px[0]),
    y=int(segment[0].planning_point_px[1]),
    coverage_width_px=coverage_width_px,
    side="left",
  )
  # 右侧边界同理，从右端找最近障碍，避免对齐点靠墙穿行。
  right_boundary = _horizontal_obstacle_boundary(
    room_map,
    x=int(segment[-1].planning_point_px[0]),
    y=int(segment[-1].planning_point_px[1]),
    coverage_width_px=coverage_width_px,
    side="right",
  )
  # 无障碍边界时回退原规则网格端点，避免虚构约束把端点推离通道。
  left_grid, right_grid = _segment_grid_center_px_span(segment)
  # 左侧有约束时保留机器人半宽间隙，确保不贴墙。
  target_left = (
    int(round(float(left_boundary) + float(robot_half_width_px)))
    if left_boundary is not None
    else int(left_grid)
  )
  # 右侧有约束时同理，留出半宽缓冲减少碰撞风险。
  target_right = (
    int(round(float(right_boundary) - float(robot_half_width_px)))
    if right_boundary is not None
    else int(right_grid)
  )
  # 夹紧到地图边界内，避免后续点查询出现越界异常。
  target_left = max(0, min(room_map.shape[1] - 1, target_left))
  target_right = max(0, min(room_map.shape[1] - 1, target_right))
  # 端点退化说明约束不可解，保留原位置更稳妥。
  if target_left >= target_right:
    return None
  return target_left, target_right


def _segment_grid_center_px_span(segment: Sequence[Node]) -> Tuple[int, int]:
  """返回段首/段尾的规则中心 x，用于退化时的兜底边界。"""

  first_center = segment[0].grid_center_px
  last_center = segment[-1].grid_center_px
  return int(round(first_center[0])), int(round(last_center[0]))


def _continuous_accessible_column_segments(nodes: Sequence[Sequence[Node]]) -> List[List[Node]]:
  """按列扫描提取连续可通行段，配合上下对齐。"""

  if not nodes:
    # 空矩阵无列扫描对象，直接返回空结果。
    return []

  segments: List[List[Node]] = []
  # 用最大列数驱动扫描，兼容每行长度不一致的稀疏节点矩阵。
  max_cols = max((len(row) for row in nodes), default=0)
  for col_index in range(max_cols):
    current: List[Node] = []
    for row in nodes:
      if col_index >= len(row):
        # 行尾越界表示该列在该行无效，先落库当前段并切换下一行。
        if current:
          segments.append(current)
          current = []
        continue
      node = row[col_index]
      if node.obstacle:
        # 障碍打断当前列段，避免将两个不连通片段合并。
        if current:
          segments.append(current)
          current = []
        continue
      current.append(node)
    if current:
      # 列扫描结束，收尾提交末段。
      segments.append(current)
  return segments


def _segment_target_y_bounds(
  room_map: np.ndarray,
  segment: Sequence[Node],
  coverage_width_px: int,
  robot_half_width_px: float,
) -> Tuple[int, int] | None:
  """计算单列连续段对齐后在 y 轴上的上下目标边界。"""

  # 通过首尾点向上/向下找障碍边界，限制对齐段不越界进墙。
  top_boundary = _vertical_obstacle_boundary(
    room_map,
    x=int(segment[0].planning_point_px[0]),
    y=int(segment[0].planning_point_px[1]),
    coverage_width_px=coverage_width_px,
    side="top",
  )
  # 下边界同理，避免末端点落入下方阻挡区。
  bottom_boundary = _vertical_obstacle_boundary(
    room_map,
    x=int(segment[-1].planning_point_px[0]),
    y=int(segment[-1].planning_point_px[1]),
    coverage_width_px=coverage_width_px,
    side="bottom",
  )
  # 上下边界缺省时回退规则网格端点，避免基于缺失约束硬推边界。
  top_grid, bottom_grid = _segment_grid_center_px_y_span(segment)
  # 上方存在约束时向下偏移半宽，避免贴顶壁。
  target_top = (
    int(round(float(top_boundary) + float(robot_half_width_px)))
    if top_boundary is not None
    else int(top_grid)
  )
  # 下方存在约束时向上偏移半宽，避免碰底部障碍。
  target_bottom = (
    int(round(float(bottom_boundary) - float(robot_half_width_px)))
    if bottom_boundary is not None
    else int(bottom_grid)
  )
  # 坐标先与图像边界夹紧，后续采样/写入不再越界。
  target_top = max(0, min(room_map.shape[0] - 1, target_top))
  target_bottom = max(0, min(room_map.shape[0] - 1, target_bottom))
  # 上下边界失效时保留原位，避免强行修正带来拓扑反转。
  if target_top >= target_bottom:
    return None
  return target_top, target_bottom


def _segment_grid_center_px_y_span(segment: Sequence[Node]) -> Tuple[int, int]:
  """返回段首/段尾的规则中心 y，用于边界退化时回退。"""

  first_center = segment[0].grid_center_px
  last_center = segment[-1].grid_center_px
  return int(round(first_center[1])), int(round(last_center[1]))


def _sample_axis_positions(start: int, end: int, count: int) -> np.ndarray:
  """按等距采样生成对齐目标坐标，单点时居中返回。"""

  if count == 1:
    # 单点段只能取中点，避免对两端偏移造成端点抖动。
    return np.array([0.5 * (float(start) + float(end))], dtype=np.float64)
  return np.linspace(float(start), float(end), num=count)


def _set_endpoint_alignment_applied(node: Node, previous_point: Tuple[int, int]) -> None:
  """在 planning_point 真正变化时标记对齐改动，供追溯层判断来源。"""

  if node.planning_point_px != previous_point and hasattr(node, "endpoint_alignment_applied"):
    # 仅当坐标变化时置位，避免未修改点误标记为对齐动作。
    node.endpoint_alignment_applied = True


def _horizontal_obstacle_boundary(
  room_map: np.ndarray,
  *,
  x: int,
  y: int,
  coverage_width_px: int,
  side: str,
) -> int | None:
  """在指定方向搜寻障碍边界，返回可对齐约束的障碍坐标。"""

  band_half = _narrow_band_half_width(coverage_width_px)
  y0 = int(y) - band_half
  y1 = int(y) + band_half + 1
  if side == "left":
    # 左侧边界只看左窗，避免把右侧空域误当成约束而过早收缩。
    # 只看左侧窗内障碍并排除当前点，防止自引用当作约束。
    x0 = int(x) - int(coverage_width_px)
    x1 = int(x)
    obstacle_cols = _obstacle_columns(room_map, x0, x1, y0, y1)
    if obstacle_cols.size == 0:
      # 没有左侧边界时仅在窗口越界时回退到-1，不触发左移约束。
      return -1 if x0 < 0 else None
    # 未见边界则外延到墙面，避免对齐点滑出地图。
    return max(0, x0) + int(obstacle_cols[-1])
  if side == "right":
    # 右侧边界只看右窗，避免当前 x 参与统计造成边界过紧。
    # 只看右侧窗并跳过当前 x，避免当前点吞掉边界语义。
    x0 = int(x) + 1
    x1 = int(x) + int(coverage_width_px) + 1
    obstacle_cols = _obstacle_columns(room_map, x0, x1, y0, y1)
    if obstacle_cols.size == 0:
      # 无右侧约束时返回地图右边界（未越界）或空约束信号（越界）。
      return room_map.shape[1] if x1 > room_map.shape[1] else None
    # 取最左障碍作为有效约束，控制端点停在安全走廊内。
    return max(0, x0) + int(obstacle_cols[0])
  # side 必须受控，可避免传参错误时产生静默的错误边界。
  raise ValueError(f"unsupported side: {side}")


def _vertical_obstacle_boundary(
  room_map: np.ndarray,
  *,
  x: int,
  y: int,
  coverage_width_px: int,
  side: str,
) -> int | None:
  """在指定方向搜寻障碍边界，返回可对齐约束的障碍坐标。"""

  band_half = _narrow_band_half_width(coverage_width_px)
  x0 = int(x) - band_half
  x1 = int(x) + band_half + 1
  if side == "top":
    # 上侧边界只看上窗，控制端点上移不会越界穿墙。
    # 只在上方窗口找障碍并排除当前点，避免自点干扰。
    y0 = int(y) - int(coverage_width_px)
    y1 = int(y)
    obstacle_rows = _obstacle_rows(room_map, x0, x1, y0, y1)
    if obstacle_rows.size == 0:
      # 无上边界约束时以窗口越界为信号返回-1。
      return -1 if y0 < 0 else None
    # 取最下方障碍作为上界，防止上移过量。
    return max(0, y0) + int(obstacle_rows[-1])
  if side == "bottom":
    # 下侧边界只看下窗，避免下方临近空域错误约束上端对齐。
    # 只在下方窗口找障碍并跳过当前点，避免当前点被误识别。
    y0 = int(y) + 1
    y1 = int(y) + int(coverage_width_px) + 1
    obstacle_rows = _obstacle_rows(room_map, x0, x1, y0, y1)
    if obstacle_rows.size == 0:
      # 下边界未命中时走地图底部兜底，保持下移能力。
      return room_map.shape[0] if y1 > room_map.shape[0] else None
    # 取最上方障碍作为下界，避免下压到障碍底面。
    return max(0, y0) + int(obstacle_rows[0])
  # side 必须受控，非法分支应直接失败而不是返回错误约束。
  raise ValueError(f"unsupported side: {side}")


def _obstacle_columns(
  room_map: np.ndarray,
  x0: int,
  x1: int,
  y0: int,
  y1: int,
) -> np.ndarray:
  """返回搜索窗口内有障碍的列偏移列表（按列索引）。"""

  x0 = max(0, int(x0))
  x1 = min(room_map.shape[1], int(x1))
  y0 = max(0, int(y0))
  y1 = min(room_map.shape[0], int(y1))
  if x0 >= x1 or y0 >= y1:
    # 空采样窗表示该方向不可得边界，返回空列表让上游走退化逻辑。
    return np.array([], dtype=np.int64)
  band = np.asarray(room_map[y0:y1, x0:x1]) != 255
  return np.flatnonzero(np.any(band, axis=0))


def _obstacle_rows(
  room_map: np.ndarray,
  x0: int,
  x1: int,
  y0: int,
  y1: int,
) -> np.ndarray:
  """返回搜索窗口内有障碍的行偏移列表（按行索引）。"""

  x0 = max(0, int(x0))
  x1 = min(room_map.shape[1], int(x1))
  y0 = max(0, int(y0))
  y1 = min(room_map.shape[0], int(y1))
  if x0 >= x1 or y0 >= y1:
    # 空采样窗表示该方向不存在行内障碍索引，返回空列表。
    return np.array([], dtype=np.int64)
  band = np.asarray(room_map[y0:y1, x0:x1]) != 255
  return np.flatnonzero(np.any(band, axis=1))


def _narrow_band_half_width(coverage_width_px: int) -> int:
  """按覆盖宽度计算搜索窄带半宽，降低与非主轴障碍干扰。"""

  return max(1, int(round(float(coverage_width_px) * 0.1)))


def align_grid_segments_to_free_endpoints(
  room_map: np.ndarray,
  nodes: Sequence[Sequence[Node]],
  coverage_width_px: int,
  robot_half_width_px: float,
) -> None:
  """对规则网格中的连续可通行段做端点对齐，缩小边界漂移。
  
  先按行左右对齐，再按列上下对齐。该步骤只微调已有非障碍节点的
  planning_point_px：`grid_center_px`、`grid_row/grid_col`、障碍节点和后续邻居构建方式
  都保持不变。
  
  Args:
      room_map: 0/255 的障碍地图，用于推断障碍边界。
      nodes: 规划节点二维矩阵。
      coverage_width_px: 节点步距，用于定义端点可回溯边界的搜索窗口。
      robot_half_width_px: 机器人半宽（像素），用于端点对齐时的安全缓冲。
  """

  # 固定先横向再纵向，减少一次对齐对另一次的参数污染。
  align_row_segments_to_free_endpoints(room_map, nodes, coverage_width_px, robot_half_width_px)
  # 纵向在横向结果上复用，避免回填导致两次方向互相抖动。
  align_column_segments_to_free_endpoints(room_map, nodes, coverage_width_px, robot_half_width_px)


def align_row_segments_to_free_endpoints(
  room_map: np.ndarray,
  nodes: Sequence[Sequence[Node]],
  coverage_width_px: int,
  robot_half_width_px: float,
) -> None:
  """对每行连续可通行段做左右首尾对齐。
  
  Args:
      room_map: 0/255 的障碍地图。
      nodes: 节点矩阵，按行扫描。
      coverage_width_px: 覆盖步幅，影响端点边界计算。
      robot_half_width_px: 机器人半宽（像素），用于避让障碍时的夹持缓冲。
  
  Returns:
      None: 直接在 nodes 中原地更新 planning_point_px。
  """

  for row in nodes:
    # 每行处理为多个连续段，避免把断开的通道混为一个端点对齐对象。
    for segment in _continuous_accessible_segments(row):
      bounds = _segment_target_x_bounds(room_map, segment, coverage_width_px, robot_half_width_px)
      if bounds is None:
        # 边界不可解则保留原坐标，不做坐标注入。
        continue
      left_x, right_x = bounds
      if left_x >= right_x:
        # 宽度约束塌缩时跳过该段，防止反向采样造成倒置。
        continue

      target_xs = _sample_axis_positions(left_x, right_x, len(segment))
      for node, target_x in zip(segment, target_xs):
        planning_point_px = node.planning_point_px
        node.planning_point_px = (int(round(target_x)), int(round(planning_point_px[1])))
        _set_endpoint_alignment_applied(node, planning_point_px)


def align_column_segments_to_free_endpoints(
  room_map: np.ndarray,
  nodes: Sequence[Sequence[Node]],
  coverage_width_px: int,
  robot_half_width_px: float,
) -> None:
  """对每列连续可通行段做上下首尾对齐。
  
  Args:
      room_map: 0/255 的障碍地图。
      nodes: 节点矩阵，按列扫描时按列聚合可通行段。
      coverage_width_px: 覆盖步幅，影响端点边界计算。
      robot_half_width_px: 机器人半宽（像素），用于避免贴边走行。
  
  Returns:
      None: 直接在 nodes 中原地更新 planning_point_px。
  """

  for segment in _continuous_accessible_column_segments(nodes):
    bounds = _segment_target_y_bounds(room_map, segment, coverage_width_px, robot_half_width_px)
    if bounds is None:
      # 列段无上下边界时保留原坐标，交由前后段行为一致性控制。
      continue
    top_y, bottom_y = bounds
    if top_y >= bottom_y:
      # 上下边界退化则不做调整，避免顺序反转。
      continue

    target_ys = _sample_axis_positions(top_y, bottom_y, len(segment))
    for node, target_y in zip(segment, target_ys):
      planning_point_px = node.planning_point_px
      node.planning_point_px = (int(round(planning_point_px[0])), int(round(target_y)))
      _set_endpoint_alignment_applied(node, planning_point_px)
