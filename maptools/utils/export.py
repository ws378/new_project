import os
import json
import yaml
import numpy as np
import cv2
from PIL import Image
from ..models.map_data import MapData
from ..models.annotations import Annotations
from .room_identity import area_room_id, canonical_room_name

class Exporter:
    """负责将地图和标注导出为ROS2/Nav2可用格式"""

    def __init__(self, map_data: MapData, annotations: Annotations):
        self.map_data = map_data
        self.annotations = annotations

    def export(self, output_dir: str):
        """
        导出完整项目到指定目录
        包括：
        1. 合并后的主地图 (map.pgm + map.yaml)
        2. 禁行区代价地图 (map_forbidden.pgm)
        3. 虚拟墙代价地图 (map_virtual_wall.pgm)
        4. 原始标注数据 (annotations.json)
        """
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        print(f"Exporting to {output_dir}...")

        # 1. 保存标注数据 (JSON)
        json_path = os.path.join(output_dir, "annotations.json")
        self.annotations.save(json_path)

        # 2. 导出合并后的主地图
        self._export_merged_map(output_dir)

        # 3. 导出禁行区图层
        self._export_layer(output_dir, "forbidden", "map_forbidden")

        # 4. 导出虚拟墙图层
        self._export_layer(output_dir, "virtual_wall", "map_virtual_wall")

        # 4.5 导出只通区图层
        self._export_layer(output_dir, "pass_only", "map_pass_only")

        # 6. 导出区域标记图层
        self._export_area_labels_pgm(output_dir)
        self._export_area_labels_json(output_dir)

        # 5. 复制/生成对应的 YAML 文件
        # 注意：所有导出的 PGM 共用相同的元数据（分辨率、原点等）
        self._export_yaml(output_dir, "map.yaml", "map.pgm")
        self._export_yaml(output_dir, "map_forbidden.yaml", "map_forbidden.pgm")
        self._export_yaml(output_dir, "map_virtual_wall.yaml", "map_virtual_wall.pgm")
        self._export_yaml(output_dir, "map_pass_only.yaml", "map_pass_only.pgm")
        self._export_yaml(output_dir, "map_area_labels.yaml", "map_area_labels.pgm")

        print("Export completed.")

    def _export_merged_map(self, output_dir):
        """导出合并了编辑层的主地图"""
        if self.map_data.base_image is None:
            return

        # 获取原始地图数据
        merged = self.map_data.grid_map.copy()

        # 应用编辑层
        # edit_layer: 0=障碍, 254=通行, 255=无修改
        if self.map_data.edit_layer is not None:
            mask = self.map_data.edit_layer != 255
            merged[mask] = self.map_data.edit_layer[mask]

        # 保存
        path = os.path.join(output_dir, "map.pgm")
        Image.fromarray(merged).save(path)

    def _export_layer(self, output_dir, layer_type, filename_prefix):
        """
        导出特定类型的标注层
        生成的地图中：
        - 0 (黑色) = 障碍/生效区域
        - 254 (白色) = 空闲/无区域
        """
        width = self.map_data.width
        height = self.map_data.height
        meta = self.map_data.metadata

        # 初始化为全白 (254)
        layer = np.full((height, width), 254, dtype=np.uint8)

        # 坐标转换函数: World -> Pixel
        def world_to_px(wx, wy):
            # px = (wx - origin_x) / res
            # py = height - (wy - origin_y) / res
            px = int((wx - meta.origin[0]) / meta.resolution)
            py = int(height - (wy - meta.origin[1]) / meta.resolution)
            return px, py

        if layer_type == "forbidden":
            for zone in self.annotations.forbidden_zones:
                if not zone.polygon or len(zone.polygon) < 3:
                    continue

                pts = []
                for wx, wy in zone.polygon:
                    pts.append(world_to_px(wx, wy))

                # cv2需要numpy数组格式: (N, 1, 2)
                pts_np = np.array(pts, dtype=np.int32)
                pts_np = pts_np.reshape((-1, 1, 2))

                # 填充多边形为黑色 (0)
                cv2.fillPoly(layer, [pts_np], 0)

        elif layer_type == "pass_only":
            for zone in self.annotations.pass_only_zones:
                if not zone.polygon or len(zone.polygon) < 3:
                    continue

                pts = []
                for wx, wy in zone.polygon:
                    pts.append(world_to_px(wx, wy))

                # cv2需要numpy数组格式: (N, 1, 2)
                pts_np = np.array(pts, dtype=np.int32)
                pts_np = pts_np.reshape((-1, 1, 2))

                # 填充多边形为黑色 (0)
                cv2.fillPoly(layer, [pts_np], 0)

        elif layer_type == "virtual_wall":
            for wall in self.annotations.virtual_walls:
                p1 = world_to_px(*wall.start)
                p2 = world_to_px(*wall.end)

                # 绘制线段为黑色 (0)，宽度设为3像素(约15cm)
                cv2.line(layer, p1, p2, 0, thickness=3)

        if layer_type == "forbidden":
            self._apply_derived_regions_to_layer(layer, "forbidden_zone", fill_value=0)

        # 保存
        path = os.path.join(output_dir, f"{filename_prefix}.pgm")
        Image.fromarray(layer).save(path)

    def _apply_derived_regions_to_layer(self, layer: np.ndarray, action_type: str, *, fill_value: int) -> None:
        iterator = getattr(self.annotations, "iter_derived_constraint_regions", None)
        decoder = getattr(self.annotations, "decode_derived_constraint_region_mask", None)
        if not callable(iterator) or not callable(decoder):
            return
        for region in iterator(action_type):
            x, y, width, height = (int(value) for value in region.bbox_px)
            if width <= 0 or height <= 0:
                continue
            region_mask = decoder(region)
            if region_mask.size == 0:
                continue
            x0 = max(0, x)
            y0 = max(0, y)
            x1 = min(layer.shape[1], x + width)
            y1 = min(layer.shape[0], y + height)
            if x1 <= x0 or y1 <= y0:
                continue
            region_x0 = x0 - x
            region_y0 = y0 - y
            region_x1 = region_x0 + (x1 - x0)
            region_y1 = region_y0 + (y1 - y0)
            roi = layer[y0:y1, x0:x1]
            roi_region = region_mask[region_y0:region_y1, region_x0:region_x1]
            roi[roi_region > 0] = int(fill_value)

    def _export_area_labels_pgm(self, output_dir):
        """导出区域标记PGM图层，每个区域用其area_id作为灰度值"""
        if not self.annotations.area_labels:
            # Still create an empty (all-zero) layer for consistency
            width = self.map_data.width
            height = self.map_data.height
            layer = np.zeros((height, width), dtype=np.uint8)
            path = os.path.join(output_dir, "map_area_labels.pgm")
            Image.fromarray(layer).save(path)
            return

        width = self.map_data.width
        height = self.map_data.height
        meta = self.map_data.metadata

        # Background = 0 (no area)
        layer = np.zeros((height, width), dtype=np.uint8)

        def world_to_px(wx, wy):
            px = int((wx - meta.origin[0]) / meta.resolution)
            py = int(height - (wy - meta.origin[1]) / meta.resolution)
            return px, py

        for area in self.annotations.area_labels:
            if not area.polygon or len(area.polygon) < 3:
                continue

            pts = []
            for wx, wy in area.polygon:
                pts.append(world_to_px(wx, wy))

            pts_np = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
            # Use room_id as grayscale value, clamped to 255 for PGM storage.
            value = min(area_room_id(area), 255)
            cv2.fillPoly(layer, [pts_np], value)

        path = os.path.join(output_dir, "map_area_labels.pgm")
        Image.fromarray(layer).save(path)

    def _export_area_labels_json(self, output_dir):
        """导出区域标记JSON"""
        areas = []
        for area in self.annotations.area_labels:
            areas.append({
                "area_id": area_room_id(area),
                "room_id": area_room_id(area),
                "name": canonical_room_name(area_room_id(area)),
                "color": area.color,
                "polygon": area.polygon
            })

        data = {"areas": areas}
        path = os.path.join(output_dir, "areas.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _export_yaml(self, output_dir, yaml_filename, image_filename):
        """导出YAML元数据"""
        if not self.map_data.metadata:
            return

        meta = self.map_data.metadata
        free_thresh = meta.free_thresh
        if yaml_filename == "map_forbidden.yaml":
            # KeepoutFilter treats UNKNOWN mask cells as no-op. The white
            # background in map_forbidden.pgm must remain unknown so it does
            # not clear unknown cells from the base map.
            free_thresh = 0.0

        data = {
            "image": image_filename,
            "mode": meta.mode,
            "resolution": meta.resolution,
            "origin": list(meta.origin),
            "negate": meta.negate,
            "occupied_thresh": meta.occupied_thresh,
            "free_thresh": free_thresh
        }

        path = os.path.join(output_dir, yaml_filename)
        with open(path, 'w') as f:
            yaml.dump(data, f, sort_keys=False)
