"""Coverage planner routing and applicability logic."""

from .applicability import classify_applicability, compute_applicability_metrics
from .coverage_router import route_coverage_plan
from ..modes import ROUTED_PLANNER_MODES

__all__ = [
    "ROUTED_PLANNER_MODES",
    "classify_applicability",
    "compute_applicability_metrics",
    "route_coverage_plan",
]
