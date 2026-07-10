from __future__ import annotations

from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_summary import (
    CandidateEvaluationRecord,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_decision_debug import (
    candidate_evaluation_record_payload,
)


def test_candidate_evaluation_record_payload_includes_score_components():
    record = CandidateEvaluationRecord.from_energy_result(
        cell_id="candidate",
        move_source="normal_neighbor",
        accepted=True,
        total_energy=4.0,
        score_components={"turn_cost": 3.0, "distance_cost": 1.0},
        score_component_sum_valid=True,
    )

    payload = candidate_evaluation_record_payload(record)

    assert payload["cell_id"] == "candidate"
    assert payload["total_energy"] == 4.0
    assert payload["score_components"] == {
        "distance_cost": 1.0,
        "turn_cost": 3.0,
    }
    assert payload["score_component_sum_valid"] is True
