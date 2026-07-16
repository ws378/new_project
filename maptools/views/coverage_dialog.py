"""
覆盖路径参数配置对话框
"""

from pathlib import Path
import tkinter as tk
from tkinter import ttk, simpledialog

from .layout_components import _ToolTip
from .theme import COLORS, FONTS, SPACING

from algorithms.coverage_planning.modes import (
    AUTO_MODE,
    BASIC_MODE,
    BASIC_IMPROVED_MODE,
    BCD_BOUSTROPHEDON_MODE,
    CELL_DNN_MODE,
    CHANNEL_TOPOLOGY_GRAPH_MODE,
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
    UI_PLANNER_MODES,
    WAVEFRONT_MODE,
)
from algorithms.coverage_planning.profiles import (
    coverage_planner_mode_default_overrides,
    coverage_planner_profile_metadata,
)
from ..adapters.coverage_planning_adapter import CoveragePlannerConfig

UI_PLANNER_CHOICES = (
    ("自动选择", AUTO_MODE),
    ("C*矩形算法", CSTAR_RECT_MODE),
    ("C*TSP优化", CSTAR_TSP_MODE),
    ("基础算法", BASIC_MODE),
    ("基础算法改进版", BASIC_IMPROVED_MODE),
    ("等高线GBNN", CONTOUR_DNN_MODE),
    ("细胞分解GBNN", ECD_DNN_MODE),
    ("BCD牛耕分解", BCD_BOUSTROPHEDON_MODE),
    ("螺旋覆盖", SPIRAL_MODE),
    ("波前算法", WAVEFRONT_MODE),
    ("生成树覆盖", STC_MODE),
    ("shelfAware", SHELF_AWARE_MODE),
    ("ShelfAware+TurnCost", SHELF_AWARE_TURN_COST_MODE),
    ("通道拓扑图", CHANNEL_TOPOLOGY_GRAPH_MODE),
)
assert tuple(value for _, value in UI_PLANNER_CHOICES) == UI_PLANNER_MODES

TOOLTIP_MAP: dict[str, str] = {
    "coverage_width_m": "相邻扫描线/等高线之间的间距，也是路径点的间距。越小覆盖率越高但路径越长。",
    "robot_width_m": "机器人的物理宽度，用于障碍物膨胀和窄通道判断。",
    "open_kernel_m": "形态学开运算核大小，去除地图噪点。",
    "obstacle_expand_m": "障碍物膨胀距离，确保机器人安全通过。",
    "step": "等高线/扫描线的取样步长（沿轮廓撒点的间距）。",
    "contour_start_offset": "第一条等高线距离障碍物的偏移量 (m)。",
    "contour_layer_gap": "相邻等高线层之间的间距 (m)。",
    "contour_layers": "等高线层数。0=根据地图自适应。",
    "min_perimeter_factor": "最小周长倍率，过滤过短的等高线片段。",
    "min_node_dist_factor": "节点最小间距倍率，防止节点过密。",
    "connection_dist_factor": "层间连接距离倍率，决定上下层节点的连接范围。",
    "straight_ahead_weight": "直行奖励权重，越大越倾向于直行。",
    "turn_penalty_weight": "转向惩罚权重，越大越少转弯。",
    "lateral_weight": "横切惩罚权重，抑制横向移动。",
    "max_turn_deg": "规划路径中允许的最大转角 (度)。",
    "jump_bridge_interpolations": "层间桥接时的插值点数。",
    "turn_weight": "TSP 阶段的转向惩罚权重。",
    "boustrophedon_turn_weight": "牛耕往复直线权重，控制行间跳转时的方向偏好。",
    "gbnn_frontier_weight": "GBNN 前沿（未访问邻居）在评分中的权重。",
    "gbnn_dist_weight": "GBNN 距离项在评分中的权重。",
    "gbnn_turn_weight": "GBNN 转弯惩罚在评分中的权重。",
    "gbnn_straight_weight": "GBNN 直行偏好在评分中的权重。",
    "gbnn_zigzag_weight": "GBNN 蛇形换行偏好的权重。",
    "gbnn_A": "GBNN 动力学方程参数 A（衰减率）。",
    "gbnn_B": "GBNN 动力学方程参数 B（上界）。",
    "gbnn_D": "GBNN 动力学方程参数 D（下界）。",
    "gbnn_E": "GBNN 动力学方程参数 E（外部输入强度）。",
    "gbnn_iters": "GBNN 动力学迭代次数。",
    "gbnn_backtrack_enable": "启用回溯，死胡同时跳向全局最近未覆盖节点。",
    "layer_bridge_enable": "启用层间 A* 桥接连接。",
    "short_side_branch_m": "通道拓扑图中短侧枝的阈值长度 (m)。",
    "free_node_min_clearance_m": "自由节点所需的最小净空距离 (m)。",
    "auto_rotate": "自动将地图旋转对齐到主方向。",
    "write_artifacts": "将调试中间结果（分段图、节点可视化等）写出到文件。",
    "turn_constraint_enable": "启用转角约束，在靠近障碍物时限制最大转角。",
    "turn_constraint_near_dist_m": "近邻判定距离，在此距离内的障碍物触发转角约束 (m)。",
    "turn_constraint_near_max_turn_deg": "近邻区域内的最大允许转角 (度)。",
    "turn_constraint_neighbor_max_turn_deg": "邻接路径段的最大允许转角 (度)。",
    "turn_constraint_fallback_max_turn_deg": "回退模式的最大允许转角 (度)。",
    "turn_constraint_fallback_relax_dist_m": "回退放宽距离，超过此距离放松转角约束 (m)。",
    "local_direction_enable": "启用局部方向图，为 ShelfAware 规划器提供局部方向引导。",
    "local_direction_energy_weight": "局部方向图在评分中的权重。",
    "fallback_jump_weight": "长跳惩罚权重，用于 ShelfAware 的跳转评分。",
    "history_clearance_weight": "历史轨迹净空权重，避免重复路径。",
    "shelf_ctg_auxiliary_enable": "启用 CTG territory/junction 辅助。",
    "shelf_quality_guard_enable": "启用质量守卫，确保覆盖率达标。",
    "shelf_quality_guard_min_coverage_ratio": "质量守卫要求的最小覆盖率。",
    "shelf_row_endpoint_alignment_enable": "启用行段首尾对齐。",
    "shelf_node_obstacle_ratio_filter_enable": "启用节点障碍比例过滤。",
    "shelf_node_obstacle_ratio_threshold": "节点障碍比例阈值。",
    "local_lateral_weight": "横切惩罚权重（局部）。",
    "split_jump_dist_factor": "长跳切段阈值倍率。",
    "allow_revisit_bridge": "允许重复回接已覆盖区域。",
    "isolated_jump_cleanup_enable": "启用孤立跳变点治理。",
    "isolated_jump_distance_m": "孤立跳变判定距离 (m)。",
    "isolated_jump_max_points": "孤立段最大点数。",
    "isolated_jump_max_length_m": "孤立段最大长度 (m)。",
    "isolated_jump_reinsert_max_distance_m": "回插最大邻近距离 (m)。",
    "isolated_jump_reinsert_improvement_ratio": "回插改善比例。",
    "intersection_merge_geodesic_px": "交汇合并 geodesic 距离 (px)。",
    "junction_polygon_radius_px": "交汇 polygon 半径 (px)。",
}

COMPARISON_CANDIDATES = (
    CSTAR_RECT_MODE,
    CSTAR_TSP_MODE,
    CONTOUR_DNN_MODE,
    BASIC_IMPROVED_MODE,
)

