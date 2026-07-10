import tkinter as tk
from tkinter import messagebox


class PathDrawParamsPanel(tk.LabelFrame):
    """Compact path drawing parameters and selected area Room ID editor."""

    def __init__(self, parent):
        super().__init__(parent, text="Path Params")

        self.interval_entry = self._add_row("Interval:")
        self.interval_entry.insert(0, "0.5")

        self.room_entry = self._add_row("Room ID:")
        self.room_entry.insert(0, "0")
        self.room_context = tk.Label(self, text="No selected area", anchor="w", fg="#555")
        self.room_context.pack(fill=tk.X, padx=4, pady=(0, 2))

        tk.Button(
            self,
            text="Apply Room ID",
            command=self._on_apply_room_id,
        ).pack(fill=tk.X, padx=4, pady=(0, 4))

    def _add_row(self, label_text: str) -> tk.Entry:
        row = tk.Frame(self)
        row.pack(fill=tk.X, padx=4, pady=2)
        tk.Label(row, text=label_text, width=8, anchor="e").pack(side=tk.LEFT)
        entry = tk.Entry(row, width=10)
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
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 2
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=self.text,
            justify=tk.LEFT,
            background="#ffffe0",
            relief=tk.SOLID,
            borderwidth=1,
            padx=6,
            pady=3,
        )
        label.pack()

    def _on_leave(self, _event):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


class Toolbar(tk.Frame):
    # 可视断言清单（Task 2 Step 1）:
    # - wide: primary/vector/path 全可见
    # - medium: primary/vector 可见，path 折叠到 More 菜单
    # - narrow: primary 可见，vector/path 折叠到 More 菜单
    VISIBILITY_ASSERTIONS = {
        "wide": ("primary", "vector", "path"),
        "medium": ("primary", "vector"),
        "narrow": ("primary",),
    }

    ICON_ONLY_GROUPS = {
        "medium": {"primary", "vector"},
    }

    def __init__(self, parent, tool_manager=None):
        super().__init__(parent, bd=1, relief=tk.RAISED)
        self.pack(side=tk.TOP, fill=tk.X)
        self.tool_manager = tool_manager
        self.current_breakpoint = None
        self.group_defs = {
            "primary": [
                {"label": "Select", "tool": "select", "shortcut": "V", "icon": "◎"},
                {"label": "Pan", "tool": "pan", "shortcut": "Space", "icon": "✥"},
                {"label": "Crop", "tool": "crop", "shortcut": "C", "icon": "▣"},
                {"label": "Brush", "tool": "brush", "shortcut": "B", "icon": "✎"},
                {"label": "Line", "tool": "straight_line", "shortcut": "L", "icon": "／"},
                {"label": "Eraser", "tool": "eraser", "shortcut": "E", "icon": "⌫"},
            ],
            "vector": [
                {"label": "Set Origin", "tool": "origin", "shortcut": "O", "icon": "⌖"},
                {"label": "Forbidden Zone", "tool": "polygon", "shortcut": "F", "icon": "⛔"},
                {"label": "Pass Only Zone", "tool": "pass_only", "shortcut": "P", "icon": "✓"},
                {"label": "Virtual Wall", "tool": "line", "shortcut": "W", "icon": "║"},
                {"label": "Station", "tool": "station", "shortcut": "S", "icon": "◉"},
                {"label": "Area Label", "tool": "area_label", "shortcut": "A", "icon": "▧"},
            ],
            "path": [
                {"label": "Path Select", "tool": "path_select", "shortcut": "1", "icon": "①"},
                {"label": "Path Poly", "tool": "path_polygon", "shortcut": "2", "icon": "②"},
                {"label": "Path Add", "tool": "path_add", "shortcut": "3", "icon": "③"},
                {"label": "Path Draw", "tool": "path_draw", "shortcut": "4", "icon": "④"},
                {"label": "Path Line", "tool": "path_line", "shortcut": "5", "icon": "⑤"},
            ],
        }

        self.left_frame = tk.Frame(self)
        self.left_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.group_frames = {}
        self.group_buttons = {}
        for group_name, items in self.group_defs.items():
            group_frame = tk.Frame(self.left_frame)
            button_items = []
            for item in items:
                label = self._button_text(item, "wide", group_name)
                button = tk.Button(
                    group_frame,
                    text=label,
                    command=lambda n=item["tool"]: self.set_tool(n),
                )
                button.pack(side=tk.LEFT, padx=2, pady=2)
                _ToolTip(button, self._tooltip_text(item))
                button_items.append((button, item))
            self.group_buttons[group_name] = button_items
            self.group_frames[group_name] = group_frame

        self.overflow_button = tk.Menubutton(self.left_frame, text="More Tools", relief=tk.RAISED)
        self.overflow_menu = tk.Menu(self.overflow_button, tearoff=0)
        self.overflow_button.configure(menu=self.overflow_menu)

        self.brush_frame = tk.Frame(self)
        self.brush_frame.pack(side=tk.RIGHT, padx=4)
        tk.Label(self.brush_frame, text="Size:").pack(side=tk.LEFT, padx=2)
        self.scale_size = tk.Scale(
            self.brush_frame,
            from_=1,
            to=50,
            orient=tk.HORIZONTAL,
            length=100,
            command=self.update_brush_size,
        )
        self.scale_size.set(5)
        self.scale_size.pack(side=tk.LEFT, padx=2)

        self.apply_breakpoint("wide")

    @staticmethod
    def _tooltip_text(item) -> str:
        return f"{item['label']}\nShortcut: {item['shortcut']}"

    @classmethod
    def _button_text(cls, item, breakpoint_name: str, group_name: str) -> str:
        icon_only_groups = cls.ICON_ONLY_GROUPS.get(breakpoint_name, set())
        if group_name in icon_only_groups:
            return item["icon"]
        if breakpoint_name == "wide":
            return f"{item['icon']} {item['label']}"
        return item["label"]

    def set_tool(self, name):
        if self.tool_manager:
            self.tool_manager.set_tool(name)

    def apply_breakpoint(self, breakpoint_name: str):
        if breakpoint_name == self.current_breakpoint:
            return

        visible_groups = self.VISIBILITY_ASSERTIONS.get(
            breakpoint_name, self.VISIBILITY_ASSERTIONS["narrow"]
        )
        for group_name, button_items in self.group_buttons.items():
            for button, item in button_items:
                button.configure(text=self._button_text(item, breakpoint_name, group_name))
        for group_name, frame in self.group_frames.items():
            frame.pack_forget()
            if group_name in visible_groups:
                frame.pack(side=tk.LEFT, padx=2)

        hidden_groups = [name for name in self.group_defs if name not in visible_groups]
        self._rebuild_overflow_menu(hidden_groups)
        self.overflow_button.pack_forget()
        if hidden_groups:
            self.overflow_button.pack(side=tk.LEFT, padx=4)

        self.current_breakpoint = breakpoint_name

    def _rebuild_overflow_menu(self, hidden_groups):
        self.overflow_menu.delete(0, tk.END)
        for idx, group_name in enumerate(hidden_groups):
            if idx > 0:
                self.overflow_menu.add_separator()
            self.overflow_menu.add_command(
                label=f"{group_name.title()} Tools",
                state=tk.DISABLED,
            )
            for item in self.group_defs[group_name]:
                self.overflow_menu.add_command(
                    label=f"{item['label']} ({item['shortcut']})",
                    command=lambda n=item["tool"]: self.set_tool(n),
                )

    def update_brush_size(self, val):
        if self.tool_manager:
            size = int(val)
            # Update all brush-like tools
            brush = self.tool_manager.get_tool("brush")
            if brush: brush.radius = size

            eraser = self.tool_manager.get_tool("eraser")
            if eraser: eraser.radius = size

            straight_line = self.tool_manager.get_tool("straight_line")
            if straight_line: straight_line.radius = size


