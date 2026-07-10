from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Literal

import numpy as np

from ..models.annotations import Annotations, DerivedConstraintRegion
from .free_space_components import FreeSpaceComponentsResult, extract_component_bbox_mask

FreeSpaceRegionSource = Literal["free_component", "derived_region"]
FreeSpaceRegionSemantic = Literal["free", "forbidden_zone", "no_coverage"]


@dataclass(frozen=True)
class FreeSpaceRegionTarget:
    source: FreeSpaceRegionSource
    semantic: FreeSpaceRegionSemantic
    component_id: int
    component_key: str
    bbox_px: tuple[int, int, int, int]
    mask: np.ndarray
    area_m2: float
    repair_radius_m: float

    @property
    def pixel_count(self) -> int:
        return int(np.count_nonzero(self.mask))


def component_key_from_bbox_mask(bbox_px, component_mask=None) -> str:
    x, y, w, h = (int(value) for value in bbox_px)
    base = f"{x}:{y}:{w}:{h}"
    if component_mask is None:
        return base
    binary = (np.asarray(component_mask, dtype=np.uint8) > 0).astype(np.uint8)
    digest = hashlib.sha1(binary.tobytes()).hexdigest()[:12]
    return f"{base}:{digest}"


def component_object_id(prefix: str, component_key: str, *, fallback_component_id: int) -> str:
    normalized = "".join(ch if ch.isalnum() else "-" for ch in str(component_key or ""))
    normalized = normalized.strip("-")
    if not normalized:
        normalized = f"component-{int(fallback_component_id)}"
    return f"{prefix}-{normalized}"


def metadata_component_key(item) -> str:
    metadata = getattr(item, "metadata", {}) or {}
    if isinstance(metadata, dict):
        return str(metadata.get("component_key", "") or "")
    return ""


def truth_matches_target(item, target: FreeSpaceRegionTarget) -> bool:
    item_key = metadata_component_key(item)
    if not item_key and hasattr(item, "bbox_px"):
        item_key = component_key_from_bbox_mask(getattr(item, "bbox_px"))
    return bool(item_key) and item_key == target.component_key


def target_from_free_component(result: FreeSpaceComponentsResult | None, component_id: int) -> FreeSpaceRegionTarget | None:
    if result is None:
        return None
    extracted = extract_component_bbox_mask(result, int(component_id))
    stat = result.stat_for_label(int(component_id))
    if extracted is None or stat is None:
        return None
    bbox_px, mask = extracted
    component_key = component_key_from_bbox_mask(bbox_px, mask)
    return FreeSpaceRegionTarget(
        source="free_component",
        semantic="free",
        component_id=int(component_id),
        component_key=component_key,
        bbox_px=tuple(int(value) for value in bbox_px),
        mask=(np.asarray(mask, dtype=np.uint8) > 0).astype(np.uint8) * 255,
        area_m2=float(stat.area_m2),
        repair_radius_m=float(getattr(result, "repair_radius_m", 0.0)),
    )


def target_from_derived_region(annotations: Annotations, region: DerivedConstraintRegion) -> FreeSpaceRegionTarget | None:
    mask = annotations.decode_derived_constraint_region_mask(region)
    if mask.size <= 0:
        return None
    bbox_px = tuple(int(value) for value in region.bbox_px)
    component_key = metadata_component_key(region) or component_key_from_bbox_mask(bbox_px, mask)
    action_type = str(region.action_type)
    if action_type == "forbidden_zone":
        semantic: FreeSpaceRegionSemantic = "forbidden_zone"
    elif action_type == "no_coverage":
        semantic = "no_coverage"
    else:
        semantic = "free"
    return FreeSpaceRegionTarget(
        source="derived_region",
        semantic=semantic,
        component_id=int(region.component_id),
        component_key=component_key,
        bbox_px=bbox_px,
        mask=(np.asarray(mask, dtype=np.uint8) > 0).astype(np.uint8) * 255,
        area_m2=float(region.component_area_m2),
        repair_radius_m=float(region.repair_radius_m),
    )


def derived_region_from_target(
    annotations: Annotations,
    target: FreeSpaceRegionTarget,
    action_type: str,
    *,
    object_id: str,
    name: str,
) -> DerivedConstraintRegion:
    return DerivedConstraintRegion(
        id=object_id,
        name=name,
        action_type=str(action_type),
        source="free_space_component",
        component_id=int(target.component_id),
        bbox_px=tuple(int(value) for value in target.bbox_px),
        packed_mask_b64=annotations.encode_binary_mask_packbits(target.mask),
        repair_radius_m=float(target.repair_radius_m),
        component_area_m2=float(target.area_m2),
        metadata={
            "component_id": int(target.component_id),
            "component_key": str(target.component_key),
        },
    )
