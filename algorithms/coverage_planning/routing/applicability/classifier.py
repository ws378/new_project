from __future__ import annotations

from ...contracts import ApplicabilityResult, CoveragePlanningRequest
from ...preprocessing import apply_region_constraint, resolve_request_region_mask
from .metrics import compute_applicability_metrics

OBSTACLE_COMPLEX_THRESHOLD = 20


def classify_applicability(request: CoveragePlanningRequest) -> ApplicabilityResult:
    """Classify the scene before routing to a planner.

    Three-tier routing (distances in meters):
      1. oc ≤ 5 + mean clearance ≥ 0.3m                    → cstar_rect
      2. oc ≤ 20                                           → cstar_tsp
      3. oc > 20                                           → basic_improved
    """

    effective_map = apply_region_constraint(
        request.prepared_map,
        resolve_request_region_mask(request),
    )
    res = float(request.map_resolution)
    try:
        metrics = compute_applicability_metrics(effective_map, resolution=res)
    except Exception:
        return ApplicabilityResult(
            scene_type="fallback",
            recommended_planner="basic_improved",
            fallback_chain=("region_basic",),
            reasons=("metrics_computation_failed",),
            warnings=("metrics error, fell back to basic_improved",),
            metrics=None,
        )
    if metrics.free_area_pixel_count <= 0:
        return ApplicabilityResult(
            scene_type="invalid",
            recommended_planner="",
            reasons=("no_free_space",),
            warnings=("coverage planning skipped because free space is empty",),
            metrics=metrics,
        )

    oc = metrics.obstacle_count
    mc_m = metrics.mean_clearance_px * res

    # 禁行区已作为障碍物烘焙进 prepared_map，contour 检测已反映简化后的地图
    # 有禁行区表示用户主动划掉了复杂区域 → 放宽 cstar_rect 门槛
    fz = int(getattr(request, "forbidden_zone_count", 0))
    if fz > 0:
        oc = min(oc, 5)  # 有禁行区时 oc 压到 cstar_rect 准入上限

    if oc <= 5 and mc_m >= 0.3:
        return ApplicabilityResult(
            scene_type="simple_channel",
            recommended_planner="cstar_rect",
            fallback_chain=("cstar_tsp", "region_basic"),
            reasons=("few_obstacles_wide_passage",),
            metrics=metrics,
        )

    if oc <= OBSTACLE_COMPLEX_THRESHOLD:
        return ApplicabilityResult(
            scene_type="complex_terrain",
            recommended_planner="cstar_tsp",
            fallback_chain=("basic_improved", "region_basic"),
            reasons=("moderate_obstacles_or_narrow_passage",),
            metrics=metrics,
        )

    return ApplicabilityResult(
        scene_type="very_complex",
        recommended_planner="basic_improved",
        fallback_chain=("region_basic",),
        reasons=("too_many_obstacles_over_20",),
        metrics=metrics,
    )
