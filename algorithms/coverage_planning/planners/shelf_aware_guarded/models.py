"""shelf_aware 守护覆盖规划的数据模型定义。

用途：
  - 定义 planner 内部核心数据结构（节点、策略、约束、artifact 路径）。
  - 提供结构化配置序列化接口，便于 profile/日志与复现。

输入：
  - 上层通过 `PlannerConfig` 传入的参数组。

输出：
  - `to_dict()`/`planner_params_dict()` 产出的可序列化配置快照。

依赖与限制：
  - 该文件仅承载结构与轻量转换逻辑，不应包含长距离几何推导。
  - `np.ndarray` 字段保持引用语义，JSON 序列化需通过对应 `to_dict()` 路径剥离。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

import numpy as np


Point = Tuple[int, int]


@dataclass
class Node:
  """规划图节点的运行态单元。

  该对象同时承担图拓扑、障碍/访问状态和调试元信息，便于在多个 pipeline 阶段共享。
  `planning_point_px` 为实际生效点位，而 `grid_center_px` 作为规则格子锚点用于可复现识别。

  Notes:
    该类以可变状态（如 `visited`、`visit_count`）为主，适合在一次规划运行内维护，不建议跨运行复用。
  """

  # planning_point_px 是实际用于规划的旋转图像坐标，可能不同于规则网格中心。
  planning_point_px: Point
  # grid_center_px 是规则网格中心；生成后保持不变，用于调试和稳定分组。
  grid_center_px: Point
  # obstacle=True 的节点代表该 cell 没有可用 free 像素，遍历时会被直接跳过。
  obstacle: bool = True
  # visited 是覆盖主循环的状态位，不参与网格构建本身。
  visited: bool = False
  # visit_count 支持 revisit bridge 策略，普通覆盖节点首次访问后为 1。
  visit_count: int = 0
  # neighbors 中保留障碍邻居，方便后续统计边界和拓扑连接度。
  neighbors: List["Node"] = field(default_factory=list)
  # grid_row/grid_col 给节点一个稳定调试 id，避免用对象 id 这类进程内值。
  grid_row: int = -1
  grid_col: int = -1
  # obstacle_ratio 记录机器人宽度方窗内的障碍比例；None 表示未启用该过滤。
  obstacle_ratio: float | None = None
  # obstacle_ratio_filtered=True 表示该节点由规划前障碍比例过滤置为障碍。
  obstacle_ratio_filtered: bool = False

  def count_non_obstacle_neighbors(self) -> int:
    """统计非障碍邻居数量。

    该计数用于角点识别与连接价值评估；忽略障碍邻居可避免把断连节点误判为可达通道。

    Returns:
      int: 可通行邻居数量。
    """
    return sum(1 for neighbor in self.neighbors if not neighbor.obstacle)

  @property
  def stable_id(self) -> str:
    """返回稳定节点 id（基于网格行列），用于日志对齐和去重。"""
    return f"r{self.grid_row}_c{self.grid_col}"

  @property
  def adjusted_from_grid_center_px(self) -> bool:
    """指示节点是否发生过与网格中心不同的坐标修正。

    Returns:
      bool: True 代表实际规划点被调整过，主要用于修复后的候选差异追踪。
    """
    return self.planning_point_px != self.grid_center_px


@dataclass
class TurnConstraintConfig:
  """TurnConstraint 转向约束参数集合。

  在邻接阶段和 fallback 阶段分别设置不同阈值，目标是：
  - 压制起点及低速段的小角抖动；
  - 允许全局跳转阶段出现更大角度以降低死锁风险。
  
  与速度无关，仅对候选几何方向施加硬约束或评分惩罚。
  """

  # enable_prohibit=True 时，违反转角约束的候选会被打成 prohibit_energy 并过滤。
  enable_prohibit: bool = False
  # prohibit_energy 取极大值，避免和普通评分项混淆。
  prohibit_energy: float = 1_000_000.0
  # near_dist_m 内使用更严格的近距离转角限制，降低原地大角度折返。
  near_dist_m: float = 0.1
  near_max_turn_deg: float = 20.0
  # 邻接移动和全局 fallback 分别使用不同最大转角，fallback 允许更大跳转。
  neighbor_max_turn_deg: float = 90.0
  fallback_max_turn_deg: float = 135.0
  # fallback_relax_dist_m 控制从邻接转角阈值过渡到 fallback 阈值的距离尺度。
  fallback_relax_dist_m: float = 5.0

  def to_dict(self) -> dict:
    """返回用于 artifacts 记录的可序列化字典。"""
    return {
      "enable_prohibit": self.enable_prohibit,
      "near_max_turn_deg": self.near_max_turn_deg,
      "neighbor_max_turn_deg": self.neighbor_max_turn_deg,
      "fallback_max_turn_deg": self.fallback_max_turn_deg,
      "fallback_relax_dist_m": self.fallback_relax_dist_m,
    }


@dataclass
class LocalDirectionConfig:
  """局部方向场配置。

  通过方向场对候选运动方向加权，优先沿局部主轴移动；低置信度时应避开强约束，减少噪声放大。
  """

  # enable=False 时使用旧的水平移动偏好兜底评分。
  enable: bool = True
  # window_size_px/smooth_sigma 用于从图像梯度估计局部主方向场。
  window_size_px: int = 41
  smooth_sigma: float = 6.0
  # energy_weight 决定移动方向偏离局部主轴时的惩罚强度。
  energy_weight: float = 2.5
  # 低置信度方向场不参与评分，避免噪声主导路径。
  min_confidence: float = 0.08

  def to_dict(self) -> dict:
    """导出方向场参数快照，确保回放与 artifacts 可复用一致配置。"""
    return {
      "enable": self.enable,
      "window_size_px": self.window_size_px,
      "smooth_sigma": self.smooth_sigma,
      "energy_weight": self.energy_weight,
      "min_confidence": self.min_confidence,
    }


@dataclass
class CtgGuidanceConfig:
  """CTG（Connectivity/Topology）引导配置。

  通过 edge/junction 语义的奖励与惩罚引导路径顺序，防止跨语义边界的无意义跳变。
  """

  # CTG 引导默认关闭；只有外部 edge label map 可信时才参与能量评分。
  enable: bool = False
  # 同一 edge 内移动给奖励，跨 edge 或进入 junction 给惩罚。
  same_edge_reward: float = 0.35
  edge_switch_penalty: float = 1.2
  junction_entry_penalty: float = 0.15
  # fallback 跨 edge 的成本更高，避免大跳直接破坏语义顺序。
  fallback_edge_switch_penalty: float = 3.0

  def to_dict(self) -> dict:
    """导出 CTG 配置参数快照，保证复盘可复原语义评分约束。"""
    return {
      "enable": self.enable,
      "same_edge_reward": self.same_edge_reward,
      "edge_switch_penalty": self.edge_switch_penalty,
      "junction_entry_penalty": self.junction_entry_penalty,
      "fallback_edge_switch_penalty": self.fallback_edge_switch_penalty,
    }


@dataclass
class IsolatedJumpCleanupConfig:
  """孤立跳变片段治理配置。

  用于在路径后处理中治理离散小片段跳变，避免误报异常与短回跳污染覆盖结果。
  """

  # 该配置属于最终输出层治理，不影响主遍历和 semantic path 的节点状态。
  enable: bool = True
  # 两侧连接距离超过 jump_distance_m 时，片段才可能被判定为孤立跳变片段。
  jump_distance_m: float = 3.0
  # 只处理短片段，避免误删真实覆盖走廊或长区域。
  max_isolated_points: int = 3
  max_isolated_length_m: float = 1.0
  # 片段能插回主路径附近时优先重插，否则才标记 inactive 并从输出路径移除。
  reinsert_max_distance_m: float = 1.0
  reinsert_improvement_ratio: float = 0.80

  def to_dict(self) -> dict:
    """导出孤立跳变治理参数，便于策略复盘和跨版本比对。"""
    return {
      "enable": bool(self.enable),
      "jump_distance_m": float(self.jump_distance_m),
      "max_isolated_points": int(self.max_isolated_points),
      "max_isolated_length_m": float(self.max_isolated_length_m),
      "reinsert_max_distance_m": float(self.reinsert_max_distance_m),
      "reinsert_improvement_ratio": float(self.reinsert_improvement_ratio),
    }


@dataclass
class StrategyConfig:
  """StrategyConfig 策略参数与策略分组定义。

  该配置定义一次遍历从局部候选评估、连续性控制到后处理的总策略参数。
  通过参数分组（foundation/continuity/postprocess/residual）约束不同阶段行为。
  
  覆盖的语义域：
  - foundation：fallback 与方向相关基础评分；
  - continuity：局部连续性约束；
  - postprocess：输出路径简化与分段；
  - residual/history：历史残留与避让历史路径行为。

  from_payload 会按分组/顶层键兼容读取，增强 profile 的演进兼容性。
  """

  # name/description 用于 artifact 记录当前策略来源，不参与评分。
  name: str = "default"
  description: str = ""
  # foundation：fallback 和局部方向偏好的基础评分项。
  fallback_jump_weight: float = 0.0
  fallback_heading_weight: float = 0.0
  local_lateral_weight: float = 0.0
  # revisit bridge 允许短暂经过已访问节点，以连接仍有未访问 frontier 的区域。
  allow_revisit_bridge: bool = False
  max_revisit_count: int = 2
  revisit_penalty: float = 4.0
  revisit_frontier_depth: int = 2
  revisit_frontier_weight: float = 1.4
  # continuity：在线候选过滤，减少近距离掉头和短锯齿。
  near_reverse_enable: bool = False
  near_reverse_max_dist_factor: float = 1.4
  near_reverse_prohibit_deg: float = 120.0
  short_zigzag_enable: bool = False
  short_zigzag_seg_factor: float = 1.6
  short_zigzag_prohibit_deg: float = 145.0
  # postprocess：遍历完成后的简化和分段阈值。
  simplify_enable: bool = True
  simplify_short_seg_factor: float = 1.6
  simplify_turn_deg: float = 145.0
  split_turn_deg: float = 150.0
  split_jump_dist_factor: float = 10.0
  # residual/history：避免过早离开局部残留，同时降低 fallback 贴近历史路径的倾向。
  local_residual_radius_steps: int = 2
  local_residual_continue_weight: float = 0.0
  local_residual_leave_penalty: float = 0.0
  history_clearance_weight: float = 0.0
  history_clearance_radius_factor: float = 2.0

  @staticmethod
  def _read_section(payload: dict, section: str) -> dict:
    """读取 payload 中的策略分组；非字典分组返回空以防止异常。

    Args:
      payload: 外部 profile 字典。
      section: 分组名，例如 meta/foundation/continuity/postprocess。

    Returns:
      dict: 对应分组对象，非法类型时为空字典。
    """
    value = payload.get(section, {})
    # 非字典分组会导致后续 `key in section` 崩溃，统一兜底为空字典。
    return value if isinstance(value, dict) else {}

  @classmethod
  def from_payload(cls, payload: dict, fallback: Optional["StrategyConfig"] = None) -> "StrategyConfig":
    """从 payload 兼容构建 StrategyConfig。

    支持三类来源：顶层字段优先，其次 foundation/continuity/postprocess/meta 分组；
    任何缺失项都回落到 fallback，以保持 profile 逐步演进时的兼容性。

    Args:
      payload: 外部策略配置。
      fallback: 上一版本基线；未提供时使用默认实例。

    Returns:
      StrategyConfig: 构建后的完整策略配置。
    """
    fallback = fallback or cls()
    foundation = cls._read_section(payload, "foundation")
    continuity = cls._read_section(payload, "continuity")
    postprocess = cls._read_section(payload, "postprocess")
    meta = cls._read_section(payload, "meta")

    def pick(key: str, default):
      """从多源配置中选择参数，优先级：顶层 -> foundation -> continuity -> postprocess -> meta。

      Args:
        key: 要读取的配置字段名。
        default: 当前层级都不存在时回落到该值。

      Returns:
        任一来源匹配字段值，否则返回 default。
      """
      # 按固定优先级查找，避免配置同名时出现“局部覆盖全局默认”的歧义。
      if key in payload:
        # 最高优先级：顶层字段直接生效，适配运行时快速热修复。
        return payload[key]
      if key in foundation:
        # foundation 常用于通用参数，先于 continuity 兼容历史写法。
        return foundation[key]
      if key in continuity:
        # continuity 组承担回退/局部约束参数，缺省时沿用更低优先级。
        return continuity[key]
      if key in postprocess:
        # postprocess 记录输出行为相关参数，仅在未覆盖时再读取。
        return postprocess[key]
      if key in meta:
        # meta 保留兼容性冗余值，最后尝试，避免因新增分组变更中断运行。
        return meta[key]
      # 无来源命中则回落到 fallback，实现 profile 逐步演进时的前向兼容。
      return default

    return cls(
      name=str(pick("name", fallback.name)),
      description=str(pick("description", fallback.description)),
      fallback_jump_weight=float(pick("fallback_jump_weight", fallback.fallback_jump_weight)),
      fallback_heading_weight=float(pick("fallback_heading_weight", fallback.fallback_heading_weight)),
      local_lateral_weight=float(pick("local_lateral_weight", fallback.local_lateral_weight)),
      allow_revisit_bridge=bool(pick("allow_revisit_bridge", fallback.allow_revisit_bridge)),
      max_revisit_count=int(pick("max_revisit_count", fallback.max_revisit_count)),
      revisit_penalty=float(pick("revisit_penalty", fallback.revisit_penalty)),
      revisit_frontier_depth=int(pick("revisit_frontier_depth", fallback.revisit_frontier_depth)),
      revisit_frontier_weight=float(pick("revisit_frontier_weight", fallback.revisit_frontier_weight)),
      near_reverse_enable=bool(pick("near_reverse_enable", fallback.near_reverse_enable)),
      near_reverse_max_dist_factor=float(pick("near_reverse_max_dist_factor", fallback.near_reverse_max_dist_factor)),
      near_reverse_prohibit_deg=float(pick("near_reverse_prohibit_deg", fallback.near_reverse_prohibit_deg)),
      short_zigzag_enable=bool(pick("short_zigzag_enable", fallback.short_zigzag_enable)),
      short_zigzag_seg_factor=float(pick("short_zigzag_seg_factor", fallback.short_zigzag_seg_factor)),
      short_zigzag_prohibit_deg=float(pick("short_zigzag_prohibit_deg", fallback.short_zigzag_prohibit_deg)),
      simplify_enable=bool(pick("simplify_enable", fallback.simplify_enable)),
      simplify_short_seg_factor=float(pick("simplify_short_seg_factor", fallback.simplify_short_seg_factor)),
      simplify_turn_deg=float(pick("simplify_turn_deg", fallback.simplify_turn_deg)),
      split_turn_deg=float(pick("split_turn_deg", fallback.split_turn_deg)),
      split_jump_dist_factor=float(pick("split_jump_dist_factor", fallback.split_jump_dist_factor)),
      local_residual_radius_steps=int(pick("local_residual_radius_steps", fallback.local_residual_radius_steps)),
      local_residual_continue_weight=float(pick("local_residual_continue_weight", fallback.local_residual_continue_weight)),
      local_residual_leave_penalty=float(pick("local_residual_leave_penalty", fallback.local_residual_leave_penalty)),
      history_clearance_weight=float(pick("history_clearance_weight", fallback.history_clearance_weight)),
      history_clearance_radius_factor=float(pick("history_clearance_radius_factor", fallback.history_clearance_radius_factor)),
    )

  def to_dict(self) -> dict:
    """输出带分组的策略字典，用于 artifact/重放对齐。"""
    return {
      "meta": {
        "name": self.name,
        "description": self.description,
      },
      "foundation": {
        "fallback_jump_weight": self.fallback_jump_weight,
        "fallback_heading_weight": self.fallback_heading_weight,
        "local_lateral_weight": self.local_lateral_weight,
        "allow_revisit_bridge": self.allow_revisit_bridge,
        "max_revisit_count": self.max_revisit_count,
        "revisit_penalty": self.revisit_penalty,
        "revisit_frontier_depth": self.revisit_frontier_depth,
        "revisit_frontier_weight": self.revisit_frontier_weight,
      },
      "continuity": {
        "near_reverse_enable": self.near_reverse_enable,
        "near_reverse_max_dist_factor": self.near_reverse_max_dist_factor,
        "near_reverse_prohibit_deg": self.near_reverse_prohibit_deg,
        "short_zigzag_enable": self.short_zigzag_enable,
        "short_zigzag_seg_factor": self.short_zigzag_seg_factor,
        "short_zigzag_prohibit_deg": self.short_zigzag_prohibit_deg,
        "local_residual_radius_steps": self.local_residual_radius_steps,
        "local_residual_continue_weight": self.local_residual_continue_weight,
        "local_residual_leave_penalty": self.local_residual_leave_penalty,
        "history_clearance_weight": self.history_clearance_weight,
        "history_clearance_radius_factor": self.history_clearance_radius_factor,
      },
      "postprocess": {
        "simplify_enable": self.simplify_enable,
        "simplify_short_seg_factor": self.simplify_short_seg_factor,
        "simplify_turn_deg": self.simplify_turn_deg,
        "split_turn_deg": self.split_turn_deg,
        "split_jump_dist_factor": self.split_jump_dist_factor,
      },
    }


@dataclass
class PlannerConfig:
  """planner 全量运行参数。

  约定：
  - 覆盖宽度（coverage_width）与机器人宽度（robot_width）分离，避免参数语义混淆。
  - 栅格起点 `start_pixel` 作为入口状态，后续经过旋转与约束归一化处理。
  - 所有可序列化参数通过 `planner_params_dict()` 提供。
  """

  # coverage_width_m 是该算法内部的正式覆盖宽度语义，后续统一换算到像素步长。
  coverage_width_m: float = 0.6
  # robot_width_m 是碰撞安全宽度，和覆盖节拍分开使用。
  robot_width_m: float = 0.4
  # start_pixel 是原始 room_map 坐标系下的手动起点，进入 planner 后会旋转到节点图坐标系。
  start_pixel: Optional[Point] = None
  # region_polygon/region_mask 是阶段2预处理后的区域真值，主要用于 artifact 和可视化边界。
  region_polygon: Optional[List[Point]] = None
  region_mask: Optional[np.ndarray] = None
  # save_debug_csv 控制 CSV 诊断明细；write_artifacts 控制所有文件型 artifact 是否写出。
  save_debug_csv: bool = True
  write_artifacts: bool = True
  turn_constraint: TurnConstraintConfig = field(default_factory=TurnConstraintConfig)
  local_direction: LocalDirectionConfig = field(default_factory=LocalDirectionConfig)
  external_axis_direction_map: Optional[np.ndarray] = None
  external_axis_confidence_map: Optional[np.ndarray] = None
  # blend=True 时外部方向场会和图像梯度方向融合，避免外部语义局部失真。
  external_axis_blend_with_image_gradient: bool = False
  # 外部 CTG label map 保持原图尺寸，planner 内部按房间旋转矩阵同步旋转。
  external_edge_label_map: Optional[np.ndarray] = None
  external_junction_label_map: Optional[np.ndarray] = None
  # semantic path 是遍历后的语义重排/补强阶段，可单独关闭以回到纯能量路径。
  semantic_path_enable: bool = True
  semantic_actual_clean_width_m: float = 0.70
  ctg_guidance: CtgGuidanceConfig = field(default_factory=CtgGuidanceConfig)
  node_generation_mode: str = "shelf_cell_adjusted"
  repaired_grid_max_offset_factor: float = 0.35
  row_endpoint_alignment_enable: bool = True
  node_obstacle_ratio_filter_enable: bool = True
  node_obstacle_ratio_threshold: float = 0.45
  isolated_jump_cleanup: IsolatedJumpCleanupConfig = field(default_factory=IsolatedJumpCleanupConfig)
  strategy: StrategyConfig = field(default_factory=StrategyConfig)

  def planner_params_dict(self) -> dict:
    """返回 artifacts 可记录的 planner 参数快照。

    返回值不包含大数组对象，仅保留开关、数字和嵌套 dict，便于日志落库和复现比对。
    """
    return {
      "coverage_width_m": self.coverage_width_m,
      "robot_width_m": self.robot_width_m,
      "save_debug_csv": self.save_debug_csv,
      "write_artifacts": bool(self.write_artifacts),
      "turn_constraint": self.turn_constraint.to_dict(),
      "local_direction": self.local_direction.to_dict(),
      "external_axis_direction_enabled": self.external_axis_direction_map is not None,
      "external_axis_blend_with_image_gradient": self.external_axis_blend_with_image_gradient,
      "external_edge_label_enabled": self.external_edge_label_map is not None,
      "external_junction_label_enabled": self.external_junction_label_map is not None,
      "semantic_path_enable": bool(self.semantic_path_enable),
      "semantic_actual_clean_width_m": float(self.semantic_actual_clean_width_m),
      "ctg_guidance": self.ctg_guidance.to_dict(),
      "node_generation_mode": str(self.node_generation_mode),
      "repaired_grid_max_offset_factor": float(self.repaired_grid_max_offset_factor),
      "row_endpoint_alignment_enable": bool(self.row_endpoint_alignment_enable),
      "node_obstacle_ratio_filter_enable": bool(self.node_obstacle_ratio_filter_enable),
      "node_obstacle_ratio_threshold": float(self.node_obstacle_ratio_threshold),
      "isolated_jump_cleanup": self.isolated_jump_cleanup.to_dict(),
      "strategy": self.strategy.to_dict(),
    }


@dataclass
class PlannerArtifacts:
  """执行期间产生的 artifact 路径容器。

  设计为集中入口，便于上层只消费一组路径信息；当不写入文件时路径可为 None。
  """

  # output_dir 始终返回，具体文件路径在 write_artifacts=False 时返回 None。
  output_dir: str
  rotated_map_path: Optional[str]
  overlay_path: Optional[str]
  nodes_path: Optional[str]
  path_pixels_path: Optional[str]
  path_world_path: Optional[str]
  debug_csv_path: Optional[str]
  local_direction_path: Optional[str] = None
  baseline_path_pixels_path: Optional[str] = None
  node_semantics_path: Optional[str] = None
  semantic_path_path: Optional[str] = None
  isolated_jump_cleanup_path: Optional[str] = None
  node_obstacle_ratio_filter_path: Optional[str] = None
  path_generation_provenance_path: Optional[str] = None
  final_segment_provenance_path: Optional[str] = None
  candidate_decision_debug_path: Optional[str] = None
  pipeline_trace_path: Optional[str] = None
  artifact_manifest_path: Optional[str] = None
  final_path_transform_records: list[dict[str, Any]] = field(default_factory=list)
