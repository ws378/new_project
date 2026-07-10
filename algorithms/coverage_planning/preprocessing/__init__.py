"""Shared preprocessing helpers for stage-2 coverage-planning inputs."""

from .common import (
    apply_region_constraint,
    build_region_mask_from_polygon,
    derive_min_free_component_area_m2,
    derive_min_free_component_area_px,
    nearest_free_pixel,
    preprocess_total_map,
    resolve_request_starting_position,
    resolve_request_region_mask,
)

__all__ = [
    "apply_region_constraint",
    "build_region_mask_from_polygon",
    "derive_min_free_component_area_m2",
    "derive_min_free_component_area_px",
    "nearest_free_pixel",
    "preprocess_total_map",
    "resolve_request_starting_position",
    "resolve_request_region_mask",
]
