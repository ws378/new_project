"""FinalCoveragePath 主链实现。"""

from __future__ import annotations

from typing import Any

from ...contracts import (
    CoverageLaneInfoItem,
    EdgeInfo,
    FinalCoveragePathBuildInfo,
    FinalCoveragePathConnection,
    FinalCoveragePathInfo,
    FinalCoveragePathOrderedItem,
    FinalCoveragePathRoute,
    FinalCoveragePathSummary,
    FinalCoveragePathValidation,
    GeometryPreparationResult,
    GraphInfo,
    NodeInfo,
    SweepCadenceBuildInfo,
    SweepCadenceInfo,
    SweepCadenceRoute,
    SweepCadenceSegment,
    SweepGraphBuildInfo,
    SweepInfo,
    SweepTransitionCandidateItem,
)
from ..common_geometry import (
    angle_between_deg,
    connection_angle_deg,
    normalize_vector,
    pick_from_endpoint_pair,
    pick_to_endpoint_pair,
    segment_length,
    sqdist,
    to_float_point,
    to_path_tuple,
)
from ..sweep_graph.sweep_graph_build import build_transition_candidate_lookup


def polyline_length_px(path_rc: tuple[tuple[float, float], ...]) -> float:
    return float(sum(segment_length(path_rc[idx - 1], path_rc[idx]) for idx in range(1, len(path_rc))))


def path_segment_lengths(path_rc: tuple[tuple[float, float], ...]) -> tuple[float, ...]:
    return tuple(segment_length(path_rc[idx - 1], path_rc[idx]) for idx in range(1, len(path_rc)))


