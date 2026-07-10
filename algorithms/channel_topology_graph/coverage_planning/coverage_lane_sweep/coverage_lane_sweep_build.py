"""Coverage lane 与 sweep 正式结果构造。"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from ...contracts import (
    CoverageLaneGenerationValidation,
    CoverageLaneInfoItem,
    CoverageLaneSweepBuildInfo,
    CoverageLaneSweepSummary,
    EdgeInfo,
    GeometryPreparationResult,
    GraphInfo,
    NodeInfo,
    SweepInfo,
)
from .lane_common import mask_to_points, to_path_tuple
from .lane_regions import (
    build_allowed_domain_mask,
    build_endpoint_polygon_block_mask,
    build_node_polygon_mask,
    derive_effective_region_mask,
    derive_outer_path_territory_pixels,
)
from .lane_sweep_results import (
    as_binary_mask,
    build_coverage_lane_sweep_summary,
    build_failed_lane_debug_info,
    build_sweep_item_from_layout,
    initialize_lane_item,
    resolve_lane_sweep_spacing_context,
    validate_coverage_lane_generation,
)
from .lane_sweep_specs import build_lane_sweep_specs


def build_coverage_lane_sweep_info(
    *,
    graph_info: GraphInfo,
    geometry_result: GeometryPreparationResult,
    config: dict[str, object] | None = None,
) -> CoverageLaneSweepBuildInfo:
    """构造 coverage lane sweep 正式结果。"""

    coverage_lane_info, sweeps = build_coverage_lanes_and_sweeps(
        graph_info=graph_info,
        geometry_result=geometry_result,
        config=config,
    )
    coverage_lane_items = tuple(coverage_lane_info)
    sweep_items = tuple(sweeps)
    return CoverageLaneSweepBuildInfo(
        coverage_lane_info=coverage_lane_items,
        sweeps=sweep_items,
        summary=build_coverage_lane_sweep_summary(coverage_lane_items, sweep_items),
        validation_info=validate_coverage_lane_generation(coverage_lane_items, sweep_items),
    )


def build_coverage_lanes_and_sweeps(
    graph_info: GraphInfo,
    geometry_result: GeometryPreparationResult,
    config: dict[str, Any] | None = None,
) -> tuple[list[CoverageLaneInfoItem], list[SweepInfo]]:
    """遍历 graph 边，直接物化全部 coverage lanes 与 sweeps。"""

    coverage_width_m, sweep_spacing_px, effective_min_clearance_px, normal_search_px = resolve_lane_sweep_spacing_context(
        geometry_result=geometry_result,
        config=config,
    )
    free_mask = as_binary_mask(geometry_result.free_mask)
    obstacle_distance_px = cv2.distanceTransform(free_mask, cv2.DIST_L2, 3)
    node_polygon_mask = build_node_polygon_mask(free_mask.shape, graph_info.nodes)
    constrained_free_mask = np.where(node_polygon_mask > 0, 0, free_mask).astype(np.uint8)
    nodes_by_id = {int(node.node_id): node for node in graph_info.nodes}
    territory_pixels_by_edge_id = derive_outer_path_territory_pixels(
        graph_info=graph_info,
        constrained_free_mask=constrained_free_mask,
    )

    coverage_lane_items: list[CoverageLaneInfoItem] = []
    sweep_items: list[SweepInfo] = []
    next_sweep_id = 1
    resolution_m_per_px = float(geometry_result.resolution_m_per_px)
    for edge in graph_info.edges:
        lane_item, edge_sweeps, next_sweep_id = build_single_coverage_lane(
            coverage_lane_id=int(len(coverage_lane_items) + 1),
            edge=edge,
            nodes_by_id=nodes_by_id,
            free_mask=free_mask,
            constrained_free_mask=constrained_free_mask,
            territory_pixels=territory_pixels_by_edge_id.get(int(edge.edge_id), ()),
            obstacle_distance_px=obstacle_distance_px,
            sweep_spacing_px=sweep_spacing_px,
            coverage_width_m=coverage_width_m,
            normal_search_px=normal_search_px,
            effective_min_clearance_px=effective_min_clearance_px,
            resolution_m_per_px=resolution_m_per_px,
            next_sweep_id=next_sweep_id,
        )
        coverage_lane_items.append(lane_item)
        sweep_items.extend(edge_sweeps)
    return coverage_lane_items, sweep_items


def build_single_coverage_lane(
    *,
    coverage_lane_id: int,
    edge: EdgeInfo,
    nodes_by_id: dict[int, NodeInfo],
    free_mask: np.ndarray,
    constrained_free_mask: np.ndarray,
    territory_pixels: tuple[tuple[int, int], ...],
    obstacle_distance_px: np.ndarray,
    sweep_spacing_px: int,
    coverage_width_m: float,
    normal_search_px: int,
    effective_min_clearance_px: float,
    resolution_m_per_px: float,
    next_sweep_id: int,
) -> tuple[CoverageLaneInfoItem, list[SweepInfo], int]:
    """为一条 edge 直接构造 coverage lane 与内部 sweeps。"""

    outer_path = to_path_tuple(edge.outer_path_rc)
    lane_item = initialize_lane_item(
        coverage_lane_id=coverage_lane_id,
        edge=edge,
        outer_path=outer_path,
        resolution_m_per_px=resolution_m_per_px,
    )
    if len(outer_path) < 2:
        # outer_path 不够长时，连 lane 主轴都无法成立，直接把 edge 标成排除而不是硬造 sweep。
        lane_item['excluded_reason'] = 'outer_path_too_short'
        return lane_item, [], next_sweep_id

    src_node = nodes_by_id.get(int(edge.src_node_id))
    dst_node = nodes_by_id.get(int(edge.dst_node_id))
    if src_node is None or dst_node is None:
        # 端点节点丢失时，后续 endpoint polygon block / allowed domain 都无法可靠求解。
        lane_item['excluded_reason'] = 'missing_endpoint_node'
        return lane_item, [], next_sweep_id

    polygon_block_mask = build_endpoint_polygon_block_mask(constrained_free_mask.shape, src_node, dst_node)
    lane_free_mask = np.where(polygon_block_mask > 0, 0, constrained_free_mask).astype(np.uint8)
    effective_region_mask = derive_effective_region_mask(outer_path, lane_free_mask)
    effective_region_pixels = tuple(mask_to_points(effective_region_mask))
    allowed_domain_mask = build_allowed_domain_mask(
        shape=free_mask.shape,
        territory_pixels=territory_pixels,
        src_node=src_node,
        dst_node=dst_node,
    )

    sweep_specs, layout_debug = build_lane_sweep_specs(
        axis_path=outer_path,
        free_mask=free_mask,
        allowed_domain_mask=allowed_domain_mask,
        obstacle_distance_px=obstacle_distance_px,
        sampling_step_px=sweep_spacing_px,
        normal_search_px=normal_search_px,
        effective_min_clearance_px=effective_min_clearance_px,
        robust_quantile=0.6,
    )
    if not sweep_specs:
        lane_item['excluded_reason'] = 'sweep_layout_invalid'
        lane_item['debug_info'] = build_failed_lane_debug_info(
            territory_pixels=territory_pixels,
            effective_region_pixels=effective_region_pixels,
            sweep_spacing_px=sweep_spacing_px,
            normal_search_px=normal_search_px,
            effective_min_clearance_px=effective_min_clearance_px,
            layout_debug=layout_debug,
        )
        return lane_item, [], next_sweep_id

    sweep_items: list[SweepInfo] = []
    positive_count = 0
    negative_count = 0
    center_sweep_id: int | None = None
    for spec in sweep_specs:
        sweep_item = build_sweep_item_from_layout(
            coverage_lane_id=coverage_lane_id,
            sweep_id=next_sweep_id,
            edge=edge,
            resolution_m_per_px=resolution_m_per_px,
            sampling_step_px=sweep_spacing_px,
            normal_search_px=normal_search_px,
            effective_min_clearance_px=effective_min_clearance_px,
            spec=spec,
        )
        sweep_items.append(sweep_item)
        if str(spec['side_label']) == 'center':
            center_sweep_id = int(next_sweep_id)
        elif str(spec['side_label']) == 'positive':
            positive_count += 1
        else:
            # 剩余合法侧别只有 negative；这里不再额外写分支枚举，保持结果层收口简单。
            negative_count += 1
        next_sweep_id += 1

    lane_item.update(
        territory_pixels=tuple([list(point) for point in territory_pixels]),
        effective_region_pixels=tuple([list(point) for point in effective_region_pixels]),
        sweep_ids=tuple(int(item['sweep_id']) for item in sweep_items),
        sweep_count=int(len(sweep_items)),
        local_width_stats={
            'sweep_spacing_px': int(sweep_spacing_px),
            'coverage_width_m': float(coverage_width_m),
            'effective_min_clearance_px': float(effective_min_clearance_px),
            'positive_side_sweep_count': int(positive_count),
            'negative_side_sweep_count': int(negative_count),
            'target_sweep_count': int(sweep_specs[0]['target_count']) if sweep_specs else 0,
            'robust_percentile': 0.6,
            'anchor_count': int(sweep_specs[0]['anchor_count']) if sweep_specs else 0,
            'approx_usable_width_px': float(max(1, len(sweep_items) - 1) * sweep_spacing_px),
            'approx_usable_width_m': float(max(1, len(sweep_items) - 1) * coverage_width_m),
        },
        geometry_valid=True,
        node_valid=True,
        active=True,
        debug_info={
            'territory_pixel_count': int(len(territory_pixels)),
            'effective_region_pixel_count': int(len(effective_region_pixels)),
            'sampling_step_px': int(sweep_spacing_px),
            'normal_search_px': int(normal_search_px),
            'effective_min_clearance_px': float(effective_min_clearance_px),
            'center_sweep_id': int(center_sweep_id) if center_sweep_id is not None else -1,
            'trimmed_outer_path_count': int(len(outer_path)),
            'sweep_layout_debug': layout_debug,
        },
    )
    return lane_item, sweep_items, next_sweep_id



__all__ = (
    'build_coverage_lane_sweep_info',
    'build_coverage_lanes_and_sweeps',
    'build_single_coverage_lane',
)
