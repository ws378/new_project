"""遍历循环的阶段选择器。

该模块保留原 ``traversal.py`` 的阶段行为：按既定顺序枚举候选，调用同一套 energy，
只返回命中的阶段与可选的 fallback 调试载荷。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Sequence

from .traversal_candidate_evaluation import (
  evaluate_candidate_for_selection,
  score_candidate_for_selection,
)
from .traversal_candidate_summary import (
  CandidateEvaluationRecord,
  CandidatePhaseSelection,
  CandidatePhaseSummary,
  PRE_ENERGY_REJECT_REASON_NO_UNVISITED_FRONTIER,
)
from .traversal_candidate_ref import TraversalCandidateRef
from .traversal_phase_query import TraversalPhaseQueryContext
from .traversal_roles import (
  MOVE_SOURCE_GLOBAL_FALLBACK,
  MOVE_SOURCE_NORMAL_NEIGHBOR,
  MOVE_SOURCE_REVISIT_BRIDGE,
)
from .traversal_scoring_context import TraversalScoringContext
from .traversal_debug_payloads import candidate_debug_payload, node_debug_payload


@dataclass(frozen=True)
class FallbackPhaseResult:
  """fallback 阶段返回结构：阶段选型 + 可选 debug 载荷。"""
  selection: CandidatePhaseSelection
  debug_event: dict[str, Any] | None


def _with_candidate_ranks(
  records: Sequence[CandidateEvaluationRecord],
) -> tuple[CandidateEvaluationRecord, ...]:
  """给已评估候选注入 rank_in_phase 字段，保持原始记录不可变。

  Args:
      records: 已完成评分的候选记录。

  Returns:
      tuple[CandidateEvaluationRecord, ...]: 保持 `rank_in_phase` 已补齐的候选序列。
  """
  # 在保留原始候选记录的同时补齐秩序信息，利于复盘而不改 selection 判定。
  accepted_energies = [
    float(record.total_energy)
    for record in records
    if record.accepted and record.total_energy is not None
  ]
  ranked_records: list[CandidateEvaluationRecord] = []
  # 按评分结果顺序回填 rank，便于后续将“拒绝原因”与“可比较候选”混合展示。
  for record in records:
    if not record.accepted or record.total_energy is None:
      # 被能量评估过滤或结果缺失的记录不参与排序，仅保留原始拒绝痕迹。
      ranked_records.append(record)
      continue
    # 仅对可比较候选重算名次，保持拒绝记录不受排序公式影响。
    rank = 1 + sum(1 for energy in accepted_energies if energy < float(record.total_energy))
    ranked_records.append(replace(record, rank_in_phase=rank))
  return tuple(ranked_records)


def _selected_summary(
  *,
  candidate_count: int,
  energy_evaluated_candidate_count: int,
  accepted_candidate_count: int,
  selected_energy: float,
  accepted_energies: Sequence[float],
  rejected_before_energy_count: int = 0,
  include_rank: bool,
) -> CandidatePhaseSummary:
  """按诊断开关构建阶段摘要。

  `candidate_rank` 只服务于候选审计与 move trace 复盘；线上关闭 artifact 时不再
  为排名维护完整能量序列，减少全局 fallback 大候选池的二次扫描成本。
  """
  if include_rank:
    return CandidatePhaseSummary.from_selected(
      candidate_count=candidate_count,
      energy_evaluated_candidate_count=energy_evaluated_candidate_count,
      accepted_energies=accepted_energies,
      selected_energy=selected_energy,
      rejected_before_energy_count=rejected_before_energy_count,
    )
  return CandidatePhaseSummary.from_counts(
    candidate_count=candidate_count,
    energy_evaluated_candidate_count=energy_evaluated_candidate_count,
    accepted_candidate_count=accepted_candidate_count,
    rejected_before_energy_count=rejected_before_energy_count,
  )


def _global_fallback_lower_bound_energy(
  *,
  last_point_px: tuple[int, int],
  candidate_point_px: tuple[int, int],
  coverage_width_px: int,
  fallback_jump_weight: float,
) -> float:
  """计算 global fallback 候选的非负能量下界。

  下界只包含距离项和长跳惩罚，两者在正式评分中一定存在且非负；当配置存在 CTG
  同边奖励或局部残量奖励时不使用该剪枝，避免负奖励使下界失效。
  """
  diff_x = float(candidate_point_px[0] - last_point_px[0])
  diff_y = float(candidate_point_px[1] - last_point_px[1])
  translational = math.hypot(diff_x, diff_y) / max(1, int(coverage_width_px))
  dist_ratio = max(0.0, translational - 1.0)
  return float(translational + max(0.0, float(fallback_jump_weight)) * dist_ratio * dist_ratio)


def select_normal_neighbor_phase(
  *,
  last_cell_id: str,
  not_visited_neighbors: Sequence[TraversalCandidateRef],
  query_context: TraversalPhaseQueryContext,
  context: TraversalScoringContext,
) -> CandidatePhaseSelection:
  """枚举 normal 邻居候选并返回本阶段最佳结果。

  该阶段优先统计尝试规模与拒绝原因，便于与后续阶段行为一致比对。

  Args:
      last_cell_id: 当前遍历节点 id。
      not_visited_neighbors: 可尝试的 normal 邻居候选。
      query_context: 封装当前访问状态与图访问接口。
      context: 当前遍历评分上下文。

  Returns:
      CandidatePhaseSelection: 当前阶段选中的候选与候选摘要。
  """
  # normal 阶段不提前剪枝，先把所有候选都评分一次，避免候选顺序影响拒绝统计与可复盘结果。
  graph_access = query_context.graph_access
  collect_records = bool(context.config.write_artifacts)
  min_energy = float("inf")
  selected_ref: TraversalCandidateRef | None = None
  energy_evaluated_count = 0
  accepted_count = 0
  accepted_energies: list[float] = []
  candidate_records: list[CandidateEvaluationRecord] = []
  # 遍历所有未访问邻居并统一打分，避免因提前跳过导致复盘口径缺失。
  for candidate_ref in not_visited_neighbors:
    energy_evaluated_count += 1
    # 每个 normal 候选都必须先过能量评估，后续才可比较和排序。
    if collect_records:
      record = evaluate_candidate_for_selection(
        last_cell_id=last_cell_id,
        candidate_ref=candidate_ref,
        graph_access=graph_access,
        context=context,
        move_source=MOVE_SOURCE_NORMAL_NEIGHBOR,
        is_global_fallback=False,
        candidate_visit_count=0,
        candidate_local_residual_count=query_context.candidate_local_residual_count(candidate_ref.cell_id),
      )
      candidate_records.append(record)
      accepted = bool(record.accepted)
      total_energy = record.total_energy
    else:
      score = score_candidate_for_selection(
        last_cell_id=last_cell_id,
        candidate_ref=candidate_ref,
        graph_access=graph_access,
        context=context,
        is_global_fallback=False,
        candidate_visit_count=0,
        candidate_local_residual_count=query_context.candidate_local_residual_count(candidate_ref.cell_id),
      )
      accepted = bool(score.accepted)
      total_energy = score.total_energy
    if not accepted or total_energy is None:
      # 不可行候选不参与 min 比较，但仍需保留记录用于复盘。
      continue
    energy = float(total_energy)
    accepted_count += 1
    if collect_records:
      accepted_energies.append(float(energy))
    # 总是保留最小能量候选，避免相同候选顺序下不同 run 的落点漂移。
    if energy < min_energy:
      min_energy = energy
      selected_ref = candidate_ref
  if selected_ref is None:
    # normal 阶段失败时返回 empty，保留 count 口径供上游统计。
    return CandidatePhaseSelection.empty(
      phase_summary=CandidatePhaseSummary.from_counts(
        candidate_count=len(not_visited_neighbors),
        energy_evaluated_candidate_count=energy_evaluated_count,
        accepted_candidate_count=accepted_count,
      ),
      candidate_records=_with_candidate_ranks(candidate_records) if collect_records else (),
    )
  return CandidatePhaseSelection.selected(
    candidate_ref=selected_ref,
    move_source=MOVE_SOURCE_NORMAL_NEIGHBOR,
    selected_energy=min_energy,
    phase_summary=_selected_summary(
      candidate_count=len(not_visited_neighbors),
      energy_evaluated_candidate_count=energy_evaluated_count,
      accepted_candidate_count=accepted_count,
      accepted_energies=accepted_energies,
      selected_energy=min_energy,
      include_rank=collect_records,
    ),
    candidate_records=_with_candidate_ranks(candidate_records) if collect_records else (),
  )


def select_revisit_bridge_phase(
  *,
  last_cell_id: str,
  query_context: TraversalPhaseQueryContext,
  context: TraversalScoringContext,
) -> CandidatePhaseSelection:
  """先做 frontier 预筛，再在可达候选中挑选 revisit 桥接候选。

  Args:
      last_cell_id: 当前遍历节点 id。
      query_context: 提供 revisit 候选与历史约束查询。
      context: 当前遍历评分上下文。

  Returns:
      CandidatePhaseSelection: 本阶段选型结果，失败时为 empty。
  """
  # revisit 阶段先做 frontier 过滤再计入候选，避免把无效重复访问推成退化策略。
  graph_access = query_context.graph_access
  collect_records = bool(context.config.write_artifacts)
  revisit_candidates = query_context.revisit_bridge_candidates(last_cell_id)
  min_energy = float("inf")
  selected_ref: TraversalCandidateRef | None = None
  energy_evaluated_count = 0
  rejected_before_energy_count = 0
  accepted_count = 0
  accepted_energies: list[float] = []
  candidate_records: list[CandidateEvaluationRecord] = []
  selected_revisit_frontier_score = 0
  # 仅当 frontier 有剩余边界值时参与评分，否则直接标记为预筛拒绝。
  for candidate_ref in revisit_candidates:
    frontier_score = query_context.revisit_frontier_score(candidate_ref.cell_id)
    if frontier_score <= 0:
      # frontier 打分为 0 表示暂时无法接回未覆盖边界，优先记录为预筛拒绝。
      rejected_before_energy_count += 1
      if collect_records:
        candidate_records.append(
          CandidateEvaluationRecord.rejected_before_energy_record(
            cell_id=candidate_ref.cell_id,
            move_source=MOVE_SOURCE_REVISIT_BRIDGE,
            reason=PRE_ENERGY_REJECT_REASON_NO_UNVISITED_FRONTIER,
          )
        )
      continue
    energy_evaluated_count += 1
    if collect_records:
      record = evaluate_candidate_for_selection(
        last_cell_id=last_cell_id,
        candidate_ref=candidate_ref,
        graph_access=graph_access,
        context=context,
        move_source=MOVE_SOURCE_REVISIT_BRIDGE,
        is_global_fallback=False,
        candidate_visit_count=query_context.visit_count_for_cell(candidate_ref.cell_id),
        candidate_local_residual_count=query_context.candidate_local_residual_count(candidate_ref.cell_id),
        revisit_frontier_score=frontier_score,
      )
      candidate_records.append(record)
      accepted = bool(record.accepted)
      total_energy = record.total_energy
    else:
      score = score_candidate_for_selection(
        last_cell_id=last_cell_id,
        candidate_ref=candidate_ref,
        graph_access=graph_access,
        context=context,
        is_global_fallback=False,
        candidate_visit_count=query_context.visit_count_for_cell(candidate_ref.cell_id),
        candidate_local_residual_count=query_context.candidate_local_residual_count(candidate_ref.cell_id),
        revisit_frontier_score=frontier_score,
      )
      accepted = bool(score.accepted)
      total_energy = score.total_energy
    if not accepted or total_energy is None:
      # 已经过 frontier 的候选仍可能因硬约束被拒绝，保留用于完整审计。
      continue
    energy = float(total_energy)
    accepted_count += 1
    if collect_records:
      accepted_energies.append(float(energy))
    if energy < min_energy:
      min_energy = energy
      selected_ref = candidate_ref
      selected_revisit_frontier_score = int(frontier_score)
  if selected_ref is None:
    # 全部 revisit 候选不可用则返回 empty，由全局 fallback 接管。
    return CandidatePhaseSelection.empty(
      phase_summary=CandidatePhaseSummary.from_counts(
        candidate_count=len(revisit_candidates),
        energy_evaluated_candidate_count=energy_evaluated_count,
        accepted_candidate_count=accepted_count,
        rejected_before_energy_count=rejected_before_energy_count,
      ),
      candidate_records=_with_candidate_ranks(candidate_records) if collect_records else (),
    )
  return CandidatePhaseSelection.selected(
    candidate_ref=selected_ref,
    move_source=MOVE_SOURCE_REVISIT_BRIDGE,
    selected_energy=min_energy,
    revisit_frontier_score=selected_revisit_frontier_score,
    phase_summary=_selected_summary(
      candidate_count=len(revisit_candidates),
      energy_evaluated_candidate_count=energy_evaluated_count,
      accepted_candidate_count=accepted_count,
      accepted_energies=accepted_energies,
      selected_energy=min_energy,
      rejected_before_energy_count=rejected_before_energy_count,
      include_rank=collect_records,
    ),
    candidate_records=_with_candidate_ranks(candidate_records) if collect_records else (),
  )


def select_global_fallback_phase(
  *,
  last_cell_id: str,
  query_context: TraversalPhaseQueryContext,
  context: TraversalScoringContext,
  step_counter: int,
  write_artifacts: bool,
) -> FallbackPhaseResult:
  """在正常阶段无解时执行全局回退，返回可复用的选型结果与可选调试载荷。

  Args:
      last_cell_id: 当前遍历节点 id。
      query_context: 提供全局候选与历史状态查询。
      context: 当前遍历评分上下文。
      step_counter: 当前 step 编号，用于 debug 事件对齐。
      write_artifacts: 是否收集并返回 fallback 候选调试载荷。

  Returns:
      FallbackPhaseResult: 选型结果与可选的调试事件。
  """
  # 全局回退仅在 normal/revisit 都无可行候选时触发，目标是找回拓扑可达性。
  graph_access = query_context.graph_access
  min_energy = float("inf")
  selected_ref: TraversalCandidateRef | None = None
  fallback_candidates_debug: list[dict[str, Any]] = []
  # 统计既反映“候选池规模”，也区分“真正评估了能量”的候选数量，避免两者口径混淆。
  candidate_count = 0
  energy_evaluated_count = 0
  accepted_count = 0
  accepted_energies: list[float] = []
  candidate_records: list[CandidateEvaluationRecord] = []
  # 未写 artifact 时不保存未访问节点清单，减少每步 fallback 的额外内存开销。
  unvisited_before_fallback = (
    query_context.unvisited_accessible_cell_ids()
    if write_artifacts
    else []
  )
  # 全局候选来自全图可达集合；评估阶段只关注能量可比性，不做额外局部偏序。
  fallback_candidates = query_context.global_fallback_candidates()
  enable_lower_bound_pruning = (
    not write_artifacts
    and not bool(context.config.ctg_guidance.enable)
    and float(context.config.strategy.local_residual_continue_weight) <= 0.0
  )
  last_point_px = graph_access.planning_point_px_for_cell(last_cell_id)
  # 全量兜底时不做额外过滤，先统一评分再用最小能量决定回退落点。
  # 只允许通过评估链路决策，避免回退阶段引入额外规则导致可复现性下降。
  for candidate_ref in fallback_candidates:
    # 计数先行，确保 count 口径覆盖“未提前过滤”的候选池规模。
    candidate_count += 1
    # 对每个候选都执行能量估计，保持回退选择可对比、可归并。
    energy_evaluated_count += 1
    if enable_lower_bound_pruning and min_energy < float("inf"):
      candidate_point_px = graph_access.planning_point_px_for_cell(candidate_ref.cell_id)
      lower_bound_energy = _global_fallback_lower_bound_energy(
        last_point_px=last_point_px,
        candidate_point_px=candidate_point_px,
        coverage_width_px=context.coverage_width_px,
        fallback_jump_weight=context.config.strategy.fallback_jump_weight,
      )
      if lower_bound_energy >= min_energy:
        # 下界已不可能优于当前最优，跳过完整评分；该分支只在线上无 artifact 时启用。
        continue
    # global fallback 遍历全局可达，逐一评分后比较全局最小能量。
    if write_artifacts:
      record = evaluate_candidate_for_selection(
        last_cell_id=last_cell_id,
        candidate_ref=candidate_ref,
        graph_access=graph_access,
        context=context,
        move_source=MOVE_SOURCE_GLOBAL_FALLBACK,
        is_global_fallback=True,
        candidate_visit_count=0,
        candidate_local_residual_count=query_context.candidate_local_residual_count(candidate_ref.cell_id),
      )
      candidate_records.append(record)
      accepted = bool(record.accepted)
      total_energy = record.total_energy
    else:
      score = score_candidate_for_selection(
        last_cell_id=last_cell_id,
        candidate_ref=candidate_ref,
        graph_access=graph_access,
        context=context,
        is_global_fallback=True,
        candidate_visit_count=0,
        candidate_local_residual_count=query_context.candidate_local_residual_count(candidate_ref.cell_id),
      )
      accepted = bool(score.accepted)
      total_energy = score.total_energy
    if not accepted or total_energy is None:
      # rejected_before_energy 不入 accepted_energies，保持可比较集合纯净且不把拒绝样本带入 min 比较。
      continue
    energy = float(total_energy)
    accepted_count += 1
    if write_artifacts:
      accepted_energies.append(float(energy))
    if write_artifacts:
      # 只归档通过 energy 评估的候选，未接受候选不适合用于“最小能量前 K 名”对齐。
      fallback_candidates_debug.append(
        candidate_debug_payload(
          candidate_ref.cell_id,
          energy,
          traversal_state=query_context.traversal_state,
          graph_access=graph_access,
        )
      )
    # 最小值选择作为回退落点，优先复现同一状态下的稳定决策。
    # 能量是当前策略下的统一代价口径，取局部最小确保回退决策可复现且稳定。
    if energy < min_energy:
      min_energy = energy
      selected_ref = candidate_ref

  selection = CandidatePhaseSelection.empty(
    phase_summary=CandidatePhaseSummary.from_counts(
      candidate_count=candidate_count,
      energy_evaluated_candidate_count=energy_evaluated_count,
      accepted_candidate_count=accepted_count,
    ),
    candidate_records=_with_candidate_ranks(candidate_records) if write_artifacts else (),
  )
  if selected_ref is not None:
    # selected_ref 非空时保留 from_counts 的审计信息并补充 selected 路径，满足统计口径一致。
    selection = CandidatePhaseSelection.selected(
      candidate_ref=selected_ref,
      move_source=MOVE_SOURCE_GLOBAL_FALLBACK,
      selected_energy=min_energy,
      phase_summary=_selected_summary(
        candidate_count=candidate_count,
        energy_evaluated_candidate_count=energy_evaluated_count,
        accepted_candidate_count=accepted_count,
        accepted_energies=accepted_energies,
        selected_energy=min_energy,
        include_rank=write_artifacts,
      ),
      candidate_records=_with_candidate_ranks(candidate_records) if write_artifacts else (),
    )

  debug_event = None
  if write_artifacts:
    # write_artifacts=False 时保持调试对象为空，减少主循环日志大小；开启时构建完整复盘快照。
    # debug 列表按 energy 升序输出，方便复盘时快速对齐 selected 与相邻候选分布。
    # 同步保持 candidates 与 unvisited 列表，避免在诊断中出现“展示项”与“状态快照”口径断层。
    fallback_candidates_debug.sort(key=lambda item: float(item["energy"]))
    # candidate_count 使用归档列表长度，保持与 candidates 展示口径一致；selected 可为 None 时仍需输出。
    debug_event = {
      "step": int(step_counter),
      "path_index_before_selection": int(len(context.point_path)),
      "current_node": node_debug_payload(
        last_cell_id,
        traversal_state=query_context.traversal_state,
        graph_access=graph_access,
      ),
      "local_residual_count": int(context.local_residual_count),
      "unvisited_node_count_before_selection": int(len(unvisited_before_fallback)),
      "unvisited_node_ids_before_selection": unvisited_before_fallback,
      "candidate_count": int(len(fallback_candidates_debug)),
      "candidates": fallback_candidates_debug,
      "selected_node_id": (
        selected_ref.cell_id
        if selected_ref is not None
        else None
      ),
      # selected_energy 与 selected_node_id 同步存在性：都可用于复盘 selected_ref 的缺失场景。
      "selected_energy": float(min_energy) if selected_ref is not None else None,
    }
  return FallbackPhaseResult(selection=selection, debug_event=debug_event)
