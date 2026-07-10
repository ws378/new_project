"""Stable contracts shared by coverage-planning planners and adapters."""

from .applicability import ApplicabilityMetrics, ApplicabilityResult
from .config import (
    apply_planner_mode_defaults,
    build_coverage_planning_request_configs,
    coverage_planner_config_diff,
    coverage_planner_mode_default_overrides,
    coverage_planner_profile_metadata,
    CoveragePlannerConfig,
    CoveragePlannerPrivateConfig,
    SHELF_AWARE_MODE,
    SHELF_AWARE_TURN_COST_MODE,
    SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE,
    SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR,
    build_private_coverage_planner_config,
    coverage_planner_config_to_dict,
    normalize_coverage_planner_config_dict,
)
from .diagnostics import CoveragePlanningDiagnostics, CoveragePlanningRuntimeDetails
from .diagnostics import (
    build_readable_diagnostics_summary,
    CoveragePlanningFinalPathSummary,
    CoveragePlanningFinalPathValidation,
    CoveragePlanningPipelineMeta,
)
from .planner_results import CoverageResult, Pose2D
from .requests import CoveragePlanningRequest
from .results import CoveragePlanningResult, CoveragePlanningStatus, CoveragePose2D

__all__ = [
    "ApplicabilityMetrics",
    "ApplicabilityResult",
    "apply_planner_mode_defaults",
    "build_coverage_planning_request_configs",
    "coverage_planner_config_diff",
    "coverage_planner_mode_default_overrides",
    "coverage_planner_profile_metadata",
    "CoveragePlannerConfig",
    "CoveragePlannerPrivateConfig",
    "SHELF_AWARE_MODE",
    "SHELF_AWARE_TURN_COST_MODE",
    "SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE",
    "SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR",
    "build_private_coverage_planner_config",
    "build_readable_diagnostics_summary",
    "coverage_planner_config_to_dict",
    "normalize_coverage_planner_config_dict",
    "CoverageResult",
    "CoveragePlanningDiagnostics",
    "CoveragePlanningFinalPathSummary",
    "CoveragePlanningFinalPathValidation",
    "CoveragePlanningPipelineMeta",
    "CoveragePlanningRuntimeDetails",
    "CoveragePlanningRequest",
    "CoveragePlanningResult",
    "CoveragePlanningStatus",
    "CoveragePose2D",
    "Pose2D",
]
