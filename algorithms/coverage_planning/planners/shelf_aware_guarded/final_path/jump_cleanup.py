"""最终路径中的孤立长跳片段治理。

本模块只在遍历和 semantic path 之后修改输出点序列。不会把节点标记 inactive，
也不回写覆盖状态；inactive fragment 只作为可疑短片段的诊断证据。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


Point = tuple[float, float]


@dataclass(frozen=True)
class IsolatedJumpCleanupConfig:
  """隔离长跳片段清理参数，决定何时执行移除与重插。

  约束：
    - 只在输入路径已经完成语义与几何后处理之后运行，避免干扰原始覆盖。
    - 规则命中仅做输出层处理，不改变访问状态或覆盖图。
  """
  # enable=False 时原样返回路径，仅在 debug 保留开关状态，便于复盘为何未执行。
  enable: bool = True
  # 超过该距离的相邻点连接被视为“长跳边”，是候选长-短-长结构的触发条件。
  jump_distance_m: float = 3.0
  # 只有点数少、内部长度短的片段才可能是孤立碎片，避免吞掉真实清扫段。
  max_isolated_points: int = 3
  max_isolated_length_m: float = 1.0
  # 碎片靠近保留主路径时尝试重插，否则优先移除记录 inactive。
  reinsert_max_distance_m: float = 1.0
  # 重插必须把总代价进一步下降到阈值以上，避免把片段移回导致路径更长且更抖动。
  reinsert_improvement_ratio: float = 0.80

  def to_dict(self) -> dict[str, float | int | bool]:
    """导出清理配置，便于记录在 artifact 与复测参数里。"""
    return {
      "enable": bool(self.enable),
      "jump_distance_m": float(self.jump_distance_m),
      "max_isolated_points": int(self.max_isolated_points),
      "max_isolated_length_m": float(self.max_isolated_length_m),
      "reinsert_max_distance_m": float(self.reinsert_max_distance_m),
      "reinsert_improvement_ratio": float(self.reinsert_improvement_ratio),
    }


@dataclass(frozen=True)
class InactivePathFragment:
  """记录已移除片段的诊断元数据，便于复盘为何发生路径瘦身。"""
  # start/end 使用原始路径中的 1-based 索引，便于和导出的 path_pixels.json 对齐。
  start_index: int
  end_index: int
  # points 保存被移出最终路径的原始片段点。
  points: tuple[Point, ...]
  # reason 是稳定字符串，供测试和诊断工具过滤。
  reason: str
  # 两侧跳变和片段内部长度都用像素存储，导出时按 resolution 转米。
  before_jump_px: float
  after_jump_px: float
  internal_length_px: float

  def to_dict(self, resolution_m_per_px: float) -> dict[str, object]:
    """导出片段级诊断字段并转为米制单位，供人工审阅和比对。"""
    # json 中输出米制字段，直接面向调试报告和人工检查。
    return {
      "start_index": int(self.start_index),
      "end_index": int(self.end_index),
      "reason": self.reason,
      "points": [[float(x), float(y)] for x, y in self.points],
      "before_jump_m": float(self.before_jump_px) * float(resolution_m_per_px),
      "after_jump_m": float(self.after_jump_px) * float(resolution_m_per_px),
      "internal_length_m": float(self.internal_length_px) * float(resolution_m_per_px),
    }


@dataclass(frozen=True)
class ReinsertedPathFragment:
  """可重插片段在路径中的重建痕迹，用于复盘为什么选择“插回”而非禁用。"""
  # original_* 是片段在原路径中的位置，insert_after_index 是重插后的锚点索引。
  original_start_index: int
  original_end_index: int
  insert_after_index: int
  # points 是被重新插回最终路径的片段。
  points: tuple[Point, ...]
  # 两个成本用于解释为什么该片段被重插而不是标记 inactive。
  original_bridge_cost_px: float
  new_cost_px: float

  def to_dict(self, resolution_m_per_px: float) -> dict[str, object]:
    """导出重插成本与索引，便于对比为何选择重插。"""
    # 与 inactive 输出保持同一单位体系，便于比较。
    return {
      "original_start_index": int(self.original_start_index),
      "original_end_index": int(self.original_end_index),
      "insert_after_index": int(self.insert_after_index),
      "points": [[float(x), float(y)] for x, y in self.points],
      "original_bridge_cost_m": float(self.original_bridge_cost_px) * float(resolution_m_per_px),
      "new_cost_m": float(self.new_cost_px) * float(resolution_m_per_px),
    }


@dataclass(frozen=True)
class IsolatedJumpCleanupResult:
  """返回一次清理阶段的结构化结果，既保留最终路径也保留诊断痕迹。"""
  # path_points 是最终给后续分段和 world_path 使用的路径。
  path_points: list[Point]
  # inactive_fragments 表示从输出路径移除但保留诊断记录的碎片。
  inactive_fragments: tuple[InactivePathFragment, ...] = ()
  # reinserted_fragments 表示找到更合理插入位置的碎片。
  reinserted_fragments: tuple[ReinsertedPathFragment, ...] = ()
  # candidate_count 记录被长跳规则识别出的候选片段总数。
  candidate_count: int = 0
  changed: bool = False
  debug: dict[str, object] = field(default_factory=dict)

  def to_summary_dict(self, resolution_m_per_px: float) -> dict[str, object]:
    """生成摘要统计，避免在主日志中重复展开完整片段明细。"""
    # artifact 只需要摘要，不重复输出完整最终路径。
    return {
      "candidate_count": int(self.candidate_count),
      "inactive_count": int(len(self.inactive_fragments)),
      "reinserted_count": int(len(self.reinserted_fragments)),
      "changed": bool(self.changed),
      "inactive_fragments": [
        item.to_dict(resolution_m_per_px)
        for item in self.inactive_fragments
      ],
      "reinserted_fragments": [
        item.to_dict(resolution_m_per_px)
        for item in self.reinserted_fragments
      ],
      "debug": dict(self.debug),
    }


def point_distance_px(a: Point, b: Point) -> float:
  """计算两个点的欧式距离，统一使用像素距离口径。"""
  # 统一像素单位后再比较阈值，避免米/px 混用导致清理边界漂移。
  return float(math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1])))


def path_length_px(points: Sequence[Point]) -> float:
  """求路径序列长度；用于估计孤立片段内部移动成本。"""
  # 单点片段长度为 0 仍可被识别，后续通过候选规则继续过滤。
  if len(points) < 2:
    # 少于 2 点无法形成边，返回 0 让上层统一按长度阈值过滤。
    return 0.0
  return float(sum(point_distance_px(a, b) for a, b in zip(points, points[1:])))


def _segment_distance_to_point_px(a: Point, b: Point, p: Point) -> float:
  """计算点到线段的最近距离（处理退化线段）。"""
  # 该距离用于判断碎片是否仍在候选主路径近邻内，决定是否允许重插。
  ax, ay = float(a[0]), float(a[1])
  bx, by = float(b[0]), float(b[1])
  px, py = float(p[0]), float(p[1])
  vx = bx - ax
  vy = by - ay
  denom = vx * vx + vy * vy
  if denom <= 1e-9:
    # 退化线段按端点距离处理。
    return point_distance_px(a, p)
  t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / denom))
  closest = (ax + t * vx, ay + t * vy)
  return point_distance_px(closest, p)


def _span_near_edge_distance_px(path: Sequence[Point], insert_after: int, span: Sequence[Point]) -> float:
  """计算片段与候选插入边界的最近距离，用于判断是否可重插。"""
  # insert_after=-1 代表头部，>=len(path)-1 代表尾部，边界要单独处理。
  if not span:
    # 空 span 表示候选片段本身无效，返回 inf 直接排除重插。
    return float("inf")
  if not path:
    # 无既有路径时无法定义边界，返回 inf 避免误判可重插。
    return float("inf")
  if insert_after < 0:
    anchor = path[0]
    # 插到头部时，片段只需靠近原路径首点。
    return min(point_distance_px(anchor, point) for point in span)
  if insert_after >= len(path) - 1:
    # 插到尾部时只看最后一个点，避免跨段连接造成虚假更短路径。
    anchor = path[-1]
    return min(point_distance_px(anchor, point) for point in span)
  return min(_segment_distance_to_point_px(path[insert_after], path[insert_after + 1], point) for point in span)


def _insertion_added_cost_px(path: Sequence[Point], insert_after: int, span: Sequence[Point]) -> float:
  """估算片段插入到某位置后的增量路径长度。"""
  # 估算将 span 插入后增加的路径长度，用于与移除方案做代价比。
  if not span:
    # 空片段不会增加路径代价，直接返回 0 避免分母污染后续成本比较。
    return 0.0
  if not path:
    # 主路径缺失时退化为独立路径成本，保留重插候选的一致性。
    return path_length_px(span)
  span_cost = path_length_px(span)
  if insert_after < 0:
    # 头插候选从片段末端连到现有首点，体现“先走片段再续接”成本。
    return point_distance_px(span[-1], path[0]) + span_cost
  if insert_after >= len(path) - 1:
    # 尾插候选从现有尾点连到片段起点，避免把中间边界误当成尾部。
    return point_distance_px(path[-1], span[0]) + span_cost
  # 插入中间时，要减去原本被断开的 path[insert_after] -> path[insert_after + 1] 边。
  return (
    point_distance_px(path[insert_after], span[0])
    + span_cost
    + point_distance_px(span[-1], path[insert_after + 1])
    - point_distance_px(path[insert_after], path[insert_after + 1])
  )


def _find_candidate_spans(
  points: Sequence[Point],
  *,
  jump_distance_px: float,
  max_isolated_points: int,
  max_isolated_length_px: float,
) -> list[tuple[int, int, float, float, float]]:
  """枚举长跳-短段-长跳结构并返回候选孤立片段。"""
  # 候选形态固定为“长跳 -> 短片段 -> 长跳”，用 start/end 闭区间输出。
  if len(points) < 3:
    # 小于 3 点无法构成两段跳变夹住的“孤立段”，直接空返回。
    return []
  jump_edges = [
    index
    for index, (a, b) in enumerate(zip(points, points[1:]))
    if point_distance_px(a, b) > jump_distance_px
  ]
  candidates: list[tuple[int, int, float, float, float]] = []
  for left_jump, right_jump in zip(jump_edges, jump_edges[1:]):
    # 两个相邻长跳之间夹住的点列就是候选孤立片段。
    start = left_jump + 1
    end = right_jump
    if start > end:
      # 理论上不应发生，但防御性过滤可避免非法反向切片。
      continue
    span = points[start : end + 1]
    if len(span) > int(max_isolated_points):
      # 片段太长更可能是有效区域，超出本规则处理边界。
      continue
    internal_length = path_length_px(span)
    if internal_length > float(max_isolated_length_px):
      # 内部长度过大时通常有几何意义，不作为孤立碎片。
      continue
    candidates.append(
      (
        int(start),
        int(end),
        point_distance_px(points[left_jump], points[start]),
        point_distance_px(points[end], points[right_jump + 1]),
        internal_length,
      )
    )
  return candidates


def cleanup_isolated_jump_fragments(
  points: Sequence[Point],
  *,
  resolution_m_per_px: float,
  config: IsolatedJumpCleanupConfig,
) -> IsolatedJumpCleanupResult:
  """执行孤立跳变片段清理：先移除再尝试重插。

  该过程仅改变输出层路径，不改写规划图状态。
  """
  # 输入点先规范成 float，避免上游 int/np 标量混入 artifact。
  path = [(float(x), float(y)) for x, y in points]
  # 功能关闭或点数过少不具备长跳结构，直接返回原路径并保留 debug。
  if not config.enable or len(path) < 3:
    return IsolatedJumpCleanupResult(path_points=path, debug={"enabled": bool(config.enable)})

  resolution = float(resolution_m_per_px)
  # 配置使用米定义，内部统一转换为像素再进行几何比较。
  jump_distance_px = float(config.jump_distance_m) / resolution
  max_isolated_length_px = float(config.max_isolated_length_m) / resolution
  reinsert_max_distance_px = float(config.reinsert_max_distance_m) / resolution
  candidates = _find_candidate_spans(
    path,
    jump_distance_px=jump_distance_px,
    max_isolated_points=int(config.max_isolated_points),
    max_isolated_length_px=max_isolated_length_px,
  )
  if not candidates:
    # 无候选时返回原路径，但把换算阈值写 debug，便于核对为何未触发清理。
    return IsolatedJumpCleanupResult(
      path_points=path,
      debug={
        "enabled": True,
        "jump_distance_px": jump_distance_px,
        "max_isolated_length_px": max_isolated_length_px,
        "reinsert_max_distance_px": reinsert_max_distance_px,
      },
    )

  # 先统一移除候选片段构建 kept 主路径，后续重插评估基于同一基线。
  removed_indices: set[int] = set()
  inactive: list[InactivePathFragment] = []
  reinserted: list[ReinsertedPathFragment] = []
  # span 已按起点排序，先做一次“索引占用”后统一移除，避免边界插值受处理顺序影响。
  spans = sorted(candidates, key=lambda item: item[0])
  for start, end, _before_jump, _after_jump, _internal_length in spans:
    # 先记录待移除索引，保证跨片段重插评估使用同一基线路径。
    removed_indices.update(range(start, end + 1))
  kept = [point for index, point in enumerate(path) if index not in removed_indices]

  # 用同一份 kept 基线逐段尝试重插，避免某个片段的修改影响后续片段的近邻判断。
  for start, end, before_jump, after_jump, internal_length in spans:
    span = path[start : end + 1]
    # delete_bridge_cost 表示移除片段后两侧直接相连的桥接成本。
    delete_bridge_cost = point_distance_px(path[start - 1], path[end + 1])
    # original_bridge_cost 表示原路径保留该片段时的桥接成本。
    original_bridge_cost = before_jump + internal_length + after_jump
    best_insert_after = -1
    best_near_distance = float("inf")
    best_new_cost = float("inf")
    for insert_after in range(-1, len(kept)):
      # 全量尝试插入位点，避免局部贪心导致次优重插。
      near_distance = _span_near_edge_distance_px(kept, insert_after, span)
      if near_distance > reinsert_max_distance_px:
        # 与该插入位置距离超限，说明非同一局部片段，跳过重插尝试。
        continue
      new_cost = delete_bridge_cost + _insertion_added_cost_px(kept, insert_after, span)
      if new_cost < best_new_cost:
        # 仅保留当前最小增量，为后续成本阈值提供统一基准。
        best_insert_after = int(insert_after)
        best_near_distance = float(near_distance)
        best_new_cost = float(new_cost)

    if best_insert_after >= -1 and best_new_cost <= original_bridge_cost * float(config.reinsert_improvement_ratio):
      # 仅在新成本明显更低时重插，避免引入代价更高的噪声。
      # best_insert_after=-1 意味着插回头部，需额外转换成切片索引。
      insert_at = best_insert_after + 1
      kept[insert_at:insert_at] = span
      reinserted.append(
        ReinsertedPathFragment(
          original_start_index=start + 1,
          original_end_index=end + 1,
          insert_after_index=best_insert_after + 1,
          points=tuple(span),
          original_bridge_cost_px=original_bridge_cost,
          new_cost_px=best_new_cost,
        )
      )
      continue
    # 无法重插的片段移入 inactive，保留链路信息用于复查。
    inactive.append(
      InactivePathFragment(
        start_index=start + 1,
        end_index=end + 1,
        points=tuple(span),
        reason="长跳后的孤立片段无法重插",
        before_jump_px=before_jump,
        after_jump_px=after_jump,
        internal_length_px=internal_length,
      )
    )

  return IsolatedJumpCleanupResult(
    path_points=kept,
    inactive_fragments=tuple(inactive),
    reinserted_fragments=tuple(reinserted),
    candidate_count=len(candidates),
    changed=bool(inactive or reinserted),
    debug={
      "enabled": True,
      "jump_distance_px": jump_distance_px,
      "max_isolated_length_px": max_isolated_length_px,
      "reinsert_max_distance_px": reinsert_max_distance_px,
    },
  )
