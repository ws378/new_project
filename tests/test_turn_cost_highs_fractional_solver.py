import pytest

try:
    from algorithms.turn_cost_coverage_research.scripts.experiments.run_paper_official_algorithm_steps import (
        OfficialExampleParameters,
        run_official_steps_case,
    )
except ImportError as exc:
    pytest.skip(f"official reference environment unavailable: {exc}", allow_module_level=True)


def test_highs_fractional_solver_matches_gurobi_on_license_smoke(tmp_path) -> None:
    pytest.importorskip("gurobipy")
    pytest.importorskip("scipy")

    params = OfficialExampleParameters(
        complexity=3,
        size=5.0,
        penalties=1,
        multiplier=1,
        turn_costs=1,
        penalty_strength=40.0,
        multiplier_strength=20.0,
        tool_radius=0.5,
    )
    gurobi_summary = run_official_steps_case(
        tmp_path / "gurobi",
        stop_after="fractional",
        seed=4,
        parameters=params,
        parameter_profile="license_smoke",
        fractional_solver_backend="gurobi",
    )
    highs_summary = run_official_steps_case(
        tmp_path / "highs",
        stop_after="fractional",
        seed=4,
        parameters=params,
        parameter_profile="license_smoke",
        fractional_solver_backend="highs",
    )

    assert gurobi_summary.status == "success"
    assert highs_summary.status == "success"
    assert highs_summary.metrics["non_official_solver_replacement"]["stage"] == "fractional"
    assert highs_summary.metrics["fractional_objective_value"] == pytest.approx(
        gurobi_summary.metrics["fractional_objective_value"],
        abs=1e-6,
    )
