from .base_tool import BaseTool


class CropTool(BaseTool):
    name = "crop"
    cursor = "crosshair"

    HANDLE_ORDER = ("nw", "n", "ne", "e", "se", "s", "sw", "w")
    HANDLE_CURSORS = {
        "move": "fleur",
        "n": "sb_v_double_arrow",
        "s": "sb_v_double_arrow",
        "e": "sb_h_double_arrow",
        "w": "sb_h_double_arrow",
        "nw": "top_left_corner",
        "se": "top_left_corner",
        "ne": "top_right_corner",
        "sw": "top_right_corner",
    }

    def __init__(self, canvas, controller):
        super().__init__(canvas, controller)
        self.rect_px = None
        self.mode = "idle"
        self.active_handle = None
        self.start_px = None
        self.anchor_rect = None

    def activate(self):
        super().activate()
        self.canvas.focus_set()
        self._render_preview()

    def deactivate(self):
        self.canvas.delete("tool_preview")
        self.rect_px = None
        self.mode = "idle"
        self.active_handle = None
        self.start_px = None
        self.anchor_rect = None

    def on_press(self, event):
        if not self.canvas.map_data:
            return

        px, py = self._event_to_image_px(event)
        hit = self._hit_test(event)

        if self.rect_px is None:
            self.mode = "creating"
            self.start_px = (px, py)
            self.rect_px = self._normalize_rect(px, py, px + 1, py + 1)
            self._render_preview()
            return

        self.anchor_rect = self.rect_px
        if hit == "inside":
            self.mode = "moving"
            self.active_handle = "move"
            self.start_px = (px, py)
        elif hit in self.HANDLE_ORDER:
            self.mode = "resizing"
            self.active_handle = hit
        else:
            self.mode = "creating"
            self.active_handle = None
            self.start_px = (px, py)
            self.rect_px = self._normalize_rect(px, py, px + 1, py + 1)

        self._render_preview()

    def on_drag(self, event):
        if not self.canvas.map_data or self.mode == "idle":
            return

        px, py = self._event_to_image_px(event)

        if self.mode == "creating" and self.start_px is not None:
            self.rect_px = self._normalize_rect(self.start_px[0], self.start_px[1], px + 1, py + 1)
        elif self.mode == "moving" and self.anchor_rect is not None and self.start_px is not None:
            dx = px - self.start_px[0]
            dy = py - self.start_px[1]
            self.rect_px = self._translate_rect(self.anchor_rect, dx, dy)
        elif self.mode == "resizing" and self.anchor_rect is not None and self.active_handle:
            self.rect_px = self._resize_rect(self.anchor_rect, self.active_handle, px, py)

        self._render_preview()

    def on_release(self, event):
        if self.mode == "creating" and self.rect_px is not None:
            self.rect_px = self._normalize_rect(*self.rect_px)
        self.mode = "idle"
        self.active_handle = None
        self.start_px = None
        self.anchor_rect = None
        self._render_preview()

    def on_move(self, event):
        if self.mode != "idle" or self.rect_px is None:
            return

        hit = self._hit_test(event)
        cursor = self.HANDLE_CURSORS.get(hit, self.cursor)
        self.canvas.config(cursor=cursor)

    def on_key_press(self, event):
        if event.keysym == "Escape":
            if self.rect_px is not None:
                self.rect_px = None
                self.mode = "idle"
                self.active_handle = None
                self.start_px = None
                self.anchor_rect = None
                self.canvas.config(cursor=self.cursor)
                self._render_preview()
                if self.controller and hasattr(self.controller, "statusbar_left"):
                    self.controller.statusbar_left.config(text="Crop selection cleared")
            elif self.controller and hasattr(self.controller, "tool_manager"):
                self.controller.tool_manager.set_tool("pan")
        elif event.keysym == "Return" and self.rect_px is not None:
            x0, y0, x1, y1 = self._normalize_rect(*self.rect_px)
            applied = False
            if self.controller and hasattr(self.controller, "crop_map_to_pixels"):
                applied = bool(self.controller.crop_map_to_pixels(x0, y0, x1, y1))
            if applied and self.controller and hasattr(self.controller, "tool_manager"):
                self.controller.tool_manager.set_tool("pan")

    def _event_to_image_px(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        px, py = self.canvas.canvas_to_image(cx, cy)
        return self._clamp_px(px, py)

    def _clamp_px(self, px, py):
        max_x = max(0, self.canvas.map_data.width - 1)
        max_y = max(0, self.canvas.map_data.height - 1)
        return max(0, min(int(px), max_x)), max(0, min(int(py), max_y))

    def _normalize_rect(self, x0, y0, x1, y1):
        x0, x1 = sorted((int(x0), int(x1)))
        y0, y1 = sorted((int(y0), int(y1)))

        max_x = self.canvas.map_data.width
        max_y = self.canvas.map_data.height
        x0 = max(0, min(x0, max_x - 1))
        y0 = max(0, min(y0, max_y - 1))
        x1 = max(x0 + 1, min(x1, max_x))
        y1 = max(y0 + 1, min(y1, max_y))
        return x0, y0, x1, y1

    def _translate_rect(self, rect, dx, dy):
        x0, y0, x1, y1 = rect
        width = x1 - x0
        height = y1 - y0

        new_x0 = x0 + dx
        new_y0 = y0 + dy
        new_x0 = max(0, min(new_x0, self.canvas.map_data.width - width))
        new_y0 = max(0, min(new_y0, self.canvas.map_data.height - height))
        return new_x0, new_y0, new_x0 + width, new_y0 + height

    def _resize_rect(self, rect, handle, px, py):
        x0, y0, x1, y1 = rect
        px = max(0, min(px, self.canvas.map_data.width))
        py = max(0, min(py, self.canvas.map_data.height))

        if "w" in handle:
            x0 = min(px, x1 - 1)
        if "e" in handle:
            x1 = max(px + 1, x0 + 1)
        if handle == "n":
            y0 = min(py, y1 - 1)
        if handle == "s":
            y1 = max(py + 1, y0 + 1)
        if "n" in handle and handle not in ("n",):
            y0 = min(py, y1 - 1)
        if "s" in handle and handle not in ("s",):
            y1 = max(py + 1, y0 + 1)

        return self._normalize_rect(x0, y0, x1, y1)

    def _hit_test(self, event):
        if self.rect_px is None or not self.canvas.map_data:
            return None

        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        x0, y0, x1, y1 = self.rect_px
        left, top = self.canvas.image_to_canvas(x0, y0)
        right, bottom = self.canvas.image_to_canvas(x1, y1)
        if left > right:
            left, right = right, left
        if top > bottom:
            top, bottom = bottom, top

        tolerance = max(6, 8 * self.canvas.zoom_level ** 0.25)
        mid_x = (left + right) / 2.0
        mid_y = (top + bottom) / 2.0
        handles = {
            "nw": (left, top),
            "n": (mid_x, top),
            "ne": (right, top),
            "e": (right, mid_y),
            "se": (right, bottom),
            "s": (mid_x, bottom),
            "sw": (left, bottom),
            "w": (left, mid_y),
        }
        for name in self.HANDLE_ORDER:
            hx, hy = handles[name]
            if abs(cx - hx) <= tolerance and abs(cy - hy) <= tolerance:
                return name

        if left <= cx <= right and top <= cy <= bottom:
            return "inside"
        return None

    def _render_preview(self):
        self.canvas.delete("tool_preview")
        if self.rect_px is None:
            return

        x0, y0, x1, y1 = self.rect_px
        left, top = self.canvas.image_to_canvas(x0, y0)
        right, bottom = self.canvas.image_to_canvas(x1, y1)
        if left > right:
            left, right = right, left
        if top > bottom:
            top, bottom = bottom, top

        self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline="#00d4ff",
            width=2,
            dash=(6, 4),
            tags="tool_preview",
        )

        handle_size = 4
        mid_x = (left + right) / 2.0
        mid_y = (top + bottom) / 2.0
        for hx, hy in (
            (left, top),
            (mid_x, top),
            (right, top),
            (right, mid_y),
            (right, bottom),
            (mid_x, bottom),
            (left, bottom),
            (left, mid_y),
        ):
            self.canvas.create_rectangle(
                hx - handle_size,
                hy - handle_size,
                hx + handle_size,
                hy + handle_size,
                fill="#00d4ff",
                outline="white",
                tags="tool_preview",
            )

        label = f"{x1 - x0} x {y1 - y0} px | Enter 确认 | Esc 取消"
        self.canvas.create_text(
            left,
            max(12, top - 10),
            text=label,
            anchor="sw",
            fill="#00d4ff",
            font=("Arial", 9, "bold"),
            tags="tool_preview",
        )
