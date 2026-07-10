from algorithms.coverage_planning.contracts import build_coverage_planning_request_configs
from tools.coverage_planning.run_case import _planner_config


def test_run_case_planner_config_requires_stage2_public_fields():
    try:
        _planner_config({}, "basic")
    except ValueError as exc:
        assert "coverage_width_m" in str(exc)
        return

    raise AssertionError("expected missing stage2 public field to fail")


def test_run_case_planner_config_reads_stage2_public_fields():
    config = _planner_config(
        {
            "coverage_width_m": 0.6,
            "open_kernel_m": 0.4,
            "obstacle_expand_m": 0.3,
            "robot_width_m": 0.5,
        },
        "basic",
    )

    assert config["coverage_width_m"] == 0.6
    assert config["open_kernel_m"] == 0.4
    assert config["obstacle_expand_m"] == 0.3
    assert config["robot_width_m"] == 0.5


def test_build_coverage_planning_request_configs_keeps_public_source_keys():
    public_config, source_keys, private_config = build_coverage_planning_request_configs(
        {
            "coverage_width_m": 0.6,
            "open_kernel_m": 0.4,
            "obstacle_expand_m": 0.3,
            "robot_width_m": 0.5,
            "enable_channel_topology_graph": True,
        }
    )

    assert public_config.coverage_width_m == 0.6
    assert source_keys == ("coverage_width_m", "obstacle_expand_m", "open_kernel_m", "robot_width_m")
    assert private_config.enable_channel_topology_graph is True
