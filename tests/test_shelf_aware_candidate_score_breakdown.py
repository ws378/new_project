from __future__ import annotations

import inspect

import numpy as np
import pytest

from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.candidate_scoring import (
    CandidateScoringContext,
    CandidateScoringGeometry,
    REJECT_REASON_SHAPE_CONSTRAINT,
    REJECT_REASON_TURN_CONSTRAINT,
    REJECT_REASON_VALUES,
    SCORE_COMPONENT_CTG_EDGE_SWITCH_COST,
    SCORE_COMPONENT_CTG_JUNCTION_ENTRY_COST,
    SCORE_COMPONENT_CTG_FALLBACK_EDGE_SWITCH_COST,
    SCORE_COMPONENT_CTG_SAME_EDGE_REWARD,
    SCORE_COMPONENT_DISTANCE_COST,
    SCORE_COMPONENT_FALLBACK_HEADING_COST,
    SCORE_COMPONENT_FALLBACK_JUMP_COST,
    SCORE_COMPONENT_HISTORY_CLEARANCE_COST,
    SCORE_COMPONENT_KEYS,
    SCORE_COMPONENT_LEGACY_HORIZONTAL_BIAS,
    SCORE_COMPONENT_LOCAL_DIRECTION_COST,
    SCORE_COMPONENT_LOCAL_LATERAL_COST,
    SCORE_COMPONENT_LOCAL_RESIDUAL_CONTINUE_REWARD,
    SCORE_COMPONENT_LOCAL_RESIDUAL_LEAVE_COST,
    SCORE_COMPONENT_REVISIT_FRONTIER_REWARD,
    SCORE_COMPONENT_REVISIT_PENALTY_COST,
    SCORE_COMPONENT_TURN_COST,
    compute_energy_breakdown_for_geometry,
    evaluate_candidate_score_for_geometry,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import (
    CtgGuidanceConfig,
    LocalDirectionConfig,
    StrategyConfig,
    TurnConstraintConfig,
)


def _score_context(**overrides):
    values = {
        "point_path": [(0.0, 0.0)],
        "coverage_width_px": 10,
        "previous_travel_angle": 0.0,
        "map_resolution": 0.05,
        "is_global_fallback": False,
        "turn_constraint": TurnConstraintConfig(),
        "local_direction_map": None,
        "local_direction_confidence": None,
        "local_direction_cfg": LocalDirectionConfig(enable=False),
        "edge_label_map": None,
        "ctg_guidance_cfg": CtgGuidanceConfig(),
        "strategy_cfg": StrategyConfig(),
        "local_residual_count": 0,
    }
    values.update(overrides)
    return CandidateScoringContext(**values)


def test_score_component_key_registry_is_stable_and_unique() -> None:
    assert SCORE_COMPONENT_KEYS == (
        SCORE_COMPONENT_DISTANCE_COST,
        SCORE_COMPONENT_TURN_COST,
        SCORE_COMPONENT_LOCAL_DIRECTION_COST,
        SCORE_COMPONENT_LEGACY_HORIZONTAL_BIAS,
        SCORE_COMPONENT_LOCAL_LATERAL_COST,
        SCORE_COMPONENT_CTG_SAME_EDGE_REWARD,
        SCORE_COMPONENT_CTG_EDGE_SWITCH_COST,
        SCORE_COMPONENT_CTG_FALLBACK_EDGE_SWITCH_COST,
        SCORE_COMPONENT_CTG_JUNCTION_ENTRY_COST,
        SCORE_COMPONENT_FALLBACK_JUMP_COST,
        SCORE_COMPONENT_FALLBACK_HEADING_COST,
        SCORE_COMPONENT_LOCAL_RESIDUAL_CONTINUE_REWARD,
        SCORE_COMPONENT_REVISIT_PENALTY_COST,
        SCORE_COMPONENT_REVISIT_FRONTIER_REWARD,
        SCORE_COMPONENT_LOCAL_RESIDUAL_LEAVE_COST,
        SCORE_COMPONENT_HISTORY_CLEARANCE_COST,
    )
    assert len(SCORE_COMPONENT_KEYS) == len(set(SCORE_COMPONENT_KEYS))


def test_reject_reason_registry_is_stable_and_unique() -> None:
    assert REJECT_REASON_VALUES == (
        REJECT_REASON_SHAPE_CONSTRAINT,
        REJECT_REASON_TURN_CONSTRAINT,
    )
    assert len(REJECT_REASON_VALUES) == len(set(REJECT_REASON_VALUES))


def test_candidate_score_entrypoint_uses_context_contract() -> None:
    compute_signature = inspect.signature(compute_energy_breakdown_for_geometry)
    assert tuple(compute_signature.parameters) == ("geometry", "context")

    signature = inspect.signature(evaluate_candidate_score_for_geometry)
    assert tuple(signature.parameters) == (
        "geometry",
        "context",
        "candidate_local_residual_count",
        "candidate_visit_count",
        "revisit_frontier_score",
    )


def test_candidate_score_breakdown_reports_components_for_accepted_candidate() -> None:
    score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points((0.0, 0.0), (10.0, 0.0)),
        context=_score_context(),
    )

    assert score.accepted is True
    assert score.component_sum_valid is True
    assert score.rejected_reasons == ()
    assert score.total_energy is not None
    assert sum(score.components.values()) == pytest.approx(score.total_energy)
    assert score.components[SCORE_COMPONENT_DISTANCE_COST] == pytest.approx(1.0)
    assert score.components[SCORE_COMPONENT_TURN_COST] == pytest.approx(0.0)
    assert SCORE_COMPONENT_LEGACY_HORIZONTAL_BIAS in score.components


