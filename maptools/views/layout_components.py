import tkinter as tk
from tkinter import messagebox
from .theme import COLORS, FONTS, SPACING, WIDTHS, styled_button


# ---------------------------------------------------------------------------
# Tooltip
# ---------------------------------------------------------------------------

class _ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.widget.bind("<Enter>", self._on_enter)
        self.widget.bind("<Leave>", self._on_leave)

    def _on_enter(self, _event):
        if self.tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw, text=self.text, justify=tk.LEFT,
            background=COLORS["tooltip_bg"], foreground=COLORS["tooltip_fg"],
            font=FONTS["tooltip"], relief=tk.SOLID, borderwidth=1, padx=8, pady=4,
        )
        label.pack()

    def _on_leave(self, _event):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


# ---------------------------------------------------------------------------
# CollapsibleFrame
# ---------------------------------------------------------------------------

class CollapsibleFrame(tk.Frame):
    """带标题栏的可折叠面板。"""

    def __init__(self, parent, title="", collapsed=False, **kwargs):
        bg = kwargs.pop("bg", COLORS["bg_primary"])
        super().__init__(parent, bg=bg, **kwargs)
        self._collapsed = collapsed
        self._header = tk.Frame(self, bg=COLORS["sidebar_header_bg"], cursor="hand2")
        self._header.pack(fill=tk.X)
        self._header.bind("<Button-1>", self._toggle)
        self._arrow_label = tk.Label(
            self._header,
            text="▼" if not collapsed else "▶",
            bg=COLORS["sidebar_header_bg"], fg=COLORS["fg_secondary"],
            font=FONTS["caption"], padx=4,
        )
        self._arrow_label.pack(side=tk.LEFT)
        self._arrow_label.bind("<Button-1>", self._toggle)
        self._title_label = tk.Label(
            self._header, text=title,
            bg=COLORS["sidebar_header_bg"], fg=COLORS["fg_primary"],
            font=FONTS["body_bold"], anchor="w",
        )
        self._title_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self._title_label.bind("<Button-1>", self._toggle)
        self.content = tk.Frame(self, bg=bg)
        if not collapsed:
            self.content.pack(fill=tk.BOTH, expand=True)

    def _toggle(self, _event=None):
        self._collapsed = not self._collapsed
        if self._collapsed:
            self.content.pack_forget()
            self._arrow_label.config(text="▶")
        else:
            self.content.pack(fill=tk.BOTH, expand=True)
            self._arrow_label.config(text="▼")

    @property
    def is_collapsed(self):
        return self._collapsed

    def expand(self):
        if self._collapsed:
            self._toggle()

    def collapse(self):
        if not self._collapsed:
            self._toggle()


# ---------------------------------------------------------------------------
# PathDrawParamsPanel
# ---------------------------------------------------------------------------

