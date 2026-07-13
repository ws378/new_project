"""Planner mode profiles and deterministic mode defaults."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from .modes import (
    BASIC_MODE,
    BASIC_IMPROVED_MODE,
    BOUSTROPHEDON_MODE,
    BCD_BOUSTROPHEDON_MODE,
    CELL_DNN_MODE,
    CONTOUR_DNN_MODE,
    CONTOUR_MATRIX_MODE,
    CSTAR_CIRCLE_MODE,
    CSTAR_RECT_MODE,
    CSTAR_TSP_MODE,
    ECD_DNN_MODE,
    SHELF_AWARE_MODE,
    SHELF_AWARE_TURN_COST_MODE,
    SPIRAL_MODE,
    STC_MODE,
    WAVEFRONT_MODE,
)

SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE = "turn_cost_repaired_grid"
SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR = 0.28
PLANNER_PROFILE_VERSION_POLICY = "increment_on_default_overrides_or_formal_behavior_contract_change"


@dataclass(frozen=True)
class PlannerModeProfile:
    """Stable identity and forced defaults for a planner mode."""

    planner_mode: str
    profile_id: str
    profile_version: int
    profile_status: str
    default_overrides: Mapping[str, Any]
    version_policy: str = PLANNER_PROFILE_VERSION_POLICY


PLANNER_MODE_PROFILES: dict[str, PlannerModeProfile] = {
    BASIC_MODE: PlannerModeProfile(
        planner_mode=BASIC_MODE,
        profile_id="basic_default",
        profile_version=1,
        profile_status="formal_baseline",
        default_overrides={},
    ),
    BASIC_IMPROVED_MODE: PlannerModeProfile(
        planner_mode=BASIC_IMPROVED_MODE,
        profile_id="basic_improved_default",
        profile_version=1,
        profile_status="candidate_enhancement",
        default_overrides={
            "straight_ahead_weight": 2.0,
            "turn_penalty_weight": 2.5,
            "lateral_weight": 1.0,
            "max_turn_deg": 90.0,
        },
    ),
    CONTOUR_DNN_MODE: PlannerModeProfile(
        planner_mode=CONTOUR_DNN_MODE,
        profile_id="contour_dnn_default",
        profile_version=1,
        profile_status="research_baseline",
        default_overrides={
            "min_perimeter_factor": 0.3,
            "gbnn_frontier_weight": 0.3,
            "gbnn_dist_weight": 0.5,
            "gbnn_turn_weight": 0.5,
        },
    ),
    CELL_DNN_MODE: PlannerModeProfile(
        planner_mode=CELL_DNN_MODE,
        profile_id="cell_dnn_default",
        profile_version=1,
        profile_status="research_baseline",
        default_overrides={},
    ),
    ECD_DNN_MODE: PlannerModeProfile(
        planner_mode=ECD_DNN_MODE,
        profile_id="ecd_dnn_default",
        profile_version=1,
        profile_status="research_baseline",
        default_overrides={},
    ),
    CONTOUR_MATRIX_MODE: PlannerModeProfile(
        planner_mode=CONTOUR_MATRIX_MODE,
        profile_id="contour_matrix_default",
        profile_version=1,
        profile_status="research_baseline",
        default_overrides={
            "min_perimeter_factor": 0.3,
        },
    ),
    CSTAR_RECT_MODE: PlannerModeProfile(
        planner_mode=CSTAR_RECT_MODE,
        profile_id="cstar_rect_default",
        profile_version=1,
        profile_status="research_baseline",
        default_overrides={},
    ),
    CSTAR_CIRCLE_MODE: PlannerModeProfile(
        planner_mode=CSTAR_CIRCLE_MODE,
        profile_id="cstar_circle_default",
        profile_version=1,
        profile_status="research_baseline",
        default_overrides={},
    ),
    CSTAR_TSP_MODE: PlannerModeProfile(
        planner_mode=CSTAR_TSP_MODE,
        profile_id="cstar_tsp_default",
        profile_version=1,
        profile_status="research_baseline",
        default_overrides={},
    ),
    BOUSTROPHEDON_MODE: PlannerModeProfile(
        planner_mode=BOUSTROPHEDON_MODE,
        profile_id="boustrophedon_default",
        profile_version=1,
        profile_status="research_baseline",
        default_overrides={},
    ),
    BCD_BOUSTROPHEDON_MODE: PlannerModeProfile(
        planner_mode=BCD_BOUSTROPHEDON_MODE,
        profile_id="bcd_boustrophedon_default",
        profile_version=1,
        profile_status="research_baseline",
        default_overrides={},
    ),
    SPIRAL_MODE: PlannerModeProfile(
        planner_mode=SPIRAL_MODE,
        profile_id="spiral_default",
        profile_version=1,
        profile_status="research_baseline",
        default_overrides={},
    ),
    WAVEFRONT_MODE: PlannerModeProfile(
        planner_mode=WAVEFRONT_MODE,
        profile_id="wavefront_default",
        profile_version=1,
        profile_status="research_baseline",
        default_overrides={},
    ),
    STC_MODE: PlannerModeProfile(
        planner_mode=STC_MODE,
        profile_id="stc_default",
        profile_version=1,
        profile_status="research_baseline",
        default_overrides={},
    ),
    SHELF_AWARE_MODE: PlannerModeProfile(
        planner_mode=SHELF_AWARE_MODE,
        profile_id="shelf_aware_default",
        profile_version=1,
        profile_status="formal_baseline",
        default_overrides={},
    ),
    SHELF_AWARE_TURN_COST_MODE: PlannerModeProfile(
        planner_mode=SHELF_AWARE_TURN_COST_MODE,
        profile_id="shelf_aware_turn_cost_repaired_grid_0_28",
        profile_version=2,
        profile_status="candidate_enhancement",
        default_overrides={
            "shelf_node_generation_mode": SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE,
            "shelf_repaired_grid_max_offset_factor": SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR,
            "isolated_jump_cleanup_enable": False,
        },
    ),
}


def planner_mode_profile(planner_mode: str) -> PlannerModeProfile | None:
    """Return the profile for a planner mode, if it has one."""

    return PLANNER_MODE_PROFILES.get(str(planner_mode or BASIC_MODE))


def apply_planner_mode_defaults(config: Any) -> Any:
    """Apply deterministic defaults for named composite planner modes."""

    profile = planner_mode_profile(getattr(config, "planner_mode", BASIC_MODE))
    if profile is None or not profile.default_overrides:
        return config
    return replace(config, **dict(profile.default_overrides))


def coverage_planner_profile_metadata(planner_mode: str) -> dict[str, Any]:
    """Return stable profile metadata for a formal planner mode."""

    mode = str(planner_mode or BASIC_MODE)
    profile = planner_mode_profile(mode)
    if profile is None:
        return {
            "planner_mode": mode,
            "profile_id": "",
            "profile_version": 0,
            "profile_status": "unknown_planner_mode",
            "profile_version_policy": PLANNER_PROFILE_VERSION_POLICY,
        }
    return {
        "planner_mode": mode,
        "profile_id": profile.profile_id,
        "profile_version": int(profile.profile_version),
        "profile_status": profile.profile_status,
        "profile_version_policy": profile.version_policy,
    }


def coverage_planner_mode_default_overrides(planner_mode: str) -> dict[str, Any]:
    """Return public config values forced by composite planner mode defaults."""

    profile = planner_mode_profile(planner_mode)
    if profile is None:
        return {}
    return dict(profile.default_overrides)