COMMON_PARAMETER_FIELDS = (
    "coverage_width_m",
    "robot_width_m",
    "open_kernel_m",
    "obstacle_expand_m",
)

SHELF_PARAMETER_FIELDS = (
    "local_direction_enable",
    "local_direction_energy_weight",
    "fallback_jump_weight",
    "history_clearance_weight",
)

SHELF_ADVANCED_FIELDS = (
    "shelf_ctg_auxiliary_enable",
    "shelf_row_endpoint_alignment_enable",
    "shelf_node_obstacle_ratio_filter_enable",
    "shelf_node_obstacle_ratio_threshold",
    "local_lateral_weight",
    "split_jump_dist_factor",
    "allow_revisit_bridge",
    "isolated_jump_cleanup_enable",
    "isolated_jump_distance_m",
    "isolated_jump_max_points",
    "isolated_jump_max_length_m",
    "isolated_jump_reinsert_max_distance_m",
    "isolated_jump_reinsert_improvement_ratio",
)

SHELF_TURN_COST_ADVANCED_FIELDS = tuple(
    field_name
    for field_name in SHELF_ADVANCED_FIELDS
    if field_name
    not in {
        "isolated_jump_cleanup_enable",
        "isolated_jump_distance_m",
        "isolated_jump_max_points",
        "isolated_jump_max_length_m",
        "isolated_jump_reinsert_max_distance_m",
        "isolated_jump_reinsert_improvement_ratio",
    }
)

SHELF_QUALITY_GUARD_FIELDS = (
    "shelf_quality_guard_enable",
    "shelf_quality_guard_min_coverage_ratio",
)

CTG_PARAMETER_FIELDS = (
    "short_side_branch_m",
    "free_node_min_clearance_m",
)

CTG_ADVANCED_FIELDS = (
    "intersection_merge_geodesic_px",
    "junction_polygon_radius_px",
)

SHARED_ADVANCED_FIELDS = (
    "auto_rotate",
    "write_artifacts",
)

TURN_CONSTRAINT_FIELDS = (
    "turn_constraint_enable",
    "turn_constraint_near_dist_m",
    "turn_constraint_near_max_turn_deg",
    "turn_constraint_neighbor_max_turn_deg",
    "turn_constraint_fallback_max_turn_deg",
    "turn_constraint_fallback_relax_dist_m",
)

SHELF_AWARE_DIALOG_MODES = (
    SHELF_AWARE_MODE,
    SHELF_AWARE_TURN_COST_MODE,
)

GBNN_DIALOG_MODES = (
    CONTOUR_DNN_MODE,
    CELL_DNN_MODE,
    ECD_DNN_MODE,
    CONTOUR_MATRIX_MODE,
)

CSTAR_DIALOG_MODES = (
    CSTAR_RECT_MODE,
    CSTAR_CIRCLE_MODE,
    CSTAR_TSP_MODE,
)

CONTOUR_DNN_PARAMETER_FIELDS = (
    "step",
    "contour_start_offset",
    "contour_layer_gap",
    "contour_layers",
    "min_perimeter_factor",
    "min_node_dist_factor",
    "connection_dist_factor",
    "gbnn_A",
    "gbnn_B",
    "gbnn_D",
    "gbnn_E",
    "gbnn_iters",
    "gbnn_frontier_weight",
    "gbnn_dist_weight",
    "gbnn_turn_weight",
    "gbnn_straight_weight",
    "gbnn_zigzag_weight",
    "gbnn_backtrack_enable",
)

CONTOUR_LEVEL_FIELDS = (
    "step",
    "contour_start_offset",
    "contour_layer_gap",
    "contour_layers",
    "min_perimeter_factor",
    "min_node_dist_factor",
    "connection_dist_factor",
)

GBNN_SCORE_FIELDS = (
    "gbnn_frontier_weight",
    "gbnn_dist_weight",
    "gbnn_turn_weight",
    "gbnn_straight_weight",
    "gbnn_zigzag_weight",
    "gbnn_backtrack_enable",
)

GBNN_DYNAMICS_FIELDS = (
    "gbnn_A",
    "gbnn_B",
    "gbnn_D",
    "gbnn_E",
    "gbnn_iters",
)

CSTAR_SHARED_FIELDS = (
    "layer_bridge_enable",
    "jump_bridge_interpolations",
    "boustrophedon_turn_weight",
)

CSTAR_TSP_FIELDS = (
    "turn_weight",
)

CSTAR_PARAMETER_FIELDS = (*CSTAR_SHARED_FIELDS, *CSTAR_TSP_FIELDS)

BASIC_ENERGY_FIELDS = (
    "straight_ahead_weight",
    "turn_penalty_weight",
    "lateral_weight",
    "max_turn_deg",
)

DIALOG_CONFIG_FIELDS = (
    "planner_mode",
    *COMMON_PARAMETER_FIELDS,
    *SHARED_ADVANCED_FIELDS,
    *BASIC_ENERGY_FIELDS,
    *CONTOUR_DNN_PARAMETER_FIELDS,
    *CSTAR_PARAMETER_FIELDS,
    *SHELF_PARAMETER_FIELDS,
    *SHELF_ADVANCED_FIELDS,
    *SHELF_QUALITY_GUARD_FIELDS,
    *CTG_PARAMETER_FIELDS,
    *CTG_ADVANCED_FIELDS,
    *TURN_CONSTRAINT_FIELDS,
)

