"""遍历候选阶段摘要模型。

仅将选中阶段的统计口径结构化，避免计数逻辑散落到多个局部变量；
不负责候选枚举、不负责评分、不负责最终动作决策。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .traversal_candidate_ref import TraversalCandidateRef


PRE_ENERGY_REJECT_REASON_NO_UNVISITED_FRONTIER = "no_unvisited_frontier"
PRE_ENERGY_REJECT_REASON_VALUES = (
  PRE_ENERGY_REJECT_REASON_NO_UNVISITED_FRONTIER,
)


def selected_phase_candidate_rank(accepted_energies: Sequence[float], selected_energy: float) -> int:
  """返回同一阶段内选中候选的名次；能量越低名次越靠前。"""

  # 统计时只比较“已通过能量计算”的候选，保留被预过滤排除者的影响边界。
  return 1 + sum(1 for energy in accepted_energies if float(energy) < float(selected_energy))


@dataclass(frozen=True)
class CandidateEvaluationRecord:
  """一条遍历候选评估记录（只读）。

  用于说明某候选在当前阶段为何被接受/拒绝；该记录不参与状态变更，只服务于可解释追踪。
  """

  cell_id: str
  move_source: str
  accepted: bool
  total_energy: float | None
  score_components: tuple[tuple[str, float], ...]
  score_component_sum_valid: bool
  rejected_reasons: tuple[str, ...]
  rejected_before_energy: bool
  rank_in_phase: int | None

  @classmethod
  def from_energy_result(
    cls,
    *,
    cell_id: str,
    move_source: str,
    accepted: bool,
    total_energy: float | None,
    score_components: Mapping[str, float] | None = None,
    score_component_sum_valid: bool = False,
    rejected_reasons: Sequence[str] = (),
    ) -> "CandidateEvaluationRecord":
    """从评估结果创建只读记录，保留 rejected 信息与得分组件。"""
    # from_* 返回不可变快照，便于跨阶段复用且不会被选择逻辑副作用修改。
    return cls(
      cell_id=str(cell_id),
      move_source=str(move_source),
      accepted=bool(accepted),
      total_energy=None if total_energy is None else float(total_energy),
      score_components=tuple(
        sorted((str(key), float(value)) for key, value in (score_components or {}).items())
      ),
      score_component_sum_valid=bool(score_component_sum_valid),
      rejected_reasons=tuple(str(reason) for reason in rejected_reasons),
      rejected_before_energy=False,
      rank_in_phase=None,
    )

  @classmethod
  def rejected_before_energy_record(
    cls,
    *,
    cell_id: str,
    move_source: str,
    reason: str,
    ) -> "CandidateEvaluationRecord":
    """创建“预筛阶段拒绝”的记录，total_energy 置空避免污染排序。"""
    # 预筛阶段拒绝者不携带能量，避免把结构性拒绝误当作数值比较结果。
    return cls(
      cell_id=str(cell_id),
      move_source=str(move_source),
      accepted=False,
      total_energy=None,
      score_components=(),
      score_component_sum_valid=False,
      rejected_reasons=(str(reason),),
      rejected_before_energy=True,
      rank_in_phase=None,
    )


@dataclass(frozen=True)
class CandidatePhaseSummary:
  """单一 move source 阶段的评估结果摘要（只读）。"""

  candidate_count: int
  energy_evaluated_candidate_count: int
  accepted_candidate_count: int
  rejected_before_energy_count: int
  candidate_rank: int

  @classmethod
  def empty(cls) -> "CandidatePhaseSummary":
    """返回全零统计，作为“无候选/无接受”场景的统一默认值。"""
    return cls(
      candidate_count=0,
      energy_evaluated_candidate_count=0,
      accepted_candidate_count=0,
      rejected_before_energy_count=0,
      candidate_rank=0,
    )

  @classmethod
  def from_counts(
    cls,
    *,
    candidate_count: int,
    energy_evaluated_candidate_count: int,
    accepted_candidate_count: int,
    rejected_before_energy_count: int = 0,
    candidate_rank: int = 0,
    ) -> "CandidatePhaseSummary":
    """从已统计计数构建摘要，用于未进入 accept 分支的阶段。"""
    return cls(
      candidate_count=int(candidate_count),
      energy_evaluated_candidate_count=int(energy_evaluated_candidate_count),
      accepted_candidate_count=int(accepted_candidate_count),
      rejected_before_energy_count=int(rejected_before_energy_count),
      candidate_rank=int(candidate_rank),
    )

  @classmethod
  def from_selected(
    cls,
    *,
    candidate_count: int,
    energy_evaluated_candidate_count: int,
    accepted_energies: Sequence[float],
    selected_energy: float,
    rejected_before_energy_count: int = 0,
    ) -> "CandidatePhaseSummary":
    """基于已选能量与排序序列构建摘要，补齐本阶段的名次口径。"""
    # 选中名次基于同阶段能量序列，可直接复用 accepted_energies，避免二次排序带来排序稳定性差异。
    return cls(
      candidate_count=int(candidate_count),
      energy_evaluated_candidate_count=int(energy_evaluated_candidate_count),
      accepted_candidate_count=len(accepted_energies),
      rejected_before_energy_count=int(rejected_before_energy_count),
      candidate_rank=selected_phase_candidate_rank(accepted_energies, selected_energy),
    )


@dataclass(frozen=True)
class CandidatePhaseSelection:
  """记录单次阶段的最终选型结果，附带阶段统计与候选审计快照。"""

  candidate_ref: TraversalCandidateRef | None
  move_source: str | None
  selected_energy: float
  revisit_frontier_score: int
  phase_summary: CandidatePhaseSummary
  candidate_records: tuple[CandidateEvaluationRecord, ...]

  @classmethod
  def empty(
    cls,
    *,
    phase_summary: CandidatePhaseSummary | None = None,
    candidate_records: Sequence[CandidateEvaluationRecord] = (),
  ) -> "CandidatePhaseSelection":
    """返回未选中的阶段结果，保留空 selection 与空位置信息。"""
    return cls(
      candidate_ref=None,
      move_source=None,
      selected_energy=float("inf"),
      revisit_frontier_score=0,
      phase_summary=CandidatePhaseSummary.empty() if phase_summary is None else phase_summary,
      candidate_records=tuple(candidate_records),
    )

  @classmethod
  def selected(
    cls,
    *,
    candidate_ref: TraversalCandidateRef,
    move_source: str,
    selected_energy: float,
    phase_summary: CandidatePhaseSummary,
    revisit_frontier_score: int = 0,
    candidate_records: Sequence[CandidateEvaluationRecord] = (),
  ) -> "CandidatePhaseSelection":
    """构造已命中候选的阶段结果，要求 caller 已确认 candidate_ref 非空。"""
    return cls(
      candidate_ref=candidate_ref,
      move_source=str(move_source),
      selected_energy=float(selected_energy),
      revisit_frontier_score=int(revisit_frontier_score),
      phase_summary=phase_summary,
      candidate_records=tuple(candidate_records),
    )

  @property
  def has_selection(self) -> bool:
    """是否命中了可执行候选。

    Returns:
        bool: 当 `candidate_ref` 不为空，表示本阶段完成了可落地选型。
    """
    return self.candidate_ref is not None

  @property
  def selected_cell_id(self) -> str | None:
    """命中候选时返回 cell id，否则返回 None。"""
    return None if self.candidate_ref is None else self.candidate_ref.cell_id
