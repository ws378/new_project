from dataclasses import dataclass, field
from typing import Any, List, Tuple, Dict
import json
import uuid
import math
import numpy as np
import base64
from maptools.utils.constraint_styles import constraint_base_color
from maptools.utils.room_identity import (
    canonical_room_name,
    normalize_and_validate_area_room_ids,
    normalize_area_room_identity,
    validate_room_id,
    validate_unique_area_room_ids,
)

AREA_LABEL_COLORS = [
    "#4CAF50",  # Green
    "#2196F3",  # Blue
    "#FF9800",  # Orange
    "#9C27B0",  # Purple
    "#00BCD4",  # Cyan
    "#E91E63",  # Pink
    "#8BC34A",  # Light Green
    "#FF5722",  # Deep Orange
    "#3F51B5",  # Indigo
    "#CDDC39",  # Lime
]

@dataclass
class AreaLabel:
    id: str
    area_id: int
    name: str
    polygon: List[Tuple[float, float]]
    color: str

    @property
    def room_id(self) -> int:
        return int(self.area_id)

    @room_id.setter
    def room_id(self, value: int) -> None:
        self.area_id = validate_room_id(value)
        self.name = canonical_room_name(self.area_id)

@dataclass
class ForbiddenZone:
    id: str
    name: str
    polygon: List[Tuple[float, float]]  # List of (x, y) world coordinates

@dataclass
class PassOnlyZone:
    id: str
    name: str
    polygon: List[Tuple[float, float]]  # List of (x, y) world coordinates

@dataclass
class VirtualWall:
    id: str
    name: str
    start: Tuple[float, float]
    end: Tuple[float, float]


@dataclass
class ConstraintSegment:
    id: str
    name: str
    points: List[Tuple[float, float]]
    closed: bool
    constraint_type: str
    color: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DerivedConstraintRegion:
    id: str
    name: str
    action_type: str
    source: str
    component_id: int
    bbox_px: Tuple[int, int, int, int]
    row_spans: List[List[int]] = field(default_factory=list)
    packed_mask_b64: str = ""
    repair_radius_m: float = 0.0
    component_area_m2: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Station:
    id: str
    name: str
    position: Tuple[float, float]
    orientation: float  # radians