DIALOG_VARIABLE_NAMES = {
    "planner_mode": "planner_mode_var",
    "coverage_width_m": "coverage_width_var",
    "robot_width_m": "robot_width_var",
    "open_kernel_m": "open_kernel_var",
    "obstacle_expand_m": "obstacle_expand_var",
    "auto_rotate": "auto_rotate_var",
    "local_direction_enable": "local_direction_enable_var",
    "local_direction_energy_weight": "local_direction_energy_weight_var",
    "fallback_jump_weight": "fallback_jump_weight_var",
    "local_lateral_weight": "local_lateral_weight_var",
    "history_clearance_weight": "history_clearance_weight_var",
    "split_jump_dist_factor": "split_jump_dist_factor_var",
    "allow_revisit_bridge": "allow_revisit_bridge_var",
    "shelf_ctg_auxiliary_enable": "shelf_ctg_auxiliary_enable_var",
    "shelf_quality_guard_enable": "shelf_quality_guard_enable_var",
    "shelf_quality_guard_min_coverage_ratio": "shelf_quality_guard_min_coverage_ratio_var",
    "shelf_row_endpoint_alignment_enable": "shelf_row_endpoint_alignment_enable_var",
    "shelf_node_obstacle_ratio_filter_enable": "shelf_node_obstacle_ratio_filter_enable_var",
    "shelf_node_obstacle_ratio_threshold": "shelf_node_obstacle_ratio_threshold_var",
    "isolated_jump_cleanup_enable": "isolated_jump_cleanup_enable_var",
    "isolated_jump_distance_m": "isolated_jump_distance_m_var",
    "isolated_jump_max_points": "isolated_jump_max_points_var",
    "isolated_jump_max_length_m": "isolated_jump_max_length_m_var",
    "isolated_jump_reinsert_max_distance_m": "isolated_jump_reinsert_max_distance_m_var",
    "isolated_jump_reinsert_improvement_ratio": "isolated_jump_reinsert_improvement_ratio_var",
    "short_side_branch_m": "short_side_branch_var",
    "free_node_min_clearance_m": "free_node_min_clearance_var",
    "intersection_merge_geodesic_px": "intersection_merge_geodesic_var",
    "junction_polygon_radius_px": "junction_polygon_radius_var",
    "turn_constraint_enable": "turn_constraint_var",
    "turn_constraint_near_dist_m": "turn_constraint_near_dist_m_var",
    "turn_constraint_near_max_turn_deg": "turn_constraint_near_max_turn_deg_var",
    "turn_constraint_neighbor_max_turn_deg": "turn_constraint_neighbor_max_turn_deg_var",
    "turn_constraint_fallback_max_turn_deg": "turn_constraint_fallback_max_turn_deg_var",
    "turn_constraint_fallback_relax_dist_m": "turn_constraint_fallback_relax_dist_m_var",
    "step": "step_var",
    "contour_start_offset": "contour_start_offset_var",
    "contour_layer_gap": "contour_layer_gap_var",
    "contour_layers": "contour_layers_var",
    "min_perimeter_factor": "min_perimeter_factor_var",
    "min_node_dist_factor": "min_node_dist_factor_var",
    "connection_dist_factor": "connection_dist_factor_var",
    "gbnn_A": "gbnn_A_var",
    "gbnn_B": "gbnn_B_var",
    "gbnn_D": "gbnn_D_var",
    "gbnn_E": "gbnn_E_var",
    "gbnn_iters": "gbnn_iters_var",
    "gbnn_frontier_weight": "gbnn_frontier_weight_var",
    "gbnn_dist_weight": "gbnn_dist_weight_var",
    "gbnn_turn_weight": "gbnn_turn_weight_var",
    "gbnn_straight_weight": "gbnn_straight_weight_var",
    "gbnn_zigzag_weight": "gbnn_zigzag_weight_var",
    "gbnn_backtrack_enable": "gbnn_backtrack_enable_var",
    "layer_bridge_enable": "layer_bridge_enable_var",

    "straight_ahead_weight": "straight_ahead_weight_var",
    "turn_penalty_weight": "turn_penalty_weight_var",
    "lateral_weight": "lateral_weight_var",
    "max_turn_deg": "max_turn_deg_var",
    "jump_bridge_interpolations": "jump_bridge_interpolations_var",
    "turn_weight": "turn_weight_var",
    "boustrophedon_turn_weight": "boustrophedon_turn_weight_var",
    "write_artifacts": "write_artifacts_var",
    "show_advanced": "show_advanced_var",
}


def coverage_dialog_default_values() -> dict[str, object]:
    """Return the dialog defaults used when opening a fresh dialog."""

    return {
        "planner_mode": AUTO_MODE,
        "coverage_width_m": 0.6,
        "robot_width_m": 0.4,
        "open_kernel_m": 0.6,
        "obstacle_expand_m": 0.6,
        "auto_rotate": True,
        "write_artifacts": False,
        "step": 0.5,
        "contour_start_offset": 0.3,
        "contour_layer_gap": 0.5,
        "contour_layers": 0,
        "min_perimeter_factor": 1.0,
        "min_node_dist_factor": 0.4,
        "connection_dist_factor": 2.5,
        "gbnn_A": 5.0,
        "gbnn_B": 1.0,
        "gbnn_D": 1.0,
        "gbnn_E": 100.0,
        "gbnn_iters": 80,
        "gbnn_frontier_weight": 0.3,
        "gbnn_dist_weight": 0.5,
        "gbnn_turn_weight": 0.5,
        "gbnn_straight_weight": 0.0,
        "gbnn_zigzag_weight": 0.0,
        "gbnn_backtrack_enable": True,
        "local_direction_enable": True,
        "local_direction_energy_weight": 2.8,
        "fallback_jump_weight": 5.8,
        "local_lateral_weight": 0.8,
        "history_clearance_weight": 4.0,
        "split_jump_dist_factor": 10.0,
        "allow_revisit_bridge": True,
        "shelf_ctg_auxiliary_enable": False,
        "shelf_quality_guard_enable": False,
        "shelf_quality_guard_min_coverage_ratio": 0.90,
        "shelf_row_endpoint_alignment_enable": True,
        "shelf_node_obstacle_ratio_filter_enable": True,
        "shelf_node_obstacle_ratio_threshold": 0.45,
        "isolated_jump_cleanup_enable": True,
        "isolated_jump_distance_m": 3.0,
        "isolated_jump_max_points": 3,
        "isolated_jump_max_length_m": 1.0,
        "isolated_jump_reinsert_max_distance_m": 1.0,
        "isolated_jump_reinsert_improvement_ratio": 0.8,
        "short_side_branch_m": 2.0,
        "free_node_min_clearance_m": 0.35,
        "intersection_merge_geodesic_px": 20,
        "junction_polygon_radius_px": 10.0,
        "layer_bridge_enable": True,
        "straight_ahead_weight": 1.5,
        "turn_penalty_weight": 2.0,
        "lateral_weight": 0.8,
        "max_turn_deg": 90.0,
        "jump_bridge_interpolations": 2,
        "turn_weight": 0.0,
        "boustrophedon_turn_weight": 0.0,
        "turn_constraint_enable": True,
        "turn_constraint_near_dist_m": 0.1,
        "turn_constraint_near_max_turn_deg": 20.0,
        "turn_constraint_neighbor_max_turn_deg": 100.0,
        "turn_constraint_fallback_max_turn_deg": 135.0,
        "turn_constraint_fallback_relax_dist_m": 2.0,
        "show_advanced": False,
    }


def merge_coverage_dialog_values(values: dict[str, object] | None) -> dict[str, object]:
    """Merge remembered dialog values with current known defaults."""

    merged = coverage_dialog_default_values()
    for key, value in dict(values or {}).items():
        if key in merged:
            merged[key] = value
    return merged


def coverage_dialog_values_from_config(
    config: CoveragePlannerConfig,
    *,
    show_advanced: bool = False,
) -> dict[str, object]:
    """Build dialog values from an existing planner config."""

    values = coverage_dialog_default_values()
    for field_name in DIALOG_CONFIG_FIELDS:
        if hasattr(config, field_name):
            values[field_name] = getattr(config, field_name)
    values["show_advanced"] = bool(show_advanced)
    return values


def coverage_dialog_config_from_values(values: dict[str, object] | None) -> CoveragePlannerConfig:
    """Build a planner config from dialog values, ignoring UI-only state."""

    merged = merge_coverage_dialog_values(values)
    config_values = {
        field_name: merged[field_name]
        for field_name in DIALOG_CONFIG_FIELDS
    }
    return CoveragePlannerConfig(**config_values)


def build_coverage_input_summary(parent, *, area_name: str = "", start_point_set: bool = False) -> dict[str, str]:
    map_data = getattr(parent, "map_data", None)
    yaml_path = getattr(map_data, "yaml_path", "") if map_data is not None else ""
    map_name = Path(str(yaml_path)).name if yaml_path else "未加载"
    metadata = getattr(map_data, "metadata", None)
    resolution = getattr(metadata, "resolution", None) if metadata is not None else None
    return {
        "map_name": map_name or "未加载",
        "resolution": "未知" if resolution is None else f"{float(resolution):.3f} m/px",
        "region_status": area_name or "未指定区域",
        "start_status": "已设置" if start_point_set else "未设置，默认使用区域质心",
    }


