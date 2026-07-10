from maptools.adapters.coverage_planning_adapter import CoveragePlannerConfig
from maptools.utils.coverage_repo_export import _normalize_export_planner_config


def test_normalize_export_planner_config_defaults_to_basic():
    config = _normalize_export_planner_config(None)

    assert config.planner_mode == "basic"


def test_normalize_export_planner_config_keeps_requested_mode():
    original = CoveragePlannerConfig(planner_mode="basic")

    normalized = _normalize_export_planner_config(original)

    assert normalized is original
    assert normalized.planner_mode == "basic"


def test_normalize_export_planner_config_keeps_auto_mode():
    original = CoveragePlannerConfig(planner_mode="auto")

    normalized = _normalize_export_planner_config(original)

    assert normalized is original
    assert normalized.coverage_width_m == original.coverage_width_m
