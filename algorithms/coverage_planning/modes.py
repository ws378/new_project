"""Coverage planner mode registry.

This module is the single source of truth for planner mode identifiers shared
by the UI, export path, formal planner factory, and routing adapters.
"""

from __future__ import annotations

BASIC_MODE = "basic"
REGION_BASIC_ROUTED_MODE = "region_basic"
SHELF_AWARE_MODE = "shelf_aware"
SHELF_AWARE_TURN_COST_MODE = "shelf_aware_turn_cost"
AUTO_MODE = "auto"
CHANNEL_TOPOLOGY_GRAPH_MODE = "channel_topology_graph"

SHELF_AWARE_FORMAL_MODES = frozenset(
    {
        SHELF_AWARE_MODE,
        SHELF_AWARE_TURN_COST_MODE,
    }
)

FORMAL_FACTORY_MODES = frozenset(
    {
        BASIC_MODE,
        *SHELF_AWARE_FORMAL_MODES,
    }
)

SHELF_AWARE_ROUTED_MODES = frozenset(
    {
        SHELF_AWARE_MODE,
    }
)

ROUTED_PLANNER_MODES = frozenset(
    {
        REGION_BASIC_ROUTED_MODE,
        *SHELF_AWARE_ROUTED_MODES,
        CHANNEL_TOPOLOGY_GRAPH_MODE,
    }
)

UI_PLANNER_MODES = (
    AUTO_MODE,
    BASIC_MODE,
    SHELF_AWARE_MODE,
    SHELF_AWARE_TURN_COST_MODE,
    CHANNEL_TOPOLOGY_GRAPH_MODE,
)

ADAPTER_ONLY_MODES = frozenset(
    {
        CHANNEL_TOPOLOGY_GRAPH_MODE,
    }
)


def formal_selected_planner_name(planner_mode: str) -> str:
    """Return the diagnostics selected_planner name for a formal factory mode."""

    return REGION_BASIC_ROUTED_MODE if str(planner_mode) == BASIC_MODE else str(planner_mode)


def config_planner_mode_from_routed_mode(planner_mode: str) -> str:
    """Return the public config planner_mode for a routed planner identifier."""

    return BASIC_MODE if str(planner_mode) == REGION_BASIC_ROUTED_MODE else str(planner_mode)


def is_formal_factory_mode(planner_mode: str) -> bool:
    """Return whether `planner_mode` is directly runnable by planner_factory."""

    return str(planner_mode) in FORMAL_FACTORY_MODES


def is_shelf_aware_formal_mode(planner_mode: str) -> bool:
    """Return whether `planner_mode` uses the shelfAware guarded planner."""

    return str(planner_mode) in SHELF_AWARE_FORMAL_MODES


def is_shelf_aware_routed_mode(planner_mode: str) -> bool:
    """Return whether `planner_mode` uses shelfAware inside the auto router."""

    return str(planner_mode) in SHELF_AWARE_ROUTED_MODES


def is_adapter_only_mode(planner_mode: str) -> bool:
    """Return whether `planner_mode` is an adapter mode, not a formal factory mode."""

    return str(planner_mode) in ADAPTER_ONLY_MODES