def resolve_visible_parameter_groups(planner_mode: str) -> dict[str, tuple[str, ...]]:
    mode = str(planner_mode or AUTO_MODE)
    groups: dict[str, tuple[str, ...]] = {
        "common": COMMON_PARAMETER_FIELDS,
        "basic_energy": (),
        "shared_advanced": SHARED_ADVANCED_FIELDS,
        "turn_constraint": (),
        "contour": (),
        "gbnn_score": (),
        "gbnn_dynamics": (),
        "cstar": (),
        "boustrophedon": (),
        "shelf": (),
        "shelf_advanced": (),
        "shelf_quality_guard": (),
        "ctg": (),
        "ctg_advanced": (),
    }
    if mode == BASIC_IMPROVED_MODE:
        groups["basic_energy"] = BASIC_ENERGY_FIELDS

    SURVEY_DIALOG_MODES = (SPIRAL_MODE, WAVEFRONT_MODE, STC_MODE)
    if mode in {BASIC_MODE, BASIC_IMPROVED_MODE, *SHELF_AWARE_DIALOG_MODES, *CSTAR_DIALOG_MODES, *SURVEY_DIALOG_MODES}:
        groups["turn_constraint"] = TURN_CONSTRAINT_FIELDS

    CONTOUR_MODES = (CONTOUR_DNN_MODE, CONTOUR_MATRIX_MODE)
    SCORE_MODES = (CONTOUR_DNN_MODE, CELL_DNN_MODE, ECD_DNN_MODE)
    DYNAMICS_MODES = (ECD_DNN_MODE,)
    if mode in CONTOUR_MODES:
        groups["contour"] = CONTOUR_LEVEL_FIELDS
    if mode in SCORE_MODES:
        groups["gbnn_score"] = GBNN_SCORE_FIELDS
    if mode in DYNAMICS_MODES:
        groups["gbnn_dynamics"] = GBNN_DYNAMICS_FIELDS
    if mode in CSTAR_DIALOG_MODES:
        groups["contour"] = CONTOUR_LEVEL_FIELDS
        groups["cstar"] = CSTAR_PARAMETER_FIELDS
    if mode in SHELF_AWARE_DIALOG_MODES:
        groups["shelf"] = SHELF_PARAMETER_FIELDS
        groups["shelf_advanced"] = (
            SHELF_TURN_COST_ADVANCED_FIELDS
            if mode == SHELF_AWARE_TURN_COST_MODE
            else SHELF_ADVANCED_FIELDS
        )
        groups["shelf_quality_guard"] = SHELF_QUALITY_GUARD_FIELDS
    elif mode == CHANNEL_TOPOLOGY_GRAPH_MODE:
        groups["ctg"] = CTG_PARAMETER_FIELDS
        groups["ctg_advanced"] = CTG_ADVANCED_FIELDS
    return groups


