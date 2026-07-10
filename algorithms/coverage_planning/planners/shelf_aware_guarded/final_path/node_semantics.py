"""为旋转坐标系下的规划节点派生 CTG 与 clearance 语义。

payload 供诊断和语义路径引导使用，不决定 traversal 次序，也不修改 coverage graph 状态。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from typing import Any

import cv2
import numpy as np

from ..graph_build.coverage_graph import CoverageCell
from ..geometry.room_rotation import transform_points


@dataclass(frozen=True)
class NodeSemanticsConfig:
  """节点语义构建默认参数，定义边界、空间归属和覆盖责任阈值。"""
  # footprint_radius_factor：节点 footprint 半径相对覆盖宽度的比例。
  footprint_radius_factor: float = 0.5
  # small_local_free_ratio_threshold：局部 free 比例低于该值时认为覆盖收益偏低。
  small_local_free_ratio_threshold: float = 0.45
  # low_degree_threshold：非障碍邻居数小于等于该值时认为连接性弱。
  low_degree_threshold: int = 5
  # obstacle_neighbor_boundary_threshold：障碍邻居数过多时认为节点靠边敏感。
  obstacle_neighbor_boundary_threshold: int = 2
  # min_clearance_boundary_m：正式运行时按 coverage_width_m * 0.7 写入。
  min_clearance_boundary_m: float = 0.0
  # mixed_ratio_threshold：某类空间占比超过该阈值才算进入 mixed_space。
  mixed_ratio_threshold: float = 0.10


def clamp01(value: float) -> float:
  """把数值裁剪到 [0, 1]，作为 coverage_obligation/connectivity 的统一约束。

  Args:
    value: 输入评分值。

  Returns:
    float: 裁剪后的数值。
  """
  # 两个评分都要在同一区间内比较，避免后续阈值在不同量纲下漂移。
  return float(max(0.0, min(1.0, value)))


def footprint_slices(shape: tuple[int, int], point_xy: tuple[float, float], radius_px: int) -> tuple[slice, slice]:
  """根据点位计算不越界的方形 footprint 切片。

  Args:
    shape: 图像形状 `(h, w)`。
    point_xy: 中心点坐标。
    radius_px: 半径像素。

  Returns:
    tuple[slice, slice]: 行列切片。
  """
  # 直接用 planning point 居中取窗，边界节点靠 clip 避免越界抖动。
  x = int(round(float(point_xy[0])))
  y = int(round(float(point_xy[1])))
  # shape 是 free_mask 的高宽，footprint 不能越界。
  h, w = shape
  # clip 后返回统一窗口用于后续所有像素统计，防止边界节点因窗口尺寸变化导致语义噪声。
  return slice(max(0, y - radius_px), min(h, y + radius_px + 1)), slice(max(0, x - radius_px), min(w, x + radius_px + 1))


def counter_to_dict(counter: Counter[int]) -> dict[str, int]:
  """将 Counter[int] 按字符串 key 导出，保证 JSON 兼容和展示一致。

  Args:
    counter: 像素统计计数器。

  Returns:
    dict[str, int]: key 转字符串后的映射。
  """
  # 统一转为字符串可避免某些可视化工具把数字 key 解析成数组索引。
  return {str(int(key)): int(value) for key, value in sorted(counter.items())}


def normalize_label_map(label_map: np.ndarray | None, shape: tuple[int, int]) -> np.ndarray:
  """把外部语义图归一化到 int32，并在缺失时补齐 unknown。

  Args:
    label_map: 外部语义图（可为空）。
    shape: 目标地图形状。

  Returns:
    np.ndarray: 与目标形状一致的 int32 标签图。
  """
  # 缺失语义图时只用 unknown 占位，保证后续统计流程不因空输入中断。
  if label_map is None:
    return np.full(shape, -1, dtype=np.int32)
  # 尺寸不一致会导致不同像素位置错位，必须 fail fast 提前暴露配置问题。
  labels = np.asarray(label_map, dtype=np.int32)
  if labels.shape != shape:
    raise ValueError("语义标签图必须与房间地图尺寸一致")
  return labels


def cell_id(cell: CoverageCell) -> str:
  """返回 cell 的稳定字符串 id。

  Args:
    cell: 节点实体。

  Returns:
    str: `cell.row_cell_col` 风格 id。
  """
  return str(cell.cell_id)


def cell_grid_row(cell: CoverageCell) -> int:
  """返回 cell 的网格行索引。

  行号用于语义统计和邻接输出的稳定定位，对应 coverage graph 的行方向语义。

  Args:
    cell: 节点实体。

  Returns:
    int: grid_row。
  """
  return int(cell.grid_row)


def cell_grid_col(cell: CoverageCell) -> int:
  """返回 cell 的网格列索引。

  列号与网格坐标耦合，保持语义汇总、路径复盘和日志检索可对齐。

  Args:
    cell: 节点实体。

  Returns:
    int: grid_col。
  """
  return int(cell.grid_col)


def cell_planning_point_px(cell: CoverageCell) -> tuple[int, int]:
  """返回 cell 的 planning point 像素坐标。

  Args:
    cell: 节点实体。

  Returns:
    tuple[int, int]: 该节点的规划点坐标。
  """
  return (int(cell.planning_point_px[0]), int(cell.planning_point_px[1]))


def cell_accessible_neighbor_count(cell: CoverageCell) -> int:
  """返回非障碍邻居数量，用作拓扑连接强度。

  Args:
    cell: 节点实体。

  Returns:
    int: 可访问邻居数。
  """
  return int(len(cell.accessible_neighbor_cell_ids))


def cell_obstacle_neighbor_count(cell: CoverageCell) -> int:
  """返回障碍邻居数量，用于边界敏感降权。

  Args:
    cell: 节点实体。

  Returns:
    int: 障碍邻居数。
  """
  return int(len(cell.neighbor_cell_ids) - len(cell.accessible_neighbor_cell_ids))


def compute_space_stats(
  *,
  free_mask: np.ndarray,
  territory_labels: np.ndarray,
  junction_id_map: np.ndarray,
  planning_point_xy: tuple[float, float],
  radius_px: int,
  mixed_ratio_threshold: float,
) -> dict[str, Any]:
  """统计单个 cell 的局部空间占比与混合空间标签。

  Args:
    free_mask: free 区域掩码。
    territory_labels: edge/空间标签图。
    junction_id_map: 通道或交汇标签图。
    planning_point_xy: 采样点坐标。
    radius_px: 周围统计半径。
    mixed_ratio_threshold: 混合判断阈值。

  Returns:
    dict[str, Any]: 空间占比、主标签与混合类型。
  """
  # 以 planning point 为中心做窗口统计，避免同一 node 在不同采样里漂移到不同语义。
  rows, cols = footprint_slices(free_mask.shape, planning_point_xy, radius_px)
  # free_patch 只保留可通行像素，障碍物像素不参与归属比例统计。
  free_patch = free_mask[rows, cols] > 0
  # window_pixel_count 是完整窗口像素数，包含障碍物和 free。
  window_pixel_count = int(free_patch.size)
  # free_count 是窗口内真正可覆盖/可通行的像素数。
  free_count = int(np.count_nonzero(free_patch))
  # 如果窗口里没有 free 像素，这个节点在空间语义上就是 empty。
  if free_count <= 0:
    return {
      "footprint_radius_px": int(radius_px),
      "footprint_window_pixel_count": window_pixel_count,
      "footprint_free_pixel_count": 0,
      "local_free_ratio": 0.0,
      "territory_pixel_counts": {},
      "junction_pixel_counts": {},
      "unknown_pixel_count": 0,
      "primary_space_type": "empty",
      "primary_territory_label": None,
      "primary_junction_id": None,
      "territory_ratio": 0.0,
      "junction_ratio": 0.0,
      "unknown_ratio": 0.0,
      "mixed_space": False,
      "mixed_space_types": [],
    }
  # territory_patch 统计 edge 区域分布，是判断主空间类型的第一依据。
  territory_patch = territory_labels[rows, cols]
  # junction_patch 统计通道/节点区域分布，用于识别连接型语义。
  junction_patch = junction_id_map[rows, cols]
  # territory_counter 只统计 free 像素上的有效 edge id，label < 0 不算 edge。
  territory_counter: Counter[int] = Counter(int(value) for value in territory_patch[free_patch] if int(value) >= 0)
  # junction_counter 只统计 free 像素上的有效 junction id，id < 0 不算 junction。
  junction_counter: Counter[int] = Counter(int(value) for value in junction_patch[free_patch] if int(value) >= 0)
  # territory_total 表示该 footprint 内落入所有 edge territory 的 free 像素数。
  territory_total = int(sum(territory_counter.values()))
  # junction_total 表示该 footprint 内落入所有 junction polygon 的 free 像素数。
  junction_total = int(sum(junction_counter.values()))
  # unknown 是 free 像素，但既不属于 edge territory，也不属于 junction polygon。
  unknown_mask = free_patch & (territory_patch < 0) & (junction_patch < 0)
  # unknown_count 后续用于判断节点是否主要处在未归属区域。
  unknown_count = int(np.count_nonzero(unknown_mask))
  # best_territory 是 footprint 内占比最高的 edge id 及其像素数。
  best_territory = territory_counter.most_common(1)[0] if territory_counter else (None, 0)
  # best_junction 是 footprint 内占比最高的 junction id 及其像素数。
  best_junction = junction_counter.most_common(1)[0] if junction_counter else (None, 0)
  # 同一窗口内 edge/junction/unknown 同时竞争主标签，按像素占比取最大值。
  candidates = [("edge", best_territory[0], int(best_territory[1])), ("junction", best_junction[0], int(best_junction[1])), ("unknown", None, unknown_count)]
  # primary_type 是该节点空间语义的主标签，不是覆盖角色。
  primary_type, primary_id, primary_count = max(candidates, key=lambda item: item[2])
  # 如果三类都没有像素，兜底为 empty，避免把 0 像素误判为 unknown。
  if primary_count <= 0:
    primary_type, primary_id = "empty", None
  # territory_ratio 是最高占比 edge 的像素数 / free_count。
  territory_ratio = float(best_territory[1] / free_count) if best_territory[0] is not None else 0.0
  # junction_ratio 是最高占比 junction 的像素数 / free_count。
  junction_ratio = float(best_junction[1] / free_count) if best_junction[0] is not None else 0.0
  # unknown_ratio 是未归属 free 像素数 / free_count。
  unknown_ratio = float(unknown_count / free_count)
  # mixed_types 反映是否混合多类空间，混合高则降低该节点单一职责可信度。
  mixed_types = []
  # edge 达阈值则标记 mixed 包含 edge，避免后续把边缘任务误判为纯 junction。
  if territory_total / free_count >= mixed_ratio_threshold:
    mixed_types.append("edge")
  # junction 达阈值则标记 mixed 包含 junction，便于连接价值提升。
  if junction_total / free_count >= mixed_ratio_threshold:
    mixed_types.append("junction")
  # unknown 达阈值提示语义不确定区，需要在后续降权而不是强推核心角色。
  if unknown_ratio >= mixed_ratio_threshold:
    mixed_types.append("unknown")
  # 把原始计数与比例一起导出，用于审计时直接回放每个角色的语义归属依据。
  return {
    "footprint_radius_px": int(radius_px),
    "footprint_window_pixel_count": window_pixel_count,
    "footprint_free_pixel_count": free_count,
    "local_free_ratio": float(free_count / window_pixel_count) if window_pixel_count else 0.0,
    "territory_pixel_counts": counter_to_dict(territory_counter),
    "junction_pixel_counts": counter_to_dict(junction_counter),
    "unknown_pixel_count": unknown_count,
    "primary_space_type": primary_type,
    "primary_territory_label": int(primary_id) if primary_type == "edge" and primary_id is not None else None,
    "primary_junction_id": int(primary_id) if primary_type == "junction" and primary_id is not None else None,
    "territory_ratio": territory_ratio,
    "junction_ratio": junction_ratio,
    "unknown_ratio": unknown_ratio,
    "mixed_space": bool(len(mixed_types) >= 2),
    "mixed_space_types": mixed_types,
  }


def compute_semantics(
  cell: CoverageCell,
  planning_point_xy: tuple[float, float],
  space: dict[str, Any],
  *,
  config: NodeSemanticsConfig,
  resolution: float,
  dist_map_rotated: np.ndarray,
) -> dict[str, Any]:
  """基于空间统计和拓扑特征计算单个 node 的语义角色。

  Args:
    cell: 目标节点。
    planning_point_xy: 该节点规划坐标。
    space: 局部空间统计结果。
    config: 节点语义参数。
    resolution: 地图分辨率（m/px）。
    dist_map_rotated: 旋转后距离变换图。

  Returns:
    dict[str, Any]: node 语义字段与标签。
  """
  # degree 用于判断拓扑可达性，低度数通常意味着接近死角。
  degree = cell_accessible_neighbor_count(cell)
  # obstacle_neighbors 反映局部边界压力，障碍邻居越多说明越贴边。
  obstacle_neighbors = cell_obstacle_neighbor_count(cell)
  # 从 distance transform 直接采样可减少外部依赖，提高复算稳定性。
  rotated_point_px = cell_planning_point_px(cell)
  cx = int(round(float(rotated_point_px[0])))
  cy = int(round(float(rotated_point_px[1])))
  if 0 <= cy < dist_map_rotated.shape[0] and 0 <= cx < dist_map_rotated.shape[1]:
    min_distance_m = float(dist_map_rotated[cy, cx]) * float(resolution)
  else:
    min_distance_m = 0.0
  # 边界阈值取 coverage_width 的 0.7 与 1.5px 下限，兼顾不同分辨率下的最小安全距离。
  clearance_threshold_m = max(float(config.min_clearance_boundary_m), float(resolution) * 1.5)
  # small_local_free 表示可清扫比例偏低，降低该点作为主覆盖点权重是合理的。
  small_local_free = float(space["local_free_ratio"]) <= float(config.small_local_free_ratio_threshold)
  # low_degree 表示连接选择少，容易形成残留点，需要降低覆盖责任。
  low_degree = degree <= int(config.low_degree_threshold)
  # boundary 同时看 clearance 与障碍邻居，判断是否需要覆盖责任退避。
  boundary = min_distance_m <= clearance_threshold_m or obstacle_neighbors >= int(config.obstacle_neighbor_boundary_threshold)
  # primary 定义空间主类型：edge/junction/unknown/empty，每种类型有不同 base_obligation。
  primary = str(space["primary_space_type"])
  # edge 被认作可清扫主线，默认最高 coverage_obligation。
  if primary == "edge":
    base_obligation = 1.0
  # junction 主要扮演转场角色，不应与 edge 同等覆盖优先级。
  elif primary == "junction":
    base_obligation = 0.55
  # unknown 未归属区域可清扫，但先给中低责任减少误判。
  elif primary == "unknown":
    base_obligation = 0.45
  # empty 无覆盖价值，避免把空洞区域作为主目标。
  else:
    base_obligation = 0.0
  # quality_factor 统一承载 low_local_free、boundary、low_degree 等降权因素。
  quality_factor = 1.0
  # 局部 free 比例过低意味着重复覆盖收益低，按比例降权。
  if small_local_free:
    quality_factor *= 0.60
  # boundary 降权可避免贴边区域被错误提升为核心清洁点。
  if boundary:
    quality_factor *= 0.60
  # low_degree 再降权，防止弱连接节点抢占高责任角色。
  if low_degree:
    quality_factor *= 0.60
  # coverage_obligation 表示该节点优先清扫倾向，越高越应保留。
  coverage_obligation = clamp01(base_obligation * quality_factor)
  # connectivity_value 表示过渡节点价值，辅助识别 connector。
  if primary == "junction":
    connectivity_value = 0.90
  elif primary == "edge":
    connectivity_value = 0.40
  elif primary == "unknown":
    connectivity_value = 0.35
  else:
    connectivity_value = 0.0
  # mixed_types 为 2 个及以上空间共存时提高连接价值，兼顾换道/转场特征。
  mixed_types = set(space.get("mixed_space_types", []))
  # 同时碰到 junction 与其他空间，常见于过渡点，优先提升 connectivity 价值。
  if "junction" in mixed_types and len(mixed_types) >= 2:
    connectivity_value = max(connectivity_value, 0.75)
  # 同时触达多个 edge territory，通常对应边界切换位置，保留一定连接价值。
  if len(space.get("territory_pixel_counts", {})) >= 2:
    connectivity_value = max(connectivity_value, 0.70)
  # 非 junction 且低度数的点不应被误当高连接值，降级避免绕行偏差。
  if low_degree and primary != "junction":
    connectivity_value *= 0.70
  # 高度数说明可选路径多，可轻微抬高连接价值以促进路径流畅。
  if degree >= 5:
    connectivity_value += 0.10
  # 连通价值约束到 0~1，后续角色阈值判断稳定可复现。
  connectivity_value = clamp01(connectivity_value)
  # role 在覆盖价值与连通价值之间做优先级平衡，避免单指标极端化。
  if connectivity_value >= 0.75:
    role = "connector"
  elif coverage_obligation >= 0.75:
    role = "cover_core"
  elif coverage_obligation >= 0.55:
    role = "cover_soft"
  elif coverage_obligation >= 0.20:
    role = "residual_soft"
  else:
    role = "noise_candidate"
  return {
    "node_id": cell_id(cell),
    "grid_row": cell_grid_row(cell),
    "grid_col": cell_grid_col(cell),
    "planning_point_pixel": [float(planning_point_xy[0]), float(planning_point_xy[1])],
    "space": space,
    "quality_features": {
      "small_local_free": bool(small_local_free),
      "low_degree": bool(low_degree),
      "boundary": bool(boundary),
      "degree": int(degree),
      "obstacle_neighbor_count": int(obstacle_neighbors),
      "min_distance_m": float(min_distance_m),
      "clearance_threshold_m": float(clearance_threshold_m),
    },
    "coverage_obligation": float(coverage_obligation),
    "connectivity_value": float(connectivity_value),
    "node_role": role,
  }


def build_node_semantics(
  *,
  graph_access: Any,
  free_mask: np.ndarray,
  territory_label_map: np.ndarray | None,
  junction_label_map: np.ndarray | None,
  inverse_rotation_matrix: np.ndarray,
  rotated_room_map: np.ndarray,
  coverage_width_px: int,
  coverage_width_m: float,
  resolution_m_per_px: float,
  config: NodeSemanticsConfig | None = None,
) -> dict[str, Any]:
  """构建所有可通行 cell 的节点语义集合与摘要。

  Args:
    graph_access: 图访问封装。
    free_mask: free 区域图。
    territory_label_map: 可选 edge 语义图。
    junction_label_map: 可选 junction 语义图。
    inverse_rotation_matrix: 反向旋转矩阵。
    rotated_room_map: 已旋转房间图。
    coverage_width_px: 覆盖宽度像素。
    coverage_width_m: 覆盖宽度米。
    resolution_m_per_px: 地图分辨率。
    config: 语义参数配置，可为空。

  Returns:
    dict[str, Any]: version/config/summary/nodes/node_by_id。
  """
  # config 为空时退回默认参数，保证调用一致性和可复现性。
  base_config = config or NodeSemanticsConfig()
  # min_clearance_boundary_m 按覆盖宽度动态计算，适配不同机型清扫宽度。
  effective_config = replace(base_config, min_clearance_boundary_m=float(coverage_width_m) * 0.7)
  # free_mask 与最终输出语义都在原图坐标系计算，避免坐标系二次偏移。
  normalized_free = np.where(np.asarray(free_mask) > 0, 255, 0).astype(np.uint8)
  # territory 为空时统一 unknown，避免外部缺失导致中断。
  territory_labels = normalize_label_map(territory_label_map, normalized_free.shape)
  # junction 缺失时全部置 -1，确保统计时只保留有效 junction。
  junction_labels = normalize_label_map(junction_label_map, normalized_free.shape)
  # footprint 半径默认 0.5*coverage width，与扫描头覆盖粒度匹配。
  footprint_radius_px = max(1, int(round(float(coverage_width_px) * float(effective_config.footprint_radius_factor))))
  # dist_map_rotated 用于边界距离回采，减少重复计算并共享 rotated 坐标基准。
  dist_map_rotated = cv2_distance_transform(rotated_room_map)
  # records 收敛所有可通行 node 的明细，供 semantic path 与调试使用。
  records = []
  # node_by_id 提供 O(1) 按 id 关联，便于下游快速检索。
  node_by_id: dict[str, dict[str, Any]] = {}
  # 逐个遍历 graph snapshot 中的可通行 cell；semantic 语义只依赖静态图快照。
  for cell_id in graph_access.accessible_cell_ids():
    cell = graph_access.cell(cell_id)
    rotated_planning_point_px = cell_planning_point_px(cell)
    planning_point_xy = transform_points([(float(rotated_planning_point_px[0]), float(rotated_planning_point_px[1]))], inverse_rotation_matrix)[0]
    space = compute_space_stats(
      free_mask=normalized_free,
      territory_labels=territory_labels,
      junction_id_map=junction_labels,
      planning_point_xy=(float(planning_point_xy[0]), float(planning_point_xy[1])),
      radius_px=footprint_radius_px,
      mixed_ratio_threshold=float(effective_config.mixed_ratio_threshold),
    )
    record = compute_semantics(
      cell,
      (float(planning_point_xy[0]), float(planning_point_xy[1])),
      space,
      config=effective_config,
      resolution=float(resolution_m_per_px),
      dist_map_rotated=dist_map_rotated,
    )
    records.append(record)
    node_by_id[str(record["node_id"])] = record
  return {
    "version": "formal_semantic_ctg_node_semantics_v1",
    "config": {
      "footprint_radius_factor": effective_config.footprint_radius_factor,
      "footprint_radius_px": int(footprint_radius_px),
      "small_local_free_ratio_threshold": effective_config.small_local_free_ratio_threshold,
      "low_degree_threshold": effective_config.low_degree_threshold,
      "obstacle_neighbor_boundary_threshold": effective_config.obstacle_neighbor_boundary_threshold,
      "min_clearance_boundary_m": effective_config.min_clearance_boundary_m,
      "min_clearance_boundary_rule": "coverage_width_m * 0.7",
      "mixed_ratio_threshold": effective_config.mixed_ratio_threshold,
    },
    "summary": summarize_records(records),
    "nodes": records,
    "node_by_id": node_by_id,
  }


def cv2_distance_transform(rotated_room_map: np.ndarray) -> np.ndarray:
  """封装 distance transform，固定返回像素单位的 float32 距离图。

  Args:
    rotated_room_map: 已旋转房间图，非零视为 free。

  Returns:
    np.ndarray: 距离变换结果（像素）。
  """
  # OpenCV distanceTransform 要求 free 为非零，障碍为 0。
  binary = np.where(np.asarray(rotated_room_map) > 0, 255, 0).astype(np.uint8)
  # 距离结果保持像素便于阈值复用，外层再乘 resolution 才能对齐真实米制成本。
  return np.asarray(cv2.distanceTransform(binary, cv2.DIST_L2, 5), dtype=np.float32)


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
  """汇总节点语义分布与指标均值，供调度层快速审计。

  Args:
    records: 语义节点记录列表。

  Returns:
    dict[str, Any]: 节点计数、角色计数、均值与布尔特征计数。
  """
  # role_counts 统计 cover_core/connector 等最终角色数量。
  role_counts = Counter(str(item["node_role"]) for item in records)
  # space_counts 统计 edge/junction/unknown 等空间主标签数量。
  space_counts = Counter(str(item["space"]["primary_space_type"]) for item in records)
  # quality_counts 只统计布尔质量标签为 True 的次数。
  quality_counts = Counter()
  # 只统计质量特征为 True 的标签，避免大量 False 把覆盖/连接评分基线向下稀释。
  for item in records:
    for key, value in item["quality_features"].items():
      if isinstance(value, bool) and value:
        quality_counts[key] += 1
  # obligations 用于给出覆盖责任均值。
  obligations = [float(item["coverage_obligation"]) for item in records]
  # connectivity 用于给出连通价值均值。
  connectivity = [float(item["connectivity_value"]) for item in records]
  return {
    "node_count": int(len(records)),
    "node_role_counts": dict(sorted(role_counts.items())),
    "primary_space_counts": dict(sorted(space_counts.items())),
    "quality_feature_counts": dict(sorted(quality_counts.items())),
    "coverage_obligation_mean": float(sum(obligations) / len(obligations)) if obligations else 0.0,
    "connectivity_value_mean": float(sum(connectivity) / len(connectivity)) if connectivity else 0.0,
    "mixed_space_count": int(sum(1 for item in records if bool(item["space"].get("mixed_space")))),
  }
