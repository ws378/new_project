from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from ..contracts import CoveragePlanningRequest


def to_uint8_mask(mask: np.ndarray) -> np.ndarray:
    """Normalize any truthy mask into a strict 0/255 uint8 mask."""

    if mask.dtype == np.bool_:
        return np.where(mask, 255, 0).astype(np.uint8)
    if mask.dtype == np.uint8:
        return np.where(mask > 0, 255, 0).astype(np.uint8)
    return np.where(np.asarray(mask).astype(np.int32) > 0, 255, 0).astype(np.uint8)


def derive_open_kernel_px(*, open_kernel_m: float, resolution_m_per_px: float) -> int:
    """Convert the shared morphology scale to pixels."""

    if resolution_m_per_px <= 0.0:
        raise ValueError("resolution_m_per_px must be positive")
    return max(1, int(round(float(open_kernel_m) / float(resolution_m_per_px))))


def morphology_open(mask: np.ndarray, *, kernel_px: int) -> np.ndarray:
    """Run the shared morphology-open step on a binary free-space mask."""

    if kernel_px <= 1:
        return to_uint8_mask(mask)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (int(kernel_px), int(kernel_px)))
    opened = cv2.morphologyEx(to_uint8_mask(mask), cv2.MORPH_OPEN, kernel)
    return to_uint8_mask(opened)


def morphology_erode(mask: np.ndarray, *, kernel_px: int) -> np.ndarray:
    """Run one shared free-space erosion step, equivalent to obstacle dilation."""

    if kernel_px <= 1:
        return to_uint8_mask(mask)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (int(kernel_px), int(kernel_px)))
    eroded = cv2.erode(to_uint8_mask(mask), kernel, iterations=1)
    return to_uint8_mask(eroded)


def remove_small_free_islands(mask: np.ndarray, *, min_area_px: int) -> np.ndarray:
    """Drop tiny connected free-space components from a binary mask."""

    normalized = to_uint8_mask(mask)
    if min_area_px <= 1:
        return normalized
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(normalized, 8)
    cleaned = np.zeros_like(normalized, dtype=np.uint8)
    for label in range(1, num_labels):
        area_px = int(stats[label, cv2.CC_STAT_AREA])
        if area_px < min_area_px:
            continue
        cleaned[labels == label] = 255
    return cleaned


def derive_min_free_component_area_m2(open_kernel_m: float) -> float:
    """Return the unified free-island cleanup threshold in square meters."""

    kernel_m = max(0.0, float(open_kernel_m))
    return float(4.0 * kernel_m * kernel_m)


def derive_min_free_component_area_px(*, open_kernel_m: float, resolution_m_per_px: float) -> int:
    """Convert the stage-2 area rule into a connected-component pixel threshold."""

    if resolution_m_per_px <= 0.0:
        raise ValueError("resolution_m_per_px must be positive")
    area_m2 = derive_min_free_component_area_m2(open_kernel_m)
    if area_m2 <= 0.0:
        return 1
    return max(1, int(math.ceil(area_m2 / float(resolution_m_per_px * resolution_m_per_px))))


def build_region_mask_from_polygon(
    *,
    shape: tuple[int, int],
    polygon_px: tuple[tuple[int, int], ...] | list[tuple[int, int]] | None,
) -> np.ndarray | None:
    """Rasterize a polygon into a full-image region mask."""

    if not polygon_px:
        return None
    region_mask = np.zeros(shape, dtype=np.uint8)
    points = np.asarray(tuple(polygon_px), dtype=np.int32)
    cv2.fillPoly(region_mask, [points], 255)
    return region_mask


def resolve_request_region_mask(request: CoveragePlanningRequest) -> np.ndarray | None:
    """Resolve region truth from request mask first, then polygon fallback."""

    if request.region_mask is not None:
        return np.where(np.asarray(request.region_mask) > 0, 255, 0).astype(np.uint8)
    return build_region_mask_from_polygon(
        shape=np.asarray(request.prepared_map).shape[:2],
        polygon_px=request.region_polygon_px,
    )


def apply_region_constraint(prepared_map: np.ndarray, region_mask: np.ndarray | None) -> np.ndarray:
    """Restrict the prepared map to the requested planning region."""

    prepared = np.where(np.asarray(prepared_map) > 0, 255, 0).astype(np.uint8)
    if region_mask is None:
        return prepared
    return np.where((prepared > 0) & (np.asarray(region_mask) > 0), 255, 0).astype(np.uint8)


