"""货架感知 guarded 覆盖规划入口适配器。

用途：
  - 封装 shelf-aware 覆盖规划流水线的入口，对上游输入进行最小适配与配置归一化。
  - 生成本次执行的 artifacts 目录与运行元数据，统一调用 `plan_coverage_path`。
  - 将核心返回值转换为公共接口 `CoverageResult`。

输入：
  - 占据图（`room_map`）
  - 地图分辨率与原点
  - 起始像素坐标
  - 可选的方向/边缘/交汇标签图与区域掩码

输出：
  - 路径（世界坐标 `Pose2D` 列表）
  - 像素路径
  - 产物目录与运行元数据

依赖与限制：
  - `CoveragePlannerConfig` 需要提供 shelf-aware 相关字段。
  - 当 `artifacts_output_root` 未配置时，回退到仓库路径
    `repo_root/runtime_runs/coverage_planning`，其中 `repo_root` 由
    `parents[4]` 推断，受仓库层级结构约束。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import numpy as np

from ...contracts import CoveragePlannerConfig, CoverageResult, Pose2D
from .planner import plan_coverage_path
from .models import (
  CtgGuidanceConfig,
  IsolatedJumpCleanupConfig,
  LocalDirectionConfig,
  PlannerConfig,
  StrategyConfig,
  TurnConstraintConfig,
)


@dataclass(frozen=True)
class _ShelfAwareInternalDefaults:
  """内部固定默认值容器，不对外暴露为可配置 UI 参数。"""

  semantic_path_enable: bool = True
  semantic_actual_clean_width_m: float = 0.70
  strategy_name: str = "shelf_aware"


_SHELF_AWARE_INTERNAL_DEFAULTS = _ShelfAwareInternalDefaults()


class ShelfAwareCoveragePlanner:
  """shelf-aware 覆盖规划器入口封装。

  职责边界：
  - 负责输入校验、目录规划、配置组装、结果映射。
  - 不直接承载核心搜索/图构建算法，`plan_coverage_path` 承担执行主流程。

  生命周期：
  - 保存一份 `CoveragePlannerConfig` 快照供多次调用复用。
  - 不维护跨 `plan()` 的可变中间状态，适合重复调用但不推荐跨线程共享单实例。
  """

  def __init__(self, config: CoveragePlannerConfig | None = None):
    """初始化 planner 包装器。

    Args:
      config: 覆盖规划运行配置。为空时使用默认模式 `shelf_aware`。

    Side effects:
      将配置保存到 `self.cfg`，成为后续 `plan()` 的默认上下文。
    """
    self.cfg = config or CoveragePlannerConfig(planner_mode="shelf_aware")

  def _default_output_root(self) -> Path:
    """返回 artifacts 根目录。

    Returns:
      Path: 输出根目录。

    Notes:
      优先使用配置覆盖值，保证外部系统可控；未设置时使用仓库内固定回退目录，提升无配置运行可用性。
      回退路径依赖仓库目录层级稳定。
    """
    if self.cfg.artifacts_output_root:
      return Path(self.cfg.artifacts_output_root).expanduser().resolve()

    # 固定回退目录用于缺省场景，避免 output_dir 为空导致运行失败。
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "runtime_runs" / "coverage_planning"

  def _build_run_dir(self) -> Path:
    """按时间戳创建本次运行目录名。

    Returns:
      Path: 本次执行对应的目录路径，计划执行开始时再实际创建。
    """
    run_name = "run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return self._default_output_root() / run_name

  def _build_planner_config(
    self,
    room_map: np.ndarray,
    starting_position: Tuple[int, int],
    local_axis_direction_map: np.ndarray | None = None,
    local_axis_confidence_map: np.ndarray | None = None,
    local_edge_label_map: np.ndarray | None = None,
    local_junction_label_map: np.ndarray | None = None,
    region_mask: np.ndarray | None = None,
    blend_axis_with_local_direction: bool = False,
    ctg_guidance_enable: bool = False,
  ) -> PlannerConfig:
    """将入口参数映射为 planner 运行配置。

    该映射层的目标是保持：
      1) 外部配置与内部默认的分离；
      2) 运行时可选输入（方向/标签图）存在时才注入配置；
      3) 不可配的关键参数使用内部稳定基线，避免线上行为漂移。

    Args:
      room_map: 输入栅格地图，沿用原始像素坐标语义。
      starting_position: 起始像素坐标 `(row, col)`，用于生成 planner 初始化位姿。
      local_axis_direction_map: 局部主轴方向图，可为空。
      local_axis_confidence_map: 主轴方向置信度图，可为空。
      local_edge_label_map: 边缘标签图，可为空。
      local_junction_label_map: 交汇点标签图，可为空。
      region_mask: 区域掩码，可为空。
      blend_axis_with_local_direction: 是否融合外部方向约束与图像梯度方向。
      ctg_guidance_enable: 是否启用 CTG 引导。

    Returns:
      PlannerConfig: 传入 core pipeline 的完整配置对象。
    """
    internal_defaults = _SHELF_AWARE_INTERNAL_DEFAULTS
    # 内部默认值不直接暴露给外部 profile，确保关键行为参数有一致的最小保障边界。
    return PlannerConfig(
      coverage_width_m=float(self.cfg.coverage_width_m),
      robot_width_m=float(self.cfg.robot_width_m),
      start_pixel=(int(round(starting_position[0])), int(round(starting_position[1]))),
      region_polygon=None,
      region_mask=region_mask,
      save_debug_csv=bool(self.cfg.write_artifacts),
      write_artifacts=bool(self.cfg.write_artifacts),
      turn_constraint=TurnConstraintConfig(
        enable_prohibit=bool(self.cfg.turn_constraint_enable),
        prohibit_energy=float(self.cfg.turn_constraint_prohibit_energy),
        near_dist_m=float(self.cfg.turn_constraint_near_dist_m),
        near_max_turn_deg=float(self.cfg.turn_constraint_near_max_turn_deg),
        neighbor_max_turn_deg=float(self.cfg.turn_constraint_neighbor_max_turn_deg),
        fallback_max_turn_deg=float(self.cfg.turn_constraint_fallback_max_turn_deg),
        fallback_relax_dist_m=float(self.cfg.turn_constraint_fallback_relax_dist_m),
      ),
      local_direction=LocalDirectionConfig(
        enable=bool(self.cfg.local_direction_enable),
        energy_weight=float(self.cfg.local_direction_energy_weight),
      ),
      external_axis_direction_map=local_axis_direction_map,
      external_axis_confidence_map=local_axis_confidence_map,
      external_axis_blend_with_image_gradient=bool(blend_axis_with_local_direction),
      external_edge_label_map=local_edge_label_map,
      external_junction_label_map=local_junction_label_map,
      semantic_path_enable=internal_defaults.semantic_path_enable,
      semantic_actual_clean_width_m=internal_defaults.semantic_actual_clean_width_m,
      ctg_guidance=CtgGuidanceConfig(enable=bool(ctg_guidance_enable)),
      node_generation_mode=str(self.cfg.shelf_node_generation_mode),
      repaired_grid_max_offset_factor=float(self.cfg.shelf_repaired_grid_max_offset_factor),
      row_endpoint_alignment_enable=bool(self.cfg.shelf_row_endpoint_alignment_enable),
      node_obstacle_ratio_filter_enable=bool(self.cfg.shelf_node_obstacle_ratio_filter_enable),
      node_obstacle_ratio_threshold=float(self.cfg.shelf_node_obstacle_ratio_threshold),
      isolated_jump_cleanup=IsolatedJumpCleanupConfig(
        enable=bool(self.cfg.isolated_jump_cleanup_enable),
        jump_distance_m=float(self.cfg.isolated_jump_distance_m),
        max_isolated_points=int(self.cfg.isolated_jump_max_points),
        max_isolated_length_m=float(self.cfg.isolated_jump_max_length_m),
        reinsert_max_distance_m=float(self.cfg.isolated_jump_reinsert_max_distance_m),
        reinsert_improvement_ratio=float(self.cfg.isolated_jump_reinsert_improvement_ratio),
      ),
      strategy=StrategyConfig(
        name=internal_defaults.strategy_name,
        fallback_jump_weight=float(self.cfg.fallback_jump_weight),
        local_lateral_weight=float(self.cfg.local_lateral_weight),
        allow_revisit_bridge=bool(self.cfg.allow_revisit_bridge),
        split_jump_dist_factor=float(self.cfg.split_jump_dist_factor),
        history_clearance_weight=float(self.cfg.history_clearance_weight),
      ),
    )

  def _metadata(
    self,
    map_resolution: float,
    map_origin: Tuple[float, float],
  ) -> dict:
    """构建供 core 使用的元信息结构。

    Args:
      map_resolution: 地图分辨率（m / pixel）。
      map_origin: 地图原点 `(x, y)`。

    Returns:
      dict: 包含分辨率、原点与输入来源路径占位的元数据。
    """
    return {
      "resolution": float(map_resolution),
      "origin": [float(map_origin[0]), float(map_origin[1]), 0.0],
      "map_yaml": str(getattr(self.cfg, "map_yaml_path", "")),
      "image_path": "",
    }

  def _to_pose_path(self, world_path: List[dict]) -> List[Pose2D]:
    """将 core 的世界路径字典转换为 `Pose2D` 数据结构。

    以 `Pose2D` 返回是为了与上层运行时模型对齐，避免路径消费方重复做字段解析。

    Args:
      world_path: 由核心规划器返回的 dict 列表，每项包含 `x/y/theta`。

    Returns:
      List[Pose2D]: 标准姿态路径。
    """
    return [
      Pose2D(
        float(item["x"]),
        float(item["y"]),
        float(item["theta"]),
      )
      for item in world_path
    ]

  def _to_path_pixels(
    self,
    world_path: List[dict],
    map_resolution: float,
    map_origin: Tuple[float, float],
    map_height: int,
  ) -> List[Tuple[float, float]]:
    """将世界路径映射到像素坐标系，保持与可视化模块一致。

    Args:
      world_path: 世界坐标路径（dict list），每项包含 `x/y`。
      map_resolution: 地图分辨率。
      map_origin: 地图原点 `(x, y)`。
      map_height: 图像高度（像素），用于 v 轴翻转。

    Returns:
      List[Tuple[float, float]]: 像素路径 `(u, v)`。
    """
    return [
      (
        (float(item["x"]) - float(map_origin[0])) / float(map_resolution),
        float(map_height) - (float(item["y"]) - float(map_origin[1])) / float(map_resolution),
      )
      for item in world_path
    ]

  def plan(
    self,
    room_map: np.ndarray,
    map_resolution: float,
    starting_position: Tuple[int, int],
    map_origin: Tuple[float, float] = (0.0, 0.0),
    local_axis_direction_map: np.ndarray | None = None,
    local_axis_confidence_map: np.ndarray | None = None,
    local_edge_label_map: np.ndarray | None = None,
    local_junction_label_map: np.ndarray | None = None,
    region_mask: np.ndarray | None = None,
    blend_axis_with_local_direction: bool = False,
    ctg_guidance_enable: bool = False,
  ) -> CoverageResult:
    """执行一次 shelf-aware 覆盖规划。

    工作流程：
      1. 输入空图快速失败，避免无效地图进入 pipeline。
      2. 创建独立运行目录，隔离 artifacts。
      3. 组装 planner 配置并调用核心入口。
      4. 将输出转换为世界路径 + 像素路径，返回标准结果对象。

    Args:
      room_map: 输入地图栅格。
      map_resolution: 地图分辨率（m / pixel）。
      starting_position: 起始像素坐标 `(row, col)`。
      map_origin: 地图原点 `(x, y)`。
      local_axis_direction_map: 局部方向图（可选）。
      local_axis_confidence_map: 方向置信度图（可选）。
      local_edge_label_map: 边缘标签图（可选）。
      local_junction_label_map: 交汇标签图（可选）。
      region_mask: 区域掩码（可选）。
      blend_axis_with_local_direction: 是否与图像梯度方向融合方向约束。
      ctg_guidance_enable: 是否开启 CTG guidance。

    Returns:
      CoverageResult: 成功时返回路径；失败时返回失败码与原因。
    """
    if room_map is None or room_map.size == 0:
      # 空图会导致后续 pipeline 无法产生可验证结果；提前返回明确错误码便于上层降级。
      return CoverageResult.failure_result(101, "输入地图为空")

    try:
      # 先为本次执行实例分配独立目录，防止 artifacts 被并发调用覆盖。
      run_dir = self._build_run_dir()
      run_dir.mkdir(parents=True, exist_ok=True)
      planner_cfg = self._build_planner_config(
        room_map,
        starting_position,
        local_axis_direction_map=local_axis_direction_map,
        local_axis_confidence_map=local_axis_confidence_map,
        local_edge_label_map=local_edge_label_map,
        local_junction_label_map=local_junction_label_map,
        region_mask=region_mask,
        blend_axis_with_local_direction=blend_axis_with_local_direction,
        ctg_guidance_enable=ctg_guidance_enable,
      )

      # metadata 统一由入口注入，避免调用方重复构造坐标系字段导致的一致性差异。
      world_path_raw, artifacts = plan_coverage_path(
        room_map=room_map,
        metadata=self._metadata(map_resolution, map_origin),
        output_dir=str(run_dir),
        config=planner_cfg,
      )

      if not world_path_raw:
        # 空路径是核心返回的合法边界，需要显式失败码向上层上报，触发人工或 fallback 流程。
        return CoverageResult.failure_result(
          102,
          "shelfAware 未生成任何路径点",
          artifacts_dir=str(run_dir),
        )

      path = self._to_pose_path(world_path_raw)
      path_pixels = self._to_path_pixels(
        world_path_raw, map_resolution, map_origin, int(room_map.shape[0])
      )

      # 回传 artifacts 的 transform 记录，便于后续复现与脱敏比对。
      return CoverageResult.success_result(
        path,
        path_pixels,
        artifacts_dir=str(getattr(artifacts, "output_dir", run_dir)),
        runtime_metadata={
          "final_path_transform_records": [
            dict(record)
            for record in getattr(artifacts, "final_path_transform_records", [])
          ],
        },
      )
    except Exception as exc:  # pragma: no cover - UI/导出层展示错误信息
      # 任何未捕获异常都汇总为执行失败，保留原始异常文本，避免在上游吞掉关键异常脉络。
      return CoverageResult.failure_result(
        201,
        f"shelfAware 规划失败：{exc}",
      )
