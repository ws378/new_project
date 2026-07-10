import numpy as np
import pytest

from algorithms.coverage_planning.contracts import (
    CoveragePlannerConfig,
    CoveragePlannerPrivateConfig,
    CoveragePlanningRequest,
    build_private_coverage_planner_config,
    normalize_coverage_planner_config_dict,
)


def test_coverage_planning_request_requires_prepared_map_contract_only():
    request = CoveragePlanningRequest(
        prepared_map=np.zeros((8, 8), dtype=np.uint8),
        map_resolution=0.05,
        starting_position_px=(1, 1),
    )

    assert request.prepared_map.shape == (8, 8)
    assert not hasattr(request, "room_map")


def test_coverage_planning_request_accepts_typed_public_and_private_config():
    request = CoveragePlanningRequest(
        prepared_map=np.zeros((8, 8), dtype=np.uint8),
        map_resolution=0.05,
        starting_position_px=(1, 1),
        public_config=CoveragePlannerConfig(
            coverage_width_m=0.6,
            robot_width_m=0.45,
            open_kernel_m=0.2,
            obstacle_expand_m=0.15,
        ),
        private_config=CoveragePlannerPrivateConfig(enable_channel_topology_graph=True),
    )

    assert isinstance(request.public_config, CoveragePlannerConfig)
    assert request.public_config.coverage_width_m == 0.6
    assert request.public_config.robot_width_m == 0.45
    assert request.private_config is not None
    assert request.private_config.enable_channel_topology_graph is True


def test_coverage_planning_request_keeps_explicit_public_source_keys_only():
    request = CoveragePlanningRequest(
        prepared_map=np.zeros((8, 8), dtype=np.uint8),
        map_resolution=0.05,
        starting_position_px=(1, 1),
        public_config=CoveragePlannerConfig(coverage_width_m=0.6),
        public_config_source_keys=("coverage_width_m",),
    )

    assert request.public_config_source_keys == ("coverage_width_m",)


def test_normalize_coverage_planner_config_dict_rejects_removed_legacy_public_keys():
    with pytest.raises(ValueError, match="legacy public config keys are no longer supported"):
        normalize_coverage_planner_config_dict({"coverage_radius": 0.8})


def test_build_private_coverage_planner_config_rejects_removed_legacy_ctg_keys():
    with pytest.raises(ValueError, match="legacy CTG config keys are no longer supported"):
        build_private_coverage_planner_config({"sweep_max_spacing_m": 0.8})


def test_coverage_planning_request_accepts_typed_private_config():
    request = CoveragePlanningRequest(
        prepared_map=np.zeros((8, 8), dtype=np.uint8),
        map_resolution=0.05,
        starting_position_px=(1, 1),
        private_config=CoveragePlannerPrivateConfig(enable_channel_topology_graph=True),
    )

    assert request.private_config is not None
    assert request.private_config.enable_channel_topology_graph is True


def test_coverage_planning_request_rejects_region_mask_shape_mismatch():
    with pytest.raises(ValueError, match="region_mask must have the same shape as prepared_map"):
        CoveragePlanningRequest(
            prepared_map=np.zeros((8, 8), dtype=np.uint8),
            map_resolution=0.05,
            starting_position_px=(1, 1),
            region_mask=np.zeros((7, 8), dtype=np.uint8),
        )
