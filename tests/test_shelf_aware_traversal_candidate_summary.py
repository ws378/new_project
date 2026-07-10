from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_summary import (
    CandidateEvaluationRecord,
    CandidatePhaseSelection,
    CandidatePhaseSummary,
    PRE_ENERGY_REJECT_REASON_NO_UNVISITED_FRONTIER,
    PRE_ENERGY_REJECT_REASON_VALUES,
    selected_phase_candidate_rank,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_ref import (
    TraversalCandidateRef,
)


def test_selected_phase_candidate_rank_counts_lower_energy_candidates():
    assert selected_phase_candidate_rank([10.0, 3.0, 5.0], 5.0) == 2


def test_candidate_phase_summary_separates_energy_and_pre_energy_rejections():
    summary = CandidatePhaseSummary.from_selected(
        candidate_count=5,
        energy_evaluated_candidate_count=3,
        accepted_energies=[10.0, 4.0],
        selected_energy=10.0,
        rejected_before_energy_count=2,
    )

    assert summary.candidate_count == 5
    assert summary.energy_evaluated_candidate_count == 3
    assert summary.accepted_candidate_count == 2
    assert summary.rejected_before_energy_count == 2
    assert summary.candidate_rank == 2


def test_pre_energy_reject_reason_values_are_stable_and_unique():
    assert PRE_ENERGY_REJECT_REASON_VALUES == (
        PRE_ENERGY_REJECT_REASON_NO_UNVISITED_FRONTIER,
    )
    assert len(set(PRE_ENERGY_REJECT_REASON_VALUES)) == len(PRE_ENERGY_REJECT_REASON_VALUES)


def test_candidate_phase_summary_can_represent_failed_phase_counts():
    summary = CandidatePhaseSummary.from_counts(
        candidate_count=4,
        energy_evaluated_candidate_count=3,
        accepted_candidate_count=0,
        rejected_before_energy_count=1,
    )

    assert summary.candidate_count == 4
    assert summary.energy_evaluated_candidate_count == 3
    assert summary.accepted_candidate_count == 0
    assert summary.rejected_before_energy_count == 1
    assert summary.candidate_rank == 0


def test_empty_candidate_phase_summary_uses_zero_values():
    assert CandidatePhaseSummary.empty() == CandidatePhaseSummary(
        candidate_count=0,
        energy_evaluated_candidate_count=0,
        accepted_candidate_count=0,
        rejected_before_energy_count=0,
        candidate_rank=0,
    )


def test_candidate_evaluation_record_preserves_energy_result_semantics():
    accepted = CandidateEvaluationRecord.from_energy_result(
        cell_id="candidate",
        move_source="normal_neighbor",
        accepted=True,
        total_energy=3.5,
        score_components={"turn_cost": 2.5, "distance_cost": 1.0},
        score_component_sum_valid=True,
    )
    rejected = CandidateEvaluationRecord.from_energy_result(
        cell_id="candidate",
        move_source="normal_neighbor",
        accepted=False,
        total_energy=None,
        rejected_reasons=("shape_constraint",),
    )
    pre_energy = CandidateEvaluationRecord.rejected_before_energy_record(
        cell_id="candidate",
        move_source="revisit_bridge",
        reason=PRE_ENERGY_REJECT_REASON_NO_UNVISITED_FRONTIER,
    )

    assert accepted.cell_id == "candidate"
    assert not hasattr(accepted, "node_id")
    assert accepted.accepted is True
    assert accepted.total_energy == 3.5
    assert accepted.score_components == (("distance_cost", 1.0), ("turn_cost", 2.5))
    assert accepted.score_component_sum_valid is True
    assert accepted.rejected_reasons == ()
    assert accepted.rejected_before_energy is False
    assert rejected.accepted is False
    assert rejected.total_energy is None
    assert rejected.rejected_reasons == ("shape_constraint",)
    assert pre_energy.accepted is False
    assert pre_energy.score_components == ()
    assert pre_energy.score_component_sum_valid is False
    assert pre_energy.rejected_before_energy is True
    assert pre_energy.rejected_reasons == (PRE_ENERGY_REJECT_REASON_NO_UNVISITED_FRONTIER,)


def test_candidate_phase_selection_wraps_selected_cell_id_and_summary():
    summary = CandidatePhaseSummary.from_selected(
        candidate_count=2,
        energy_evaluated_candidate_count=2,
        accepted_energies=[3.0, 1.0],
        selected_energy=1.0,
    )

    selection = CandidatePhaseSelection.selected(
        candidate_ref=TraversalCandidateRef(cell_id="candidate"),
        move_source="revisit_bridge",
        selected_energy=1.0,
        revisit_frontier_score=4,
        phase_summary=summary,
    )

    assert selection.has_selection
    assert selection.selected_cell_id == "candidate"
    assert not hasattr(selection, "node_id")
    assert not hasattr(selection, "legacy_node")
    assert selection.move_source == "revisit_bridge"
    assert selection.selected_energy == 1.0
    assert selection.revisit_frontier_score == 4
    assert selection.phase_summary == summary
    assert selection.candidate_records == ()


def test_empty_candidate_phase_selection_has_no_node():
    record = CandidateEvaluationRecord.rejected_before_energy_record(
        cell_id="candidate",
        move_source="revisit_bridge",
        reason=PRE_ENERGY_REJECT_REASON_NO_UNVISITED_FRONTIER,
    )
    summary = CandidatePhaseSummary.from_counts(
        candidate_count=1,
        energy_evaluated_candidate_count=0,
        accepted_candidate_count=0,
        rejected_before_energy_count=1,
    )
    selection = CandidatePhaseSelection.empty(
        phase_summary=summary,
        candidate_records=(record,),
    )

    assert not selection.has_selection
    assert selection.candidate_ref is None
    assert selection.selected_cell_id is None
    assert selection.selected_energy == float("inf")
    assert selection.phase_summary == summary
    assert selection.candidate_records == (record,)