class Annotations:
    """管理所有向量标注数据"""

    def __init__(self):
        self.forbidden_zones: List[ForbiddenZone] = []
        self.pass_only_zones: List[PassOnlyZone] = []
        self.virtual_walls: List[VirtualWall] = []
        self.stations: List[Station] = []
        self.area_labels: List[AreaLabel] = []
        self.constraint_segments: List[ConstraintSegment] = []
        self.derived_constraint_regions: List[DerivedConstraintRegion] = []
        self._next_area_id = 1
        self.version = "1.0"
        self.change_stamp = 0
        self.analysis_change_stamp = 0
        self._analysis_signature = self._analysis_signature_payload()

    def add_forbidden_zone(self, points: List[Tuple[float, float]], name="Forbidden Zone", item_id: str | None = None) -> ForbiddenZone:
        segment = self.add_constraint_segment(
            points,
            closed=True,
            constraint_type="forbidden_zone",
            name=name,
            item_id=item_id,
            color=constraint_base_color("forbidden_zone"),
        )
        return self._require_legacy_constraint(segment.id, self.forbidden_zones)

    def add_pass_only_zone(self, points: List[Tuple[float, float]], name="Pass Only Zone", item_id: str | None = None) -> PassOnlyZone:
        segment = self.add_constraint_segment(
            points,
            closed=True,
            constraint_type="pass_only",
            name=name,
            item_id=item_id,
            color=constraint_base_color("pass_only"),
        )
        return self._require_legacy_constraint(segment.id, self.pass_only_zones)

    def add_virtual_wall(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        name="Virtual Wall",
        item_id: str | None = None,
    ) -> VirtualWall:
        segment = self.add_constraint_segment(
            [start, end],
            closed=False,
            constraint_type="virtual_wall",
            name=name,
            item_id=item_id,
            color=constraint_base_color("virtual_wall"),
        )
        return self._require_legacy_constraint(segment.id, self.virtual_walls)

    def add_constraint_segment(
        self,
        points: List[Tuple[float, float]],
        *,
        closed: bool,
        constraint_type: str,
        name: str = "Constraint Segment",
        item_id: str | None = None,
        color: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> ConstraintSegment:
        item_id = item_id or str(uuid.uuid4())
        segment = ConstraintSegment(
            id=item_id,
            name=name,
            points=[tuple(point) for point in points],
            closed=bool(closed),
            constraint_type=str(constraint_type),
            color=color or self._default_constraint_color(str(constraint_type)),
            metadata=dict(metadata or {}),
        )
        self._upsert_constraint_segment(segment)
        self.sync_constraint_views()
        return segment

    def replace_constraint_segments(
        self,
        constraint_type: str,
        segments: List[ConstraintSegment],
    ) -> None:
        self.constraint_segments = [
            segment
            for segment in self.constraint_segments
            if segment.constraint_type != constraint_type
        ]
        self.constraint_segments.extend(
            ConstraintSegment(
                id=segment.id,
                name=segment.name,
                points=[tuple(point) for point in segment.points],
                closed=bool(segment.closed),
                constraint_type=str(segment.constraint_type),
                color=str(segment.color),
                metadata=dict(segment.metadata),
            )
            for segment in segments
        )
        self.sync_constraint_views()

    def add_area_label(self, points: List[Tuple[float, float]], name="Area", area_id=None) -> AreaLabel:
        if area_id is None:
            area_id = self._next_area_id
            self._next_area_id += 1
        else:
            area_id = validate_room_id(area_id)
            # Ensure counter stays ahead of manually assigned IDs
            if area_id >= self._next_area_id:
                self._next_area_id = area_id + 1
        color = AREA_LABEL_COLORS[(area_id - 1) % len(AREA_LABEL_COLORS)]
        validate_unique_area_room_ids(self.area_labels)
        if any(int(area.area_id) == int(area_id) for area in self.area_labels):
            raise ValueError(f"duplicate room_id: {area_id}")
        label = AreaLabel(
            id=str(uuid.uuid4()),
            area_id=area_id,
            name=canonical_room_name(area_id),
            polygon=points,
            color=color
        )
        self.area_labels.append(label)
        self.change_stamp += 1
        return label

    def add_station(self, position: Tuple[float, float], orientation: float, name="Station") -> Station:
        station = Station(
            id=str(uuid.uuid4()),
            name=name,
            position=position,
            orientation=orientation
        )
        self.stations.append(station)
        self.change_stamp += 1
        return station

    def remove_by_id(self, item_id: str):
        self.forbidden_zones = [z for z in self.forbidden_zones if z.id != item_id]
        self.pass_only_zones = [z for z in self.pass_only_zones if z.id != item_id]
        self.virtual_walls = [w for w in self.virtual_walls if w.id != item_id]
        self.stations = [s for s in self.stations if s.id != item_id]
        self.area_labels = [a for a in self.area_labels if a.id != item_id]
        self.constraint_segments = [segment for segment in self.constraint_segments if segment.id != item_id]
        self.derived_constraint_regions = [region for region in self.derived_constraint_regions if region.id != item_id]
        self.sync_constraint_views()

    def restore_item(self, item_type: str, item) -> None:
        if item_type == 'forbidden_zones':
            self.add_constraint_segment(
                item.polygon,
                closed=True,
                constraint_type="forbidden_zone",
                name=item.name,
                item_id=item.id,
                color=constraint_base_color("forbidden_zone"),
            )
            return
        if item_type == 'pass_only_zones':
            self.add_constraint_segment(
                item.polygon,
                closed=True,
                constraint_type="pass_only",
                name=item.name,
                item_id=item.id,
                color=constraint_base_color("pass_only"),
            )
            return
        if item_type == 'virtual_walls':
            self.add_constraint_segment(
                [item.start, item.end],
                closed=False,
                constraint_type="virtual_wall",
                name=item.name,
                item_id=item.id,
                color=constraint_base_color("virtual_wall"),
            )
            return
        if item_type == 'constraint_segments':
            self._upsert_constraint_segment(item)
            self.sync_constraint_views()
            return
        if item_type == 'stations':
            self.stations.append(item)
            self.change_stamp += 1
            return
        if item_type == 'area_labels':
            normalize_area_room_identity(item)
            validate_unique_area_room_ids(self.area_labels, exclude_area_id=getattr(item, "id", None))
            self.area_labels.append(item)
            self.change_stamp += 1
            return

    def to_dict(self):
        normalize_and_validate_area_room_ids(self.area_labels)
        return {
            "version": self.version,
            "constraint_segments": [
                {
                    "id": segment.id,
                    "name": segment.name,
                    "points": segment.points,
                    "closed": segment.closed,
                    "constraint_type": segment.constraint_type,
                    "color": segment.color,
                    "metadata": segment.metadata,
                }
                for segment in self.constraint_segments
            ],
            "derived_constraint_regions": [
                {
                    "id": region.id,
                    "name": region.name,
                    "action_type": region.action_type,
                    "source": region.source,
                    "component_id": int(region.component_id),
                    "bbox_px": list(region.bbox_px),
                    "row_spans": region.row_spans,
                    "packed_mask_b64": region.packed_mask_b64,
                    "repair_radius_m": float(region.repair_radius_m),
                    "component_area_m2": float(region.component_area_m2),
                    "metadata": region.metadata,
                }
                for region in self.derived_constraint_regions
            ],
            "stations": [
                {"id": s.id, "name": s.name, "position": s.position, "orientation": s.orientation}
                for s in self.stations
            ],
            "area_labels": [
                {"id": a.id, "area_id": a.area_id, "room_id": a.area_id, "name": canonical_room_name(a.area_id), "polygon": a.polygon, "color": a.color}
                for a in self.area_labels
            ],
            "_next_area_id": self._next_area_id
        }

    def save(self, path: str):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def load(self, path: str):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.constraint_segments = []
        for segment in data.get("constraint_segments", []):
            self.constraint_segments.append(
                ConstraintSegment(
                    id=segment["id"],
                    name=segment.get("name", "Constraint Segment"),
                    points=[tuple(point) for point in segment.get("points", [])],
                    closed=bool(segment.get("closed", False)),
                    constraint_type=str(segment.get("constraint_type", "")),
                    color=str(segment.get("color", "")),
                    metadata=dict(segment.get("metadata", {}) or {}),
                )
            )

        if not self.constraint_segments:
            self._migrate_constraint_segments_from_legacy_dict(data)

        self.derived_constraint_regions = []
        for region in data.get("derived_constraint_regions", []):
            self.derived_constraint_regions.append(
                DerivedConstraintRegion(
                    id=region["id"],
                    name=region.get("name", "Derived Constraint Region"),
                    action_type=str(region.get("action_type", "")),
                    source=str(region.get("source", "")),
                    component_id=int(region.get("component_id", 0)),
                    bbox_px=tuple(int(v) for v in region.get("bbox_px", [0, 0, 0, 0])),
                    row_spans=[[int(value) for value in row] for row in region.get("row_spans", [])],
                    packed_mask_b64=str(region.get("packed_mask_b64", "") or ""),
                    repair_radius_m=float(region.get("repair_radius_m", 0.0)),
                    component_area_m2=float(region.get("component_area_m2", 0.0)),
                    metadata=dict(region.get("metadata", {}) or {}),
                )
            )

        self.sync_constraint_views()

        self.stations = []
        for s in data.get("stations", []):
            self.stations.append(Station(s["id"], s["name"], tuple(s["position"]), s["orientation"]))

        self.area_labels = []
        for a in data.get("area_labels", []):
            room_id = validate_room_id(a.get("room_id", a.get("area_id")))
            self.area_labels.append(AreaLabel(
                a["id"], room_id, canonical_room_name(room_id),
                [tuple(p) for p in a["polygon"]], a["color"]
            ))
        normalize_and_validate_area_room_ids(self.area_labels)
        saved_next = data.get("_next_area_id", 1)
        max_existing = max((a.area_id for a in self.area_labels), default=0)
        self._next_area_id = max(saved_next, max_existing + 1)
        self.change_stamp += 1
        self._update_analysis_change_stamp()

    def rotate(self, angle_deg: float, center_wx: float, center_wy: float):
        """
        围绕指定的世界坐标中心旋转所有标注
        :param angle_deg: 旋转角度 (逆时针为正)
        :param center_wx: 旋转中心 X (世界坐标)
        :param center_wy: 旋转中心 Y (世界坐标)
        """
        rad = math.radians(angle_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        def transform_point(x, y):
            dx = x - center_wx
            dy = y - center_wy
            nx = dx * cos_a - dy * sin_a + center_wx
            ny = dx * sin_a + dy * cos_a + center_wy
            return nx, ny

        # 1. 旋转约束分段
        for segment in self.constraint_segments:
            segment.points = [transform_point(px, py) for px, py in segment.points]
        self.derived_constraint_regions = []
        self.sync_constraint_views()

        # 2. 旋转基站
        for station in self.stations:
            np = transform_point(*station.position)
            station.position = np
            # 方向也需要旋转
            station.orientation += rad

        # 3. 旋转区域标记
        for area in self.area_labels:
            new_poly = []
            for px, py in area.polygon:
                new_poly.append(transform_point(px, py))
            area.polygon = new_poly
        self.change_stamp += 1

    def crop_to_bounds(self, min_x: float, max_x: float, min_y: float, max_y: float):
        """将标注裁剪到给定世界坐标包围盒内。"""
        self.constraint_segments = self._clip_constraint_segments(self.constraint_segments, min_x, max_x, min_y, max_y)
        self.derived_constraint_regions = []
        self.sync_constraint_views()
        self.area_labels = self._clip_polygon_items(self.area_labels, min_x, max_x, min_y, max_y)
        self.stations = [
            station for station in self.stations
            if self._point_in_rect(station.position[0], station.position[1], min_x, max_x, min_y, max_y)
        ]
        self.change_stamp += 1

    def _upsert_constraint_segment(self, segment: ConstraintSegment) -> None:
        self.constraint_segments = [item for item in self.constraint_segments if item.id != segment.id]
        self.constraint_segments.append(segment)

    @staticmethod
    def _require_legacy_constraint(item_id: str, items):
        for item in items:
            if item.id == item_id:
                return item
        raise ValueError(f"legacy constraint view missing for id={item_id}")

    def sync_constraint_views(self) -> None:
        self._rebuild_legacy_constraints_from_segments()
        self.change_stamp += 1
        self._update_analysis_change_stamp()

    def set_derived_constraint_regions(self, regions: List[DerivedConstraintRegion]) -> None:
        self.derived_constraint_regions = [
            DerivedConstraintRegion(
                id=region.id,
                name=region.name,
                action_type=region.action_type,
                source=region.source,
                component_id=int(region.component_id),
                bbox_px=tuple(int(v) for v in region.bbox_px),
                row_spans=[[int(value) for value in row] for row in region.row_spans],
                packed_mask_b64=str(region.packed_mask_b64 or ""),
                repair_radius_m=float(region.repair_radius_m),
                component_area_m2=float(region.component_area_m2),
                metadata=dict(region.metadata),
            )
            for region in regions
        ]
        self.change_stamp += 1
        self._update_analysis_change_stamp()

    def iter_derived_constraint_regions(self, action_type: str | None = None):
        for region in self.derived_constraint_regions:
            if action_type is not None and region.action_type != action_type:
                continue
            yield region

    @staticmethod
    def encode_binary_mask_rows(mask: np.ndarray) -> List[List[int]]:
        binary = np.asarray(mask, dtype=np.uint8)
        if binary.ndim != 2:
            raise ValueError("mask must be a 2D array")
        rows: List[List[int]] = []
        for row in binary:
            spans: List[int] = []
            x = 0
            width = int(row.shape[0])
            while x < width:
                if int(row[x]) > 0:
                    start = x
                    while x < width and int(row[x]) > 0:
                        x += 1
                    spans.extend([start, x - start])
                else:
                    x += 1
            rows.append(spans)
        return rows

    @staticmethod
    def encode_binary_mask_packbits(mask: np.ndarray) -> str:
        binary = (np.asarray(mask, dtype=np.uint8) > 0).astype(np.uint8)
        if binary.ndim != 2:
            raise ValueError("mask must be a 2D array")
        packed = np.packbits(binary, axis=1)
        return base64.b64encode(packed.tobytes()).decode("ascii")

    @staticmethod
    def decode_binary_mask_packbits(width: int, height: int, packed_mask_b64: str) -> np.ndarray:
        if not packed_mask_b64:
            return np.zeros((int(height), int(width)), dtype=np.uint8)
        packed_bytes = base64.b64decode(packed_mask_b64.encode("ascii"))
        row_bytes = (int(width) + 7) // 8
        packed = np.frombuffer(packed_bytes, dtype=np.uint8).reshape((int(height), row_bytes))
        unpacked = np.unpackbits(packed, axis=1)[:, : int(width)]
        return (unpacked.astype(np.uint8) * 255)

    @staticmethod
    def decode_binary_mask_rows(width: int, height: int, row_spans: List[List[int]]) -> np.ndarray:
        mask = np.zeros((int(height), int(width)), dtype=np.uint8)
        for y, spans in enumerate(row_spans[: int(height)]):
            for idx in range(0, len(spans), 2):
                start = int(spans[idx])
                length = int(spans[idx + 1]) if idx + 1 < len(spans) else 0
                if length <= 0:
                    continue
                end = min(int(width), start + length)
                if end > start:
                    mask[y, start:end] = 255
        return mask

    def decode_derived_constraint_region_mask(self, region: DerivedConstraintRegion) -> np.ndarray:
        _, _, width, height = region.bbox_px
        if region.packed_mask_b64:
            return self.decode_binary_mask_packbits(int(width), int(height), region.packed_mask_b64)
        return self.decode_binary_mask_rows(int(width), int(height), region.row_spans)

    def iter_constraint_segments(self, constraint_type: str, *, closed: bool | None = None):
        for segment in self.constraint_segments:
            if segment.constraint_type != constraint_type:
                continue
            if closed is not None and bool(segment.closed) != bool(closed):
                continue
            yield segment

    @staticmethod
    def _default_constraint_color(constraint_type: str) -> str:
        return constraint_base_color(constraint_type)

    def _rebuild_legacy_constraints_from_segments(self) -> None:
        forbidden_by_id = {item.id: item for item in self.forbidden_zones}
        pass_only_by_id = {item.id: item for item in self.pass_only_zones}
        virtual_by_id = {item.id: item for item in self.virtual_walls}
        forbidden = []
        pass_only = []
        virtual_walls = []
        for segment in self.constraint_segments:
            if segment.constraint_type == "forbidden_zone" and segment.closed and len(segment.points) >= 3:
                item = forbidden_by_id.get(segment.id)
                if item is None:
                    item = ForbiddenZone(segment.id, segment.name, [tuple(point) for point in segment.points])
                else:
                    item.name = segment.name
                    item.polygon = [tuple(point) for point in segment.points]
                forbidden.append(item)
            elif segment.constraint_type == "pass_only" and segment.closed and len(segment.points) >= 3:
                item = pass_only_by_id.get(segment.id)
                if item is None:
                    item = PassOnlyZone(segment.id, segment.name, [tuple(point) for point in segment.points])
                else:
                    item.name = segment.name
                    item.polygon = [tuple(point) for point in segment.points]
                pass_only.append(item)
            elif segment.constraint_type == "virtual_wall" and not segment.closed and len(segment.points) >= 2:
                item = virtual_by_id.get(segment.id)
                if item is None:
                    item = VirtualWall(segment.id, segment.name, tuple(segment.points[0]), tuple(segment.points[-1]))
                else:
                    item.name = segment.name
                    item.start = tuple(segment.points[0])
                    item.end = tuple(segment.points[-1])
                virtual_walls.append(item)
        self.forbidden_zones = forbidden
        self.pass_only_zones = pass_only
        self.virtual_walls = virtual_walls

    def _migrate_constraint_segments_from_legacy_dict(self, data: Dict[str, Any]) -> None:
        segments = []
        for item in data.get("forbidden_zones", []):
            segments.append(
                ConstraintSegment(
                    id=item["id"],
                    name=item["name"],
                    points=[tuple(point) for point in item["polygon"]],
                    closed=True,
                    constraint_type="forbidden_zone",
                    color=self._default_constraint_color("forbidden_zone"),
                )
            )
        for item in data.get("pass_only_zones", []):
            segments.append(
                ConstraintSegment(
                    id=item["id"],
                    name=item["name"],
                    points=[tuple(point) for point in item["polygon"]],
                    closed=True,
                    constraint_type="pass_only",
                    color=self._default_constraint_color("pass_only"),
                )
            )
        for item in data.get("virtual_walls", []):
            segments.append(
                ConstraintSegment(
                    id=item["id"],
                    name=item["name"],
                    points=[tuple(item["start"]), tuple(item["end"])],
                    closed=False,
                    constraint_type="virtual_wall",
                    color=self._default_constraint_color("virtual_wall"),
                )
            )
        self.constraint_segments = segments

    def _analysis_signature_payload(self):
        segment_payload = []
        for segment in self.constraint_segments:
            if segment.constraint_type not in {"forbidden_zone", "virtual_wall"}:
                continue
            segment_payload.append(
                (
                    segment.id,
                    segment.constraint_type,
                    bool(segment.closed),
                    tuple((round(float(x), 6), round(float(y), 6)) for x, y in segment.points),
                )
            )
        derived_payload = []
        for region in self.derived_constraint_regions:
            if region.action_type not in {"forbidden_zone"}:
                continue
            derived_payload.append(
                (
                    region.id,
                    region.action_type,
                    int(region.component_id),
                    tuple(int(v) for v in region.bbox_px),
                    tuple(tuple(int(value) for value in row) for row in region.row_spans),
                )
            )
        return (tuple(segment_payload), tuple(derived_payload))

    def _update_analysis_change_stamp(self) -> None:
        signature = self._analysis_signature_payload()
        if signature != self._analysis_signature:
            self._analysis_signature = signature
            self.analysis_change_stamp += 1

    @staticmethod
    def _clip_polygon_items(items, min_x, max_x, min_y, max_y):
        kept = []
        for item in items:
            clipped = Annotations._clip_polygon_to_rect(item.polygon, min_x, max_x, min_y, max_y)
            if len(clipped) >= 3 and Annotations._polygon_area(clipped) > 1e-9:
                item.polygon = clipped
                kept.append(item)
        return kept

    @staticmethod
    def _clip_line_items(items, min_x, max_x, min_y, max_y):
        kept = []
        for item in items:
            clipped = Annotations._clip_line_to_rect(item.start, item.end, min_x, max_x, min_y, max_y)
            if clipped is not None:
                item.start, item.end = clipped
                kept.append(item)
        return kept

    @staticmethod
    def _clip_constraint_segments(items, min_x, max_x, min_y, max_y):
        kept = []
        for item in items:
            if item.closed:
                clipped = Annotations._clip_polygon_to_rect(item.points, min_x, max_x, min_y, max_y)
                if len(clipped) >= 3 and Annotations._polygon_area(clipped) > 1e-9:
                    item.points = clipped
                    kept.append(item)
            else:
                if len(item.points) < 2:
                    continue
                clipped = Annotations._clip_line_to_rect(item.points[0], item.points[-1], min_x, max_x, min_y, max_y)
                if clipped is not None:
                    item.points = [tuple(clipped[0]), tuple(clipped[1])]
                    kept.append(item)
        return kept

    @staticmethod
    def _point_in_rect(x, y, min_x, max_x, min_y, max_y):
        eps = 1e-9
        return (min_x - eps) <= x <= (max_x + eps) and (min_y - eps) <= y <= (max_y + eps)

    @staticmethod
    def _polygon_area(points):
        area = 0.0
        for i, (x1, y1) in enumerate(points):
            x2, y2 = points[(i + 1) % len(points)]
            area += x1 * y2 - x2 * y1
        return abs(area) * 0.5

    @staticmethod
    def _dedupe_polygon(points):
        deduped = []
        for point in points:
            if not deduped or abs(point[0] - deduped[-1][0]) > 1e-9 or abs(point[1] - deduped[-1][1]) > 1e-9:
                deduped.append(point)
        if len(deduped) >= 2 and abs(deduped[0][0] - deduped[-1][0]) <= 1e-9 and abs(deduped[0][1] - deduped[-1][1]) <= 1e-9:
            deduped.pop()
        return deduped

    @staticmethod
    def _clip_polygon_to_rect(points, min_x, max_x, min_y, max_y):
        def clip_edge(poly, inside_fn, intersect_fn):
            if not poly:
                return []

            clipped = []
            prev = poly[-1]
            prev_inside = inside_fn(prev)
            for curr in poly:
                curr_inside = inside_fn(curr)
                if curr_inside:
                    if not prev_inside:
                        clipped.append(intersect_fn(prev, curr))
                    clipped.append(curr)
                elif prev_inside:
                    clipped.append(intersect_fn(prev, curr))
                prev = curr
                prev_inside = curr_inside
            return clipped

        def intersect_vertical(p1, p2, x_edge):
            x1, y1 = p1
            x2, y2 = p2
            if abs(x2 - x1) <= 1e-12:
                return (x_edge, y1)
            t = (x_edge - x1) / (x2 - x1)
            return (x_edge, y1 + t * (y2 - y1))

        def intersect_horizontal(p1, p2, y_edge):
            x1, y1 = p1
            x2, y2 = p2
            if abs(y2 - y1) <= 1e-12:
                return (x1, y_edge)
            t = (y_edge - y1) / (y2 - y1)
            return (x1 + t * (x2 - x1), y_edge)

        clipped = list(points)
        clipped = clip_edge(clipped, lambda p: p[0] >= min_x, lambda p1, p2: intersect_vertical(p1, p2, min_x))
        clipped = clip_edge(clipped, lambda p: p[0] <= max_x, lambda p1, p2: intersect_vertical(p1, p2, max_x))
        clipped = clip_edge(clipped, lambda p: p[1] >= min_y, lambda p1, p2: intersect_horizontal(p1, p2, min_y))
        clipped = clip_edge(clipped, lambda p: p[1] <= max_y, lambda p1, p2: intersect_horizontal(p1, p2, max_y))
        return Annotations._dedupe_polygon(clipped)

    @staticmethod
    def _clip_line_to_rect(start, end, min_x, max_x, min_y, max_y):
        INSIDE = 0
        LEFT = 1
        RIGHT = 2
        BOTTOM = 4
        TOP = 8

        def code(x, y):
            out = INSIDE
            if x < min_x:
                out |= LEFT
            elif x > max_x:
                out |= RIGHT
            if y < min_y:
                out |= BOTTOM
            elif y > max_y:
                out |= TOP
            return out

        x1, y1 = start
        x2, y2 = end
        code1 = code(x1, y1)
        code2 = code(x2, y2)

        while True:
            if not (code1 | code2):
                return (x1, y1), (x2, y2)
            if code1 & code2:
                return None

            out = code1 or code2
            if out & TOP:
                x = x1 + (x2 - x1) * (max_y - y1) / (y2 - y1)
                y = max_y
            elif out & BOTTOM:
                x = x1 + (x2 - x1) * (min_y - y1) / (y2 - y1)
                y = min_y
            elif out & RIGHT:
                y = y1 + (y2 - y1) * (max_x - x1) / (x2 - x1)
                x = max_x
            else:
                y = y1 + (y2 - y1) * (min_x - x1) / (x2 - x1)
                x = min_x

            if out == code1:
                x1, y1 = x, y
                code1 = code(x1, y1)
            else:
                x2, y2 = x, y
                code2 = code(x2, y2)
