"""流水线阶段摘要结构体（结构化阶段可视化与审计产物）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .trace import PipelineStageRecord


@dataclass(frozen=True)
class InputValidationStageSummary:
  """输入校验阶段摘要。
  
  记录可用像素、起点与覆盖宽度等统计，支撑后处理判定。
  """
  free_pixel_count: int
  has_region_mask: bool
  start_pixel: tuple[int, int]
  coverage_width_px: int
  robot_half_width_px: float

  def to_stage_record(self) -> PipelineStageRecord:
    """把输入校验摘要写成统一的阶段追踪记录。"""

    # 输入阶段要把“可用性”与起点约束都落在同一阶段快照中，避免前处理分散记录。
    return PipelineStageRecord(
      stage_name="input_validation",
      summary={
        "free_pixel_count": int(self.free_pixel_count),
        "has_region_mask": bool(self.has_region_mask),
        "start_pixel": [int(self.start_pixel[0]), int(self.start_pixel[1])],
        "coverage_width_px": int(self.coverage_width_px),
        "robot_half_width_px": float(self.robot_half_width_px),
      },
    )


@dataclass(frozen=True)
class RoomRotationStageSummary:
  """房间旋转阶段摘要。
  
  提供旋转参数与结果尺寸，用于重放时快速确认几何一致性。
  """
  rotation_angle_rad: float
  full_bounding_rect: tuple[int, int, int, int]
  crop_rect: tuple[int, int, int, int]
  crop_padding_px: int
  rotated_crop_offset_px: tuple[int, int]
  full_rotated_shape: tuple[int, int]
  rotated_shape: tuple[int, int]

  def to_stage_record(self) -> PipelineStageRecord:
    """把旋转几何基准落地到阶段追踪，避免后续像素坐标反算口径漂移。"""

    # 下游正式消费 cropped rotated frame；full frame 只保留为审计事实，避免双坐标系混用。
    return PipelineStageRecord(
      stage_name="room_rotation",
      summary={
        "rotation_angle_rad": float(self.rotation_angle_rad),
        "full_bounding_rect": [int(value) for value in self.full_bounding_rect],
        "crop_rect": [int(value) for value in self.crop_rect],
        "crop_padding_px": int(self.crop_padding_px),
        "rotated_crop_offset_px": [
          int(self.rotated_crop_offset_px[0]),
          int(self.rotated_crop_offset_px[1]),
        ],
        "full_rotated_shape": [int(self.full_rotated_shape[0]), int(self.full_rotated_shape[1])],
        "rotated_shape": [int(self.rotated_shape[0]), int(self.rotated_shape[1])],
      },
    )


@dataclass(frozen=True)
class LocalDirectionFieldStageSummary:
  """方向场阶段摘要。
  
  记录来源、是否启用与平均置信度，便于方向策略失效时定位。
  """
  source: str
  enabled: bool
  mean_confidence: float
  external_guidance_inputs: dict[str, bool]

  def to_stage_record(self) -> PipelineStageRecord:
    """记录方向场来源与置信度，支持后续方向策略可追溯。"""

    # 方向场由图像与外部输入共同决定，需把来源和置信度一起保留。
    return PipelineStageRecord(
      stage_name="local_direction_field",
      summary={
        "source": str(self.source),
        "enabled": bool(self.enabled),
        "mean_confidence": float(self.mean_confidence),
        "external_guidance_inputs": {
          str(key): bool(value)
          for key, value in sorted(self.external_guidance_inputs.items())
        },
      },
    )


@dataclass(frozen=True)
class CoverageGraphStageSummary:
  """覆盖图构建阶段摘要。
  
  统计图规模、生成模式与边界范围，降低结构变更带来的黑盒感。
  """
  graph_summary: dict[str, int]
  node_generation_mode: str
  node_generation_profile: dict[str, Any]
  coverage_width_px: int
  rotated_min_room_px: tuple[int, int]
  rotated_max_room_px: tuple[int, int]

  def to_stage_record(self) -> PipelineStageRecord:
    """记录覆盖图构建规模与生成参数，便于复现实验。"""

    # 覆盖图阶段记录节点规模与生成配置，直接决定下游遍历空间。
    return PipelineStageRecord(
      stage_name="coverage_graph_build",
      summary={
        **{str(key): int(value) for key, value in self.graph_summary.items()},
        "node_generation_mode": str(self.node_generation_mode),
        "node_generation_profile": dict(self.node_generation_profile),
        "coverage_width_px": int(self.coverage_width_px),
        "rotated_min_room_px": [int(self.rotated_min_room_px[0]), int(self.rotated_min_room_px[1])],
        "rotated_max_room_px": [int(self.rotated_max_room_px[0]), int(self.rotated_max_room_px[1])],
      },
    )


@dataclass(frozen=True)
class StartCellSelectionStageSummary:
  """起点选择阶段摘要。
  
  记录请求起点与落点映射、候选 cell 维度，用于复盘起点偏差。
  """
  requested_start_pixel: tuple[int, int]
  rotated_start_pixel: tuple[int, int]
  selected_cell_id: str
  selected_grid_row: int
  selected_grid_col: int
  selected_planning_point_rotated_px: tuple[int, int]
  distance_to_rotated_start_px: float

  def to_stage_record(self) -> PipelineStageRecord:
    """记录起点选择偏差，用于复核用户输入与实际可达起点的一致性。"""

    # 起点偏移会影响遍历轨迹；这里固定记录请求点、实际选择点和偏差距离。
    return PipelineStageRecord(
      stage_name="start_cell_selection",
      summary={
        "requested_start_pixel": [
          int(self.requested_start_pixel[0]),
          int(self.requested_start_pixel[1]),
        ],
        "rotated_start_pixel": [
          int(self.rotated_start_pixel[0]),
          int(self.rotated_start_pixel[1]),
        ],
        "selected_cell_id": str(self.selected_cell_id),
        "selected_grid_row": int(self.selected_grid_row),
        "selected_grid_col": int(self.selected_grid_col),
        "selected_planning_point_rotated_px": [
          int(self.selected_planning_point_rotated_px[0]),
          int(self.selected_planning_point_rotated_px[1]),
        ],
        "distance_to_rotated_start_px": float(self.distance_to_rotated_start_px),
      },
    )


@dataclass(frozen=True)
class GraphTraversalStageSummary:
  """图遍历阶段摘要。
  
  保留事件数与输出规模，支撑 fallback/decision 流程的离线分析。
  """
  move_trace_count: int
  fallback_event_count: int
  candidate_decision_event_count: int
  traversal_state: dict[str, object]
  output_point_count: int

  def to_stage_record(self) -> PipelineStageRecord:
    """记录遍历阶段事件与关键计数，识别异常回退。"""

    # 遍历阶段统计 move 与 fallback 事件用于检验是否发生异常回退行为。
    return PipelineStageRecord(
      stage_name="graph_traversal",
      mutates_path=True,
      output_point_count=int(self.output_point_count),
      summary={
        "move_trace_count": int(self.move_trace_count),
        "fallback_event_count": int(self.fallback_event_count),
        "candidate_decision_event_count": int(self.candidate_decision_event_count),
        "traversal_state": dict(self.traversal_state),
      },
    )


@dataclass(frozen=True)
class SimplifyRotatedPathStageSummary:
  """路径简化阶段摘要。
  
  记录压缩前后点数量变化，避免几何简化与覆盖完整性指标误读。
  """
  input_point_count: int
  output_point_count: int

  def to_stage_record(self) -> PipelineStageRecord:
    """记录路径简化前后的点数量差异，避免质量指标误读。"""

    # 简化阶段记录移除点数量，防止几何压缩与质量指标混淆。
    return PipelineStageRecord(
      stage_name="simplify_rotated_path",
      mutates_path=True,
      input_point_count=int(self.input_point_count),
      output_point_count=int(self.output_point_count),
      summary={
        "removed_point_count": int(self.input_point_count - self.output_point_count),
      },
    )


@dataclass(frozen=True)
class SemanticGlobalPathStageSummary:
  """语义路径阶段摘要。
  
  说明语义清理是否启用以及输入输出规模差异，辅助版本回归对比。
  """
  enabled: bool
  input_point_count: int
  output_point_count: int
  summary: dict[str, Any]

  def to_stage_record(self) -> PipelineStageRecord:
    """记录语义路径阶段是否启用及输入输出规模。"""

    # 语义阶段有时禁用，状态机通过 status 标识，保留完整分支信息。
    return PipelineStageRecord(
      stage_name="semantic_global_path",
      status="completed" if self.enabled else "skipped",
      mutates_path=True,
      input_point_count=int(self.input_point_count),
      output_point_count=int(self.output_point_count),
      summary=dict(self.summary),
    )


@dataclass(frozen=True)
class IsolatedJumpCleanupStageSummary:
  """孤立跳跃清理阶段摘要。
  
  记录清理前后规模变化，定位过度清理与路径断裂风险。
  """
  input_point_count: int
  output_point_count: int
  summary: dict[str, object]

  def to_stage_record(self) -> PipelineStageRecord:
    """记录长跳清理阶段的规模变化，留痕可复核结构变更。"""

    # 长跳清理可能改变路径长度和可达结构，必须单独打点留痕。
    return PipelineStageRecord(
      stage_name="isolated_jump_cleanup",
      mutates_path=True,
      input_point_count=int(self.input_point_count),
      output_point_count=int(self.output_point_count),
      summary=dict(self.summary),
    )


@dataclass(frozen=True)
class FinalPathGeometryStageSummary:
  """最终几何路径阶段摘要。
  
  关注段数与跳转统计，作为路径拓扑质量的轻量约束。
  """
  input_point_count: int
  output_point_count: int
  segment_count: int
  split_segment_count: int
  jump_segment_count: int

  def to_stage_record(self) -> PipelineStageRecord:
    """记录路径几何分段指标，给后续可视化和分段分析提供边界。"""

    # 路径几何输出阶段关注分段指标，后续分段/跳段可视化以此校验。
    return PipelineStageRecord(
      stage_name="final_path_geometry",
      input_point_count=int(self.input_point_count),
      output_point_count=int(self.output_point_count),
      summary={
        "segment_count": int(self.segment_count),
        "split_segment_count": int(self.split_segment_count),
        "jump_segment_count": int(self.jump_segment_count),
      },
    )


@dataclass(frozen=True)
class OutputAssemblyStageSummary:
  """输出装配阶段摘要。
  
  对齐像素点与世界点规模，作为坐标转换一致性的快速检查。
  """
  input_pose_count: int
  world_path_count: int

  def to_stage_record(self) -> PipelineStageRecord:
    """记录像素路径向世界路径转换前后的点数一致性。"""

    # 世界路径装配是坐标系最终转换点，输入输出点数用于快速一致性检查。
    return PipelineStageRecord(
      stage_name="output_assembly",
      input_point_count=int(self.input_pose_count),
      output_point_count=int(self.world_path_count),
      summary={
        "world_path_count": int(self.world_path_count),
      },
    )


@dataclass(frozen=True)
class ArtifactWriteStageSummary:
  """artifact 写入阶段摘要。
  
  明确是否写盘及目标路径，降低结果不可复查风险。
  """
  enabled: bool
  output_path: str

  def to_stage_record(self) -> PipelineStageRecord:
    """记录 artifact 写入开关与目标路径，用于结果复核与回滚。"""

    # artifact 是否写出决定了后续字段是否可复查，显式带入 stage 状态。
    return PipelineStageRecord(
      stage_name="artifact_write",
      status="completed" if self.enabled else "skipped",
      summary={
        "enabled": bool(self.enabled),
        "output_path": str(self.output_path),
      },
    )