def _dialog_value_text(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_planner_mode_override_notice(planner_mode: str) -> str:
    """Return the inline mode/profile notice shown in the parameter dialog."""

    mode = str(planner_mode or AUTO_MODE)
    metadata = coverage_planner_profile_metadata(mode)
    profile_id = str(metadata.get("profile_id", "") or "")
    profile_version = int(metadata.get("profile_version", 0) or 0)
    overrides = coverage_planner_mode_default_overrides(mode)
    if not profile_id:
        return "当前模式没有正式 profile；不会在参数面板外追加固定覆盖。"
    profile_text = profile_id
    if profile_version:
        profile_text = f"{profile_text} v{profile_version}"
    if not overrides:
        return f"Profile: {profile_text}；当前模式不会强制覆盖保存参数。"
    override_text = ", ".join(
        f"{field_name}={_dialog_value_text(overrides[field_name])}"
        for field_name in sorted(overrides)
    )
    return f"Profile: {profile_text}；固定覆盖: {override_text}"


class CoverageDialog(simpledialog.Dialog):
    """覆盖路径规划参数配置对话框"""

    def __init__(self, parent, title="覆盖路径参数", input_summary=None, initial_values=None):
        self.result_config = None
        self.result_values = None
        self.input_summary = dict(input_summary or {})
        self._initial_values = merge_coverage_dialog_values(initial_values)
        self._field_rows = {}
        super().__init__(parent, title=title)

    def body(self, master):
        """创建对话框内容"""
        master.configure(bg=COLORS["bg_primary"])

        summary_frame = tk.LabelFrame(
            master, text="正式输入摘要",
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            font=FONTS["body_bold"], relief=tk.GROOVE, bd=1,
        )
        summary_frame.grid(row=0, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=(8, 4))
        summary_frame.columnconfigure(1, weight=1)
        summary = {
            "map_name": self.input_summary.get("map_name", "未加载"),
            "resolution": self.input_summary.get("resolution", "未知"),
            "region_status": self.input_summary.get("region_status", "未指定区域"),
            "start_status": self.input_summary.get("start_status", "未设置"),
        }
        for row, (label, value) in enumerate(
            (
                ("当前地图:", summary["map_name"]),
                ("地图分辨率:", summary["resolution"]),
                ("当前区域:", summary["region_status"]),
                ("起点状态:", summary["start_status"]),
            )
        ):
            tk.Label(summary_frame, text=label, width=10, anchor="e",
                     bg=COLORS["bg_primary"], fg=COLORS["fg_secondary"],
                     font=FONTS["body"]).grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
            tk.Label(summary_frame, text=value, anchor="w",
                     bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
                     font=FONTS["body"]).grid(row=row, column=1, sticky=tk.W, padx=5, pady=2)

        mode_frame = tk.LabelFrame(
            master, text="算法选择",
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            font=FONTS["body_bold"], relief=tk.GROOVE, bd=1,
        )
        mode_frame.grid(row=1, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=4)
        self.planner_mode_var = tk.StringVar(value=AUTO_MODE)
        for index, (label, value) in enumerate(UI_PLANNER_CHOICES):
            tk.Radiobutton(
                mode_frame, text=label,
                variable=self.planner_mode_var, value=value,
                command=self._update_parameter_visibility,
                bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
                activebackground=COLORS["bg_primary"],
                activeforeground=COLORS["fg_bright"],
                selectcolor=COLORS["bg_surface"],
                font=FONTS["body"],
            ).pack(side=tk.LEFT, padx=(8, 0) if index else 0)
        self.mode_override_notice_var = tk.StringVar(value="")
        tk.Label(
            mode_frame, textvariable=self.mode_override_notice_var,
            anchor=tk.W, justify=tk.LEFT,
            bg=COLORS["bg_primary"], fg=COLORS["fg_muted"],
            font=FONTS["caption"], wraplength=520,
        ).pack(side=tk.LEFT, padx=(12, 0))

        self.coverage_width_var = tk.DoubleVar(value=0.6)
        self.robot_width_var = tk.DoubleVar(value=0.4)
        self.open_kernel_var = tk.DoubleVar(value=0.6)
        self.obstacle_expand_var = tk.DoubleVar(value=0.6)
        self.auto_rotate_var = tk.BooleanVar(value=True)
        self.write_artifacts_var = tk.BooleanVar(value=False)
        self.turn_constraint_var = tk.BooleanVar(value=True)
        self.turn_constraint_near_dist_m_var = tk.DoubleVar(value=0.1)
        self.local_direction_enable_var = tk.BooleanVar(value=True)
        self.local_direction_energy_weight_var = tk.DoubleVar(value=2.8)
        self.fallback_jump_weight_var = tk.DoubleVar(value=5.8)
        self.local_lateral_weight_var = tk.DoubleVar(value=0.8)
        self.history_clearance_weight_var = tk.DoubleVar(value=4.0)
        self.split_jump_dist_factor_var = tk.DoubleVar(value=10.0)
        self.allow_revisit_bridge_var = tk.BooleanVar(value=True)
        self.shelf_ctg_auxiliary_enable_var = tk.BooleanVar(value=False)
        self.shelf_quality_guard_enable_var = tk.BooleanVar(value=False)
        self.shelf_quality_guard_min_coverage_ratio_var = tk.DoubleVar(value=0.90)
        self.shelf_row_endpoint_alignment_enable_var = tk.BooleanVar(value=True)
        self.shelf_node_obstacle_ratio_filter_enable_var = tk.BooleanVar(value=True)
        self.shelf_node_obstacle_ratio_threshold_var = tk.DoubleVar(value=0.45)
        self.isolated_jump_cleanup_enable_var = tk.BooleanVar(value=True)
        self.isolated_jump_distance_m_var = tk.DoubleVar(value=3.0)
        self.isolated_jump_max_points_var = tk.IntVar(value=3)
        self.isolated_jump_max_length_m_var = tk.DoubleVar(value=1.0)
        self.isolated_jump_reinsert_max_distance_m_var = tk.DoubleVar(value=1.0)
        self.isolated_jump_reinsert_improvement_ratio_var = tk.DoubleVar(value=0.8)

        self.step_var = tk.DoubleVar(value=0.5)
        self.contour_start_offset_var = tk.DoubleVar(value=0.3)
        self.contour_layer_gap_var = tk.DoubleVar(value=0.5)
        self.contour_layers_var = tk.IntVar(value=0)
        self.min_perimeter_factor_var = tk.DoubleVar(value=1.0)
        self.min_node_dist_factor_var = tk.DoubleVar(value=0.4)
        self.connection_dist_factor_var = tk.DoubleVar(value=2.5)
        self.gbnn_A_var = tk.DoubleVar(value=5.0)
        self.gbnn_B_var = tk.DoubleVar(value=1.0)
        self.gbnn_D_var = tk.DoubleVar(value=1.0)
        self.gbnn_E_var = tk.DoubleVar(value=100.0)
        self.gbnn_iters_var = tk.IntVar(value=80)
        self.gbnn_frontier_weight_var = tk.DoubleVar(value=0.3)
        self.gbnn_dist_weight_var = tk.DoubleVar(value=0.5)
        self.gbnn_turn_weight_var = tk.DoubleVar(value=0.5)
        self.gbnn_straight_weight_var = tk.DoubleVar(value=0.0)
        self.gbnn_zigzag_weight_var = tk.DoubleVar(value=0.0)
        self.gbnn_backtrack_enable_var = tk.BooleanVar(value=True)

        self.short_side_branch_var = tk.DoubleVar(value=2.0)
        self.free_node_min_clearance_var = tk.DoubleVar(value=0.35)
        self.intersection_merge_geodesic_var = tk.IntVar(value=20)
        self.junction_polygon_radius_var = tk.DoubleVar(value=10.0)
        self.turn_constraint_near_max_turn_deg_var = tk.DoubleVar(value=20.0)
        self.turn_constraint_neighbor_max_turn_deg_var = tk.DoubleVar(value=100.0)
        self.turn_constraint_fallback_max_turn_deg_var = tk.DoubleVar(value=135.0)
        self.turn_constraint_fallback_relax_dist_m_var = tk.DoubleVar(value=2.0)
        self.layer_bridge_enable_var = tk.BooleanVar(value=True)
        self.straight_ahead_weight_var = tk.DoubleVar(value=1.5)
        self.turn_penalty_weight_var = tk.DoubleVar(value=2.0)
        self.lateral_weight_var = tk.DoubleVar(value=0.8)
        self.max_turn_deg_var = tk.DoubleVar(value=90.0)
        self.jump_bridge_interpolations_var = tk.IntVar(value=2)
        self.turn_weight_var = tk.DoubleVar(value=0.0)
        self.boustrophedon_turn_weight_var = tk.DoubleVar(value=0.0)
        self.show_advanced_var = tk.BooleanVar(value=False)

        self._comparison_vars: dict[str, tk.BooleanVar] = {}
        for cm in COMPARISON_CANDIDATES:
            self._comparison_vars[cm] = tk.BooleanVar(value=False)

        common_frame = tk.LabelFrame(
            master, text="通用参数",
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            font=FONTS["body_bold"], relief=tk.GROOVE, bd=1,
        )
        common_frame.grid(row=2, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=4)
        common_frame.columnconfigure(0, weight=1)
        common_frame.columnconfigure(1, weight=1)
        common_left = tk.Frame(common_frame, bg=COLORS["bg_primary"])
        common_left.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 8))
        common_right = tk.Frame(common_frame, bg=COLORS["bg_primary"])
        common_right.grid(row=0, column=1, sticky=tk.NSEW)
        self._build_parameter_row(common_left, 0, "coverage_width_m", "覆盖宽度 (m):", self.coverage_width_var)
        self._build_parameter_row(common_left, 1, "robot_width_m", "机器人宽度 (m):", self.robot_width_var)
        self._build_parameter_row(common_right, 0, "open_kernel_m", "开运算核尺度 (m):", self.open_kernel_var)
        self._build_parameter_row(common_right, 1, "obstacle_expand_m", "障碍物膨胀 (m):", self.obstacle_expand_var)

        self.basic_frame = tk.LabelFrame(
            master, text="基础算法能量参数",
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            font=FONTS["body_bold"], relief=tk.GROOVE, bd=1,
        )
        self.basic_frame.grid(row=3, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=4)
        self.basic_frame.columnconfigure(0, weight=1)
        self.basic_frame.columnconfigure(1, weight=1)
        basic_left = tk.Frame(self.basic_frame, bg=COLORS["bg_primary"])
        basic_left.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 8))
        basic_right = tk.Frame(self.basic_frame, bg=COLORS["bg_primary"])
        basic_right.grid(row=0, column=1, sticky=tk.NSEW)
        basic_params = (
            ("straight_ahead_weight", "直行奖励权重:", self.straight_ahead_weight_var),
            ("turn_penalty_weight", "转向惩罚权重:", self.turn_penalty_weight_var),
            ("lateral_weight", "横切惩罚权重:", self.lateral_weight_var),
            ("max_turn_deg", "最大转角 (deg):", self.max_turn_deg_var),
            ("jump_bridge_interpolations", "桥接插值点数:", self.jump_bridge_interpolations_var),
        )
        b_split = (len(basic_params) + 1) // 2
        for row, (field_name, label, var) in enumerate(basic_params[:b_split]):
            self._build_parameter_row(basic_left, row, field_name, label, var)
        for row, (field_name, label, var) in enumerate(basic_params[b_split:]):
            self._build_parameter_row(basic_right, row, field_name, label, var)

        self.shelf_frame = tk.LabelFrame(
            master, text="ShelfAware 专属参数",
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            font=FONTS["body_bold"], relief=tk.GROOVE, bd=1,
        )
        self.shelf_frame.grid(row=3, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=4)
        self._build_parameter_row(self.shelf_frame, 0, "local_direction_enable", "启用局部方向图:", self.local_direction_enable_var, field_type="bool")
        self._build_parameter_row(self.shelf_frame, 1, "local_direction_energy_weight", "局部方向权重:", self.local_direction_energy_weight_var)
        self._build_parameter_row(self.shelf_frame, 2, "fallback_jump_weight", "长跳惩罚权重:", self.fallback_jump_weight_var)
        self._build_parameter_row(self.shelf_frame, 3, "history_clearance_weight", "历史轨迹净空权重:", self.history_clearance_weight_var)

        self.contour_frame = tk.LabelFrame(
            master, text="等高线参数",
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            font=FONTS["body_bold"], relief=tk.GROOVE, bd=1,
        )
        self.contour_frame.grid(row=4, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=4)
        self.contour_frame.columnconfigure(0, weight=1)
        self.contour_frame.columnconfigure(1, weight=1)
        contour_left = tk.Frame(self.contour_frame, bg=COLORS["bg_primary"])
        contour_left.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 8))
        contour_right = tk.Frame(self.contour_frame, bg=COLORS["bg_primary"])
        contour_right.grid(row=0, column=1, sticky=tk.NSEW)
        contour_params = (
            ("step", "步长 (m):", self.step_var),
            ("contour_start_offset", "等高线起始偏移 (m):", self.contour_start_offset_var),
            ("contour_layer_gap", "等高线层间距 (m):", self.contour_layer_gap_var),
            ("contour_layers", "等高线层数 (0=自适应):", self.contour_layers_var),
            ("min_perimeter_factor", "最小周长倍率:", self.min_perimeter_factor_var),
            ("min_node_dist_factor", "最小节点间距倍率:", self.min_node_dist_factor_var),
            ("connection_dist_factor", "连接距离倍率:", self.connection_dist_factor_var),
        )
        c_split = (len(contour_params) + 1) // 2
        for row, (field_name, label, var) in enumerate(contour_params[:c_split]):
            self._build_parameter_row(contour_left, row, field_name, label, var)
        for row, (field_name, label, var) in enumerate(contour_params[c_split:]):
            self._build_parameter_row(contour_right, row, field_name, label, var)

        self.gbnn_frame = tk.LabelFrame(
            master, text="GBNN 专属参数",
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            font=FONTS["body_bold"], relief=tk.GROOVE, bd=1,
        )
        self.gbnn_frame.grid(row=5, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=4)
        gbnn_left = tk.Frame(self.gbnn_frame, bg=COLORS["bg_primary"])
        gbnn_left.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 8))
        gbnn_right = tk.Frame(self.gbnn_frame, bg=COLORS["bg_primary"])
        gbnn_right.grid(row=0, column=1, sticky=tk.NSEW)
        gbnn_params = (
            ("gbnn_frontier_weight", "前沿权重:", self.gbnn_frontier_weight_var),
            ("gbnn_dist_weight", "距离权重:", self.gbnn_dist_weight_var),
            ("gbnn_turn_weight", "转弯权重:", self.gbnn_turn_weight_var),
            ("gbnn_straight_weight", "直线偏好:", self.gbnn_straight_weight_var),
            ("gbnn_zigzag_weight", "蛇形换行:", self.gbnn_zigzag_weight_var),
            ("gbnn_A", "GBNN A:", self.gbnn_A_var),
            ("gbnn_B", "GBNN B:", self.gbnn_B_var),
            ("gbnn_D", "GBNN D:", self.gbnn_D_var),
            ("gbnn_E", "GBNN E:", self.gbnn_E_var),
            ("gbnn_iters", "GBNN 迭代次数:", self.gbnn_iters_var),
        )
        split = (len(gbnn_params) + 1) // 2
        for row, (field_name, label, var) in enumerate(gbnn_params[:split]):
            self._build_parameter_row(gbnn_left, row, field_name, label, var)
        for row, (field_name, label, var) in enumerate(gbnn_params[split:]):
            self._build_parameter_row(gbnn_right, row, field_name, label, var)
        self._build_parameter_row(
            self.gbnn_frame, split, "gbnn_backtrack_enable",
            "启用回溯，死胡同时跳向全局最近未覆盖节点（不勾选则仅在邻居内选择）:",
            self.gbnn_backtrack_enable_var, field_type="bool",
        )

        self.cstar_frame = tk.LabelFrame(
            master, text="C* 算法专属参数",
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            font=FONTS["body_bold"], relief=tk.GROOVE, bd=1,
        )
        self.cstar_frame.grid(row=6, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=4)
        self._build_parameter_row(self.cstar_frame, 0, "layer_bridge_enable", "层间 A* 桥接:", self.layer_bridge_enable_var, field_type="bool")
        self._build_parameter_row(self.cstar_frame, 1, "jump_bridge_interpolations", "桥接插值点数:", self.jump_bridge_interpolations_var)
        self._build_parameter_row(self.cstar_frame, 2, "turn_weight", "转向惩罚权重:", self.turn_weight_var)
        self._build_parameter_row(self.cstar_frame, 3, "boustrophedon_turn_weight", "牛耕直线权重:", self.boustrophedon_turn_weight_var)

        self.ctg_frame = tk.LabelFrame(
            master, text="通道拓扑图专属参数",
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            font=FONTS["body_bold"], relief=tk.GROOVE, bd=1,
        )
        self.ctg_frame.grid(row=7, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=4)
        self._build_parameter_row(self.ctg_frame, 0, "short_side_branch_m", "短侧枝阈值 (m):", self.short_side_branch_var)
        self._build_parameter_row(self.ctg_frame, 1, "free_node_min_clearance_m", "自由节点最小净空 (m):", self.free_node_min_clearance_var)

        toggle_frame = tk.Frame(master, bg=COLORS["bg_primary"])
        toggle_frame.grid(row=9, column=0, columnspan=2, sticky=tk.W, padx=8, pady=(4, 2))
        tk.Checkbutton(
            toggle_frame, text="显示高级参数",
            variable=self.show_advanced_var,
            command=self._update_parameter_visibility,
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            activebackground=COLORS["bg_primary"],
            selectcolor=COLORS["bg_surface"],
            font=FONTS["body"],
        ).pack(side=tk.LEFT)

        self.advanced_frame = tk.LabelFrame(
            master, text="高级参数",
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            font=FONTS["body_bold"], relief=tk.GROOVE, bd=1,
        )
        self.advanced_frame.grid(row=9, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=4)
        self.advanced_frame.columnconfigure(0, weight=1)
        self.advanced_frame.columnconfigure(1, weight=1)
        advanced_left = tk.Frame(self.advanced_frame, bg=COLORS["bg_primary"])
        advanced_left.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 8))
        advanced_right = tk.Frame(self.advanced_frame, bg=COLORS["bg_primary"])
        advanced_right.grid(row=0, column=1, sticky=tk.NSEW)
        advanced_fields = (
            ("auto_rotate", "自动旋转对齐:", self.auto_rotate_var, "bool"),
            ("write_artifacts", "写出调试证据:", self.write_artifacts_var, "bool"),
            ("turn_constraint_enable", "启用转角约束:", self.turn_constraint_var, "bool"),
            ("turn_constraint_near_dist_m", "近邻判定距离 (m):", self.turn_constraint_near_dist_m_var, "entry"),
            ("turn_constraint_near_max_turn_deg", "近邻最大转角 (deg):", self.turn_constraint_near_max_turn_deg_var, "entry"),
            ("turn_constraint_neighbor_max_turn_deg", "邻接最大转角 (deg):", self.turn_constraint_neighbor_max_turn_deg_var, "entry"),
            ("turn_constraint_fallback_max_turn_deg", "回退最大转角 (deg):", self.turn_constraint_fallback_max_turn_deg_var, "entry"),
            ("turn_constraint_fallback_relax_dist_m", "回退放宽距离 (m):", self.turn_constraint_fallback_relax_dist_m_var, "entry"),
            ("shelf_ctg_auxiliary_enable", "启用 CTG territory/junction 辅助:", self.shelf_ctg_auxiliary_enable_var, "bool"),
            ("shelf_quality_guard_enable", "启用质量守卫:", self.shelf_quality_guard_enable_var, "bool"),
            ("shelf_quality_guard_min_coverage_ratio", "质量守卫最小覆盖率:", self.shelf_quality_guard_min_coverage_ratio_var, "entry"),
            ("shelf_row_endpoint_alignment_enable", "启用行段首尾对齐:", self.shelf_row_endpoint_alignment_enable_var, "bool"),
            ("shelf_node_obstacle_ratio_filter_enable", "启用节点障碍比例过滤:", self.shelf_node_obstacle_ratio_filter_enable_var, "bool"),
            ("shelf_node_obstacle_ratio_threshold", "节点障碍比例阈值:", self.shelf_node_obstacle_ratio_threshold_var, "entry"),
            ("local_lateral_weight", "横切惩罚权重:", self.local_lateral_weight_var, "entry"),
            ("split_jump_dist_factor", "长跳切段阈值倍率:", self.split_jump_dist_factor_var, "entry"),
            ("allow_revisit_bridge", "启用重复回接:", self.allow_revisit_bridge_var, "bool"),
            ("isolated_jump_cleanup_enable", "启用孤立跳变点治理:", self.isolated_jump_cleanup_enable_var, "bool"),
            ("isolated_jump_distance_m", "孤立跳变判定距离 (m):", self.isolated_jump_distance_m_var, "entry"),
            ("isolated_jump_max_points", "孤立段最大点数:", self.isolated_jump_max_points_var, "entry"),
            ("isolated_jump_max_length_m", "孤立段最大长度 (m):", self.isolated_jump_max_length_m_var, "entry"),
            ("isolated_jump_reinsert_max_distance_m", "回插最大邻近距离 (m):", self.isolated_jump_reinsert_max_distance_m_var, "entry"),
            ("isolated_jump_reinsert_improvement_ratio", "回插改善比例:", self.isolated_jump_reinsert_improvement_ratio_var, "entry"),
            ("intersection_merge_geodesic_px", "交汇合并 geodesic (px):", self.intersection_merge_geodesic_var, "entry"),
            ("junction_polygon_radius_px", "交汇 polygon 半径 (px):", self.junction_polygon_radius_var, "entry"),
        )
        split_index = (len(advanced_fields) + 1) // 2
        for row, (field_name, label, variable, field_type) in enumerate(advanced_fields[:split_index]):
            self._build_parameter_row(advanced_left, row, field_name, label, variable, field_type=field_type)
        for row, (field_name, label, variable, field_type) in enumerate(advanced_fields[split_index:]):
            self._build_parameter_row(advanced_right, row, field_name, label, variable, field_type=field_type)

        comparison_frame = tk.LabelFrame(
            master, text="批量对比（可选）",
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            font=FONTS["body_bold"], relief=tk.GROOVE, bd=1,
        )
        comparison_frame.grid(row=10, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=4)
        label_map = {m: n for n, m in UI_PLANNER_CHOICES}
        for ci, cm in enumerate(COMPARISON_CANDIDATES):
            cb = tk.Checkbutton(
                comparison_frame, text=label_map.get(cm, cm),
                variable=self._comparison_vars[cm],
                bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
                activebackground=COLORS["bg_primary"],
                activeforeground=COLORS["fg_bright"],
                selectcolor=COLORS["bg_surface"],
                font=FONTS["body"],
            )
            cb.grid(row=0, column=ci, sticky=tk.W, padx=(8, 0))
            tip = "勾选后，主规划器运行完成自动追加该规划器的对比结果。"
            _ToolTip(cb, tip)

        tk.Label(
            master,
            text="说明: auto 默认只展示通用参数；切换到具体算法后显示对应专属参数，高级参数折叠展示。",
            bg=COLORS["bg_primary"], fg=COLORS["fg_muted"],
            font=FONTS["caption"],
        ).grid(row=11, column=0, columnspan=2, sticky=tk.W, padx=8, pady=(4, 3))

        self._apply_values(self._initial_values)
        return None

    def _build_parameter_row(self, parent, row, field_name, label, variable, *, field_type="entry"):
        row_frame = tk.Frame(parent, bg=COLORS["bg_primary"])
        row_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=2)
        row_frame.columnconfigure(1, weight=1)
        if field_type == "bool":
            tk.Checkbutton(
                row_frame, text=label, variable=variable,
                bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
                activebackground=COLORS["bg_primary"],
                activeforeground=COLORS["fg_bright"],
                selectcolor=COLORS["bg_surface"],
                font=FONTS["body"],
            ).grid(row=0, column=0, columnspan=2, sticky=tk.W)
        else:
            tk.Label(
                row_frame, text=label,
                bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
                font=FONTS["body"],
            ).grid(row=0, column=0, sticky=tk.W)
            tk.Entry(
                row_frame, textvariable=variable, width=12,
                bg=COLORS["bg_surface"], fg=COLORS["fg_bright"],
                insertbackground=COLORS["fg_primary"],
                relief=tk.FLAT, bd=1, font=FONTS["body"],
            ).grid(row=0, column=1, sticky=tk.W, padx=(8, 0))
        tip = TOOLTIP_MAP.get(field_name)
        if tip:
            for child in row_frame.winfo_children():
                if isinstance(child, (tk.Label, tk.Checkbutton, tk.Entry)):
                    _ToolTip(child, tip)
        self._field_rows[field_name] = row_frame

    def _set_fields_visible(self, field_names, visible):
        for field_name in field_names:
            row = self._field_rows.get(field_name)
            if row is None:
                continue
            if visible:
                row.grid()
            else:
                row.grid_remove()

    def _update_parameter_visibility(self):
        planner_mode = self.planner_mode_var.get()
        self.mode_override_notice_var.set(build_planner_mode_override_notice(planner_mode))
        groups = resolve_visible_parameter_groups(planner_mode)
        has_contour = bool(groups["contour"])
        has_gbnn_score = bool(groups["gbnn_score"])
        has_gbnn_dynamics = bool(groups["gbnn_dynamics"])
        has_cstar = bool(groups["cstar"])
        has_shelf = bool(groups["shelf"])
        has_ctg = bool(groups["ctg"])
        has_basic = bool(groups["basic_energy"])
        try:
            if has_basic:
                self.basic_frame.grid()
            else:
                self.basic_frame.grid_remove()
            if has_contour:
                self.contour_frame.grid()
            else:
                self.contour_frame.grid_remove()
            has_gbnn = has_gbnn_score or has_gbnn_dynamics
            if has_gbnn:
                self.gbnn_frame.grid()
            else:
                self.gbnn_frame.grid_remove()
            if has_cstar:
                self.cstar_frame.grid()
            else:
                self.cstar_frame.grid_remove()
            if has_shelf:
                self.shelf_frame.grid()
            else:
                self.shelf_frame.grid_remove()
            if has_ctg:
                self.ctg_frame.grid()
            else:
                self.ctg_frame.grid_remove()

            self._set_fields_visible(SHELF_PARAMETER_FIELDS, has_shelf)
            self._set_fields_visible(CTG_PARAMETER_FIELDS, has_ctg)
            self._set_fields_visible(CONTOUR_LEVEL_FIELDS, has_contour)
            self._set_fields_visible(GBNN_SCORE_FIELDS, has_gbnn_score)
            self._set_fields_visible(GBNN_DYNAMICS_FIELDS, has_gbnn_dynamics)
            self._set_fields_visible(CSTAR_PARAMETER_FIELDS, has_cstar)

            show_advanced = bool(self.show_advanced_var.get())
            if show_advanced:
                self.advanced_frame.grid()
            else:
                self.advanced_frame.grid_remove()

            self._set_fields_visible(SHARED_ADVANCED_FIELDS, show_advanced)
            self._set_fields_visible(TURN_CONSTRAINT_FIELDS, show_advanced and bool(groups["turn_constraint"]))
            self._set_fields_visible(SHELF_ADVANCED_FIELDS, False)
            self._set_fields_visible(groups["shelf_advanced"], show_advanced and has_shelf)
            self._set_fields_visible(
                SHELF_QUALITY_GUARD_FIELDS,
                show_advanced and bool(groups["shelf_quality_guard"]),
            )
            self._set_fields_visible(CTG_ADVANCED_FIELDS, show_advanced and has_ctg)
            self._set_fields_visible(BASIC_ENERGY_FIELDS, show_advanced and has_basic)
        except tk.TclError:
            pass

    def _snapshot_values(self) -> dict[str, object]:
        return {
            field_name: getattr(self, variable_name).get()
            for field_name, variable_name in DIALOG_VARIABLE_NAMES.items()
        }

    def _apply_values(self, values):
        merged = merge_coverage_dialog_values(values)
        for field_name, variable_name in DIALOG_VARIABLE_NAMES.items():
            getattr(self, variable_name).set(merged[field_name])
        self._update_parameter_visibility()

    def _reset_to_defaults(self):
        self._apply_values(coverage_dialog_default_values())

    def buttonbox(self):
        box = tk.Frame(self, bg=COLORS["bg_primary"])
        tk.Button(
            box, text="生成", width=8, command=self.ok, default=tk.ACTIVE,
            bg=COLORS["accent"], fg=COLORS["fg_on_accent"],
            activebackground=COLORS["accent_hover"],
            relief=tk.FLAT, bd=0, font=FONTS["button"], cursor="hand2",
        ).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(
            box, text="恢复默认值", width=10, command=self._reset_to_defaults,
            bg=COLORS["bg_surface"], fg=COLORS["fg_primary"],
            activebackground=COLORS["bg_hover"],
            relief=tk.FLAT, bd=0, font=FONTS["button"], cursor="hand2",
        ).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(
            box, text="取消", width=8, command=self.cancel,
            bg=COLORS["bg_surface"], fg=COLORS["fg_primary"],
            activebackground=COLORS["bg_hover"],
            relief=tk.FLAT, bd=0, font=FONTS["button"], cursor="hand2",
        ).pack(side=tk.LEFT, padx=5, pady=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        box.pack()

    def apply(self):
        self.result_values = self._snapshot_values()
        self.result_config = coverage_dialog_config_from_values(self.result_values)
        selected = tuple(cm for cm, v in self._comparison_vars.items() if v.get())
        if selected:
            object.__setattr__(self.result_config, "comparison_modes", selected)


def show_coverage_dialog(parent, *, input_summary=None) -> CoveragePlannerConfig | None:
    """显示覆盖路径参数对话框

    Returns:
        CoveragePlannerConfig 如果用户点击"生成"，否则 None
    """
    initial_values = getattr(parent, "_last_coverage_dialog_values", None)
    dlg = CoverageDialog(parent, input_summary=input_summary, initial_values=initial_values)
    if dlg.result_config is not None and dlg.result_values is not None:
        parent._last_coverage_dialog_values = merge_coverage_dialog_values(dlg.result_values)
    return dlg.result_config


# ---------------------------------------------------------------------------
# Room 连接顺序重排对话框
# ---------------------------------------------------------------------------

class RoomOrderDialog(tk.Toplevel):
    """拖拽式调整 Room 路径连接顺序的对话框。"""

    def __init__(self, parent, room_ids):
        super().__init__(parent)
        self.title("Room 路径连接顺序")
        self.resizable(False, False)
        self.result = None  # 用户确认后为新的 room_ids 列表

        self.room_ids = list(room_ids)

        # --- 标题 ---
        tk.Label(
            self, text="调整 Room 路径连接顺序（上移/下移）",
            bg=COLORS["bg_primary"], fg=COLORS["fg_primary"],
            font=FONTS["body"], pady=8,
        ).pack()

        # --- 主体: Listbox + 按钮 ---
        body = tk.Frame(self, bg=COLORS["bg_primary"])
        body.pack(padx=12, pady=(0, 8))

        self.listbox = tk.Listbox(
            body, width=20, height=min(len(room_ids), 15),
            bg=COLORS.get("bg_surface", COLORS["bg_primary"]),
            fg=COLORS["fg_primary"],
            selectbackground=COLORS.get("bg_active", "#4a90d9"),
            selectforeground=COLORS.get("fg_on_accent", "#ffffff"),
            font=FONTS["body"],
            activestyle="none",
            bd=1, relief=tk.SOLID,
        )
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for rid in self.room_ids:
            self.listbox.insert(tk.END, f"Room {rid}")

        # 双击也能上移
        self.listbox.bind("<Double-Button-1>", lambda e: self._move_up())

        btn_frame = tk.Frame(body, bg=COLORS["bg_primary"])
        btn_frame.pack(side=tk.LEFT, padx=(8, 0))

        self._btn_up = tk.Button(
            btn_frame, text="▲ 上移", width=8,
            bg=COLORS.get("bg_surface", COLORS["bg_primary"]),
            fg=COLORS["fg_primary"],
            activebackground=COLORS.get("bg_hover", "#e0e0e0"),
            relief=tk.FLAT, font=FONTS["button"], cursor="hand2",
            command=self._move_up,
        )
        self._btn_up.pack(pady=(0, 4))

        self._btn_down = tk.Button(
            btn_frame, text="▼ 下移", width=8,
            bg=COLORS.get("bg_surface", COLORS["bg_primary"]),
            fg=COLORS["fg_primary"],
            activebackground=COLORS.get("bg_hover", "#e0e0e0"),
            relief=tk.FLAT, font=FONTS["button"], cursor="hand2",
            command=self._move_down,
        )
        self._btn_down.pack()

        # --- 底部按钮 ---
        bottom = tk.Frame(self, bg=COLORS["bg_primary"])
        bottom.pack(fill=tk.X, padx=12, pady=8)

        tk.Button(
            bottom, text="确定", width=8,
            bg=COLORS.get("bg_active", "#4a90d9"),
            fg=COLORS.get("fg_on_accent", "#ffffff"),
            activebackground=COLORS.get("bg_hover", "#e0e0e0"),
            relief=tk.FLAT, font=FONTS["button"], cursor="hand2",
            command=self._on_ok,
        ).pack(side=tk.RIGHT, padx=(4, 0))

        tk.Button(
            bottom, text="取消", width=8,
            bg=COLORS.get("bg_surface", COLORS["bg_primary"]),
            fg=COLORS["fg_primary"],
            activebackground=COLORS.get("bg_hover", "#e0e0e0"),
            relief=tk.FLAT, font=FONTS["button"], cursor="hand2",
            command=self._on_cancel,
        ).pack(side=tk.RIGHT)

        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.wait_window()

    def _move_up(self):
        sel = self.listbox.curselection()
        if not sel or sel[0] == 0:
            return
        idx = sel[0]
        self.room_ids[idx - 1], self.room_ids[idx] = self.room_ids[idx], self.room_ids[idx - 1]
        text = self.listbox.get(idx)
        self.listbox.delete(idx)
        self.listbox.insert(idx - 1, text)
        self.listbox.selection_set(idx - 1)
        self.listbox.see(idx - 1)

    def _move_down(self):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self.room_ids) - 1:
            return
        idx = sel[0]
        self.room_ids[idx], self.room_ids[idx + 1] = self.room_ids[idx + 1], self.room_ids[idx]
        text = self.listbox.get(idx)
        self.listbox.delete(idx)
        self.listbox.insert(idx + 1, text)
        self.listbox.selection_set(idx + 1)
        self.listbox.see(idx + 1)

    def _on_ok(self):
        self.result = list(self.room_ids)
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()
