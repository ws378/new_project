"""遍历 move 的追踪原语。

该模块只负责把遍历步骤编码成稳定 artifact 记录。它不参与候选排序，不改变
路径，也不反向驱动旧 ``Node`` 状态。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .traversal_roles import EDGE_ROLE_START, MOVE_SOURCE_START


def normalize_turn_angle_deg(from_heading_rad: float | None, to_heading_rad: float | None) -> float | None:
  """返回两次航向差的绝对最小转角（度）。

  只依赖角度周期性规约，不引入方向性偏置。
  """
  if from_heading_rad is None or to_heading_rad is None:
    # 任一端朝向未知时不参与 turn 统计，避免脏值被错误写入 trace。
    return None
  delta = (float(to_heading_rad) - float(from_heading_rad) + math.pi) % (2.0 * math.pi) - math.pi
  # 输出绝对值后作为统一代价度量，不再区分左/右转向的符号。
  return abs(math.degrees(delta))


@dataclass(frozen=True)
class TraversalMove:
  """可追溯的遍历动作记录，字段全部可序列化用于 artifact。"""
  move_id: str
  path_index: int
  step_index: int
  move_source: str
  edge_role: str
  from_node_id: str | None
  to_node_id: str
  from_point_rotated_px: tuple[float, float] | None
  to_point_rotated_px: tuple[float, float]
  selected_energy: float
  local_residual_count: int
  revisit_frontier_score: int
  distance_px: float
  heading_rad: float | None
  turn_angle_deg: float | None
  phase_candidate_count: int | None
  phase_energy_evaluated_candidate_count: int | None
  phase_accepted_candidate_count: int | None
  phase_rejected_before_energy_count: int | None
  phase_candidate_rank: int | None

  @classmethod
  def start(cls, *, to_node_id: str, to_point_rotated_px: tuple[float, float]) -> "TraversalMove":
    """生成起始点 move，约束 move_id/序号从 1 开始。"""
    return cls(
      move_id="move_000001",
      path_index=1,
      step_index=0,
      move_source=MOVE_SOURCE_START,
      edge_role=EDGE_ROLE_START,
      from_node_id=None,
      to_node_id=str(to_node_id),
      from_point_rotated_px=None,
      to_point_rotated_px=(float(to_point_rotated_px[0]), float(to_point_rotated_px[1])),
      selected_energy=0.0,
      local_residual_count=0,
      revisit_frontier_score=0,
      distance_px=0.0,
      heading_rad=None,
      turn_angle_deg=None,
      phase_candidate_count=None,
      phase_energy_evaluated_candidate_count=None,
      phase_accepted_candidate_count=None,
      phase_rejected_before_energy_count=None,
      phase_candidate_rank=None,
    )

  @classmethod
  def from_legacy_step(
    cls,
    *,
    path_index: int,
    step_index: int,
    move_source: str,
    edge_role: str,
    from_node_id: str,
    to_node_id: str,
    from_point_rotated_px: tuple[float, float],
    to_point_rotated_px: tuple[float, float],
    selected_energy: float,
    local_residual_count: int,
    revisit_frontier_score: int,
    heading_rad: float,
    previous_heading_rad: float | None,
    phase_candidate_count: int,
    phase_energy_evaluated_candidate_count: int,
    phase_accepted_candidate_count: int,
    phase_rejected_before_energy_count: int,
    phase_candidate_rank: int,
  ) -> "TraversalMove":
    """将 legacy step 结果转为 artifact 记录并统一数值类型。"""
    distance_px = math.hypot(
      float(to_point_rotated_px[0]) - float(from_point_rotated_px[0]),
      float(to_point_rotated_px[1]) - float(from_point_rotated_px[1]),
    )
    # 距离先转为 float，确保后续 artifact 数值类型统一，不受 numpy dtype 影响。
    return cls(
      move_id=f"move_{int(path_index):06d}",
      path_index=int(path_index),
      step_index=int(step_index),
      move_source=str(move_source),
      edge_role=str(edge_role),
      from_node_id=str(from_node_id),
      to_node_id=str(to_node_id),
      from_point_rotated_px=(float(from_point_rotated_px[0]), float(from_point_rotated_px[1])),
      to_point_rotated_px=(float(to_point_rotated_px[0]), float(to_point_rotated_px[1])),
      selected_energy=float(selected_energy),
      local_residual_count=int(local_residual_count),
      revisit_frontier_score=int(revisit_frontier_score),
      distance_px=float(distance_px),
      heading_rad=float(heading_rad),
      turn_angle_deg=normalize_turn_angle_deg(previous_heading_rad, heading_rad),
      phase_candidate_count=int(phase_candidate_count),
      phase_energy_evaluated_candidate_count=int(phase_energy_evaluated_candidate_count),
      phase_accepted_candidate_count=int(phase_accepted_candidate_count),
      phase_rejected_before_energy_count=int(phase_rejected_before_energy_count),
      phase_candidate_rank=int(phase_candidate_rank),
    )

  def to_trace_item(self) -> dict[str, Any]:
    """输出 artifact trace 所需的字典视图，保持数值可 JSON 兼容。"""
    return {
      "move_id": self.move_id,
      "path_index": int(self.path_index),
      "step_index": int(self.step_index),
      "move_source": self.move_source,
      "edge_role": self.edge_role,
      "from_node_id": self.from_node_id,
      "to_node_id": self.to_node_id,
      "from_point_rotated_px": None if self.from_point_rotated_px is None else [
        float(self.from_point_rotated_px[0]),
        float(self.from_point_rotated_px[1]),
      ],
      "to_point_rotated_px": [
        float(self.to_point_rotated_px[0]),
        float(self.to_point_rotated_px[1]),
      ],
      "selected_energy": float(self.selected_energy),
      "local_residual_count": int(self.local_residual_count),
      "revisit_frontier_score": int(self.revisit_frontier_score),
      "distance_px": float(self.distance_px),
      "heading_rad": self.heading_rad,
      "turn_angle_deg": self.turn_angle_deg,
      "phase_candidate_count": self.phase_candidate_count,
      "phase_energy_evaluated_candidate_count": self.phase_energy_evaluated_candidate_count,
      "phase_accepted_candidate_count": self.phase_accepted_candidate_count,
      "phase_rejected_before_energy_count": self.phase_rejected_before_energy_count,
      "phase_candidate_rank": self.phase_candidate_rank,
    }