class PathDrawParamsPanel(tk.Frame):
    """路径绘制参数和 Room ID 编辑器。"""

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg_primary"])

        self.interval_entry = self._add_row("Interval:")
        self.interval_entry.insert(0, "0.5")

        self.room_entry = self._add_row("Room ID:")
        self.room_entry.insert(0, "0")
        self.room_context = tk.Label(
            self, text="No selected area", anchor="w",
            bg=COLORS["bg_primary"], fg=COLORS["fg_secondary"], font=FONTS["caption"],
        )
        self.room_context.pack(fill=tk.X, padx=SPACING["md"], pady=(0, SPACING["sm"]))

        btn = tk.Button(
            self, text="Apply Room ID", command=self._on_apply_room_id,
            bg=COLORS["bg_surface"], fg=COLORS["fg_primary"],
            activebackground=COLORS["bg_hover"],
            relief=tk.FLAT, bd=0, font=FONTS["button"], cursor="hand2",
        )
        btn.pack(fill=tk.X, padx=SPACING["md"], pady=(0, SPACING["sm"]))

    def _add_row(self, label_text: str) -> tk.Entry:
        row = tk.Frame(self, bg=COLORS["bg_primary"])
        row.pack(fill=tk.X, padx=SPACING["md"], pady=SPACING["xs"])
        tk.Label(
            row, text=label_text, width=8, anchor="e",
            bg=COLORS["bg_primary"], fg=COLORS["fg_secondary"], font=FONTS["body"],
        ).pack(side=tk.LEFT)
        entry = tk.Entry(
            row, width=10,
            bg=COLORS["bg_surface"], fg=COLORS["fg_bright"],
            insertbackground=COLORS["fg_primary"],
            relief=tk.FLAT, bd=1, font=FONTS["body"],
        )
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return entry

    def get_draw_interval(self) -> float:
        try:
            value = float(self.interval_entry.get())
        except ValueError:
            return 0.5
        return value if value > 0 else 0.5

    def get_draw_room(self) -> int:
        try:
            return int(self.room_entry.get())
        except ValueError:
            return 0

    def get_draw_segment(self) -> int:
        return 0

    def set_draw_room(self, room_id: int) -> None:
        self.room_entry.delete(0, tk.END)
        self.room_entry.insert(0, str(int(room_id)))
        self.room_context.config(text=f"Selected area Room ID: {int(room_id)}")

    def _on_apply_room_id(self) -> None:
        try:
            room_id = int(self.room_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Room ID must be an integer")
            return
        toplevel = self.winfo_toplevel()
        if hasattr(toplevel, "apply_room_id_to_selected_area"):
            toplevel.apply_room_id_to_selected_area(room_id)


# ---------------------------------------------------------------------------
# RoomOrderPanel
# ---------------------------------------------------------------------------

class RoomOrderPanel(tk.Frame):
    """Sidebar 中的 Room 路径连接顺序面板（嵌入式，非弹窗）。"""

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["sidebar_bg"])
        self._room_ids = []
        self._apply_cb = None  # 回调：def callback(new_order: list[int])
        self._tsp_cb = None   # 回调：def callback() → list[int] | None
        self._generate_all_cb = None  # 回调：def callback()

        self._generate_all_btn = tk.Button(
            self, text="⚡ 生成全部覆盖路径",
            bg=COLORS.get("accent", "#e67e22"),
            fg=COLORS.get("fg_on_accent", "#ffffff"),
            activebackground=COLORS.get("bg_hover", "#e0e0e0"),
            relief=tk.FLAT, font=FONTS["button"], cursor="hand2",
            command=self._on_generate_all,
        )
        self._generate_all_btn.pack(fill=tk.X, padx=SPACING["md"], pady=(SPACING["sm"], 2))

        tk.Label(
            self, text="拖拽调整 Room 连接顺序",
            bg=COLORS["sidebar_bg"], fg=COLORS["fg_secondary"],
            font=FONTS["caption"], anchor="w",
        ).pack(fill=tk.X, padx=SPACING["md"], pady=(0, 2))

        list_frame = tk.Frame(self, bg=COLORS["sidebar_bg"])
        list_frame.pack(fill=tk.X, padx=SPACING["md"])

        self.listbox = tk.Listbox(
            list_frame, height=6,
            bg=COLORS["bg_surface"],
            fg=COLORS["fg_primary"],
            selectbackground=COLORS.get("bg_active", "#4a90d9"),
            selectforeground=COLORS.get("fg_on_accent", "#ffffff"),
            font=FONTS["body"],
            activestyle="none",
            bd=1, relief=tk.SOLID,
            exportselection=False,
        )
        self.listbox.pack(fill=tk.X)

        btn_row = tk.Frame(self, bg=COLORS["sidebar_bg"])
        btn_row.pack(fill=tk.X, padx=SPACING["md"], pady=(4, 0))

        tk.Button(
            btn_row, text="▲", width=3,
            bg=COLORS["bg_surface"],
            fg=COLORS["fg_primary"],
            activebackground=COLORS.get("bg_hover", "#e0e0e0"),
            relief=tk.FLAT, font=FONTS["button"], cursor="hand2",
            command=self._move_up,
        ).pack(side=tk.LEFT, padx=(0, 2))

        tk.Button(
            btn_row, text="▼", width=3,
            bg=COLORS["bg_surface"],
            fg=COLORS["fg_primary"],
            activebackground=COLORS.get("bg_hover", "#e0e0e0"),
            relief=tk.FLAT, font=FONTS["button"], cursor="hand2",
            command=self._move_down,
        ).pack(side=tk.LEFT)

        tk.Button(
            btn_row, text="TSP 优化",
            bg=COLORS.get("accent", "#e67e22"),
            fg=COLORS.get("fg_on_accent", "#ffffff"),
            activebackground=COLORS.get("bg_hover", "#e0e0e0"),
            relief=tk.FLAT, font=FONTS["button"], cursor="hand2",
            command=self._on_tsp,
        ).pack(side=tk.RIGHT, padx=(4, 0))

        self._apply_btn = tk.Button(
            btn_row, text="应用顺序",
            bg=COLORS.get("bg_active", "#4a90d9"),
            fg=COLORS.get("fg_on_accent", "#ffffff"),
            activebackground=COLORS.get("bg_hover", "#e0e0e0"),
            relief=tk.FLAT, font=FONTS["button"], cursor="hand2",
            command=self._on_apply,
        )
        self._apply_btn.pack(side=tk.RIGHT)

    def set_apply_callback(self, cb):
        self._apply_cb = cb

    def set_tsp_callback(self, cb):
        """设置 TSP 优化回调，应返回 list[int]（新 room_id 顺序）或 None。"""
        self._tsp_cb = cb

    def set_generate_all_callback(self, cb):
        """设置生成全部路径回调。"""
        self._generate_all_cb = cb

    def _on_generate_all(self):
        if self._generate_all_cb:
            self._generate_all_cb()

    def refresh(self, room_ids):
        """用新的 room_ids 列表刷新面板。room_ids = [1, 3, 2, ...]"""
        self._room_ids = list(room_ids)
        self.listbox.delete(0, tk.END)
        for rid in self._room_ids:
            self.listbox.insert(tk.END, f"Room {rid}")

    def clear(self):
        self._room_ids = []
        self.listbox.delete(0, tk.END)

    def _move_up(self):
        sel = self.listbox.curselection()
        if not sel or sel[0] == 0:
            return
        idx = sel[0]
        self._room_ids[idx - 1], self._room_ids[idx] = self._room_ids[idx], self._room_ids[idx - 1]
        text = self.listbox.get(idx)
        self.listbox.delete(idx)
        self.listbox.insert(idx - 1, text)
        self.listbox.selection_set(idx - 1)
        self.listbox.see(idx - 1)

    def _move_down(self):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self._room_ids) - 1:
            return
        idx = sel[0]
        self._room_ids[idx], self._room_ids[idx + 1] = self._room_ids[idx + 1], self._room_ids[idx]
        text = self.listbox.get(idx)
        self.listbox.delete(idx)
        self.listbox.insert(idx + 1, text)
        self.listbox.selection_set(idx + 1)
        self.listbox.see(idx + 1)

    def _on_tsp(self):
        if self._tsp_cb:
            new_order = self._tsp_cb()
            if new_order:
                self.refresh(new_order)
                if self._apply_cb:
                    self._apply_cb(list(new_order))

    def _on_apply(self):
        if self._apply_cb and self._room_ids:
            self._apply_cb(list(self._room_ids))


