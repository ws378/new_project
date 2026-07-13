from algorithms.coverage_planning.modes import (
    ADAPTER_ONLY_MODES,
    AUTO_MODE,
    BASIC_MODE,
    BCD_BOUSTROPHEDON_MODE,
    CHANNEL_TOPOLOGY_GRAPH_MODE,
    FORMAL_FACTORY_MODES,
    REGION_BASIC_ROUTED_MODE,
    ROUTED_PLANNER_MODES,
    SHELF_AWARE_MODE,
    SHELF_AWARE_TURN_COST_MODE,
    UI_PLANNER_MODES,
    config_planner_mode_from_routed_mode,
    formal_selected_planner_name,
    is_adapter_only_mode,
    is_formal_factory_mode,
)
from algorithms.coverage_planning.profiles import (
    PLANNER_MODE_PROFILES,
    PLANNER_PROFILE_VERSION_POLICY,
    SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE,
    SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR,
    coverage_planner_mode_default_overrides,
    coverage_planner_profile_metadata,
    planner_mode_profile,
)


def test_top_level_coverage_planning_exports_turn_cost_profile_contract():
    from algorithms.coverage_planning import (
        SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE as exported_node_generation_mode,
        SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR as exported_repaired_grid_factor,
        coverage_planner_mode_default_overrides as exported_default_overrides,
        coverage_planner_profile_metadata as exported_profile_metadata,
    )

    assert exported_node_generation_mode == SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE
    assert exported_repaired_grid_factor == SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR
    assert exported_default_overrides(SHELF_AWARE_TURN_COST_MODE) == {
        "shelf_node_generation_mode": SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE,
        "shelf_repaired_grid_max_offset_factor": SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR,
        "isolated_jump_cleanup_enable": False,
    }
    assert exported_profile_metadata(SHELF_AWARE_TURN_COST_MODE)["profile_status"] == "candidate_enhancement"


def test_planner_mode_registry_separates_ui_factory_and_router_domains():
    assert BCD_BOUSTROPHEDON_MODE in UI_PLANNER_MODES
    assert BCD_BOUSTROPHEDON_MODE in FORMAL_FACTORY_MODES

    assert AUTO_MODE not in FORMAL_FACTORY_MODES
    assert CHANNEL_TOPOLOGY_GRAPH_MODE not in FORMAL_FACTORY_MODES
    assert REGION_BASIC_ROUTED_MODE not in FORMAL_FACTORY_MODES

    assert ROUTED_PLANNER_MODES == {
        REGION_BASIC_ROUTED_MODE,
        SHELF_AWARE_MODE,
        CHANNEL_TOPOLOGY_GRAPH_MODE,
    }
    assert ADAPTER_ONLY_MODES == {CHANNEL_TOPOLOGY_GRAPH_MODE}


def test_planner_mode_registry_maps_public_config_and_diagnostics_names():
    assert formal_selected_planner_name(BASIC_MODE) == REGION_BASIC_ROUTED_MODE
    assert formal_selected_planner_name(SHELF_AWARE_MODE) == SHELF_AWARE_MODE
    assert config_planner_mode_from_routed_mode(REGION_BASIC_ROUTED_MODE) == BASIC_MODE
    assert config_planner_mode_from_routed_mode(SHELF_AWARE_MODE) == SHELF_AWARE_MODE


def test_planner_mode_registry_predicates_match_contract_boundaries():
    assert is_formal_factory_mode(BASIC_MODE)
    assert is_formal_factory_mode(SHELF_AWARE_TURN_COST_MODE)
    assert not is_formal_factory_mode(AUTO_MODE)
    assert not is_formal_factory_mode(CHANNEL_TOPOLOGY_GRAPH_MODE)

    assert is_adapter_only_mode(CHANNEL_TOPOLOGY_GRAPH_MODE)
    assert not is_adapter_only_mode(SHELF_AWARE_TURN_COST_MODE)


def test_planner_profile_registry_owns_turn_cost_composite_defaults():
    profile = planner_mode_profile(SHELF_AWARE_TURN_COST_MODE)

    assert profile is not None
    assert profile.profile_id == "shelf_aware_turn_cost_repaired_grid_0_28"
    assert profile.profile_status == "candidate_enhancement"
    assert profile.default_overrides == {
        "shelf_node_generation_mode": SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE,
        "shelf_repaired_grid_max_offset_factor": SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR,
        "isolated_jump_cleanup_enable": False,
    }
    assert coverage_planner_mode_default_overrides(SHELF_AWARE_TURN_COST_MODE) == dict(profile.default_overrides)
    assert coverage_planner_profile_metadata(SHELF_AWARE_TURN_COST_MODE) == {
        "planner_mode": SHELF_AWARE_TURN_COST_MODE,
        "profile_id": profile.profile_id,
        "profile_version": profile.profile_version,
        "profile_status": "candidate_enhancement",
        "profile_version_policy": PLANNER_PROFILE_VERSION_POLICY,
    }


def test_planner_profile_registry_requires_status_and_version_policy():
    assert set(PLANNER_MODE_PROFILES) == FORMAL_FACTORY_MODES
    for mode, profile in PLANNER_MODE_PROFILES.items():
        metadata = coverage_planner_profile_metadata(mode)

        assert metadata["planner_mode"] == mode
        assert metadata["profile_id"] == profile.profile_id
        assert metadata["profile_version"] == profile.profile_version
        assert metadata["profile_status"] == profile.profile_status
        assert metadata["profile_version_policy"] == PLANNER_PROFILE_VERSION_POLICY