def nearest_free_pixel(mask: np.ndarray, preferred_xy: tuple[int, int]) -> tuple[int, int] | None:
    """Return the nearest free pixel to ``preferred_xy`` in image ``(x, y)`` coordinates."""

    free = np.asarray(mask) > 0
    if not np.any(free):
        return None
    x = int(round(float(preferred_xy[0])))
    y = int(round(float(preferred_xy[1])))
    height, width = free.shape[:2]
    if 0 <= x < width and 0 <= y < height and bool(free[y, x]):
        return x, y
    rows, cols = np.where(free)
    distances = (cols.astype(np.int64) - int(x)) ** 2 + (rows.astype(np.int64) - int(y)) ** 2
    nearest_index = int(np.argmin(distances))
    return int(cols[nearest_index]), int(rows[nearest_index])


def resolve_request_starting_position(
    request: CoveragePlanningRequest,
    effective_map: np.ndarray | None = None,
) -> tuple[tuple[int, int] | None, bool]:
    """Snap the requested start to the nearest free pixel in the effective planning mask."""

    mask = (
        np.asarray(effective_map)
        if effective_map is not None
        else apply_region_constraint(request.prepared_map, resolve_request_region_mask(request))
    )
    original = (int(request.starting_position_px[0]), int(request.starting_position_px[1]))
    snapped = nearest_free_pixel(mask, original)
    return snapped, snapped is not None and snapped != original


def _write_prepare_map_stage_images(
    *,
    output_root: str | Path | None,
    raw_map: np.ndarray,
    free_mask: np.ndarray,
    after_open: np.ndarray,
    after_obstacle_expand: np.ndarray,
    prepared_map: np.ndarray,
) -> None:
    """Persist preprocessing stage images under `<output_root>/prepare_map/`."""

    if output_root is None:
        return
    output_dir = Path(output_root).expanduser()
    prepare_map_dir = output_dir / "prepare_map"
    prepare_map_dir.mkdir(parents=True, exist_ok=True)
    stage_images = {
        "01_raw_map.png": to_uint8_mask(np.asarray(raw_map)),
        "02_free_mask.png": to_uint8_mask(np.asarray(free_mask)),
        "03_after_open.png": to_uint8_mask(np.asarray(after_open)),
        "04_after_obstacle_expand.png": to_uint8_mask(np.asarray(after_obstacle_expand)),
        "05_prepared_map.png": to_uint8_mask(np.asarray(prepared_map)),
    }
    for filename, image in stage_images.items():
        cv2.imwrite(str(prepare_map_dir / filename), image)


def preprocess_total_map(
    *,
    raw_map: np.ndarray,
    resolution_m_per_px: float,
    open_kernel_m: float,
    obstacle_expand_m: float,
    region_mask: np.ndarray | None = None,
    output_root: str | Path | None = None,
) -> np.ndarray:
    """Apply the shared stage-2 total-map preprocessing rule.

    The rule intentionally follows the current CTG morphology strategy:
    1. optionally restrict raw free space to the selected planning region
    2. normalize to strict 0/255 free-space truth
    3. run morphology open using ``open_kernel_m``
    4. run one shared obstacle-expansion step using ``obstacle_expand_m``
    5. remove tiny free-space islands using ``4 * open_kernel_m^2``
    """

    constrained_raw_map = apply_region_constraint(np.asarray(raw_map), region_mask)
    free_mask = to_uint8_mask(constrained_raw_map)
    kernel_px = derive_open_kernel_px(
        open_kernel_m=float(open_kernel_m),
        resolution_m_per_px=float(resolution_m_per_px),
    )
    after_open = morphology_open(
        mask=free_mask,
        kernel_px=kernel_px,
    )
    after_obstacle_expand = morphology_erode(
        mask=after_open,
        kernel_px=derive_open_kernel_px(
            open_kernel_m=float(obstacle_expand_m),
            resolution_m_per_px=float(resolution_m_per_px),
        ),
    )
    min_area_px = derive_min_free_component_area_px(
        open_kernel_m=float(open_kernel_m),
        resolution_m_per_px=float(resolution_m_per_px),
    )
    prepared_map = remove_small_free_islands(after_obstacle_expand, min_area_px=min_area_px)
    # Re-apply region mask after morphological ops to prevent free-space bleed
    if region_mask is not None:
        prepared_map = apply_region_constraint(prepared_map, region_mask)
    _write_prepare_map_stage_images(
        output_root=output_root,
        raw_map=constrained_raw_map,
        free_mask=free_mask,
        after_open=after_open,
        after_obstacle_expand=after_obstacle_expand,
        prepared_map=prepared_map,
    )
    return prepared_map