# ---------------------------------------------------------------------------
# Toolbar
# ---------------------------------------------------------------------------

class Toolbar(tk.Frame):
    """工具栏：扁平按钮分组 + 画笔大小滑块，不使用 tk.Menu。"""

    def __init__(self, parent, tool_manager=None):
        super().__init__(parent, bg=COLORS["toolbar_bg"], bd=0)
        self.pack(side=tk.TOP, fill=tk.X)
        self.tool_manager = tool_manager
        self.current_breakpoint = None
        self._tool_buttons = {}
        self._action_handlers: dict[str, callable] = {}

        groups = [
            ("编辑", [
                ("Select",   "select"),
                ("Pan",      "pan"),
                ("Crop",     "crop"),
                ("Brush",    "brush"),
                ("Line",     "straight_line"),
                ("Eraser",   "eraser"),
            ]),
            ("标注", [
                ("Origin",   "origin"),
                ("Forbidden","polygon"),
                ("PassOnly", "pass_only"),
                ("V.Wall",   "line"),
                ("Station",  "station"),
                ("AreaLabel","area_label"),
            ]),
            ("路径", [
                ("PSel",  "path_select"),
                ("PPoly", "path_polygon"),
                ("PAdd",  "path_add"),
                ("PDraw", "path_draw"),
                ("PLine", "path_line"),
            ]),
        ]

        btn_frame = tk.Frame(self, bg=COLORS["toolbar_bg"])
        btn_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        for gi, (glabel, tools) in enumerate(groups):
            if gi > 0:
                tk.Frame(btn_frame, width=1, bg=COLORS["border_light"],
                         bd=0).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=3)
            tk.Label(btn_frame, text=glabel, bg=COLORS["toolbar_bg"],
                     fg=COLORS["fg_secondary"], font=FONTS["caption"],
                     padx=2).pack(side=tk.LEFT)
            for label, tool_name in tools:
                btn = styled_button(
                    btn_frame, text=label,
                    command=lambda n=tool_name: self.set_tool(n),
                    width=len(label) + 1,
                )
                btn.pack(side=tk.LEFT, padx=2, pady=2)
                self._tool_buttons[tool_name] = btn

        brush_frame = tk.Frame(self, bg=COLORS["toolbar_bg"])
        brush_frame.pack(side=tk.RIGHT, padx=SPACING["md"])
        tk.Label(
            brush_frame, text="Size:", bg=COLORS["toolbar_bg"],
            fg=COLORS["fg_secondary"], font=FONTS["caption"],
        ).pack(side=tk.LEFT, padx=SPACING["xs"])
        self.scale_size = tk.Scale(
            brush_frame, from_=1, to=50, orient=tk.HORIZONTAL, length=80,
            bg=COLORS["toolbar_bg"], fg=COLORS["fg_primary"],
            troughcolor=COLORS["bg_surface"],
            highlightthickness=0, bd=0,
            command=self.update_brush_size,
        )
        self.scale_size.set(5)
        self.scale_size.pack(side=tk.LEFT, padx=SPACING["xs"])

    def set_tool(self, name):
        if name in self._action_handlers:
            self._action_handlers[name]()
            return
        if self.tool_manager:
            self.tool_manager.set_tool(name)
        self._highlight_tool(name)

    def add_action_button(self, group_label, label, action_name, command):
        self._action_handlers[action_name] = command
        # 找到 btn_frame 末尾处插入
        btn_frame = self.winfo_children()[0] if self.winfo_children() else None
        if btn_frame is None:
            return
        tk.Frame(btn_frame, width=1, bg=COLORS["border_light"],
                 bd=0).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=3)
        tk.Label(btn_frame, text=group_label, bg=COLORS["toolbar_bg"],
                 fg=COLORS["fg_secondary"], font=FONTS["caption"],
                 padx=2).pack(side=tk.LEFT)
        btn = styled_button(
            btn_frame, text=label,
            command=lambda: self.set_tool(action_name),
            width=len(label) + 1,
        )
        btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._tool_buttons[action_name] = btn

    def _highlight_tool(self, tool_name):
        for name, btn in self._tool_buttons.items():
            if name == tool_name:
                btn.configure(bg=COLORS["bg_active"], fg=COLORS["fg_on_accent"])
            else:
                btn.configure(bg=COLORS["bg_surface"], fg=COLORS["fg_primary"])

    def apply_breakpoint(self, breakpoint_name: str):
        if breakpoint_name == self.current_breakpoint:
            return
        self.current_breakpoint = breakpoint_name

    def update_brush_size(self, val):
        if self.tool_manager:
            size = int(val)
            brush = self.tool_manager.get_tool("brush")
            if brush: brush.radius = size
            eraser = self.tool_manager.get_tool("eraser")
            if eraser: eraser.radius = size
            straight_line = self.tool_manager.get_tool("straight_line")
            if straight_line: straight_line.radius = size


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

