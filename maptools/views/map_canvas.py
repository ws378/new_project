import tkinter as tk
from PIL import Image, ImageDraw, ImageTk
import math
import colorsys
from typing import Sequence
import cv2
import numpy as np
from ..utils.coordinate import CoordinateTransformer
from ..utils.constraint_styles import constraint_visual_style
from ..utils.room_identity import area_room_id
from ..models.annotations import Annotations
from ..models.coverage_path import CoveragePathManager
from ..utils.free_space_components import (
    FreeSpaceComponentStat,
    analyze_free_space_components,
)
from .theme import COLORS

class MapCanvas(tk.Canvas):
    """
    负责地图显示、缩放、平移的画布组件
    """
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=COLORS["bg_root"], highlightthickness=0, **kwargs)

        # 状态数据
        self.map_data = None
        self.annotations = None  # Annotations model
        self.original_image = None  # PIL Image
        self.display_image = None   # PIL Image (resized)
        self.tk_image = None        # ImageTk (held to prevent GC)

        # 视图变换参数
        self.zoom_level = 1.0
        self.pan_offset_x = 0
        self.pan_offset_y = 0
        self._zoom_refresh_after_id = None
        self.zoom_callback = None

        # 显示选项
        self.show_base_map = True
        self.show_grid = False
        self.show_origin = True
        self.show_scale = True
        self.show_annotations = True
        self.show_pass_only_zones = True
        self.show_area_labels = True
        self.show_free_space_components = False
        self.free_space_component_repair_radius_m = 0.15
        self.small_component_no_coverage_threshold_m2 = 1000.0
        self.free_space_components_result = None
        self._free_space_components_cache_key = None
        self._free_space_overlay_image = None
        self._free_space_hover_component_id = None
        self._free_space_hover_semantic = None
        self.free_space_status_callback = None
        self._derived_constraint_region_images = []
        self._area_label_overlay_image = None
        self._area_label_overlay_cache = None
        self._free_space_overlay_cache = None
        self._derived_region_overlay_cache = None
        self._derived_region_index_cache = None
        self._derived_region_mask_cache = {}

        # 参考轨迹叠加数据（只显示，不参与导出）
        self.reference_trajectory_world = []  # List[(wx, wy)]

        # 覆盖路径叠加数据 (Legacy/Display only)
        self.coverage_path_pixels = None  # List[(px, py)] 像素坐标
        self.coverage_path_callback = None  # 右键菜单生成回调
        self.delete_coverage_path_callback = None  # 右键菜单删除回调
        self.has_coverage_path_for = None  # 检查某区域是否有路径的回调

        # 覆盖路径可编辑数据 (New)
        self.coverage_path_manager: CoveragePathManager = None
        self.path_label_threshold: float = 8.0  # Zoom > 8.0x 时才显示 ID

        # 临时取点模式 (设置覆盖路径起点)
        self._pick_start_mode = False
        self._pick_start_area_label = None

        # 选中状态数据 (供 SelectTool 使用)
        self.selected_item = None
        self.selected_type = None
        self.selected_constraint_segment_ids = set()

        # 坐标转换器
        self.coord_transformer = None

        # 拖拽状态
        self.drag_start_x = 0
        self.drag_start_y = 0

        # 绑定事件
        self.bind("<Configure>", self.on_resize)
        self.bind("<ButtonPress-2>", self.start_pan)  # 中键平移
        self.bind("<B2-Motion>", self.do_pan)
        self.bind("<ButtonRelease-2>", self.end_pan)
        self.bind("<MouseWheel>", self.on_zoom)       # Windows/MacOS
        self.bind("<Button-4>", self.on_zoom)         # Linux Scroll Up
        self.bind("<Button-5>", self.on_zoom)         # Linux Scroll Down
        self.bind("<Button-3>", self._on_right_click)  # 右键菜单
        self.bind("<Double-Button-1>", self._on_double_click)  # 双击居中
        self.bind("<Leave>", self._on_leave)
        self.bind("<Escape>", self._on_escape)
        self.bind("<KeyPress>", self._on_key_press)

        # 兼容 Space + 左键拖拽平移
        self.bind("<space>", lambda e: self.config(cursor="fleur"))
        self.bind("<KeyRelease-space>", lambda e: self.config(cursor="arrow"))

    def set_map_data(self, map_data):
        """设置要显示的地图数据"""
        self.map_data = map_data
        self.coord_transformer = CoordinateTransformer(map_data, self)
        if map_data and map_data.base_image:
            self.original_image = map_data.get_display_image()
            # 初始居中显示
            self.zoom_to_fit()
        self.refresh()

    def set_annotations(self, annotations: Annotations):
        """设置标注数据"""
        self.annotations = annotations
        self._free_space_components_cache_key = None
        self._derived_region_overlay_cache = None
        self._area_label_overlay_cache = None
        self._derived_region_index_cache = None
        self._derived_region_mask_cache = {}
        self.refresh()

    def set_coverage_path_manager(self, manager: CoveragePathManager):
        """设置可编辑路径管理器"""
        self.coverage_path_manager = manager
        self.refresh()

    def set_free_space_components_enabled(self, enabled: bool):
        self.show_free_space_components = bool(enabled)
        if not self.show_free_space_components:
            self.free_space_components_result = None
            self._free_space_components_cache_key = None
            self._free_space_overlay_cache = None
            self._free_space_hover_component_id = None
            self._emit_free_space_status(None)
        self._derived_region_overlay_cache = None
        self.refresh()

    def set_free_space_component_repair_radius(self, radius_m: float):
        self.free_space_component_repair_radius_m = max(float(radius_m), 0.0)
        self._free_space_components_cache_key = None
        self._free_space_overlay_cache = None
        self._derived_region_overlay_cache = None
        if self.show_free_space_components:
            self.refresh()

    def set_small_component_no_coverage_threshold(self, threshold_m2: float):
        self.small_component_no_coverage_threshold_m2 = max(float(threshold_m2), 0.0)
        self._free_space_components_cache_key = None
        self._free_space_overlay_cache = None
        self._derived_region_overlay_cache = None
        if self.show_free_space_components:
            self.refresh()

    def _current_free_space_analysis_cache_key(self):
        map_stamp = int(getattr(self.map_data, "change_stamp", 0)) if self.map_data else 0
        ann_stamp = int(getattr(self.annotations, "analysis_change_stamp", 0)) if self.annotations else 0
        return (
            map_stamp,
            ann_stamp,
            round(float(self.free_space_component_repair_radius_m), 6),
            round(float(self.small_component_no_coverage_threshold_m2), 6),
        )

    def _ensure_free_space_components_result(self):
        if not self.show_free_space_components or not self.map_data or not self.annotations or not self.map_data.metadata:
            self.free_space_components_result = None
            self._free_space_components_cache_key = None
            return
        cache_key = self._current_free_space_analysis_cache_key()
        if self.free_space_components_result is not None and self._free_space_components_cache_key == cache_key:
            return
        self.free_space_components_result = analyze_free_space_components(
            self.map_data,
            self.annotations,
            repair_radius_m=self.free_space_component_repair_radius_m,
            small_component_threshold_m2=self.small_component_no_coverage_threshold_m2,
        )
        self._free_space_components_cache_key = cache_key
        self._free_space_overlay_cache = None
        self._derived_region_overlay_cache = None

    def _emit_free_space_status(self, stat: FreeSpaceComponentStat | None, *, semantic_type: str | None = None):
        callback = self.free_space_status_callback
        if callable(callback):
            callback(stat, self.free_space_components_result, semantic_type)

    def coverage_debug_stats(self) -> dict:
        """返回当前画布覆盖路径显示统计，便于排查“看到了什么”。"""

        manager_nodes = list(self.coverage_path_manager.nodes) if self.coverage_path_manager else []
        room_ids = sorted({int(node.room) for node in manager_nodes})
        return {
            "manager_points": len(manager_nodes),
            "manager_rooms": room_ids,
            "legacy_points": len(self.coverage_path_pixels or ()),
            "canvas_items": len(self.find_withtag("coverage_path")),
        }

    def set_reference_trajectory(self, trajectory_world: Sequence[tuple[float, float]] | None):
        """设置只读参考轨迹（世界坐标）。"""
        self.reference_trajectory_world = list(trajectory_world or [])
        self.refresh()

    def clear_reference_trajectory(self):
        """清除只读参考轨迹。"""
        self.reference_trajectory_world = []
        self.delete("reference_trajectory")

    def set_selected_constraint_segments(self, segments):
        self.selected_constraint_segment_ids = {
            str(segment.id)
            for segment in (segments or [])
            if hasattr(segment, "id")
        }

    def get_selected_constraint_segments(self):
        if not self.annotations:
            return []
        return [
            segment
            for segment in self.annotations.constraint_segments
            if str(segment.id) in self.selected_constraint_segment_ids
        ]

    def _get_visible_region(self):
        """计算当前视口可见的源图像像素区域
        Returns: (src_x0, src_y0, src_x1, src_y1) 源图像中可见的像素范围
                 or None if nothing visible
        """
        if not self.map_data:
            return None

        canvas_w = self.winfo_width()
        canvas_h = self.winfo_height()
        if canvas_w <= 1 or canvas_h <= 1:
            return None

        img_w = self.map_data.width
        img_h = self.map_data.height
        if img_w <= 0 or img_h <= 0:
            return None

        # Canvas viewport corners (0,0) to (canvas_w, canvas_h) mapped to image pixels
        src_x0 = (0 - self.pan_offset_x) / self.zoom_level
        src_y0 = (0 - self.pan_offset_y) / self.zoom_level
        src_x1 = (canvas_w - self.pan_offset_x) / self.zoom_level
        src_y1 = (canvas_h - self.pan_offset_y) / self.zoom_level

        # Clamp to image bounds
        src_x0 = max(0, int(math.floor(src_x0)))
        src_y0 = max(0, int(math.floor(src_y0)))
        src_x1 = min(img_w, int(math.ceil(src_x1)))
        src_y1 = min(img_h, int(math.ceil(src_y1)))

        if src_x1 <= src_x0 or src_y1 <= src_y0:
            return None

        return (src_x0, src_y0, src_x1, src_y1)

    def _render_map_image(self):
        """渲染地图图像 (仅可见视口区域)"""
        if not self.map_data:
            return

        region = self._get_visible_region()
        if region is None:
            # Fallback: nothing visible or no data
            self.tk_image = None
            return

        src_x0, src_y0, src_x1, src_y1 = region

        # Get only the visible region from map data (avoids full array copy)
        region_img = self.map_data.get_display_image_region(src_x0, src_y0, src_x1, src_y1)
        if region_img is None:
            self.tk_image = None
            return

        # Calculate the zoomed size of this region
        region_w = src_x1 - src_x0
        region_h = src_y1 - src_y0
        display_w = max(1, int(region_w * self.zoom_level))
        display_h = max(1, int(region_h * self.zoom_level))

        # Resize only the visible region
        resized = region_img.resize((display_w, display_h), Image.NEAREST)
        self.display_image = resized
        self.tk_image = ImageTk.PhotoImage(resized)

        # Position: the region starts at (src_x0, src_y0) in image coords
        # which maps to canvas coords:
        draw_x = self.pan_offset_x + src_x0 * self.zoom_level
        draw_y = self.pan_offset_y + src_y0 * self.zoom_level

        if self.show_base_map:
            self.create_image(
                draw_x, draw_y,
                image=self.tk_image,
                anchor="nw",
                tags="map_image"
            )

    def refresh(self):
        """刷新画布显示 (完整重绘)"""
        self.delete("all")

        if not self.map_data:
            return

        # 1. 渲染地图图像 (仅可见区域)
        self._render_map_image()

        # 1.5 渲染自由连通区分析叠加
        self._ensure_free_space_components_result()
        if self.show_free_space_components and self.free_space_components_result is not None:
            self._draw_free_space_components_overlay()

        # 2. 绘制标注
        if self.show_annotations:
            self._draw_annotations()

        # 3. 绘制参考轨迹叠加
        self._draw_reference_trajectory()

        # 4. 绘制覆盖路径叠加
        # 如果可编辑路径管理器有节点，优先使用可编辑渲染器
        if self.coverage_path_manager and self.coverage_path_manager.nodes:
            self._draw_coverage_paths_editable()
        else:
            self._draw_coverage_path()

        # 5. 绘制辅助层
        self._draw_overlay()

    def refresh_image_only(self):
        """仅刷新地图图像，不重绘标注和辅助层 (用于画笔拖拽时)"""
        self.delete("map_image")
        self._render_map_image()

    def _free_space_overlay_cache_key(self, src_x0: int, src_y0: int, src_x1: int, src_y1: int):
        ann_stamp = int(getattr(self.annotations, "change_stamp", 0)) if self.annotations is not None else 0
        return (
            int(src_x0),
            int(src_y0),
            int(src_x1),
            int(src_y1),
            round(float(self.zoom_level), 6),
            ann_stamp,
            self._free_space_components_cache_key,
        )

    def _derived_region_index(self):
        if not self.annotations:
            return None
        ann_stamp = int(getattr(self.annotations, "change_stamp", 0))
        cached = getattr(self, "_derived_region_index_cache", None)
        if cached is not None and cached.get("ann_stamp") == ann_stamp:
            return cached

        self._derived_region_mask_cache = {}
        bucket_size = 256
        regions = []
        buckets = {}
        iterator = getattr(self.annotations, "iter_derived_constraint_regions", None)
        if callable(iterator):
            for region in iterator():
                if region.action_type not in {"forbidden_zone", "no_coverage"}:
                    continue
                x, y, width, height = (int(value) for value in region.bbox_px)
                if width <= 0 or height <= 0:
                    continue
                index = len(regions)
                regions.append((region, x, y, width, height))
                bx0 = x // bucket_size
                by0 = y // bucket_size
                bx1 = (x + width - 1) // bucket_size
                by1 = (y + height - 1) // bucket_size
                for by in range(by0, by1 + 1):
                    for bx in range(bx0, bx1 + 1):
                        buckets.setdefault((bx, by), []).append(index)

        self._derived_region_index_cache = {
            "ann_stamp": ann_stamp,
            "bucket_size": bucket_size,
            "regions": regions,
            "buckets": buckets,
        }
        return self._derived_region_index_cache

    def _iter_visible_derived_constraint_regions(self, src_x0, src_y0, src_x1, src_y1):
        index = self._derived_region_index()
        if index is None:
            return
        regions = index["regions"]
        if not regions:
            return
        bucket_size = int(index["bucket_size"])
        bx0 = int(src_x0) // bucket_size
        by0 = int(src_y0) // bucket_size
        bx1 = (int(src_x1) - 1) // bucket_size
        by1 = (int(src_y1) - 1) // bucket_size
        seen = set()
        for by in range(by0, by1 + 1):
            for bx in range(bx0, bx1 + 1):
                for region_index in index["buckets"].get((bx, by), ()):
                    if region_index in seen:
                        continue
                    seen.add(region_index)
                    region, x, y, width, height = regions[region_index]
                    if x >= src_x1 or y >= src_y1 or x + width <= src_x0 or y + height <= src_y0:
                        continue
                    yield region, x, y, width, height

    def _decoded_derived_region_mask(self, region):
        decoder = getattr(self.annotations, "decode_derived_constraint_region_mask", None) if self.annotations else None
        if not callable(decoder):
            return None
        ann_stamp = int(getattr(self.annotations, "change_stamp", 0))
        cache_key = (
            ann_stamp,
            str(region.id),
            tuple(int(value) for value in region.bbox_px),
            len(str(getattr(region, "packed_mask_b64", "") or "")),
        )
        cached = self._derived_region_mask_cache.get(cache_key)
        if cached is not None:
            return cached
        mask = decoder(region)
        self._derived_region_mask_cache[cache_key] = mask
        return mask

    def _draw_free_space_components_overlay(self):
        if self.free_space_components_result is None:
            return
        region = self._get_visible_region()
        if region is None:
            return
        src_x0, src_y0, src_x1, src_y1 = region
        labels = self.free_space_components_result.component_labels[src_y0:src_y1, src_x0:src_x1]
        if labels.size == 0:
            return
        cache_key = self._free_space_overlay_cache_key(src_x0, src_y0, src_x1, src_y1)
        if self._free_space_overlay_cache is not None and self._free_space_overlay_cache[0] == cache_key:
            self._free_space_overlay_image = self._free_space_overlay_cache[1]
            draw_x = self.pan_offset_x + src_x0 * self.zoom_level
            draw_y = self.pan_offset_y + src_y0 * self.zoom_level
            self.create_image(draw_x, draw_y, image=self._free_space_overlay_image, anchor="nw", tags="free_space_components")
            return
        labels_for_draw = np.array(labels, copy=True)
        if self.annotations:
            for region, x, y, width, height in self._iter_visible_derived_constraint_regions(src_x0, src_y0, src_x1, src_y1):
                x0 = max(src_x0, x)
                y0 = max(src_y0, y)
                x1 = min(src_x1, x + width)
                y1 = min(src_y1, y + height)
                if x1 <= x0 or y1 <= y0:
                    continue
                region_mask = self._decoded_derived_region_mask(region)
                if region_mask is None or region_mask.size == 0:
                    continue
                local_x0 = x0 - src_x0
                local_y0 = y0 - src_y0
                local_x1 = x1 - src_x0
                local_y1 = y1 - src_y0
                mask_x0 = x0 - x
                mask_y0 = y0 - y
                mask_x1 = mask_x0 + (x1 - x0)
                mask_y1 = mask_y0 + (y1 - y0)
                roi_labels = labels_for_draw[local_y0:local_y1, local_x0:local_x1]
                roi_mask = region_mask[mask_y0:mask_y1, mask_x0:mask_x1] > 0
                roi_labels[roi_mask] = 0
        lut = self.free_space_components_result.component_color_lut
        rgba = lut[labels_for_draw]
        if rgba.size == 0:
            return
        region_w = src_x1 - src_x0
        region_h = src_y1 - src_y0
        display_w = max(1, int(region_w * self.zoom_level))
        display_h = max(1, int(region_h * self.zoom_level))
        image = Image.fromarray(rgba, mode="RGBA").resize((display_w, display_h), Image.NEAREST)
        self._free_space_overlay_image = ImageTk.PhotoImage(image)
        self._free_space_overlay_cache = (cache_key, self._free_space_overlay_image)
        draw_x = self.pan_offset_x + src_x0 * self.zoom_level
        draw_y = self.pan_offset_y + src_y0 * self.zoom_level
        self.create_image(draw_x, draw_y, image=self._free_space_overlay_image, anchor="nw", tags="free_space_components")


    def _draw_annotations(self):
        if not self.annotations or not self.coord_transformer:
            return

        self._draw_derived_constraint_regions()
        self._draw_constraint_segments()

        # 绘制基站 (点+箭头)
        for station in self.annotations.stations:
            wx, wy = station.position
            cx, cy = self.coord_transformer.world_to_canvas(wx, wy)
            is_selected = (self.selected_item and self.selected_item.id == station.id)

            # 绘制点
            r = 7 if is_selected else 5
            self.create_oval(cx-r, cy-r, cx+r, cy+r, fill="green", outline="white", width=2, tags="annotation")

            # 绘制方向箭头
            length = 20
            # 注意: 画布坐标系Y轴向下，角度逆时针为正需要调整
            # ROS yaw: 0 is right, pi/2 is up
            # Canvas: 0 is right, pi/2 is down
            # Need to flip angle for visual if map y-axis is inverted

            # 简单的视觉转换：ROS angle -> Canvas angle
            # dx = cos(theta), dy = -sin(theta) (because Y flips)
            angle = station.orientation
            end_x = cx + length * math.cos(angle)
            end_y = cy - length * math.sin(angle) # Y轴翻转

            self.create_line(cx, cy, end_x, end_y, fill="lime", width=2, arrow=tk.LAST, tags="annotation")
            self.create_text(cx, cy-15, text=station.name, fill="lime", font=("Arial", 8), tags="annotation")

            if is_selected:
                self._draw_selection_handles([cx, cy])

        # 绘制区域标记
        if self.show_area_labels:
            self._draw_area_label_fill_overlay()
            for area in self.annotations.area_labels:
                if not area.polygon or len(area.polygon) < 3:
                    continue
                points = []
                cx_sum, cy_sum = 0, 0
                for wx, wy in area.polygon:
                    cx, cy = self.coord_transformer.world_to_canvas(wx, wy)
                    points.extend([cx, cy])
                    cx_sum += cx
                    cy_sum += cy

                if len(points) >= 6:
                    is_selected = (self.selected_item and self.selected_item.id == area.id)
                    outline_w = 4 if is_selected else 2
                    self.create_polygon(points, outline=area.color, fill="", width=outline_w, tags="annotation")
                    if is_selected:
                        self._draw_selection_handles(points)

                    # Centroid for label text
                    n = len(area.polygon)
                    centroid_x = cx_sum / n
                    centroid_y = cy_sum / n
                    label_text = f"Room {area_room_id(area)}"
                    self.create_text(centroid_x, centroid_y, text=label_text, fill="white", font=("Arial", 9, "bold"), tags="annotation")

    def _draw_area_label_fill_overlay(self):
        """Draw AreaLabel fills as real RGBA overlays instead of Tk stipple.

        Tk Canvas stipple rendering is backend-dependent: Linux/X11 usually
        looks translucent, while macOS Aqua Tk can render the same stipple as an
        almost solid fill. A PIL RGBA image keeps the visual contract stable.
        """
        if not self.annotations or not self.coord_transformer:
            return
        visible_region = self._get_visible_region()
        if visible_region is None:
            return
        areas = [
            area
            for area in self.annotations.area_labels
            if area.polygon and len(area.polygon) >= 3
        ]
        if not areas:
            return

        src_x0, src_y0, src_x1, src_y1 = visible_region
        region_w = src_x1 - src_x0
        region_h = src_y1 - src_y0
        display_w = max(1, int(region_w * self.zoom_level))
        display_h = max(1, int(region_h * self.zoom_level))
        ann_stamp = int(getattr(self.annotations, "change_stamp", 0))
        selected_id = getattr(getattr(self, "selected_item", None), "id", None)
        cache_key = (
            src_x0,
            src_y0,
            src_x1,
            src_y1,
            display_w,
            display_h,
            round(float(self.zoom_level), 6),
            ann_stamp,
            selected_id,
            tuple((area.id, area.color, len(area.polygon)) for area in areas),
        )
        if self._area_label_overlay_cache is not None and self._area_label_overlay_cache[0] == cache_key:
            overlay_image = self._area_label_overlay_cache[1]
        else:
            image = Image.new("RGBA", (display_w, display_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image, "RGBA")
            for area in areas:
                polygon = []
                for wx, wy in area.polygon:
                    px, py = self.coord_transformer.world_to_pixel(wx, wy)
                    polygon.append(
                        (
                            (px - src_x0) * self.zoom_level,
                            (py - src_y0) * self.zoom_level,
                        )
                    )
                if len(polygon) < 3:
                    continue
                fill = (*self._hex_color_to_rgb(area.color), 72)
                draw.polygon(polygon, fill=fill)
            overlay_image = ImageTk.PhotoImage(image)
            self._area_label_overlay_cache = (cache_key, overlay_image)
        self._area_label_overlay_image = overlay_image
        draw_x = self.pan_offset_x + src_x0 * self.zoom_level
        draw_y = self.pan_offset_y + src_y0 * self.zoom_level
        self.create_image(draw_x, draw_y, image=overlay_image, anchor="nw", tags="annotation")

    @staticmethod
    def _hex_color_to_rgb(color: str) -> tuple[int, int, int]:
        value = str(color or "").lstrip("#")
        if len(value) != 6:
            return 191, 191, 191
        try:
            return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
        except ValueError:
            return 191, 191, 191

    def _draw_constraint_segments(self):
        for segment in self.annotations.constraint_segments:
            if len(segment.points) < 2:
                continue
            if segment.constraint_type == "pass_only" and not self.show_pass_only_zones:
                continue

            canvas_points = []
            for wx, wy in segment.points:
                cx, cy = self.coord_transformer.world_to_canvas(wx, wy)
                canvas_points.extend([cx, cy])
            is_selected = (
                (self.selected_item and self.selected_item.id == segment.id)
                or (str(segment.id) in self.selected_constraint_segment_ids)
            )
            outline_w = 4 if is_selected else 2

            if segment.closed and len(canvas_points) >= 6:
                outline, fill, stipple = self._constraint_segment_style(segment.constraint_type)
                self.create_polygon(
                    canvas_points,
                    outline=outline,
                    fill=fill,
                    stipple=stipple,
                    width=outline_w,
                    tags="annotation",
                )
                if is_selected:
                    self._draw_selection_handles(canvas_points)
                continue

            line_points = canvas_points
            if len(line_points) >= 4:
                outline, _, _ = self._constraint_segment_style(segment.constraint_type)
                self.create_line(
                    line_points,
                    fill=outline,
                    width=outline_w + 1 if segment.constraint_type == "virtual_wall" else outline_w,
                    dash=(5, 3) if segment.constraint_type in {"virtual_wall", "electronic_fence"} else (),
                    tags="annotation",
                )
                if is_selected:
                    self._draw_selection_handles(line_points)

    def _draw_derived_constraint_regions(self):
        if not self.annotations:
            return
        visible_region = self._get_visible_region()
        if visible_region is None:
            return
        src_x0, src_y0, src_x1, src_y1 = visible_region
        ann_stamp = int(getattr(self.annotations, "change_stamp", 0))
        cache_key = (
            src_x0,
            src_y0,
            src_x1,
            src_y1,
            round(float(self.zoom_level), 6),
            ann_stamp,
        )
        if self._derived_region_overlay_cache is not None and self._derived_region_overlay_cache[0] == cache_key:
            overlay_image = self._derived_region_overlay_cache[1]
        else:
            region_w = src_x1 - src_x0
            region_h = src_y1 - src_y0
            rgba = np.zeros((region_h, region_w, 4), dtype=np.uint8)
            for region, x, y, width, height in self._iter_visible_derived_constraint_regions(src_x0, src_y0, src_x1, src_y1):
                x0 = max(src_x0, x)
                y0 = max(src_y0, y)
                x1 = min(src_x1, x + width)
                y1 = min(src_y1, y + height)
                if x1 <= x0 or y1 <= y0:
                    continue
                mask = self._decoded_derived_region_mask(region)
                if mask is None or mask.size == 0:
                    continue
                local_x0 = x0 - src_x0
                local_y0 = y0 - src_y0
                local_x1 = x1 - src_x0
                local_y1 = y1 - src_y0
                mask_x0 = x0 - x
                mask_y0 = y0 - y
                mask_x1 = mask_x0 + (x1 - x0)
                mask_y1 = mask_y0 + (y1 - y0)
                roi = rgba[local_y0:local_y1, local_x0:local_x1]
                roi_mask = mask[mask_y0:mask_y1, mask_x0:mask_x1] > 0
                fill = self._derived_constraint_region_fill(region.action_type)
                roi[roi_mask, 0] = fill[0]
                roi[roi_mask, 1] = fill[1]
                roi[roi_mask, 2] = fill[2]
                roi[roi_mask, 3] = fill[3]
                if str(getattr(region, "source", "") or "") == "unknown_region":
                    continue
                contours, _ = cv2.findContours(
                    np.where(mask[mask_y0:mask_y1, mask_x0:mask_x1] > 0, 255, 0).astype(np.uint8),
                    cv2.RETR_EXTERNAL,
                    cv2.CHAIN_APPROX_SIMPLE,
                )
                outline = self._derived_constraint_region_outline(region.action_type)
                for contour in contours:
                    if contour.size == 0:
                        continue
                    cv2.drawContours(roi, [contour], -1, outline, thickness=2)
            display_w = max(1, int(region_w * self.zoom_level))
            display_h = max(1, int(region_h * self.zoom_level))
            image = Image.fromarray(rgba, mode="RGBA").resize((display_w, display_h), Image.NEAREST)
            overlay_image = ImageTk.PhotoImage(image)
            self._derived_region_overlay_cache = (cache_key, overlay_image)
        self._derived_constraint_region_images = [overlay_image]
        draw_x = self.pan_offset_x + src_x0 * self.zoom_level
        draw_y = self.pan_offset_y + src_y0 * self.zoom_level
        self.create_image(draw_x, draw_y, image=overlay_image, anchor="nw", tags="annotation")

    @staticmethod
    def _constraint_segment_style(constraint_type: str):
        style = constraint_visual_style(constraint_type)
        return style.outline, style.fill, style.stipple

    @staticmethod
    def _derived_constraint_region_fill(action_type: str):
        return constraint_visual_style(action_type).overlay_rgba

    @staticmethod
    def _derived_constraint_region_outline(action_type: str):
        style = constraint_visual_style(action_type)
        color = style.outline.lstrip("#")
        rgb = tuple(int(color[idx : idx + 2], 16) for idx in (0, 2, 4))
        return rgb[0], rgb[1], rgb[2], 255

    def _draw_selection_handles(self, points, size=6):
        """为选中的对象绘制顶点控制锚点"""
        for i in range(0, len(points), 2):
            cx, cy = points[i], points[i+1]
            self.create_rectangle(cx-size/2, cy-size/2, cx+size/2, cy+size/2,
                                  fill="white", outline="black", tags="annotation_handle")

    def _draw_reference_trajectory(self):
        """绘制只读参考轨迹：细蓝虚线。"""
        if not self.reference_trajectory_world or len(self.reference_trajectory_world) < 2:
            return
        if not self.coord_transformer:
            return

        points = []
        for wx, wy in self.reference_trajectory_world:
            cx, cy = self.coord_transformer.world_to_canvas(wx, wy)
            points.extend([cx, cy])

        if len(points) < 4:
            return

        line_width = 1 if self.zoom_level < 4.0 else 2
        self.create_line(
            points,
            fill="#1e6cff",
            width=line_width,
            dash=(6, 6),
            tags="reference_trajectory",
        )

    def _draw_overlay(self):
        """绘制辅助层"""
        if not self.map_data or not self.coord_transformer:
            return

        # 获取当前可视区域的世界坐标范围
        # Canvas corners: (0,0) -> (width, height)
        cw = self.winfo_width()
        ch = self.winfo_height()
        wx1, wy1 = self.coord_transformer.canvas_to_world(0, 0)
        wx2, wy2 = self.coord_transformer.canvas_to_world(cw, ch)

        # 确定网格绘制范围
        min_wx, max_wx = min(wx1, wx2), max(wx1, wx2)
        min_wy, max_wy = min(wy1, wy2), max(wy1, wy2)

        # 1. 绘制网格 (1米间隔)
        if self.show_grid:
            self._draw_grid(min_wx, max_wx, min_wy, max_wy)

        # 2. 绘制原点
        if self.show_origin:
            self._draw_origin()

        # 3. 绘制比例尺
        if self.show_scale:
            self._draw_scale_bar()

    def handle_motion(self, event):
        if not self.show_free_space_components or self.free_space_components_result is None:
            return
        derived_region = self._hit_test_derived_constraint_region(event.x, event.y)
        if derived_region is not None:
            hover_key = (str(derived_region.action_type), int(derived_region.component_id))
            if self._free_space_hover_semantic == hover_key:
                return
            self._free_space_hover_semantic = hover_key
            self._free_space_hover_component_id = int(derived_region.component_id)
            stat = self.free_space_components_result.stat_for_label(int(derived_region.component_id))
            self._emit_free_space_status(stat, semantic_type=str(derived_region.action_type))
            return
        px, py = self.canvas_to_image(self.canvasx(event.x), self.canvasy(event.y))
        if (
            px < 0 or py < 0 or
            px >= self.free_space_components_result.component_labels.shape[1] or
            py >= self.free_space_components_result.component_labels.shape[0]
        ):
            if self._free_space_hover_component_id is not None or self._free_space_hover_semantic is not None:
                self._free_space_hover_component_id = None
                self._free_space_hover_semantic = None
                self._emit_free_space_status(None, semantic_type=None)
            return
        component_id = int(self.free_space_components_result.component_labels[py, px])
        if component_id <= 0:
            if self._free_space_hover_component_id is not None or self._free_space_hover_semantic is not None:
                self._free_space_hover_component_id = None
                self._free_space_hover_semantic = None
                self._emit_free_space_status(None, semantic_type=None)
            return
        if self._free_space_hover_component_id == component_id and self._free_space_hover_semantic == "free":
            return
        self._free_space_hover_component_id = component_id
        self._free_space_hover_semantic = "free"
        self._emit_free_space_status(self.free_space_components_result.stat_for_label(component_id), semantic_type="free")

    def _hit_test_free_space_component(self, cx, cy):
        if not self.show_free_space_components or self.free_space_components_result is None:
            return None
        px, py = self.canvas_to_image(self.canvasx(cx), self.canvasy(cy))
        labels = self.free_space_components_result.component_labels
        if px < 0 or py < 0 or py >= labels.shape[0] or px >= labels.shape[1]:
            return None
        component_id = int(labels[py, px])
        if component_id <= 0:
            return None
        return component_id

    def _hit_test_derived_constraint_region(self, cx, cy):
        if not self.show_annotations or not self.annotations:
            return None
        px, py = self.canvas_to_image(self.canvasx(cx), self.canvasy(cy))
        for region, x, y, width, height in self._iter_visible_derived_constraint_regions(px, py, px + 1, py + 1):
            mask = self._decoded_derived_region_mask(region)
            if mask is None or mask.size == 0:
                continue
            if mask[int(py - y), int(px - x)] > 0:
                return region
        return None

    def _on_leave(self, event):
        if self._free_space_hover_component_id is not None or self._free_space_hover_semantic is not None:
            self._free_space_hover_component_id = None
            self._free_space_hover_semantic = None
            self._emit_free_space_status(None, semantic_type=None)

    def _draw_grid(self, min_wx, max_wx, min_wy, max_wy):
        """绘制1m网格"""
        grid_size = 1.0 # 1 meter

        # 计算起始线
        start_x = math.floor(min_wx / grid_size) * grid_size
        start_y = math.floor(min_wy / grid_size) * grid_size

        # 绘制垂直线
        curr_x = start_x
        while curr_x <= max_wx + grid_size:
            cx1, cy1 = self.coord_transformer.world_to_canvas(curr_x, min_wy)
            cx2, cy2 = self.coord_transformer.world_to_canvas(curr_x, max_wy)
            self.create_line(cx1, cy1, cx2, cy2, fill="#404040", dash=(2, 4), tags="overlay")
            curr_x += grid_size

        # 绘制水平线
        curr_y = start_y
        while curr_y <= max_wy + grid_size:
            cx1, cy1 = self.coord_transformer.world_to_canvas(min_wx, curr_y)
            cx2, cy2 = self.coord_transformer.world_to_canvas(max_wx, curr_y)
            self.create_line(cx1, cy1, cx2, cy2, fill="#404040", dash=(2, 4), tags="overlay")
            curr_y += grid_size

    def _draw_origin(self):
        """绘制世界坐标原点"""
        # 原点 (0,0)
        cx, cy = self.coord_transformer.world_to_canvas(0, 0)

        # 轴长度 (50像素)
        axis_len = 50

        # X轴 (红) - ROS X is right
        # Canvas angle 0 is right.
        self.create_line(cx, cy, cx + axis_len, cy, fill="red", width=2, arrow=tk.LAST, tags="overlay")
        self.create_text(cx + axis_len + 10, cy, text="X", fill="red", font=("Arial", 10, "bold"), tags="overlay")

        # Y轴 (绿) - ROS Y is up
        # Canvas Y is down, so ROS Y corresponds to negative Canvas Y
        self.create_line(cx, cy, cx, cy - axis_len, fill="#00FF00", width=2, arrow=tk.LAST, tags="overlay")
        self.create_text(cx, cy - axis_len - 10, text="Y", fill="#00FF00", font=("Arial", 10, "bold"), tags="overlay")

        # 原点点
        self.create_oval(cx-3, cy-3, cx+3, cy+3, fill="white", outline="black", tags="overlay")

    def _draw_scale_bar(self):
        """绘制比例尺"""
        # 固定在左下角
        margin_x = 20
        margin_y = self.winfo_height() - 20

        # 目标: 找一个“整数”距离，使得它在屏幕上大概占 100 像素
        target_pixel_width = 100
        # 对应的世界距离
        # 1 pixel = resolution / zoom_level (meters) ?? No.
        # pixel_to_world logic: dist_world = dist_pixel * resolution / zoom ?? No.
        # Let's check coord transformer.
        # canvas_dist = world_dist / resolution * zoom
        # world_dist = canvas_dist * resolution / zoom
        res = self.map_data.metadata.resolution
        world_dist_raw = target_pixel_width * res / self.zoom_level

        # 找最近的整齐数字 (1, 2, 5, 10, etc.)
        magnitude = 10**math.floor(math.log10(world_dist_raw))
        # 候选: 1x, 2x, 5x magnitude
        candidates = [1*magnitude, 2*magnitude, 5*magnitude, 10*magnitude]
        world_dist = min(candidates, key=lambda x: abs(x - world_dist_raw))

        # 计算该距离对应的像素宽度
        pixel_width = world_dist / res * self.zoom_level

        # 绘制
        start_x = margin_x
        start_y = margin_y
        end_x = start_x + pixel_width

        # 线条
        self.create_line(start_x, start_y, end_x, start_y, fill="white", width=2, tags="overlay")
        self.create_line(start_x, start_y-5, start_x, start_y+5, fill="white", width=2, tags="overlay")
        self.create_line(end_x, start_y-5, end_x, start_y+5, fill="white", width=2, tags="overlay")

        # 文字
        text = f"{world_dist:.2g} m"
        self.create_text((start_x + end_x)/2, start_y - 10, text=text, fill="white", font=("Arial", 10), tags="overlay")



    def zoom_to_fit(self):
        """适应窗口大小"""
        if not self.map_data or self.map_data.width <= 0 or self.map_data.height <= 0:
            return

        canvas_w = self.winfo_width()
        canvas_h = self.winfo_height()
        img_w = self.map_data.width
        img_h = self.map_data.height

        if canvas_w <= 1 or canvas_h <= 1:
            return

        scale_w = canvas_w / img_w
        scale_h = canvas_h / img_h
        self.zoom_level = min(scale_w, scale_h) * 0.9 # 留一点边距

        # 居中
        new_w = img_w * self.zoom_level
        new_h = img_h * self.zoom_level
        self.pan_offset_x = (canvas_w - new_w) / 2
        self.pan_offset_y = (canvas_h - new_h) / 2

    def start_pan(self, event):
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def do_pan(self, event):
        dx = event.x - self.drag_start_x
        dy = event.y - self.drag_start_y

        self.pan_offset_x += dx
        self.pan_offset_y += dy

        self.drag_start_x = event.x
        self.drag_start_y = event.y

        self.move("all", dx, dy)

    def end_pan(self, event):
        """中键平移结束，完整刷新以更新视口渲染"""
        self.refresh()

    def on_zoom(self, event):
        """处理鼠标滚轮缩放"""
        scale_factor = 1.1

        # 判断滚轮方向
        if event.num == 5 or event.delta < 0:
            factor = 1.0 / scale_factor
        else:
            factor = scale_factor

        # 计算鼠标在图像上的相对位置，以便以鼠标为中心缩放
        # 鼠标在Canvas上的坐标: event.x, event.y
        # 图像左上角在Canvas上的坐标: self.pan_offset_x, self.pan_offset_y

        # 鼠标相对于图像左上角的偏移
        rel_x = event.x - self.pan_offset_x
        rel_y = event.y - self.pan_offset_y

        # 更新缩放级别
        new_zoom = self.zoom_level * factor

        # 限制缩放范围
        if new_zoom < 0.1: new_zoom = 0.1
        if new_zoom > 50.0: new_zoom = 50.0

        actual_factor = new_zoom / self.zoom_level
        self.zoom_level = new_zoom

        # 调整 pan_offset 以保持鼠标指向的图像点位置不变
        # 新的相对偏移 = 旧相对偏移 * 缩放比例
        new_rel_x = rel_x * actual_factor
        new_rel_y = rel_y * actual_factor

        # 新的图像左上角 = 鼠标位置 - 新的相对偏移
        self.pan_offset_x = event.x - new_rel_x
        self.pan_offset_y = event.y - new_rel_y

        self._schedule_zoom_refresh()

    def _schedule_zoom_refresh(self):
        if self._zoom_refresh_after_id is not None:
            return
        self._zoom_refresh_after_id = self.after(16, self._flush_zoom_refresh)

    def _flush_zoom_refresh(self):
        self._zoom_refresh_after_id = None
        self.refresh()
        if self.zoom_callback:
            self.zoom_callback(self.zoom_level)

    def on_resize(self, event):
        # 窗口大小改变时，如果还没有加载图片，不处理
        # 如果已经加载，可能不需要做什么，除非是zoom_to_fit模式
        pass

    def canvas_to_image(self, cx, cy):
        """将Canvas坐标转换为图像像素坐标"""
        if self.zoom_level == 0: return 0, 0
        px = (cx - self.pan_offset_x) / self.zoom_level
        py = (cy - self.pan_offset_y) / self.zoom_level
        return int(px), int(py)

    def image_to_canvas(self, px, py):
        """将图像像素坐标转换为Canvas坐标"""
        cx = px * self.zoom_level + self.pan_offset_x
        cy = py * self.zoom_level + self.pan_offset_y
        return cx, cy

    # ==================== 双击居中 ====================

    def _on_double_click(self, event):
        """双击将点击位置居中到画布中央。"""
        if not self.original_image:
            return
        canvas_w = self.winfo_width()
        canvas_h = self.winfo_height()
        if canvas_w <= 0 or canvas_h <= 0:
            return
        # 计算鼠标位置相对于当前视图的偏移
        dx = canvas_w / 2 - event.x
        dy = canvas_h / 2 - event.y
        self.pan_offset_x += dx
        self.pan_offset_y += dy
        self._schedule_zoom_refresh()

    # ==================== 右键菜单 ====================

    def _on_right_click(self, event):
        """处理右键点击事件"""
        if not self.annotations or not self.coord_transformer:
            return

        area_label_hit = self._hit_test_area_label(event.x, event.y) if getattr(self, "show_area_labels", False) else None
        derived_region_hit = self._hit_test_derived_constraint_region(event.x, event.y)
        component_id = None if derived_region_hit is not None else self._hit_test_free_space_component(event.x, event.y)
        if (derived_region_hit is not None or component_id is not None) and self._show_area_free_space_context_menu(
            event,
            area_label=area_label_hit,
            component_id=component_id,
            derived_region=derived_region_hit,
        ):
            return

        segment_hit, vertex_idx = self._hit_test_constraint_segment(event.x, event.y)
        if segment_hit is not None:
            self.selected_item = segment_hit
            self.selected_type = "constraint_segments"
            if str(segment_hit.id) not in self.selected_constraint_segment_ids:
                self.selected_constraint_segment_ids = {str(segment_hit.id)}
            self.refresh()
            menu = tk.Menu(self, tearoff=0)
            if (
                vertex_idx is not None
                and (
                    segment_hit.closed
                    or 0 < vertex_idx < (len(segment_hit.points) - 1)
                )
                and hasattr(self.winfo_toplevel(), "_split_constraint_segment_at_vertex")
            ):
                menu.add_command(
                    label=f"切开分段 - {segment_hit.name}",
                    command=lambda s=segment_hit, i=vertex_idx: self.winfo_toplevel()._split_constraint_segment_at_vertex(s, i),
                )
            if hasattr(self.winfo_toplevel(), "_can_merge_constraint_segment") and self.winfo_toplevel()._can_merge_constraint_segment(segment_hit):
                menu.add_command(
                    label=f"合并相邻段 - {segment_hit.name}",
                    command=lambda s=segment_hit: self.winfo_toplevel()._merge_constraint_segment(s),
                )
            if hasattr(self.winfo_toplevel(), "_toggle_constraint_segment_closed"):
                menu.add_command(
                    label=("改为开口段" if segment_hit.closed else "闭合成区域"),
                    command=lambda s=segment_hit: self.winfo_toplevel()._toggle_constraint_segment_closed(s),
                )
            if (
                len(self.selected_constraint_segment_ids) >= 2
                and hasattr(self.winfo_toplevel(), "_merge_selected_constraint_segments")
                and hasattr(self.winfo_toplevel(), "_can_merge_selected_constraint_segments")
                and self.winfo_toplevel()._can_merge_selected_constraint_segments()
            ):
                menu.add_command(
                    label=f"合并已选段 ({len(self.selected_constraint_segment_ids)})",
                    command=self.winfo_toplevel()._merge_selected_constraint_segments,
                )
            type_menu = tk.Menu(menu, tearoff=0)
            for type_name, label in (
                ("electronic_fence", "电子围栏"),
                ("virtual_wall", "虚拟墙"),
                ("forbidden_zone", "禁止区"),
                ("pass_only", "只通区"),
                ("no_coverage", "不规划覆盖"),
            ):
                type_menu.add_command(
                    label=label,
                    command=lambda s=segment_hit, t=type_name: self.winfo_toplevel()._change_constraint_segment_type(s, t),
                )
            menu.add_cascade(label="修改类型", menu=type_menu)
            menu.tk_popup(event.x_root, event.y_root)
            return

        if area_label_hit is not None:
            self._show_area_free_space_context_menu(
                event,
                area_label=area_label_hit,
                component_id=None,
                derived_region=None,
            )
        return

    def _show_area_free_space_context_menu(self, event, *, area_label=None, component_id=None, derived_region=None) -> bool:
        has_area = area_label is not None
        has_free_space = derived_region is not None or component_id is not None
        if not has_area and not has_free_space:
            return False
        toplevel = self.winfo_toplevel()
        if not has_area and has_free_space and hasattr(toplevel, "_show_free_space_component_menu"):
            self._log_free_space_right_click_hit(component_id=component_id, derived_region=derived_region)
            toplevel._show_free_space_component_menu(
                event,
                int(derived_region.component_id) if derived_region is not None else int(component_id),
                derived_region=derived_region,
            )
            return True

        menu = tk.Menu(self, tearoff=0)
        if has_area:
            self.selected_item = area_label
            self.selected_type = "area_labels"
            self.selected_constraint_segment_ids = set()
            self._sync_area_room_to_path_panel(area_label)
            self._log_area_label_right_click_hit(event, area_label)
            self._add_area_label_context_menu_items(menu, area_label)
        if has_area and has_free_space:
            menu.add_separator()
        if has_free_space:
            self._log_free_space_right_click_hit(component_id=component_id, derived_region=derived_region)
            self._add_free_space_context_menu_items(menu, component_id=component_id, derived_region=derived_region)
        menu.tk_popup(event.x_root, event.y_root)
        return True

    def _sync_area_room_to_path_panel(self, area_label) -> None:
        toplevel = self.winfo_toplevel()
        sidebar = getattr(toplevel, "sidebar", None)
        path_panel = getattr(sidebar, "path_panel", None)
        if path_panel is not None and hasattr(path_panel, "set_draw_room"):
            path_panel.set_draw_room(area_room_id(area_label))

    def _add_area_label_context_menu_items(self, menu, area_label):
        menu.add_command(
            label=f"生成覆盖路径 - {area_label.name}",
            command=lambda area=area_label: self._trigger_coverage(area),
        )
        if self.has_coverage_path_for and self.has_coverage_path_for(area_label):
            menu.add_command(
                label=f"删除覆盖路径 - {area_label.name}",
                command=lambda area=area_label: self._trigger_delete_coverage(area),
            )

    def _add_free_space_context_menu_items(self, menu, *, component_id=None, derived_region=None):
        toplevel = self.winfo_toplevel()
        target_id = int(derived_region.component_id) if derived_region is not None else int(component_id)
        if not hasattr(toplevel, "_populate_free_space_component_menu"):
            return
        toplevel._populate_free_space_component_menu(menu, target_id, derived_region=derived_region)

    def _log_area_label_right_click_hit(self, event, area_label):
        print(
            f"[coverage-debug] action=right_click_hit area_id={int(area_label.area_id)} "
            f"area_name={area_label.name!r} canvas=({event.x},{event.y})"
        )

    @staticmethod
    def _log_free_space_right_click_hit(*, component_id=None, derived_region=None):
        if derived_region is not None:
            print(
                f"[free-space-debug] action=right_click_hit semantic={str(derived_region.action_type)!r} "
                f"component_id={int(derived_region.component_id)!r} "
                f"component_key={str((derived_region.metadata or {}).get('component_key', ''))!r}"
            )
            return
        print(
            f"[free-space-debug] action=right_click_hit semantic='free' component_id={int(component_id)!r}"
        )

    def _trigger_coverage(self, area_label):
        """触发覆盖路径生成回调"""
        print(
            f"[coverage-debug] action=trigger_generate area_id={int(area_label.area_id)} "
            f"area_name={area_label.name!r}"
        )
        if self.coverage_path_callback:
            self.coverage_path_callback(area_label)

    def _trigger_delete_coverage(self, area_label):
        """触发删除覆盖路径回调"""
        if self.delete_coverage_path_callback:
            self.delete_coverage_path_callback(area_label)

    # ==================== 临时取点模式 ====================

    def _enter_pick_start_mode(self, area_label):
        """进入取点模式：等待用户在地图上点击选择覆盖路径起点"""
        self._pick_start_mode = True
        self._pick_start_area_label = area_label
        self.config(cursor="crosshair")
        # 更新状态栏提示
        main_win = self.winfo_toplevel()
        if hasattr(main_win, 'statusbar_left'):
            main_win.statusbar_left.config(
                text=f"请在地图上点击选择覆盖路径起点（Esc 取消） - {area_label.name}")

    def _exit_pick_start_mode(self):
        """退出取点模式，恢复光标和状态"""
        self._pick_start_mode = False
        self._pick_start_area_label = None
        self.config(cursor="arrow")
        main_win = self.winfo_toplevel()
        if hasattr(main_win, 'statusbar_left'):
            main_win.statusbar_left.config(text="Ready")

    def _on_left_click(self, event):
        """左键点击事件：在取点模式下拦截并获取起点坐标"""
        if not self._pick_start_mode:
            return  # 不在取点模式，不拦截

        if not self.coord_transformer:
            self._exit_pick_start_mode()
            return

        # 获取点击位置的世界坐标
        wx, wy = self.coord_transformer.canvas_to_world(event.x, event.y)
        area_label = self._pick_start_area_label

        # 退出取点模式
        self._exit_pick_start_mode()

        # 取点完成后回到统一的覆盖路径生成入口，不再暴露独立右键入口。
        if self.coverage_path_callback and area_label:
            self.coverage_path_callback(area_label, start_world_xy=(wx, wy))

        return "break"  # 阻止事件继续传播到当前工具

    def _on_escape(self, event):
        """Escape 键处理：优先取消取点模式，若无，则转发给 ToolManager"""
        if self._pick_start_mode:
            self._exit_pick_start_mode()
        else:
            # 伪造一个规范的keysym发送泛型按键事件
            event.keysym = 'Escape'
            self._on_key_press(event)

    def _on_key_press(self, event):
        """统一拦截所有的键盘操作，并转发给目前激活的工具（如删除）"""
        main_win = self.winfo_toplevel()
        if hasattr(main_win, 'tool_manager') and main_win.tool_manager is not None:
             main_win.tool_manager.handle_key_press(event)

    def _hit_test_area_label(self, cx, cy):
        """检测 Canvas 坐标 (cx, cy) 是否在某个 AreaLabel 多边形内

        Returns:
            AreaLabel 或 None
        """
        if not self.annotations:
            return None

        for area in self.annotations.area_labels:
            if not area.polygon or len(area.polygon) < 3:
                continue
            # 转换多边形到 Canvas 坐标
            canvas_poly = []
            for wx, wy in area.polygon:
                pcx, pcy = self.coord_transformer.world_to_canvas(wx, wy)
                canvas_poly.append((pcx, pcy))

            if self._point_in_polygon(cx, cy, canvas_poly):
                return area
        return None

    def _hit_test_constraint_segment(self, cx, cy):
        if not self.annotations or not self.coord_transformer:
            return None, None
        for segment in reversed(self.annotations.constraint_segments):
            if segment.constraint_type == "pass_only" and not self.show_pass_only_zones:
                continue
            vertex_idx = self._hit_test_constraint_segment_vertex(cx, cy, segment)
            if vertex_idx is not None:
                return segment, vertex_idx
            if segment.closed and len(segment.points) >= 3:
                if self._hit_test_polygon_pts(cx, cy, segment.points):
                    return segment, None
                continue
            if len(segment.points) < 2:
                continue
            for index in range(len(segment.points) - 1):
                cx1, cy1 = self.coord_transformer.world_to_canvas(*segment.points[index])
                cx2, cy2 = self.coord_transformer.world_to_canvas(*segment.points[index + 1])
                if self._distance_to_line_segment(cx, cy, cx1, cy1, cx2, cy2) <= 5:
                    return segment, None
        return None, None

    def _hit_test_constraint_segment_vertex(self, cx, cy, segment, tolerance=8):
        if not segment.points:
            return None
        for idx, (wx, wy) in enumerate(segment.points):
            px, py = self.coord_transformer.world_to_canvas(wx, wy)
            if math.hypot(cx - px, cy - py) <= tolerance:
                return idx
        return None

    @staticmethod
    def _point_in_polygon(x, y, polygon):
        """射线法判断点是否在多边形内"""
        n = len(polygon)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    # ==================== 命中检测与通用判定 ====================

    def hit_test_all(self, cx, cy):
        """通用命中检测，按层级返回选中的标注对象及其类型。
        层级顺序：小点(基站) -> 线段(虚拟墙) -> 封闭多边形(禁行/只通/区域)
        """
        if not self.annotations or not self.coord_transformer:
            return None, None

        # 1. 检查基站 (点)
        for station in self.annotations.stations:
            wx, wy = station.position
            scx, scy = self.coord_transformer.world_to_canvas(wx, wy)
            if math.hypot(cx - scx, cy - scy) <= 10:  # 容差 10 像素
                return station, 'stations'

        # 2. 检查统一约束分段
        for segment in self.annotations.constraint_segments:
            if segment.constraint_type == "pass_only" and not self.show_pass_only_zones:
                continue
            if segment.closed and len(segment.points) >= 3:
                if self._hit_test_polygon_pts(cx, cy, segment.points):
                    return segment, 'constraint_segments'
                continue
            if len(segment.points) < 2:
                continue
            for index in range(len(segment.points) - 1):
                cx1, cy1 = self.coord_transformer.world_to_canvas(*segment.points[index])
                cx2, cy2 = self.coord_transformer.world_to_canvas(*segment.points[index + 1])
                if self._distance_to_line_segment(cx, cy, cx1, cy1, cx2, cy2) <= 5:
                    return segment, 'constraint_segments'

        # 3. 检查区域标记
        if self.show_area_labels:
            for area in self.annotations.area_labels:
                if self._hit_test_polygon_pts(cx, cy, area.polygon):
                    return area, 'area_labels'

        return None, None

    def _hit_test_polygon_pts(self, cx, cy, world_polygon):
        """测试 Canvas 坐标是否落在世界坐标记录的多边形内"""
        if not world_polygon or len(world_polygon) < 3:
            return False
        canvas_poly = []
        for wx, wy in world_polygon:
            pcx, pcy = self.coord_transformer.world_to_canvas(wx, wy)
            canvas_poly.append((pcx, pcy))
        return self._point_in_polygon(cx, cy, canvas_poly)

    @staticmethod
    def _distance_to_line_segment(x, y, x1, y1, x2, y2):
        """计算点(x,y)到线段(x1,y1)-(x2,y2)的最短距离"""
        l2 = (x1 - x2) ** 2 + (y1 - y2) ** 2
        if l2 == 0:
            return math.hypot(x - x1, y - y1)
        # Projection of point onto the line
        t = max(0, min(1, ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / l2))
        proj_x = x1 + t * (x2 - x1)
        proj_y = y1 + t * (y2 - y1)
        return math.hypot(x - proj_x, y - proj_y)

    # ==================== 覆盖路径叠加 ====================

    def show_coverage_path(self, path_pixels):
        """设置并显示覆盖路径

        Args:
            path_pixels: List[(px, py)] 像素坐标路径点
        """
        self.coverage_path_pixels = path_pixels
        self.refresh()

    def clear_coverage_path(self):
        """清除覆盖路径叠加"""
        self.coverage_path_pixels = None
        self.delete("coverage_path")

    def _draw_coverage_path(self):
        """绘制覆盖路径叠加层 (旧版只读模式)"""
        if not self.coverage_path_pixels or len(self.coverage_path_pixels) < 2:
            return

        path = self.coverage_path_pixels
        n = len(path)

        # 绘制彩色折线段 (从蓝到红，渐变表示路径方向)
        for i in range(n - 1):
            px1, py1 = path[i]
            px2, py2 = path[i + 1]
            cx1, cy1 = self.image_to_canvas(px1, py1)
            cx2, cy2 = self.image_to_canvas(px2, py2)

            # 颜色渐变: 蓝(起始) -> 绿(中间) -> 红(终点)
            t = i / max(1, n - 2)
            r = int(255 * t)
            g = int(255 * (1 - abs(2 * t - 1)))
            b = int(255 * (1 - t))
            color = f"#{r:02x}{g:02x}{b:02x}"

            self.create_line(
                cx1, cy1, cx2, cy2,
                fill=color, width=2, tags="coverage_path")

        # 绘制路径点小圆圈
        r = max(2, int(2 * self.zoom_level))
        r = min(r, 5)  # 限制最大半径
        for i, (px, py) in enumerate(path):
            cx, cy = self.image_to_canvas(px, py)
            # 起点绿色，终点红色，中间白色
            if i == 0:
                pt_color = "#00FF00"
            elif i == n - 1:
                pt_color = "#FF0000"
            else:
                # 每隔几个点画一个，避免太密集
                if n > 100 and i % max(1, n // 100) != 0:
                    continue
                pt_color = "white"

            self.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                fill=pt_color, outline="", tags="coverage_path")

    def _get_segment_color(self, segment: int) -> str:
        """为段分配伪随机高对比度颜色 (基于黄金比例 HSV)"""
        golden_ratio_conjugate = 0.618033988749895
        h = (segment * golden_ratio_conjugate) % 1.0
        s = 0.8
        v = 0.95
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

    def _draw_coverage_paths_editable(self) -> None:
        """绘制可编辑的覆盖路径列表 (含分段颜色、选中光晕、视口裁剪)"""
        if not self.coverage_path_manager or not self.coverage_path_manager.nodes:
            return

        points = self.coverage_path_manager.nodes
        selection = self.coverage_path_manager.selection

        # 1. 视口裁剪：计算当前可见区域（带 100 像素冗余）
        vis = self._get_visible_region()
        if vis is None:
            return
        sx0, sy0, sx1, sy1 = vis
        margin = 100 / self.zoom_level
        u_min, u_max = sx0 - margin, sx1 + margin
        v_min, v_max = sy0 - margin, sy1 + margin

        # 2. 绘制连线
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]

            # 简单的 AABB 视口剔除
            if (p1.u < u_min and p2.u < u_min) or (p1.u > u_max and p2.u > u_max) or \
               (p1.v < v_min and p2.v < v_min) or (p1.v > v_max and p2.v > v_max):
                continue

            cx1, cy1 = self.image_to_canvas(p1.u, p1.v)
            cx2, cy2 = self.image_to_canvas(p2.u, p2.v)

            if p1.segment == p2.segment:
                color = self._get_segment_color(p1.segment)
                dash_pat = None
                width = max(1.0, 2 * self.zoom_level)
            else:
                color = "#888888" # 暗灰色跨段虚线
                dash_pat = (4, 4)
                width = max(1.0, 1 * self.zoom_level)

            self.create_line(
                cx1, cy1, cx2, cy2,
                fill=color, width=width, dash=dash_pat, tags="coverage_path"
            )

        # 3. 绘制点
        r_base = max(1.5, 3 * self.zoom_level)
        r_sel = r_base * 1.5
        show_labels = self.zoom_level >= self.path_label_threshold

        for i, p in enumerate(points):
            # 视口剔除
            if p.u < u_min or p.u > u_max or p.v < v_min or p.v > v_max:
                continue

            cx, cy = self.image_to_canvas(p.u, p.v)
            is_sel = p.id in selection

            if is_sel:
                # 绘制选中光晕 Halo
                self.create_oval(
                    cx - r_sel - 2, cy - r_sel - 2,
                    cx + r_sel + 2, cy + r_sel + 2,
                    fill="", outline="#FFFFFF", width=r_base, tags="coverage_path"
                )
                self.create_oval(
                    cx - r_sel, cy - r_sel, cx + r_sel, cy + r_sel,
                    fill="#FFFF00", outline="#000000", tags="coverage_path"
                )
            else:
                # 未选中点
                color = self._get_segment_color(p.segment)
                self.create_oval(
                    cx - r_base, cy - r_base,
                    cx + r_base, cy + r_base,
                    fill=color, outline="#222222", width=max(1, int(self.zoom_level*0.5)), tags="coverage_path"
                )

            # 4. 在点旁边绘制 ID
            if show_labels:
                self.create_text(
                    cx + r_base + 2, cy - r_base - 2,
                    text=str(p.id), fill="white", font=("Arial", max(8, int(10 * self.zoom_level))),
                    anchor="sw", tags="coverage_path"
                )

        # 5. 绘制起始点/终止点标记
        self._draw_start_end_markers()

    def _draw_start_end_markers(self):
        """绘制全局及每个 Room 的起始点/终止点醒目标记"""
        mgr = self.coverage_path_manager
        if not mgr or not self.coord_transformer:
            return

        markers = []
        # 全局终点（起点由 Room 级标记 R{rid}-S 代替）
        if mgr.end_point:
            markers.append(("E", mgr.end_point, "#FF3333", "#660000"))

        # 每个 Room 的起点和终点
        room_starts: dict[int, tuple[float, float]] = {}
        room_ends: dict[int, tuple[float, float]] = {}
        for node in mgr.nodes:
            rid = node.room_id
            if rid not in room_starts:
                room_starts[rid] = (node.x, node.y)
            room_ends[rid] = (node.x, node.y)

        _SNAP_TOL = 1.0
        for rid in sorted(room_starts):
            markers.append((f"R{rid}-S", room_starts[rid], "#66FF66", "#338833"))
        for rid in sorted(room_ends):
            if not mgr.end_point:
                markers.append((f"R{rid}-E", room_ends[rid], "#FF6666", "#883333"))
            else:
                dx = room_ends[rid][0] - mgr.end_point[0]
                dy = room_ends[rid][1] - mgr.end_point[1]
                if dx*dx + dy*dy > _SNAP_TOL*_SNAP_TOL:
                    markers.append((f"R{rid}-E", room_ends[rid], "#FF6666", "#883333"))

        for label, (wx, wy), fill, outline in markers:
            u, v = self.coord_transformer.world_to_pixel(wx, wy)
            cx, cy = self.image_to_canvas(u, v)

            r = max(6, 8 * self.zoom_level)
            # 外圈白色光晕
            self.create_oval(
                cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3,
                fill="", outline="#FFFFFF", width=2, tags="coverage_path"
            )
            # 实心圆
            self.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                fill=fill, outline=outline, width=2, tags="coverage_path"
            )
            # 标签文字
            font_size = max(10, int(12 * self.zoom_level))
            self.create_text(
                cx + r + 4, cy, text=label, fill="#FFFFFF",
                font=("Arial", font_size, "bold"), tags="coverage_path",
                anchor="w",
            )
