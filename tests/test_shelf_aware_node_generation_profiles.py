import pytest

from algorithms.coverage_planning.node_generation_profiles import (
    NODE_GENERATION_MODES,
    NODE_GENERATION_PROFILE_REGISTRY,
    SHELF_CELL_ADJUSTED,
    TURN_COST_REPAIRED_GRID,
    NodeGenerationSettings,
    normalize_node_generation_mode,
    resolve_node_generation_profile,
)


def test_node_generation_settings_normalizes_public_values():
    settings = NodeGenerationSettings.from_public_values(
        node_generation_mode=TURN_COST_REPAIRED_GRID,
        repaired_grid_max_offset_factor="0.28",
        row_endpoint_alignment_enable=1,
        node_obstacle_ratio_filter_enable=1,
        node_obstacle_ratio_threshold="0.45",
    )

    assert settings.mode == TURN_COST_REPAIRED_GRID
    assert settings.profile.profile_id == "turn_cost_repaired_grid_v1"
    assert settings.profile.status == "candidate_mode_default"
    assert settings.repaired_grid_max_offset_factor == 0.28
    assert settings.row_endpoint_alignment_enable is True
    assert settings.node_obstacle_ratio_filter_enable is True
    assert settings.node_obstacle_ratio_threshold == 0.45
    assert normalize_node_generation_mode("shelf_cell_adjusted") == "shelf_cell_adjusted"
    assert "turn_cost_regular_grid" in NODE_GENERATION_MODES


def test_node_generation_settings_rejects_unknown_mode():
    with pytest.raises(ValueError, match="node_generation_mode must be"):
        NodeGenerationSettings.from_public_values(node_generation_mode="unknown_mode")


def test_node_generation_settings_does_not_validate_unused_numeric_values():
    settings = NodeGenerationSettings.from_public_values(
        node_generation_mode="shelf_cell_adjusted",
        repaired_grid_max_offset_factor="unused",
        node_obstacle_ratio_filter_enable=False,
        node_obstacle_ratio_threshold="unused",
    )

    assert settings.mode == "shelf_cell_adjusted"
    assert settings.profile.profile_id == "shelf_cell_adjusted_v1"
    assert settings.repaired_grid_max_offset_factor == 0.35
    assert settings.node_obstacle_ratio_threshold == 0.45


def test_node_generation_profile_registry_describes_modes():
    shelf_profile = resolve_node_generation_profile(SHELF_CELL_ADJUSTED)
    turn_cost_profile = resolve_node_generation_profile(TURN_COST_REPAIRED_GRID)

    assert set(NODE_GENERATION_PROFILE_REGISTRY) == set(NODE_GENERATION_MODES)
    assert shelf_profile.status == "formal_baseline"
    assert shelf_profile.applies_to_modes == ("shelf_aware",)
    assert turn_cost_profile.applies_to_modes == ("shelf_aware_turn_cost",)
    assert turn_cost_profile.supports_repaired_grid_offset is True


def test_node_generation_settings_exposes_profile_metadata():
    settings = NodeGenerationSettings.from_public_values(
        node_generation_mode=TURN_COST_REPAIRED_GRID,
        repaired_grid_max_offset_factor=0.28,
        row_endpoint_alignment_enable=True,
        node_obstacle_ratio_filter_enable=True,
        node_obstacle_ratio_threshold=0.45,
    )

    metadata = settings.profile_metadata()

    assert metadata["profile_id"] == "turn_cost_repaired_grid_v1"
    assert metadata["mode"] == TURN_COST_REPAIRED_GRID
    assert metadata["strategy"] == "regular_grid_with_bounded_repair"
    assert metadata["status"] == "candidate_mode_default"
    assert metadata["applies_to_modes"] == ["shelf_aware_turn_cost"]
    assert metadata["repaired_grid_max_offset_factor"] == 0.28
    assert metadata["row_endpoint_alignment_enable"] is True
