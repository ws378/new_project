"""覆盖图构建阶段。

本模块收束旋转地图上的 coverage cell 生成、静态 graph view 生成和 trace 摘要。
过渡期只在阶段内部生成旧 ``Node`` mirror 并绑定到 ``TraversalGraphAccess``，
不能公开返回旧矩阵，也不能在本阶段写 traversal 状态。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..graph_build.coverage_graph import CoverageGraphView
from ..graph_build.grid_builder import (
  CoverageCellGrid,
  build_cell_candidates,
  build_coverage_graph,
  build_legacy_node_matrix,
)
from ..models import PlannerConfig
from algorithms.coverage_planning.node_generation_profiles import NodeGenerationSettings
from ..geometry.room_rotation import get_min_max_coordinates
from .trace import PipelineStageRecord
from .summaries import CoverageGraphStageSummary
from ..traversal_core.traversal_graph_access import TraversalGraphAccess


@dataclass(frozen=True)
class CoverageGraphBuildResult:
  """覆盖图构建阶段的产物。
  
  包含静态网格、可达图与阶段记录，作为遍历阶段的事实源输入。
  """
  static_cell_grid: CoverageCellGrid
  coverage_graph: CoverageGraphView
  graph_access: TraversalGraphAccess
  min_room: tuple[int, int]
  max_room: tuple[int, int]
  stage_record: PipelineStageRecord


def build_coverage_graph_stage(
  *,
  rotated_room_map: np.ndarray,
  coverage_width_px: int,
  robot_half_width_px: float,
  config: PlannerConfig,
) -> CoverageGraphBuildResult:
  """生成覆盖图阶段的静态拓扑及访问器，作为后续遍历的唯一事实源。"""

  # 统一在本阶段完成边界、网格和 graph 三步，输出固定可回放的静态拓扑视图。
  min_room, max_room = get_min_max_coordinates(rotated_room_map)
  node_generation_settings = NodeGenerationSettings.from_public_values(
    node_generation_mode=str(config.node_generation_mode),
    repaired_grid_max_offset_factor=float(config.repaired_grid_max_offset_factor),
    row_endpoint_alignment_enable=bool(config.row_endpoint_alignment_enable),
    node_obstacle_ratio_filter_enable=bool(config.node_obstacle_ratio_filter_enable),
    node_obstacle_ratio_threshold=float(config.node_obstacle_ratio_threshold),
  )
  
  # 按节点生成模式批量构建覆盖候选网格并冻结为不可变结构
  static_cell_grid = build_cell_candidates(
    rotated_room_map,
    min_room,
    max_room,
    coverage_width_px,
    robot_half_width_px=robot_half_width_px,
    node_generation_mode=node_generation_settings.mode,
    repaired_grid_max_offset_factor=node_generation_settings.repaired_grid_max_offset_factor,
    row_endpoint_alignment_enable=node_generation_settings.row_endpoint_alignment_enable,
    node_obstacle_ratio_filter_enable=node_generation_settings.node_obstacle_ratio_filter_enable,
    node_obstacle_ratio_threshold=node_generation_settings.node_obstacle_ratio_threshold,
  )
  
  coverage_graph = build_coverage_graph(static_cell_grid)
  if config.write_artifacts:
    # legacy 镜像只在 artifact/debug 场景绑定，防止旧入口继续成为在线运行事实源。
    legacy_mirror_matrix = build_legacy_node_matrix(static_cell_grid)
    graph_access = TraversalGraphAccess.bind_legacy_mirror(
      legacy_mirror_matrix=legacy_mirror_matrix,
      coverage_graph=coverage_graph,
    )
  else:
    # 在线规划直接使用正式 coverage graph，避免为不可见的旧镜像对象支付构造成本。
    graph_access = TraversalGraphAccess.from_coverage_graph(coverage_graph)
  stage_record = CoverageGraphStageSummary(
    graph_summary=coverage_graph.summary(),
    node_generation_mode=node_generation_settings.mode,
    node_generation_profile=node_generation_settings.profile_metadata(),
    coverage_width_px=int(coverage_width_px),
    rotated_min_room_px=(int(min_room[0]), int(min_room[1])),
    rotated_max_room_px=(int(max_room[0]), int(max_room[1])),
  ).to_stage_record()
  
  return CoverageGraphBuildResult(
    static_cell_grid=static_cell_grid,
    coverage_graph=coverage_graph,
    graph_access=graph_access,
    min_room=(int(min_room[0]), int(min_room[1])),
    max_room=(int(max_room[0]), int(max_room[1])),
    stage_record=stage_record,
  )
