"""Coverage lane 与 sweep 正式结果装配辅助函数。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np

from ...contracts import (
    CoverageLaneGenerationValidation,
    CoverageLaneInfoItem,
    CoverageLaneSweepSummary,
    EdgeInfo,
    GeometryPreparationResult,
    GraphInfo,
    SweepInfo,
)
from ..common_units import px_to_m, sequence_px_to_m
from .lane_common import to_path_tuple
from .lane_sweep_geometry import solve_main_direction


def initialize_lane_item(
    *,
    coverage_lane_id: int,
    edge: EdgeInfo,
    outer_path: tuple[tuple[float, float], ...],
    resolution_m_per_px: float,
) -> CoverageLaneInfoItem:
    """初始化单 lane 的正式结果壳对象。"""

    return {
        'coverage_lane_id': int(coverage_lane_id),
        'source_edge_id': int(edge.edge_id),
        'main_direction': solve_main_direction(outer_path),
        'territory_pixels': (),
        'effective_region_pixels': (),
        'sweep_ids': (),
        'sweep_count': 0,
        'local_width_stats': {},
        'geometry_valid': False,
        'node_valid': False,
        'topology_valid': True,
        'active': False,
        'excluded_reason': '',
        'resolution_m_per_px': float(resolution_m_per_px),
        'debug_info': {},
    }



def build_sweep_item_from_layout(
    *,
    coverage_lane_id: int,
    sweep_id: int,
    edge: EdgeInfo,
    resolution_m_per_px: float,
    sampling_step_px: int,
    normal_search_px: int,
    effective_min_clearance_px: float,
    spec: dict[str, Any],
) -> SweepInfo:
    """把 layout 阶段产出的单条 sweep 规格物化成正式 sweep 条目。"""

    # layout 求解阶段只负责回答“这条 sweep 应该铺在哪里”；
    # 正式结果对象的装配应该集中在结果辅助层，避免 build/specs 两边都承担结果物化职责。
    # 这一层同时也是 px -> m 的正式边界：
    # 几何内部仍可保留像素工作量纲，但写入正式 SweepInfo 时必须统一换成米。
    path_tuple = to_path_tuple(spec['path_rc'])
    path_length_px = float(spec['path_length_px'])
    offset_profile_m = sequence_px_to_m(spec['offset_profile_px'], resolution_m_per_px)
    return {
        'sweep_id': int(sweep_id),
        'coverage_lane_id': int(coverage_lane_id),
        'source_edge_id': int(edge.edge_id),
        'resolution_m_per_px': float(resolution_m_per_px),
        'side_label': str(spec['side_label']),
        'side_level': int(spec['side_level']),
        'mean_offset_m': float(np.mean(offset_profile_m)) if offset_profile_m else 0.0,
        'path_rc': [list(point) for point in path_tuple],
        'anchor_points_rc': [list(point) for point in spec['anchor_points_rc']],
        'offset_profile_m': [float(item) for item in offset_profile_m],
        'sampling_step_m': float(px_to_m(sampling_step_px, resolution_m_per_px)),
        'normal_search_m': float(px_to_m(normal_search_px, resolution_m_per_px)),
        'effective_min_clearance_m': float(px_to_m(effective_min_clearance_px, resolution_m_per_px)),
        'path_count': int(len(path_tuple)),
        'path_length_m': float(px_to_m(path_length_px, resolution_m_per_px)),
        'active': True,
    }



def build_failed_lane_debug_info(
    *,
    territory_pixels: tuple[tuple[int, int], ...],
    effective_region_pixels: tuple[tuple[int, int], ...],
    sweep_spacing_px: int,
    normal_search_px: int,
    effective_min_clearance_px: float,
    layout_debug: object,
) -> dict[str, object]:
    """构造 sweep layout 失败时的调试信息。"""

    return {
        'territory_pixel_count': int(len(territory_pixels)),
        'effective_region_pixel_count': int(len(effective_region_pixels)),
        'sampling_step_px': int(sweep_spacing_px),
        'normal_search_px': int(normal_search_px),
        'effective_min_clearance_px': float(effective_min_clearance_px),
        'sweep_layout_debug': layout_debug or {},
    }



def resolve_lane_sweep_spacing_context(
    *,
    geometry_result: GeometryPreparationResult,
    config: dict[str, Any] | None,
) -> tuple[float, int, float, int]:
    """解析 coverage lane sweep 的几何主导参数。"""

    config = dict(config or {})
    resolution_m_per_px = float(geometry_result.resolution_m_per_px)
    if resolution_m_per_px <= 0.0:
        raise ValueError('resolution_m_per_px must be positive')
    coverage_width_m = float(config.get('coverage_width_m', 0.55))
    if coverage_width_m <= 0.0:
        raise ValueError('coverage_width_m must be positive')
    free_node_min_clearance_m = float(config.get('free_node_min_clearance_m', 0.0))
    if free_node_min_clearance_m < 0.0:
        raise ValueError('free_node_min_clearance_m must be non-negative')
    # clearance 允许为 0，表示显式关闭额外节点净空要求，但不允许出现负净空语义。
    # 这里继续返回 px，是因为 lane_sweep 几何求解仍发生在像素网格上。
    sweep_spacing_px = max(2, int(round(coverage_width_m / resolution_m_per_px)))
    required_clearance_m = max(free_node_min_clearance_m, 0.5 * coverage_width_m)
    effective_min_clearance_px = float(required_clearance_m / resolution_m_per_px)
    normal_search_px = max(1, int(round(0.5 * coverage_width_m / resolution_m_per_px)))
    return coverage_width_m, sweep_spacing_px, effective_min_clearance_px, normal_search_px



def as_binary_mask(mask: Any) -> np.ndarray:
    """把输入掩膜标准化成 `0/255` 二值图。"""

    array = np.asarray(mask)
    if array.ndim != 2:
        raise ValueError('mask must be 2D')
    return np.where(array > 0, 255, 0).astype(np.uint8)



def build_coverage_lane_sweep_summary(
    coverage_lane_items: tuple[CoverageLaneInfoItem, ...],
    sweep_items: tuple[SweepInfo, ...],
) -> CoverageLaneSweepSummary:
    """构造 coverage lane sweep 最小 summary。"""

    return {
        'coverage_lane_count': int(len(coverage_lane_items)),
        'active_coverage_lane_count': int(sum(1 for item in coverage_lane_items if bool(item.get('active', True)))),
        'sweep_count': int(len(sweep_items)),
        'active_sweep_count': int(sum(1 for item in sweep_items if bool(item.get('active', True)))),
    }



def build_edge_coverage_projection(lane_item: CoverageLaneInfoItem) -> dict[str, object]:
    """把单条 lane truth 投影成 edge.coverage_info。"""

    return {
        'coverage_lane_id': int(lane_item['coverage_lane_id']),
        'active': bool(lane_item.get('active', True)),
        'main_direction': str(lane_item.get('main_direction', '')),
        'territory_pixels': tuple((int(point[0]), int(point[1])) for point in tuple(lane_item.get('territory_pixels', ()))),
        'effective_region_pixels': tuple((int(point[0]), int(point[1])) for point in tuple(lane_item.get('effective_region_pixels', ()))),
        'sweep_ids': tuple(int(item) for item in tuple(lane_item.get('sweep_ids', ()))),
        'sweep_count': int(lane_item.get('sweep_count', 0)),
        'local_width_stats': dict(lane_item.get('local_width_stats', {})),
        'geometry_valid': bool(lane_item.get('geometry_valid', False)),
        'node_valid': bool(lane_item.get('node_valid', False)),
        'topology_valid': bool(lane_item.get('topology_valid', False)),
        'excluded_reason': str(lane_item.get('excluded_reason', '')),
        'resolution_m_per_px': float(lane_item.get('resolution_m_per_px', 0.0)),
    }



def attach_edge_coverage_info(
    *,
    graph_info: GraphInfo,
    coverage_lane_info: tuple[CoverageLaneInfoItem, ...] | list[CoverageLaneInfoItem],
) -> GraphInfo:
    """把 lane truth 投影回 graph_info.edges[*].coverage_info。"""

    lane_by_edge_id = {int(item['source_edge_id']): item for item in tuple(coverage_lane_info or ())}
    projected_edges: list[EdgeInfo] = []
    for edge in graph_info.edges:
        lane_item = lane_by_edge_id.get(int(edge.edge_id))
        projected_edges.append(edge if lane_item is None else replace(edge, coverage_info=build_edge_coverage_projection(lane_item)))
    return replace(
        graph_info,
        edges=tuple(projected_edges),
        meta={**graph_info.meta, 'coverage_projection_attached': True, 'coverage_projection_edge_count': int(len(projected_edges))},
    )



def validate_coverage_lane_generation(
    coverage_lane_info: tuple[CoverageLaneInfoItem, ...] | list[CoverageLaneInfoItem],
    sweeps: tuple[SweepInfo, ...] | list[SweepInfo],
) -> CoverageLaneGenerationValidation:
    """校验 coverage lane 前半段结果闭环。"""

    errors: list[str] = []
    sweep_ids = {int(item['sweep_id']) for item in sweeps}
    active_lane_count = 0
    for lane in coverage_lane_info:
        lane_id = int(lane['coverage_lane_id'])
        lane_sweep_ids = tuple(int(item) for item in lane.get('sweep_ids', ()))
        if bool(lane.get('active', True)):
            active_lane_count += 1
            if not lane_sweep_ids:
                errors.append(f'coverage lane {lane_id} has no sweeps')
        for sweep_id in lane_sweep_ids:
            if sweep_id not in sweep_ids:
                errors.append(f'coverage lane {lane_id} references missing sweep {sweep_id}')
    for sweep in sweeps:
        if len(sweep.get('path_rc', ())) < 2:
            errors.append(f"sweep {sweep['sweep_id']} has too short path")
    return {
        'valid': not errors,
        'error_count': int(len(errors)),
        'errors': errors,
        'coverage_lane_count': int(len(tuple(coverage_lane_info))),
        'active_coverage_lane_count': int(active_lane_count),
        'sweep_count': int(len(tuple(sweeps))),
    }


__all__ = (
    'as_binary_mask',
    'attach_edge_coverage_info',
    'build_coverage_lane_sweep_summary',
    'build_edge_coverage_projection',
    'build_failed_lane_debug_info',
    'build_sweep_item_from_layout',
    'initialize_lane_item',
    'resolve_lane_sweep_spacing_context',
    'validate_coverage_lane_generation',
)
