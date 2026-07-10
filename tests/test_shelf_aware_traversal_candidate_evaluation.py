from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core import (
    traversal_candidate_evaluation,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.candidate_scoring import (
    CandidateScoreBreakdown,
    CandidateScoringGeometry,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import (
    PlannerConfig,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_evaluation import (
    evaluate_candidate_for_selection,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_ref import (
    TraversalCandidateRef,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_scoring_context import (
    build_traversal_scoring_context,
)


@dataclass
class FakeGraphAccess:
    points_by_cell_id: dict[str, tuple[int, int]]

    def planning_point_px_for_cell(self, cell_id: str) -> tuple[int, int]:
        return self.points_by_cell_id[str(cell_id)]


def _context() -> object:
    return build_traversal_scoring_context(
        point_path=[(100.0, 100.0)],
        coverage_width_px=9,
        previous_travel_angle=0.75,
        map_resolution=0.05,
        config=PlannerConfig(),
        local_direction_map=np.zeros((4, 4), dtype=float),
        local_direction_confidence=np.zeros((4, 4), dtype=float),
        edge_label_map=np.ones((4, 4), dtype=int),
        local_residual_count=3,
    )


def test_evaluate_candidate_for_selection_uses_graph_snapshot_geometry(monkeypatch) -> None:
    graph_access = FakeGraphAccess(
        points_by_cell_id={
            "last": (10, 20),
            "candidate": (30, 40),
        }
    )
    captured: dict[str, object] = {}

    def fake_score(geometry: CandidateScoringGeometry, **kwargs):
        captured["geometry"] = geometry
        captured["kwargs"] = kwargs
        return CandidateScoreBreakdown(
            total_energy=12.5,
            components={"distance_cost": 1.0, "turn_cost": 0.5},
            rejected_reasons=(),
            accepted=True,
            component_sum_valid=True,
        )

    monkeypatch.setattr(
        traversal_candidate_evaluation,
        "evaluate_candidate_score_for_geometry",
        fake_score,
    )

    record = evaluate_candidate_for_selection(
        last_cell_id="last",
        candidate_ref=TraversalCandidateRef.from_cell_id("candidate"),
        graph_access=graph_access,
        context=_context(),
        move_source="normal_neighbor",
        is_global_fallback=False,
        candidate_visit_count=2,
        candidate_local_residual_count=4,
        revisit_frontier_score=5,
    )

    geometry = captured["geometry"]
    assert isinstance(geometry, CandidateScoringGeometry)
    assert geometry.location_point_px == (10.0, 20.0)
    assert geometry.candidate_point_px == (30.0, 40.0)
    assert captured["kwargs"]["candidate_visit_count"] == 2
    assert captured["kwargs"]["candidate_local_residual_count"] == 4
    assert captured["kwargs"]["revisit_frontier_score"] == 5
    assert "history_clearance_index" not in captured["kwargs"]
    assert record.cell_id == "candidate"
    assert record.move_source == "normal_neighbor"
    assert record.accepted is True
    assert record.total_energy == 12.5
    assert record.score_components == (("distance_cost", 1.0), ("turn_cost", 0.5))
    assert record.rejected_reasons == ()


def test_evaluate_candidate_for_selection_preserves_rejected_score(monkeypatch) -> None:
    graph_access = FakeGraphAccess(
        points_by_cell_id={
            "last": (1, 2),
            "candidate": (3, 4),
        }
    )
    history_clearance_index = object()
    context = build_traversal_scoring_context(
        point_path=[(1.0, 2.0)],
        coverage_width_px=7,
        previous_travel_angle=0.0,
        map_resolution=0.05,
        config=PlannerConfig(),
        local_direction_map=np.zeros((4, 4), dtype=float),
        local_direction_confidence=np.zeros((4, 4), dtype=float),
        edge_label_map=None,
        local_residual_count=0,
        history_clearance_index=history_clearance_index,
    )
    captured: dict[str, object] = {}

    def fake_score(geometry: CandidateScoringGeometry, **kwargs):
        captured["geometry"] = geometry
        captured["kwargs"] = kwargs
        return CandidateScoreBreakdown(
            total_energy=None,
            components={},
            rejected_reasons=("shape_constraint",),
            accepted=False,
            component_sum_valid=False,
        )

    monkeypatch.setattr(
        traversal_candidate_evaluation,
        "evaluate_candidate_score_for_geometry",
        fake_score,
    )

    record = evaluate_candidate_for_selection(
        last_cell_id="last",
        candidate_ref=TraversalCandidateRef.from_cell_id("candidate"),
        graph_access=graph_access,
        context=context,
        move_source="global_fallback",
        is_global_fallback=True,
        candidate_visit_count=0,
        candidate_local_residual_count=0,
    )

    assert captured["kwargs"]["context"].history_clearance_index is history_clearance_index
    assert record.cell_id == "candidate"
    assert record.move_source == "global_fallback"
    assert record.accepted is False
    assert record.total_energy is None
    assert record.score_components == ()
    assert record.rejected_reasons == ("shape_constraint",)
