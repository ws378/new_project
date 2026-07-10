from __future__ import annotations

import numpy as np

from ...contracts import ApplicabilityResult, CoveragePlanningRequest
from ...preprocessing import apply_region_constraint, resolve_request_region_mask
from .metrics import compute_applicability_metrics


def _free_bbox_aspect(room_map: np.ndarray) -> float:
    free_mask = np.asarray(room_map) > 0
    if not np.any(free_mask):
        return 0.0
    rows, cols = np.where(free_mask)
    height = int(rows.max() - rows.min() + 1)
    width = int(cols.max() - cols.min() + 1)
    return float(max(width, height)) / float(max(1, min(width, height)))


def classify_applicability(request: CoveragePlanningRequest) -> ApplicabilityResult:
    """Classify the scene conservatively before routing to a planner."""

    effective_map = apply_region_constraint(
        request.prepared_map,
        resolve_request_region_mask(request),
    )
    metrics = compute_applicability_metrics(effective_map)
    if metrics.free_area_pixel_count <= 0:
        return ApplicabilityResult(
            scene_type="invalid",
            recommended_planner="",
            reasons=("no_free_space",),
            warnings=("coverage planning skipped because free space is empty",),
            metrics=metrics,
        )

    aspect_ratio = _free_bbox_aspect(effective_map)
    if aspect_ratio >= 4.0:
        if bool(getattr(request.private_config, "enable_channel_topology_graph", False)):
            return ApplicabilityResult(
                scene_type="aisle_like",
                recommended_planner="channel_topology_graph",
                fallback_chain=("shelf_aware", "region_basic"),
                reasons=("free_space_bbox_is_long_and_narrow", "explicit_channel_topology_graph_enabled"),
                metrics=metrics,
            )
        return ApplicabilityResult(
            scene_type="aisle_like",
            recommended_planner="shelf_aware",
            fallback_chain=("region_basic",),
            reasons=("free_space_bbox_is_long_and_narrow",),
            warnings=(
                "channel_topology_graph requires explicit enable_channel_topology_graph; using shelf_aware",
            ),
            metrics=metrics,
        )

    if aspect_ratio >= 2.4 or metrics.mixed_scene_score >= 0.75:
        return ApplicabilityResult(
            scene_type="mixed",
            recommended_planner="shelf_aware",
            fallback_chain=("region_basic",),
            reasons=("scene_has_mixed_or_directional_shape_proxy",),
            warnings=("mixed scene routing is conservative and does not perform room segmentation",),
            metrics=metrics,
        )

    return ApplicabilityResult(
        scene_type="room_like",
        recommended_planner="region_basic",
        fallback_chain=("shelf_aware",),
        reasons=("free_space_bbox_is_not_strongly_channel_like",),
        metrics=metrics,
    )
