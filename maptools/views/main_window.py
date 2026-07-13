import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import os
import math
import json
import shutil
import subprocess
import sys
from pathlib import Path
from .map_canvas import MapCanvas
from .layout_components import Toolbar, Sidebar
from .theme import COLORS, FONTS, SPACING, apply_theme
from ..models.map_data import MapData
from ..models.annotations import Annotations, ConstraintSegment, DerivedConstraintRegion
from ..models.project import ProjectManager
from ..controllers.tool_manager import ToolManager
from ..controllers.command_manager import CommandManager
from ..tools.pan_tool import PanTool

from ..tools.raster_tools import BrushTool, EraserTool, StraightLineTool
from ..tools.vector_tools import PolygonTool, LineTool, StationTool
from ..tools.pass_only_tool import PassOnlyTool
from ..tools.area_label_tool import AreaLabelTool
from ..tools.path_tools import PathSelectTool, PathPolygonSelectTool, PathAddTool, PathDrawTool, PathLineTool
from ..tools.origin_tool import OriginTool
from ..tools.crop_tool import CropTool
from ..tools.select_tool import SelectTool
from ..utils.export import Exporter
from ..utils.constraint_styles import constraint_base_color
from ..views.dialogs import RotationDialog, CropInfoDialog
from ..controllers.commands.transform_command import TransformCommand
from ..controllers.commands.update_constraint_segments_command import UpdateConstraintSegmentsCommand
from ..controllers.commands.update_constraint_region_truth_command import UpdateConstraintRegionTruthCommand

from ..adapters.coverage_planning_adapter import (
    CoveragePlanningRequest,
    preprocess_total_map,
    run_formal_planner_request,
    route_coverage_plan,
    run_channel_topology_graph_adapter,
)
from .coverage_dialog import build_coverage_input_summary, show_coverage_dialog
from ..utils.coverage_repo_import import detect_yaml_kind, import_area_labels_json, import_coverage_repo
from ..utils.coverage_repo_export import (
    build_area_region_mask,
    build_selected_area_planning_map,
    build_total_free_map,
    export_coverage_repo,
    repair_path_rooms_from_area_labels,
    run_export_preflight,
)
from ..utils.coverage_planner_params import (
    COVERAGE_PLANNER_PARAMS_FILENAME,
    coverage_planner_params_path,
    load_coverage_planner_params,
    save_coverage_planner_params,
)
from ..utils.coverage_start_points import (
    COVERAGE_START_POINTS_FILENAME,
    area_label_fingerprint,
    load_coverage_start_points,
    save_coverage_start_points,
    valid_start_point_for_area,
)
from ..utils.room_identity import (
    area_room_id,
    normalize_and_validate_area_room_ids,
    set_area_room_id,
    validate_room_id,
    validate_unique_area_room_ids,
)
from ..models.coverage_path import CoveragePathManager, PathParser
import cv2
import numpy as np

from algorithms.coverage_planning.modes import (
    AUTO_MODE,
    BASIC_MODE,
    CHANNEL_TOPOLOGY_GRAPH_MODE,
)
from algorithms.coverage_planning.contracts import build_readable_diagnostics_summary
import copy
from ..utils.free_space_components import (
    FREE_SPACE_COMPONENT_COLOR_HEX,
    extract_component_polygon_world,
)
from ..utils.free_space_region_target import (
    FreeSpaceRegionTarget,
    component_key_from_bbox_mask,
    component_object_id,
    derived_region_from_target,
    target_from_derived_region,
    target_from_free_component,
    truth_matches_target,
)
from ..utils.unknown_regions import (
    analyze_unknown_regions,
    build_unknown_forbidden_regions,
    compact_unknown_forbidden_regions,
    is_unknown_region,
)


def _diagnostics_readable_summary(diagnostics) -> dict:
    if diagnostics is None:
        return {}
    if hasattr(diagnostics, "to_readable_summary_dict"):
        return dict(diagnostics.to_readable_summary_dict())
    if hasattr(diagnostics, "to_summary_dict"):
        payload = dict(diagnostics.to_summary_dict())
        readable = payload.get("readable_summary", {})
        if isinstance(readable, dict) and str(readable.get("status_line", "") or "").strip():
            return dict(readable)
        return build_readable_diagnostics_summary(payload)
    return {}


def build_routing_summary(diagnostics) -> str:
    if diagnostics is None:
        return ""
    readable_summary = _diagnostics_readable_summary(diagnostics)
    status_line = str(readable_summary.get("status_line", "") or "").strip()
    if status_line:
        return status_line
    return ""


def build_routing_detail_lines(diagnostics) -> tuple[str, ...]:
    """Return table-like diagnostic detail lines for UI/export drill-down."""

    if diagnostics is None:
        return ()
    readable_summary = _diagnostics_readable_summary(diagnostics)
    sections = readable_summary.get("detail_sections", ())
    if not isinstance(sections, (list, tuple)):
        return ()
    lines: list[str] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        label = str(section.get("label", "") or section.get("key", "") or "").strip()
        rows = section.get("rows", ())
        if not label or not isinstance(rows, (list, tuple)):
            continue
        row_parts = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_label = str(row.get("label", "") or row.get("key", "") or "").strip()
            value = str(row.get("value", "") or "").strip()
            if row_label and value:
                row_parts.append(f"{row_label}={value}")
        if row_parts:
            lines.append(f"{label}: {'; '.join(row_parts)}")
    return tuple(lines)


