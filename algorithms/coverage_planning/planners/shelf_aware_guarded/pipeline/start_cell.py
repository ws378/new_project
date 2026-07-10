"""起点 coverage cell 选择阶段。"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .trace import PipelineStageRecord
from ..geometry.room_rotation import transform_points
from .summaries import StartCellSelectionStageSummary
from ..traversal_core.traversal import choose_start_cell_id
from ..traversal_core.traversal_graph_access import TraversalGraphAccess


@dataclass(frozen=True)
class StartCellSelectionResult:
  """起点选择阶段结果。
  
  统一记录原始起点、旋转后坐标与实际起始 cell id，避免下游坐标系统混用。
  """
  chosen_start_pixel: tuple[int, int]
  rotated_start_pixel: tuple[int, int]
  start_cell_id: str
  stage_record: PipelineStageRecord


def select_start_cell_stage(
  *,
  graph_access: TraversalGraphAccess,
  chosen_start_pixel: tuple[int, int],
  rotation_matrix: np.ndarray,
) -> StartCellSelectionResult:
  """把用户起点映射到旋转坐标系并选择实际覆盖起始单元。"""

  # 用户输入起点先转到旋转坐标系，再按最近访问候选选取，保持旋转前后一致。
  rotated_start = transform_points([chosen_start_pixel], rotation_matrix)[0]
  rotated_start_int = (int(round(rotated_start[0])), int(round(rotated_start[1])))
  start_cell_id = choose_start_cell_id(graph_access=graph_access, rotated_start=rotated_start_int)
  start_cell = graph_access.cell(start_cell_id)
  start_point = graph_access.planning_point_px_for_cell(start_cell_id)
  stage_record = StartCellSelectionStageSummary(
    requested_start_pixel=(int(chosen_start_pixel[0]), int(chosen_start_pixel[1])),
    rotated_start_pixel=rotated_start_int,
    selected_cell_id=str(start_cell.cell_id),
    selected_grid_row=int(start_cell.grid_row),
    selected_grid_col=int(start_cell.grid_col),
    selected_planning_point_rotated_px=(
      int(start_point[0]),
      int(start_point[1]),
    ),
    distance_to_rotated_start_px=math.hypot(
      float(start_point[0]) - float(rotated_start_int[0]),
      float(start_point[1]) - float(rotated_start_int[1]),
    ),
  ).to_stage_record()
  return StartCellSelectionResult(
    chosen_start_pixel=(int(chosen_start_pixel[0]), int(chosen_start_pixel[1])),
    rotated_start_pixel=rotated_start_int,
    start_cell_id=str(start_cell_id),
    stage_record=stage_record,
  )
