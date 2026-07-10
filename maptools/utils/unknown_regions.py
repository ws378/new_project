from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import cv2
import numpy as np

from ..models.annotations import Annotations, DerivedConstraintRegion
from ..models.map_data import MapData
from .free_space_region_target import component_key_from_bbox_mask, component_object_id

UNKNOWN_REGION_SOURCE = "unknown_region"
DEFAULT_UNKNOWN_PIXEL_VALUE = 205


@dataclass(frozen=True)
class UnknownRegionStat:
    component_id: int
    pixel_count: int
    area_m2: float
    bbox_px: tuple[int, int, int, int]
    component_key: str


@dataclass(frozen=True)
class UnknownRegionsResult:
    unknown_mask: np.ndarray
    component_labels: np.ndarray
    component_stats: Dict[int, UnknownRegionStat]
    total_component_count: int
    total_pixel_count: int
    total_area_m2: float


def _extract_component_bbox_mask(
    labels: np.ndarray,
    component_id: int,
    bbox_px: tuple[int, int, int, int],
) -> np.ndarray:
    x, y, width, height = (int(value) for value in bbox_px)
    window = labels[y : y + height, x : x + width]
    return np.where(window == int(component_id), 255, 0).astype(np.uint8)


def analyze_unknown_regions(
    map_data: MapData,
    *,
    unknown_value: int = DEFAULT_UNKNOWN_PIXEL_VALUE,
) -> UnknownRegionsResult:
    if map_data.metadata is None or map_data.width <= 0 or map_data.height <= 0:
        raise ValueError("map data is not loaded")

    display = np.asarray(map_data.get_display_image(), dtype=np.uint8)
    unknown_mask = np.where(display == int(unknown_value), 255, 0).astype(np.uint8)
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats((unknown_mask > 0).astype(np.uint8), connectivity=8)

    component_stats: Dict[int, UnknownRegionStat] = {}
    area_per_pixel = float(map_data.metadata.resolution) ** 2
    total_pixels = 0
    for component_id in range(1, int(component_count)):
        x = int(stats[component_id, cv2.CC_STAT_LEFT])
        y = int(stats[component_id, cv2.CC_STAT_TOP])
        width = int(stats[component_id, cv2.CC_STAT_WIDTH])
        height = int(stats[component_id, cv2.CC_STAT_HEIGHT])
        pixel_count = int(stats[component_id, cv2.CC_STAT_AREA])
        bbox_px = (x, y, width, height)
        component_mask = _extract_component_bbox_mask(labels, component_id, bbox_px)
        component_key = component_key_from_bbox_mask(bbox_px, component_mask)
        total_pixels += pixel_count
        component_stats[component_id] = UnknownRegionStat(
            component_id=int(component_id),
            pixel_count=pixel_count,
            area_m2=pixel_count * area_per_pixel,
            bbox_px=bbox_px,
            component_key=component_key,
        )

    return UnknownRegionsResult(
        unknown_mask=unknown_mask,
        component_labels=labels,
        component_stats=component_stats,
        total_component_count=len(component_stats),
        total_pixel_count=total_pixels,
        total_area_m2=total_pixels * area_per_pixel,
    )


def build_unknown_forbidden_regions(
    annotations: Annotations,
    result: UnknownRegionsResult,
) -> list[DerivedConstraintRegion]:
    if result.total_pixel_count <= 0:
        return []
    ys, xs = np.nonzero(result.unknown_mask > 0)
    if xs.size == 0 or ys.size == 0:
        return []
    x0 = int(xs.min())
    y0 = int(ys.min())
    x1 = int(xs.max()) + 1
    y1 = int(ys.max()) + 1
    bbox_px = (x0, y0, x1 - x0, y1 - y0)
    mask = np.where(result.unknown_mask[y0:y1, x0:x1] > 0, 255, 0).astype(np.uint8)
    component_key = component_key_from_bbox_mask(bbox_px, mask)
    return [
        DerivedConstraintRegion(
            id=component_object_id(
                "unknown-forbidden",
                component_key,
                fallback_component_id=0,
            ),
            name="Unknown Areas Forbidden",
            action_type="forbidden_zone",
            source=UNKNOWN_REGION_SOURCE,
            component_id=0,
            bbox_px=tuple(int(value) for value in bbox_px),
            packed_mask_b64=annotations.encode_binary_mask_packbits(mask),
            repair_radius_m=0.0,
            component_area_m2=float(result.total_area_m2),
            metadata={
                "source": UNKNOWN_REGION_SOURCE,
                "component_id": 0,
                "component_key": str(component_key),
                "component_count": int(result.total_component_count),
                "pixel_value": DEFAULT_UNKNOWN_PIXEL_VALUE,
            },
        )
    ]


def is_unknown_region(region: DerivedConstraintRegion) -> bool:
    metadata = getattr(region, "metadata", {}) or {}
    metadata_source = str(metadata.get("source", "") or "") if isinstance(metadata, dict) else ""
    return str(getattr(region, "source", "") or "") == UNKNOWN_REGION_SOURCE or metadata_source == UNKNOWN_REGION_SOURCE


def compact_unknown_forbidden_regions(annotations: Annotations) -> int:
    unknown_regions = [
        region
        for region in annotations.iter_derived_constraint_regions("forbidden_zone")
        if is_unknown_region(region)
    ]
    if len(unknown_regions) <= 1:
        return 0

    x0 = min(int(region.bbox_px[0]) for region in unknown_regions)
    y0 = min(int(region.bbox_px[1]) for region in unknown_regions)
    x1 = max(int(region.bbox_px[0]) + int(region.bbox_px[2]) for region in unknown_regions)
    y1 = max(int(region.bbox_px[1]) + int(region.bbox_px[3]) for region in unknown_regions)
    width = x1 - x0
    height = y1 - y0
    if width <= 0 or height <= 0:
        return 0

    merged = np.zeros((height, width), dtype=np.uint8)
    total_area_m2 = 0.0
    for region in unknown_regions:
        rx, ry, rw, rh = (int(value) for value in region.bbox_px)
        if rw <= 0 or rh <= 0:
            continue
        mask = annotations.decode_derived_constraint_region_mask(region)
        if mask.size == 0:
            continue
        local_x0 = rx - x0
        local_y0 = ry - y0
        merged[local_y0 : local_y0 + rh, local_x0 : local_x0 + rw][mask > 0] = 255
        total_area_m2 += float(region.component_area_m2)

    if int(np.count_nonzero(merged)) <= 0:
        return 0

    bbox_px = (x0, y0, width, height)
    component_key = component_key_from_bbox_mask(bbox_px, merged)
    compacted = DerivedConstraintRegion(
        id=component_object_id("unknown-forbidden", component_key, fallback_component_id=0),
        name="Unknown Areas Forbidden",
        action_type="forbidden_zone",
        source=UNKNOWN_REGION_SOURCE,
        component_id=0,
        bbox_px=bbox_px,
        packed_mask_b64=annotations.encode_binary_mask_packbits(merged),
        repair_radius_m=0.0,
        component_area_m2=total_area_m2,
        metadata={
            "source": UNKNOWN_REGION_SOURCE,
            "component_id": 0,
            "component_key": str(component_key),
            "compacted_region_count": len(unknown_regions),
            "pixel_value": DEFAULT_UNKNOWN_PIXEL_VALUE,
        },
    )
    new_regions = [
        region
        for region in annotations.derived_constraint_regions
        if not (region.action_type == "forbidden_zone" and is_unknown_region(region))
    ]
    new_regions.append(compacted)
    annotations.set_derived_constraint_regions(new_regions)
    return len(unknown_regions) - 1