class Sidebar(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, width=WIDTHS["sidebar"], bg=COLORS["sidebar_bg"])
        self.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas = None

        self._layers_panel = CollapsibleFrame(self, title="Layers", collapsed=False)
        self._layers_panel.pack(fill=tk.X)

        self.layer_configs = [
            ("Base Map", "show_base_map", True),
            ("Grid (1m)", "show_grid", False),
            ("Origin", "show_origin", True),
            ("Scale", "show_scale", True),
            ("Annotations", "show_annotations", True),
            ("Pass Only Zones", "show_pass_only_zones", True),
            ("Area Labels", "show_area_labels", True),
        ]
        self.vars = {}
        for name, attr, default in self.layer_configs:
            var = tk.BooleanVar(value=default)
            self.vars[attr] = var
            cb = tk.Checkbutton(
                self._layers_panel.content, text=name, variable=var,
                command=lambda a=attr: self.toggle_layer(a),
                bg=COLORS["sidebar_bg"], fg=COLORS["fg_primary"],
                activebackground=COLORS["sidebar_bg"],
                activeforeground=COLORS["fg_bright"],
                selectcolor=COLORS["bg_surface"],
                font=FONTS["body"],
            )
            cb.pack(anchor="w", padx=SPACING["md"], pady=1)

        self._room_order_panel = CollapsibleFrame(self, title="Room 顺序", collapsed=False)
        self._room_order_panel.pack(fill=tk.X, pady=(SPACING["sm"], 0))
        self.room_order_panel = RoomOrderPanel(self._room_order_panel.content)
        self.room_order_panel.pack(fill=tk.X, padx=SPACING["sm"], pady=SPACING["sm"])

        self._boundary_refine_panel = CollapsibleFrame(self, title="边界修正", collapsed=False)
        self._boundary_refine_panel.pack(fill=tk.X, pady=(SPACING["sm"], 0))
        self.boundary_refine_panel = BoundaryRefinePanel(
            self._boundary_refine_panel.content, parent_window=parent)
        self.boundary_refine_panel.pack(fill=tk.X, padx=SPACING["sm"], pady=SPACING["sm"])

        self._path_panel_container = CollapsibleFrame(self, title="Path Params", collapsed=True)
        self._path_panel_container.pack(fill=tk.X, pady=(SPACING["sm"], 0))

        self.path_panel = PathDrawParamsPanel(self._path_panel_container.content)
        self.path_panel.pack(fill=tk.X, padx=SPACING["sm"], pady=SPACING["sm"])

        tk.Frame(self, height=1, bg=COLORS["border"]).pack(
            fill=tk.X, padx=SPACING["md"], pady=SPACING["md"],
        )

        self._info_panel = CollapsibleFrame(self, title="Info", collapsed=False)
        self._info_panel.pack(fill=tk.X)
        self._info_label = tk.Label(
            self._info_panel.content, text="No map loaded",
            bg=COLORS["sidebar_bg"], fg=COLORS["fg_secondary"],
            font=FONTS["caption"], anchor="w", justify=tk.LEFT,
            padx=SPACING["md"], pady=SPACING["sm"],
        )
        self._info_label.pack(fill=tk.X)

    def toggle_layer(self, attr):
        if self.canvas:
            val = self.vars[attr].get()
            if hasattr(self.canvas, attr):
                setattr(self.canvas, attr, val)
                self.canvas.refresh()

    def update_info(self, text: str):
        self._info_label.config(text=text)


