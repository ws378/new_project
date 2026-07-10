"""局部邻接候选和全局 fallback 候选的能量评分辅助函数。

规划器在邻接移动和全局 fallback 选点时都会调用这里的评分函数。
评分函数不修改节点状态；候选点是否标记 visited、是否写入路径，由主循环决定。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np

from ..models import CtgGuidanceConfig, LocalDirectionConfig, StrategyConfig, TurnConstraintConfig
from ..final_path.postprocess import point_distance, violates_shape_constraints
from .traversal_history_clearance import HistoryClearanceIndex


SCORE_COMPONENT_DISTANCE_COST = "distance_cost"
SCORE_COMPONENT_TURN_COST = "turn_cost"
SCORE_COMPONENT_LOCAL_DIRECTION_COST = "local_direction_cost"
SCORE_COMPONENT_LEGACY_HORIZONTAL_BIAS = "legacy_horizontal_bias"
SCORE_COMPONENT_LOCAL_LATERAL_COST = "local_lateral_cost"
SCORE_COMPONENT_CTG_SAME_EDGE_REWARD = "ctg_same_edge_reward"
SCORE_COMPONENT_CTG_EDGE_SWITCH_COST = "ctg_edge_switch_cost"
SCORE_COMPONENT_CTG_FALLBACK_EDGE_SWITCH_COST = "ctg_fallback_edge_switch_cost"
SCORE_COMPONENT_CTG_JUNCTION_ENTRY_COST = "ctg_junction_entry_cost"
SCORE_COMPONENT_FALLBACK_JUMP_COST = "fallback_jump_cost"
SCORE_COMPONENT_FALLBACK_HEADING_COST = "fallback_heading_cost"
SCORE_COMPONENT_LOCAL_RESIDUAL_CONTINUE_REWARD = "local_residual_continue_reward"
SCORE_COMPONENT_REVISIT_PENALTY_COST = "revisit_penalty_cost"
SCORE_COMPONENT_REVISIT_FRONTIER_REWARD = "revisit_frontier_reward"
SCORE_COMPONENT_LOCAL_RESIDUAL_LEAVE_COST = "local_residual_leave_cost"
SCORE_COMPONENT_HISTORY_CLEARANCE_COST = "history_clearance_cost"

SCORE_COMPONENT_KEYS = (
  SCORE_COMPONENT_DISTANCE_COST,
  SCORE_COMPONENT_TURN_COST,
  SCORE_COMPONENT_LOCAL_DIRECTION_COST,
  SCORE_COMPONENT_LEGACY_HORIZONTAL_BIAS,
  SCORE_COMPONENT_LOCAL_LATERAL_COST,
  SCORE_COMPONENT_CTG_SAME_EDGE_REWARD,
  SCORE_COMPONENT_CTG_EDGE_SWITCH_COST,
  SCORE_COMPONENT_CTG_FALLBACK_EDGE_SWITCH_COST,
  SCORE_COMPONENT_CTG_JUNCTION_ENTRY_COST,
  SCORE_COMPONENT_FALLBACK_JUMP_COST,
  SCORE_COMPONENT_FALLBACK_HEADING_COST,
  SCORE_COMPONENT_LOCAL_RESIDUAL_CONTINUE_REWARD,
  SCORE_COMPONENT_REVISIT_PENALTY_COST,
  SCORE_COMPONENT_REVISIT_FRONTIER_REWARD,
  SCORE_COMPONENT_LOCAL_RESIDUAL_LEAVE_COST,
  SCORE_COMPONENT_HISTORY_CLEARANCE_COST,
)

REJECT_REASON_SHAPE_CONSTRAINT = "shape_constraint"
REJECT_REASON_TURN_CONSTRAINT = "turn_constraint"
REJECT_REASON_VALUES = (
  REJECT_REASON_SHAPE_CONSTRAINT,
  REJECT_REASON_TURN_CONSTRAINT,
)


@dataclass(frozen=True)
class CandidateScoreBreakdown:
  """候选评分分解结果。
  
  包含总能量、分项和拒绝原因，供 selection 与调参诊断。
  """
  total_energy: float | None
  components: dict[str, float]
  rejected_reasons: tuple[str, ...]
  accepted: bool
  component_sum_valid: bool


@dataclass(frozen=True)
class CandidateScoringGeometry:
  """候选几何向量容器。
  
  约束：仅承载位置与差值计算，不承担策略决策。
  """
  location_point_px: Tuple[float, float]
  candidate_point_px: Tuple[float, float]

  @classmethod
  def from_points(
    cls,
    location_point_px: Tuple[float, float],
    candidate_point_px: Tuple[float, float],
  ) -> "CandidateScoringGeometry":
    """按原始坐标创建标准化几何对象。
    
    将输入点转为 float，减少 int / np.int 混用导致的角度计算抖动。
    """
    return cls(
      location_point_px=(float(location_point_px[0]), float(location_point_px[1])),
      candidate_point_px=(float(candidate_point_px[0]), float(candidate_point_px[1])),
    )

  @property
  def diff_x(self) -> float:
    """返回候选点相对当前位置点的 X 轴位移（像素）。"""
    return float(self.candidate_point_px[0] - self.location_point_px[0])

  @property
  def diff_y(self) -> float:
    """返回候选点相对当前位置点的 Y 轴位移（像素）。"""
    return float(self.candidate_point_px[1] - self.location_point_px[1])


@dataclass(frozen=True)
class CandidateScoringContext:
  """遍历评分所需上下文。
  
  将路径、方向场与策略配置汇聚到一个只读对象，避免参数散落导致约束缺失。
  """
  point_path: Sequence[Tuple[float, float]]
  coverage_width_px: int
  previous_travel_angle: float
  map_resolution: float
  is_global_fallback: bool
  turn_constraint: TurnConstraintConfig
  local_direction_map: Optional[np.ndarray]
  local_direction_confidence: Optional[np.ndarray]
  local_direction_cfg: LocalDirectionConfig
  edge_label_map: Optional[np.ndarray]
  ctg_guidance_cfg: CtgGuidanceConfig
  strategy_cfg: StrategyConfig
  local_residual_count: int
  history_clearance_index: HistoryClearanceIndex | None = None


def clamp_index(value: float, upper: int) -> int:
  """将采样坐标裁剪到图像边界。
  
  用于方向场与 label map 的采样前裁剪，防止越界访问触发运行时异常。
  
  Args:
      value: 任意坐标值。
      upper: 对应数组维度的最大合法下标。
      
  Returns:
      int: 已裁剪到 [0, upper] 区间的整数坐标。
  """
  ivalue = int(value)
  if ivalue < 0:
    # 小于 0 视为边界外采样，返回最小索引避免越界读取。
    return 0
  if ivalue > upper:
    # 大于上界仍可能来自外部缩放坐标，夹到边界最后一格。
    return int(upper)
  return ivalue


def normalize_angle(angle: float) -> float:
  """将角度规范化到 [-pi, pi] 区间。
  
  将角度差拉回主值区间，避免跨 pi 边界时出现 2pi 跳变导致的错误大角度。
  
  Args:
      angle: 输入角度（弧度）。
      
  Returns:
      float: 归一化后的角度（弧度）。
  """
  while angle < -math.pi:
    # 小于 -pi 的角度在同轴上等价于加 2π 后再比较，避免符号突变。
    angle += 2.0 * math.pi
  while angle > math.pi:
    # 大于 pi 的角度反向加减 2π 后才有可比较的最短转角。
    angle -= 2.0 * math.pi
  return angle


def undirected_axis_penalty(travel_angle: float, axis_angle: float) -> float:
  """按无向轴线计算转向惩罚。
  
  通道/货架主轴是无向轴线，行驶方向反向也应视为低转向代价。
  
  Args:
      travel_angle: 当前移动角度（弧度）。
      axis_angle: 参考主轴角度（弧度）。
      
  Returns:
      float: 无向轴线转向惩罚，范围 [0,1]。
  """
  return abs(math.sin(normalize_angle(float(travel_angle) - float(axis_angle))))

def compute_energy_breakdown_for_geometry(
  geometry: CandidateScoringGeometry,
  context: CandidateScoringContext,
) -> CandidateScoreBreakdown:
  """计算单候选几何的能量分项与拒绝结果。
  
  先做硬约束，再按可配置权重计算距离、转角、方向、CTG 与回退相关能量分量。
  
  Args:
      geometry: 候选几何信息，包含候选点与当前位置。
      context: 评分上下文（参数、约束、运行状态）。
      
  Returns:
      CandidateScoreBreakdown: 包含分项、拒绝原因与可否接受标记。
  """
  diff_x = geometry.diff_x
  diff_y = geometry.diff_y
  translational = math.hypot(diff_x, diff_y) / context.coverage_width_px
  travel_angle = math.atan2(diff_y, diff_x)
  diff_angle = normalize_angle(travel_angle - context.previous_travel_angle)
  components: dict[str, float] = {SCORE_COMPONENT_DISTANCE_COST: float(translational)}

  if context.turn_constraint.enable_prohibit and not context.is_global_fallback:
    # 邻接移动阶段先执行硬转角约束；违反时直接返回 prohibit_energy。
    dist_m = math.hypot(diff_x, diff_y) * context.map_resolution
    abs_diff_angle_deg = abs(diff_angle) * 180.0 / math.pi
    if dist_m <= context.turn_constraint.near_dist_m:
      # 近距段优先保护路径连续性，超出门限直接禁止，避免转向抖动。
      if abs_diff_angle_deg > context.turn_constraint.near_max_turn_deg:
        return CandidateScoreBreakdown(
          total_energy=float(context.turn_constraint.prohibit_energy),
          components=components,
          rejected_reasons=(REJECT_REASON_TURN_CONSTRAINT,),
          accepted=False,
          component_sum_valid=False,
        )
    else:
      allowed_max_turn_deg = context.turn_constraint.neighbor_max_turn_deg
      if context.is_global_fallback:
        # 当前分支理论上不会进入，因为外层限定 not is_global_fallback；保留公式表达配置语义。
        denom = max(1e-9, context.turn_constraint.fallback_relax_dist_m - context.turn_constraint.near_dist_m)
        t = min(1.0, max(0.0, (dist_m - context.turn_constraint.near_dist_m) / denom))
        allowed_max_turn_deg = context.turn_constraint.neighbor_max_turn_deg + (
          context.turn_constraint.fallback_max_turn_deg - context.turn_constraint.neighbor_max_turn_deg
        ) * t
      # 距离越远允许的转角可放宽，但仍以 allowed_max_turn_deg 为统一上限。
      if abs_diff_angle_deg > allowed_max_turn_deg:
        return CandidateScoreBreakdown(
          total_energy=float(context.turn_constraint.prohibit_energy),
          components=components,
          rejected_reasons=(REJECT_REASON_TURN_CONSTRAINT,),
          accepted=False,
          component_sum_valid=False,
        )

  rotational = abs(diff_angle) * (2.0 / math.pi)
  components[SCORE_COMPONENT_TURN_COST] = float(rotational)
  energy = translational + rotational

  if (
    context.local_direction_cfg.enable
    and context.local_direction_map is not None
    and context.local_direction_confidence is not None
  ):
    # 用候选节点位置采样局部主轴，移动方向越偏离主轴，能量越高。
    sample_x = clamp_index(geometry.candidate_point_px[0], context.local_direction_map.shape[1] - 1)
    sample_y = clamp_index(geometry.candidate_point_px[1], context.local_direction_map.shape[0] - 1)
    local_preferred_angle = float(context.local_direction_map[sample_y, sample_x])
    local_confidence = float(context.local_direction_confidence[sample_y, sample_x])
    if local_confidence >= context.local_direction_cfg.min_confidence:
      direction_penalty = undirected_axis_penalty(travel_angle, local_preferred_angle)
      value = context.local_direction_cfg.energy_weight * local_confidence * direction_penalty
      components[SCORE_COMPONENT_LOCAL_DIRECTION_COST] = float(value)
      energy += value
  else:
    # 没有方向场时沿用旧逻辑：水平移动能量更低，纵向移动更贵。
    horizontal_movement_ratio = abs(diff_x) / (abs(diff_x) + abs(diff_y) + 1e-6)
    horizontal_reward = 8.0 - 1.5 * horizontal_movement_ratio
    components[SCORE_COMPONENT_LEGACY_HORIZONTAL_BIAS] = float(horizontal_reward)
    energy += horizontal_reward

  if (
    context.strategy_cfg.local_lateral_weight > 0.0
    and context.local_direction_map is not None
    and context.local_direction_confidence is not None
  ):
    # lateral 惩罚使用当前位置的主轴，约束“离开当前通道/货架边”的移动。
    sample_x = clamp_index(geometry.location_point_px[0], context.local_direction_map.shape[1] - 1)
    sample_y = clamp_index(geometry.location_point_px[1], context.local_direction_map.shape[0] - 1)
    current_preferred_angle = float(context.local_direction_map[sample_y, sample_x])
    current_confidence = float(context.local_direction_confidence[sample_y, sample_x])
    if current_confidence >= context.local_direction_cfg.min_confidence:
      lateral_ratio = undirected_axis_penalty(travel_angle, current_preferred_angle)
      value = context.strategy_cfg.local_lateral_weight * current_confidence * lateral_ratio
      components[SCORE_COMPONENT_LOCAL_LATERAL_COST] = float(value)
      energy += value

  if context.ctg_guidance_cfg.enable and context.edge_label_map is not None:
    # CTG edge label 在旋转图坐标系采样，约束路径优先沿同一 edge territory 推进。
    current_x = clamp_index(geometry.location_point_px[0], context.edge_label_map.shape[1] - 1)
    current_y = clamp_index(geometry.location_point_px[1], context.edge_label_map.shape[0] - 1)
    next_x = clamp_index(geometry.candidate_point_px[0], context.edge_label_map.shape[1] - 1)
    next_y = clamp_index(geometry.candidate_point_px[1], context.edge_label_map.shape[0] - 1)
    current_edge = int(context.edge_label_map[current_y, current_x])
    next_edge = int(context.edge_label_map[next_y, next_x])
    if current_edge >= 0 and next_edge >= 0:
      if current_edge == next_edge:
        # 同一 edge 内连续清扫更符合语义覆盖顺序。
        value = -context.ctg_guidance_cfg.same_edge_reward
        components[SCORE_COMPONENT_CTG_SAME_EDGE_REWARD] = float(value)
        energy += value
      else:
        # 跨 edge 切换可能意味着穿过 junction 或跳到另一条货架边，成本更高。
        components[SCORE_COMPONENT_CTG_EDGE_SWITCH_COST] = float(context.ctg_guidance_cfg.edge_switch_penalty)
        energy += context.ctg_guidance_cfg.edge_switch_penalty
        if context.is_global_fallback:
          components[SCORE_COMPONENT_CTG_FALLBACK_EDGE_SWITCH_COST] = float(context.ctg_guidance_cfg.fallback_edge_switch_penalty)
          energy += context.ctg_guidance_cfg.fallback_edge_switch_penalty
    elif current_edge >= 0 and next_edge < 0:
      # 从明确 edge 进入未归属/junction 区域时给轻微惩罚。
      components[SCORE_COMPONENT_CTG_JUNCTION_ENTRY_COST] = float(context.ctg_guidance_cfg.junction_entry_penalty)
      energy += context.ctg_guidance_cfg.junction_entry_penalty

  if context.is_global_fallback:
    # fallback 是非邻接跳转，额外惩罚长跳和大角度跳转，避免输出路径碎片化。
    dist_ratio = max(0.0, translational - 1.0)
    if context.strategy_cfg.fallback_jump_weight > 0.0:
      value = context.strategy_cfg.fallback_jump_weight * dist_ratio * dist_ratio
      components[SCORE_COMPONENT_FALLBACK_JUMP_COST] = float(value)
      energy += value
    if context.strategy_cfg.fallback_heading_weight > 0.0:
      value = context.strategy_cfg.fallback_heading_weight * abs(diff_angle) * (2.0 / math.pi)
      components[SCORE_COMPONENT_FALLBACK_HEADING_COST] = float(value)
      energy += value

  return CandidateScoreBreakdown(
    total_energy=float(energy),
    components=components,
    rejected_reasons=(),
    accepted=True,
    component_sum_valid=True,
  )


def min_distance_to_path(
  candidate_point: Tuple[float, float],
  path_points: Sequence[Tuple[float, float]],
  skip_recent: int = 12,
) -> float:
  """回退路径距离估计（慢速实现）。
  
  仅在 HistoryClearanceIndex 不可用时使用，返回候选点到历史路径最小距离。
  
  Args:
      candidate_point: 候选点坐标。
      path_points: 历史路径点序列。
      skip_recent: 最近 N 个点跳过用于避免惩罚局部连续动作。
      
  Returns:
      float: candidate_point 到历史路径的最小距离；无历史路径时为 inf。
  """
  if not path_points:
    # 空历史路径无法构成距离约束，返回 inf 让上层保守处理。
    return float("inf")
  usable_points = path_points[:-skip_recent] if len(path_points) > skip_recent else []
  if not usable_points:
    # 仅保留 skip_recent 以外历史时若无可用点，说明尚无长期轨迹可比。
    return float("inf")
  return min(point_distance(candidate_point, visited_point) for visited_point in usable_points)


def local_residual_bonus(candidate_local_residual_count: int, strategy_cfg: StrategyConfig) -> float:
  """基于周边未访问残量的奖励项。
  
  候选周边未覆盖越多，奖励越高，用于抑制过早离开局部清扫。
  
  Args:
      candidate_local_residual_count: 候选周边未访问节点数。
      strategy_cfg: 策略配置（local_residual_continue_weight）。
      
  Returns:
      float: 局部残量奖励分。
  """
  if strategy_cfg.local_residual_continue_weight <= 0.0:
    # 未配置奖励权重时不引入残量奖励，避免对既有距离排序引入额外干扰。
    return 0.0
  return strategy_cfg.local_residual_continue_weight * int(candidate_local_residual_count)


def history_clearance_penalty(
  candidate_point: Tuple[float, float],
  path_points: Sequence[Tuple[float, float]],
  coverage_width_px: int,
  strategy_cfg: StrategyConfig,
  history_clearance_index: HistoryClearanceIndex | None = None,
) -> float:
  """历史贴近惩罚项。
  
  用于 fallback 场景，抑制大跳后紧贴历史路径导致的重复覆盖。
  
  Args:
      candidate_point: 待评估候选点。
      path_points: 历史路径坐标序列。
      coverage_width_px: 覆盖宽度（像素），用于归一化惩罚。
      strategy_cfg: 策略配置（history_clearance_weight 等）。
      history_clearance_index: 可选的路径索引；存在则走 O(1) 邻域查询。
      
  Returns:
      float: 历史贴近惩罚，非 fallback 或权重关闭时为 0。
  """
  if strategy_cfg.history_clearance_weight <= 0.0:
    # 历史贴近惩罚权重关闭时直接返回，保持 fallback 与常规模式评分一致。
    return 0.0
  clearance_limit = coverage_width_px * strategy_cfg.history_clearance_radius_factor
  if history_clearance_index is not None:
    # 有索引时走 O(1) 邻域查询，避免对长路径做全量遍历。
    clearance = history_clearance_index.min_distance(candidate_point)
  else:
    # 索引未就绪时退化为路径最小距离扫描，保持评分可用。
    clearance = min_distance_to_path(candidate_point, path_points)
  if clearance >= clearance_limit:
    # 距离超过安全半径时不再追加惩罚，降低对远离历史路径动作的抑制。
    return 0.0
  # 越接近历史路径，惩罚越高；coverage_width_px 用于归一化不同分辨率/覆盖宽度。
  return strategy_cfg.history_clearance_weight * (clearance_limit - clearance) / max(1.0, coverage_width_px)


def evaluate_candidate_score_for_geometry(
  geometry: CandidateScoringGeometry,
  *,
  context: CandidateScoringContext,
  candidate_local_residual_count: int = 0,
  candidate_visit_count: int = 0,
  revisit_frontier_score: int = 0,
) -> CandidateScoreBreakdown:
  """对候选几何执行完整评分并返回分解。
  
  先执行形状硬约束，不满足时返回拒绝记录并由上层按顺序判定是否可采纳。
  
  Args:
      geometry: 候选几何。
      context: 评分上下文。
      candidate_local_residual_count: 邻近残量。
      candidate_visit_count: 候选历史访问次数。
      revisit_frontier_score: 接 frontier 分值。
  
  Returns:
      CandidateScoreBreakdown: 接受状态、分项得分和拒绝原因。
  """
  candidate_point = geometry.candidate_point_px
  if violates_shape_constraints(context.point_path, candidate_point, context.coverage_width_px, context.strategy_cfg):
    # 形状约束失败会直接拒绝该候选，避免路径被“短折返清理器”放大为抖动。
    return CandidateScoreBreakdown(
      total_energy=None,
      components={},
      rejected_reasons=(REJECT_REASON_SHAPE_CONSTRAINT,),
      accepted=False,
      component_sum_valid=False,
    )

  score = compute_energy_breakdown_for_geometry(
    geometry,
    context,
  )
  if not score.accepted:
    # 能量分解未通过时保留拒绝原因，供决策日志和复盘聚合。
    return score
  assert score.total_energy is not None
  energy = float(score.total_energy)
  components = dict(score.components)
  if context.turn_constraint.enable_prohibit and energy >= context.turn_constraint.prohibit_energy:
    # 可达评分里先保留硬约束边界，超限后不参与 soft 目标值比较。
    # prohibit_energy 是硬禁止信号，不进入普通 min-energy 比较。
    return CandidateScoreBreakdown(
      total_energy=float(energy),
      components=components,
      rejected_reasons=(REJECT_REASON_TURN_CONSTRAINT,),
      accepted=False,
      component_sum_valid=False,
    )

  # 局部残留 bonus 会降低能量，鼓励继续覆盖邻近未访问区域。
  residual_bonus = local_residual_bonus(candidate_local_residual_count, context.strategy_cfg)
  if residual_bonus:
    # 残量奖励仅在 >0 时扣减能量，用于偏向继续清扫局部未覆盖区域。
    components[SCORE_COMPONENT_LOCAL_RESIDUAL_CONTINUE_REWARD] = -float(residual_bonus)
  energy -= residual_bonus

  if revisit_frontier_score > 0:
    # frontier 有值时加入“重复访问惩罚 - frontier 奖励”平衡，维持重连能力与抑制抖动。
    # revisit 候选既要承担重复访问惩罚，也会因能到达 frontier 获得奖励。
    revisit_cost = context.strategy_cfg.revisit_penalty * max(1, int(candidate_visit_count))
    revisit_reward = context.strategy_cfg.revisit_frontier_weight * revisit_frontier_score
    components[SCORE_COMPONENT_REVISIT_PENALTY_COST] = float(revisit_cost)
    components[SCORE_COMPONENT_REVISIT_FRONTIER_REWARD] = -float(revisit_reward)
    energy += revisit_cost
    energy -= revisit_reward

  if context.is_global_fallback:
    # 全局回退下额外约束优先级更高，既要惩罚离开局部，也要抑制贴近历史路径。
    if context.strategy_cfg.local_residual_leave_penalty > 0.0 and context.local_residual_count > 0:
      # 还有局部残留时惩罚离开，避免过早全局跳转吞掉邻域未覆盖。
      # 当前局部还有残留时，提高离开成本，降低过早全局跳转。
      value = context.strategy_cfg.local_residual_leave_penalty * context.local_residual_count
      components[SCORE_COMPONENT_LOCAL_RESIDUAL_LEAVE_COST] = float(value)
      energy += value
    history_cost = history_clearance_penalty(
      candidate_point,
      context.point_path,
      context.coverage_width_px,
      context.strategy_cfg,
      context.history_clearance_index,
    )
    if history_cost:
      # 仅在非零惩罚时回填组件，便于后续定位 fallback 回退行为贡献。
      components[SCORE_COMPONENT_HISTORY_CLEARANCE_COST] = float(history_cost)
    energy += history_cost

  return CandidateScoreBreakdown(
    total_energy=float(energy),
    components=components,
    rejected_reasons=(),
    accepted=True,
    component_sum_valid=True,
  )