class Sidebar(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, width=180, bg="#f0f0f0")
        self.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas = None # Will be set by MainWindow

        tk.Label(self, text="Layers", font=("Arial", 10, "bold")).pack(pady=5)

        self.layer_frame = tk.Frame(self)
        self.layer_frame.pack(fill=tk.X, padx=5)

        # Layers configuration: (Name, attribute_in_canvas, default_value)
        self.layer_configs = [
            ("Base Map", "show_base_map", True), # Need to implement this in Canvas if not exists
            ("Grid (1m)", "show_grid", False),
            ("Origin", "show_origin", True),
            ("Scale", "show_scale", True),
            ("Annotations", "show_annotations", True), # Need to implement this in Canvas
            ("Pass Only Zones", "show_pass_only_zones", True),
            ("Area Labels", "show_area_labels", True)
        ]

        self.vars = {}

        for name, attr, default in self.layer_configs:
            var = tk.BooleanVar(value=default)
            self.vars[attr] = var
            # Use lambda to capture attr
            cb = tk.Checkbutton(self.layer_frame, text=name, variable=var,
                                command=lambda a=attr: self.toggle_layer(a))
            cb.pack(anchor="w")

        tk.Frame(self, height=2, bd=1, relief=tk.SUNKEN).pack(fill=tk.X, padx=5, pady=8)

        self.path_panel = PathDrawParamsPanel(self)
        self.path_panel.pack(fill=tk.X, padx=5, pady=(0, 6))

    def toggle_layer(self, attr):
        if self.canvas:
            val = self.vars[attr].get()
            if hasattr(self.canvas, attr):
                setattr(self.canvas, attr, val)
                self.canvas.refresh()
            else:
                print(f"Canvas has no attribute {attr}")
