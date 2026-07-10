from pathlib import Path

import pytest

try:
    from algorithms.turn_cost_coverage_research.scripts.experiments.run_paper_official_algorithm_steps import (
        OfficialExampleParameters,
        _is_expected_license_failure,
        _result_scope,
        run_official_steps_case,
    )
except ImportError as exc:
    OfficialExampleParameters = None
    _is_expected_license_failure = None
    _result_scope = None
    run_official_steps_case = None
    OFFICIAL_REFERENCE_IMPORT_ERROR = exc
else:
    OFFICIAL_REFERENCE_IMPORT_ERROR = None
from algorithms.turn_cost_coverage_research.src.visualization.artifact_writer import (
    RunSummary,
    default_dependencies,
    validate_summary_contract,
    write_root_summary,
)


def _require_official_reference() -> None:
    if OFFICIAL_REFERENCE_IMPORT_ERROR is not None:
        pytest.skip(f"official reference environment unavailable: {OFFICIAL_REFERENCE_IMPORT_ERROR}")


def test_official_result_scope_marks_prefix_runs() -> None:
    _require_official_reference()
    scope = _result_scope("coverage")

    assert scope["is_full_algorithm_run"] is False
    assert scope["completion_scope"] == "official_prefix_until_coverage"


def test_square8_guided_atomic_requires_explicit_api_opt_in(tmp_path: Path) -> None:
    _require_official_reference()
    with pytest.raises(ValueError, match="allow_square8_guided_atomic"):
        run_official_steps_case(
            tmp_path / "case",
            stop_after="grid",
            seed=7,
            parameters=OfficialExampleParameters(),
            parameter_profile="unit_guard",
            fractional_solver_backend="highs",
            guidance_config={"enabled": True, "mode": "shelf_local_direction"},
            graph_backend_config={"backend": "square8_axis_guided"},
        )


def test_official_summary_contract_requires_source_and_scope() -> None:
    summary = RunSummary(
        case_id="official_example_algorithm_steps",
        case_group="paper_official_algorithm_steps",
        input={
            "source_commit": "abc123",
            "parameter_profile": "license_smoke",
            "stop_after": "coverage_plot",
            "fractional_solver_backend": "gurobi",
            "result_scope": {"is_full_algorithm_run": True},
        },
        dependencies={
            **default_dependencies(mesh_backend="pcpptc_official_hex_delaunay", solver_backend="pcpptc_official_gurobi_blossom_pcst"),
            "official_dependency_versions": {"gurobipy": "13.0.2"},
        },
        stage_status={"coverage_plot": "success"},
        metrics={
            "cycle_count_before_connection": 1,
            "connected_tour_feasible": True,
            "tour_waypoint_count": 3,
            "tour_length_m": 1.0,
            "tour_feasible_area_coverage_ratio": 0.9,
            "tour_valuable_area_value_coverage_ratio": 0.8,
            "tour_missed_value": 0.2,
        },
        third_party_usage=[
            {
                "name": "pcpptc",
                "commit_or_version": "abc123",
            }
        ],
    )

    assert validate_summary_contract(summary) == []


def test_official_summary_contract_rejects_missing_commit_or_version() -> None:
    summary = RunSummary(
        case_id="official_example_algorithm_steps",
        case_group="paper_official_algorithm_steps",
        input={
            "source_commit": "abc123",
            "parameter_profile": "license_smoke",
            "stop_after": "coverage_plot",
            "fractional_solver_backend": "gurobi",
            "result_scope": {"is_full_algorithm_run": True},
        },
        dependencies={
            **default_dependencies(),
            "official_dependency_versions": {"gurobipy": "13.0.2"},
        },
        stage_status={"coverage_plot": "success"},
        metrics={
            "cycle_count_before_connection": 1,
            "connected_tour_feasible": True,
            "tour_waypoint_count": 3,
            "tour_length_m": 1.0,
            "tour_feasible_area_coverage_ratio": 0.9,
            "tour_valuable_area_value_coverage_ratio": 0.8,
            "tour_missed_value": 0.2,
        },
        third_party_usage=[{"name": "pcpptc"}],
    )

    assert "official third_party_usage missing commit_or_version" in validate_summary_contract(summary)


def test_official_full_summary_contract_requires_tour_quality_metrics() -> None:
    summary = RunSummary(
        case_id="official_example_algorithm_steps",
        case_group="paper_official_algorithm_steps",
        input={
            "source_commit": "abc123",
            "parameter_profile": "license_smoke",
            "stop_after": "coverage_plot",
            "fractional_solver_backend": "gurobi",
            "result_scope": {"is_full_algorithm_run": True},
        },
        dependencies={
            **default_dependencies(),
            "official_dependency_versions": {"gurobipy": "13.0.2"},
        },
        stage_status={"coverage_plot": "success"},
        metrics={
            "cycle_count_before_connection": 1,
            "connected_tour_feasible": True,
        },
        third_party_usage=[{"name": "pcpptc", "commit_or_version": "abc123"}],
    )

    errors = validate_summary_contract(summary)

    assert "official full run missing tour_feasible_area_coverage_ratio" in errors
    assert "official full run missing tour_valuable_area_value_coverage_ratio" in errors


def test_expected_license_failure_detector(tmp_path: Path) -> None:
    _require_official_reference()
    write_root_summary(
        tmp_path,
        {
            "runner": "run_paper_official_algorithm_steps",
            "case_group": "paper_official_algorithm_steps",
            "case_count": 1,
            "success_count": 0,
            "parameter_profile": "notebook_default",
            "fractional_solver_backend": "gurobi",
            "result_scope": {"is_full_algorithm_run": True},
            "cases": [
                {
                    "failure_stage": "fractional",
                    "failure_reason": "GurobiError",
                    "failure_detail": "Model too large for size-limited license",
                }
            ],
        },
    )

    assert _is_expected_license_failure(tmp_path)
