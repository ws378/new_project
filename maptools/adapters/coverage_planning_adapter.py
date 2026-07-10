"""Stable maptools-side bridge for formal coverage-planning integration."""

from __future__ import annotations

from algorithms.coverage_planning import (
    CoveragePlannerConfig,
    CoveragePlannerPrivateConfig,
    CoveragePlanningRequest,
    check_optional_planner_dependencies,
    create_coverage_planner,
    run_formal_planner_request,
    route_coverage_plan,
)
from algorithms.coverage_planning.preprocessing import build_region_mask_from_polygon, preprocess_total_map
from algorithms.coverage_planning.routing.adapters import run_channel_topology_graph_adapter

__all__ = [
    "CoveragePlannerConfig",
    "CoveragePlannerPrivateConfig",
    "CoveragePlanningRequest",
    "build_region_mask_from_polygon",
    "check_optional_planner_dependencies",
    "create_coverage_planner",
    "preprocess_total_map",
    "run_formal_planner_request",
    "route_coverage_plan",
    "run_channel_topology_graph_adapter",
]