def test_candidate_score_breakdown_preserves_turn_constraint_rejection() -> None:
    score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points((0.0, 0.0), (10.0, 0.0)),
        context=_score_context(
            previous_travel_angle=np.pi,
            turn_constraint=TurnConstraintConfig(enable_prohibit=True, neighbor_max_turn_deg=90.0),
        ),
    )

    assert score.accepted is False
    assert score.component_sum_valid is False
    assert score.rejected_reasons == (REJECT_REASON_TURN_CONSTRAINT,)
    assert score.total_energy == pytest.approx(1_000_000.0)
    assert score.components[SCORE_COMPONENT_DISTANCE_COST] == pytest.approx(1.0)


def test_candidate_score_breakdown_documents_fallback_turn_constraint_is_not_hard_rejected() -> None:
    score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points((0.0, 0.0), (10.0, 0.0)),
        context=_score_context(
            previous_travel_angle=np.pi,
            is_global_fallback=True,
            turn_constraint=TurnConstraintConfig(
                enable_prohibit=True,
                near_max_turn_deg=1.0,
                neighbor_max_turn_deg=1.0,
                fallback_max_turn_deg=1.0,
            ),
        ),
    )

    assert score.accepted is True
    assert REJECT_REASON_TURN_CONSTRAINT not in score.rejected_reasons
    assert score.total_energy is not None
    assert score.total_energy < 1_000_000.0


def test_candidate_score_breakdown_reports_shape_rejection_without_energy() -> None:
    score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points((5.0, 0.0), (0.0, 0.0)),
        context=_score_context(
            point_path=[(0.0, 0.0), (5.0, 0.0)],
            strategy_cfg=StrategyConfig(near_reverse_enable=True),
        ),
    )

    assert score.accepted is False
    assert score.component_sum_valid is False
    assert score.rejected_reasons == (REJECT_REASON_SHAPE_CONSTRAINT,)
    assert score.total_energy is None
    assert score.components == {}


def test_candidate_score_breakdown_reports_fallback_costs() -> None:
    score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points((0.0, 0.0), (10.0, 10.0)),
        context=_score_context(
            previous_travel_angle=0.25,
            is_global_fallback=True,
            strategy_cfg=StrategyConfig(fallback_jump_weight=2.0, fallback_heading_weight=3.0),
            local_residual_count=2,
        ),
    )

    assert score.accepted is True
    assert score.total_energy is not None
    assert score.components[SCORE_COMPONENT_FALLBACK_JUMP_COST] > 0.0
    assert score.components[SCORE_COMPONENT_FALLBACK_HEADING_COST] > 0.0
    assert sum(score.components.values()) == pytest.approx(score.total_energy)


def test_candidate_score_breakdown_reports_sampling_costs() -> None:
    local_direction_map = np.zeros((5, 5), dtype=float)
    local_direction_confidence = np.zeros((5, 5), dtype=float)
    local_direction_map[1, 3] = 0.5 * np.pi
    local_direction_confidence[1, 3] = 0.8
    local_direction_map[1, 1] = 0.5 * np.pi
    local_direction_confidence[1, 1] = 0.7
    edge_label_map = np.full((5, 5), -1, dtype=int)
    edge_label_map[1, 1] = 4
    edge_label_map[1, 3] = 7

    score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points((1.0, 1.0), (3.0, 1.0)),
        context=_score_context(
            point_path=[(1.0, 1.0)],
            coverage_width_px=2,
            is_global_fallback=True,
            local_direction_map=local_direction_map,
            local_direction_confidence=local_direction_confidence,
            local_direction_cfg=LocalDirectionConfig(enable=True, min_confidence=0.1, energy_weight=2.0),
            edge_label_map=edge_label_map,
            ctg_guidance_cfg=CtgGuidanceConfig(enable=True, edge_switch_penalty=3.0, fallback_edge_switch_penalty=5.0),
            strategy_cfg=StrategyConfig(local_lateral_weight=1.5),
        ),
    )

    assert score.accepted is True
    assert score.components[SCORE_COMPONENT_LOCAL_DIRECTION_COST] == pytest.approx(1.6)
    assert score.components[SCORE_COMPONENT_LOCAL_LATERAL_COST] == pytest.approx(1.05)
    assert score.components[SCORE_COMPONENT_CTG_EDGE_SWITCH_COST] == pytest.approx(3.0)
    assert score.components[SCORE_COMPONENT_CTG_FALLBACK_EDGE_SWITCH_COST] == pytest.approx(5.0)
