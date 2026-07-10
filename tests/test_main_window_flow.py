from itertools import product
import json
import tkinter as tk
from pathlib import Path

import numpy as np
from PIL import Image

from algorithms.coverage_planning.contracts import (
    CoveragePlanningDiagnostics,
    CoveragePlanningResult,
    CoveragePlanningRuntimeDetails,
    CoveragePlanningStatus,
    CoveragePose2D,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.decision_debug_payloads import (
    CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION,
)
from maptools.models.annotations import Annotations, DerivedConstraintRegion
from maptools.models.coverage_path import CoveragePathManager, CoveragePathNode
from maptools.models.map_data import MapData, MapMetadata
from maptools.adapters.coverage_planning_adapter import CoveragePlannerConfig
from maptools.controllers.command_manager import CommandManager
from maptools.tools.select_tool import SelectTool
from maptools.views.map_canvas import MapCanvas
from maptools.views.coverage_dialog import (
    CTG_ADVANCED_FIELDS,
    CTG_PARAMETER_FIELDS,
    CoverageDialog,
    SHELF_ADVANCED_FIELDS,
    SHELF_PARAMETER_FIELDS,
    SHELF_TURN_COST_ADVANCED_FIELDS,
    SHELF_QUALITY_GUARD_FIELDS,
    SHARED_ADVANCED_FIELDS,
    TURN_CONSTRAINT_FIELDS,
    build_planner_mode_override_notice,
    build_coverage_input_summary,
    coverage_dialog_config_from_values,
    coverage_dialog_default_values,
    coverage_dialog_values_from_config,
    merge_coverage_dialog_values,
    resolve_visible_parameter_groups,
    show_coverage_dialog,
    UI_PLANNER_CHOICES,
)
from maptools.views.layout_components import Toolbar
from maptools.views.main_window import (
    MainWindow,
    build_coverage_status_text,
    build_routing_artifact_locations,
    build_routing_detail_lines,
    build_routing_detail_text,
    build_routing_summary,
)
from maptools.utils.free_space_components import FREE_SPACE_COMPONENT_COLOR_HEX, FreeSpaceComponentStat
from maptools.utils.coverage_planner_params import (
    COVERAGE_PLANNER_PARAMS_FILENAME,
    load_coverage_planner_params,
    save_coverage_planner_params,
)
from maptools.utils.coverage_start_points import (
    COVERAGE_START_POINTS_FILENAME,
    load_coverage_start_points,
    save_coverage_start_points,
)


def test_resize_event_applies_toolbar_breakpoints():
    window = MainWindow.__new__(MainWindow)
    applied = []

    class _ToolbarStub:
        def apply_breakpoint(self, name):
            applied.append(name)

    window.toolbar = _ToolbarStub()
    window._toolbar_breakpoint = None

    event = type("Event", (), {"widget": window, "width": 1200})
    window._on_window_resize(event)
    event.width = 1500
    window._on_window_resize(event)
    event.width = 2000
    window._on_window_resize(event)

    assert applied == ["narrow", "medium", "wide"]


def test_resolve_planner_config_keeps_basic_mode():
    window = MainWindow.__new__(MainWindow)
    requested = CoveragePlannerConfig(planner_mode="basic")

    resolved, warning = window._resolve_planner_config(requested)

    assert resolved is requested
    assert warning is None


def test_resolve_planner_config_keeps_auto_mode():
    window = MainWindow.__new__(MainWindow)
    requested = CoveragePlannerConfig(planner_mode="auto")

    resolved, warning = window._resolve_planner_config(requested)

    assert resolved is requested
    assert warning is None


def test_resolve_planner_config_keeps_shelf_aware_mode():
    window = MainWindow.__new__(MainWindow)
    requested = CoveragePlannerConfig(planner_mode="shelf_aware")

    resolved, warning = window._resolve_planner_config(requested)

    assert resolved is requested
    assert warning is None


def test_resolve_planner_config_keeps_channel_topology_graph_mode():
    window = MainWindow.__new__(MainWindow)
    requested = CoveragePlannerConfig(planner_mode="channel_topology_graph")

    resolved, warning = window._resolve_planner_config(requested)

    assert resolved is requested
    assert warning is None


def test_coverage_dialog_ui_choices_do_not_include_ctc():
    values = {value for _, value in UI_PLANNER_CHOICES}

    assert values == {
        "auto",
        "basic",
        "shelf_aware",
        "shelf_aware_turn_cost",
        "channel_topology_graph",
    }
    assert "ctc" not in values


def test_coverage_dialog_auto_mode_hides_algorithm_specific_groups():
    groups = resolve_visible_parameter_groups("auto")

    assert groups["shelf"] == ()
    assert groups["ctg"] == ()
    assert groups["turn_constraint"] == ()
    assert groups["shared_advanced"] == SHARED_ADVANCED_FIELDS


def test_coverage_dialog_shelf_mode_exposes_only_shelf_groups():
    groups = resolve_visible_parameter_groups("shelf_aware")

    assert groups["turn_constraint"] == TURN_CONSTRAINT_FIELDS
    assert groups["shelf"] == SHELF_PARAMETER_FIELDS
    assert groups["shelf_advanced"] == SHELF_ADVANCED_FIELDS
    assert groups["shelf_quality_guard"] == SHELF_QUALITY_GUARD_FIELDS
    assert groups["ctg"] == ()
    assert groups["ctg_advanced"] == ()


def test_coverage_dialog_turn_cost_shelf_mode_exposes_shelf_groups():
    groups = resolve_visible_parameter_groups("shelf_aware_turn_cost")

    assert groups["turn_constraint"] == TURN_CONSTRAINT_FIELDS
    assert groups["shelf"] == SHELF_PARAMETER_FIELDS
    assert groups["shelf_advanced"] == SHELF_TURN_COST_ADVANCED_FIELDS
    assert "shelf_ctg_auxiliary_enable" in groups["shelf_advanced"]
    assert "isolated_jump_cleanup_enable" not in groups["shelf_advanced"]
    assert "shelf_turn_cost_advanced" not in groups
    assert groups["shelf_quality_guard"] == SHELF_QUALITY_GUARD_FIELDS
    assert groups["ctg"] == ()
    assert groups["ctg_advanced"] == ()


def test_coverage_dialog_turn_cost_mode_notice_shows_profile_forced_overrides():
    notice = build_planner_mode_override_notice("shelf_aware_turn_cost")

    assert "Profile: shelf_aware_turn_cost_repaired_grid_0_28 v2" in notice
    assert "固定覆盖:" in notice
    assert "shelf_ctg_auxiliary_enable=true" not in notice
    assert "shelf_node_generation_mode=turn_cost_repaired_grid" in notice
    assert "shelf_repaired_grid_max_offset_factor=0.28" in notice
    assert "isolated_jump_cleanup_enable=false" in notice


def test_coverage_dialog_shelf_mode_notice_has_no_forced_overrides():
    notice = build_planner_mode_override_notice("shelf_aware")

    assert "Profile: shelf_aware_default v1" in notice
    assert "不会强制覆盖保存参数" in notice
    assert "固定覆盖:" not in notice


def test_coverage_dialog_unknown_mode_notice_has_no_profile():
    notice = build_planner_mode_override_notice("unknown_mode")

    assert "当前模式没有正式 profile" in notice
    assert "固定覆盖:" not in notice


def _tk_root_or_skip():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        import pytest

        pytest.skip(f"Tk display unavailable: {exc}")
    root.withdraw()
    return root


class _NonModalCoverageDialog:
    """Mixin used by tests to instantiate CoverageDialog without blocking."""

    def grab_set(self):
        return None

    def wait_visibility(self, window=None):
        return None

    def wait_window(self, window=None):
        return None


def test_coverage_dialog_real_widget_turn_cost_mode_visibility_and_apply():
    class DialogUnderTest(_NonModalCoverageDialog, CoverageDialog):
        pass

    root = _tk_root_or_skip()
    try:
        dialog = DialogUnderTest(
            root,
            input_summary={
                "map_name": "beiguoshangcheng_floor_3.yaml",
                "resolution": "0.050 m/px",
                "region_status": "area 5",
                "start_status": "已设置",
            },
            initial_values=merge_coverage_dialog_values(
                {
                    "planner_mode": "shelf_aware_turn_cost",
                    "show_advanced": True,
                    "shelf_node_obstacle_ratio_threshold": 0.41,
                }
            ),
        )

        assert dialog.planner_mode_var.get() == "shelf_aware_turn_cost"
        assert "Profile: shelf_aware_turn_cost_repaired_grid_0_28 v2" in dialog.mode_override_notice_var.get()
        assert dialog.shelf_frame.grid_info()
        assert not dialog.ctg_frame.grid_info()
        assert dialog.advanced_frame.grid_info()
        assert dialog._field_rows["turn_constraint_enable"].grid_info()
        assert dialog._field_rows["shelf_node_obstacle_ratio_threshold"].grid_info()
        assert dialog._field_rows["shelf_ctg_auxiliary_enable"].grid_info()
        assert not dialog._field_rows["isolated_jump_cleanup_enable"].grid_info()
        assert dialog._field_rows["shelf_quality_guard_enable"].grid_info()

        dialog.planner_mode_var.set("shelf_aware")
        dialog._update_parameter_visibility()
        assert dialog._field_rows["shelf_ctg_auxiliary_enable"].grid_info()
        assert dialog._field_rows["isolated_jump_cleanup_enable"].grid_info()
        assert dialog._field_rows["shelf_quality_guard_enable"].grid_info()

        dialog.planner_mode_var.set("shelf_aware_turn_cost")
        dialog.shelf_node_obstacle_ratio_threshold_var.set(0.37)
        dialog.apply()
        assert dialog.result_values["planner_mode"] == "shelf_aware_turn_cost"
        assert dialog.result_values["show_advanced"] is True
        assert dialog.result_config.planner_mode == "shelf_aware_turn_cost"
        assert dialog.result_config.shelf_node_obstacle_ratio_threshold == 0.37
    finally:
        for widget in root.winfo_children():
            widget.destroy()
        root.destroy()


def test_coverage_dialog_ctg_mode_exposes_only_ctg_groups():
    groups = resolve_visible_parameter_groups("channel_topology_graph")

    assert groups["turn_constraint"] == ()
    assert groups["shelf"] == ()
    assert groups["ctg"] == CTG_PARAMETER_FIELDS
    assert groups["ctg_advanced"] == CTG_ADVANCED_FIELDS


def test_coverage_dialog_default_values_are_current_ui_defaults():
    values = coverage_dialog_default_values()

    assert values["planner_mode"] == "auto"
    assert values["coverage_width_m"] == 0.6
    assert values["robot_width_m"] == 0.4
    assert values["open_kernel_m"] == 0.6
    assert values["obstacle_expand_m"] == 0.6
    assert values["show_advanced"] is False
    assert values["shelf_row_endpoint_alignment_enable"] is True
    assert values["shelf_node_obstacle_ratio_filter_enable"] is True
    assert values["shelf_node_obstacle_ratio_threshold"] == 0.45
    assert values["shelf_quality_guard_enable"] is False
    assert values["shelf_quality_guard_min_coverage_ratio"] == 0.90
    assert values["turn_constraint_enable"] is True


def test_coverage_dialog_values_from_config_preserve_checkboxes_and_ui_state():
    config = CoveragePlannerConfig(
        planner_mode="shelf_aware",
        coverage_width_m=0.72,
        local_direction_enable=False,
        allow_revisit_bridge=False,
        shelf_row_endpoint_alignment_enable=False,
        shelf_node_obstacle_ratio_filter_enable=False,
        shelf_node_obstacle_ratio_threshold=0.33,
        turn_constraint_enable=False,
        isolated_jump_max_points=2,
    )

    values = coverage_dialog_values_from_config(config, show_advanced=True)

    assert values["planner_mode"] == "shelf_aware"
    assert values["coverage_width_m"] == 0.72
    assert values["local_direction_enable"] is False
    assert values["allow_revisit_bridge"] is False
    assert values["shelf_row_endpoint_alignment_enable"] is False
    assert values["shelf_node_obstacle_ratio_filter_enable"] is False
    assert values["shelf_node_obstacle_ratio_threshold"] == 0.33
    assert values["turn_constraint_enable"] is False
    assert values["isolated_jump_max_points"] == 2
    assert values["show_advanced"] is True


def test_coverage_dialog_config_from_values_ignores_unknown_and_ui_only_state():
    values = merge_coverage_dialog_values(
        {
            "planner_mode": "channel_topology_graph",
            "coverage_width_m": 0.7,
            "free_node_min_clearance_m": 0.22,
            "junction_polygon_radius_px": 8.0,
            "turn_constraint_enable": False,
            "show_advanced": True,
            "unknown_future_key": "ignored",
        }
    )

    config = coverage_dialog_config_from_values(values)

    assert config.planner_mode == "channel_topology_graph"
    assert config.coverage_width_m == 0.7
    assert config.free_node_min_clearance_m == 0.22
    assert config.junction_polygon_radius_px == 8.0
    assert config.turn_constraint_enable is False
    assert not hasattr(config, "show_advanced")


def test_show_coverage_dialog_remembers_values_after_success(monkeypatch):
    previous = merge_coverage_dialog_values(
        {
            "planner_mode": "shelf_aware",
            "coverage_width_m": 0.91,
            "show_advanced": True,
        }
    )
    parent = type("ParentStub", (), {"_last_coverage_dialog_values": previous})()
    seen_initial_values = []

    class DialogStub:
        def __init__(self, parent, title="覆盖路径参数", input_summary=None, initial_values=None):
            seen_initial_values.append(dict(initial_values or {}))
            self.result_values = merge_coverage_dialog_values(
                {
                    "planner_mode": "channel_topology_graph",
                    "coverage_width_m": 0.66,
                    "show_advanced": False,
                }
            )
            self.result_config = coverage_dialog_config_from_values(self.result_values)

    monkeypatch.setattr("maptools.views.coverage_dialog.CoverageDialog", DialogStub)

    config = show_coverage_dialog(parent, input_summary={"map_name": "demo.yaml"})

    assert config.planner_mode == "channel_topology_graph"
    assert seen_initial_values[0]["planner_mode"] == "shelf_aware"
    assert seen_initial_values[0]["coverage_width_m"] == 0.91
    assert seen_initial_values[0]["show_advanced"] is True
    assert parent._last_coverage_dialog_values["planner_mode"] == "channel_topology_graph"
    assert parent._last_coverage_dialog_values["coverage_width_m"] == 0.66
    assert parent._last_coverage_dialog_values["show_advanced"] is False


def test_show_coverage_dialog_cancel_does_not_overwrite_memory(monkeypatch):
    previous = merge_coverage_dialog_values(
        {
            "planner_mode": "shelf_aware",
            "coverage_width_m": 0.88,
            "show_advanced": True,
        }
    )
    parent = type("ParentStub", (), {"_last_coverage_dialog_values": dict(previous)})()

    class DialogStub:
        def __init__(self, parent, title="覆盖路径参数", input_summary=None, initial_values=None):
            self.result_values = merge_coverage_dialog_values(
                {
                    "planner_mode": "channel_topology_graph",
                    "coverage_width_m": 0.44,
                    "show_advanced": False,
                }
            )
            self.result_config = None

    monkeypatch.setattr("maptools.views.coverage_dialog.CoverageDialog", DialogStub)

    config = show_coverage_dialog(parent)

    assert config is None
    assert parent._last_coverage_dialog_values == previous


def test_coverage_planner_params_round_trip(tmp_path):
    values = merge_coverage_dialog_values(
        {
            "planner_mode": "shelf_aware",
            "coverage_width_m": 0.73,
            "shelf_row_endpoint_alignment_enable": False,
            "show_advanced": True,
        }
    )

    path = save_coverage_planner_params(tmp_path, values)
    loaded = load_coverage_planner_params(tmp_path)

    assert path == tmp_path / COVERAGE_PLANNER_PARAMS_FILENAME
    assert loaded["planner_mode"] == "shelf_aware"
    assert loaded["coverage_width_m"] == 0.73
    assert loaded["shelf_row_endpoint_alignment_enable"] is False
    assert loaded["show_advanced"] is True


def test_coverage_planner_params_round_trip_preserves_turn_cost_mode(tmp_path):
    values = merge_coverage_dialog_values(
        {
            "planner_mode": "shelf_aware_turn_cost",
            "coverage_width_m": 0.6,
            "show_advanced": True,
            "shelf_node_obstacle_ratio_threshold": 0.41,
        }
    )

    save_coverage_planner_params(tmp_path, values)
    loaded = load_coverage_planner_params(tmp_path)
    config = coverage_dialog_config_from_values(loaded)

    assert loaded["planner_mode"] == "shelf_aware_turn_cost"
    assert loaded["show_advanced"] is True
    assert loaded["shelf_node_obstacle_ratio_threshold"] == 0.41
    assert config.planner_mode == "shelf_aware_turn_cost"
    assert config.shelf_node_obstacle_ratio_threshold == 0.41


def test_coverage_start_points_round_trip_filters_deleted_and_modified_areas(tmp_path):
    annotations = Annotations()
    area_1 = annotations.add_area_label(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        name="A1",
        area_id=1,
    )
    annotations.add_area_label(
        [(20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0)],
        name="A2",
        area_id=2,
    )

    save_coverage_start_points(
        tmp_path,
        annotations,
        {
            1: (1.0, 2.0),
            2: (25.0, 5.0),
            3: (100.0, 100.0),
        },
    )

    loaded = load_coverage_start_points(tmp_path, annotations)
    assert loaded == {1: (1.0, 2.0), 2: (25.0, 5.0)}

    changed_annotations = Annotations()
    changed_annotations.add_area_label(
        [(0.0, 0.0), (8.0, 0.0), (8.0, 8.0), (0.0, 8.0)],
        name="A1 renamed",
        area_id=1,
    )
    changed_annotations.add_area_label(
        [(20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0)],
        name="A2",
        area_id=2,
    )

    loaded_after_change = load_coverage_start_points(tmp_path, changed_annotations)
    assert loaded_after_change == {2: (25.0, 5.0)}


def test_valid_coverage_start_points_for_current_areas_drops_stale_fingerprint():
    window = MainWindow.__new__(MainWindow)
    window.annotations = Annotations()
    area = window.annotations.add_area_label(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        name="A1",
        area_id=1,
    )
    window._coverage_start_points_by_area_id = {}
    window._remember_coverage_start_point(area, (1.0, 2.0))

    area.polygon = [(0.0, 0.0), (8.0, 0.0), (8.0, 8.0), (0.0, 8.0)]

    assert window._valid_coverage_start_points_for_current_areas() == {}
    assert window._coverage_start_points_by_area_id == {}


def test_restore_coverage_start_points_loads_valid_project_memory(tmp_path):
    annotations = Annotations()
    area = annotations.add_area_label(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        name="A1",
        area_id=1,
    )
    save_coverage_start_points(tmp_path, annotations, {1: (1.0, 2.0)})
    window = MainWindow.__new__(MainWindow)
    window.annotations = annotations
    window._show_warning = lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected warning"))

    note = window._restore_coverage_start_points(str(tmp_path))

    assert note == "coverage_start_points=1"
    assert window._get_remembered_coverage_start_point(area) == (1.0, 2.0)


def test_restore_coverage_start_points_warns_and_clears_on_invalid_file(tmp_path):
    window = MainWindow.__new__(MainWindow)
    window.annotations = Annotations()
    window._coverage_start_points_by_area_id = {1: (1.0, 2.0)}
    warnings = []
    window._show_warning = lambda **kwargs: warnings.append(kwargs)
    (tmp_path / COVERAGE_START_POINTS_FILENAME).write_text(
        '{"schema_version": 999, "start_points": []}',
        encoding="utf-8",
    )

    note = window._restore_coverage_start_points(str(tmp_path))

    assert note == "coverage_start_points=invalid"
    assert window._coverage_start_points_by_area_id == {}
    assert warnings
    assert "覆盖路径起点加载失败" in warnings[0]["problem"]


def test_prompt_save_coverage_planner_params_skips_without_memory(tmp_path, monkeypatch):
    window = MainWindow.__new__(MainWindow)
    calls = []
    monkeypatch.setattr(
        "maptools.views.main_window.messagebox.askyesno",
        lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )

    window._prompt_save_coverage_planner_params(str(tmp_path))

    assert calls == []
    assert not (tmp_path / COVERAGE_PLANNER_PARAMS_FILENAME).exists()


def test_prompt_save_coverage_planner_params_writes_when_confirmed(tmp_path, monkeypatch):
    window = MainWindow.__new__(MainWindow)
    window._last_coverage_dialog_values = merge_coverage_dialog_values(
        {
            "planner_mode": "channel_topology_graph",
            "coverage_width_m": 0.64,
            "show_advanced": True,
        }
    )
    prompts = []

    def _ask(title, message):
        prompts.append(message)
        return True

    monkeypatch.setattr("maptools.views.main_window.messagebox.askyesno", _ask)

    window._prompt_save_coverage_planner_params(str(tmp_path))

    loaded = load_coverage_planner_params(tmp_path)
    assert prompts == ["是否保存当前覆盖路径参数到工程？"]
    assert loaded["planner_mode"] == "channel_topology_graph"
    assert loaded["coverage_width_m"] == 0.64
    assert loaded["show_advanced"] is True


def test_prompt_save_coverage_planner_params_uses_overwrite_prompt(tmp_path, monkeypatch):
    window = MainWindow.__new__(MainWindow)
    window._last_coverage_dialog_values = merge_coverage_dialog_values(
        {
            "planner_mode": "basic",
            "coverage_width_m": 0.61,
        }
    )
    save_coverage_planner_params(
        tmp_path,
        merge_coverage_dialog_values({"planner_mode": "shelf_aware", "coverage_width_m": 0.9}),
    )
    prompts = []

    def _ask(title, message):
        prompts.append(message)
        return True

    monkeypatch.setattr("maptools.views.main_window.messagebox.askyesno", _ask)

    window._prompt_save_coverage_planner_params(str(tmp_path))

    loaded = load_coverage_planner_params(tmp_path)
    assert prompts == ["工程中已存在覆盖路径参数，是否用当前参数覆盖？"]
    assert loaded["planner_mode"] == "basic"
    assert loaded["coverage_width_m"] == 0.61


def test_restore_coverage_planner_params_loads_project_memory(tmp_path):
    window = MainWindow.__new__(MainWindow)
    window._show_warning = lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected warning"))
    save_coverage_planner_params(
        tmp_path,
        merge_coverage_dialog_values(
            {
                "planner_mode": "shelf_aware",
                "coverage_width_m": 0.82,
                "show_advanced": True,
            }
        ),
    )

    note = window._restore_coverage_planner_params(str(tmp_path))

    assert note == "coverage_params=loaded"
    assert window._last_coverage_dialog_values["planner_mode"] == "shelf_aware"
    assert window._last_coverage_dialog_values["coverage_width_m"] == 0.82
    assert window._last_coverage_dialog_values["show_advanced"] is True


def test_restore_coverage_planner_params_clears_missing_project_memory(tmp_path):
    window = MainWindow.__new__(MainWindow)
    window._last_coverage_dialog_values = merge_coverage_dialog_values({"planner_mode": "shelf_aware"})

    note = window._restore_coverage_planner_params(str(tmp_path))

    assert note == ""
    assert "_last_coverage_dialog_values" not in window.__dict__


def test_restore_coverage_planner_params_warns_and_falls_back_on_invalid_file(tmp_path):
    window = MainWindow.__new__(MainWindow)
    warnings = []
    window._show_warning = lambda **kwargs: warnings.append(kwargs)
    (tmp_path / COVERAGE_PLANNER_PARAMS_FILENAME).write_text(
        '{"schema_version": 1, "coverage_dialog_values": {"coverage_width_m": -1}}',
        encoding="utf-8",
    )

    note = window._restore_coverage_planner_params(str(tmp_path))

    assert note == "coverage_params=invalid"
    assert warnings
    assert "覆盖路径参数加载失败" in warnings[0]["problem"]


def test_coverage_start_points_are_remembered_per_area():
    window = MainWindow.__new__(MainWindow)
    window._coverage_start_points_by_area_id = {}
    area_1 = type("AreaLabelStub", (), {"area_id": 1, "polygon": [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]})()
    area_2 = type("AreaLabelStub", (), {"area_id": 2, "polygon": [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]})()

    window._remember_coverage_start_point(area_1, (1.25, 2.5))
    window._remember_coverage_start_point(area_2, (3.5, 4.75))

    assert window._get_remembered_coverage_start_point(area_1) == (1.25, 2.5)
    assert window._get_remembered_coverage_start_point(area_2) == (3.5, 4.75)


def test_choose_coverage_start_uses_remembered_point_when_confirmed(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    area = type("AreaLabelStub", (), {"area_id": 7, "name": "A7", "polygon": [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]})()
    window._coverage_start_points_by_area_id = {}
    window._remember_coverage_start_point(area, (1.0, 2.0))
    prompts = []

    def _ask(title, message):
        prompts.append(message)
        return True

    monkeypatch.setattr("maptools.views.main_window.messagebox.askyesno", _ask)

    assert window._choose_coverage_start_point(area) == (1.0, 2.0)
    assert prompts == ["区域 A7 是否使用上一次起点？"]


def test_choose_coverage_start_can_enter_pick_mode_without_remembered_point(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    area = type("AreaLabelStub", (), {"area_id": 7, "name": "A7", "polygon": [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]})()
    window._coverage_start_points_by_area_id = {}
    answers = iter([True])

    monkeypatch.setattr(
        "maptools.views.main_window.messagebox.askyesno",
        lambda title, message: next(answers),
    )

    assert window._choose_coverage_start_point(area) == "pick"


def test_choose_coverage_start_can_use_default_after_declining_manual_pick(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    area = type("AreaLabelStub", (), {"area_id": 7, "name": "A7", "polygon": [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]})()
    window._coverage_start_points_by_area_id = {}
    prompts = []
    answers = iter([False, True])

    def _ask(title, message):
        prompts.append(message)
        return next(answers)

    monkeypatch.setattr("maptools.views.main_window.messagebox.askyesno", _ask)

    assert window._choose_coverage_start_point(area) is None
    assert prompts == ["区域 A7 是否设置起点？", "区域 A7 是否使用默认起点？"]


def test_choose_coverage_start_can_cancel_after_declining_all(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    area = type("AreaLabelStub", (), {"area_id": 7, "name": "A7", "polygon": [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]})()
    window._coverage_start_points_by_area_id = {}
    window._remember_coverage_start_point(area, (1.0, 2.0))
    answers = iter([False, False, False])

    monkeypatch.setattr(
        "maptools.views.main_window.messagebox.askyesno",
        lambda title, message: next(answers),
    )

    assert window._choose_coverage_start_point(area) == "cancel"


def test_on_generate_coverage_path_enters_pick_mode_when_requested():
    window = MainWindow.__new__(MainWindow)
    area = type("AreaLabelStub", (), {"area_id": 7, "name": "A7"})()
    picked = []
    generated = []
    window.canvas = type("CanvasStub", (), {"_enter_pick_start_mode": lambda self, area_label: picked.append(area_label)})()
    window._choose_coverage_start_point = lambda area_label: "pick"
    window._generate_coverage_path_for_area = lambda area_label, start_world_xy=None: generated.append(
        (area_label, start_world_xy)
    )

    window._on_generate_coverage_path(area)

    assert picked == [area]
    assert generated == []


def test_on_generate_coverage_path_uses_default_start_when_confirmed():
    window = MainWindow.__new__(MainWindow)
    area = type("AreaLabelStub", (), {"area_id": 7, "name": "A7"})()
    generated = []
    window._choose_coverage_start_point = lambda area_label: None
    window._generate_coverage_path_for_area = lambda area_label, start_world_xy=None: generated.append(
        (area_label, start_world_xy)
    )

    window._on_generate_coverage_path(area)

    assert generated == [(area, None)]


def test_on_generate_coverage_path_with_explicit_start_remembers_manual_start():
    window = MainWindow.__new__(MainWindow)
    area = type("AreaLabelStub", (), {"area_id": 7, "name": "A7", "polygon": [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]})()
    generated = []
    window._coverage_start_points_by_area_id = {}
    window._generate_coverage_path_for_area = lambda area_label, start_world_xy=None: generated.append(
        (area_label, start_world_xy)
    )

    window._on_generate_coverage_path(area, start_world_xy=(12.0, 34.0))

    assert window._get_remembered_coverage_start_point(area) == (12.0, 34.0)
    assert generated == [(area, (12.0, 34.0))]


def test_generate_coverage_path_uses_turn_cost_mode_from_dialog(monkeypatch, tmp_path):
    grid = np.full((20, 20), 254, dtype=np.uint8)
    map_data = MapData()
    map_data.metadata = MapMetadata(
        image_path="demo.pgm",
        resolution=0.5,
        origin=(0.0, 0.0, 0.0),
        negate=0,
        occupied_thresh=0.65,
        free_thresh=0.25,
        mode="trinary",
    )
    map_data.base_image = Image.fromarray(grid)
    map_data.grid_map = grid.copy()
    map_data.edit_layer = np.full_like(grid, 255, dtype=np.uint8)
    map_data.yaml_path = str(tmp_path / "demo.yaml")
    map_data.width = int(grid.shape[1])
    map_data.height = int(grid.shape[0])

    area = type(
        "AreaLabelStub",
        (),
        {
            "area_id": 5,
            "room_id": 5,
            "name": "area5",
            "polygon": [(1.0, 1.0), (8.0, 1.0), (8.0, 8.0), (1.0, 8.0)],
        },
    )()
    diagnostics = CoveragePlanningDiagnostics(
        selected_planner="shelf_aware_turn_cost",
        profile={"profile_id": "shelf_aware_turn_cost_repaired_grid_0_28", "profile_version": 2},
    )
    result = CoveragePlanningResult(
        status=CoveragePlanningStatus.SUCCESS,
        path=(
            CoveragePose2D(x=1.0, y=1.0, theta=0.0),
            CoveragePose2D(x=2.0, y=1.0, theta=0.0),
        ),
        diagnostics=diagnostics,
    )

    calls = []

    def _run_formal(request, planner_mode):
        calls.append((request, planner_mode))
        return result

    monkeypatch.setattr(
        "maptools.views.main_window.show_coverage_dialog",
        lambda parent, input_summary=None: CoveragePlannerConfig(
            planner_mode="shelf_aware_turn_cost",
            coverage_width_m=0.6,
            open_kernel_m=0.6,
            obstacle_expand_m=0.2,
        ),
    )
    monkeypatch.setattr("maptools.views.main_window.run_formal_planner_request", _run_formal)
    monkeypatch.setattr(
        "maptools.views.main_window.run_channel_topology_graph_adapter",
        lambda request: (_ for _ in ()).throw(AssertionError("unexpected CTG adapter call")),
    )
    monkeypatch.setattr(
        "maptools.views.main_window.route_coverage_plan",
        lambda request: (_ for _ in ()).throw(AssertionError("unexpected auto router call")),
    )

    window = MainWindow.__new__(MainWindow)
    window.map_data = map_data
    window.annotations = Annotations()
    window.coverage_path_manager = CoveragePathManager()
    window.canvas = type("CanvasStub", (), {"refresh": lambda self: None})()
    window.statusbar = type(
        "StatusStub",
        (),
        {"messages": [], "config": lambda self, **kwargs: self.messages.append(kwargs.get("text", ""))},
    )()
    window.update = lambda: None
    window._show_error = lambda **kwargs: (_ for _ in ()).throw(AssertionError(f"unexpected error: {kwargs}"))
    window._show_warning = lambda **kwargs: (_ for _ in ()).throw(AssertionError(f"unexpected warning: {kwargs}"))
    window._log_coverage_canvas_state = lambda *args, **kwargs: None

    window._generate_coverage_path_for_area(area, start_world_xy=(1.0, 1.0))

    assert len(calls) == 1
    request, planner_mode = calls[0]
    assert planner_mode == "shelf_aware_turn_cost"
    assert request.public_config.planner_mode == "shelf_aware_turn_cost"
    assert request.starting_position_px == (2, 18)
    assert request.region_mask.shape == grid.shape
    assert request.region_polygon_px == ((2, 18), (16, 18), (16, 4), (2, 4))
    assert request.artifacts_output_root == tmp_path / "maptools_shelf_aware_turn_cost_runs"
    assert window._last_coverage_planning_diagnostics is diagnostics
    assert len(window.coverage_path_manager.nodes) == 2
    assert {node.room for node in window.coverage_path_manager.nodes} == {5}
    assert any("shelf aware turn cost" in message.lower() for message in window.statusbar.messages)


def test_pick_start_left_click_calls_unified_coverage_callback():
    canvas = MapCanvas.__new__(MapCanvas)
    area = type("AreaLabelStub", (), {"area_id": 7, "name": "A7"})()
    triggered = []
    canvas._pick_start_mode = True
    canvas._pick_start_area_label = area
    canvas.coord_transformer = type(
        "CoordTransformerStub",
        (),
        {"canvas_to_world": lambda self, x, y: (float(x) + 0.5, float(y) + 0.25)},
    )()
    canvas.coverage_path_callback = lambda area_label, start_world_xy=None: triggered.append(
        (area_label, start_world_xy)
    )
    canvas.config = lambda **kwargs: None
    canvas.winfo_toplevel = lambda: type("TopLevelStub", (), {"statusbar": type("StatusStub", (), {"config": lambda self, **kwargs: None})()})()

    result = canvas._on_left_click(type("Event", (), {"x": 12, "y": 34})())

    assert result == "break"
    assert triggered == [(area, (12.5, 34.25))]
    assert canvas._pick_start_mode is False
    assert canvas._pick_start_area_label is None


def test_build_coverage_input_summary_reads_parent_map_context():
    parent = type(
        "ParentStub",
        (),
        {
            "map_data": type(
                "MapDataStub",
                (),
                {
                    "yaml_path": "/tmp/maps/demo.yaml",
                    "metadata": type("MetaStub", (), {"resolution": 0.05})(),
                },
            )(),
        },
    )()

    summary = build_coverage_input_summary(parent, area_name="A-01", start_point_set=True)

    assert summary["map_name"] == "demo.yaml"
    assert summary["resolution"] == "0.050 m/px"
    assert summary["region_status"] == "A-01"
    assert summary["start_status"] == "已设置"


def test_build_routing_summary_compacts_diagnostics():
    diagnostics = CoveragePlanningDiagnostics(
        selected_planner="channel_topology_graph",
        scene_type="aisle_like",
        reasons=("free_space_bbox_is_long_and_narrow", "explicit_channel_topology_graph_enabled"),
        warnings=("channel_topology_graph requires explicit enable_channel_topology_graph; using shelf_aware",),
    )

    summary = build_routing_summary(diagnostics)

    assert "规划器=channel topology graph" in summary
    assert "场景类型=aisle like" in summary
    assert "原因=free space bbox is long and narrow; explicit channel topology graph enabled" in summary
    assert "警告=channel topology graph requires explicit enable channel topology graph; using shelf aware" in summary


def test_build_routing_summary_includes_profile_quality_and_provenance():
    diagnostics = CoveragePlanningDiagnostics(
        selected_planner="shelf_aware_turn_cost",
        scene_type="explicit",
        profile={"profile_id": "shelf_aware_turn_cost_repaired_grid_0_28"},
        runtime=CoveragePlanningRuntimeDetails(
            coverage_meta={
                "shelf_ctg_auxiliary": {
                    "enabled": False,
                    "reason": "auxiliary_failed_continued_without_ctg",
                    "error_message": "edge 6 path too short",
                }
            },
            path_quality_summary={
                "available": True,
                "status": "pass",
                "passed": True,
                "coverage_ratio": 0.9987,
            },
            provenance_summary={
                "available": True,
                "path_generation_provenance": {
                    "available": True,
                    "move_trace_count": 42,
                    "global_fallback_count": 3,
                    "revisit_bridge_count": 5,
                },
            },
        ),
    )

    summary = build_routing_summary(diagnostics)

    assert "策略配置=shelf aware turn cost repaired grid 0 28" in summary
    assert "路径质量=pass 覆盖率=0.999" in summary
    assert "路径溯源=移动=42 fallback=3 revisit=5" in summary


def test_build_routing_summary_includes_compact_risk_summary():
    class DiagnosticsStub:
        selected_planner = "shelf_aware_turn_cost"
        scene_type = "explicit"
        reasons = ()
        warnings = ()
        profile = {"profile_id": "shelf_aware_turn_cost_repaired_grid_0_28"}
        runtime = {
            "path_quality_summary": {
                "available": True,
                "status": "warn",
                "passed": False,
                "coverage_ratio": 0.991,
            },
            "provenance_summary": {
                "path_generation_provenance": {
                    "available": True,
                    "move_trace_count": 10,
                    "global_fallback_count": 1,
                    "revisit_bridge_count": 2,
                },
            },
        }

        def to_summary_dict(self):
            return {
                "selected_planner": self.selected_planner,
                "scene_type": self.scene_type,
                "profile": dict(self.profile),
                "runtime": dict(self.runtime),
                "compact_summary": {
                    "mode_default_override_fields": (
                        "isolated_jump_cleanup_enable",
                        "shelf_ctg_auxiliary_enable",
                        "shelf_node_generation_mode",
                        "shelf_repaired_grid_max_offset_factor",
                    ),
                    "override_diff_fields": (
                        "shelf_ctg_auxiliary_enable",
                        "shelf_node_generation_mode",
                    ),
                    "geometry_risk": {
                        "available": False,
                        "reason": "readonly_geometry_diagnostic_not_run_in_formal_planner",
                    },
                    "provenance": {
                        "artifact_manifest_available": True,
                    },
                },
            }

    diagnostics = DiagnosticsStub()

    summary = build_routing_summary(diagnostics)

    assert "模式固定覆盖=4 项" in summary
    assert "实际生效覆盖=2 项" in summary
    assert "几何风险=未作为硬约束运行：readonly geometry diagnostic not run in formal planner" in summary
    assert "路径溯源=fallback=0 revisit=0 产物清单=有" in summary


def test_build_routing_summary_includes_available_geometry_risk_summary():
    class DiagnosticsStub:
        selected_planner = "shelf_aware_turn_cost"
        scene_type = "explicit"
        reasons = ()
        warnings = ()
        profile = {"profile_id": "shelf_aware_turn_cost_repaired_grid_0_28"}
        runtime = {}

        def to_summary_dict(self):
            return {
                "selected_planner": self.selected_planner,
                "scene_type": self.scene_type,
                "profile": dict(self.profile),
                "runtime": {},
                "compact_summary": {
                    "geometry_risk": {
                        "available": True,
                        "body_swept_collision_count": 2,
                        "turn_swept_collision_count": 4,
                        "cleaning_footprint_coverage_ratio": 0.987,
                    },
                    "provenance": {},
                },
            }

    summary = build_routing_summary(DiagnosticsStub())

    assert "几何风险=只读诊断 车体碰撞=2 转弯碰撞=4 清扫覆盖=0.987" in summary


def test_build_routing_summary_prefers_shared_readable_summary():
    diagnostics = CoveragePlanningDiagnostics(
        selected_planner="shelf_aware_turn_cost",
        scene_type="explicit",
        profile={"profile_id": "shelf_aware_turn_cost_repaired_grid_0_28", "profile_version": 2},
        runtime=CoveragePlanningRuntimeDetails(
            path_quality_summary={
                "available": True,
                "status": "pass",
                "coverage_ratio": 0.9987,
                "long_jump_count": 0,
                "infeasible_segment_count": 0,
            }
        ),
    )

    summary = build_routing_summary(diagnostics)

    assert summary.startswith("规划器=shelf aware turn cost")
    assert "策略配置=shelf aware turn cost repaired grid 0 28 v2" in summary
    assert "路径质量=pass 覆盖率=0.999 长跳跃=0 不可行段=0" in summary


def test_build_routing_detail_lines_exposes_profile_diff_geometry_and_provenance():
    diagnostics = CoveragePlanningDiagnostics(
        selected_planner="shelf_aware_turn_cost",
        scene_type="explicit",
        artifacts_dir="/tmp/shelf_turn_cost_run",
        profile={
            "planner_mode": "shelf_aware_turn_cost",
            "profile_id": "shelf_aware_turn_cost_repaired_grid_0_28",
            "profile_version": 2,
            "profile_status": "candidate",
        },
        mode_default_overrides={
            "isolated_jump_cleanup_enable": False,
            "shelf_node_generation_mode": "turn_cost_repaired_grid",
        },
        override_diff={
            "shelf_node_generation_mode": {
                "requested": "shelf_cell_adjusted",
                "applied": "turn_cost_repaired_grid",
            }
        },
        runtime=CoveragePlanningRuntimeDetails(
            coverage_meta={
                "shelf_ctg_auxiliary": {
                    "enabled": False,
                    "reason": "auxiliary_failed_continued_without_ctg",
                    "error_message": "edge 6 path too short",
                }
            },
            path_quality_summary={
                "available": True,
                "status": "pass",
                "coverage_ratio": 0.9987,
                "long_jump_count": 0,
                "infeasible_segment_count": 0,
            },
            provenance_summary={
                "available": True,
                "artifact_manifest": {
                    "available": True,
                    "path": "/tmp/shelf_turn_cost_run/artifact_manifest.json",
                    "artifact_paths": {
                        "path_overlay": {
                            "path": "/tmp/shelf_turn_cost_run/path_overlay.png",
                            "role": "path_visual_evidence",
                            "schema_or_format": "png",
                        },
                        "path_pixels": {
                            "path": "/tmp/shelf_turn_cost_run/path_pixels.json",
                            "role": "final_path_pixels_evidence",
                            "schema_or_format": "path_pixels_v2",
                        },
                        "candidate_decision_debug": {
                            "path": "/tmp/shelf_turn_cost_run/candidate_decision_debug.json",
                            "role": "artifact_only_candidate_decision_evidence",
                            "schema_or_format": CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION,
                        },
                    },
                },
                "candidate_decision_debug": {"available": True},
                "path_generation_provenance": {
                    "available": True,
                    "move_trace_count": 42,
                    "global_fallback_count": 3,
                    "revisit_bridge_count": 5,
                },
            },
            geometry_risk_summary={
                "available": False,
                "status": "not_run",
                "reason": "readonly_geometry_diagnostic_not_run_in_formal_planner",
            },
        ),
    )

    lines = build_routing_detail_lines(diagnostics)
    detail_text = "\n".join(lines)

    assert "策略配置:" in detail_text
    assert "产物目录=/tmp/shelf_turn_cost_run" in detail_text
    assert "Profile ID=shelf_aware_turn_cost_repaired_grid_0_28" in detail_text
    assert "Profile 版本=2" in detail_text
    assert "模式固定覆盖:" in detail_text
    assert "isolated_jump_cleanup_enable=false" in detail_text
    assert "shelf_node_generation_mode=turn_cost_repaired_grid" in detail_text
    assert "请求/生效差异:" in detail_text
    assert "shelf_node_generation_mode=shelf_cell_adjusted -> turn_cost_repaired_grid" in detail_text
    assert "CTG 辅助:" in detail_text
    assert "CTG 辅助是否生效=false" in detail_text
    assert "CTG 辅助状态原因=auxiliary_failed_continued_without_ctg" in detail_text
    assert "几何风险:" in detail_text
    assert "规划约束关系=只读诊断，不作为正式规划硬约束" in detail_text
    assert "候选决策调试是否可用=true" in detail_text
    assert "关键产物路径:" in detail_text
    assert "产物清单=/tmp/shelf_turn_cost_run/artifact_manifest.json" in detail_text
    assert "路径总览图=/tmp/shelf_turn_cost_run/path_overlay.png" in detail_text
    assert "最终像素路径=/tmp/shelf_turn_cost_run/path_pixels.json" in detail_text

    locations = build_routing_artifact_locations(diagnostics)
    assert locations[0] == {
        "key": "artifacts_dir",
        "label": "产物目录",
        "path": "/tmp/shelf_turn_cost_run",
        "kind": "directory",
    }
    assert {item["key"] for item in locations} >= {
        "artifact_manifest",
        "path_overlay",
        "path_pixels",
        "candidate_decision_debug",
    }


def test_build_routing_detail_text_prepends_compact_summary():
    diagnostics = CoveragePlanningDiagnostics(
        selected_planner="shelf_aware_turn_cost",
        scene_type="explicit",
        profile={"profile_id": "shelf_aware_turn_cost_repaired_grid_0_28", "profile_version": 2},
    )

    text = build_routing_detail_text(diagnostics)

    assert text.startswith("摘要: 规划器=shelf aware turn cost")
    assert "策略配置:" in text
    assert "Profile ID=shelf_aware_turn_cost_repaired_grid_0_28" in text


def test_show_coverage_planning_diagnostics_reports_empty_state():
    window = MainWindow.__new__(MainWindow)
    infos = []
    window._safe_showinfo = lambda title, message: infos.append((title, message))

    window._show_coverage_planning_diagnostics()

    assert infos == [("覆盖路径规划诊断", "当前会话还没有可显示的覆盖路径规划诊断。")]


def test_show_coverage_planning_diagnostics_displays_last_diagnostics():
    window = MainWindow.__new__(MainWindow)
    infos = []
    window._safe_showinfo = lambda title, message: infos.append((title, message))
    window._last_coverage_planning_diagnostics = CoveragePlanningDiagnostics(
        selected_planner="shelf_aware_turn_cost",
        scene_type="explicit",
        profile={"profile_id": "shelf_aware_turn_cost_repaired_grid_0_28", "profile_version": 2},
    )

    window._show_coverage_planning_diagnostics()

    assert infos
    assert infos[0][0] == "覆盖路径规划诊断"
    assert "摘要: 规划器=shelf aware turn cost" in infos[0][1]
    assert "Profile ID=shelf_aware_turn_cost_repaired_grid_0_28" in infos[0][1]


def test_show_coverage_planning_diagnostics_uses_artifact_location_dialog():
    window = MainWindow.__new__(MainWindow)
    infos = []
    dialogs = []
    window._safe_showinfo = lambda title, message: infos.append((title, message))
    window._safe_show_coverage_diagnostics_detail = (
        lambda title, message, locations: dialogs.append((title, message, locations))
    )
    window._last_coverage_planning_diagnostics = CoveragePlanningDiagnostics(
        selected_planner="shelf_aware_turn_cost",
        scene_type="explicit",
        artifacts_dir="/tmp/shelf_turn_cost_run",
        runtime=CoveragePlanningRuntimeDetails(
            provenance_summary={
                "available": True,
                "artifact_manifest": {
                    "available": True,
                    "path": "/tmp/shelf_turn_cost_run/artifact_manifest.json",
                    "artifact_paths": {
                        "path_overlay": {
                            "path": "/tmp/shelf_turn_cost_run/path_overlay.png",
                            "role": "path_visual_evidence",
                            "schema_or_format": "png",
                        }
                    },
                },
            }
        ),
    )

    window._show_coverage_planning_diagnostics()

    assert infos == []
    assert dialogs
    assert dialogs[0][0] == "覆盖路径规划诊断"
    assert "关键产物路径:" in dialogs[0][1]
    assert dialogs[0][2][0]["key"] == "artifacts_dir"
    assert {item["key"] for item in dialogs[0][2]} >= {"artifact_manifest", "path_overlay"}


def test_filesystem_location_target_uses_artifact_kind_before_suffix():
    assert MainWindow._filesystem_location_target("/tmp/run.with.dot", "directory") == "/tmp/run.with.dot"
    assert MainWindow._filesystem_location_target("/tmp/run/path_overlay.png", "png") == "/tmp/run"


def test_build_coverage_status_text_keeps_auto_summary():
    diagnostics = CoveragePlanningDiagnostics(
        selected_planner="region_basic",
        scene_type="room_like",
        reasons=("free_space_bbox_is_not_strongly_channel_like",),
    )

    text = build_coverage_status_text(
        total_areas=2,
        total_points=120,
        diagnostics=diagnostics,
        artifacts_dir="",
        requested_mode="auto",
    )

    assert "Coverage: 2 area(s), 120 total points." in text
    assert "Auto: 规划器=region basic" in text


def test_build_coverage_status_text_shows_explicit_planner_summary():
    diagnostics = CoveragePlanningDiagnostics(
        selected_planner="shelf_aware_turn_cost",
        scene_type="explicit",
        profile={"profile_id": "shelf_aware_turn_cost_repaired_grid_0_28"},
    )

    text = build_coverage_status_text(
        total_areas=1,
        total_points=50,
        diagnostics=diagnostics,
        artifacts_dir="",
        requested_mode="shelf_aware_turn_cost",
    )

    assert "Planner: 规划器=shelf aware turn cost" in text
    assert "策略配置=shelf aware turn cost repaired grid 0 28" in text


def test_build_session_status_text_includes_map_project_and_dirty_state():
    window = MainWindow.__new__(MainWindow)
    window.map_data = type("MapDataStub", (), {"yaml_path": "/tmp/maps/demo.yaml"})()
    window._current_project_dir = "/tmp/project_a"
    window.command_manager = type("CmdStub", (), {"can_undo": lambda self: False})()
    window.coverage_path_manager = type("PathStub", (), {"is_dirty": True})()
    window._toolbar_breakpoint = "medium"

    text = window._build_session_status_text()

    assert "Map: demo.yaml" in text
    assert "Project: project_a" in text
    assert "Dirty: Yes" in text
    assert "Layout: medium" in text


def test_get_toolbar_shortcut_hints_contains_core_shortcuts():
    window = MainWindow.__new__(MainWindow)
    hints = window._get_toolbar_shortcut_hints()

    assert "Select: V" in hints
    assert "Pan: Space" in hints
    assert "Brush: B" in hints


def test_set_tool_from_shortcut_ignores_when_editable_input_focused():
    window = MainWindow.__new__(MainWindow)
    called = []

    class _ManagerStub:
        def set_tool(self, name):
            called.append(name)

    class _EntryLike:
        @staticmethod
        def winfo_class():
            return "Entry"

    window.tool_manager = _ManagerStub()
    window.focus_get = lambda: _EntryLike()

    event = type("Event", (), {"state": 0})
    window._set_tool_from_shortcut(event, "brush", "Brush")

    assert called == []


def test_build_session_status_text_uses_toolbar_breakpoint_when_synced_value_missing():
    window = MainWindow.__new__(MainWindow)
    window.map_data = type("MapDataStub", (), {"yaml_path": "/tmp/maps/demo.yaml"})()
    window._current_project_dir = None
    window.command_manager = type("CmdStub", (), {"can_undo": lambda self: False})()
    window.coverage_path_manager = type("PathStub", (), {"is_dirty": False})()
    window._toolbar_breakpoint = None
    window.toolbar = type("ToolbarStub", (), {"current_breakpoint": "wide"})()

    text = window._build_session_status_text()

    assert "Layout: wide" in text


def test_choose_resource_path_selects_yaml_file(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    monkeypatch.setattr(
        "maptools.views.main_window.filedialog.askopenfilename",
        lambda **kwargs: "/tmp/demo.yaml",
    )
    monkeypatch.setattr(
        "maptools.views.main_window.filedialog.askdirectory",
        lambda **kwargs: "/tmp/project",
    )

    path = window._choose_resource_path()

    assert path == "/tmp/demo.yaml"


def test_choose_resource_path_selects_project_dir(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    monkeypatch.setattr(
        "maptools.views.main_window.filedialog.askopenfilename",
        lambda **kwargs: "",
    )
    monkeypatch.setattr(
        "maptools.views.main_window.filedialog.askdirectory",
        lambda **kwargs: "/tmp/project",
    )

    path = window._choose_resource_path()

    assert path == "/tmp/project"


def test_default_project_dialog_dir_prefers_current_project(tmp_path):
    current_project = tmp_path / "current_project"
    manager_project = tmp_path / "manager_project"
    map_dir = tmp_path / "maps"
    current_project.mkdir()
    manager_project.mkdir()
    map_dir.mkdir()

    window = MainWindow.__new__(MainWindow)
    window._current_project_dir = str(current_project)
    window.project_manager = type("ProjectManagerStub", (), {"project_dir": str(manager_project)})()
    window.map_data = type("MapDataStub", (), {"yaml_path": str(map_dir / "demo.yaml")})()

    assert window._default_project_dialog_dir() == str(current_project)


def test_default_project_dialog_dir_falls_back_to_map_directory(tmp_path):
    map_dir = tmp_path / "maps"
    map_dir.mkdir()

    window = MainWindow.__new__(MainWindow)
    window._current_project_dir = None
    window.project_manager = type("ProjectManagerStub", (), {"project_dir": None})()
    window.map_data = type("MapDataStub", (), {"yaml_path": str(map_dir / "demo.yaml")})()

    assert window._default_project_dialog_dir() == str(map_dir)


def test_open_project_uses_project_file_picker(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    called = []

    monkeypatch.setattr(
        "maptools.views.main_window.filedialog.askopenfilename",
        lambda **kwargs: "/tmp/demo.mapproj",
    )
    window._open_project_file = lambda path: called.append(path)

    window.open_project()

    assert called == ["/tmp/demo.mapproj"]


def test_save_project_refreshes_nav2_derivatives(monkeypatch, tmp_path):
    window = MainWindow.__new__(MainWindow)
    map_dir = tmp_path / "maps"
    save_dir = tmp_path / "project"
    map_dir.mkdir()
    save_dir.mkdir()
    window.map_data = type("MapDataStub", (), {"metadata": object(), "yaml_path": str(map_dir / "demo.yaml")})()
    window.annotations = Annotations()
    window._current_project_dir = None
    window.statusbar = type("StatusStub", (), {"messages": [], "config": lambda self, **kwargs: self.messages.append(kwargs.get("text", ""))})()
    window._show_warning = lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected warning"))
    window._show_error = lambda **kwargs: (_ for _ in ()).throw(AssertionError(f"unexpected error: {kwargs}"))
    window._save_project_extras = lambda path: extras_calls.append(path)
    window._safe_showinfo = lambda title, message: infos.append((title, message))
    save_calls = []
    export_calls = []
    extras_calls = []
    infos = []
    askdirectory_calls = []
    window.project_manager = type("ProjectManagerStub", (), {"project_dir": None, "save_project": lambda self, path: save_calls.append(path)})()

    class _ExporterStub:
        def __init__(self, map_data, annotations):
            export_calls.append(("init", map_data, annotations))

        def export(self, output_dir):
            export_calls.append(("export", output_dir))

    monkeypatch.setattr("maptools.views.main_window.Exporter", _ExporterStub)
    def _askdirectory_stub(**kwargs):
        askdirectory_calls.append(kwargs)
        return str(save_dir)

    monkeypatch.setattr("maptools.views.main_window.filedialog.askdirectory", _askdirectory_stub)

    window.save_project_as()

    assert askdirectory_calls[0]["initialdir"] == str(map_dir)
    assert save_calls == [str(save_dir)]
    assert export_calls[0][0] == "init"
    assert export_calls[1] == ("export", str(save_dir))
    assert extras_calls == [str(save_dir)]
    assert infos == [("Success", f"Project saved to {save_dir}")]


def test_save_project_uses_current_project_without_directory_picker(monkeypatch, tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    window = MainWindow.__new__(MainWindow)
    window.map_data = type("MapDataStub", (), {"metadata": object(), "yaml_path": str(project_dir / "demo.yaml")})()
    window.annotations = Annotations()
    window._current_project_dir = str(project_dir)
    window.statusbar = type("StatusStub", (), {"messages": [], "config": lambda self, **kwargs: self.messages.append(kwargs.get("text", ""))})()
    window._show_warning = lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected warning"))
    window._show_error = lambda **kwargs: (_ for _ in ()).throw(AssertionError(f"unexpected error: {kwargs}"))
    window._save_project_extras = lambda path: extras_calls.append(path)
    window._prompt_save_coverage_planner_params = lambda path: None
    window._safe_showinfo = lambda title, message: infos.append((title, message))
    save_calls = []
    export_calls = []
    extras_calls = []
    infos = []
    window.project_manager = type("ProjectManagerStub", (), {"project_dir": str(project_dir), "save_project": lambda self, path: save_calls.append(path)})()

    class _ExporterStub:
        def __init__(self, map_data, annotations):
            export_calls.append(("init", map_data, annotations))

        def export(self, output_dir):
            export_calls.append(("export", output_dir))

    monkeypatch.setattr("maptools.views.main_window.Exporter", _ExporterStub)
    monkeypatch.setattr(
        "maptools.views.main_window.filedialog.askdirectory",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("directory picker should not open")),
    )

    window.save_project()

    assert save_calls == [str(project_dir)]
    assert export_calls[1] == ("export", str(project_dir))
    assert extras_calls == [str(project_dir)]
    assert infos == [("Success", f"Project saved to {project_dir}")]


def test_safe_showinfo_ignores_destroyed_window(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    window._is_closing = False
    window.winfo_exists = lambda: False
    called = []
    monkeypatch.setattr("maptools.views.main_window.messagebox.showinfo", lambda title, message: called.append((title, message)))

    window._safe_showinfo("Success", "saved")

    assert called == []


def test_check_dirty_state_stops_after_window_destroyed():
    window = MainWindow.__new__(MainWindow)
    window._is_closing = False
    window._dirty_state_after_id = "existing"
    window.winfo_exists = lambda: False
    window.command_manager = type("CmdStub", (), {"can_undo": lambda self: True})()
    window.coverage_path_manager = type("PathStub", (), {"is_dirty": False})()

    window._check_dirty_state()

    assert window._dirty_state_after_id is None


def test_new_project_resets_session_and_loads_yaml(monkeypatch):
    window = MainWindow.__new__(MainWindow)

    class _MapDataStub:
        def __init__(self):
            self.metadata = None
            self.loaded_path = None

        def load(self, path):
            self.loaded_path = path
            self.yaml_path = path
            self.metadata = object()
            return True

    class _CanvasStub:
        def __init__(self):
            self.reference_trajectory_world = [(1.0, 2.0)]
            self.map_data = None
            self.annotations = None
            self.refresh_count = 0
            self.cleared = 0

        def set_map_data(self, map_data):
            self.map_data = map_data

        def set_annotations(self, annotations):
            self.annotations = annotations

        def refresh(self):
            self.refresh_count += 1

        def clear_reference_trajectory(self):
            self.reference_trajectory_world = []
            self.cleared += 1

    class _StatusbarStub:
        def __init__(self):
            self.text = ""

        def config(self, **kwargs):
            self.text = kwargs.get("text", self.text)

    window.map_data = _MapDataStub()
    window.annotations = Annotations()
    window.project_manager = type("ProjectManagerStub", (), {"annotations": window.annotations})()
    window.command_manager = type("CmdStub", (), {"undo_stack": [1], "redo_stack": [2]})()
    window.coverage_path_manager = CoveragePathManager()
    window.coverage_path_manager.nodes = [CoveragePathNode(0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0)]
    window.canvas = _CanvasStub()
    window.statusbar = _StatusbarStub()
    window.update = lambda: None
    window._show_error = lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error"))
    window._log_coverage_canvas_state = lambda *args, **kwargs: None
    window._current_project_dir = "/tmp/old_project"

    monkeypatch.setattr(
        "maptools.views.main_window.filedialog.askopenfilename",
        lambda **kwargs: "/tmp/demo.yaml",
    )
    monkeypatch.setattr(
        "maptools.views.main_window.messagebox.askyesno",
        lambda *args, **kwargs: False,
    )

    window.new_project()

    assert window.map_data.loaded_path == "/tmp/demo.yaml"
    assert window.command_manager.undo_stack == []
    assert window.command_manager.redo_stack == []
    assert window.coverage_path_manager.nodes == []
    assert window.canvas.map_data is window.map_data
    assert window.canvas.annotations is window.annotations
    assert window.canvas.refresh_count == 1
    assert window.canvas.cleared == 1
    assert window._current_project_dir is None


def test_save_and_restore_project_extras_round_trip(tmp_path, monkeypatch):
    export_calls = []
    import_calls = []
    expected_map_id = tmp_path.name

    def fake_export_coverage_repo(
        map_data,
        annotations,
        *,
        output_root,
        map_id,
        map_version,
        path_manager,
        auto_generate_missing,
        allow_partial_export,
    ):
        export_calls.append(
            {
                "output_root": output_root,
                "map_id": map_id,
                "map_version": map_version,
                "node_count": len(path_manager.nodes),
                "area_count": len(annotations.area_labels),
                "allow_partial_export": allow_partial_export,
            }
        )
        repo_dir = Path(output_root) / map_id
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / "coverage_path_master.yaml").write_text("map_id: demo\npaths: []\n", encoding="utf-8")

    def fake_import_coverage_repo(coverage_yaml_path, map_data, path_manager, annotations, restore_area_labels):
        import_calls.append(
            {
                "coverage_yaml_path": coverage_yaml_path,
                "restore_area_labels": restore_area_labels,
            }
        )
        path_manager.set_nodes(
            [
                CoveragePathNode(
                    id=0,
                    room=2,
                    segment=1,
                    x=1.0,
                    y=2.0,
                    yaw=0.5,
                    u=10.0,
                    v=20.0,
                    acc_dist=0.0,
                    room_dist=0.0,
                    seg_dist=0.0,
                )
            ]
        )
        return type("ImportResult", (), {"imported_nodes": 1})()

    monkeypatch.setattr("maptools.views.main_window.export_coverage_repo", fake_export_coverage_repo)
    monkeypatch.setattr("maptools.views.main_window.import_coverage_repo", fake_import_coverage_repo)

    window = MainWindow.__new__(MainWindow)
    window.map_data = type(
        "MapDataStub",
        (),
        {
            "metadata": MapMetadata(
                image_path="demo.pgm",
                resolution=0.05,
                origin=(0.0, 0.0, 0.0),
                negate=0,
                occupied_thresh=0.65,
                free_thresh=0.25,
            ),
            "yaml_path": "/tmp/demo.yaml",
            "width": 100,
            "height": 100,
        },
    )()
    window.coverage_path_manager = CoveragePathManager()
    window.coverage_path_manager.nodes = [
        CoveragePathNode(
            id=0,
            room=2,
            segment=1,
            x=1.0,
            y=2.0,
            yaw=0.5,
            u=10.0,
            v=20.0,
            acc_dist=0.0,
            room_dist=0.0,
            seg_dist=0.0,
        )
    ]
    window.canvas = type(
        "CanvasStub",
        (),
        {
            "reference_trajectory_world": [],
            "clear_reference_trajectory": lambda self: setattr(self, "reference_trajectory_world", []),
            "set_reference_trajectory": lambda self, points: setattr(self, "reference_trajectory_world", list(points)),
        },
    )()
    window.annotations = Annotations()
    window.annotations.add_area_label([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], name="Room 2", area_id=2)
    window.annotations.add_constraint_segment(
        [(3.0, 4.0), (5.0, 6.0)],
        closed=False,
        constraint_type="electronic_fence",
        name="Electronic Fence",
    )

    window._save_project_extras(str(tmp_path))

    assert export_calls == [
        {
            "output_root": str(tmp_path / "coverage_repo"),
            "map_id": expected_map_id,
            "map_version": 1,
            "node_count": 1,
            "area_count": 1,
            "allow_partial_export": True,
        }
    ]
    assert (tmp_path / "coverage_repo" / expected_map_id / "coverage_path_master.yaml").exists()
    assert (tmp_path / "coverage_repo" / "reference_trajectory.json").exists()
    assert not (tmp_path / "coverage_repo" / "coverage_paths.tsv").exists()
    assert not (tmp_path / "coverage_paths.tsv").exists()
    assert not (tmp_path / "reference_trajectory.json").exists()

    restore = MainWindow.__new__(MainWindow)
    restore.map_data = type("MapDataStub", (), {"metadata": object(), "yaml_path": "/tmp/demo.yaml"})()
    restore.coverage_path_manager = CoveragePathManager()
    restore.canvas = type(
        "CanvasStub",
        (),
        {
            "reference_trajectory_world": [],
            "clear_reference_trajectory": lambda self: setattr(self, "reference_trajectory_world", []),
            "set_reference_trajectory": lambda self, points: setattr(self, "reference_trajectory_world", list(points)),
        },
    )()
    restore.annotations = Annotations()

    notes = restore._restore_project_extras(str(tmp_path))

    assert len(restore.coverage_path_manager.nodes) == 1
    assert restore.coverage_path_manager.nodes[0].room == 2
    fence_segments = list(restore.annotations.iter_constraint_segments("electronic_fence", closed=False))
    assert len(fence_segments) == 1
    assert fence_segments[0].points == [(3.0, 4.0), (5.0, 6.0)]
    assert import_calls == [
        {
            "coverage_yaml_path": str(tmp_path / "coverage_repo" / expected_map_id / "coverage_path_master.yaml"),
            "restore_area_labels": True,
        }
    ]
    assert "path_nodes=1" in notes
    assert "fence_points=2" in notes


def test_navigation_map_id_uses_project_name_when_project_is_open(tmp_path):
    project_dir = tmp_path / "beiguoshangcheng_floor_3"
    yaml_path = project_dir / "beiguoshangcheng_floor_3.yaml"
    project_dir.mkdir(parents=True)
    yaml_path.write_text("image: beiguoshangcheng_floor_3.pgm\n", encoding="utf-8")

    window = MainWindow.__new__(MainWindow)
    window.map_data = type("MapDataStub", (), {"yaml_path": str(yaml_path)})()
    window.project_manager = type("ProjectManagerStub", (), {"project_dir": str(project_dir)})()
    window._current_project_dir = None

    assert window._resolve_navigation_map_id() == "beiguoshangcheng_floor_3"


def test_save_project_extras_keeps_project_saved_when_coverage_repo_preflight_blocks(tmp_path, monkeypatch):
    export_calls = []
    monkeypatch.setattr("maptools.views.main_window.export_coverage_repo", lambda *args, **kwargs: export_calls.append((args, kwargs)))
    window = MainWindow.__new__(MainWindow)
    window.map_data = type(
        "MapDataStub",
        (),
        {
            "metadata": MapMetadata(
                image_path="demo.pgm",
                resolution=0.05,
                origin=(0.0, 0.0, 0.0),
                negate=0,
                occupied_thresh=0.65,
                free_thresh=0.25,
            ),
            "yaml_path": "/tmp/demo.yaml",
            "width": 100,
            "height": 100,
        },
    )()
    window.coverage_path_manager = CoveragePathManager()
    window.coverage_path_manager.nodes = [
        CoveragePathNode(
            id=0,
            room=1,
            segment=1,
            x=0.2,
            y=0.2,
            yaw=0.0,
            u=4.0,
            v=96.0,
            acc_dist=0.0,
            room_dist=0.0,
            seg_dist=0.0,
        )
    ]
    window.canvas = type("CanvasStub", (), {"reference_trajectory_world": []})()
    window.annotations = Annotations()
    window.annotations.add_area_label([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)], name="A", area_id=1)
    window.annotations.add_area_label([(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)], name="B", area_id=2)

    window._save_project_extras(str(tmp_path))

    assert export_calls == []
    assert any("area_overlap" in warning for warning in window._last_project_extra_warnings)
    report = json.loads((tmp_path / "coverage_repo" / "export_preflight_report.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert any("area_overlap" in issue for issue in report["issues"])


def test_load_electronic_fence_path_imports_editable_constraint_segment(tmp_path):
    trajectory_path = tmp_path / "trajectory_from_tf.jsonl"
    trajectory_path.write_text(
        "\n".join(
            [
                '{"pose": {"x": 1.0, "y": 2.0}}',
                '{"pose": {"x": 3.0, "y": 4.0}}',
                '{"pose": {"x": 5.0, "y": 6.0}}',
            ]
        ),
        encoding="utf-8",
    )

    window = MainWindow.__new__(MainWindow)
    window.map_data = type("MapDataStub", (), {"metadata": object(), "yaml_path": "/tmp/demo.yaml"})()
    window.annotations = Annotations()
    window.canvas = type(
        "CanvasStub",
        (),
        {
            "reference_trajectory_world": [(9.0, 9.0)],
            "clear_reference_trajectory": lambda self: setattr(self, "reference_trajectory_world", []),
            "refresh": lambda self: None,
        },
    )()
    window.statusbar = type("StatusStub", (), {"config": lambda self, **kwargs: None})()
    window.update = lambda: None
    window._show_error = lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected error"))

    window._load_electronic_fence_path(str(trajectory_path))

    fence_segments = list(window.annotations.iter_constraint_segments("electronic_fence", closed=False))
    assert len(fence_segments) == 1
    assert fence_segments[0].points == [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]
    assert fence_segments[0].metadata == {}
    assert window.canvas.reference_trajectory_world == []


def test_resolve_electronic_fence_summary_uses_summary_relative_jsonl(tmp_path):
    trajectory_path = tmp_path / "trajectory_from_tf.jsonl"
    trajectory_path.write_text("", encoding="utf-8")
    summary_path = tmp_path / "summary.json"
    summary_path.write_text('{"jsonl_path": "trajectory_from_tf.jsonl"}\n', encoding="utf-8")

    window = MainWindow.__new__(MainWindow)

    assert window._resolve_electronic_fence_path(str(summary_path)) == str(trajectory_path.resolve())


def _build_constraint_window():
    window = MainWindow.__new__(MainWindow)
    window.annotations = Annotations()
    window.canvas = type(
        "CanvasStub",
        (),
        {
            "selected_item": None,
            "selected_type": None,
            "selected_constraint_segment_ids": set(),
            "refresh": lambda self: None,
            "get_selected_constraint_segments": lambda self: [
                segment
                for segment in window.annotations.constraint_segments
                if segment.id in self.selected_constraint_segment_ids
            ],
        },
    )()
    window.statusbar = type("StatusStub", (), {"messages": [], "config": lambda self, **kwargs: self.messages.append(kwargs.get("text", ""))})()
    window.command_manager = type("CmdStub", (), {"execute": lambda self, cmd: cmd.execute()})()
    warnings = []
    window._show_warning = lambda **kwargs: warnings.append(kwargs)
    return window, warnings


def _make_component_map_data(grid: np.ndarray, *, resolution: float = 0.5) -> MapData:
    map_data = MapData()
    map_data.metadata = MapMetadata(
        image_path="demo.pgm",
        resolution=resolution,
        origin=(0.0, 0.0, 0.0),
        negate=0,
        occupied_thresh=0.65,
        free_thresh=0.25,
        mode="trinary",
    )
    map_data.base_image = Image.fromarray(grid)
    map_data.grid_map = grid.copy()
    map_data.edit_layer = np.full_like(grid, 255, dtype=np.uint8)
    map_data.yaml_path = str(Path("/tmp/demo.yaml"))
    map_data.width = int(grid.shape[1])
    map_data.height = int(grid.shape[0])
    return map_data


def _prepare_single_component_constraint_window():
    window, warnings = _build_constraint_window()
    grid = np.zeros((12, 12), dtype=np.uint8)
    grid[2:10, 2:10] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.15
    window.canvas.small_component_no_coverage_threshold_m2 = 1000.0
    _recompute_free_space_components(window)
    return window, warnings


def _recompute_free_space_components(window):
    from maptools.utils.free_space_components import analyze_free_space_components

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=float(window.canvas.free_space_component_repair_radius_m),
        small_component_threshold_m2=float(window.canvas.small_component_no_coverage_threshold_m2),
    )
    return window.canvas.free_space_components_result


def _current_component_semantic_state(window):
    forbidden_regions = list(window.annotations.iter_derived_constraint_regions("forbidden_zone"))
    no_coverage_regions = list(window.annotations.iter_derived_constraint_regions("no_coverage"))
    assert not (forbidden_regions and no_coverage_regions)
    if forbidden_regions:
        assert len(forbidden_regions) == 1
        return "forbidden_zone", forbidden_regions[0]
    if no_coverage_regions:
        assert len(no_coverage_regions) == 1
        return "no_coverage", no_coverage_regions[0]
    return "free", None


def _roundtrip_constraint_annotations(window, tmp_path: Path, step_name: str):
    path = tmp_path / f"{step_name}.json"
    window.annotations.save(str(path))
    restored = Annotations()
    restored.load(str(path))
    window.annotations = restored
    _recompute_free_space_components(window)


def _apply_component_semantic_action(window, action: str):
    state, target_region = _current_component_semantic_state(window)
    result = _recompute_free_space_components(window)
    component_id = (
        int(target_region.component_id)
        if target_region is not None
        else next(iter(result.component_stats))
    )
    if action == "free":
        window._restore_free_space_component(component_id, target_region=target_region)
    else:
        window._apply_free_space_component_constraint(component_id, action, target_region=target_region)
    _recompute_free_space_components(window)


def _assert_component_semantic_state(window, expected_state: str):
    state, region = _current_component_semantic_state(window)
    assert state == expected_state
    result = window.canvas.free_space_components_result
    if expected_state == "free":
        assert region is None
        assert len(result.component_stats) == 1
        return
    assert region is not None
    assert str(region.action_type) == expected_state
    if expected_state == "forbidden_zone":
        assert len(result.component_stats) == 0
        assert window.statusbar.messages[-1].endswith("color=#ff4d4f")
        return
    assert len(result.component_stats) == 1
    assert window.statusbar.messages[-1].endswith("color=#ff7a45")


def test_split_constraint_segment_at_internal_vertex():
    window, warnings = _build_constraint_window()
    segment = window.annotations.add_constraint_segment(
        [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)],
        closed=False,
        constraint_type="electronic_fence",
        name="Fence",
        item_id="fence-1",
    )
    window.canvas.selected_item = segment
    window.canvas.selected_type = "constraint_segments"

    window._split_constraint_segment_at_vertex(segment, 2)

    segments = sorted(window.annotations.iter_constraint_segments("electronic_fence", closed=False), key=lambda item: item.id)
    assert warnings == []
    assert [item.id for item in segments] == ["fence-1__a", "fence-1__b"]
    assert segments[0].points == [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    assert segments[1].points == [(2.0, 0.0), (3.0, 0.0)]


def test_split_closed_constraint_segment_opens_ring():
    window, warnings = _build_constraint_window()
    segment = window.annotations.add_constraint_segment(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        closed=True,
        constraint_type="forbidden_zone",
        name="Forbidden",
        item_id="fz-1",
    )
    window.canvas.selected_item = segment
    window.canvas.selected_type = "constraint_segments"

    window._split_constraint_segment_at_vertex(segment, 2)

    segments = list(window.annotations.iter_constraint_segments("forbidden_zone"))
    assert warnings == []
    assert len(segments) == 1
    assert segments[0].closed is False
    assert segments[0].points == [(1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]


def test_toggle_constraint_segment_closed_round_trip():
    window, warnings = _build_constraint_window()
    segment = window.annotations.add_constraint_segment(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
        closed=False,
        constraint_type="electronic_fence",
        name="Fence",
        item_id="fence-2",
    )
    window.canvas.selected_item = segment
    window.canvas.selected_type = "constraint_segments"

    window._toggle_constraint_segment_closed(segment)
    closed_segment = next(window.annotations.iter_constraint_segments("electronic_fence"))
    assert warnings == []
    assert closed_segment.closed is True

    window.canvas.selected_item = closed_segment
    window._toggle_constraint_segment_closed(closed_segment)
    reopened_segment = next(window.annotations.iter_constraint_segments("electronic_fence"))
    assert reopened_segment.closed is False


def test_change_constraint_segment_type_updates_shape_semantics():
    window, warnings = _build_constraint_window()
    segment = window.annotations.add_constraint_segment(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
        closed=False,
        constraint_type="electronic_fence",
        name="Electronic Fence",
        item_id="fence-3",
    )
    window.canvas.selected_item = segment
    window.canvas.selected_type = "constraint_segments"

    window._change_constraint_segment_type(segment, "forbidden_zone")

    forbidden = next(window.annotations.iter_constraint_segments("forbidden_zone"))
    assert warnings == []
    assert forbidden.closed is True
    assert forbidden.color == "#ff4d4f"
    assert forbidden.name == "Forbidden Zone"

    window.canvas.selected_item = forbidden
    window._change_constraint_segment_type(forbidden, "virtual_wall")
    virtual_wall = next(window.annotations.iter_constraint_segments("virtual_wall", closed=False))
    assert virtual_wall.closed is False
    assert virtual_wall.color == "#1e6cff"
    assert virtual_wall.name == "Virtual Wall"


def test_constraint_segment_style_uses_stipple_fill_for_no_coverage():
    outline, fill, stipple = MapCanvas._constraint_segment_style("no_coverage")

    assert outline == "#ff7a45"
    assert fill == "#ff7a45"
    assert stipple == "gray25"


def test_constraint_segment_style_uses_stipple_fill_for_forbidden_zone():
    outline, fill, stipple = MapCanvas._constraint_segment_style("forbidden_zone")

    assert outline == "#ff4d4f"
    assert fill == "#ff4d4f"
    assert stipple == "gray25"


def test_merge_constraint_segments_joins_matching_open_segments():
    window, warnings = _build_constraint_window()
    first = window.annotations.add_constraint_segment(
        [(0.0, 0.0), (1.0, 0.0)],
        closed=False,
        constraint_type="electronic_fence",
        name="Fence A",
        item_id="fence-a",
    )
    window.annotations.add_constraint_segment(
        [(1.0, 0.0), (2.0, 0.0), (3.0, 0.0)],
        closed=False,
        constraint_type="electronic_fence",
        name="Fence B",
        item_id="fence-b",
    )
    window.canvas.selected_item = first
    window.canvas.selected_type = "constraint_segments"

    assert window._can_merge_constraint_segment(first) is True
    window._merge_constraint_segment(first)

    segments = list(window.annotations.iter_constraint_segments("electronic_fence", closed=False))
    assert warnings == []
    assert len(segments) == 1
    assert segments[0].id == "fence-a"
    assert segments[0].points == [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]


def test_merge_selected_constraint_segments_auto_merges_chain():
    window, warnings = _build_constraint_window()
    window.annotations.add_constraint_segment(
        [(0.0, 0.0), (1.0, 0.0)],
        closed=False,
        constraint_type="electronic_fence",
        name="Fence A",
        item_id="fence-a",
    )
    window.annotations.add_constraint_segment(
        [(1.0, 0.0), (2.0, 0.0)],
        closed=False,
        constraint_type="electronic_fence",
        name="Fence B",
        item_id="fence-b",
    )
    window.annotations.add_constraint_segment(
        [(2.0, 0.0), (3.0, 0.0)],
        closed=False,
        constraint_type="electronic_fence",
        name="Fence C",
        item_id="fence-c",
    )
    window.canvas.selected_constraint_segment_ids = {"fence-a", "fence-b", "fence-c"}

    window._merge_selected_constraint_segments()

    segments = list(window.annotations.iter_constraint_segments("electronic_fence", closed=False))
    assert warnings == []
    assert len(segments) == 1
    assert segments[0].points == [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]
    assert window.canvas.selected_constraint_segment_ids == {"fence-a"}


def test_can_merge_selected_constraint_segments_uses_endpoint_tolerance():
    window, warnings = _build_constraint_window()
    window.annotations.add_constraint_segment(
        [(0.0, 0.0), (1.0, 0.0)],
        closed=False,
        constraint_type="electronic_fence",
        name="Fence A",
        item_id="fence-a",
    )
    window.annotations.add_constraint_segment(
        [(1.03, 0.0), (2.0, 0.0)],
        closed=False,
        constraint_type="electronic_fence",
        name="Fence B",
        item_id="fence-b",
    )
    window.canvas.selected_constraint_segment_ids = {"fence-a", "fence-b"}

    assert warnings == []
    assert window._can_merge_selected_constraint_segments() is True


def test_apply_free_space_component_constraint_creates_no_coverage_region():
    window, warnings = _build_constraint_window()
    grid = np.zeros((12, 12), dtype=np.uint8)
    grid[2:10, 2:10] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.5
    window.canvas.small_component_no_coverage_threshold_m2 = 3.0
    from maptools.utils.free_space_components import analyze_free_space_components

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.0,
        small_component_threshold_m2=3.0,
    )
    component_id = next(iter(window.canvas.free_space_components_result.component_stats))

    window._apply_free_space_component_constraint(component_id, "no_coverage")

    regions = list(window.annotations.iter_derived_constraint_regions("no_coverage"))
    assert warnings == []
    assert len(regions) == 1
    assert int(regions[0].component_id) == int(component_id)
    assert regions[0].bbox_px[2] > 0
    assert window.statusbar.messages[-1].endswith("color=#ff7a45")


def test_apply_free_space_component_constraint_can_switch_forbidden_to_no_coverage_after_recompute():
    window, warnings = _build_constraint_window()
    grid = np.zeros((12, 12), dtype=np.uint8)
    grid[2:10, 2:10] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.15
    window.canvas.small_component_no_coverage_threshold_m2 = 1000.0
    from maptools.utils.free_space_components import analyze_free_space_components

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    component_id = next(iter(window.canvas.free_space_components_result.component_stats))

    window._apply_free_space_component_constraint(component_id, "forbidden_zone")
    assert len(list(window.annotations.iter_derived_constraint_regions("forbidden_zone"))) == 1

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    assert window.canvas.free_space_components_result.stat_for_label(component_id) is None

    window._apply_free_space_component_constraint(component_id, "no_coverage")

    assert warnings == []
    assert len(list(window.annotations.iter_derived_constraint_regions("forbidden_zone"))) == 0
    regions = list(window.annotations.iter_derived_constraint_regions("no_coverage"))
    assert len(regions) == 1
    assert int(regions[0].component_id) == int(component_id)
    assert window.statusbar.messages[-1].endswith("color=#ff7a45")


def test_apply_free_space_component_constraint_keeps_multiple_forbidden_regions_after_relabel():
    window, warnings = _build_constraint_window()
    grid = np.zeros((24, 24), dtype=np.uint8)
    grid[2:8, 2:8] = 254
    grid[10:16, 10:16] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.15
    window.canvas.small_component_no_coverage_threshold_m2 = 1000.0
    from maptools.utils.free_space_components import analyze_free_space_components

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    first_component_id = next(iter(window.canvas.free_space_components_result.component_stats))
    window._apply_free_space_component_constraint(first_component_id, "forbidden_zone")

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    second_component_id = next(iter(window.canvas.free_space_components_result.component_stats))
    window._apply_free_space_component_constraint(second_component_id, "forbidden_zone")

    assert warnings == []
    regions = list(window.annotations.iter_derived_constraint_regions("forbidden_zone"))
    assert len(regions) == 2
    keys = {str(region.metadata.get("component_key", "")) for region in regions}
    assert len(keys) == 2
    assert all(len(key.split(":")) == 5 for key in keys)
    assert len({region.id for region in regions}) == 2


def test_apply_free_space_component_constraint_keeps_multiple_no_coverage_regions_after_relabel():
    window, warnings = _build_constraint_window()
    grid = np.zeros((24, 24), dtype=np.uint8)
    grid[2:8, 2:8] = 254
    grid[10:16, 10:16] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.15
    window.canvas.small_component_no_coverage_threshold_m2 = 1000.0
    from maptools.utils.free_space_components import analyze_free_space_components

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    first_component_id = next(iter(window.canvas.free_space_components_result.component_stats))
    window._apply_free_space_component_constraint(first_component_id, "no_coverage")

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    second_component_id = next(
        component_id
        for component_id in window.canvas.free_space_components_result.component_stats
        if int(component_id) != int(first_component_id)
    )
    window._apply_free_space_component_constraint(second_component_id, "no_coverage")

    assert warnings == []
    regions = list(window.annotations.iter_derived_constraint_regions("no_coverage"))
    assert len(regions) == 2
    keys = {str(region.metadata.get("component_key", "")) for region in regions}
    assert len(keys) == 2
    assert len({region.id for region in regions}) == 2


def test_restore_free_space_component_by_derived_region_removes_only_target_region():
    window, warnings = _build_constraint_window()
    grid = np.zeros((24, 24), dtype=np.uint8)
    grid[2:8, 2:8] = 254
    grid[10:16, 10:16] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.15
    window.canvas.small_component_no_coverage_threshold_m2 = 1000.0
    from maptools.utils.free_space_components import analyze_free_space_components

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    first_component_id = next(iter(window.canvas.free_space_components_result.component_stats))
    window._apply_free_space_component_constraint(first_component_id, "forbidden_zone")

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    second_component_id = next(iter(window.canvas.free_space_components_result.component_stats))
    window._apply_free_space_component_constraint(second_component_id, "forbidden_zone")
    regions = list(window.annotations.iter_derived_constraint_regions("forbidden_zone"))
    target = regions[0]

    window._restore_free_space_component(int(target.component_id), target_region=target)

    assert warnings == []
    remaining = list(window.annotations.iter_derived_constraint_regions("forbidden_zone"))
    assert len(remaining) == 1
    assert str(remaining[0].metadata.get("component_key", "")) != str(target.metadata.get("component_key", ""))


def test_generate_polygon_constraint_after_forbidden_recompute_uses_target_region_fallback():
    window, warnings = _build_constraint_window()
    grid = np.zeros((12, 12), dtype=np.uint8)
    grid[2:10, 2:10] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.15
    window.canvas.small_component_no_coverage_threshold_m2 = 1000.0
    from maptools.utils.free_space_components import analyze_free_space_components

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    component_id = next(iter(window.canvas.free_space_components_result.component_stats))
    window._apply_free_space_component_constraint(component_id, "forbidden_zone")
    target = next(window.annotations.iter_derived_constraint_regions("forbidden_zone"))

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    assert window.canvas.free_space_components_result.stat_for_label(component_id) is None

    window._generate_free_space_component_polygon_constraint(component_id, "no_coverage", target_region=target)

    assert warnings == []
    segments = list(window.annotations.iter_constraint_segments("no_coverage", closed=True))
    assert len(segments) == 1
    assert len(segments[0].points) >= 3


def test_apply_constraint_from_derived_region_reuses_target_mask_after_relabel():
    window, warnings = _build_constraint_window()
    grid = np.zeros((24, 24), dtype=np.uint8)
    grid[2:8, 2:8] = 254
    grid[12:18, 12:18] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.15
    window.canvas.small_component_no_coverage_threshold_m2 = 1000.0
    from maptools.utils.free_space_components import analyze_free_space_components

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    component_id = next(iter(window.canvas.free_space_components_result.component_stats))
    window._apply_free_space_component_constraint(component_id, "forbidden_zone")
    target = next(window.annotations.iter_derived_constraint_regions("forbidden_zone"))
    target_key = str(target.metadata.get("component_key", ""))

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    relabeled_stat = window.canvas.free_space_components_result.stat_for_label(component_id)
    assert relabeled_stat is not None
    assert MainWindow._component_key_from_bbox_mask(relabeled_stat.bbox_px) != target_key

    window._apply_free_space_component_constraint(
        int(target.component_id),
        "no_coverage",
        target_region=target,
    )

    assert warnings == []
    assert list(window.annotations.iter_derived_constraint_regions("forbidden_zone")) == []
    regions = list(window.annotations.iter_derived_constraint_regions("no_coverage"))
    assert len(regions) == 1
    assert str(regions[0].metadata.get("component_key", "")) == target_key


def test_show_free_space_component_menu_freezes_derived_region_target(monkeypatch):
    window, warnings = _build_constraint_window()
    grid = np.zeros((24, 24), dtype=np.uint8)
    grid[2:8, 2:8] = 254
    grid[12:18, 12:18] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.15
    window.canvas.small_component_no_coverage_threshold_m2 = 1000.0
    from maptools.utils.free_space_components import analyze_free_space_components

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    component_id = next(iter(window.canvas.free_space_components_result.component_stats))
    window._apply_free_space_component_constraint(component_id, "forbidden_zone")
    target = next(window.annotations.iter_derived_constraint_regions("forbidden_zone"))
    target_key = str(target.metadata.get("component_key", ""))

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    relabeled_stat = window.canvas.free_space_components_result.stat_for_label(component_id)
    assert relabeled_stat is not None
    assert MainWindow._component_key_from_bbox_mask(relabeled_stat.bbox_px) != target_key

    created_menus = []

    class _MenuStub:
        def __init__(self, *args, **kwargs):
            self.commands = []
            created_menus.append(self)

        def add_command(self, **kwargs):
            self.commands.append(kwargs)

        def add_separator(self):
            pass

        def tk_popup(self, *args):
            pass

    monkeypatch.setattr("maptools.views.main_window.tk.Menu", _MenuStub)
    event = type("Event", (), {"x_root": 10, "y_root": 20})()

    window._show_free_space_component_menu(event, int(target.component_id), derived_region=target)
    created_menus[-1].commands[1]["command"]()

    assert warnings == []
    assert list(window.annotations.iter_derived_constraint_regions("forbidden_zone")) == []
    regions = list(window.annotations.iter_derived_constraint_regions("no_coverage"))
    assert len(regions) == 1
    assert str(regions[0].metadata.get("component_key", "")) == target_key


def test_apply_constraint_without_target_region_rejects_ambiguous_component_id():
    window, warnings = _build_constraint_window()
    grid = np.zeros((24, 24), dtype=np.uint8)
    grid[2:8, 2:8] = 254
    grid[12:18, 12:18] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.15
    window.canvas.small_component_no_coverage_threshold_m2 = 1000.0
    from maptools.utils.free_space_components import analyze_free_space_components

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    first_component_id = next(iter(window.canvas.free_space_components_result.component_stats))
    window._apply_free_space_component_constraint(first_component_id, "no_coverage")

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    second_component_id = next(
        component_id
        for component_id in window.canvas.free_space_components_result.component_stats
        if int(component_id) != int(first_component_id)
    )
    window._apply_free_space_component_constraint(second_component_id, "no_coverage")
    for region in window.annotations.derived_constraint_regions:
        region.component_id = 99
        region.metadata["component_id"] = 99

    window._apply_free_space_component_constraint(99, "forbidden_zone")

    assert len(warnings) == 1
    assert warnings[0]["problem"] == "自由连通区掩膜提取失败"
    assert len(list(window.annotations.iter_derived_constraint_regions("no_coverage"))) == 2
    assert len(list(window.annotations.iter_derived_constraint_regions("forbidden_zone"))) == 0


def test_generate_polygon_from_derived_region_reuses_target_mask_after_relabel():
    window, warnings = _build_constraint_window()
    grid = np.zeros((24, 24), dtype=np.uint8)
    grid[2:8, 2:8] = 254
    grid[12:18, 12:18] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.15
    window.canvas.small_component_no_coverage_threshold_m2 = 1000.0
    from maptools.utils.free_space_components import analyze_free_space_components

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    component_id = next(iter(window.canvas.free_space_components_result.component_stats))
    window._apply_free_space_component_constraint(component_id, "forbidden_zone")
    target = next(window.annotations.iter_derived_constraint_regions("forbidden_zone"))
    target_key = str(target.metadata.get("component_key", ""))

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    relabeled_stat = window.canvas.free_space_components_result.stat_for_label(component_id)
    assert relabeled_stat is not None
    assert MainWindow._component_key_from_bbox_mask(relabeled_stat.bbox_px) != target_key

    window._generate_free_space_component_polygon_constraint(
        int(target.component_id),
        "no_coverage",
        target_region=target,
    )

    assert warnings == []
    segments = list(window.annotations.iter_constraint_segments("no_coverage", closed=True))
    assert len(segments) == 1
    assert str(segments[0].metadata.get("component_key", "")) == target_key
    resolution = float(window.map_data.metadata.resolution)
    height = int(window.map_data.height)
    xs = [float(wx) / resolution for wx, _ in segments[0].points]
    ys = [height - float(wy) / resolution for _, wy in segments[0].points]
    assert max(xs) < 10
    assert max(ys) < 10


def test_restore_free_space_component_removes_matching_no_coverage_region():
    window, warnings = _build_constraint_window()
    grid = np.zeros((12, 12), dtype=np.uint8)
    grid[2:10, 2:10] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.5
    window.canvas.small_component_no_coverage_threshold_m2 = 3.0
    from maptools.utils.free_space_components import analyze_free_space_components

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.0,
        small_component_threshold_m2=3.0,
    )
    component_id = next(iter(window.canvas.free_space_components_result.component_stats))
    window._apply_free_space_component_constraint(component_id, "no_coverage")
    assert len(list(window.annotations.iter_derived_constraint_regions("no_coverage"))) == 1

    window._restore_free_space_component(component_id)

    assert warnings == []
    assert len(list(window.annotations.iter_derived_constraint_regions("no_coverage"))) == 0


def test_apply_small_components_as_no_coverage_marks_only_suggested_components():
    window, warnings = _build_constraint_window()
    grid = np.zeros((16, 16), dtype=np.uint8)
    grid[1:4, 1:4] = 254
    grid[8:15, 8:15] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.0
    window.canvas.small_component_no_coverage_threshold_m2 = 3.0
    from maptools.utils.free_space_components import analyze_free_space_components

    window._free_space_components_var = type("Var", (), {"get": lambda self: True})()
    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.0,
        small_component_threshold_m2=3.0,
    )

    window._apply_small_components_as_no_coverage()

    regions = list(window.annotations.iter_derived_constraint_regions("no_coverage"))
    assert warnings == []
    assert len(regions) == 1
    assert "color=#ff7a45" in window.statusbar.messages[-1]


def test_apply_unknown_areas_as_forbidden_creates_undoable_regions(monkeypatch):
    window, warnings = _build_constraint_window()
    grid = np.full((10, 12), 254, dtype=np.uint8)
    grid[1:3, 1:3] = 205
    grid[5:7, 7:10] = 205
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.command_manager = CommandManager()
    window.annotations.add_forbidden_zone(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
        name="Manual Forbidden",
        item_id="manual-forbidden",
    )
    monkeypatch.setattr("maptools.views.main_window.messagebox.askyesno", lambda *args, **kwargs: True)

    window._apply_unknown_areas_as_forbidden()

    assert warnings == []
    regions = list(window.annotations.iter_derived_constraint_regions("forbidden_zone"))
    assert len(regions) == 1
    assert {region.source for region in regions} == {"unknown_region"}
    assert regions[0].component_area_m2 == 2.5
    assert regions[0].metadata["component_count"] == 2
    assert len(list(window.annotations.iter_constraint_segments("forbidden_zone", closed=True))) == 1
    assert "Applied 1 unknown area(s) as forbidden" in window.statusbar.messages[-1]
    assert "components=2" in window.statusbar.messages[-1]

    window.command_manager.undo()

    assert list(window.annotations.iter_derived_constraint_regions("forbidden_zone")) == []
    assert len(list(window.annotations.iter_constraint_segments("forbidden_zone", closed=True))) == 1


def test_apply_unknown_areas_as_forbidden_replaces_previous_unknown_regions(monkeypatch):
    window, warnings = _build_constraint_window()
    grid = np.full((10, 12), 254, dtype=np.uint8)
    grid[1:3, 1:3] = 205
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    monkeypatch.setattr("maptools.views.main_window.messagebox.askyesno", lambda *args, **kwargs: True)

    window._apply_unknown_areas_as_forbidden()
    first_ids = {region.id for region in window.annotations.iter_derived_constraint_regions("forbidden_zone")}
    grid[6:8, 8:10] = 205
    window.map_data.grid_map = grid.copy()
    window.map_data.base_image = Image.fromarray(grid)
    window.map_data._display_dirty = True

    window._apply_unknown_areas_as_forbidden()

    assert warnings == []
    regions = list(window.annotations.iter_derived_constraint_regions("forbidden_zone"))
    assert len(regions) == 1
    assert first_ids.isdisjoint({region.id for region in regions})
    assert regions[0].metadata["component_count"] == 2


def test_hit_test_derived_constraint_region_finds_semantic_region():
    annotations = Annotations()
    mask = np.array(
        [
            [255, 255, 0],
            [255, 255, 0],
        ],
        dtype=np.uint8,
    )
    annotations.set_derived_constraint_regions(
        [
            DerivedConstraintRegion(
                id="derived-1",
                name="Component 7 Forbidden Region",
                action_type="forbidden_zone",
                source="free_space_component",
                component_id=7,
                bbox_px=(10, 20, 3, 2),
                packed_mask_b64=annotations.encode_binary_mask_packbits(mask),
                repair_radius_m=0.15,
                component_area_m2=1.0,
                metadata={"component_id": 7},
            )
        ]
    )
    canvas = MapCanvas.__new__(MapCanvas)
    canvas.show_annotations = True
    canvas.annotations = annotations
    canvas.zoom_level = 1.0
    canvas.pan_offset_x = 0
    canvas.pan_offset_y = 0
    canvas.canvasx = lambda value: value
    canvas.canvasy = lambda value: value
    canvas.canvas_to_image = MapCanvas.canvas_to_image.__get__(canvas, MapCanvas)

    region = canvas._hit_test_derived_constraint_region(11, 21)
    assert region is not None
    assert region.component_id == 7
    assert canvas._hit_test_derived_constraint_region(12, 21) is None


def test_visible_derived_constraint_region_index_filters_far_regions():
    annotations = Annotations()
    regions = []
    for index in range(100):
        x = index * 300
        mask = np.ones((2, 2), dtype=np.uint8) * 255
        regions.append(
            DerivedConstraintRegion(
                id=f"derived-{index}",
                name=f"Derived {index}",
                action_type="forbidden_zone",
                source="unknown_region",
                component_id=index + 1,
                bbox_px=(x, 0, 2, 2),
                packed_mask_b64=annotations.encode_binary_mask_packbits(mask),
                component_area_m2=1.0,
            )
        )
    annotations.set_derived_constraint_regions(regions)
    canvas = MapCanvas.__new__(MapCanvas)
    canvas.annotations = annotations
    canvas._derived_region_index_cache = None
    canvas._derived_region_mask_cache = {}

    visible = list(canvas._iter_visible_derived_constraint_regions(0, 0, 100, 100))

    assert [region.id for region, *_ in visible] == ["derived-0"]


def test_zoom_refresh_is_throttled_to_one_pending_frame():
    canvas = MapCanvas.__new__(MapCanvas)
    canvas._zoom_refresh_after_id = None
    scheduled = []
    refreshes = []
    canvas.after = lambda delay, callback: scheduled.append((delay, callback)) or "after-1"
    canvas.refresh = lambda: refreshes.append("refresh")

    canvas._schedule_zoom_refresh()
    canvas._schedule_zoom_refresh()

    assert len(scheduled) == 1
    assert scheduled[0][0] == 16
    scheduled[0][1]()
    assert canvas._zoom_refresh_after_id is None
    assert refreshes == ["refresh"]


def test_on_right_click_combines_area_label_and_free_space_component_menu():
    canvas = MapCanvas.__new__(MapCanvas)
    canvas.annotations = Annotations()
    area = canvas.annotations.add_area_label(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
        name="Room 1",
        area_id=1,
    )
    canvas.coord_transformer = object()
    canvas.show_area_labels = True
    canvas.has_coverage_path_for = lambda area_label: False
    triggered = []
    canvas._trigger_coverage = lambda area_label: triggered.append(("coverage", int(area_label.area_id)))
    canvas._hit_test_area_label = lambda x, y: area
    canvas._hit_test_free_space_component = lambda x, y: 11
    canvas._hit_test_derived_constraint_region = lambda x, y: None
    canvas._hit_test_constraint_segment = lambda x, y: (None, None)
    captured = []

    class _MenuStub:
        def __init__(self, *args, **kwargs):
            self.commands = []
            captured.append(self)

        def add_command(self, **kwargs):
            self.commands.append(kwargs)

        def add_separator(self):
            self.commands.append({"separator": True})

        def tk_popup(self, *args):
            pass

    toplevel = type(
        "TopLevelStub",
        (),
        {
            "_populate_free_space_component_menu": lambda self, menu, component_id, derived_region=None: (
                menu.add_command(label=f"置为禁止区 - component {component_id}", command=lambda: triggered.append(("free", int(component_id))))
                or True
            )
        },
    )()
    canvas.winfo_toplevel = lambda: toplevel

    old_menu = tk.Menu
    tk.Menu = _MenuStub
    try:
        canvas._on_right_click(type("Event", (), {"x": 10, "y": 20, "x_root": 30, "y_root": 40})())
    finally:
        tk.Menu = old_menu

    command_items = [item for item in captured[-1].commands if "label" in item]
    labels = [item.get("label") for item in command_items]
    assert labels == [
        "生成覆盖路径 - 1",
        "置为禁止区 - component 11",
    ]
    command_items[0]["command"]()
    command_items[1]["command"]()
    assert triggered == [("coverage", 1), ("free", 11)]
    assert canvas.selected_item is area
    assert canvas.selected_type == "area_labels"


def test_on_right_click_syncs_area_room_to_path_params_panel():
    canvas = MapCanvas.__new__(MapCanvas)
    canvas.annotations = Annotations()
    area = canvas.annotations.add_area_label(
        [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)],
        area_id=8,
    )
    canvas.coord_transformer = type(
        "TransformerStub",
        (),
        {"canvas_to_world": lambda self, x, y: (1.0, 1.0)},
    )()
    canvas.selected_item = None
    canvas.selected_type = None
    canvas.selected_constraint_segment_ids = set()
    canvas.show_area_labels = True
    canvas._hit_test_area_label = lambda x, y: area
    canvas._hit_test_free_space_component = lambda x, y: None
    canvas._hit_test_derived_constraint_region = lambda x, y: None
    canvas.canvasx = lambda x: x
    canvas.canvasy = lambda y: y
    canvas.has_coverage_path_for = lambda area_label: False
    canvas.coverage_path_callback = None

    synced_rooms = []
    path_panel = type("PathParamsStub", (), {"set_draw_room": lambda self, room_id: synced_rooms.append(int(room_id))})()
    toplevel = type("TopLevelStub", (), {"sidebar": type("SidebarStub", (), {"path_panel": path_panel})()})()
    canvas.winfo_toplevel = lambda: toplevel

    captured_labels = []

    class _MenuStub:
        def __init__(self, *args, **kwargs):
            pass

        def add_command(self, **kwargs):
            captured_labels.append(kwargs.get("label"))

        def add_separator(self):
            pass

        def tk_popup(self, *args):
            pass

    old_menu = tk.Menu
    tk.Menu = _MenuStub
    try:
        canvas._on_right_click(type("Event", (), {"x": 10, "y": 20, "x_root": 30, "y_root": 40})())
    finally:
        tk.Menu = old_menu

    assert synced_rooms == [8]
    assert canvas.selected_item is area
    assert canvas.selected_type == "area_labels"
    assert captured_labels == ["生成覆盖路径 - 8"]


def test_apply_room_id_to_selected_area_updates_area_paths_and_start_state():
    window = MainWindow.__new__(MainWindow)
    window.annotations = Annotations()
    area = window.annotations.add_area_label(
        [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)],
        area_id=6,
    )
    window.annotations.add_area_label(
        [(3.0, 0.0), (4.0, 0.0), (4.0, 1.0), (3.0, 1.0)],
        area_id=7,
    )
    manager = CoveragePathManager()
    manager.nodes = [
        CoveragePathNode(0, 6, 0, 0.5, 0.5, 0.0, 10.0, 10.0, 0.0, 0.0, 0.0),
        CoveragePathNode(1, 7, 0, 3.5, 0.5, 0.0, 20.0, 10.0, 0.0, 0.0, 0.0),
    ]
    window.coverage_path_manager = manager
    window.canvas = type(
        "CanvasStub",
        (),
        {
            "selected_item": area,
            "selected_type": "area_labels",
            "refresh": lambda self: None,
        },
    )()
    synced_rooms = []
    path_panel = type("PathParamsStub", (), {"set_draw_room": lambda self, room_id: synced_rooms.append(int(room_id))})()
    window.sidebar = type("SidebarStub", (), {"path_panel": path_panel})()
    window.statusbar = type("StatusStub", (), {"messages": [], "config": lambda self, **kwargs: self.messages.append(kwargs.get("text", ""))})()
    window._show_error = lambda **kwargs: (_ for _ in ()).throw(AssertionError(f"unexpected error: {kwargs}"))
    window._show_warning = lambda **kwargs: (_ for _ in ()).throw(AssertionError(f"unexpected warning: {kwargs}"))
    window._coverage_start_points_by_area_id = {6: (1.0, 1.0)}
    window._coverage_start_fingerprints_by_area_id = {6: "old"}

    window.apply_room_id_to_selected_area(9)

    assert area.area_id == 9
    assert area.name == "9"
    assert [node.room_id for node in manager.nodes] == [9, 7]
    assert window._coverage_start_points_by_area_id == {9: (1.0, 1.0)}
    assert set(window._coverage_start_fingerprints_by_area_id) == {9}
    assert window.annotations._next_area_id == 10
    assert synced_rooms == [9]


def test_select_tool_syncs_selected_area_room_to_path_params_panel_every_click():
    canvas = type("CanvasStub", (), {})()
    area_4 = type("AreaStub", (), {"area_id": 4, "name": "4", "id": "area-4"})()
    area_5 = type("AreaStub", (), {"area_id": 5, "name": "5", "id": "area-5"})()
    hits = [area_4, area_4, area_5]
    canvas.canvasx = lambda x: x
    canvas.canvasy = lambda y: y
    canvas.selected_item = None
    canvas.selected_type = None
    canvas.selected_constraint_segment_ids = set()
    canvas.coord_transformer = None
    canvas.hit_test_all = lambda x, y: (hits.pop(0), "area_labels")
    canvas.focus_set = lambda: None
    canvas.refresh = lambda: None

    synced_rooms = []
    path_panel = type("PathParamsStub", (), {"set_draw_room": lambda self, room_id: synced_rooms.append(int(room_id))})()
    controller = type("ControllerStub", (), {"sidebar": type("SidebarStub", (), {"path_panel": path_panel})()})()
    tool = SelectTool(canvas, controller)
    tool._record_original_state = lambda: None

    event = type("Event", (), {"x": 10, "y": 20, "state": 0})()
    tool.on_press(event)
    tool.on_press(event)
    tool.on_press(event)

    assert synced_rooms == [4, 4, 5]


def test_on_right_click_dispatches_free_space_component_menu():
    canvas = MapCanvas.__new__(MapCanvas)
    canvas.annotations = Annotations()
    canvas.coord_transformer = object()
    captured = []
    toplevel = type(
        "TopLevelStub",
        (),
        {
            "_show_free_space_component_menu": lambda self, event, component_id, derived_region=None: captured.append(
                (component_id, derived_region)
            )
        },
    )()
    canvas.winfo_toplevel = lambda: toplevel
    canvas._hit_test_free_space_component = lambda x, y: 11
    canvas._hit_test_derived_constraint_region = lambda x, y: None

    canvas._on_right_click(type("Event", (), {"x": 10, "y": 20})())

    assert captured == [(11, None)]


def test_on_right_click_dispatches_derived_region_menu_when_free_component_absent():
    canvas = MapCanvas.__new__(MapCanvas)
    canvas.annotations = Annotations()
    canvas.coord_transformer = object()
    derived_region = DerivedConstraintRegion(
        id="derived-1",
        name="Component 9 NoCoverage",
        action_type="no_coverage",
        source="free_space_component",
        component_id=9,
        bbox_px=(10, 20, 2, 2),
        packed_mask_b64="",
        metadata={"component_key": "10:20:2:2:abcd"},
    )
    captured = []
    toplevel = type(
        "TopLevelStub",
        (),
        {
            "_show_free_space_component_menu": lambda self, event, component_id, derived_region=None: captured.append(
                (component_id, derived_region)
            )
        },
    )()
    canvas.winfo_toplevel = lambda: toplevel
    canvas._hit_test_free_space_component = lambda x, y: None
    canvas._hit_test_derived_constraint_region = lambda x, y: derived_region

    canvas._on_right_click(type("Event", (), {"x": 10, "y": 20})())

    assert captured == [(9, derived_region)]


def test_on_right_click_prefers_derived_region_before_free_space_component():
    canvas = MapCanvas.__new__(MapCanvas)
    canvas.annotations = Annotations()
    canvas.coord_transformer = object()
    derived_region = DerivedConstraintRegion(
        id="derived-1",
        name="Component 9 Forbidden",
        action_type="forbidden_zone",
        source="free_space_component",
        component_id=9,
        bbox_px=(10, 20, 2, 2),
        packed_mask_b64="",
    )
    captured = []
    toplevel = type(
        "TopLevelStub",
        (),
        {
            "_show_free_space_component_menu": lambda self, event, component_id, derived_region=None: captured.append(
                (component_id, derived_region)
            )
        },
    )()
    canvas.winfo_toplevel = lambda: toplevel
    canvas._hit_test_free_space_component = lambda x, y: 3
    canvas._hit_test_derived_constraint_region = lambda x, y: derived_region

    canvas._on_right_click(type("Event", (), {"x": 10, "y": 20})())

    assert captured == [(9, derived_region)]


def test_free_space_overlay_cache_key_tracks_annotation_changes():
    canvas = MapCanvas.__new__(MapCanvas)
    canvas.annotations = type("AnnotationsStub", (), {"change_stamp": 3})()
    canvas.zoom_level = 1.25
    canvas._free_space_components_cache_key = ("analysis", 1)

    first = canvas._free_space_overlay_cache_key(0, 1, 10, 11)
    canvas.annotations.change_stamp = 4
    second = canvas._free_space_overlay_cache_key(0, 1, 10, 11)

    assert first != second
    assert first[:5] == second[:5]
    assert first[5] == 3
    assert second[5] == 4


def test_handle_motion_prefers_derived_region_semantic_status():
    annotations = Annotations()
    mask = np.array(
        [
            [255, 255],
            [255, 255],
        ],
        dtype=np.uint8,
    )
    annotations.set_derived_constraint_regions(
        [
            DerivedConstraintRegion(
                id="derived-1",
                name="Component 3 NoCoverage",
                action_type="no_coverage",
                source="free_space_component",
                component_id=3,
                bbox_px=(10, 20, 2, 2),
                packed_mask_b64=annotations.encode_binary_mask_packbits(mask),
                repair_radius_m=0.15,
                component_area_m2=1.0,
                metadata={"component_id": 3},
            )
        ]
    )
    canvas = MapCanvas.__new__(MapCanvas)
    canvas.show_free_space_components = True
    canvas.show_annotations = True
    canvas.annotations = annotations
    canvas.zoom_level = 1.0
    canvas.pan_offset_x = 0
    canvas.pan_offset_y = 0
    canvas.canvasx = lambda value: value
    canvas.canvasy = lambda value: value
    canvas.canvas_to_image = MapCanvas.canvas_to_image.__get__(canvas, MapCanvas)
    canvas.free_space_components_result = type(
        "ResultStub",
        (),
        {
            "component_labels": np.pad(np.full((2, 2), 3, dtype=np.int32), ((20, 0), (10, 0))),
            "stat_for_label": lambda self, cid: FreeSpaceComponentStat(component_id=int(cid), pixel_count=4, area_m2=1.0, bbox_px=(10, 20, 2, 2)),
        },
    )()
    captured = []
    canvas.free_space_status_callback = lambda stat, result, semantic_type=None: captured.append((stat.component_id if stat else None, semantic_type))
    canvas._free_space_hover_component_id = None
    canvas._free_space_hover_semantic = None

    canvas.handle_motion(type("Event", (), {"x": 10, "y": 20})())

    assert captured[-1] == (3, "no_coverage")


def test_generate_free_space_component_polygon_constraint_creates_polygon_segment():
    window, warnings = _build_constraint_window()
    grid = np.zeros((12, 12), dtype=np.uint8)
    grid[2:10, 2:10] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.5
    window.canvas.small_component_no_coverage_threshold_m2 = 3.0
    from maptools.utils.free_space_components import analyze_free_space_components

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.0,
        small_component_threshold_m2=3.0,
    )
    component_id = next(iter(window.canvas.free_space_components_result.component_stats))

    window._generate_free_space_component_polygon_constraint(component_id, "no_coverage")

    segments = list(window.annotations.iter_constraint_segments("no_coverage", closed=True))
    regions = list(window.annotations.iter_derived_constraint_regions("no_coverage"))
    assert warnings == []
    assert len(segments) == 1
    assert len(regions) == 0
    assert int(segments[0].metadata["component_id"]) == int(component_id)


def test_generate_polygon_constraint_keeps_multiple_unique_segment_ids_after_relabel():
    window, warnings = _build_constraint_window()
    grid = np.zeros((24, 24), dtype=np.uint8)
    grid[2:8, 2:8] = 254
    grid[10:16, 10:16] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.15
    window.canvas.small_component_no_coverage_threshold_m2 = 1000.0
    from maptools.utils.free_space_components import analyze_free_space_components

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    first_component_id = next(iter(window.canvas.free_space_components_result.component_stats))
    window._generate_free_space_component_polygon_constraint(first_component_id, "no_coverage")

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    second_component_id = next(
        component_id
        for component_id in window.canvas.free_space_components_result.component_stats
        if int(component_id) != int(first_component_id)
    )
    window._generate_free_space_component_polygon_constraint(second_component_id, "no_coverage")

    segments = list(window.annotations.iter_constraint_segments("no_coverage", closed=True))
    assert warnings == []
    assert len(segments) == 2
    assert len({segment.id for segment in segments}) == 2
    assert len({str(segment.metadata.get("component_key", "")) for segment in segments}) == 2


def test_change_constraint_segment_type_rejects_closed_type_with_insufficient_points():
    window, warnings = _build_constraint_window()
    segment = window.annotations.add_constraint_segment(
        [(0.0, 0.0), (1.0, 0.0)],
        closed=False,
        constraint_type="electronic_fence",
        name="Fence",
        item_id="fence-4",
    )
    window.canvas.selected_item = segment
    window.canvas.selected_type = "constraint_segments"

    window._change_constraint_segment_type(segment, "forbidden_zone")

    unchanged = next(window.annotations.iter_constraint_segments("electronic_fence", closed=False))
    assert unchanged.id == "fence-4"
    assert len(warnings) == 1


def test_toolbar_button_text_is_icon_only_in_medium_primary_group():
    item = {"label": "Select", "shortcut": "V", "icon": "◎"}

    text = Toolbar._button_text(item, "medium", "primary")

    assert text == "◎"


def test_toggle_free_space_components_requires_loaded_map():
    window = MainWindow.__new__(MainWindow)
    toggled = []
    warnings = []
    window.map_data = type("MapDataStub", (), {"metadata": None})()
    window.canvas = type("CanvasStub", (), {"set_free_space_components_enabled": lambda self, enabled: toggled.append(enabled)})()
    window.statusbar = type("StatusStub", (), {"config": lambda self, **kwargs: None})()
    window._show_warning = lambda **kwargs: warnings.append(kwargs)
    window._free_space_components_var = type(
        "VarStub",
        (),
        {"value": True, "get": lambda self: self.value, "set": lambda self, value: setattr(self, "value", value)},
    )()

    window._toggle_free_space_components()

    assert toggled == []
    assert window._free_space_components_var.value is False
    assert warnings and warnings[0]["problem"] == "未加载地图"


def test_apply_small_components_as_no_coverage_deduplicates_by_component_key_after_relabel():
    window, warnings = _build_constraint_window()
    grid = np.zeros((24, 24), dtype=np.uint8)
    grid[2:8, 2:8] = 254
    grid[10:16, 10:16] = 254
    window.map_data = _make_component_map_data(grid, resolution=0.5)
    window.canvas.free_space_component_repair_radius_m = 0.15
    window.canvas.small_component_no_coverage_threshold_m2 = 1000.0
    from maptools.utils.free_space_components import analyze_free_space_components

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    first_component_id = next(iter(window.canvas.free_space_components_result.component_stats))
    window._apply_free_space_component_constraint(first_component_id, "no_coverage")

    window.canvas.free_space_components_result = analyze_free_space_components(
        window.map_data,
        window.annotations,
        repair_radius_m=0.15,
        small_component_threshold_m2=1000.0,
    )
    window._apply_small_components_as_no_coverage()

    regions = list(window.annotations.iter_derived_constraint_regions("no_coverage"))
    assert warnings == []
    assert len(regions) == 2
    assert len({str(region.metadata.get("component_key", "")) for region in regions}) == 2


def test_update_free_space_component_status_formats_hover_payload():
    window = MainWindow.__new__(MainWindow)
    messages = []
    window.statusbar = type("StatusStub", (), {"config": lambda self, **kwargs: messages.append(kwargs.get("text", ""))})()
    window.canvas = type(
        "CanvasStub",
        (),
        {
            "free_space_component_repair_radius_m": 0.5,
            "small_component_no_coverage_threshold_m2": 3.0,
        },
    )()
    window._free_space_components_var = type("VarStub", (), {"get": lambda self: True})()

    stat = FreeSpaceComponentStat(component_id=3, pixel_count=128, area_m2=3.2, bbox_px=(0, 0, 10, 10))
    result = type("ResultStub", (), {"total_component_count": 4})()
    window._update_free_space_component_status(stat, result, semantic_type="free")
    window._update_free_space_component_status(stat, result, semantic_type="no_coverage")
    window._update_free_space_component_status(None, result)

    assert "Component 3" in messages[0]
    assert "pixels=128" in messages[0]
    assert "area=3.200 m²" in messages[0]
    assert f"semantic=free | color={FREE_SPACE_COMPONENT_COLOR_HEX}" in messages[0]
    assert "semantic=no_coverage | color=#ff7a45" in messages[1]
    assert "Free space components: 4" in messages[2]
    assert f"semantic=free | color={FREE_SPACE_COMPONENT_COLOR_HEX}" in messages[2]


def test_toggle_free_space_components_status_uses_only_free_color():
    window = MainWindow.__new__(MainWindow)
    messages = []
    window.map_data = type("MapDataStub", (), {"metadata": object()})()
    window.canvas = type(
        "CanvasStub",
        (),
        {
            "set_free_space_components_enabled": lambda self, enabled: None,
            "free_space_component_repair_radius_m": 0.15,
            "small_component_no_coverage_threshold_m2": 1000.0,
        },
    )()
    window.statusbar = type("StatusStub", (), {"config": lambda self, **kwargs: messages.append(kwargs.get("text", ""))})()
    window._show_warning = lambda **kwargs: None
    window._free_space_components_var = type("VarStub", (), {"get": lambda self: True})()

    window._toggle_free_space_components()

    assert messages
    assert f"semantic=free | color={FREE_SPACE_COMPONENT_COLOR_HEX}" in messages[-1]
    assert "forbidden=#ff4d4f" not in messages[-1]
    assert "no_coverage=#ff7a45" not in messages[-1]


def test_free_space_semantic_transition_matrix_exhaustive():
    actions = ("forbidden_zone", "no_coverage", "free")
    for length in range(1, 6):
        for sequence in product(actions, repeat=length):
            window, warnings = _prepare_single_component_constraint_window()
            for action in sequence:
                _apply_component_semantic_action(window, action)
                expected = "free" if action == "free" else action
                _assert_component_semantic_state(window, expected)
            assert warnings == []


def test_free_space_semantic_transition_matrix_exhaustive_with_roundtrip(tmp_path):
    actions = ("forbidden_zone", "no_coverage", "free")
    case_index = 0
    for length in range(1, 4):
        for sequence in product(actions, repeat=length):
            window, warnings = _prepare_single_component_constraint_window()
            for step_index, action in enumerate(sequence):
                _apply_component_semantic_action(window, action)
                _roundtrip_constraint_annotations(window, tmp_path, f"case{case_index}_step{step_index}_{action}")
                expected = "free" if action == "free" else action
                _assert_component_semantic_state(window, expected)
            assert warnings == []
            case_index += 1