class BoundaryRefinePanel(tk.Frame):
    def __init__(self, parent, parent_window):
        super().__init__(parent, bg=COLORS["sidebar_bg"])
        self._parent_window = parent_window

        row = tk.Frame(self, bg=COLORS["sidebar_bg"])
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text="房间 A ID:", bg=COLORS["sidebar_bg"],
                 fg=COLORS["fg_primary"], font=FONTS["body"]).pack(side=tk.LEFT)
        self._entry_a = tk.Entry(row, width=6, font=FONTS["body"])
        self._entry_a.pack(side=tk.LEFT, padx=4)

        row2 = tk.Frame(self, bg=COLORS["sidebar_bg"])
        row2.pack(fill=tk.X, pady=2)
        tk.Label(row2, text="房间 B ID:", bg=COLORS["sidebar_bg"],
                 fg=COLORS["fg_primary"], font=FONTS["body"]).pack(side=tk.LEFT)
        self._entry_b = tk.Entry(row2, width=6, font=FONTS["body"])
        self._entry_b.pack(side=tk.LEFT, padx=4)

        btn = styled_button(self, text="执行边界修正", command=self._execute)
        btn.pack(pady=4)

        self._result_label = tk.Label(
            self, text="", bg=COLORS["sidebar_bg"],
            fg=COLORS["fg_secondary"], font=FONTS["caption"],
            wraplength=180, justify=tk.LEFT)
        self._result_label.pack(fill=tk.X, padx=4)

    def _execute(self):
        try:
            a = int(self._entry_a.get().strip())
            b = int(self._entry_b.get().strip())
        except ValueError:
            self._result_label.config(text="请输入有效的房间 ID")
            return

        win = self._parent_window
        if win.map_data is None or win.map_data.metadata is None:
            self._result_label.config(text="未加载地图")
            return
        if not win.annotations.area_labels:
            self._result_label.config(text="无区域标签")
            return

        ids = [lab.area_id for lab in win.annotations.area_labels]
        if a not in ids or b not in ids:
            self._result_label.config(text=f"未找到房间 ID {a} 或 {b}")
            return

        try:
            from ..utils.free_space_components import (
                _world_to_image_pixel,
                build_obstacle_semantic_mask,
            )
            import numpy as np, cv2

            map_data = win.map_data
            annotations = win.annotations
            resolution = float(map_data.metadata.resolution)
            origin_x = float(map_data.metadata.origin[0])
            origin_y = float(map_data.metadata.origin[1])
            height = int(map_data.height)
            h = int(map_data.height)
            w = int(map_data.width)

            # 检查是否有扩张前原始 polygon 快照
            orig_snapshots = getattr(win, '_orig_area_polygons', None)

            obstacle_mask = build_obstacle_semantic_mask(map_data, annotations)
            free_mask = (obstacle_mask == 0).astype(np.uint8)

            assignment = np.full((h, w), -1, dtype=np.int32)
            orig_masks = []
            for i, lab in enumerate(annotations.area_labels):
                pts = np.array([
                    _world_to_image_pixel(px, py, resolution, origin_x, origin_y, height)
                    for px, py in lab.polygon
                ], dtype=np.int32).reshape((-1, 1, 2))
                m = np.zeros((h, w), dtype=np.uint8)
                cv2.fillPoly(m, [pts], 1)
                assignment[m > 0] = i

                # 原始 polygon：优先取快照，没有则取当前 polygon
                if orig_snapshots and i < len(orig_snapshots) and len(orig_snapshots[i]) >= 3:
                    orig_pts = np.array([
                        _world_to_image_pixel(px, py, resolution, origin_x, origin_y, height)
                        for px, py in orig_snapshots[i]
                    ], dtype=np.int32).reshape((-1, 1, 2))
                else:
                    orig_pts = pts
                om = np.zeros((h, w), dtype=np.uint8)
                cv2.fillPoly(om, [orig_pts], 1)
                orig_masks.append(om)

            ia = ids.index(a)
            ib = ids.index(b)

            mask_a = (assignment == ia).astype(np.uint8)
            mask_b = (assignment == ib).astype(np.uint8)
            orig_a = orig_masks[ia]
            orig_b = orig_masks[ib]

            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            contact_a = cv2.dilate(mask_a, kernel, iterations=1) & mask_b
            contact_b = cv2.dilate(mask_b, kernel, iterations=1) & mask_a
            contact = contact_a | contact_b
            if np.count_nonzero(contact) == 0:
                self._result_label.config(text="两个房间不相邻")
                return

            dist_a = cv2.distanceTransform(orig_a, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
            dist_b = cv2.distanceTransform(orig_b, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
            pts = np.where(contact > 0)
            d_a = float(dist_a[pts].mean()) * resolution
            d_b = float(dist_b[pts].mean()) * resolution

            thr = 0.05
            if d_a < thr and d_b > thr:
                winner, loser = ib, ia
                reason = f"dA={d_a:.2f}m < 0.05, dB={d_b:.2f}m > 0.05 → B胜"
            elif d_b < thr and d_a > thr:
                winner, loser = ia, ib
                reason = f"dB={d_b:.2f}m < 0.05, dA={d_a:.2f}m > 0.05 → A胜"
            elif d_a < thr and d_b < thr:
                if d_a >= d_b:
                    winner, loser = ia, ib
                    reason = f"均<0.05m, dA={d_a:.2f}m >= dB={d_b:.2f}m → A胜"
                else:
                    winner, loser = ib, ia
                    reason = f"均<0.05m, dB={d_b:.2f}m > dA={d_a:.2f}m → B胜"
            else:
                self._result_label.config(
                    text=f"dA={d_a:.2f}m, dB={d_b:.2f}m, 均 > 0.05m, 无需调整")
                return

            loser_mask = (assignment == loser).astype(np.uint8)
            loser_orig = orig_masks[loser]
            # 败者退回原始轮廓
            shrink = loser_mask & ~loser_orig
            assignment[shrink > 0] = -1

            # 败者退出区全部给胜者
            assignment[shrink > 0] = winner

            # 更新胜者 polygon
            region = (assignment == winner).astype(np.uint8) * 255
            cs, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if cs:
                c = max(cs, key=cv2.contourArea)
                c = cv2.approxPolyDP(c, epsilon=1.5, closed=True)
                if c.shape[0] >= 3:
                    poly = [(origin_x + float(pt[0, 0]) * resolution,
                             origin_y + float(height - pt[0, 1]) * resolution)
                            for pt in c]
                    annotations.area_labels[winner].polygon = poly

            # 删除败者的 area_label（按 area_id 查找，避免索引错位）
            loser_area_id = annotations.area_labels[loser].area_id
            annotations.area_labels = [
                lab for lab in annotations.area_labels if lab.area_id != loser_area_id]

            win.canvas.refresh()
            self._result_label.config(
                text=f"{reason}\n败者 {['A','B'][ia==loser]} 已删除，胜者 {['A','B'][ia==winner]} 吞并其区域")

        except Exception as e:
            self._result_label.config(text=f"错误: {e}")

    def _restore_original(self):
        win = self._parent_window
        orig_snapshots = getattr(win, '_orig_area_polygons', None)
        if not orig_snapshots:
            self._result_label.config(text="未找到原始多边形快照，请先运行区域标签扩展法")
            return
        try:
            a = int(self._entry_a.get().strip())
            b = int(self._entry_b.get().strip())
        except ValueError:
            self._result_label.config(text="请输入有效的房间 ID")
            return

        ids = [lab.area_id for lab in win.annotations.area_labels]
        ia = ids.index(a) if a in ids else -1
        ib = ids.index(b) if b in ids else -1
        if ia == -1 or ib == -1:
            self._result_label.config(text=f"未找到房间 ID {a} 或 {b}")
            return
        try:
            if ia < len(orig_snapshots) and len(orig_snapshots[ia]) >= 3:
                win.annotations.area_labels[ia].polygon = orig_snapshots[ia]
            if ib < len(orig_snapshots) and len(orig_snapshots[ib]) >= 3:
                win.annotations.area_labels[ib].polygon = orig_snapshots[ib]
            win.canvas.refresh()
            self._result_label.config(text=f"房间 {a} 和 {b} 已恢复原始轮廓")
        except Exception as e:
            self._result_label.config(text=f"错误: {e}")
