"""
覆盖路径参数配置对话框
"""

from pathlib import Path
import tkinter as tk
from tkinter import simpledialog

from algorithms.coverage_planning.modes import (
    AUTO_MODE,
    BASIC_MODE,
    CHANNEL_TOPOLOGY_GRAPH_MODE,
    SHELF_AWARE_MODE,
    SHELF_AWARE_TURN_COST_MODE,
    UI_PLANNER_MODES,
)
from algorithms.coverage_planning.profiles import (
    coverage_planner_mode_default_overrides,
    coverage_planner_profile_metadata,
)
from ..adapters.coverage_planning_adapter import CoveragePlannerConfig

UI_PLANNER_CHOICES = (
    ("自动选择", AUTO_MODE),
    ("基础算法", BASIC_MODE),
    ("shelfAware", SHELF_AWARE_MODE),
    ("ShelfAware+TurnCost", SHELF_AWARE_TURN_COST_MODE),
    ("通道拓扑图", CHANNEL_TOPOLOGY_GRAPH_MODE),
)
assert tuple(value for _, value in UI_PLANNER_CHOICES) == UI_PLANNER_MODES

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

DIALOG_CONFIG_FIELDS = (
    "planner_mode",
    *COMMON_PARAMETER_FIELDS,
    *SHARED_ADVANCED_FIELDS,
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
        "shared_advanced": SHARED_ADVANCED_FIELDS,
        "turn_constraint": (),
        "shelf": (),
        "shelf_advanced": (),
        "shelf_quality_guard": (),
        "ctg": (),
        "ctg_advanced": (),
    }
    if mode in {BASIC_MODE, *SHELF_AWARE_DIALOG_MODES}:
        groups["turn_constraint"] = TURN_CONSTRAINT_FIELDS
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
        summary_frame = tk.LabelFrame(master, text="正式输入摘要")
        summary_frame.grid(row=0, column=0, columnspan=2, sticky=tk.EW, padx=5, pady=(5, 3))
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
            tk.Label(summary_frame, text=label).grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
            tk.Label(summary_frame, text=value).grid(row=row, column=1, sticky=tk.W, padx=5, pady=2)

        mode_frame = tk.LabelFrame(master, text="算法选择")
        mode_frame.grid(row=1, column=0, columnspan=2, sticky=tk.EW, padx=5, pady=3)
        self.planner_mode_var = tk.StringVar(value=AUTO_MODE)
        for index, (label, value) in enumerate(UI_PLANNER_CHOICES):
            tk.Radiobutton(
                mode_frame,
                text=label,
                variable=self.planner_mode_var,
                value=value,
                command=self._update_parameter_visibility,
            ).pack(side=tk.LEFT, padx=(8, 0) if index else 0)
        self.mode_override_notice_var = tk.StringVar(value="")
        tk.Label(
            mode_frame,
            textvariable=self.mode_override_notice_var,
            anchor=tk.W,
            justify=tk.LEFT,
            fg="#555555",
            wraplength=520,
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

        self.short_side_branch_var = tk.DoubleVar(value=2.0)
        self.free_node_min_clearance_var = tk.DoubleVar(value=0.35)
        self.intersection_merge_geodesic_var = tk.IntVar(value=20)
        self.junction_polygon_radius_var = tk.DoubleVar(value=10.0)
        self.turn_constraint_near_max_turn_deg_var = tk.DoubleVar(value=20.0)
        self.turn_constraint_neighbor_max_turn_deg_var = tk.DoubleVar(value=100.0)
        self.turn_constraint_fallback_max_turn_deg_var = tk.DoubleVar(value=135.0)
        self.turn_constraint_fallback_relax_dist_m_var = tk.DoubleVar(value=2.0)
        self.show_advanced_var = tk.BooleanVar(value=False)

        common_frame = tk.LabelFrame(master, text="通用参数")
        common_frame.grid(row=2, column=0, columnspan=2, sticky=tk.EW, padx=5, pady=3)
        common_frame.columnconfigure(0, weight=1)
        common_frame.columnconfigure(1, weight=1)
        common_left = tk.Frame(common_frame)
        common_left.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 8))
        common_right = tk.Frame(common_frame)
        common_right.grid(row=0, column=1, sticky=tk.NSEW)
        self._build_parameter_row(common_left, 0, "coverage_width_m", "覆盖宽度 (m):", self.coverage_width_var)
        self._build_parameter_row(common_left, 1, "robot_width_m", "机器人宽度 (m):", self.robot_width_var)
        self._build_parameter_row(common_right, 0, "open_kernel_m", "开运算核尺度 (m):", self.open_kernel_var)
        self._build_parameter_row(common_right, 1, "obstacle_expand_m", "障碍物膨胀 (m):", self.obstacle_expand_var)

        self.shelf_frame = tk.LabelFrame(master, text="ShelfAware 专属参数")
        self.shelf_frame.grid(row=3, column=0, columnspan=2, sticky=tk.EW, padx=5, pady=3)
        self._build_parameter_row(self.shelf_frame, 0, "local_direction_enable", "启用局部方向图:", self.local_direction_enable_var, field_type="bool")
        self._build_parameter_row(self.shelf_frame, 1, "local_direction_energy_weight", "局部方向权重:", self.local_direction_energy_weight_var)
        self._build_parameter_row(self.shelf_frame, 2, "fallback_jump_weight", "长跳惩罚权重:", self.fallback_jump_weight_var)
        self._build_parameter_row(self.shelf_frame, 3, "history_clearance_weight", "历史轨迹净空权重:", self.history_clearance_weight_var)

        self.ctg_frame = tk.LabelFrame(master, text="通道拓扑图专属参数")
        self.ctg_frame.grid(row=4, column=0, columnspan=2, sticky=tk.EW, padx=5, pady=3)
        self._build_parameter_row(self.ctg_frame, 0, "short_side_branch_m", "短侧枝阈值 (m):", self.short_side_branch_var)
        self._build_parameter_row(self.ctg_frame, 1, "free_node_min_clearance_m", "自由节点最小净空 (m):", self.free_node_min_clearance_var)

        toggle_frame = tk.Frame(master)
        toggle_frame.grid(row=5, column=0, columnspan=2, sticky=tk.W, padx=5, pady=(4, 2))
        tk.Checkbutton(
            toggle_frame,
            text="显示高级参数",
            variable=self.show_advanced_var,
            command=self._update_parameter_visibility,
        ).pack(side=tk.LEFT)

        self.advanced_frame = tk.LabelFrame(master, text="高级参数")
        self.advanced_frame.grid(row=6, column=0, columnspan=2, sticky=tk.EW, padx=5, pady=3)
        self.advanced_frame.columnconfigure(0, weight=1)
        self.advanced_frame.columnconfigure(1, weight=1)
        advanced_left = tk.Frame(self.advanced_frame)
        advanced_left.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 8))
        advanced_right = tk.Frame(self.advanced_frame)
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

        tk.Label(
            master,
            text="说明: auto 默认只展示通用参数；切换到具体算法后显示对应专属参数，高级参数折叠展示。",
        ).grid(row=7, column=0, columnspan=2, sticky=tk.W, padx=5, pady=(4, 3))

        self._apply_values(self._initial_values)
        return None

    def _build_parameter_row(self, parent, row, field_name, label, variable, *, field_type="entry"):
        row_frame = tk.Frame(parent)
        row_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, padx=5, pady=2)
        row_frame.columnconfigure(1, weight=1)
        if field_type == "bool":
            tk.Checkbutton(row_frame, text=label, variable=variable).grid(row=0, column=0, columnspan=2, sticky=tk.W)
        else:
            tk.Label(row_frame, text=label).grid(row=0, column=0, sticky=tk.W)
            tk.Entry(row_frame, textvariable=variable, width=12).grid(row=0, column=1, sticky=tk.W, padx=(8, 0))
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
        has_shelf = bool(groups["shelf"])
        has_ctg = bool(groups["ctg"])
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
        box = tk.Frame(self)
        tk.Button(box, text="生成", width=8, command=self.ok, default=tk.ACTIVE).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(box, text="恢复默认值", width=10, command=self._reset_to_defaults).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(box, text="取消", width=8, command=self.cancel).pack(side=tk.LEFT, padx=5, pady=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        box.pack()

    def apply(self):
        self.result_values = self._snapshot_values()
        self.result_config = coverage_dialog_config_from_values(self.result_values)


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
