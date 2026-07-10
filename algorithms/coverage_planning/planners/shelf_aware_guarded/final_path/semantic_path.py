"""基于能量规划路径构建带 CTG 语义的全局路径。

语义过滤属于 global path 后处理：只决定保留哪些路径点，不改变 traversal 次序输入。
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from .postprocess import point_distance


KEEP_ROLES = {"cover_core", "cover_soft", "connector"}
LOW_VALUE_ROLES = {"residual_soft", "noise_candidate"}



class PointSpatialIndex:
  """基于固定网格的轻量空间索引，用于最近邻查询。"""
  def __init__(self, cell_size_px: float):
    """固定桶大小后构建网格索引容器。

    Args:
      cell_size_px: 空间网格边长（像素），用于控制附近候选搜索粒度。

    Side effects:
      初始化 `self.cells` 与 `self.cell_size_px`。
    """
    self.cell_size_px = max(1.0, float(cell_size_px))
    self.cells: dict[tuple[int, int], list[dict[str, Any]]] = {}

  def _cell_key(self, x: float, y: float) -> tuple[int, int]:
    """返回点所在网格单元索引。

    Args:
      x: x 坐标（像素）。
      y: y 坐标（像素）。

    Returns:
      tuple[int, int]: 归一化后的网格桶坐标。
    """
    return int(math.floor(float(x) / self.cell_size_px)), int(math.floor(float(y) / self.cell_size_px))

  def add(self, item: dict[str, Any], x: float, y: float) -> None:
    """将一个语义节点归入网格桶，加速后续邻域检索。

    Args:
      item: 语义节点 payload。
      x: 语义点 x。
      y: 语义点 y。

    Side effects:
      写入 `self.cells[self._cell_key(x, y)]`。
    """
    self.cells.setdefault(self._cell_key(x, y), []).append(item)

  def nearby(self, x: float, y: float) -> list[dict[str, Any]]:
    """返回 3x3 邻域网格内候选节点，减少全量扫描开销。

    Args:
      x: 查询点 x。
      y: 查询点 y。

    Returns:
      list[dict[str, Any]]: 附近 3x3 网格内的候选语义节点。
    """
    base_x, base_y = self._cell_key(x, y)
    items: list[dict[str, Any]] = []
    for dy in (-1, 0, 1):
      for dx in (-1, 0, 1):
        items.extend(self.cells.get((base_x + dx, base_y + dy), ()))
    return items


def build_semantic_node_index(semantic_nodes: list[dict[str, Any]], cell_size_px: float) -> PointSpatialIndex:
  """构建语义节点的网格索引。

  Args:
    semantic_nodes: 所有语义节点列表。
    cell_size_px: 网格桶边长（像素）。

  Returns:
    PointSpatialIndex: 可用于近邻查询的空间索引。
  """
  # 固定桶索引替代 O(N^2) 全量匹配，语义重建阶段可控在局部邻域内。
  index = PointSpatialIndex(cell_size_px)
  for node in semantic_nodes:
    planning_point = node.get("planning_point_pixel", (0.0, 0.0))
    index.add(node, float(planning_point[0]), float(planning_point[1]))
  return index


def nearest_semantic_node(point: tuple[float, float], semantic_index: PointSpatialIndex, max_distance_px: float) -> tuple[dict[str, Any] | None, float]:
  """查找某点附近最近语义节点，并返回匹配距离。

  未命中时返回 `(None, inf)`。

  Args:
    point: 输入点坐标 `(x, y)`。
    semantic_index: 已构建语义网格索引。
    max_distance_px: 匹配距离上限（像素）。

  Returns:
    tuple[dict[str, Any] | None, float]: 最近语义节点与距离，未命中时节点为空。
  """
  # 保持 point 与 node 在同一原图像素坐标系，避免旋转/反旋转导致的匹配偏移。
  px, py = float(point[0]), float(point[1])
  # 只查半径所在相邻网格；若半径内有最近点，一定在这些网格里。
  nearby_nodes = semantic_index.nearby(px, py)
  if not nearby_nodes:
    return None, float("inf")
  # 在局部候选里做精确距离比较，保持匹配语义不变。
  best = min(
    nearby_nodes,
    key=lambda node: math.hypot(
      px - float(node["planning_point_pixel"][0]),
      py - float(node["planning_point_pixel"][1]),
    ),
  )
  dist = math.hypot(
    px - float(best["planning_point_pixel"][0]),
    py - float(best["planning_point_pixel"][1]),
  )
  if dist > float(max_distance_px):
    return None, float(dist)
  return best, float(dist)


def annotate_path_points(path_points: list[tuple[float, float]], semantic_nodes: list[dict[str, Any]], match_radius_px: float) -> list[dict[str, Any]]:
  """给路径点附加最近语义节点信息。

  Args:
    path_points: 基线路径点。
    semantic_nodes: 语义节点清单。
    match_radius_px: 命中半径阈值（像素）。

  Returns:
    list[dict[str, Any]]: 每个路径点对应的语义注解条目。
  """
  # annotated 是 baseline path 上叠加语义注解，用于后续 keep/skip 与报告输出。
  annotated = []
  # semantic_index 用网格索引加速最近节点匹配。
  semantic_index = build_semantic_node_index(semantic_nodes, match_radius_px)
  # 每个路径点独立关联最近 grid node。
  for order, point in enumerate(path_points, start=1):
    node, distance_px = nearest_semantic_node((float(point[0]), float(point[1])), semantic_index, match_radius_px)
    # 无命中 node 时不删点，先保证路径连续性，再通过 role/overlap 规则收敛。
    if node is None:
      role = "unmatched"
      node_id = None
      coverage_obligation = None
      connectivity_value = None
      space = {}
    else:
      role = str(node.get("node_role", "unmatched"))
      node_id = str(node.get("node_id"))
      coverage_obligation = float(node.get("coverage_obligation", 0.0))
      connectivity_value = float(node.get("connectivity_value", 0.0))
      space = dict(node.get("space", {}))
    annotated.append(
      {
        "semantic_index": int(order),
        "baseline_index": int(order),
        "x": float(point[0]),
        "y": float(point[1]),
        "node_id": node_id,
        "node_match_distance_px": float(distance_px),
        "node_role": role,
        "coverage_obligation": coverage_obligation,
        "connectivity_value": connectivity_value,
        "primary_space_type": space.get("primary_space_type"),
        "primary_territory_label": space.get("primary_territory_label"),
        "primary_junction_id": space.get("primary_junction_id"),
      }
    )
  return annotated


def item_xy(item: dict[str, Any]) -> tuple[float, float]:
  """从语义路径条目中取 x/y。

  Args:
    item: semantic path 条目。

  Returns:
    tuple[float, float]: 当前位置的 `(x, y)`。
  """
  # 统一从 semantic path item 取 x/y。
  return float(item["x"]), float(item["y"])


def min_distance_to_kept_path(point: dict[str, Any], kept_index: PointSpatialIndex) -> float:
  """计算点到已保留路径点最近距离，用于 overlap 剔除判断。

  Args:
    point: 待比较路径点。
    kept_index: 已保留路径点的空间索引。

  Returns:
    float: 最小欧式距离，未有保留点时返回 `inf`。
  """
  # 重叠剔除用中心点距离近似，足以判断低价值点是否可被邻近覆盖替代。
  xy = item_xy(point)
  # 当前只需要知道 overlap 半径内是否存在已保留点。
  nearby_points = kept_index.nearby(xy[0], xy[1])
  if not nearby_points:
    return float("inf")
  return float(min(point_distance(xy, item_xy(item)) for item in nearby_points))


def choose_semantic_path(annotated: list[dict[str, Any]], *, overlap_radius_px: float, max_bridge_gap_px: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
  """按角色与 overlap 规则生成 semantic path 与决策记录。

  Args:
    annotated: 已带注解的路径点。
    overlap_radius_px: 低价值点合并半径（像素）。
    max_bridge_gap_px: 允许的连续性恢复阈值（像素）。

  Returns:
    tuple[list[dict[str, Any]], list[dict[str, Any]]]:
      过滤后的 semantic path 与每点决策原因。
  """
  # 两遍过滤：先按角色与重叠规则粗筛，再补齐因间隔过大导致不连续的中间点。
  selected_flags = [False] * len(annotated)
  # decisions 记录保留/跳过原因。
  decisions: list[dict[str, Any]] = []
  # kept_index 是已进入路径点的空间索引，用于 overlap 判断。
  kept_index = PointSpatialIndex(overlap_radius_px)
  # 第一遍按角色和 overlap 策略选择。
  for idx, point in enumerate(annotated):
    role = str(point["node_role"])
    # 起点终点必须保留，这是保持路径可执行和可回放的底线约束。
    must_keep_endpoint = idx == 0 or idx == len(annotated) - 1
    # keep_required_by_role 避免删掉主覆盖/连接/未匹配点导致空洞连通。
    must_keep_by_role = role in KEEP_ROLES or role == "unmatched"
    # low_value 点默认可被重叠吸收，减少冗余停留点。
    low_value = role in LOW_VALUE_ROLES
    # 该距离决定 low_value 点是否已被邻域覆盖，防止把紧邻有效路径的冗余点重复保留。
    distance_to_kept = min_distance_to_kept_path(point, kept_index)
    # 其余情况默认保留，减少语义过滤导致路径断档的风险。
    keep = True
    reason = "keep_by_role"
    if must_keep_endpoint:
      keep = True
      reason = "keep_endpoint"
    elif must_keep_by_role:
      keep = True
      reason = "keep_required_or_connector"
    elif low_value and distance_to_kept <= overlap_radius_px:
      keep = False
      reason = "skip_low_value_by_overlap"
    elif low_value:
      keep = True
      reason = "keep_low_value_far_from_path"
    else:
      keep = True
      reason = "keep_unknown_role"
    selected_flags[idx] = bool(keep)
    if keep:
      kept_index.add(point, float(point["x"]), float(point["y"]))
    decisions.append(
      {
        "semantic_index": int(point["semantic_index"]),
        "baseline_index": int(point["baseline_index"]),
        "node_role": role,
        "decision": reason,
        "selected": bool(keep),
        "distance_to_kept_path_px": float(distance_to_kept) if math.isfinite(distance_to_kept) else None,
        "x": float(point["x"]),
        "y": float(point["y"]),
      }
    )
  # 第二遍保护路径连续性，若保留点间距超阈值则恢复中间点避免解释为单跳。
  selected_indices = [idx for idx, flag in enumerate(selected_flags) if flag]
  # restored 记录由于连贯性恢复而补入的点，便于审计。
  restored: set[int] = set()
  # 只在相邻保留点索引差 > 1 时检查桥接长度。
  for left, right in zip(selected_indices, selected_indices[1:]):
    if right <= left + 1:
      continue
    gap = point_distance(item_xy(annotated[left]), item_xy(annotated[right]))
    if gap <= max_bridge_gap_px:
      continue
    for idx in range(left + 1, right):
      if not selected_flags[idx]:
        selected_flags[idx] = True
        restored.add(idx)
  # 写回恢复原因，便于 downstream 判断是否是连续性修复带来的点。
  for idx in restored:
    decisions[idx]["selected"] = True
    decisions[idx]["decision"] = "restore_bridge_continuity"
  # 重建后路径是 downstream 唯一消费接口，补 global_index 用于后续结果对齐与回放核对。
  semantic_path = [dict(point) for idx, point in enumerate(annotated) if selected_flags[idx]]
  # global_index 是正式输出路径的新序号。
  for order, point in enumerate(semantic_path, start=1):
    point["global_index"] = int(order)
  return semantic_path, decisions


def semantic_path_points(semantic_path: list[dict[str, Any]]) -> list[tuple[float, float]]:
  """从 semantic path 条目恢复 x/y 列表，供后续几何阶段使用。

  Args:
    semantic_path: semantic path 条目列表。

  Returns:
    list[tuple[float, float]]: 转换后的二维路径点。
  """
  # 仅保留几何坐标，避免语义字段的缺失扩散到几何优化和导出步骤。
  return [(float(item["x"]), float(item["y"])) for item in semantic_path]


def build_semantic_global_path(
  *,
  pixel_points: list[tuple[float, float]],
  node_semantics_payload: dict[str, Any],
  coverage_width_px: int,
  actual_clean_width_m: float,
  resolution_m_per_px: float,
  match_radius_factor: float = 0.75,
  max_bridge_gap_factor: float = 2.5,
) -> dict[str, Any]:
  """基于 node semantics 过滤/保留路径点并输出诊断决策。

  Args:
    pixel_points: 输入路径点（像素坐标）。
    node_semantics_payload: node 语义产物。
    coverage_width_px: 覆盖宽度（像素）。
    actual_clean_width_m: 实际清洁宽度（米）。
    resolution_m_per_px: 地图分辨率（m/px）。
    match_radius_factor: 匹配半径比例参数。
    max_bridge_gap_factor: 桥接恢复比例参数。

  Returns:
    dict[str, Any]: semantic path、annotated、决策与统计摘要。
  """
  # 语义过滤参数化，不改变点的几何连续性，只决定哪些点进入 semantic path。
  semantic_nodes = list(node_semantics_payload.get("nodes", []))
  # overlap_radius 用于把低价值点与保留路径点的距离判断，防止重复覆盖。
  overlap_radius_px = float(actual_clean_width_m) * 0.5 / float(resolution_m_per_px)
  # 匹配半径用于把 path point 映射到最近 node，不命中时保持 unmatched 继续回放。
  match_radius_px = max(1.0, float(coverage_width_px) * float(match_radius_factor))
  # bridge gap 阈值用于恢复因跳过造成的长连接。
  max_bridge_gap_px = max(1.0, float(coverage_width_px) * float(max_bridge_gap_factor))
  # 给 baseline path 每个点补齐最近语义节点属性（可为空），形成决策输入。
  annotated = annotate_path_points(pixel_points, semantic_nodes, match_radius_px)
  # 按当前研究策略生成 semantic path。
  semantic_path, decisions = choose_semantic_path(annotated, overlap_radius_px=overlap_radius_px, max_bridge_gap_px=max_bridge_gap_px)
  # 决策分布用于检查过滤是否过强/过弱，角色分布用于发现语义偏置。
  decision_counts = Counter(str(item["decision"]) for item in decisions)
  role_counts = Counter(str(item.get("node_role", "unmatched")) for item in semantic_path)
  return {
    "version": "formal_semantic_global_path_v1",
    "config": {
      "actual_clean_width_m": float(actual_clean_width_m),
      "overlap_radius_px": float(overlap_radius_px),
      "match_radius_factor": float(match_radius_factor),
      "match_radius_px": float(match_radius_px),
      "max_bridge_gap_factor": float(max_bridge_gap_factor),
      "max_bridge_gap_px": float(max_bridge_gap_px),
    },
    "annotated_path": annotated,
    "semantic_path": semantic_path,
    "decisions": decisions,
    "path_points": semantic_path_points(semantic_path),
    "summary": {
      "baseline_path_point_count": int(len(pixel_points)),
      "semantic_path_point_count": int(len(semantic_path)),
      "removed_path_point_count": int(len(pixel_points) - len(semantic_path)),
      "decision_counts": dict(sorted(decision_counts.items())),
      "semantic_path_role_counts": dict(sorted(role_counts.items())),
    },
  }