def build_routing_artifact_locations(diagnostics) -> tuple[dict[str, str], ...]:
    """Return UI-openable artifact locations from the shared readable diagnostics."""

    if diagnostics is None:
        return ()
    readable_summary = _diagnostics_readable_summary(diagnostics)
    sections = readable_summary.get("detail_sections", ())
    if not isinstance(sections, (list, tuple)):
        return ()
    locations: list[dict[str, str]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_key = str(section.get("key", "") or "")
        if section_key not in {"profile", "artifact_paths"}:
            continue
        rows = section.get("rows", ())
        if not isinstance(rows, (list, tuple)):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_key = str(row.get("key", "") or "")
            if section_key == "profile" and row_key != "artifacts_dir":
                continue
            path_text = str(row.get("value", "") or "").strip()
            if not path_text:
                continue
            label = str(row.get("label", "") or row_key).strip()
            locations.append(
                {
                    "key": row_key,
                    "label": label,
                    "path": path_text,
                    "kind": "directory" if row_key == "artifacts_dir" else str(row.get("artifact_kind", "") or "file"),
                }
            )
    return tuple(locations)


def build_routing_detail_text(diagnostics) -> str:
    summary = build_routing_summary(diagnostics)
    lines = list(build_routing_detail_lines(diagnostics))
    if summary:
        lines.insert(0, f"摘要: {summary}")
    return "\n".join(lines)


def build_coverage_status_text(*, total_areas: int, total_points: int, diagnostics=None, artifacts_dir: str = "", requested_mode: str = "") -> str:
    prefix = f"Coverage: {total_areas} area(s), {total_points} total points."
    if artifacts_dir:
        prefix += f" Artifacts: {artifacts_dir}"
    summary = build_routing_summary(diagnostics)
    if str(requested_mode) == AUTO_MODE:
        if summary:
            prefix += f" Auto: {summary}"
    elif summary:
        prefix += f" Planner: {summary}"
    return prefix


class MainWindow(tk.Tk):
    TOOL_SHORTCUTS = [
        ("<KeyPress-v>", "select", "Select"),
        ("<space>", "pan", "Pan"),
        ("<KeyPress-b>", "brush", "Brush"),
        ("<KeyPress-l>", "straight_line", "Line"),
        ("<KeyPress-e>", "eraser", "Eraser"),
        ("<KeyPress-c>", "crop", "Crop"),
        ("<KeyPress-o>", "origin", "Set Origin"),
        ("<KeyPress-f>", "polygon", "Forbidden Zone"),
        ("<KeyPress-p>", "pass_only", "Pass Only Zone"),
        ("<KeyPress-w>", "line", "Virtual Wall"),
        ("<KeyPress-s>", "station", "Station"),
        ("<KeyPress-a>", "area_label", "Area Label"),
        ("<KeyPress-1>", "path_select", "Path Select"),
        ("<KeyPress-2>", "path_polygon", "Path Poly"),
        ("<KeyPress-3>", "path_add", "Path Add"),
        ("<KeyPress-4>", "path_draw", "Path Draw"),
        ("<KeyPress-5>", "path_line", "Path Line"),
    ]

    def __init__(self):

        super().__init__()

        self.title("ROS2 Map Editor")
        self.geometry("1280x800")
        self.minsize(800, 600)

        # 应用主题
        apply_theme(self)

        # 数据模型
        self.map_data = MapData()
        self.annotations = Annotations()
        self.project_manager = ProjectManager(self.map_data, self.annotations)
        self.command_manager = CommandManager()

        # 覆盖路径数据管理
        self.coverage_path_manager = CoveragePathManager()
        self._last_coverage_planning_diagnostics = None
        self._free_space_components_var = tk.BooleanVar(value=False)

        # 初始化UI组件 (先创建占位，init_ui中布局)


        self.canvas = None
        self.toolbar = None
        self.tool_manager = None
        self._toolbar_breakpoint = None
        self._current_project_dir = None
        self._dirty_state_after_id = None
        self._is_closing = False
        self._coverage_start_points_by_area_id = {}
        self._coverage_start_fingerprints_by_area_id = {}

        self._init_ui()
        self._init_tools()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _init_ui(self):
        # 1. 菜单栏
        self.menu_bar = tk.Menu(self)
        self.config(menu=self.menu_bar)

        # 文件菜单
        file_menu = tk.Menu(self.menu_bar, tearoff=0)
        file_menu.add_command(label="New Project...", command=self.new_project)
        file_menu.add_command(label="Open Project...", command=self.open_project)
        file_menu.add_command(label="Save Project", command=self.save_project)
        file_menu.add_command(label="Save Project As...", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)
        self.menu_bar.add_cascade(label="File", menu=file_menu)

        # 编辑菜单
        edit_menu = tk.Menu(self.menu_bar, tearoff=0)
        edit_menu.add_command(label="Undo (Ctrl+Z)", command=self.undo)
        edit_menu.add_command(label="Redo (Ctrl+Y)", command=self.redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Rotate Map...", command=self.rotate_map)
        edit_menu.add_command(label="Crop Map...", command=self.start_crop_map)
        edit_menu.add_separator()
        edit_menu.add_command(label="Clear Coverage Paths", command=self._clear_coverage_paths)
        edit_menu.add_command(label="Reorder Room Paths...", command=self._reorder_room_paths)
        self.menu_bar.add_cascade(label="Edit", menu=edit_menu)

        # 视图菜单
        view_menu = tk.Menu(self.menu_bar, tearoff=0)
        view_menu.add_command(label="Zoom In", command=lambda: self.canvas.on_zoom(type('obj', (object,), {'num': 4, 'x': 100, 'y': 100, 'delta': 120})))
        view_menu.add_command(label="Zoom Out", command=lambda: self.canvas.on_zoom(type('obj', (object,), {'num': 5, 'x': 100, 'y': 100, 'delta': -120})))
        view_menu.add_command(label="Fit Window", command=lambda: self.canvas.zoom_to_fit())
        view_menu.add_separator()
        view_menu.add_checkbutton(
            label="Analyze Free Space Components",
            variable=self._free_space_components_var,
            command=self._toggle_free_space_components,
        )
        view_menu.add_command(label="Set Obstacle Repair Radius...", command=self._set_free_space_component_repair_radius)
        view_menu.add_command(label="Set Small Component No-Coverage Threshold...", command=self._set_small_component_no_coverage_threshold)
        view_menu.add_command(label="Apply Small Components as No Coverage", command=self._apply_small_components_as_no_coverage)
        view_menu.add_command(label="Apply Unknown Areas as Forbidden", command=self._apply_unknown_areas_as_forbidden)
        view_menu.add_separator()
        view_menu.add_command(label="Coverage Planner Diagnostics...", command=self._show_coverage_planning_diagnostics)
        view_menu.add_separator()
        view_menu.add_command(label="检测障碍物生成区域标签...", command=self._detect_obstacles_as_area_labels)
        self.menu_bar.add_cascade(label="View", menu=view_menu)

        # 2. 状态栏 (底部)
        self.statusbar = tk.Frame(self, bg=COLORS["statusbar_bg"], height=24)
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.statusbar.pack_propagate(False)
        self.statusbar_left = tk.Label(
            self.statusbar, text="Ready", bg=COLORS["statusbar_bg"],
            fg=COLORS["statusbar_fg"], font=FONTS["status"], anchor=tk.W,
        )
        self.statusbar_left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=SPACING["md"])
        self.statusbar_right = tk.Label(
            self.statusbar, text="", bg=COLORS["statusbar_bg"],
            fg=COLORS["statusbar_fg"], font=FONTS["status"], anchor=tk.E,
        )
        self.statusbar_right.pack(side=tk.RIGHT, padx=SPACING["md"])

        # 3. 工具栏 (Top) - 稍后在init_tools中传入tool_manager
        self.toolbar = Toolbar(self)
        self._toolbar_breakpoint = getattr(self.toolbar, "current_breakpoint", None)

        # 3.1 会话状态区（当前地图/项目/脏状态）
        self.session_statusbar = tk.Frame(self, bg=COLORS["session_bg"], height=28)
        self.session_statusbar.pack(side=tk.TOP, fill=tk.X)
        self.session_statusbar.pack_propagate(False)
        self.session_label_project = tk.Label(
            self.session_statusbar, text="", bg=COLORS["session_bg"],
            fg=COLORS["fg_secondary"], font=FONTS["session"], anchor=tk.W,
        )
        self.session_label_project.pack(side=tk.LEFT, padx=SPACING["lg"])
        self.session_sep1 = tk.Frame(self.session_statusbar, width=1, bg=COLORS["border"])
        self.session_sep1.pack(side=tk.LEFT, fill=tk.Y, padx=SPACING["sm"], pady=4)
        self.session_label_map = tk.Label(
            self.session_statusbar, text="", bg=COLORS["session_bg"],
            fg=COLORS["fg_secondary"], font=FONTS["session"], anchor=tk.W,
        )
        self.session_label_map.pack(side=tk.LEFT, padx=SPACING["sm"])
        self.session_sep2 = tk.Frame(self.session_statusbar, width=1, bg=COLORS["border"])
        self.session_sep2.pack(side=tk.LEFT, fill=tk.Y, padx=SPACING["sm"], pady=4)
        self.session_label_status = tk.Label(
            self.session_statusbar, text="", bg=COLORS["session_bg"],
            fg=COLORS["fg_secondary"], font=FONTS["session"], anchor=tk.W,
        )
        self.session_label_status.pack(side=tk.LEFT, padx=SPACING["sm"])

        # 4. 侧边栏 (Right)
        self.sidebar = Sidebar(self)

        # 5. 主画布 (Center)
        self.canvas = MapCanvas(self)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.zoom_callback = self._on_zoom_changed

        # 绑定快捷键
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Control-y>", lambda e: self.redo())

        # Link Sidebar to Canvas
        self.sidebar.canvas = self.canvas

        # Room 顺序面板回调
        self.sidebar.room_order_panel.set_apply_callback(self._apply_room_order)
        self.sidebar.room_order_panel.set_tsp_callback(self._on_tsp_optimize_room_order)

        # 绑定标注数据
        self.canvas.set_annotations(self.annotations)
        self.canvas.set_coverage_path_manager(self.coverage_path_manager)
        self.canvas.free_space_status_callback = self._update_free_space_component_status
        
        # 绑定覆盖路径回调
        self.canvas.coverage_path_callback = self._on_generate_coverage_path
        self.canvas.delete_coverage_path_callback = self._delete_coverage_path
        self.canvas.has_coverage_path_for = self._has_coverage_path_for
        
        # UI 定时更新机制
        self._dirty_state_after_id = self.after(100, self._check_dirty_state)
        self.bind("<Configure>", self._on_window_resize)
        self._refresh_session_status()

    def _toggle_free_space_components(self):
        enabled = bool(self._free_space_components_var.get())
        if enabled and not self.map_data.metadata:
            self._free_space_components_var.set(False)
            self._show_warning(
                problem="未加载地图",
                impact="无法分析自由连通区",
                suggestion="先通过 New Project 或 Open Project 加载工程后再分析",
            )
            return
        self.canvas.set_free_space_components_enabled(enabled)
        if enabled:
            self.statusbar_left.config(
                text=(
                    f"Free space components enabled. Repair radius={self.canvas.free_space_component_repair_radius_m:.2f} m | "
                    f"Small-threshold={self.canvas.small_component_no_coverage_threshold_m2:.0f} m² | "
                    f"semantic=free | color={FREE_SPACE_COMPONENT_COLOR_HEX}"
                )
            )
        else:
            self.statusbar_left.config(text="Free space components disabled")

    def _set_free_space_component_repair_radius(self):
        value = simpledialog.askfloat(
            "Obstacle Repair Radius",
            "障碍物连通修补尺度 (m)",
            parent=self,
            minvalue=0.0,
            initialvalue=float(self.canvas.free_space_component_repair_radius_m),
        )
        if value is None:
            return
        self.canvas.set_free_space_component_repair_radius(value)
        if self._free_space_components_var.get():
            result = self.canvas.free_space_components_result
            count = result.total_component_count if result is not None else 0
            self.statusbar_left.config(
                text=(
                    f"Free space components refreshed. Radius={value:.2f} m, components={count} | "
                    f"semantic=free | color={FREE_SPACE_COMPONENT_COLOR_HEX}"
                )
            )
        else:
            self.statusbar_left.config(text=f"Obstacle repair radius set to {value:.2f} m")

    def _set_small_component_no_coverage_threshold(self):
        value = simpledialog.askfloat(
            "Small Component Threshold",
            "小自由区 no_coverage 阈值 (m²)",
            parent=self,
            minvalue=0.0,
            initialvalue=float(self.canvas.small_component_no_coverage_threshold_m2),
        )
        if value is None:
            return
        self.canvas.set_small_component_no_coverage_threshold(value)
        if self._free_space_components_var.get():
            result = self.canvas.free_space_components_result
            count = sum(
                1
                for stat in (result.component_stats.values() if result is not None else ())
                if stat.suggested_no_coverage
            )
            self.statusbar_left.config(
                text=(
                    f"Small-component threshold refreshed. Threshold={value:.0f} m², suggested={count} | "
                    f"semantic=free | color={FREE_SPACE_COMPONENT_COLOR_HEX}"
                )
            )
        else:
            self.statusbar_left.config(text=f"Small component no-coverage threshold set to {value:.0f} m²")

    def _update_free_space_component_status(self, stat, result, semantic_type=None):
        semantic = str(semantic_type or "free")
        if semantic in {"forbidden_zone", "no_coverage"}:
            color = constraint_base_color(semantic)
        else:
            semantic = "free"
            color = FREE_SPACE_COMPONENT_COLOR_HEX
        if not self._free_space_components_var.get():
            return
        if stat is None or result is None:
            count = result.total_component_count if result is not None else 0
            self.statusbar_left.config(
                text=(
                    f"Free space components: {count} | "
                    f"Repair radius={self.canvas.free_space_component_repair_radius_m:.2f} m | "
                    f"Small-threshold={self.canvas.small_component_no_coverage_threshold_m2:.0f} m² | "
                    f"semantic={semantic} | color={color}"
                )
            )
            return
        self.statusbar_left.config(
            text=(
                f"Component {stat.component_id} | "
                f"pixels={stat.pixel_count} | "
                f"area={stat.area_m2:.3f} m² | "
                f"suggested_no_coverage={'yes' if stat.suggested_no_coverage else 'no'} | "
                f"Repair radius={self.canvas.free_space_component_repair_radius_m:.2f} m | "
                f"Small-threshold={self.canvas.small_component_no_coverage_threshold_m2:.0f} m² | "
                f"semantic={semantic} | color={color}"
            )
        )

    def _show_free_space_component_menu(self, event, component_id: int, derived_region=None):
        menu = tk.Menu(self, tearoff=0)
        if not self._populate_free_space_component_menu(menu, component_id, derived_region=derived_region):
            return
        menu.tk_popup(event.x_root, event.y_root)

    def _populate_free_space_component_menu(self, menu, component_id: int, derived_region=None) -> bool:
        target = self._resolve_free_space_region_target(component_id, target_region=derived_region)
        if target is None:
            return False
        self._log_free_space_semantic_state(
            "menu_open",
            component_id=int(target.component_id),
            semantic=str(target.semantic),
            source=str(target.source),
            target_key=str(target.component_key),
            matched=self._matching_derived_region_summaries_for_target(target),
            stat_bbox=tuple(int(v) for v in target.bbox_px),
            stat_area_m2=float(target.area_m2),
        )
        menu.add_command(
            label=f"置为禁止区 - component {target.component_id}",
            command=lambda frozen_target=target: self._apply_free_space_region_target_constraint(frozen_target, "forbidden_zone"),
        )
        menu.add_command(
            label=f"置为不规划覆盖区 - component {target.component_id}",
            command=lambda frozen_target=target: self._apply_free_space_region_target_constraint(frozen_target, "no_coverage"),
        )
        menu.add_command(
            label=f"恢复为自由区 - component {target.component_id}",
            command=lambda frozen_target=target: self._restore_free_space_region_target(frozen_target),
        )
        menu.add_separator()
        menu.add_command(
            label=f"生成禁止区多边形 - component {target.component_id}",
            command=lambda frozen_target=target: self._generate_free_space_region_target_polygon_constraint(frozen_target, "forbidden_zone"),
        )
        menu.add_command(
            label=f"生成不规划覆盖区多边形 - component {target.component_id}",
            command=lambda frozen_target=target: self._generate_free_space_region_target_polygon_constraint(frozen_target, "no_coverage"),
        )
        menu.add_separator()
        menu.add_command(
            label=(
                f"信息：pixels={target.pixel_count}, area={target.area_m2:.3f} m², "
                f"semantic={target.semantic}, color={self._free_space_target_color(target)}"
            ),
            state=tk.DISABLED,
        )
        return True

    def _component_constraint_segment_name(self, component_id: int, constraint_type: str) -> str:
        if constraint_type == "forbidden_zone":
            return f"Component {component_id} Forbidden"
        if constraint_type == "no_coverage":
            return f"Component {component_id} No Coverage"
        return f"Component {component_id} Constraint"

    def _component_derived_region_name(self, component_id: int, action_type: str) -> str:
        if action_type == "forbidden_zone":
            return f"Component {component_id} Forbidden Region"
        if action_type == "no_coverage":
            return f"Component {component_id} No Coverage Region"
        return f"Component {component_id} Region"

    @staticmethod
    def _component_key_from_bbox_mask(bbox_px, component_mask=None) -> str:
        return component_key_from_bbox_mask(bbox_px, component_mask)

    @staticmethod
    def _component_object_id(prefix: str, component_key: str, *, fallback_component_id: int) -> str:
        return component_object_id(prefix, component_key, fallback_component_id=fallback_component_id)

    def _constraint_truth_matches_target(self, item, component_id: int, component_key: str | None) -> bool:
        item_component_id = int(getattr(item, "component_id", getattr(item, "metadata", {}).get("component_id", -1)))
        item_key = ""
        metadata = getattr(item, "metadata", {}) or {}
        if isinstance(metadata, dict):
            item_key = str(metadata.get("component_key", "") or "")
        if not item_key and hasattr(item, "bbox_px"):
            item_key = self._component_key_from_bbox_mask(getattr(item, "bbox_px"))
        if component_key:
            return item_key == component_key
        return item_component_id == int(component_id)

    def _constraint_truth_matches_region_target(self, item, target: FreeSpaceRegionTarget) -> bool:
        return truth_matches_target(item, target)

    def _matching_derived_region_summaries(self, component_id: int, component_key: str | None):
        summaries = []
        for region in self.annotations.iter_derived_constraint_regions():
            if not self._constraint_truth_matches_target(region, component_id, component_key):
                continue
            summaries.append(
                {
                    "id": str(region.id),
                    "action": str(region.action_type),
                    "component_key": str((region.metadata or {}).get("component_key", "")),
                    "bbox": tuple(int(v) for v in region.bbox_px),
                }
            )
        return summaries

    def _matching_derived_region_summaries_for_target(self, target: FreeSpaceRegionTarget):
        summaries = []
        for region in self.annotations.iter_derived_constraint_regions():
            if not self._constraint_truth_matches_region_target(region, target):
                continue
            summaries.append(
                {
                    "id": str(region.id),
                    "action": str(region.action_type),
                    "component_key": str((region.metadata or {}).get("component_key", "")),
                    "bbox": tuple(int(v) for v in region.bbox_px),
                }
            )
        return summaries

    def _commit_constraint_region_truth(self, new_segments, new_regions):
        cmd = UpdateConstraintRegionTruthCommand(
            self.annotations,
            self.annotations.constraint_segments,
            new_segments,
            self.annotations.derived_constraint_regions,
            new_regions,
            refresh_cb=self.canvas.refresh,
        )
        self.command_manager.execute(cmd)

    def _free_space_target_color(self, target: FreeSpaceRegionTarget) -> str:
        if target.semantic in {"forbidden_zone", "no_coverage"}:
            return constraint_base_color(str(target.semantic))
        return FREE_SPACE_COMPONENT_COLOR_HEX

    def _resolve_free_space_region_target(self, component_id: int, target_region=None) -> FreeSpaceRegionTarget | None:
        if target_region is not None:
            return target_from_derived_region(self.annotations, target_region)
        result = getattr(self.canvas, "free_space_components_result", None)
        target = target_from_free_component(result, int(component_id))
        if target is not None:
            return target
        matches = [
            region
            for region in self.annotations.iter_derived_constraint_regions()
            if int(region.component_id) == int(component_id)
        ]
        if len(matches) != 1:
            return None
        return target_from_derived_region(self.annotations, matches[0])

    def _build_component_derived_region(self, component_id: int, action_type: str, target_region=None):
        target = self._resolve_free_space_region_target(component_id, target_region=target_region)
        if target is None:
            return None
        return self._build_derived_region_from_target(target, action_type)

    def _build_derived_region_from_target(self, target: FreeSpaceRegionTarget, action_type: str):
        return derived_region_from_target(
            self.annotations,
            target,
            action_type,
            object_id=self._component_object_id(
                f"free-space-{action_type}",
                target.component_key,
                fallback_component_id=int(target.component_id),
            ),
            name=self._component_derived_region_name(target.component_id, action_type),
        )

    def _extract_polygon_world_from_bbox_mask(self, bbox_px, component_mask, *, simplify_epsilon_px: float = 1.5):
        if self.map_data.metadata is None:
            return []
        if component_mask is None or np.asarray(component_mask).size == 0:
            return []
        component_mask = np.asarray(component_mask, dtype=np.uint8)
        contours, _ = cv2.findContours(component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return []
        contour = max(contours, key=cv2.contourArea)
        original_contour = contour
        if float(simplify_epsilon_px) > 0.0:
            contour = cv2.approxPolyDP(contour, epsilon=float(simplify_epsilon_px), closed=True)
        if contour.shape[0] < 3:
            contour = original_contour
        if contour.shape[0] < 3:
            return []
        x0, y0, _width, _height = (int(value) for value in bbox_px)
        resolution = float(self.map_data.metadata.resolution)
        origin_x = float(self.map_data.metadata.origin[0])
        origin_y = float(self.map_data.metadata.origin[1])
        height = int(self.map_data.height)
        polygon = []
        for point in contour.reshape((-1, 2)):
            px = int(point[0]) + x0
            py = int(point[1]) + y0
            wx = origin_x + float(px) * resolution
            wy = origin_y + float(height - py) * resolution
            polygon.append((wx, wy))
        return polygon

    def _apply_free_space_component_constraint(self, component_id: int, constraint_type: str, target_region=None):
        target = self._resolve_free_space_region_target(component_id, target_region=target_region)
        if target is None:
            self._show_warning(
                problem="自由连通区掩膜提取失败",
                impact="当前连通区未转成正式处置语义",
                suggestion="尝试调整障碍物连通修补尺度后重试",
            )
            return
        self._apply_free_space_region_target_constraint(target, constraint_type)

    def _apply_free_space_region_target_constraint(self, target: FreeSpaceRegionTarget, constraint_type: str):
        region = self._build_derived_region_from_target(target, constraint_type)
        self._log_free_space_semantic_state(
            "apply_before",
            component_id=int(target.component_id),
            target_action=str(constraint_type),
            target_key=str(target.component_key),
            source=str(target.source),
            matched_before=self._matching_derived_region_summaries_for_target(target),
        )
        old_segments = self.annotations.constraint_segments
        new_segments = [
            copy.deepcopy(item)
            for item in old_segments
            if not (
                bool(item.closed)
                and item.constraint_type in {"forbidden_zone", "no_coverage"}
                and self._constraint_truth_matches_region_target(item, target)
            )
        ]
        old_regions = self.annotations.derived_constraint_regions
        new_regions = [
            copy.deepcopy(item)
            for item in old_regions
            if not (
                item.action_type in {"forbidden_zone", "no_coverage"}
                and self._constraint_truth_matches_region_target(item, target)
            )
        ]
        new_regions.append(region)
        self._commit_constraint_region_truth(new_segments, new_regions)
        self._log_free_space_semantic_state(
            "apply_after",
            component_id=int(target.component_id),
            target_action=str(constraint_type),
            target_key=str(target.component_key),
            matched_after=self._matching_derived_region_summaries_for_target(target),
        )
        self.statusbar_left.config(
            text=f"Component {target.component_id} -> {constraint_type} (semantic) | color={constraint_base_color(constraint_type)}"
        )

    def _generate_free_space_component_polygon_constraint(self, component_id: int, constraint_type: str, target_region=None):
        target = self._resolve_free_space_region_target(component_id, target_region=target_region)
        if target is None:
            self._show_warning(
                problem="自由连通区轮廓提取失败",
                impact="当前连通区未生成正式多边形",
                suggestion="尝试调整障碍物连通修补尺度后重试",
            )
            return
        self._generate_free_space_region_target_polygon_constraint(target, constraint_type)

    def _generate_free_space_region_target_polygon_constraint(self, target: FreeSpaceRegionTarget, constraint_type: str):
        result = getattr(self.canvas, "free_space_components_result", None)
        if target.source == "free_component" and result is not None and result.stat_for_label(target.component_id) is not None:
            polygon = extract_component_polygon_world(self.map_data, result, target.component_id)
        else:
            polygon = self._extract_polygon_world_from_bbox_mask(
                target.bbox_px,
                target.mask,
            )
        if len(polygon) < 3:
            self._show_warning(
                problem="自由连通区轮廓提取失败",
                impact="当前连通区未生成正式多边形",
                suggestion="尝试调整障碍物连通修补尺度后重试",
            )
            return
        closed_default, color_default, default_name = self._constraint_type_defaults(constraint_type)
        metadata = {"source": "free_space_component", "component_id": int(target.component_id), "component_key": str(target.component_key)}
        old_segments = self.annotations.constraint_segments
        new_segments = [
            copy.deepcopy(item)
            for item in old_segments
            if not (
                item.constraint_type in {"forbidden_zone", "no_coverage"}
                and bool(item.closed)
                and self._constraint_truth_matches_region_target(item, target)
            )
        ]
        new_segments.append(
            ConstraintSegment(
                id=self._component_object_id(
                    f"free-space-{constraint_type}",
                    target.component_key,
                    fallback_component_id=int(target.component_id),
                ),
                name=self._component_constraint_segment_name(target.component_id, constraint_type) or default_name,
                points=[tuple(point) for point in polygon],
                closed=closed_default,
                constraint_type=constraint_type,
                color=color_default,
                metadata=metadata,
            )
        )
        old_regions = self.annotations.derived_constraint_regions
        new_regions = [
            copy.deepcopy(item)
            for item in old_regions
            if not (
                item.action_type in {"forbidden_zone", "no_coverage"}
                and self._constraint_truth_matches_region_target(item, target)
            )
        ]
        self._commit_constraint_region_truth(new_segments, new_regions)
        self.statusbar_left.config(
            text=f"Component {target.component_id} -> {constraint_type} polygon | color={constraint_base_color(constraint_type)}"
        )

    def _restore_free_space_component(self, component_id: int, target_region=None):
        target = self._resolve_free_space_region_target(component_id, target_region=target_region)
        if target is None:
            return
        self._restore_free_space_region_target(target)

    def _restore_free_space_region_target(self, target: FreeSpaceRegionTarget):
        if self.map_data.metadata is None:
            return
        self._log_free_space_semantic_state(
            "restore_before",
            component_id=int(target.component_id),
            target_key=str(target.component_key),
            source=str(target.source),
            matched_before=self._matching_derived_region_summaries_for_target(target),
        )
        old_segments = self.annotations.constraint_segments
        new_segments = []
        removed = 0
        for item in old_segments:
            if item.constraint_type not in {"forbidden_zone", "no_coverage"} or not item.closed or len(item.points) < 3:
                new_segments.append(copy.deepcopy(item))
                continue
            if self._constraint_truth_matches_region_target(item, target):
                removed += 1
                continue
            new_segments.append(copy.deepcopy(item))
        old_regions = self.annotations.derived_constraint_regions
        new_regions = []
        for region in old_regions:
            if region.action_type in {"forbidden_zone", "no_coverage"} and self._constraint_truth_matches_region_target(region, target):
                removed += 1
                continue
            new_regions.append(copy.deepcopy(region))
        if removed <= 0:
            self._log_free_space_semantic_state(
                "restore_noop",
                component_id=int(target.component_id),
                target_key=str(target.component_key),
                matched_after=self._matching_derived_region_summaries_for_target(target),
            )
            self.statusbar_left.config(text=f"Component {target.component_id} has no removable constraint overlays")
            return
        self._commit_constraint_region_truth(new_segments, new_regions)
        self._log_free_space_semantic_state(
            "restore_after",
            component_id=int(target.component_id),
            target_key=str(target.component_key),
            matched_after=self._matching_derived_region_summaries_for_target(target),
        )
        self.statusbar_left.config(text=f"Component {target.component_id} restored to free | color={FREE_SPACE_COMPONENT_COLOR_HEX}")

    def _apply_small_components_as_no_coverage(self):
        result = getattr(self.canvas, "free_space_components_result", None)
        if result is None:
            if not self._free_space_components_var.get():
                self._show_warning(
                    problem="自由连通区分析未开启",
                    impact="无法批量生成 no_coverage",
                    suggestion="先开启 Analyze Free Space Components 后再应用",
                )
            else:
                self.canvas.refresh()
                result = self.canvas.free_space_components_result
        if result is None:
            return
        candidate_ids = [
            stat.component_id
            for stat in result.component_stats.values()
            if stat.suggested_no_coverage
        ]
        if not candidate_ids:
            self.statusbar_left.config(
                text=f"No free-space components <= {self.canvas.small_component_no_coverage_threshold_m2:.2f} m²"
            )
            return
        existing_component_keys = {
            str((region.metadata or {}).get("component_key", "") or self._component_key_from_bbox_mask(region.bbox_px))
            for region in self.annotations.iter_derived_constraint_regions("no_coverage")
        }
        old_segments = self.annotations.constraint_segments
        new_segments = [copy.deepcopy(item) for item in old_segments]
        old_regions = self.annotations.derived_constraint_regions
        new_regions = [copy.deepcopy(item) for item in old_regions]
        added = 0
        for component_id in candidate_ids:
            region = self._build_component_derived_region(component_id, "no_coverage")
            if region is None:
                continue
            component_key = str(region.metadata.get("component_key", "") or "")
            if component_key in existing_component_keys:
                continue
            new_regions.append(region)
            existing_component_keys.add(component_key)
            added += 1
        if added <= 0:
            self.statusbar_left.config(text="All suggested small components already marked as no_coverage")
            return
        self._commit_constraint_region_truth(new_segments, new_regions)
        self.statusbar_left.config(
            text=f"Applied {added} small components as no_coverage | color={constraint_base_color('no_coverage')}"
        )

    def _apply_unknown_areas_as_forbidden(self):
        if self.map_data.metadata is None:
            self._show_warning(
                problem="未加载地图",
                impact="无法生成 unknown 禁止区",
                suggestion="先通过 New Project 或 Open Project 加载工程后再操作",
            )
            return
        result = analyze_unknown_regions(self.map_data)
        if result.total_component_count <= 0:
            self.statusbar_left.config(text="No unknown areas found")
            return

        confirmed = messagebox.askyesno(
            "Apply Unknown Areas as Forbidden",
            (
                "将当前地图中的 unknown 区域写入禁止区图层。\n\n"
                f"连通区数量: {result.total_component_count}\n"
                f"像素数量: {result.total_pixel_count}\n"
                f"面积: {result.total_area_m2:.3f} m²\n\n"
                "继续后会替换上一次由 unknown 自动生成的禁止区，保留手动画的禁止区。"
            ),
            parent=self,
        )
        if not confirmed:
            self.statusbar_left.config(text="Apply unknown areas as forbidden canceled")
            return

        generated_regions = build_unknown_forbidden_regions(self.annotations, result)
        old_regions = self.annotations.derived_constraint_regions
        new_regions = [
            copy.deepcopy(region)
            for region in old_regions
            if not (region.action_type == "forbidden_zone" and is_unknown_region(region))
        ]
        new_regions.extend(generated_regions)
        self._commit_constraint_region_truth(
            [copy.deepcopy(item) for item in self.annotations.constraint_segments],
            new_regions,
        )
        self.statusbar_left.config(
            text=(
                f"Applied {len(generated_regions)} unknown area(s) as forbidden | "
                f"components={result.total_component_count} | "
                f"area={result.total_area_m2:.3f} m² | color={constraint_base_color('forbidden_zone')}"
            )
        )
        

    def _detect_obstacles_as_area_labels(self):
        """检测地图中的障碍物和禁行区轮廓，自动生成区域标签。"""
        if self.map_data.metadata is None:
            self._show_warning(problem="未加载地图", impact="无法分析",
                               suggestion="先加载工程后再操作")
            return

        from ..utils.free_space_components import build_obstacle_semantic_mask
        obstacle_mask = build_obstacle_semantic_mask(self.map_data, self.annotations)
        if cv2.countNonZero(obstacle_mask) == 0:
            self.statusbar_left.config(text="地图中无检测到障碍物")
            return

        min_area = simpledialog.askfloat(
            "最小面积 (m²)", "忽略小于此面积的障碍物 (m², 默认0.5):",
            parent=self, minvalue=0.01, initialvalue=0.5)
        if min_area is None:
            return

        resolution = float(self.map_data.metadata.resolution)
        origin_x = float(self.map_data.metadata.origin[0])
        origin_y = float(self.map_data.metadata.origin[1])
        height = int(self.map_data.height)
        min_area_px = min_area / (resolution * resolution)

        contours, _ = cv2.findContours(
            obstacle_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        existing_ids = {a.area_id for a in self.annotations.area_labels}
        next_id = 1
        while next_id in existing_ids:
            next_id += 1

        from ..controllers.commands.annotation_command import AddAnnotationCommand

        added = 0
        for contour in contours:
            area_px = cv2.contourArea(contour)
            if area_px < min_area_px:
                continue
            contour = cv2.approxPolyDP(contour, epsilon=1.5, closed=True)
            if contour.shape[0] < 3:
                continue
            polygon = []
            for pt in contour[:, 0, :]:
                wx = origin_x + float(pt[0]) * resolution
                wy = origin_y + float(height - pt[1]) * resolution
                polygon.append((wx, wy))
            if len(polygon) < 3:
                continue
            area_m2 = area_px * resolution * resolution
            label = AreaLabel(
                id="", area_id=next_id,
                name=f"障碍物 {area_m2:.1f}m²",
                polygon=polygon, color="",
            )
            cmd = AddAnnotationCommand(
                self.annotations, "area_label",
                {"polygon": label.polygon, "name": label.name,
                 "area_id": label.area_id},
                refresh_cb=self.canvas.refresh,
            )
            self.command_manager.execute(cmd)
            next_id += 1
            while next_id in existing_ids:
                next_id += 1
            added += 1

        self.canvas.refresh()
        self.statusbar_left.config(
            text=f"障碍物检测: {added} 个区域已生成 (min={min_area}m²)")

    def _check_dirty_state(self):
        if bool(getattr(self, "_is_closing", False)) or not self._window_exists():
            self._dirty_state_after_id = None
            return
        # 检查撤销栈或路径管理器是否脏了
        is_dirty = self.command_manager.can_undo() or self.coverage_path_manager.is_dirty
        title = "ROS2 Map Editor"
        if is_dirty:
            title += " *"
        if self.title() != title:
            self.title(title)
        self._refresh_session_status()
        self._dirty_state_after_id = self.after(500, self._check_dirty_state)

    def _window_exists(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _safe_showinfo(self, title: str, message: str) -> None:
        if bool(getattr(self, "_is_closing", False)) or not self._window_exists():
            return
        try:
            messagebox.showinfo(title, message)
        except tk.TclError:
            # 保存/导出已完成时，应用可能已经在关闭；此时不应把提示框失败当成保存失败。
            return

    def _copy_text_to_clipboard(self, text: str) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except tk.TclError:
            return

    @staticmethod
    def _filesystem_location_target(path_text: str, kind: str = "") -> str:
        path = Path(str(path_text or "")).expanduser()
        if str(kind or "") == "directory":
            return str(path)
        if path.suffix:
            return str(path.parent)
        return str(path)

    def _open_filesystem_location(self, path_text: str, kind: str = "") -> None:
        target = self._filesystem_location_target(path_text, kind)
        if not target:
            return
        try:
            if os.name == "nt":
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
        except (OSError, tk.TclError):
            self._safe_showinfo("打开产物位置失败", target)

    def _safe_show_coverage_diagnostics_detail(
        self,
        title: str,
        message: str,
        artifact_locations: tuple[dict[str, str], ...],
    ) -> None:
        if bool(getattr(self, "_is_closing", False)) or not self._window_exists():
            return
        if not artifact_locations:
            self._safe_showinfo(title, message)
            return
        try:
            dialog = tk.Toplevel(self)
            dialog.title(title)
            dialog.geometry("980x620")
            dialog.transient(self)

            text_frame = tk.Frame(dialog)
            text_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))
            text_scroll = tk.Scrollbar(text_frame)
            text_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            text = tk.Text(text_frame, wrap=tk.WORD, height=18, yscrollcommand=text_scroll.set)
            text.insert("1.0", message)
            text.configure(state=tk.DISABLED)
            text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            text_scroll.configure(command=text.yview)

            artifact_frame = tk.LabelFrame(dialog, text="关键产物路径")
            artifact_frame.pack(fill=tk.BOTH, expand=False, padx=8, pady=4)
            listbox = tk.Listbox(artifact_frame, height=min(8, max(3, len(artifact_locations))))
            for item in artifact_locations:
                listbox.insert(tk.END, f"{item['label']}: {item['path']}")
            listbox.selection_set(0)
            listbox.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

            button_frame = tk.Frame(dialog)
            button_frame.pack(fill=tk.X, padx=8, pady=(4, 8))

            def selected_item() -> dict[str, str]:
                selection = listbox.curselection()
                if not selection:
                    return dict(artifact_locations[0])
                return dict(artifact_locations[int(selection[0])])

            def copy_selected() -> None:
                self._copy_text_to_clipboard(str(selected_item()["path"]))

            def copy_all() -> None:
                self._copy_text_to_clipboard(
                    "\n".join(f"{item['label']}: {item['path']}" for item in artifact_locations)
                )

            def open_selected() -> None:
                item = selected_item()
                self._open_filesystem_location(str(item["path"]), str(item.get("kind", "")))

            tk.Button(button_frame, text="打开选中位置", command=open_selected).pack(side=tk.LEFT, padx=(0, 6))
            tk.Button(button_frame, text="复制选中路径", command=copy_selected).pack(side=tk.LEFT, padx=(0, 6))
            tk.Button(button_frame, text="复制全部路径", command=copy_all).pack(side=tk.LEFT, padx=(0, 6))
            tk.Button(button_frame, text="关闭", command=dialog.destroy).pack(side=tk.RIGHT)
        except tk.TclError:
            self._safe_showinfo(title, message)

    def _show_coverage_planning_diagnostics(self) -> None:
        diagnostics = self.__dict__.get("_last_coverage_planning_diagnostics")
        detail_text = build_routing_detail_text(diagnostics)
        if not detail_text:
            detail_text = "当前会话还没有可显示的覆盖路径规划诊断。"
        artifact_locations = build_routing_artifact_locations(diagnostics)
        if artifact_locations:
            self._safe_show_coverage_diagnostics_detail("覆盖路径规划诊断", detail_text, artifact_locations)
        else:
            self._safe_showinfo("覆盖路径规划诊断", detail_text)

    def _on_close(self):
        self._is_closing = True
        after_id = getattr(self, "_dirty_state_after_id", None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except tk.TclError:
                pass
            self._dirty_state_after_id = None
        self.destroy()

    def _bind_tool_shortcuts(self):
        for sequence, tool_name, label in self.TOOL_SHORTCUTS:
            self.bind_all(
                sequence,
                lambda event, t=tool_name, l=label: self._set_tool_from_shortcut(event, t, l),
            )

    def _is_editable_input_focused(self) -> bool:
        focus_get = self.__dict__.get("focus_get")
        if callable(focus_get):
            widget = focus_get()
        else:
            widget = self.focus_get()
        if widget is None:
            return False
        try:
            widget_class = widget.winfo_class()
        except Exception:
            return False
        return widget_class in {"Entry", "TEntry", "Text", "Spinbox", "TCombobox", "Combobox", "TSpinbox"}

    def _set_tool_from_shortcut(self, event, tool_name: str, label: str):
        if self._is_editable_input_focused():
            return
        if getattr(event, "state", 0) & 0x4:  # Ctrl key pressed
            return
        manager = self.__dict__.get("tool_manager")
        if manager is None:
            return
        manager.set_tool(tool_name)
        statusbar = self.__dict__.get("statusbar_left")
        if statusbar is not None:
            statusbar.config(text=f"Switched tool: {label}")

    def _get_toolbar_shortcut_hints(self) -> str:
        pairs = [
            ("V", "Select"),
            ("Space", "Pan"),
            ("B", "Brush"),
            ("L", "Line"),
            ("E", "Eraser"),
            ("C", "Crop"),
        ]
        return "  ".join(f"{key}:{name}" for key, name in pairs)

    def _build_session_status_text(self) -> str:
        map_data = self.__dict__.get("map_data")
        map_name = "-"
        if map_data and getattr(map_data, "yaml_path", ""):
            map_name = os.path.basename(map_data.yaml_path)

        project_dir = self.__dict__.get("_current_project_dir")
        project_name = os.path.basename(project_dir) if project_dir else "-"

        command_manager = self.__dict__.get("command_manager")
        coverage_manager = self.__dict__.get("coverage_path_manager")
        dirty = False
        if command_manager and command_manager.can_undo():
            dirty = True
        if coverage_manager and getattr(coverage_manager, "is_dirty", False):
            dirty = True

        layout_name = self.__dict__.get("_toolbar_breakpoint")
        if not layout_name:
            toolbar = self.__dict__.get("toolbar")
            layout_name = getattr(toolbar, "current_breakpoint", None) if toolbar else None
        layout_name = layout_name or "unknown"
        hints = self._get_toolbar_shortcut_hints()
        return (
            f"Map: {map_name} | Project: {project_name} | Dirty: {'Yes' if dirty else 'No'} "
            f"| Layout: {layout_name} | Shortcuts: {hints}"
        )

    def _refresh_session_status(self):
        map_data = self.__dict__.get("map_data")
        map_name = "-"
        if map_data and getattr(map_data, "yaml_path", ""):
            map_name = os.path.basename(map_data.yaml_path)

        project_dir = self.__dict__.get("_current_project_dir")
        project_name = os.path.basename(project_dir) if project_dir else "-"

        command_manager = self.__dict__.get("command_manager")
        coverage_manager = self.__dict__.get("coverage_path_manager")
        dirty = False
        if command_manager and command_manager.can_undo():
            dirty = True
        if coverage_manager and getattr(coverage_manager, "is_dirty", False):
            dirty = True

        dirty_label = " \u25cf unsaved" if dirty else ""

        session_label_project = self.__dict__.get("session_label_project")
        session_label_map = self.__dict__.get("session_label_map")
        session_label_status = self.__dict__.get("session_label_status")
        if session_label_project:
            session_label_project.config(text=f"\u2002{project_name}")
        if session_label_map:
            session_label_map.config(text=f"\u2002{map_name}")
        if session_label_status:
            session_label_status.config(
                text=f"{dirty_label}",
                fg=COLORS["warning"] if dirty else COLORS["fg_secondary"],
            )

    def _on_window_resize(self, event):
        if event.widget is not self or not self.toolbar:
            return
        width = max(int(event.width), 0)
        if width >= 1800:
            breakpoint_name = "wide"
        elif width >= 1300:
            breakpoint_name = "medium"
        else:
            breakpoint_name = "narrow"

        if breakpoint_name != self._toolbar_breakpoint:
            self.toolbar.apply_breakpoint(breakpoint_name)
            self._toolbar_breakpoint = breakpoint_name

    def _on_zoom_changed(self, zoom_level: float):
        statusbar_right = self.__dict__.get("statusbar_right")
        if statusbar_right:
            statusbar_right.config(text=f"Zoom: {zoom_level:.1f}x")

    def _init_tools(self):
        """初始化工具管理器和工具"""
        self.tool_manager = ToolManager(self.canvas, self.command_manager)

        # 注册工具
        self.tool_manager.register_tool(PanTool, self)
        self.tool_manager.register_tool(SelectTool, self)
        self.tool_manager.register_tool(OriginTool, self)
        self.tool_manager.register_tool(CropTool, self)

        self.tool_manager.register_tool(BrushTool, self)
        self.tool_manager.register_tool(EraserTool, self)
        self.tool_manager.register_tool(StraightLineTool, self)
        self.tool_manager.register_tool(PolygonTool, self)
        self.tool_manager.register_tool(PassOnlyTool, self)
        self.tool_manager.register_tool(AreaLabelTool, self)
        self.tool_manager.register_tool(LineTool, self)
        self.tool_manager.register_tool(StationTool, self)

        # Path Tools
        self.tool_manager.register_tool(PathSelectTool, self)
        self.tool_manager.register_tool(PathPolygonSelectTool, self)
        self.tool_manager.register_tool(PathAddTool, self)
        self.tool_manager.register_tool(PathDrawTool, self)
        self.tool_manager.register_tool(PathLineTool, self)

        # 设置默认工具

        self.tool_manager.set_tool("pan")

        # 将ToolManager关联到Toolbar
        self.toolbar.tool_manager = self.tool_manager
        self._bind_tool_shortcuts()
        self._refresh_session_status()


    def rotate_map(self):
        """旋转地图"""
        if not self.map_data.metadata:
            self._show_warning(
                problem="未加载地图",
                impact="无法执行旋转操作",
                suggestion="先通过 New Project 或 Open Project 进入工程会话",
            )
            return

        dlg = RotationDialog(self)
        if dlg.angle == 0.0:
            return

        # 1. 捕获状态
        before_state = TransformCommand.capture_state(self.map_data, self.annotations)

        # 2. 执行旋转
        # 旋转中心: 图像中心的【世界坐标】
        res = self.map_data.metadata.resolution
        origin = self.map_data.metadata.origin
        h, w = self.map_data.height, self.map_data.width

        # Pixel center
        cx = w / 2.0
        cy = h / 2.0

        # World center
        center_wx = origin[0] + cx * res
        center_wy = origin[1] + (h - cy) * res # Y-up

        # A. 旋转图像 & 更新 Origin
        self.map_data.rotate(dlg.angle, interpolation_mode=dlg.interpolation_mode)

        # B. 旋转标注
        self.annotations.rotate(dlg.angle, center_wx, center_wy)

        # 3. 捕获新状态
        after_state = TransformCommand.capture_state(self.map_data, self.annotations)

        # 4. 提交命令
        cmd = TransformCommand(
            self.map_data,
            self.annotations,
            before_state,
            after_state,
            refresh_cb=self.canvas.refresh
        )
        self.command_manager.execute(cmd)

        self.canvas.refresh()
        self.statusbar_left.config(text=f"Rotated map by {dlg.angle} degrees")

    def start_crop_map(self):
        """进入框选裁剪模式。"""
        if not self.map_data.metadata:
            self._show_warning(
                problem="未加载地图",
                impact="无法执行裁剪操作",
                suggestion="先通过 New Project 或 Open Project 进入工程会话",
            )
            return

        self.tool_manager.set_tool("crop")
        self.statusbar_left.config(text="Drag to create crop box, adjust handles, press Enter to apply")

    def crop_map_to_pixels(self, x0: int, y0: int, x1: int, y1: int):
        """按像素矩形裁剪地图，并同步更新标注和 undo/redo。"""
        if not self.map_data.metadata:
            return False

        x0 = max(0, min(int(x0), self.map_data.width))
        y0 = max(0, min(int(y0), self.map_data.height))
        x1 = max(0, min(int(x1), self.map_data.width))
        y1 = max(0, min(int(y1), self.map_data.height))

        if x1 <= x0 or y1 <= y0:
            self.statusbar_left.config(text="Crop cancelled: empty selection")
            return False

        dlg = CropInfoDialog(self, x1 - x0, y1 - y0)
        if not dlg.confirmed:
            self.statusbar_left.config(text="Crop cancelled")
            return False

        before_state = TransformCommand.capture_state(self.map_data, self.annotations)
        if not self.map_data.crop(x0, y0, x1, y1):
            self.statusbar_left.config(text="Crop failed")
            return False

        bounds = self.map_data.get_world_bounds()
        if bounds is not None:
            self.annotations.crop_to_bounds(*bounds)

        after_state = TransformCommand.capture_state(self.map_data, self.annotations)
        cmd = TransformCommand(
            self.map_data,
            self.annotations,
            before_state,
            after_state,
            refresh_cb=self.canvas.refresh
        )
        self.command_manager.execute(cmd)

        self.canvas.refresh()
        self.statusbar_left.config(text=f"Cropped map to {self.map_data.width} x {self.map_data.height}")
        return True


    def save_project(self):
        """保存项目"""
        if not self.map_data.metadata:
            self._show_warning(
                problem="未加载地图",
                impact="无法保存项目",
                suggestion="先加载地图后再保存项目",
            )
            return

        current_dir = self._current_project_save_dir()
        if current_dir:
            self._save_project_to_dir(current_dir)
            return

        self.save_project_as()

    def save_project_as(self):
        """选择目录另存项目。"""
        if not self.map_data.metadata:
            self._show_warning(
                problem="未加载地图",
                impact="无法保存项目",
                suggestion="先加载地图后再保存项目",
            )
            return

        # 选择保存目录；默认回到当前项目目录或地图所在目录，避免每次从系统根目录重新选择。
        dir_path = filedialog.askdirectory(
            title="Select Project Directory to Save",
            initialdir=self._default_project_dialog_dir(),
        )
        if dir_path:
            self._save_project_to_dir(dir_path)

    def _save_project_to_dir(self, dir_path: str) -> None:
        try:
            normalize_and_validate_area_room_ids(self.annotations.area_labels)
            self.project_manager.save_project(dir_path)
            Exporter(self.map_data, self.annotations).export(dir_path)
            self._last_project_extra_warnings = []
            self._save_project_extras(dir_path)
            self._prompt_save_coverage_planner_params(dir_path)
            self._current_project_dir = dir_path
            extra_warnings = list(getattr(self, "_last_project_extra_warnings", []) or [])
            if extra_warnings:
                self.statusbar_left.config(text=f"Saved project to {dir_path}; coverage repo warnings: {len(extra_warnings)}")
                self._show_warning(
                    title="Project Saved With Warnings",
                    problem="工程已保存，但 coverage_repo 派生产物未完整刷新",
                    impact="\n".join(extra_warnings[:5]),
                    suggestion="根据提示检查区域重叠和覆盖路径一致性；路径不会被自动修改或重算",
                )
            else:
                self.statusbar_left.config(text=f"Saved project to {dir_path}")
                self._safe_showinfo("Success", f"Project saved to {dir_path}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_error(
                problem=f"项目保存失败: {e}",
                impact="当前编辑结果未落盘",
                suggestion="检查目标目录权限和磁盘空间后重试",
            )

    def _current_project_save_dir(self) -> str | None:
        candidates = [
            self.__dict__.get("_current_project_dir"),
            getattr(self.__dict__.get("project_manager"), "project_dir", None),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            expanded = os.path.abspath(os.path.expanduser(str(candidate)))
            if os.path.isdir(expanded):
                return expanded
        return None

    def _default_project_dialog_dir(self) -> str:
        """Return a stable initial directory for project save/open dialogs."""
        candidates = [
            self.__dict__.get("_current_project_dir"),
            getattr(self.__dict__.get("project_manager"), "project_dir", None),
        ]
        map_data = self.__dict__.get("map_data")
        map_yaml_path = getattr(map_data, "yaml_path", "") if map_data is not None else ""
        if map_yaml_path:
            candidates.append(os.path.dirname(os.path.abspath(map_yaml_path)))
        candidates.append(os.getcwd())

        for candidate in candidates:
            if not candidate:
                continue
            expanded = os.path.abspath(os.path.expanduser(str(candidate)))
            if os.path.isdir(expanded):
                return expanded
        return os.getcwd()

    def new_project(self):
        """创建新的工程会话，并以底图 YAML 作为唯一正式输入。"""
        map_yaml = filedialog.askopenfilename(
            title="Select Map YAML for New Project",
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")],
            initialdir=os.getcwd(),
        )
        if not map_yaml:
            return

        self.statusbar_left.config(text=f"Loading map for new project: {map_yaml}...")
        self.update()

        self._reset_project_session()
        if not self.map_data.load(map_yaml):
            self._show_error(
                problem="底图加载失败",
                impact="无法创建新工程",
                suggestion="确认选择的是有效 map.yaml 且底图图像可访问",
            )
            self.statusbar_left.config(text="New project failed")
            return

        self.canvas.set_map_data(self.map_data)
        self.canvas.set_annotations(self.annotations)
        self.canvas.refresh()

        if messagebox.askyesno("Electronic Fence", "是否为新工程载入电子围栏?"):
            try:
                self._prompt_load_electronic_fence()
            except Exception:
                self.statusbar_left.config(text=f"New project ready without electronic fence: {map_yaml}")
                self._log_coverage_canvas_state("new_project_without_fence", map_yaml=map_yaml)
                return

        self._log_coverage_canvas_state("new_project", map_yaml=map_yaml)
        self.statusbar_left.config(text=f"New project ready: {map_yaml}")

    def open_project(self):
        """打开项目"""
        project_file_path = filedialog.askopenfilename(
            title="Select Project File",
            filetypes=[("MapTools project", "*.mapproj"), ("All files", "*.*")],
            initialdir=os.getcwd(),
        )
        if not project_file_path:
            return

        try:
            self._open_project_file(project_file_path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_error(
                problem=f"项目打开失败: {e}",
                impact="项目未加载",
                suggestion="确认 .mapproj、project.json 和底图路径完整可访问",
            )
            self.statusbar_left.config(text="Load project failed")

    def _open_project_file(self, project_file_path: str):
        self.statusbar_left.config(text=f"Loading project file {project_file_path}...")
        self.update()
        if not self.project_manager.load_project_file(project_file_path):
            self._show_error(
                problem="工程文件加载失败",
                impact="项目未被打开",
                suggestion="确认 .mapproj 文件存在且 project_dir 可访问",
            )
            self.statusbar_left.config(text="Load project failed")
            return
        dir_path = self.project_manager.project_dir
        try:
            project_note = self._restore_project_extras(dir_path)
            params_note = self._restore_coverage_planner_params(dir_path)
            start_note = self._restore_coverage_start_points(dir_path)
            unknown_note = self._compact_unknown_forbidden_regions()
            self._clear_command_history()
            self._current_project_dir = dir_path
            self.canvas.set_map_data(self.map_data)
            self.canvas.set_annotations(self.annotations)
            self.canvas.refresh()
            self._log_coverage_canvas_state("open_project_file", project_file=project_file_path)
            status = f"Loaded project: {dir_path}"
            notes = ", ".join(note for note in (project_note, params_note, start_note, unknown_note) if note)
            if notes:
                status += f" ({notes})"
            self.statusbar_left.config(text=status)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_error(
                problem=f"项目附加资源恢复失败: {e}",
                impact="项目主体已加载，但部分覆盖路径或区域标签可能缺失",
                suggestion="检查 areas.json 与 coverage_path_master.yaml 是否存在且格式正确",
            )
            self.canvas.set_map_data(self.map_data)
            self.canvas.set_annotations(self.annotations)
            self.canvas.refresh()
            self._log_coverage_canvas_state("open_project_file_partial", project_file=project_file_path)
            self.statusbar_left.config(text=f"Loaded project with partial extras: {dir_path}")

    def open_resource(self):
        """统一主入口：选择 YAML 文件或项目目录并自动识别。"""
        resource_path = self._choose_resource_path()
        if not resource_path:
            return

        self.statusbar_left.config(text=f"Loading {resource_path}...")
        self.update()
        try:
            self._open_resource(resource_path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_error(
                problem=f"资源打开失败: {e}",
                impact="资源未导入到当前会话",
                suggestion="若是目录请使用项目目录；若是文件请确认 YAML schema 正确",
            )
            self.statusbar_left.config(text="Load failed")

    def _choose_resource_path(self) -> str | None:
        # 单入口：不先询问资源类型。先选文件，取消后再选目录。
        file_path = filedialog.askopenfilename(
            title="Open Resource File",
            filetypes=[
                ("Resource files", "*.yaml *.yml *.mapproj"),
                ("YAML files", "*.yaml *.yml"),
                ("MapTools project", "*.mapproj"),
                ("All files", "*.*"),
            ],
            initialdir=os.getcwd(),
        )
        if file_path:
            return file_path

        dir_path = filedialog.askdirectory(
            title="Open Resource Directory (Project)",
            initialdir=os.getcwd(),
        )
        return dir_path or None

    def _open_project_dir(self, dir_path: str):
        """加载项目目录资源"""
        self.statusbar_left.config(text=f"Loading project from {dir_path}...")
        self.update()

        if not self.project_manager.load_project(dir_path):
            self._show_error("项目加载失败", "项目未被打开", "确认目录包含 project.json 且底图路径可访问")
            self.statusbar_left.config(text="Load project failed")
            return

        try:
            project_note = self._restore_project_extras(dir_path)
            unknown_note = self._compact_unknown_forbidden_regions()
            self._clear_command_history()
            self._current_project_dir = dir_path
            self.canvas.set_map_data(self.map_data)
            self.canvas.set_annotations(self.annotations)
            self.canvas.refresh()
            self._log_coverage_canvas_state("open_project_dir", project_dir=dir_path)
            status = f"Loaded project: {dir_path}"
            notes = ", ".join(note for note in (project_note, unknown_note) if note)
            if notes:
                status += f" ({notes})"
            self.statusbar_left.config(text=status)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_error(
                problem=f"项目附加资源恢复失败: {e}",
                impact="项目主体已加载，但部分覆盖路径或区域标签可能缺失",
                suggestion="检查 areas.json 与 coverage_path_master.yaml 是否存在且格式正确",
            )
            self.canvas.set_map_data(self.map_data)
            self.canvas.set_annotations(self.annotations)
            self.canvas.refresh()
            self._log_coverage_canvas_state("open_project_dir_partial", project_dir=dir_path)
            self.statusbar_left.config(text=f"Loaded project with partial extras: {dir_path}")

    def _compact_unknown_forbidden_regions(self) -> str:
        removed = compact_unknown_forbidden_regions(self.annotations)
        if removed <= 0:
            return ""
        return f"unknown_forbidden_compacted={removed}"

    def _restore_project_extras(self, dir_path: str) -> str:
        notes = []

        coverage_repo_dir = Path(dir_path) / "coverage_repo"
        self.coverage_path_manager.set_nodes([])
        self.coverage_path_manager.current_file_path = None
        self.coverage_path_manager.is_dirty = False

        self.canvas.clear_reference_trajectory()
        reference_path = coverage_repo_dir / "reference_trajectory.json"
        if reference_path.exists():
            payload = json.loads(reference_path.read_text(encoding="utf-8"))
            trajectory_world = [tuple(point) for point in payload.get("points", [])]
            if trajectory_world and not any(
                self.annotations.iter_constraint_segments("electronic_fence", closed=False)
            ):
                self._replace_electronic_fence_segments(
                    trajectory_world,
                    source_path=str(reference_path),
                )
                notes.append(f"fence_points={len(trajectory_world)}")

        areas_json = os.path.join(dir_path, "areas.json")
        if (not self.annotations.area_labels) and os.path.exists(areas_json):
            area_count = import_area_labels_json(areas_json, self.annotations)
            if area_count:
                notes.append(f"areas={area_count}")

        map_id = self._resolve_navigation_map_id(dir_path)
        if map_id and not self.coverage_path_manager.nodes:
            coverage_yaml = coverage_repo_dir / map_id / "coverage_path_master.yaml"
            if coverage_yaml.exists():
                result = import_coverage_repo(
                    str(coverage_yaml),
                    self.map_data,
                    self.coverage_path_manager,
                    self.annotations,
                    restore_area_labels=not bool(self.annotations.area_labels),
                )
                notes.append(f"path_nodes={result.imported_nodes}")
        return ", ".join(notes)

    def _resolve_navigation_map_id(self, project_dir: str | None = None) -> str:
        """Return the map id exported for navigation/coverage runtime assets.

        When a project is open or being saved, the project directory name is
        the stable external map identity used by navigation packages.
        """

        for candidate in (
            project_dir,
            self.__dict__.get("_current_project_dir"),
            self.__dict__.get("project_manager").project_dir
            if self.__dict__.get("project_manager") is not None else None,
        ):
            if candidate:
                name = Path(candidate).expanduser().resolve().name
                if name:
                    return name

        if self.map_data.yaml_path:
            yaml_path = Path(self.map_data.yaml_path)
            return yaml_path.stem
        return "editor_map"

    def _restore_coverage_planner_params(self, dir_path: str) -> str:
        try:
            values = load_coverage_planner_params(dir_path)
        except Exception as exc:
            self._show_warning(
                problem=f"覆盖路径参数加载失败: {exc}",
                impact="工程主体继续打开，但覆盖路径参数将使用默认值或本次会话值",
                suggestion=f"检查 {COVERAGE_PLANNER_PARAMS_FILENAME} 是否为有效 JSON 和合法参数",
            )
            return "coverage_params=invalid"
        if values is None:
            self.__dict__.pop("_last_coverage_dialog_values", None)
            return ""
        self._last_coverage_dialog_values = values
        return "coverage_params=loaded"

    def _restore_coverage_start_points(self, dir_path: str) -> str:
        try:
            start_points = load_coverage_start_points(dir_path, self.annotations)
        except Exception as exc:
            self._show_warning(
                problem=f"覆盖路径起点加载失败: {exc}",
                impact="工程主体继续打开，但上一次起点不会恢复",
                suggestion=f"检查 {COVERAGE_START_POINTS_FILENAME} 是否为有效 JSON，且区域未被修改",
            )
            self._coverage_start_points_by_area_id = {}
            self._coverage_start_fingerprints_by_area_id = {}
            return "coverage_start_points=invalid"
        self._coverage_start_points_by_area_id = dict(start_points)
        areas_by_id = {area_room_id(area): area for area in self.annotations.area_labels}
        self._coverage_start_fingerprints_by_area_id = {
            int(area_id): area_label_fingerprint(areas_by_id[int(area_id)])
            for area_id in start_points
            if int(area_id) in areas_by_id
        }
        if not start_points:
            return ""
        return f"coverage_start_points={len(start_points)}"

    def _prompt_save_coverage_planner_params(self, dir_path: str) -> None:
        values = self.__dict__.get("_last_coverage_dialog_values")
        if not values:
            return
        params_path = coverage_planner_params_path(dir_path)
        if params_path.exists():
            message = "工程中已存在覆盖路径参数，是否用当前参数覆盖？"
        else:
            message = "是否保存当前覆盖路径参数到工程？"
        if not messagebox.askyesno("Coverage Planner Params", message):
            return
        save_coverage_planner_params(dir_path, values)

    def _save_project_extras(self, dir_path: str) -> None:
        if "_last_project_extra_warnings" not in self.__dict__:
            self._last_project_extra_warnings = []
        coverage_repo_dir = Path(dir_path) / "coverage_repo"
        coverage_repo_dir.mkdir(parents=True, exist_ok=True)
        legacy_coverage_tsv = Path(dir_path) / "coverage_paths.tsv"
        coverage_repo_tsv = coverage_repo_dir / "coverage_paths.tsv"
        if legacy_coverage_tsv.exists():
            legacy_coverage_tsv.unlink()
        if coverage_repo_tsv.exists():
            coverage_repo_tsv.unlink()

        map_id = self._resolve_navigation_map_id(dir_path)
        repo_subdir = coverage_repo_dir / map_id
        legacy_repo_subdir = Path(dir_path) / map_id
        if self.coverage_path_manager.nodes and self.annotations.area_labels and self.map_data.metadata:
            preflight = run_export_preflight(
                self.map_data,
                self.annotations,
                output_root=str(coverage_repo_dir),
                map_id=map_id,
                path_manager=self.coverage_path_manager,
            )
            self._write_coverage_repo_preflight_report(coverage_repo_dir, map_id, preflight)
            if preflight.issues:
                self._last_project_extra_warnings.extend(preflight.issues)
            else:
                try:
                    export_coverage_repo(
                        self.map_data,
                        self.annotations,
                        output_root=str(coverage_repo_dir),
                        map_id=map_id,
                        map_version=1,
                        path_manager=self.coverage_path_manager,
                        auto_generate_missing=False,
                        allow_partial_export=True,
                    )
                    self._last_project_extra_warnings.extend(preflight.warnings)
                    if legacy_repo_subdir.exists():
                        shutil.rmtree(legacy_repo_subdir)
                except Exception as exc:
                    self._last_project_extra_warnings.append(f"coverage_repo_export_failed: {exc}")
        elif repo_subdir.exists():
            shutil.rmtree(repo_subdir)
            if legacy_repo_subdir.exists():
                shutil.rmtree(legacy_repo_subdir)

        reference_path = coverage_repo_dir / "reference_trajectory.json"
        legacy_reference_path = Path(dir_path) / "reference_trajectory.json"
        fence_segment = next(
            self.annotations.iter_constraint_segments("electronic_fence", closed=False),
            None,
        )
        trajectory_world = list(fence_segment.points) if fence_segment is not None else []
        if trajectory_world:
            reference_path.write_text(
                json.dumps({"points": trajectory_world}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        elif reference_path.exists():
            reference_path.unlink()
        if legacy_reference_path.exists():
            legacy_reference_path.unlink()
        save_coverage_start_points(
            dir_path,
            self.annotations,
            self._valid_coverage_start_points_for_current_areas(),
        )

    def _write_coverage_repo_preflight_report(self, coverage_repo_dir: Path, map_id: str, preflight) -> None:
        report_path = coverage_repo_dir / "export_preflight_report.json"
        report = {
            "map_id": map_id,
            "ok": bool(preflight.ok),
            "issues": list(preflight.issues),
            "warnings": list(getattr(preflight, "warnings", []) or []),
            "repo_dir": str(preflight.repo_dir.relative_to(coverage_repo_dir.expanduser().resolve())),
            "expected_files": list(preflight.expected_files),
            "area_count": int(preflight.area_count),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _reset_project_session(self) -> None:
        self._clear_command_history()
        self.annotations = Annotations()
        self.project_manager.annotations = self.annotations
        self.canvas.set_annotations(self.annotations)
        self.coverage_path_manager.set_nodes([])
        self.coverage_path_manager.current_file_path = None
        self.coverage_path_manager.is_dirty = False
        self.canvas.clear_reference_trajectory()
        self._current_project_dir = None
        self._coverage_start_points_by_area_id = {}
        self._coverage_start_fingerprints_by_area_id = {}

    def _clear_command_history(self) -> None:
        self.command_manager.undo_stack.clear()
        self.command_manager.redo_stack.clear()

    def export_nav2(self):
        """导出Nav2格式"""
        if not self.map_data.metadata:
            self._show_warning(
                problem="未加载地图",
                impact="无法导出 Nav2 资源",
                suggestion="先加载地图后再导出",
            )
            return

        dir_path = filedialog.askdirectory(title="Select Export Directory")
        if dir_path:
            try:
                exporter = Exporter(self.map_data, self.annotations)
                exporter.export(dir_path)
                messagebox.showinfo("Success", f"Exported to {dir_path}")
                self.statusbar_left.config(text=f"Exported to {dir_path}")
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._show_error(
                    problem=f"Nav2 导出失败: {e}",
                    impact="未生成目标导出文件",
                    suggestion="检查输出目录权限与地图/标注数据完整性后重试",
                )

    def export_coverage_repo(self):
        """导出供算法直接使用的 coverage_repo 产物"""
        if not self.map_data.metadata:
            self._show_warning(
                problem="未加载地图",
                impact="无法导出 coverage repo",
                suggestion="先打开地图或项目，再执行导出",
            )
            return
        if not self.annotations.area_labels:
            self._show_warning(
                problem="未标注区域",
                impact="无法生成按房间组织的 coverage repo",
                suggestion="先添加 Area Label 再导出",
            )
            return
        if not self.coverage_path_manager.nodes:
            self._show_warning(
                problem="未生成覆盖路径",
                impact="无法导出 coverage repo",
                suggestion="先生成或导入覆盖路径后再导出（导出不会自动生成路径）",
            )
            return
        repaired_rooms = repair_path_rooms_from_area_labels(
            self.coverage_path_manager,
            self.annotations,
        )
        if repaired_rooms:
            self.canvas.refresh()
        area_ids = {area_room_id(area) for area in self.annotations.area_labels}
        path_rooms = {int(node.room) for node in self.coverage_path_manager.nodes}
        missing_rooms = sorted(area_ids - path_rooms)
        allow_partial_export = False
        if missing_rooms:
            preview = ", ".join(str(rid) for rid in missing_rooms[:6])
            more = "" if len(missing_rooms) <= 6 else f" 等{len(missing_rooms)}个"
            allow_partial_export = messagebox.askyesno(
                "Missing Coverage Paths",
                (
                    "部分区域没有覆盖路径。\n"
                    f"缺失房间: {preview}{more}\n\n"
                    "是否只导出已有路径（不自动生成缺失路径）?"
                ),
            )
            if not allow_partial_export:
                self.statusbar_left.config(text="Coverage repo export canceled")
                return

        dir_path = filedialog.askdirectory(title="Select Coverage Repo Root Directory")
        if not dir_path:
            return

        map_id = self._resolve_navigation_map_id()
        try:
            preflight = run_export_preflight(
                self.map_data,
                self.annotations,
                output_root=dir_path,
                map_id=map_id,
            )
            if not preflight.ok:
                self._show_error(
                    problem="导出前预检失败",
                    impact="无法生成 coverage repo 产物",
                    suggestion="; ".join(preflight.issues),
                    title="Export Blocked",
                )
                self.statusbar_left.config(text="Coverage repo export preflight failed")
                return

            checklist = "\n".join(f"- {name}" for name in preflight.expected_files)
            if not messagebox.askyesno(
                "Export Checklist",
                (
                    f"目标地图: {map_id}\n"
                    f"区域数: {preflight.area_count}\n"
                    f"输出目录: {preflight.output_root}\n\n"
                    f"将生成文件:\n{checklist}\n\n继续导出?"
                ),
            ):
                self.statusbar_left.config(text="Coverage repo export canceled")
                return

            result = export_coverage_repo(
                self.map_data,
                self.annotations,
                output_root=dir_path,
                map_id=map_id,
                map_version=1,
                path_manager=self.coverage_path_manager,
                auto_generate_missing=False,
                allow_partial_export=allow_partial_export,
            )
            summary_lines = "\n".join(f"- {name}" for name in result.output_files)
            messagebox.showinfo(
                "Success",
                (
                    f"Exported coverage repo to {result.repo_dir}\n"
                    f"Rooms: {result.room_count}, Paths: {result.path_count}\n"
                    f"Output files:\n{summary_lines}"
                ),
            )
            self.statusbar_left.config(
                text=f"Coverage repo exported: rooms={result.room_count}, paths={result.path_count}, dir={result.repo_dir}"
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_error(
                problem=f"Coverage Repo 导出失败: {e}",
                impact="未生成 coverage repo 输出文件",
                suggestion="先通过导出前预检，再检查路径数据与区域标注是否有效",
            )

    def undo(self):
        self.command_manager.undo()
        self.canvas.refresh()
        self.statusbar_left.config(text="Undo")

    def redo(self):
        self.command_manager.redo()
        self.canvas.refresh()
        self.statusbar_left.config(text="Redo")

    def open_map(self):
        """打开 YAML 资源：标准地图或 coverage repo"""
        file_path = filedialog.askopenfilename(
            title="Select YAML",
            filetypes=[("YAML files", "*.yaml"), ("All files", "*.*")],
            initialdir=os.getcwd()
        )

        if not file_path:
            return

        self.statusbar_left.config(text=f"Loading {file_path}...")
        self.update()

        try:
            self._open_resource(file_path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_error(
                problem=f"资源打开失败: {e}",
                impact="当前文件未被导入",
                suggestion="确认文件类型为地图 YAML/coverage repo YAML，且内容结构正确",
            )
            self.statusbar_left.config(text="Load failed")

    def _open_resource(self, resource_path: str):
        """统一资源入口：支持地图 YAML、coverage repo YAML、项目目录。"""
        kind = self._detect_resource_kind(resource_path)
        if kind == "project_file":
            self._open_project_file(resource_path)
            return
        if kind == "project":
            self._open_project_dir(resource_path)
            return
        if kind == "map_yaml":
            self._load_yaml_resource(resource_path, expected_kind="map")
            return
        if kind == "coverage_repo_yaml":
            self._load_yaml_resource(resource_path, expected_kind="coverage_repo")
            return
        raise ValueError(f"unsupported resource kind: {kind}")

    def _detect_resource_kind(self, resource_path: str) -> str:
        normalized = os.path.expanduser(resource_path)
        if os.path.isdir(normalized):
            return "project"
        if not os.path.isfile(normalized):
            raise ValueError(f"resource not found: {resource_path}")
        ext = os.path.splitext(normalized)[1].lower()
        if ext == ".mapproj":
            return "project_file"
        if ext not in {".yaml", ".yml"}:
            raise ValueError("only YAML/.mapproj file or project directory is supported")

        yaml_kind = detect_yaml_kind(normalized)
        if yaml_kind == "map":
            return "map_yaml"
        if yaml_kind == "coverage_repo":
            return "coverage_repo_yaml"
        raise ValueError("unknown yaml schema")

    def _import_coverage_repo_yaml(self):
        """显式导入 coverage_path_master.yaml"""
        initialdir = os.path.dirname(self.map_data.yaml_path) if self.map_data.yaml_path else os.getcwd()
        file_path = filedialog.askopenfilename(
            title="Import Coverage Repo YAML",
            initialdir=initialdir,
            filetypes=[("YAML files", "*.yaml"), ("All files", "*.*")],
        )
        if not file_path:
            return

        self.statusbar_left.config(text=f"Importing {file_path}...")
        self.update()
        try:
            self._load_yaml_resource(file_path, expected_kind="coverage_repo")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_error(
                problem=f"Coverage Repo 导入失败: {e}",
                impact="覆盖路径与区域标签未更新",
                suggestion="确认 YAML 为 coverage_path_master.yaml 且 map_id 可匹配到底图",
            )
            self.statusbar_left.config(text="Coverage repo import failed")

    def _load_yaml_resource(self, file_path: str, expected_kind: str | None = None):
        kind = detect_yaml_kind(file_path)
        if expected_kind and kind != expected_kind:
            raise ValueError(f"expected {expected_kind} yaml, got {kind}")

        if kind == "map":
            if not self.map_data.load(file_path):
                raise ValueError("failed to load map yaml")
            self._current_project_dir = None
            self.canvas.set_map_data(self.map_data)
            self.statusbar_left.config(text=f"Loaded map: {file_path} ({self.map_data.width}x{self.map_data.height})")
            return

        if kind == "coverage_repo":
            result = import_coverage_repo(
                file_path,
                self.map_data,
                self.coverage_path_manager,
                self.annotations,
                restore_area_labels=not bool(self.annotations.area_labels),
            )
            self.canvas.set_map_data(self.map_data)
            self.canvas.set_annotations(self.annotations)
            self.canvas.refresh()
            summary = result.summary
            summary_text = (
                f"Map: {summary.map_id}\n"
                f"Map YAML: {summary.map_yaml}\n"
                f"Rooms: {summary.rooms}\n"
                f"Path Nodes: {summary.nodes}\n"
                f"Segments: {summary.segments}\n"
                f"Area Labels: {summary.area_labels}"
            )
            messagebox.showinfo("Import Summary", summary_text)
            self.statusbar_left.config(
                text=(
                    f"Imported coverage repo: map={result.map_id}, rooms={result.imported_rooms}, "
                    f"nodes={result.imported_nodes}, labels={result.imported_area_labels}"
                )
            )
            return

        raise ValueError("unknown yaml schema")

    def _format_issue_message(self, problem: str, impact: str, suggestion: str) -> str:
        return f"问题: {problem}\n影响: {impact}\n建议: {suggestion}"

    def _log_coverage_canvas_state(self, action: str, **extra) -> None:
        """打印当前画布覆盖路径统计，便于排查显示链问题。"""

        stats = self.canvas.coverage_debug_stats() if getattr(self, "canvas", None) else {}
        payload = {**stats, **extra}
        details = " ".join(f"{key}={value!r}" for key, value in payload.items())
        print(f"[coverage-debug] action={action} {details}".rstrip())

    def _log_free_space_semantic_state(self, action: str, **extra) -> None:
        """打印自由区语义切换/显示关键状态。"""
        details = " ".join(f"{key}={value!r}" for key, value in extra.items())
        print(f"[free-space-debug] action={action} {details}".rstrip())

    def _show_error(self, problem: str, impact: str, suggestion: str, title: str = "Error"):
        try:
            messagebox.showerror(title, self._format_issue_message(problem, impact, suggestion))
        except tk.TclError:
            return

    def _show_warning(self, problem: str, impact: str, suggestion: str, title: str = "Warning"):
        try:
            messagebox.showwarning(title, self._format_issue_message(problem, impact, suggestion))
        except tk.TclError:
            return

    def _prompt_load_electronic_fence(self) -> bool:
        selected_path = filedialog.askopenfilename(
            title="载入电子围栏轨迹",
            initialdir=os.getcwd(),
            filetypes=[
                ("Trajectory JSONL", "*.jsonl"),
                ("Summary JSON", "summary.json *.json"),
                ("All files", "*.*"),
            ],
        )
        if not selected_path:
            selected_path = filedialog.askdirectory(
                title="载入电子围栏目录",
                initialdir=os.getcwd(),
            )
        if not selected_path:
            return False

        self._load_electronic_fence_path(selected_path)
        return True

    def load_electronic_fence(self):
        """载入离线轨迹参考层，显示为细蓝虚线。"""
        if not self.map_data or not self.map_data.metadata:
            self._show_warning(
                problem="未加载地图",
                impact="无法叠加显示电子围栏轨迹",
                suggestion="先打开地图或项目，再载入电子围栏",
            )
            return

        if not self._prompt_load_electronic_fence():
            return

    def _load_electronic_fence_path(self, selected_path: str) -> None:
        """内部电子围栏恢复逻辑；正式入口由 New/Open Project 驱动。"""

        self.statusbar_left.config(text=f"Loading electronic fence: {selected_path}...")
        self.update()

        try:
            trajectory_path = self._resolve_electronic_fence_path(selected_path)
            trajectory_world = self._load_trajectory_world_points(trajectory_path)
            self._replace_electronic_fence_segments(
                trajectory_world,
                source_path=trajectory_path,
            )
            self.canvas.clear_reference_trajectory()
            self.canvas.refresh()
            self.statusbar_left.config(
                text=f"已载入电子围栏并转为可编辑约束段: {trajectory_path} ({len(trajectory_world)} points)"
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_error(
                problem=f"载入电子围栏失败: {e}",
                impact="电子围栏未导入为可编辑约束段",
                suggestion="确认输入为 trajectory_from_tf.jsonl、summary.json 或包含它们的目录",
            )
            self.statusbar_left.config(text="Load electronic fence failed")
            raise

    def _replace_electronic_fence_segments(self, trajectory_world, *, source_path: str = "") -> None:
        if not trajectory_world or len(trajectory_world) < 2:
            raise ValueError("电子围栏轨迹点数不足，无法形成可编辑线段")
        self.annotations.replace_constraint_segments(
            "electronic_fence",
            [
                ConstraintSegment(
                    id="electronic_fence",
                    name="Electronic Fence",
                    points=[tuple(point) for point in trajectory_world],
                    closed=False,
                    constraint_type="electronic_fence",
                    color=constraint_base_color("electronic_fence"),
                    metadata={},
                )
            ],
        )

    def _resolve_electronic_fence_path(self, selected_path: str) -> str:
        path = Path(os.path.expanduser(selected_path)).resolve()
        if path.is_dir():
            jsonl_path = path / "trajectory_from_tf.jsonl"
            if jsonl_path.exists():
                return str(jsonl_path)
            summary_path = path / "summary.json"
            if summary_path.exists():
                data = json.loads(summary_path.read_text(encoding="utf-8"))
                jsonl_from_summary = data.get("jsonl_path", "")
                if jsonl_from_summary:
                    jsonl_path = Path(jsonl_from_summary).expanduser()
                    if not jsonl_path.is_absolute():
                        jsonl_path = summary_path.parent / jsonl_path
                    if jsonl_path.exists():
                        return str(jsonl_path.resolve())
            raise FileNotFoundError(f"目录中未找到 trajectory_from_tf.jsonl: {path}")

        if path.name == "summary.json":
            data = json.loads(path.read_text(encoding="utf-8"))
            jsonl_from_summary = data.get("jsonl_path", "")
            if not jsonl_from_summary:
                raise ValueError("summary.json 未提供 jsonl_path")
            jsonl_path = Path(jsonl_from_summary).expanduser()
            if not jsonl_path.is_absolute():
                jsonl_path = path.parent / jsonl_path
            if not jsonl_path.exists():
                raise FileNotFoundError(f"summary.json 指向的轨迹文件不存在: {jsonl_path}")
            return str(jsonl_path.resolve())

        if path.suffix.lower() == ".jsonl":
            return str(path)

        raise ValueError(f"不支持的电子围栏输入: {path}")

    def _load_trajectory_world_points(self, trajectory_path: str) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = []
        with open(trajectory_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                text = line.strip()
                if not text:
                    continue
                payload = json.loads(text)
                pose = payload.get("pose", {})
                if "x" not in pose or "y" not in pose:
                    raise ValueError(f"第 {line_no} 行缺少 pose.x / pose.y")
                points.append((float(pose["x"]), float(pose["y"])))

        if len(points) < 2:
            raise ValueError("轨迹点数量不足，至少需要 2 个点")
        return points

    def _resolve_planner_config(self, requested_config):
        return requested_config, None

    def _selected_constraint_segment_or_none(self, segment=None):
        target = segment if segment is not None else getattr(self.canvas, "selected_item", None)
        if target is None or getattr(self.canvas, "selected_type", None) != "constraint_segments" and segment is None:
            return None
        if not hasattr(target, "constraint_type") or not hasattr(target, "points"):
            return None
        return target

    def _commit_constraint_segments(self, new_segments):
        cmd = UpdateConstraintSegmentsCommand(
            self.annotations,
            self.annotations.constraint_segments,
            new_segments,
            refresh_cb=self.canvas.refresh,
        )
        self.command_manager.execute(cmd)

    @staticmethod
    def _constraint_type_defaults(constraint_type: str):
        mapping = {
            "electronic_fence": (False, constraint_base_color("electronic_fence"), "Electronic Fence"),
            "virtual_wall": (False, constraint_base_color("virtual_wall"), "Virtual Wall"),
            "forbidden_zone": (True, constraint_base_color("forbidden_zone"), "Forbidden Zone"),
            "pass_only": (True, constraint_base_color("pass_only"), "Pass Only Zone"),
            "no_coverage": (True, constraint_base_color("no_coverage"), "No Coverage"),
        }
        return mapping.get(constraint_type, (False, "#bfbfbf", "Constraint Segment"))

    def _split_constraint_segment_at_vertex(self, segment, vertex_idx: int):
        target = self._selected_constraint_segment_or_none(segment)
        if target is None:
            return
        if not target.closed and (vertex_idx <= 0 or vertex_idx >= len(target.points) - 1):
            self._show_warning(
                problem="切开点无效",
                impact="当前约束段保持不变",
                suggestion="请选择内部顶点进行切开",
            )
            return
        if target.closed and (vertex_idx < 0 or vertex_idx >= len(target.points)):
            self._show_warning(
                problem="切开点无效",
                impact="当前约束段保持不变",
                suggestion="请选择闭合段上的顶点进行切开",
            )
            return

        old_segments = self.annotations.constraint_segments
        new_segments = []
        for item in old_segments:
            if item.id != target.id:
                new_segments.append(copy.deepcopy(item))
                continue
            base_name = target.name or "Constraint Segment"
            if target.closed:
                ordered_points = [tuple(point) for point in (target.points[vertex_idx:] + target.points[: vertex_idx + 1])]
                new_segments.append(
                    copy.deepcopy(type(target)(
                        id=target.id,
                        name=base_name,
                        points=ordered_points,
                        closed=False,
                        constraint_type=target.constraint_type,
                        color=target.color,
                        metadata=dict(target.metadata),
                    ))
                )
            else:
                first_points = [tuple(point) for point in target.points[: vertex_idx + 1]]
                second_points = [tuple(point) for point in target.points[vertex_idx:]]
                new_segments.append(
                    copy.deepcopy(type(target)(
                        id=f"{target.id}__a",
                        name=f"{base_name} A",
                        points=first_points,
                        closed=False,
                        constraint_type=target.constraint_type,
                        color=target.color,
                        metadata=dict(target.metadata),
                    ))
                )
                new_segments.append(
                    copy.deepcopy(type(target)(
                        id=f"{target.id}__b",
                        name=f"{base_name} B",
                        points=second_points,
                        closed=False,
                        constraint_type=target.constraint_type,
                        color=target.color,
                        metadata=dict(target.metadata),
                    ))
                )
        self._commit_constraint_segments(new_segments)
        self.statusbar_left.config(text=f"Constraint segment split at vertex {vertex_idx}")

    def _toggle_constraint_segment_closed(self, segment=None):
        target = self._selected_constraint_segment_or_none(segment)
        if target is None:
            return
        new_closed = not bool(target.closed)
        if new_closed and len(target.points) < 3:
            self._show_warning(
                problem="顶点数量不足，无法闭合",
                impact="当前约束段保持开口状态",
                suggestion="至少保留 3 个点后再闭合",
            )
            return
        old_segments = self.annotations.constraint_segments
        new_segments = []
        for item in old_segments:
            if item.id != target.id:
                new_segments.append(copy.deepcopy(item))
                continue
            updated = copy.deepcopy(item)
            updated.closed = new_closed
            new_segments.append(updated)
        self._commit_constraint_segments(new_segments)
        self.statusbar_left.config(text=f"Constraint segment {'closed' if new_closed else 'opened'}")

    @staticmethod
    def _same_point(a, b, tol: float = 0.05) -> bool:
        return abs(float(a[0]) - float(b[0])) <= tol and abs(float(a[1]) - float(b[1])) <= tol

    def _find_mergeable_constraint_segment(self, segment):
        target = self._selected_constraint_segment_or_none(segment)
        if target is None or target.closed or len(target.points) < 2:
            return None
        for other in self.annotations.constraint_segments:
            if other.id == target.id:
                continue
            if other.constraint_type != target.constraint_type or other.closed or len(other.points) < 2:
                continue
            endpoints = (
                (target.points[0], other.points[0]),
                (target.points[0], other.points[-1]),
                (target.points[-1], other.points[0]),
                (target.points[-1], other.points[-1]),
            )
            if any(self._same_point(a, b) for a, b in endpoints):
                return other
        return None

    def _can_merge_constraint_segment(self, segment=None):
        return self._find_mergeable_constraint_segment(segment) is not None

    def _merge_constraint_segment(self, segment=None):
        target = self._selected_constraint_segment_or_none(segment)
        if target is None:
            return
        other = self._find_mergeable_constraint_segment(target)
        if other is None:
            self._show_warning(
                problem="没有可合并的相邻约束段",
                impact="当前约束段保持不变",
                suggestion="确保两条开口段类型一致且端点重合后再合并",
            )
            return

        left = [tuple(point) for point in target.points]
        right = [tuple(point) for point in other.points]
        if self._same_point(left[-1], right[0]):
            merged_points = left + right[1:]
        elif self._same_point(left[0], right[-1]):
            merged_points = right + left[1:]
        elif self._same_point(left[0], right[0]):
            merged_points = list(reversed(right)) + left[1:]
        elif self._same_point(left[-1], right[-1]):
            merged_points = left + list(reversed(right[:-1]))
        else:
            self._show_warning(
                problem="未找到可合并的公共端点",
                impact="当前约束段保持不变",
                suggestion="请先让两段端点重合后再合并",
            )
            return

        old_segments = self.annotations.constraint_segments
        new_segments = []
        for item in old_segments:
            if item.id == other.id:
                continue
            if item.id != target.id:
                new_segments.append(copy.deepcopy(item))
                continue
            updated = copy.deepcopy(item)
            updated.points = merged_points
            updated.closed = False
            new_segments.append(updated)
        self._commit_constraint_segments(new_segments)
        self.statusbar_left.config(text=f"Constraint segments merged into {target.name}")

    def _merge_selected_constraint_segments(self):
        selected_segments = self.canvas.get_selected_constraint_segments()
        if len(selected_segments) < 2:
            self._show_warning(
                problem="已选约束段不足",
                impact="当前约束段保持不变",
                suggestion="请至少选择 2 条约束段后再合并",
            )
            return

        selected_ids = {segment.id for segment in selected_segments}
        types = {segment.constraint_type for segment in selected_segments}
        if len(types) != 1:
            self._show_warning(
                problem="所选约束段类型不一致",
                impact="当前约束段保持不变",
                suggestion="请只选择同类型约束段进行合并",
            )
            return
        if any(segment.closed for segment in selected_segments):
            self._show_warning(
                problem="存在闭合约束段，无法直接批量合并",
                impact="当前约束段保持不变",
                suggestion="请先把闭合段改为开口段，再进行批量合并",
            )
            return

        remaining = {segment.id: copy.deepcopy(segment) for segment in selected_segments}
        endpoint_buckets = {}
        for segment in selected_segments:
            for point in (segment.points[0], segment.points[-1]):
                matched_key = None
                for key in endpoint_buckets.keys():
                    if self._same_point(point, key):
                        matched_key = key
                        break
                if matched_key is None:
                    endpoint_buckets[(float(point[0]), float(point[1]))] = {segment.id}
                else:
                    endpoint_buckets[matched_key].add(segment.id)
        if any(len(bucket) > 2 for bucket in endpoint_buckets.values()):
            self._show_warning(
                problem="所选约束段存在分叉端点，无法自动合并",
                impact="当前约束段保持不变",
                suggestion="请拆分成线性链路后再批量合并",
            )
            return

        adjacency = {segment.id: set() for segment in selected_segments}
        for bucket in endpoint_buckets.values():
            ids = list(bucket)
            if len(ids) == 2:
                adjacency[ids[0]].add(ids[1])
                adjacency[ids[1]].add(ids[0])

        components = []
        visited = set()
        for segment in selected_segments:
            if segment.id in visited:
                continue
            stack = [segment.id]
            component = []
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                component.append(node)
                stack.extend(adjacency[node] - visited)
            components.append(component)

        merged_segments = []
        component_anchor_ids = set()
        for component in components:
            items = [remaining[item_id] for item_id in component]
            degree_one = [item.id for item in items if len(adjacency[item.id]) == 1]
            if len(component) == 1:
                merged_segments.append(items[0])
                component_anchor_ids.add(items[0].id)
                continue
            if len(degree_one) not in {0, 2}:
                self._show_warning(
                    problem="所选约束段无法组成单条连续链",
                    impact="当前约束段保持不变",
                    suggestion="请检查是否存在断裂或重复端点",
                )
                return

            if len(degree_one) == 2:
                current_id = degree_one[0]
            else:
                current_id = component[0]
            ordered_ids = []
            previous_id = None
            while current_id is not None:
                ordered_ids.append(current_id)
                next_candidates = [item_id for item_id in adjacency[current_id] if item_id != previous_id]
                previous_id, current_id = current_id, (next_candidates[0] if next_candidates else None)
                if current_id in ordered_ids:
                    ordered_ids.append(current_id)
                    break

            chain = [remaining[item_id] for item_id in ordered_ids if item_id in remaining]
            if not chain:
                continue
            merged_points = [tuple(point) for point in chain[0].points]
            for next_segment in chain[1:]:
                next_points = [tuple(point) for point in next_segment.points]
                if self._same_point(merged_points[-1], next_points[0]):
                    merged_points.extend(next_points[1:])
                elif self._same_point(merged_points[-1], next_points[-1]):
                    merged_points.extend(list(reversed(next_points[:-1])))
                elif self._same_point(merged_points[0], next_points[-1]):
                    merged_points = next_points[:-1] + merged_points
                elif self._same_point(merged_points[0], next_points[0]):
                    merged_points = list(reversed(next_points[1:])) + merged_points
                else:
                    self._show_warning(
                        problem="自动合并排序失败",
                        impact="当前约束段保持不变",
                        suggestion="请检查端点连接关系后重试",
                    )
                    return

            closed = len(degree_one) == 0 and len(merged_points) >= 3 and self._same_point(merged_points[0], merged_points[-1])
            anchor = chain[0]
            anchor.points = merged_points
            anchor.closed = closed
            merged_segments.append(anchor)
            component_anchor_ids.add(anchor.id)

        old_segments = self.annotations.constraint_segments
        new_segments = []
        for item in old_segments:
            if item.id not in selected_ids:
                new_segments.append(copy.deepcopy(item))
                continue
            if item.id in component_anchor_ids:
                merged = next(segment for segment in merged_segments if segment.id == item.id)
                new_segments.append(copy.deepcopy(merged))
        self._commit_constraint_segments(new_segments)
        self.canvas.selected_constraint_segment_ids = {segment.id for segment in merged_segments}
        if merged_segments:
            self.canvas.selected_item = merged_segments[0]
            self.canvas.selected_type = "constraint_segments"
        self.canvas.refresh()
        self.statusbar_left.config(text=f"Merged {len(selected_segments)} selected constraint segments")

    def _can_merge_selected_constraint_segments(self):
        selected_segments = self.canvas.get_selected_constraint_segments()
        if len(selected_segments) < 2:
            return False
        if len({segment.constraint_type for segment in selected_segments}) != 1:
            return False
        if any(segment.closed for segment in selected_segments):
            return False
        endpoint_buckets = {}
        for segment in selected_segments:
            if len(segment.points) < 2:
                return False
            for point in (segment.points[0], segment.points[-1]):
                matched_key = None
                for key in endpoint_buckets.keys():
                    if self._same_point(point, key):
                        matched_key = key
                        break
                if matched_key is None:
                    endpoint_buckets[(float(point[0]), float(point[1]))] = {segment.id}
                else:
                    endpoint_buckets[matched_key].add(segment.id)
        return any(len(bucket) == 2 for bucket in endpoint_buckets.values()) and not any(len(bucket) > 2 for bucket in endpoint_buckets.values())

    def _change_constraint_segment_type(self, segment, new_type: str):
        target = self._selected_constraint_segment_or_none(segment)
        if target is None:
            return
        closed_default, color_default, default_name = self._constraint_type_defaults(new_type)
        if closed_default and len(target.points) < 3:
            self._show_warning(
                problem="顶点数量不足，无法改成区域类约束",
                impact="当前约束段类型保持不变",
                suggestion="至少保留 3 个点后再改成禁止区、只通区或不规划覆盖",
            )
            return
        old_segments = self.annotations.constraint_segments
        new_segments = []
        for item in old_segments:
            if item.id != target.id:
                new_segments.append(copy.deepcopy(item))
                continue
            updated = copy.deepcopy(item)
            updated.constraint_type = new_type
            updated.closed = closed_default
            updated.color = color_default
            if updated.name in {"Electronic Fence", "Virtual Wall", "Forbidden Zone", "Pass Only Zone", "No Coverage", "Constraint Segment"}:
                updated.name = default_name
            new_segments.append(updated)
        self._commit_constraint_segments(new_segments)
        self.statusbar_left.config(text=f"Constraint segment type changed to {new_type}")

    # ==================== 覆盖路径生成 ====================
    def _on_generate_coverage_path(self, area_label, start_world_xy=None):
        """生成覆盖路径回调 (由 Canvas 右键菜单触发)

        Args:
            area_label: 目标区域标记
            start_world_xy: 可选的起点世界坐标 (wx, wy)，
                           若为 None 则使用区域多边形质心
        """
        if start_world_xy is not None:
            self._remember_coverage_start_point(area_label, start_world_xy)
            self._generate_coverage_path_for_area(area_label, start_world_xy=start_world_xy)
            return

        resolved_start = self._choose_coverage_start_point(area_label)
        if resolved_start == "pick":
            self.canvas._enter_pick_start_mode(area_label)
            return
        if resolved_start == "cancel":
            self.statusbar_left.config(text="Coverage path generation cancelled.")
            return
        self._generate_coverage_path_for_area(area_label, start_world_xy=resolved_start)

    def apply_room_id_to_selected_area(self, room_id: int) -> None:
        """Apply a new Room ID to the selected area and related path state."""

        selected = getattr(self.canvas, "selected_item", None)
        if getattr(self.canvas, "selected_type", None) != "area_labels" or selected is None:
            self._show_warning(
                problem="未选中区域",
                impact="无法修改 Room ID",
                suggestion="先用 Select 工具选中一个区域，再执行区域 Room ID 修改操作",
            )
            return

        try:
            new_room_id = validate_room_id(room_id)
            validate_unique_area_room_ids(
                self.annotations.area_labels,
                exclude_area_id=getattr(selected, "id", None),
            )
            if any(
                area.id != selected.id and area_room_id(area) == new_room_id
                for area in self.annotations.area_labels
            ):
                raise ValueError(f"duplicate room_id: {new_room_id}")
        except ValueError as exc:
            self._show_error(
                problem=f"Room ID 无效: {exc}",
                impact="区域编号未修改",
                suggestion="输入正整数，且不能与已有区域 Room ID 重复",
            )
            return

        old_room_id = area_room_id(selected)
        if old_room_id == new_room_id:
            self.statusbar_left.config(text=f"Room ID unchanged: {new_room_id}")
            return

        set_area_room_id(selected, new_room_id)
        if new_room_id >= self.annotations._next_area_id:
            self.annotations._next_area_id = new_room_id + 1
        manager = self.coverage_path_manager
        changed_nodes = 0
        for node in manager.nodes:
            if int(node.room) == old_room_id:
                node.room_id = new_room_id
                changed_nodes += 1
        if changed_nodes:
            manager.renumber_nodes()
            manager.is_dirty = True

        points = self.__dict__.setdefault("_coverage_start_points_by_area_id", {})
        fingerprints = self.__dict__.setdefault("_coverage_start_fingerprints_by_area_id", {})
        if old_room_id in points:
            points[new_room_id] = points.pop(old_room_id)
        if old_room_id in fingerprints:
            fingerprints.pop(old_room_id, None)
            fingerprints[new_room_id] = area_label_fingerprint(selected)

        self.annotations.change_stamp += 1
        self.canvas.refresh()
        path_panel = getattr(self.sidebar, "path_panel", None)
        if path_panel is not None and hasattr(path_panel, "set_draw_room"):
            path_panel.set_draw_room(new_room_id)
        self.statusbar_left.config(
            text=f"Updated selected area Room ID {old_room_id} -> {new_room_id}; path nodes updated: {changed_nodes}"
        )

    def _coverage_area_key(self, area_label) -> int:
        return area_room_id(area_label)

    def _remember_coverage_start_point(self, area_label, start_world_xy) -> None:
        if start_world_xy is None:
            return
        area_id = self._coverage_area_key(area_label)
        points = self.__dict__.setdefault("_coverage_start_points_by_area_id", {})
        fingerprints = self.__dict__.setdefault("_coverage_start_fingerprints_by_area_id", {})
        points[area_id] = (
            float(start_world_xy[0]),
            float(start_world_xy[1]),
        )
        fingerprints[area_id] = area_label_fingerprint(area_label)

    def _get_remembered_coverage_start_point(self, area_label):
        area_id = self._coverage_area_key(area_label)
        points = self.__dict__.get("_coverage_start_points_by_area_id", {})
        fingerprints = self.__dict__.get("_coverage_start_fingerprints_by_area_id", {})
        point = points.get(area_id)
        if fingerprints.get(area_id) != area_label_fingerprint(area_label):
            points.pop(area_id, None)
            fingerprints.pop(area_id, None)
            return None
        valid_point = valid_start_point_for_area(area_label, point)
        if valid_point is None:
            points.pop(area_id, None)
            fingerprints.pop(area_id, None)
            return None
        return valid_point

    def _valid_coverage_start_points_for_current_areas(self) -> dict[int, tuple[float, float]]:
        valid = {}
        for area_label in self.annotations.area_labels:
            point = self._get_remembered_coverage_start_point(area_label)
            if point is not None:
                valid[area_room_id(area_label)] = point
        return valid

    def _choose_coverage_start_point(self, area_label):
        remembered_start = self._get_remembered_coverage_start_point(area_label)
        area_name = str(getattr(area_label, "name", ""))
        if remembered_start is not None:
            if messagebox.askyesno(
                "Coverage Start Point",
                f"区域 {area_name} 是否使用上一次起点？",
            ):
                return remembered_start

        if messagebox.askyesno(
            "Coverage Start Point",
            f"区域 {area_name} 是否设置起点？",
        ):
            return "pick"

        if messagebox.askyesno(
            "Coverage Start Point",
            f"区域 {area_name} 是否使用默认起点？",
        ):
            return None

        return "cancel"

    def _generate_coverage_path_for_area(self, area_label, start_world_xy=None):
        """执行覆盖路径生成；外层负责确定起点来源。"""
        # 1. 弹出参数对话框
        config = show_coverage_dialog(
            self,
            input_summary=build_coverage_input_summary(
                self,
                area_name=getattr(area_label, "name", ""),
                start_point_set=bool(start_world_xy is not None),
            ),
        )
        if config is None:
            return
        config, planner_warning = self._resolve_planner_config(config)
        if planner_warning:
            self._show_warning(
                problem="CTC 模式不可用",
                impact="已自动降级为 basic 模式，覆盖路径流程会继续执行",
                suggestion=f"{planner_warning}; 如需启用请补齐依赖后重试",
                title="Planner Fallback",
            )
        self._log_coverage_canvas_state(
            "generate_before",
            area_id=int(area_label.area_id),
            area_name=getattr(area_label, "name", ""),
            start_world_xy=start_world_xy,
        )

        # 2. 准备地图二进制数据 (255: free, 0: obstacle/unknown)
        img_pil = self.map_data.get_display_image()
        if img_pil is None:
            self._show_error(
                problem="地图图像不可用",
                impact="无法生成覆盖路径",
                suggestion="重新加载地图后重试",
            )
            return

        img_arr = np.array(img_pil)
        planning_map_binary = build_total_free_map(self.map_data, self.annotations)

        # 3. 根据 AreaLabel 多边形生成 ROI Mask
        res = self.map_data.metadata.resolution
        origin_x, origin_y, _ = self.map_data.metadata.origin
        h = self.map_data.height

        poly_pixels = []
        for wx, wy in area_label.polygon:
            u = int(round((wx - origin_x) / res))
            v = int(round(h - (wy - origin_y) / res))
            poly_pixels.append([u, v])
        # 将当前地图与区域像素多边形显式传给 planner adapter；
        # 这些字段是产品层到算法层的输入真源，不应由下游从 room_binary 反推。
        config.map_yaml_path = str(self.map_data.yaml_path)
        config.region_polygon_px = [(int(p[0]), int(p[1])) for p in poly_pixels]
        config.artifacts_output_root = str(Path(self.map_data.yaml_path).resolve().parent / f"maptools_{config.planner_mode}_runs")
        
        roi_mask = build_area_region_mask(self.map_data, area_label)
        if roi_mask is None:
            self._show_error(
                problem="区域掩膜生成失败",
                impact="无法生成覆盖路径",
                suggestion="检查区域多边形后重试",
            )
            return

        # 4.5 计算起始点
        if start_world_xy is not None:
            # 使用用户手动指定的起点
            s_wx, s_wy = start_world_xy
        else:
            # 默认使用多边形质心
            s_wx = sum(p[0] for p in area_label.polygon) / len(area_label.polygon)
            s_wy = sum(p[1] for p in area_label.polygon) / len(area_label.polygon)
        start_u = int(round((s_wx - origin_x) / res))
        start_v = int(round(h - (s_wy - origin_y) / res))

        # 5. 调用算法
        self.statusbar_left.config(text=f"Generating coverage path for {area_label.name}...")
        self.update()

        try:
            planner_mode = getattr(config, "planner_mode", BASIC_MODE)
            selected_area_planning_map = build_selected_area_planning_map(planning_map_binary, roi_mask)
            request = CoveragePlanningRequest(
                prepared_map=preprocess_total_map(
                    raw_map=selected_area_planning_map,
                    resolution_m_per_px=float(res),
                    open_kernel_m=float(getattr(config, "open_kernel_m", 0.6)),
                    obstacle_expand_m=float(getattr(config, "obstacle_expand_m", 0.6)),
                    region_mask=roi_mask,
                    output_root=Path(config.artifacts_output_root) if getattr(config, "artifacts_output_root", "") else None,
                ),
                map_resolution=float(res),
                starting_position_px=(start_u, start_v),
                map_origin_xy=(float(origin_x), float(origin_y)),
                region_mask=roi_mask,
                region_polygon_px=tuple((int(p[0]), int(p[1])) for p in poly_pixels),
                map_yaml_path=Path(self.map_data.yaml_path) if self.map_data.yaml_path else None,
                public_config=config,
                artifacts_output_root=Path(config.artifacts_output_root) if getattr(config, "artifacts_output_root", "") else None,
            )
            if planner_mode == AUTO_MODE:
                result = route_coverage_plan(request)
            elif planner_mode == CHANNEL_TOPOLOGY_GRAPH_MODE:
                result = run_channel_topology_graph_adapter(request)
            else:
                result = run_formal_planner_request(request, planner_mode)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_error(
                problem=f"覆盖路径生成失败: {e}",
                impact="当前区域未生成路径，编辑状态保持不变",
                suggestion="检查地图可达区域与算法模式参数后重试",
            )
            self.statusbar_left.config(text="Coverage path generation failed.")
            return

        if not result.success or not result.path:
            msg = result.error_message if not result.success else "Empty path returned."
            self._show_warning(
                problem=f"区域路径生成失败: {msg}",
                impact="该区域没有新增覆盖路径",
                suggestion="检查区域可达性、起点位置或切换算法参数后重试",
            )
            self.statusbar_left.config(text="No path generated.")
            return

        path_world = result.path
        diagnostics = getattr(result, "diagnostics", None)
        self._last_coverage_planning_diagnostics = diagnostics
        selected_planner = getattr(diagnostics, "selected_planner", "") or planner_mode
        scene_type = getattr(diagnostics, "scene_type", "")
        status_text = f"Path generated with {len(path_world)} points."
        if planner_mode == AUTO_MODE:
            status_text = f"Path generated with {len(path_world)} points. Auto selected: {selected_planner}"
            if scene_type:
                status_text += f" ({scene_type})"
            summary = build_routing_summary(diagnostics)
            if summary:
                status_text += f" | {summary}"
        self.statusbar_left.config(text=status_text)

        # 6. 同步到 CoveragePathManager，使路径可编辑
        from ..models.coverage_path import CoveragePathNode
        manager = self.coverage_path_manager

        # room_id 是区域、路径和 coverage_repo 共享的唯一业务编号。
        room_id = area_room_id(area_label)
        segment_id = 0
        base_idx = len(manager.nodes)

        # 如果用户手动指定了起点且该像素是自由的，前置插入作为第 0 个节点
        if start_world_xy is not None and path_world:
            su = int(round((s_wx - origin_x) / res))
            sv = int(round(h - (s_wy - origin_y) / res))
            if (0 <= su < selected_area_planning_map.shape[1] and
                0 <= sv < selected_area_planning_map.shape[0] and
                selected_area_planning_map[sv, su] == 255):
                import math
                first_pose = path_world[0]
                dir_yaw = math.atan2(first_pose.y - s_wy, first_pose.x - s_wx)
                click_node = CoveragePathNode(
                    id=base_idx,
                    room=room_id,
                    segment=segment_id,
                    x=s_wx,
                    y=s_wy,
                    yaw=dir_yaw,
                    u=(s_wx - origin_x) / res,
                    v=h - (s_wy - origin_y) / res,
                    acc_dist=0.0,
                    room_dist=0.0,
                    seg_dist=0.0,
                )
                manager.nodes.append(click_node)
                base_idx += 1

        for i, pose in enumerate(path_world):
            u = (pose.x - origin_x) / res
            v = h - (pose.y - origin_y) / res
            node = CoveragePathNode(
                id=base_idx + i,
                room=room_id,
                segment=segment_id,
                x=pose.x,
                y=pose.y,
                yaw=pose.theta,
                u=u,
                v=v,
                acc_dist=0.0,
                room_dist=0.0,
                seg_dist=0.0,
            )
            manager.nodes.append(node)

        manager.renumber_nodes()  # 重算 ID 和 distances
        manager.is_dirty = True
        self._refresh_room_order_panel()

        # 保存起始点/终止点用于画布标记
        manager.start_point = (s_wx, s_wy)
        if path_world:
            last = path_world[-1]
            manager.end_point = (last.x, last.y)
        else:
            manager.end_point = None

        # 7. 显示在画布上（使用可编辑渲染器）
        self.canvas.refresh()
        self._log_coverage_canvas_state(
            "generate_after",
            area_id=area_room_id(area_label),
            area_name=getattr(area_label, "name", ""),
            planner_mode=planner_mode,
            selected_planner=selected_planner,
            generated_points=len(path_world),
        )

        total_areas = len({int(node.room) for node in manager.nodes})
        total_pts = len(manager.nodes)
        self.statusbar_left.config(
            text=build_coverage_status_text(
                total_areas=total_areas,
                total_points=total_pts,
                diagnostics=diagnostics,
                artifacts_dir=str(getattr(result, "artifacts_dir", "")),
                requested_mode=planner_mode,
            )
        )

    def _new_coverage_path(self):
        """新建空白路径"""
        if self.coverage_path_manager.is_dirty:
            if not messagebox.askyesno("Unsaved Changes", "You have unsaved path changes. Discard them?"):
                return
                
        self.coverage_path_manager.clear()
        self.canvas.refresh()
        self._log_coverage_canvas_state("new_coverage_path")
        self.statusbar_left.config(text="Started a new path edit session.")

    def _import_coverage_path(self):
        """导入 TSV 路径"""
        if not self.map_data.metadata:
            self._show_warning(
                problem="未加载地图",
                impact="无法导入路径",
                suggestion="先加载地图，再导入 TSV 路径",
            )
            return
            
        if self.coverage_path_manager.is_dirty:
            if not messagebox.askyesno("Unsaved Changes", "You have unsaved path changes. Discard them?"):
                return

        yaml_dir = os.path.dirname(self.map_data.yaml_path) if self.map_data.yaml_path else os.getcwd()
        path_file = filedialog.askopenfilename(
            title="Import Path (TSV)",
            initialdir=yaml_dir,
            filetypes=[("TSV/TXT files", "*.tsv *.txt"), ("All files", "*.*")]
        )
        if not path_file:
            return

        try:
            from ..models.coverage_path import PathParser
            manager = self.coverage_path_manager
            manager.clear()
            
            PathParser.load_tsv(path_file, manager.nodes, self.map_data.metadata)
            manager.rebuild_spatial()
            manager.renumber_nodes()
            manager.is_dirty = False
            self.canvas.refresh()
            self._refresh_room_order_panel()
            self._log_coverage_canvas_state("import_coverage_path", path_file=path_file)
            self.statusbar_left.config(text=f"Imported path from {os.path.basename(path_file)}")
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_error(
                problem=f"路径导入失败: {e}",
                impact="路径数据未更新",
                suggestion="检查 TSV 格式与当前地图坐标参数是否一致",
            )

    def _save_coverage_paths(self):
        """保存所有已生成的覆盖路径到一个 TSV 文件"""
        manager = self.coverage_path_manager

        if not manager.nodes:
            self._show_warning(
                problem="当前没有可保存路径",
                impact="无法导出路径文件",
                suggestion="先生成或绘制路径后再保存",
            )
            return

        if not self.map_data.metadata:
            self._show_error(
                problem="未加载地图",
                impact="无法保存路径数据",
                suggestion="先加载地图后再保存路径",
            )
            return

        yaml_dir = os.path.dirname(self.map_data.yaml_path) if self.map_data.yaml_path else os.getcwd()
        save_path = filedialog.asksaveasfilename(
            title="Save Coverage Paths (TSV)",
            initialdir=yaml_dir,
            initialfile="coverage_paths.tsv",
            defaultextension=".tsv",
            filetypes=[("TSV files", "*.tsv"), ("Text files", "*.txt"), ("All files", "*.*")]
        )

        if not save_path:
            return

        try:
            from ..models.coverage_path import PathParser
            repaired_rooms = repair_path_rooms_from_area_labels(
                manager,
                self.annotations,
            )

            # Ask user if they want to recalculate yaw/distances on save
            do_recalc = messagebox.askyesno(
                "Recalculate Path Data",
                "Do you want to recalculate Yaw and cumulative Distances before saving?\\nThis ensures path data is consistent."
            )

            PathParser.save_tsv(
                save_path,
                manager.nodes,
                self.map_data.metadata,
                recompute_dist=do_recalc,
                recompute_yaw=do_recalc
            )

            # Mark as clean and sync UI
            manager.is_dirty = False
            self.canvas.refresh()
            status = f"Edited paths saved to {save_path}"
            message = f"Saved {len(manager.nodes)} points to {os.path.basename(save_path)}"
            if repaired_rooms:
                status += f" (repaired room_id for {repaired_rooms} points)"
                message += f"\nRepaired room_id for {repaired_rooms} points before saving."
            self.statusbar_left.config(text=status)
            messagebox.showinfo("Success", message)
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_error(
                problem=f"路径保存失败: {e}",
                impact="路径文件未生成",
                suggestion="检查保存目录权限与路径数据格式后重试",
            )

    def _delete_coverage_path(self, area_label):
        """删除某个区域的覆盖路径"""
        manager = self.coverage_path_manager
        room_id = area_room_id(area_label)
        before_nodes = len(manager.nodes)
        manager.nodes = [node for node in manager.nodes if node.room != room_id]
        if len(manager.nodes) != before_nodes:
            manager.selection = {idx for idx in manager.selection if idx < len(manager.nodes)}
            manager.renumber_nodes()
            manager.is_dirty = True
            # 更新全局起终点标记
            if manager.nodes:
                manager.start_point = (manager.nodes[0].x, manager.nodes[0].y)
                manager.end_point = (manager.nodes[-1].x, manager.nodes[-1].y)
            else:
                manager.start_point = None
                manager.end_point = None

        # 清除该区域记忆的起点
        points = self.__dict__.get("_coverage_start_points_by_area_id", {})
        points.pop(room_id, None)
        fingerprints = self.__dict__.get("_coverage_start_fingerprints_by_area_id", {})
        fingerprints.pop(room_id, None)

        self.canvas.refresh()
        self._refresh_room_order_panel()
        self._log_coverage_canvas_state("delete_coverage_path", area_id=room_id, area_name=area_label.name)
        self.statusbar_left.config(
            text=f"Deleted coverage path for {area_label.name}. "
                 f"{len({int(node.room) for node in manager.nodes})} area(s) remaining, {len(manager.nodes)} total points.")

    def _clear_coverage_paths(self):
        """清空所有覆盖路径"""
        self.coverage_path_manager.clear()
        self.canvas.clear_coverage_path()
        self.canvas.refresh()
        self._refresh_room_order_panel()
        self._log_coverage_canvas_state("clear_coverage_paths")
        self.statusbar_left.config(text="All coverage paths cleared.")

    def _on_tsp_optimize_room_order(self) -> list[int] | None:
        """TSP 优化回调：计算房间最优访问顺序。"""
        from algorithms.coverage_planning.routing.room_tsp_solver import solve_room_tsp

        manager = self.coverage_path_manager
        if not manager.nodes:
            return None

        room_to_nodes: dict[int, list] = {}
        for node in manager.nodes:
            room_to_nodes.setdefault(node.room_id, []).append(node)

        if len(room_to_nodes) <= 1:
            return None

        rooms = []
        for rid in sorted(room_to_nodes):
            nodes = room_to_nodes[rid]
            start = nodes[0]
            end = nodes[-1]
            rooms.append({
                "id": rid,
                "start": (start.x, start.y),
                "end": (end.x, end.y),
            })

        global_start = None
        if manager.start_point is not None:
            global_start = manager.start_point

        indices = solve_room_tsp(rooms, global_start)
        new_order = [rooms[i]["id"] for i in indices]
        return new_order

    def _reorder_room_paths(self):
        """菜单入口：触发 Room 顺序面板的 apply"""
        self._refresh_room_order_panel()

    def _apply_room_order(self, new_order):
        """RoomOrderPanel 的 apply 回调：按新顺序重排 nodes"""
        manager = self.coverage_path_manager
        if not manager.nodes:
            return

        room_to_nodes = {}
        for node in manager.nodes:
            rid = int(node.room)
            room_to_nodes.setdefault(rid, []).append(node)

        reordered = []
        for rid in new_order:
            reordered.extend(room_to_nodes.get(rid, []))

        manager.nodes = reordered
        manager.renumber_nodes()
        manager.is_dirty = True
        self.canvas.refresh()
        total_dist = sum(
            math.hypot(
                manager.nodes[i + 1].x - manager.nodes[i].x,
                manager.nodes[i + 1].y - manager.nodes[i].y,
            )
            for i in range(len(manager.nodes) - 1)
        )
        self.statusbar_left.config(
            text=f"Room 连接顺序已更新: {new_order} | 总路径长度: {total_dist:.2f} m"
        )

    def _refresh_room_order_panel(self):
        """从 CoveragePathManager 提取 room 顺序，刷新侧边栏面板"""
        panel = getattr(self.sidebar, "room_order_panel", None)
        if panel is None:
            return
        manager = self.coverage_path_manager
        if not manager.nodes:
            panel.clear()
            return
        seen = []
        for node in manager.nodes:
            rid = int(node.room)
            if rid not in seen:
                seen.append(rid)
        panel.refresh(seen)

    def _has_coverage_path_for(self, area_label) -> bool:
        """检查某个区域是否已有覆盖路径"""
        room_id = area_room_id(area_label)
        return any(int(node.room) == room_id for node in self.coverage_path_manager.nodes)

    def _refresh_coverage_display(self):
        """刷新画布上的覆盖路径显示"""
        if not self.coverage_path_manager.nodes:
            self.canvas.clear_coverage_path()
            self.canvas.refresh()
            return

        all_pixels = [(float(node.u), float(node.v)) for node in self.coverage_path_manager.nodes]
        self.canvas.show_coverage_path(all_pixels)

    def run(self):
        self.mainloop()
