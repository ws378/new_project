"""覆盖图遍历阶段。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..models import PlannerConfig
from .trace import PipelineStageRecord
from .summaries import GraphTraversalStageSummary
from ..traversal_core.traversal import TraversalResult, run_traversal_loop
from ..traversal_core.traversal_graph_access import TraversalGraphAccess


@dataclass(frozen=True)
class GraphTraversalStageInput:
  """图遍历阶段入参。
  
  统一承载图访问器、起点、覆盖参数与方向场信息；避免阶段内从外部反查。
  """
  graph_access: TraversalGraphAccess
  start_cell_id: str
  coverage_width_px: int
  config: PlannerConfig
  map_resolution: float
  local_direction_map: np.ndarray
  local_direction_confidence: np.ndarray
  rotated_edge_label_map: np.ndarray | None


@dataclass(frozen=True)
class GraphTraversalStageResult:
  """图遍历阶段输出。
  
  返回遍历结果与阶段记录，输入到摘要/装配与 artifact 写入链路。
  """
  traversal_result: TraversalResult
  stage_record: PipelineStageRecord


def run_graph_traversal_stage(stage_input: GraphTraversalStageInput) -> GraphTraversalStageResult:
  """执行遍历主循环并汇总回放关键事件数量，作为后续诊断入口。"""

  # 遍历阶段只负责路径主循环运行，返回的 trace 用于后续 artifact/metadata 分离复用。
  traversal_result = run_traversal_loop(
    graph_access=stage_input.graph_access,
    start_cell_id=stage_input.start_cell_id,
    coverage_width_px=stage_input.coverage_width_px,
    config=stage_input.config,
    map_resolution=stage_input.map_resolution,
    local_direction_map=stage_input.local_direction_map,
    local_direction_confidence=stage_input.local_direction_confidence,
    edge_label_map=stage_input.rotated_edge_label_map,
  )
  stage_record = GraphTraversalStageSummary(
    move_trace_count=len(traversal_result.move_trace),
    fallback_event_count=len(traversal_result.fallback_debug_trace),
    candidate_decision_event_count=len(traversal_result.candidate_decision_debug_trace),
    traversal_state=traversal_result.traversal_state_summary,
    output_point_count=len(traversal_result.fov_coverage_path),
  ).to_stage_record()
  return GraphTraversalStageResult(
    traversal_result=traversal_result,
    stage_record=stage_record,
  )
