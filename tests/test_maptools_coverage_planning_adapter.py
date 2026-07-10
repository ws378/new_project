import numpy as np
import pytest

from maptools.adapters.coverage_planning_adapter import (
    CoveragePlannerConfig,
    CoveragePlannerPrivateConfig,
    CoveragePlanningRequest,
    build_region_mask_from_polygon,
    check_optional_planner_dependencies,
    create_coverage_planner,
    preprocess_total_map,
    run_formal_planner_request,
    route_coverage_plan,
    run_channel_topology_graph_adapter,
)


def test_adapter_exposes_formal_planner_config_type():
    config = CoveragePlannerConfig(planner_mode="basic")

    assert config.planner_mode == "basic"


def test_adapter_exposes_factory_and_dependency_probe():
    planner = create_coverage_planner(CoveragePlannerConfig(planner_mode="basic"))
    ok, reason = check_optional_planner_dependencies("mystery")

    assert planner.__class__.__name__ == "CoveragePlanner"
    assert ok is False
    assert "unknown planner mode" in str(reason)


def test_adapter_exposes_routing_and_preprocessing_entrypoints():
    assert CoveragePlanningRequest.__name__ == "CoveragePlanningRequest"
    assert callable(preprocess_total_map)
    assert callable(build_region_mask_from_polygon)
    assert callable(run_formal_planner_request)
    assert callable(route_coverage_plan)
    assert callable(run_channel_topology_graph_adapter)


def test_run_formal_planner_request_accepts_total_map_and_region_mask(tmp_path):
    prepared_map = np.zeros((60, 80), dtype=np.uint8)
    prepared_map[10:50, 10:70] = 255
    region_mask = np.zeros((60, 80), dtype=np.uint8)
    region_mask[20:40, 20:60] = 255

    request = CoveragePlanningRequest(
        prepared_map=prepared_map,
        map_resolution=0.05,
        starting_position_px=(25, 25),
        map_origin_xy=(0.0, 0.0),
        region_mask=region_mask,
        public_config=CoveragePlannerConfig(
            coverage_width_m=0.5,
            open_kernel_m=0.2,
            obstacle_expand_m=0.2,
            auto_rotate=False,
            write_artifacts=False,
        ),
        private_config=CoveragePlannerPrivateConfig(),
        artifacts_output_root=tmp_path,
    )

    result = run_formal_planner_request(request, "basic")

    assert result.success
    assert result.diagnostics.selected_planner == "region_basic"
    assert result.diagnostics.scene_type == "explicit"


def test_run_formal_planner_request_snaps_start_to_region_free_space(tmp_path):
    prepared_map = np.zeros((80, 80), dtype=np.uint8)
    prepared_map[10:70, 10:70] = 255
    region_mask = np.zeros((80, 80), dtype=np.uint8)
    region_mask[30:60, 30:60] = 255
    request = CoveragePlanningRequest(
        prepared_map=prepared_map,
        map_resolution=0.05,
        starting_position_px=(15, 15),
        region_mask=region_mask,
        public_config=CoveragePlannerConfig(
            coverage_width_m=0.5,
            open_kernel_m=0.2,
            obstacle_expand_m=0.2,
            auto_rotate=False,
            write_artifacts=False,
        ),
        artifacts_output_root=tmp_path,
    )

    result = run_formal_planner_request(request, "basic")

    assert result.success
    assert "start_snapped_to_nearest_free_pixel" in result.diagnostics.reasons


def test_formal_planner_config_rejects_non_positive_public_widths():
    with pytest.raises(ValueError, match="coverage_width_m must be positive"):
        CoveragePlannerConfig(coverage_width_m=0.0)

    with pytest.raises(ValueError, match="robot_width_m must be positive"):
        CoveragePlannerConfig(robot_width_m=0.0)


def test_formal_planner_config_rejects_invalid_preprocessing_or_clearance_values():
    with pytest.raises(ValueError, match="open_kernel_m must be positive"):
        CoveragePlannerConfig(open_kernel_m=0.0)

    with pytest.raises(ValueError, match="obstacle_expand_m must be positive"):
        CoveragePlannerConfig(obstacle_expand_m=0.0)

    with pytest.raises(ValueError, match="free_node_min_clearance_m must be >= 0"):
        CoveragePlannerConfig(free_node_min_clearance_m=-0.1)
    with pytest.raises(ValueError, match="isolated_jump_distance_m must be positive"):
        CoveragePlannerConfig(isolated_jump_distance_m=0.0)
    with pytest.raises(ValueError, match="isolated_jump_max_points must be >= 1"):
        CoveragePlannerConfig(isolated_jump_max_points=0)
    with pytest.raises(ValueError, match="isolated_jump_reinsert_improvement_ratio must be in"):
        CoveragePlannerConfig(isolated_jump_reinsert_improvement_ratio=1.5)
