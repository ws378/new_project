"""Planner mode profiles and deterministic mode defaults."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from .modes import BASIC_MODE, SHELF_AWARE_MODE, SHELF_AWARE_TURN_COST_MODE

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
