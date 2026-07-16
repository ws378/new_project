from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping, Optional

from ..modes import (
    BASIC_MODE,
    SHELF_AWARE_MODE,
    SHELF_AWARE_TURN_COST_MODE,
)
from ..node_generation_profiles import normalize_node_generation_mode
from ..profiles import (
    SHELF_AWARE_TURN_COST_NODE_GENERATION_MODE,
    SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR,
    apply_planner_mode_defaults,
    coverage_planner_mode_default_overrides,
    coverage_planner_profile_metadata,
)

CONFIG_CONFLICT_TOLERANCE = 1e-6
LEGACY_PUBLIC_CONFIG_KEYS = (
    "coverage_radius",
    "grid_spacing_m",
    "robot_radius",
    "erode_radius",
    "erode_radius_m",
)


def normalize_coverage_planner_config_dict(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the stage2 config payload and reject removed public legacy keys."""

    raw = dict(payload or {})
    found_legacy_keys = tuple(key for key in LEGACY_PUBLIC_CONFIG_KEYS if key in raw)
    if found_legacy_keys:
        raise ValueError(
            "legacy public config keys are no longer supported: "
            + ", ".join(found_legacy_keys)
        )
    return raw


@dataclass
class CoveragePlannerConfig:
    """Stable formal planner config shared by routing, adapters, and planners.

    The public config now belongs to the formal contract layer instead of any
    single planner implementation file. Width semantics and public field names
    are already tightened at this layer; remaining planner-private details stay
    below adapters and internal planner configs.
    """

    planner_mode: str = BASIC_MODE  # formal factory modes: basic / shelf_aware / shelf_aware_turn_cost
    coverage_width_m: float = 0.5
    robot_width_m: float = 0.4
    open_kernel_m: float = 0.8
    obstacle_expand_m: float = 0.8
    auto_rotate: bool = True

    # ------- shelfAware 关键参数 -------
    local_direction_enable: bool = True
    local_direction_energy_weight: float = 2.8
    fallback_jump_weight: float = 5.8
    local_lateral_weight: float = 0.8
    history_clearance_weight: float = 4.0
    split_jump_dist_factor: float = 10.0
    allow_revisit_bridge: bool = True
    shelf_ctg_auxiliary_enable: bool = False
    shelf_ctg_auxiliary_build_sweeps: bool = False
    shelf_node_generation_mode: str = "shelf_cell_adjusted"
    shelf_repaired_grid_max_offset_factor: float = 0.35
    shelf_row_endpoint_alignment_enable: bool = True
    shelf_node_obstacle_ratio_filter_enable: bool = True
    shelf_node_obstacle_ratio_threshold: float = 0.45
    isolated_jump_cleanup_enable: bool = True
    isolated_jump_distance_m: float = 3.0
    isolated_jump_max_points: int = 3
    isolated_jump_max_length_m: float = 1.0
    isolated_jump_reinsert_max_distance_m: float = 1.0
    isolated_jump_reinsert_improvement_ratio: float = 0.80
    shelf_quality_guard_enable: bool = False
    shelf_quality_guard_min_coverage_ratio: float = 0.90

    # ------- channel_topology_graph 关键参数 -------
    short_side_branch_m: float = 2.0
    free_node_min_clearance_m: float = 0.35
    intersection_merge_geodesic_px: int = 20
    junction_polygon_radius_px: float = 10.0

    # ------- GBNN 等高线参数 -------
    step: float = 0.5
    contour_start_offset: float = 0.3
    contour_layer_gap: float = 0.5
    contour_layers: int = 0  # 0 = 自适应, >0 = 固定层数
    min_perimeter_factor: float = 5.0
    min_node_dist_factor: float = 0.4
    connection_dist_factor: float = 2.5

    # ------- GBNN 核心参数 -------
    gbnn_A: float = 5.0
    gbnn_B: float = 1.0
    gbnn_D: float = 1.0
    gbnn_E: float = 100.0
    gbnn_iters: int = 80

    # ------- GBNN 评分权重 -------
    gbnn_frontier_weight: float = 0.3
    gbnn_dist_weight: float = 0.5
    gbnn_turn_weight: float = 0.5
    gbnn_straight_weight: float = 0.0
    gbnn_zigzag_weight: float = 0.0
    gbnn_backtrack_enable: bool = True
    turn_forward_bonus: float = 0.5
    zigzag_bonus: float = 0.3

    # ------- GBNN gap fill（不再使用，保留兼容） -------
    gap_fill_threshold_m: float = 0.3
    gap_fill_node_count: int = 5

    # ------- 基础算法 能量函数权重 -------
    straight_ahead_weight: float = 1.5
    turn_penalty_weight: float = 2.0
    lateral_weight: float = 0.8
    max_turn_deg: float = 90.0
    jump_bridge_interpolations: int = 2

    # ------- 转角约束 -------
    turn_constraint_enable: bool = True
    turn_constraint_prohibit_energy: float = 1e6
    turn_constraint_near_dist_m: float = 0.1
    turn_constraint_near_max_turn_deg: float = 20.0
    turn_constraint_neighbor_max_turn_deg: float = 100.0
    turn_constraint_fallback_max_turn_deg: float = 135.0
    turn_constraint_fallback_relax_dist_m: float = 2.0

    # ------- C* 专属参数 -------
    bridge_astar_enable: bool = False
    debug_show_nodes_only: bool = False
    layer_bridge_enable: bool = True
    turn_weight: float = 0.0
    boustrophedon_turn_weight: float = 0.0

    # ------- map-tools artifact / adapter parameters -------
    map_yaml_path: str = ""
    region_polygon_px: Optional[list[tuple[int, int]]] = None
    artifacts_output_root: str = ""
    geometry_risk_summary_path: str = ""
    write_artifacts: bool = False
    main_axis_direction: str = "→"

    def __post_init__(self) -> None:
        """Guard the formal public config against invalid numeric values."""

        if float(self.coverage_width_m) <= 0.0:
            raise ValueError("coverage_width_m must be positive")
        if float(self.robot_width_m) <= 0.0:
            raise ValueError("robot_width_m must be positive")
        try:
            normalize_node_generation_mode(str(self.shelf_node_generation_mode))
        except ValueError as exc:
            raise ValueError(str(exc).replace("node_generation_mode", "shelf_node_generation_mode")) from exc
        if not 0.0 <= float(self.shelf_repaired_grid_max_offset_factor) <= 1.0:
            raise ValueError("shelf_repaired_grid_max_offset_factor must be in [0, 1]")
        if not 0.0 <= float(self.shelf_node_obstacle_ratio_threshold) <= 1.0:
            raise ValueError("shelf_node_obstacle_ratio_threshold must be in [0, 1]")
        if float(self.open_kernel_m) <= 0.0:
            raise ValueError("open_kernel_m must be positive")
        if float(self.obstacle_expand_m) <= 0.0:
            raise ValueError("obstacle_expand_m must be positive")
        if float(self.short_side_branch_m) < 0.0:
            raise ValueError("short_side_branch_m must be >= 0")
        if float(self.free_node_min_clearance_m) < 0.0:
            raise ValueError("free_node_min_clearance_m must be >= 0")
        if float(self.isolated_jump_distance_m) <= 0.0:
            raise ValueError("isolated_jump_distance_m must be positive")
        if int(self.isolated_jump_max_points) < 1:
            raise ValueError("isolated_jump_max_points must be >= 1")
        if float(self.isolated_jump_max_length_m) < 0.0:
            raise ValueError("isolated_jump_max_length_m must be >= 0")
        if float(self.isolated_jump_reinsert_max_distance_m) < 0.0:
            raise ValueError("isolated_jump_reinsert_max_distance_m must be >= 0")
        if not 0.0 < float(self.isolated_jump_reinsert_improvement_ratio) <= 1.0:
            raise ValueError("isolated_jump_reinsert_improvement_ratio must be in (0, 1]")
        if not 0.0 <= float(self.shelf_quality_guard_min_coverage_ratio) <= 1.0:
            raise ValueError("shelf_quality_guard_min_coverage_ratio must be in [0, 1]")


PUBLIC_COVERAGE_CONFIG_FIELD_NAMES = frozenset(field.name for field in fields(CoveragePlannerConfig))


def coverage_planner_config_diff(
    requested: CoveragePlannerConfig | None,
    applied: CoveragePlannerConfig | None,
    keys: set[str] | frozenset[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return public config fields changed between requested and applied configs."""

    if requested is None or applied is None:
        return {}
    requested_dict = coverage_planner_config_to_dict(requested)
    applied_dict = coverage_planner_config_to_dict(applied)
    diff: dict[str, dict[str, Any]] = {}
    diff_keys = set(keys) if keys is not None else set(requested_dict) | set(applied_dict)
    for key in sorted(diff_keys):
        if requested_dict.get(key) != applied_dict.get(key):
            diff[key] = {
                "requested": requested_dict.get(key),
                "applied": applied_dict.get(key),
            }
    return diff


@dataclass(frozen=True)
class CoveragePlannerPrivateConfig:
    """Typed planner-private options kept outside the public config contract."""

    enable_channel_topology_graph: bool = False
    ctg_open_kernel_m: float | None = None
    ctg_short_side_branch_m: float | None = None
    ctg_crop_pad_px: int | None = None
    crop_pad_px: int | None = None
    ctg_intersection_merge_geodesic_px: int | None = None
    ctg_initial_junction_zone_radius_px: int | None = None
    ctg_initial_dead_end_zone_radius_px: int | None = None
    ctg_junction_polygon_radius_px: float | None = None
    ctg_dead_end_polygon_radius_px: float | None = None
    ctg_include_truncation_debug: bool | None = None
    ctg_pure_cycle_parallel_workers: int | None = None


PRIVATE_COVERAGE_CONFIG_FIELD_NAMES = frozenset(field.name for field in fields(CoveragePlannerPrivateConfig))
LEGACY_PRIVATE_CTG_CONFIG_KEYS = (
    "sweep_max_spacing_m",
    "robot_cleaning_width_m",
)


def build_coverage_planning_request_configs(
    payload: Mapping[str, Any] | None,
) -> tuple[CoveragePlannerConfig, tuple[str, ...], CoveragePlannerPrivateConfig]:
    """Build typed public/private request configs from a mixed runtime payload."""

    normalized = normalize_coverage_planner_config_dict(payload)
    public_values = {
        key: value
        for key, value in normalized.items()
        if key in PUBLIC_COVERAGE_CONFIG_FIELD_NAMES
    }
    return (
        CoveragePlannerConfig(**public_values),
        tuple(sorted(public_values)),
        build_private_coverage_planner_config(normalized),
    )


def coverage_planner_config_to_dict(config: CoveragePlannerConfig) -> dict[str, Any]:
    """Return a stable public-config dict for artifacts and diagnostics."""

    return dict(asdict(config))


def build_private_coverage_planner_config(payload: Mapping[str, Any] | None) -> CoveragePlannerPrivateConfig:
    """Return a typed planner-private config view from request extras."""

    normalized = normalize_coverage_planner_config_dict(payload)
    found_legacy_private_keys = tuple(key for key in LEGACY_PRIVATE_CTG_CONFIG_KEYS if key in normalized)
    if found_legacy_private_keys:
        raise ValueError(
            "legacy CTG config keys are no longer supported: "
            + ", ".join(found_legacy_private_keys)
        )
    values = {
        key: value
        for key, value in normalized.items()
        if key in PRIVATE_COVERAGE_CONFIG_FIELD_NAMES
    }
    return CoveragePlannerPrivateConfig(**values)