def dedup_consecutive_points(path_rc: tuple[tuple[float, float], ...] | list[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    out: list[tuple[float, float]] = []
    for point in tuple(path_rc or ()):
        pt = to_float_point(tuple(point))
        if not out or sqdist(out[-1], pt) > 1e-12:
            out.append(pt)
    return tuple(out)


def line_intersection(
    *,
    p0: tuple[float, float],
    d0: tuple[float, float],
    p1: tuple[float, float],
    d1: tuple[float, float],
) -> tuple[float, float] | None:
    det = float(d0[0] * d1[1] - d0[1] * d1[0])
    if abs(det) <= 1e-9:
        return None
    rhs = (float(p1[0] - p0[0]), float(p1[1] - p0[1]))
    t = float((rhs[0] * d1[1] - rhs[1] * d1[0]) / det)
    return float(p0[0] + t * d0[0]), float(p0[1] + t * d0[1])


def interpolate_point(
    p0: tuple[float, float],
    p1: tuple[float, float],
    ratio: float,
) -> tuple[float, float]:
    return (
        float(p0[0] + (p1[0] - p0[0]) * ratio),
        float(p0[1] + (p1[1] - p0[1]) * ratio),
    )


def resample_path_uniformly(
    path_rc: tuple[tuple[float, float], ...],
    *,
    spacing_px: int,
) -> tuple[tuple[float, float], ...]:
    """按固定弧长步长重采样折线。"""

    # 这里服务两类场景：
    # 1. connector 路径跟随相邻 sweep 的采样密度
    # 2. 几何真值落盘前避免内部点间距忽稀忽密
    # 它不做平滑，只在现有折线上按弧长插值。
    path = dedup_consecutive_points(path_rc)
    if len(path) < 2:
        return tuple(path)
    spacing = max(1, int(spacing_px))
    lengths = path_segment_lengths(path)
    total = float(sum(lengths))
    if total <= 1e-9:
        return (path[0], path[-1])
    sample_dists = [0.0]
    dist = float(spacing)
    while dist < total:
        sample_dists.append(dist)
        dist += float(spacing)
    sample_dists.append(total)
    out: list[tuple[float, float]] = []
    seg_idx = 0
    seg_start = 0.0
    for target in sample_dists:
        while seg_idx < len(lengths) - 1 and seg_start + lengths[seg_idx] < target - 1e-9:
            seg_start += lengths[seg_idx]
            seg_idx += 1
        seg_len = max(lengths[seg_idx], 1e-9)
        ratio = max(0.0, min(1.0, (target - seg_start) / seg_len))
        out.append(interpolate_point(path[seg_idx], path[seg_idx + 1], ratio))
    return dedup_consecutive_points(tuple(out))


def sample_cubic_bezier(
    p0: tuple[float, float],
    c1: tuple[float, float],
    c2: tuple[float, float],
    p3: tuple[float, float],
    *,
    sample_count: int,
) -> tuple[tuple[float, float], ...]:
    values: list[tuple[float, float]] = []
    count = max(2, int(sample_count))
    for idx in range(count):
        t = 0.0 if count == 1 else float(idx / (count - 1))
        mt = 1.0 - t
        r = mt**3 * p0[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t**3 * p3[0]
        c = mt**3 * p0[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t**3 * p3[1]
        values.append((float(r), float(c)))
    return tuple(values)


def median(values: list[float] | tuple[float, ...]) -> float:
    seq = sorted(float(item) for item in values)
    if not seq:
        raise ValueError('median requires non-empty values')
    mid = len(seq) // 2
    if len(seq) % 2 == 1:
        return float(seq[mid])
    return float(0.5 * (seq[mid - 1] + seq[mid]))


def is_constructible_ordered_item(item: FinalCoveragePathOrderedItem) -> bool:
    if str(item.get('item_type')) != 'junction_connection':
        return True
    # junction_connection 只有显式标成不可构造时才会被断链；其余 item 默认都应参与连续路径回放。
    return bool(item.get('is_constructible', True))


def ordered_item_points(item: FinalCoveragePathOrderedItem) -> tuple[tuple[float, float], ...]:
    if str(item.get('item_type')) == 'sweep_segment':
        return to_path_tuple(item.get('sweep_points_rc', ()))
    return to_path_tuple(item.get('path_points_rc', ()))


def orient_sweep_path_by_entry_end(
    path_rc: tuple[tuple[float, float], ...],
    entry_end: str,
) -> tuple[tuple[float, float], ...]:
    path = to_path_tuple(path_rc)
    return path if str(entry_end) == 'src' else tuple(reversed(path))


def append_path_points(
    current_subchain: list[tuple[float, float]],
    points_rc: tuple[tuple[float, float], ...],
) -> list[tuple[float, float]]:
    for point in points_rc:
        pt = to_float_point(point)
        if not current_subchain or sqdist(current_subchain[-1], pt) > 1e-12:
            current_subchain.append(pt)
    return current_subchain


def append_route_points_to_subchains(
    *,
    path_subchains: list[tuple[tuple[float, float], ...]],
    current_subchain: list[tuple[float, float]],
    points_rc: tuple[tuple[float, float], ...],
) -> tuple[list[tuple[tuple[float, float], ...]], list[tuple[float, float]]]:
    if points_rc:
        append_path_points(current_subchain, to_path_tuple(points_rc))
    return path_subchains, current_subchain


def break_route_subchain(
    *,
    path_subchains: list[tuple[tuple[float, float], ...]],
    current_subchain: list[tuple[float, float]],
) -> tuple[list[tuple[tuple[float, float], ...]], list[tuple[float, float]]]:
    if len(current_subchain) >= 2:
        path_subchains.append(tuple(current_subchain))
    return path_subchains, []


def route_path_point_count(route: FinalCoveragePathRoute) -> int:
    return int(sum(len(tuple(subchain)) for subchain in tuple(route.get('path_subchains_rc', ()))))


def validate_ordered_item_seams(ordered_items: tuple[FinalCoveragePathOrderedItem, ...]) -> None:
    """验证 route 回放序列中的 seam 连接没有断口。"""

    # 这里只校验真正会写入连续路径的 ordered item。
    # 失败 connection 会主动打断连续子链，所以这里遇到它时应重置 seam，而不是强行要求前后闭合。
    prev_last: tuple[float, float] | None = None
    for item in ordered_items:
        if not is_constructible_ordered_item(item):
            # 失败连接不会写入连续轨迹，它的语义就是“这里必须断链”。
            # 所以遇到不可构造 item 时，要显式清空前一段 seam 基准，而不是强行要求后项接上它。
            prev_last = None
            continue
        points = ordered_item_points(item)
        if not points:
            # 没有 path points 的 item 对连续几何没有贡献，也不能拿来校验 seam 闭合。
            continue
        if prev_last is not None and sqdist(prev_last, points[0]) > 1e-6:
            raise ValueError('ordered_items contains seam break')
        prev_last = points[-1]


def count_route_seam_breaks(ordered_items: tuple[FinalCoveragePathOrderedItem, ...]) -> int:
    count = 0
    prev_last: tuple[float, float] | None = None
    for item in ordered_items:
        if not is_constructible_ordered_item(item):
            # 不可构造 item 会把连续子链切断，因此 seam break 计数也应从下一段重新开始。
            prev_last = None
            continue
        points = ordered_item_points(item)
        if not points:
            # 空 points 既不会形成断口，也不能作为下一段的 seam 基准。
            continue
        if prev_last is not None and sqdist(prev_last, points[0]) > 1e-6:
            count += 1
        prev_last = points[-1]
    return int(count)


def assign_global_connection_ids(routes: list[FinalCoveragePathRoute]) -> None:
    next_id = 1
    for route in routes:
        for item in tuple(route.get('junction_connections', ())):
            item['connection_id'] = int(next_id)
            next_id += 1


def build_connection_debug_info(*, local_region: dict[str, object], from_end_type: str, to_end_type: str) -> dict[str, object]:
    return {
        'from_end_type': str(from_end_type),
        'to_end_type': str(to_end_type),
        'local_bbox': [int(local_region['r0']), int(local_region['c0']), int(local_region['r1']), int(local_region['c1'])],
    }


def build_common_junction_connection_truth(**kwargs: object) -> dict[str, object]:
    local_region = dict(kwargs['local_region'])
    return {
        'item_type': 'junction_connection',
        'connection_id': -1,
        'route_id': int(kwargs['route_id']),
        'from_sweep_id': int(kwargs['from_sweep_id']),
        'to_sweep_id': int(kwargs['to_sweep_id']),
        'via_node_id': int(kwargs['via_node_id']),
        'connection_type': str(kwargs['connection_type']),
        'connector_kind': str(kwargs['connector_kind']),
        'point_a_rc': to_float_point(tuple(kwargs['point_a'])),
        'point_b_rc': to_float_point(tuple(kwargs['point_b'])),
        'point_c_rc': to_float_point(tuple(kwargs['point_c'])),
        'point_d_rc': to_float_point(tuple(kwargs['point_d'])),
        'theta_deg': float(kwargs['theta_deg']),
        'connection_class': str(kwargs['connection_class']),
        'is_foldback': bool(kwargs['is_foldback']),
        'debug_info': build_connection_debug_info(
            local_region=local_region,
            from_end_type=str(kwargs['from_end_type']),
            to_end_type=str(kwargs['to_end_type']),
        ),
    }


def make_success_junction_connection(**kwargs: object) -> FinalCoveragePathConnection:
    return {
        **build_common_junction_connection_truth(**kwargs),
        'is_constructible': True,
        'failure_reason': '',
        'rule_geometry_rc': to_path_tuple(kwargs['rule_geometry_rc']),
        'junction_connection_points_rc': to_path_tuple(kwargs['sampled_path']),
        'path_points_rc': to_path_tuple(kwargs['sampled_path']),
        'coverage_support_width_m': float(kwargs['coverage_support_width_m']),
    }


def make_failed_junction_connection(**kwargs: object) -> FinalCoveragePathConnection:
    return {
        **build_common_junction_connection_truth(**kwargs),
        'is_constructible': False,
        'failure_reason': str(kwargs['failure_reason']),
        'rule_geometry_rc': to_path_tuple(kwargs['rule_geometry_rc']),
        'junction_connection_points_rc': tuple(),
        'path_points_rc': tuple(),
        'coverage_support_width_m': 0.0,
    }


def get_transition_truth(
    segment: SweepCadenceSegment,
    transition_by_id: dict[int, SweepTransitionCandidateItem],
) -> SweepTransitionCandidateItem | None:
    return transition_by_id.get(int(segment.get('transition_id', -1)))


def is_transition_primitive(segment: SweepCadenceSegment) -> bool:
    return str(segment.get('primitive_type', 'transition')) == 'transition'


def segment_source_exit_end(segment: SweepCadenceSegment, transition_by_id: dict[int, SweepTransitionCandidateItem]) -> str:
    if is_transition_primitive(segment):
        transition = get_transition_truth(segment, transition_by_id)
        if transition is None:
            raise ValueError(f"missing transition truth for transition segment: transition_id={int(segment.get('transition_id', -1))}")
        return str(transition['from_end_type'])
    return str(segment.get('entry_end_type', 'dst'))


def opposite_end_type(end_type: str) -> str:
    if str(end_type) == 'src':
        return 'dst'
    if str(end_type) == 'dst':
        return 'src'
    raise ValueError(f'invalid end_type: {end_type}')


def segment_target_entry_end(segment: SweepCadenceSegment, transition_by_id: dict[int, SweepTransitionCandidateItem]) -> str:
    if is_transition_primitive(segment):
        transition = get_transition_truth(segment, transition_by_id)
        if transition is None:
            raise ValueError(f"missing transition truth for transition segment: transition_id={int(segment.get('transition_id', -1))}")
        return str(transition['to_end_type'])
    return str(segment.get('exit_end_type', 'src'))


def segment_via_node_id(
    segment: SweepCadenceSegment,
    transition_by_id: dict[int, SweepTransitionCandidateItem],
    edge_by_id: dict[int, EdgeInfo],
    from_sweep: SweepInfo,
) -> int:
    if is_transition_primitive(segment):
        transition = get_transition_truth(segment, transition_by_id)
        if transition is None:
            raise ValueError(f"missing transition truth for transition segment: transition_id={int(segment.get('transition_id', -1))}")
        return int(transition['via_node_id'])
    if int(segment.get('via_node_id', -1)) >= 0:
        return int(segment['via_node_id'])
    edge = edge_by_id.get(int(from_sweep['source_edge_id']))
    if edge is None:
        return -1
    return int(edge.src_node_id) if segment_source_exit_end(segment, transition_by_id) == 'src' else int(edge.dst_node_id)


def build_empty_route_result(route_id: int) -> FinalCoveragePathRoute:
    return {
        'route_id': int(route_id),
        'ordered_items': tuple(),
        'sweep_segments': tuple(),
        'junction_connections': tuple(),
        'path_subchains_rc': tuple(),
        'path_length_px': 0.0,
        'path_length_m': 0.0,
        'coverage_support_info': {},
        'debug_info': {},
    }


def build_sweep_ordered_item(*, route_id: int, item_index: int, sweep_id: int, direction: str, sweep_path: tuple[tuple[float, float], ...]) -> FinalCoveragePathOrderedItem:
    return {
        'item_type': 'sweep_segment',
        'route_id': int(route_id),
        'item_index': int(item_index),
        'sweep_id': int(sweep_id),
        'direction': str(direction),
        'sweep_points_rc': tuple(sweep_path),
    }


def resolve_route_sweep_path_from_relation_truth(
    *,
    route: SweepCadenceRoute,
    sweep_sequence: list[int],
    segments: tuple[SweepCadenceSegment, ...],
    index: int,
    sweep: SweepInfo,
    transition_by_id: dict[int, SweepTransitionCandidateItem],
) -> tuple[tuple[tuple[float, float], ...], str]:
    path_rc = to_path_tuple(sweep.get('path_rc', ()))
    if not path_rc:
        return tuple(), 'forward'
    sweep_id = int(sweep['sweep_id'])
    if int(sweep_sequence[index]) != sweep_id:
        raise ValueError('route sweep_sequence and sweep item mismatch')
    prev_segment = segments[index - 1] if index > 0 and index - 1 < len(segments) else None
    next_segment = segments[index] if index < len(segments) else None
    if prev_segment is not None and int(prev_segment['to_sweep_id']) != sweep_id:
        raise ValueError('previous segment target does not match current sweep')
    if next_segment is not None and int(next_segment['from_sweep_id']) != sweep_id:
        raise ValueError('next segment source does not match current sweep')
    incoming_end = segment_target_entry_end(prev_segment, transition_by_id) if prev_segment is not None else str(route.get('start_end_type', 'src'))
    outgoing_end = segment_source_exit_end(next_segment, transition_by_id) if next_segment is not None else str(route.get('end_end_type', opposite_end_type(incoming_end)))
    if incoming_end == outgoing_end:
        return tuple(), 'connector_only'
    return orient_sweep_path_by_entry_end(path_rc, incoming_end), ('forward' if incoming_end == 'src' else 'reverse')


def prepare_route_sweep_iteration(
    *,
    route: SweepCadenceRoute,
    sweep_sequence: list[int],
    segments: tuple[SweepCadenceSegment, ...],
    index: int,
    sweep_by_id: dict[int, SweepInfo],
    transition_by_id: dict[int, SweepTransitionCandidateItem],
) -> dict[str, Any]:
    sweep_id = int(sweep_sequence[index])
    sweep = sweep_by_id[sweep_id]
    segment = segments[index] if index < len(segments) else None
    sweep_path, direction = resolve_route_sweep_path_from_relation_truth(
        route=route,
        sweep_sequence=sweep_sequence,
        segments=segments,
        index=index,
        sweep=sweep,
        transition_by_id=transition_by_id,
    )
    return {'sweep': sweep, 'segment': segment, 'sweep_path': tuple(sweep_path), 'direction': str(direction)}


def resolve_next_route_sweep_path(
    *,
    route: SweepCadenceRoute,
    sweep_sequence: list[int],
    segments: tuple[SweepCadenceSegment, ...],
    index: int,
    segment: SweepCadenceSegment,
    sweep_by_id: dict[int, SweepInfo],
    transition_by_id: dict[int, SweepTransitionCandidateItem],
) -> tuple[tuple[float, float], ...]:
    next_sweep = sweep_by_id[int(segment['to_sweep_id'])]
    next_path, _ = resolve_route_sweep_path_from_relation_truth(
        route=route,
        sweep_sequence=sweep_sequence,
        segments=segments,
        index=index + 1,
        sweep=next_sweep,
        transition_by_id=transition_by_id,
    )
    return tuple(next_path)


def assign_route_local_connection_order(*, connection: FinalCoveragePathConnection, item_index: int) -> None:
    connection['connection_id'] = -1
    connection['item_index'] = int(item_index)


def apply_connection_to_route_subchains(
    *,
    connection: FinalCoveragePathConnection,
    path_subchains: list[tuple[tuple[float, float], ...]],
    current_subchain: list[tuple[float, float]],
) -> tuple[list[tuple[tuple[float, float], ...]], list[tuple[float, float]]]:
    if bool(connection.get('is_constructible', True)):
        return append_route_points_to_subchains(
            path_subchains=path_subchains,
            current_subchain=current_subchain,
            points_rc=to_path_tuple(connection.get('path_points_rc', ())),
        )
    return break_route_subchain(path_subchains=path_subchains, current_subchain=current_subchain)


def build_materialized_route_result(
    *,
    route_id: int,
    ordered_items: tuple[FinalCoveragePathOrderedItem, ...],
    sweep_segments: tuple[FinalCoveragePathOrderedItem, ...],
    junction_connections: tuple[FinalCoveragePathConnection, ...],
    path_subchains_rc: tuple[tuple[tuple[float, float], ...], ...],
    resolution_m_per_px: float,
) -> FinalCoveragePathRoute:
    path_length_px = float(sum(polyline_length_px(subchain) for subchain in path_subchains_rc))
    return {
        'route_id': int(route_id),
        'ordered_items': tuple(ordered_items),
        'sweep_segments': tuple(sweep_segments),
        'junction_connections': tuple(junction_connections),
        'path_subchains_rc': path_subchains_rc,
        'path_length_px': float(path_length_px),
        'path_length_m': float(path_length_px * float(resolution_m_per_px)),
        'coverage_support_info': {
            'junction_connection_count': int(len(junction_connections)),
            'max_support_width_m': float(max((float(item.get('coverage_support_width_m', 0.0)) for item in junction_connections), default=0.0)),
        },
        'debug_info': {
            'sweep_segment_count': int(len(sweep_segments)),
            'junction_connection_count': int(len(junction_connections)),
            'path_subchain_count': int(len(path_subchains_rc)),
        },
    }


def materialize_route(
    *,
    route: SweepCadenceRoute,
    geometry_result: GeometryPreparationResult,
    sweep_by_id: dict[int, SweepInfo],
    edge_by_id: dict[int, EdgeInfo],
    node_by_id: dict[int, NodeInfo],
    lane_by_id: dict[int, CoverageLaneInfoItem],
    transition_by_id: dict[int, SweepTransitionCandidateItem],
    config: dict[str, Any],
) -> FinalCoveragePathRoute:
    # route 物化是 final coverage path 的主线落点。
    # 它只消费 cadence 的正式 route 真值，不再回看 greedy 内部试探态。
    sweep_sequence = [int(item) for item in route.get('sweep_sequence', ())]
    segments = tuple(route.get('segments', ()))
    route_id = int(route['route_id'])
    if not sweep_sequence:
        return build_empty_route_result(route_id)
    ordered_items: list[FinalCoveragePathOrderedItem] = []
    sweep_segments: list[FinalCoveragePathOrderedItem] = []
    junction_connections: list[FinalCoveragePathConnection] = []
    path_subchains: list[tuple[tuple[float, float], ...]] = []
    current_subchain: list[tuple[float, float]] = []
    for index, sweep_id in enumerate(sweep_sequence):
        sweep_iteration = prepare_route_sweep_iteration(
            route=route,
            sweep_sequence=sweep_sequence,
            segments=segments,
            index=index,
            sweep_by_id=sweep_by_id,
            transition_by_id=transition_by_id,
        )
        segment = sweep_iteration['segment']
        sweep_path = sweep_iteration['sweep_path']
        direction = sweep_iteration['direction']
        if sweep_path:
            sweep_item = build_sweep_ordered_item(
                route_id=route_id,
                item_index=int(len(ordered_items) + 1),
                sweep_id=int(sweep_id),
                direction=str(direction),
                sweep_path=tuple(sweep_path),
            )
            ordered_items.append(sweep_item)
            sweep_segments.append(sweep_item)
            path_subchains, current_subchain = append_route_points_to_subchains(
                path_subchains=path_subchains,
                current_subchain=current_subchain,
                points_rc=tuple(sweep_path),
            )
        if segment is None:
            break
        if bool(segment.get('requires_junction_connection', False)) or str(segment.get('primitive_type')) == 'foldback':
            next_path = resolve_next_route_sweep_path(
                route=route,
                sweep_sequence=sweep_sequence,
                segments=segments,
                index=index,
                segment=segment,
                sweep_by_id=sweep_by_id,
                transition_by_id=transition_by_id,
            )
            from .final_path_connectors import build_junction_connection_for_segment
            connection = build_junction_connection_for_segment(
                route_id=route_id,
                segment=segment,
                geometry_result=geometry_result,
                sweep_by_id=sweep_by_id,
                edge_by_id=edge_by_id,
                node_by_id=node_by_id,
                lane_by_id=lane_by_id,
                transition_by_id=transition_by_id,
                from_sweep_path=tuple(sweep_path),
                to_sweep_path=tuple(next_path),
                config=config,
            )
            assign_route_local_connection_order(connection=connection, item_index=int(len(ordered_items) + 1))
            junction_connections.append(connection)
            ordered_items.append(connection)
            path_subchains, current_subchain = apply_connection_to_route_subchains(
                connection=connection,
                path_subchains=path_subchains,
                current_subchain=current_subchain,
            )
    path_subchains, current_subchain = break_route_subchain(path_subchains=path_subchains, current_subchain=current_subchain)
    path_subchains_rc = tuple(path_subchains)
    validate_ordered_item_seams(tuple(ordered_items))
    return build_materialized_route_result(
        route_id=route_id,
        ordered_items=tuple(ordered_items),
        sweep_segments=tuple(sweep_segments),
        junction_connections=tuple(junction_connections),
        path_subchains_rc=path_subchains_rc,
        resolution_m_per_px=float(geometry_result.resolution_m_per_px),
    )


def require_positive_robot_width(config: dict[str, Any]) -> float:
    robot_width_m = float(config.get('robot_width_m', 0.0))
    if robot_width_m <= 0.0:
        raise ValueError('FinalCoveragePath requires explicit positive robot_width_m')
    return float(robot_width_m)


def count_connections_by_kind(all_connections: tuple[dict[str, Any], ...]) -> dict[str, int]:
    summary = {'forward': 0, 'foldback': 0}
    for item in all_connections:
        connector_kind = str(item.get('connector_kind', 'forward'))
        if connector_kind in summary:
            summary[connector_kind] += 1
    return summary


def build_final_coverage_path_summary(*, path_routes: tuple[dict[str, Any], ...], all_connections: tuple[dict[str, Any], ...], resolution_m_per_px: float) -> FinalCoveragePathSummary:
    total_path_length_px = float(sum(float(item.get('path_length_px', 0.0)) for item in path_routes))
    connector_counts = count_connections_by_kind(all_connections)
    return {
        'route_count': int(len(path_routes)),
        'junction_connection_count': int(len(all_connections)),
        'forward_connection_count': int(connector_counts['forward']),
        'foldback_connection_count': int(connector_counts['foldback']),
        'path_point_count': int(sum(route_path_point_count(route) for route in path_routes)),
        'path_length_px': float(total_path_length_px),
        'path_length_m': float(total_path_length_px * float(resolution_m_per_px)),
    }


def build_final_coverage_path(
    *,
    graph_info: GraphInfo,
    geometry_result: GeometryPreparationResult,
    coverage_lane_info: tuple[CoverageLaneInfoItem, ...] | list[CoverageLaneInfoItem],
    sweeps: tuple[SweepInfo, ...] | list[SweepInfo],
    sweep_graph_build_info: SweepGraphBuildInfo,
    sweep_cadence_info: SweepCadenceInfo,
    config: dict[str, Any] | None = None,
) -> FinalCoveragePathInfo:
    # final coverage path 的正式输入面只有四类真值：
    # 1. graph_info
    # 2. geometry_result
    # 3. coverage lane / sweeps
    # 4. sweep cadence
    # 这里不再额外读调试镜像或中间投影视图。
    config = dict(config or {})
    require_positive_robot_width(config)
    sweep_by_id = {int(item['sweep_id']): item for item in tuple(sweeps or ())}
    edge_by_id = {int(edge.edge_id): edge for edge in tuple(graph_info.edges)}
    node_by_id = {int(node.node_id): node for node in tuple(graph_info.nodes)}
    lane_by_id = {int(item['coverage_lane_id']): item for item in tuple(coverage_lane_info or ())}
    transition_by_id = build_transition_candidate_lookup(sweep_graph_build_info)
    path_routes = [
        materialize_route(
            route=route,
            geometry_result=geometry_result,
            sweep_by_id=sweep_by_id,
            edge_by_id=edge_by_id,
            node_by_id=node_by_id,
            lane_by_id=lane_by_id,
            transition_by_id=transition_by_id,
            config=config,
        )
        for route in tuple((sweep_cadence_info or {}).get('routes', ()))
    ]
    assign_global_connection_ids(path_routes)
    path_routes_tuple = tuple(path_routes)
    route_order_items = tuple(item for route in path_routes_tuple for item in tuple(route.get('ordered_items', ())))
    all_connections = tuple(item for route in path_routes_tuple for item in tuple(route.get('junction_connections', ())))
    return {
        'routes': path_routes_tuple,
        'ordered_items': route_order_items,
        'junction_connections': all_connections,
        'summary': build_final_coverage_path_summary(
            path_routes=path_routes_tuple,
            all_connections=all_connections,
            resolution_m_per_px=float(geometry_result.resolution_m_per_px),
        ),
    }


def collect_duplicate_connection_ids(connections: tuple[dict[str, object], ...]) -> tuple[int, ...]:
    ids = [int(item.get('connection_id', -1)) for item in connections]
    return tuple(sorted({int(item) for item in ids if item >= 0 and ids.count(item) > 1}))


def validate_connection_item(item: dict[str, object]) -> dict[str, int]:
    invalid_path_endpoint_count = 0
    invalid_support_width_count = 0
    invalid_foldback_count = 0
    invalid_rule_truth_count = 0
    failed_connection_count = 0
    is_constructible = bool(item.get('is_constructible', True))
    path_points = tuple(item.get('path_points_rc', ()))
    point_b = tuple(item.get('point_b_rc', ()))
    point_c = tuple(item.get('point_c_rc', ()))
    if not is_constructible:
        failed_connection_count += 1
    elif len(path_points) < 2:
        invalid_path_endpoint_count += 1
    elif sqdist(path_points[0], point_b) > 1e-6 or sqdist(path_points[-1], point_c) > 1e-6:
        invalid_path_endpoint_count += 1
    if is_constructible and float(item.get('coverage_support_width_m', 0.0)) <= 0.0:
        invalid_support_width_count += 1
    connector_kind = str(item.get('connector_kind', 'forward'))
    if connector_kind not in {'forward', 'foldback'}:
        invalid_rule_truth_count += 1
    if bool(item.get('is_foldback', False)) != bool(connector_kind == 'foldback'):
        invalid_foldback_count += 1
    for field in ('point_a_rc', 'point_b_rc', 'point_c_rc', 'point_d_rc'):
        if not tuple(item.get(field, ())):
            invalid_rule_truth_count += 1
    if str(item.get('connection_class', '')) not in {'direct', 'single_bend', 'smooth_curve', 'foldback'}:
        invalid_rule_truth_count += 1
    if is_constructible and not tuple(item.get('rule_geometry_rc', ())):
        invalid_rule_truth_count += 1
    if not is_constructible and not str(item.get('failure_reason', '')).strip():
        invalid_rule_truth_count += 1
    return {
        'invalid_path_endpoint_count': int(invalid_path_endpoint_count),
        'invalid_support_width_count': int(invalid_support_width_count),
        'invalid_foldback_count': int(invalid_foldback_count),
        'invalid_rule_truth_count': int(invalid_rule_truth_count),
        'failed_connection_count': int(failed_connection_count),
    }


def validate_final_coverage_path(final_coverage_path_info: FinalCoveragePathInfo | None) -> FinalCoveragePathValidation:
    final_info = dict(final_coverage_path_info or {})
    routes = tuple(final_info.get('routes', ()))
    connections = tuple(final_info.get('junction_connections', ()))
    duplicate_connection_ids = collect_duplicate_connection_ids(connections)
    invalid_path_endpoint_count = 0
    invalid_support_width_count = 0
    invalid_foldback_count = 0
    invalid_rule_truth_count = 0
    failed_connection_count = 0
    for item in connections:
        counts = validate_connection_item(item)
        invalid_path_endpoint_count += int(counts['invalid_path_endpoint_count'])
        invalid_support_width_count += int(counts['invalid_support_width_count'])
        invalid_foldback_count += int(counts['invalid_foldback_count'])
        invalid_rule_truth_count += int(counts['invalid_rule_truth_count'])
        failed_connection_count += int(counts['failed_connection_count'])
    route_seam_break_count = int(sum(count_route_seam_breaks(tuple(route.get('ordered_items', ()))) for route in routes))
    invalid_connection_count = (
        len(duplicate_connection_ids)
        + invalid_path_endpoint_count
        + invalid_support_width_count
        + invalid_foldback_count
        + invalid_rule_truth_count
        + failed_connection_count
        + route_seam_break_count
    )
    return {
        'is_valid': bool(invalid_connection_count == 0),
        'invalid_connection_count': int(invalid_connection_count),
        'invalid_path_endpoint_count': int(invalid_path_endpoint_count),
        'invalid_support_width_count': int(invalid_support_width_count),
        'invalid_foldback_count': int(invalid_foldback_count),
        'invalid_rule_truth_count': int(invalid_rule_truth_count),
        'duplicate_connection_ids': [int(item) for item in duplicate_connection_ids],
        'route_seam_break_count': int(route_seam_break_count),
    }


def build_final_coverage_path_build_info(
    *,
    graph_info: GraphInfo,
    geometry_result: GeometryPreparationResult,
    coverage_lane_sweep_info: Any,
    sweep_graph_build_info: SweepGraphBuildInfo,
    sweep_cadence_build_info: SweepCadenceBuildInfo,
    config: dict[str, Any] | None = None,
) -> FinalCoveragePathBuildInfo:
    final_coverage_path_info = build_final_coverage_path(
        graph_info=graph_info,
        geometry_result=geometry_result,
        coverage_lane_info=coverage_lane_sweep_info.coverage_lane_info,
        sweeps=coverage_lane_sweep_info.sweeps,
        sweep_graph_build_info=sweep_graph_build_info,
        sweep_cadence_info=sweep_cadence_build_info.sweep_cadence_info,
        config=config,
    )
    validation_info = validate_final_coverage_path(final_coverage_path_info)
    return FinalCoveragePathBuildInfo(
        final_coverage_path_info=final_coverage_path_info,
        validation_info=validation_info,
        summary=final_coverage_path_info['summary'],
    )


def build_sweeps_by_id(sweeps: tuple[SweepInfo, ...] | list[SweepInfo]) -> dict[int, SweepInfo]:
    return {int(item['sweep_id']): item for item in tuple(sweeps or ())}


def build_final_connection_truth_item(item: dict[str, object], from_sweep: SweepInfo, to_sweep: SweepInfo) -> FinalCoveragePathConnection:
    return {
        'route_id': int(item['route_id']),
        'connection_id': int(item['connection_id']),
        'from_sweep_id': int(item['from_sweep_id']),
        'to_sweep_id': int(item['to_sweep_id']),
        'from_path_rc': to_path_tuple(from_sweep.get('path_rc', ())),
        'to_path_rc': to_path_tuple(to_sweep.get('path_rc', ())),
        'point_a_rc': to_float_point(tuple(item['point_a_rc'])),
        'point_b_rc': to_float_point(tuple(item['point_b_rc'])),
        'point_c_rc': to_float_point(tuple(item['point_c_rc'])),
        'point_d_rc': to_float_point(tuple(item['point_d_rc'])),
        'theta_deg': float(item['theta_deg']),
        'connection_class': str(item['connection_class']),
        'is_constructible': bool(item.get('is_constructible', True)),
        'failure_reason': str(item.get('failure_reason', '')),
        'rule_geometry_rc': to_path_tuple(item.get('rule_geometry_rc', ())),
    }


def collect_final_connection_truths(*, sweeps: tuple[SweepInfo, ...] | list[SweepInfo], final_coverage_path_info: FinalCoveragePathInfo | None) -> tuple[FinalCoveragePathConnection, ...]:
    sweeps_by_id = build_sweeps_by_id(sweeps)
    collected: list[FinalCoveragePathConnection] = []
    final_info = final_coverage_path_info or {}
    for item in tuple(final_info.get('junction_connections', ())):
        from_sweep = sweeps_by_id.get(int(item['from_sweep_id']))
        to_sweep = sweeps_by_id.get(int(item['to_sweep_id']))
        if from_sweep is None or to_sweep is None:
            # final connection truth 需要把 connection 挂回正式 sweep 真值。
            # 任一端 sweep 缺失时，这条 connection 的 from/to 语义就无法被可靠解释，因此整条跳过。
            continue
        collected.append(build_final_connection_truth_item(item, from_sweep, to_sweep))
    return tuple(collected)


__all__ = [
    'angle_between_deg',
    'append_route_points_to_subchains',
    'apply_connection_to_route_subchains',
    'assign_global_connection_ids',
    'assign_route_local_connection_order',
    'break_route_subchain',
    'build_connection_debug_info',
    'build_empty_route_result',
    'build_final_connection_truth_item',
    'build_final_coverage_path',
    'build_final_coverage_path_build_info',
    'build_final_coverage_path_summary',
    'build_materialized_route_result',
    'build_sweep_ordered_item',
    'collect_duplicate_connection_ids',
    'collect_final_connection_truths',
    'connection_angle_deg',
    'count_route_seam_breaks',
    'dedup_consecutive_points',
    'get_transition_truth',
    'interpolate_point',
    'is_constructible_ordered_item',
    'line_intersection',
    'make_failed_junction_connection',
    'make_success_junction_connection',
    'materialize_route',
    'median',
    'normalize_vector',
    'opposite_end_type',
    'orient_sweep_path_by_entry_end',
    'ordered_item_points',
    'path_segment_lengths',
    'pick_from_endpoint_pair',
    'pick_to_endpoint_pair',
    'polyline_length_px',
    'prepare_route_sweep_iteration',
    'resample_path_uniformly',
    'resolve_next_route_sweep_path',
    'resolve_route_sweep_path_from_relation_truth',
    'route_path_point_count',
    'sample_cubic_bezier',
    'segment_length',
    'segment_source_exit_end',
    'segment_target_entry_end',
    'segment_via_node_id',
    'sqdist',
    'to_path_tuple',
    'validate_final_coverage_path',
    'validate_ordered_item_seams',
]
