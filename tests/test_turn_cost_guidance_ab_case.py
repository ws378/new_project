from __future__ import annotations

from algorithms.turn_cost_coverage_research.scripts.experiments.run_maptools_guidance_ab_case import select_ab_winner


def test_guidance_ab_selects_official_when_guided_coverage_drop_exceeds_threshold() -> None:
    decision = select_ab_winner(
        official_metrics={"case_count": 1, "success_count": 1, "coverage": 0.916, "turn_deg": 15000.0},
        guided_metrics={"case_count": 1, "success_count": 1, "coverage": 0.910, "turn_deg": 14000.0},
        max_coverage_drop=0.003,
        require_turn_nonincrease=True,
    )

    assert decision["selected"] == "official"
    assert decision["reason"] == "guided_coverage_drop_exceeds_threshold"


def test_guidance_ab_selects_guided_when_within_thresholds() -> None:
    decision = select_ab_winner(
        official_metrics={"case_count": 1, "success_count": 1, "coverage": 0.916, "turn_deg": 15000.0},
        guided_metrics={"case_count": 1, "success_count": 1, "coverage": 0.915, "turn_deg": 14000.0},
        max_coverage_drop=0.003,
        require_turn_nonincrease=True,
    )

    assert decision["selected"] == "guided"
    assert decision["reason"] == "guided_within_fallback_thresholds"


def test_guidance_ab_selects_official_when_guided_fails() -> None:
    decision = select_ab_winner(
        official_metrics={"case_count": 1, "success_count": 1, "coverage": 0.9, "turn_deg": 1.0},
        guided_metrics={"case_count": 1, "success_count": 0, "coverage": 0.0, "turn_deg": 0.0},
        max_coverage_drop=0.003,
        require_turn_nonincrease=False,
    )

    assert decision["selected"] == "official"
    assert decision["reason"] == "guided_failed"
