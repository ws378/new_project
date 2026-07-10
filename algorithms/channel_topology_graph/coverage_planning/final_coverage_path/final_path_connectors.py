"""FinalCoveragePath 节点区连接实现。"""

from __future__ import annotations

import math
from typing import Any, TypedDict

import cv2
import numpy as np

from ...contracts import (
    CoverageLaneInfoItem,
    EdgeInfo,
    FinalCoveragePathConnection,
    GeometryPreparationResult,
    NodeInfo,
    SweepCadenceSegment,
    SweepInfo,
    SweepTransitionCandidateItem,
)


class NodeLocalRegion(TypedDict):
    node_id: int
    polygon_rc: tuple[tuple[float, float], ...]
    mask: np.ndarray
    clearance_dist_px: np.ndarray
    resolution_m_per_px: float
    r0: int
    c0: int
    r1: int
    c1: int
    center_local_rc: tuple[float, float]


class NodeLocalConnectionSolution(TypedDict):
    theta_deg: float
    connection_class: str
    is_constructible: bool
    failure_reason: str
    rule_geometry_rc: tuple[tuple[float, float], ...]
    node_local_path_rc: tuple[tuple[float, float], ...]


from .final_path_core import (
    connection_angle_deg,
    dedup_consecutive_points,
    line_intersection,
    make_failed_junction_connection,
    make_success_junction_connection,
    median,
    normalize_vector,
    pick_from_endpoint_pair,
    pick_to_endpoint_pair,
    sample_cubic_bezier,
    segment_source_exit_end,
    segment_target_entry_end,
    segment_via_node_id,
    sqdist,
    to_path_tuple,
)


def nearest_nonzero_pixel(mask: np.ndarray, point_rc: tuple[int, int]) -> tuple[int, int] | None:
    if mask.size == 0 or not np.any(mask > 0):
        return None
    rr, cc = np.where(mask > 0)
    idx = int(np.argmin((rr - int(point_rc[0])) ** 2 + (cc - int(point_rc[1])) ** 2))
    return int(rr[idx]), int(cc[idx])


def to_local_pixel(point_rc: tuple[float, float], local_region: NodeLocalRegion) -> tuple[int, int]:
    return int(round(float(point_rc[0]) - float(local_region['r0']))), int(round(float(point_rc[1]) - float(local_region['c0'])))


def to_global_pixel(point_rc: tuple[int, int], local_region: NodeLocalRegion) -> tuple[float, float]:
    return float(point_rc[0] + local_region['r0']), float(point_rc[1] + local_region['c0'])


def snap_local_pixel_to_mask(point_rc: tuple[int, int], mask: np.ndarray) -> tuple[int, int] | None:
    return nearest_nonzero_pixel(np.asarray(mask, dtype=np.uint8), point_rc)


def snap_global_point_to_local_mask(point_rc: tuple[float, float], local_region: NodeLocalRegion) -> tuple[float, float] | None:
    snapped = snap_local_pixel_to_mask(to_local_pixel(point_rc, local_region), np.asarray(local_region['mask'], dtype=np.uint8))
    if snapped is None:
        return None
    return to_global_pixel(snapped, local_region)


def draw_path_on_mask(mask: np.ndarray, path_rc: tuple[tuple[float, float], ...], half_width_px: int) -> None:
    if len(path_rc) < 2:
        return
    points_xy = np.array([[int(round(point[1])), int(round(point[0]))] for point in path_rc], dtype=np.int32)
    cv2.polylines(mask, [points_xy], False, 255, int(max(1, 2 * half_width_px + 1)), cv2.LINE_8)


def build_node_polygon_mask(polygon_rc: tuple[tuple[float, float], ...], mask_shape: tuple[int, int]) -> np.ndarray:
    polygon_pts = np.array([[int(round(point[1])), int(round(point[0]))] for point in polygon_rc], dtype=np.int32)
    polygon_mask = np.zeros(mask_shape, dtype=np.uint8)
    cv2.fillPoly(polygon_mask, [polygon_pts], 255)
    return polygon_mask


def build_incident_corridor_mask(
    *,
    node: NodeInfo,
    edge_by_id: dict[int, EdgeInfo],
    mask_shape: tuple[int, int],
    robot_width_m: float,
    resolution_m_per_px: float,
) -> np.ndarray:
    corridor_mask = np.zeros(mask_shape, dtype=np.uint8)
    corridor_half_width_px = int(max(1, round(0.5 * robot_width_m / max(resolution_m_per_px, 1e-6))))
    for edge_id in tuple(node.incident_edge_ids or ()):
        edge = edge_by_id.get(int(edge_id))
        if edge is None:
            # incident_edge_ids 里若有边真值缺失，就不能再拿它参与节点局部走廊构造，
            # 否则 corridor 会基于不存在的边几何产生伪支撑区。
            continue
        inner_path = to_path_tuple(edge.inner_path_rc)
        if len(inner_path) >= 2:
            draw_path_on_mask(corridor_mask, inner_path, corridor_half_width_px)
    return corridor_mask


def build_extra_seed_mask(*, free_mask: np.ndarray, extra_seed_points_rc: tuple[tuple[float, float], ...]) -> np.ndarray:
    extra_seed_mask = np.zeros_like(free_mask, dtype=np.uint8)
    for point_rc in tuple(extra_seed_points_rc or ()):
        seed_pixel = nearest_nonzero_pixel(np.where(free_mask, 255, 0).astype(np.uint8), (int(round(point_rc[0])), int(round(point_rc[1]))))
        if seed_pixel is not None:
            # 额外 seam/端点种子必须先吸附到最近的可通行像素，
            # 才能安全并入 node-local bbox 种子集合。
            extra_seed_mask[int(seed_pixel[0]), int(seed_pixel[1])] = 255
    return extra_seed_mask


def build_local_bbox_seed_mask(*, polygon_mask: np.ndarray, corridor_mask: np.ndarray, free_mask: np.ndarray, extra_seed_mask: np.ndarray | None = None) -> np.ndarray:
    seed_mask = (polygon_mask > 0) | (corridor_mask > 0)
    if extra_seed_mask is not None:
        # 显式 extra seed 只是在 node polygon 与 incident corridor 基础上的补充，不替代它们。
        seed_mask |= np.asarray(extra_seed_mask, dtype=np.uint8) > 0
    return np.where(seed_mask & free_mask, 255, 0).astype(np.uint8)


def compute_local_bbox(bbox_seed_mask: np.ndarray, *, node_id: int, mask_shape: tuple[int, int]) -> tuple[int, int, int, int]:
    ys, xs = np.where(bbox_seed_mask > 0)
    if ys.size == 0 or xs.size == 0:
        # 一个节点若连本地可行 seed 都构不出来，就不可能继续做 node-local connector 生成。
        raise ValueError(f'node {node_id} local feasible region is empty')
    r0 = max(0, int(np.min(ys)) - 2)
    r1 = min(int(mask_shape[0]), int(np.max(ys)) + 3)
    c0 = max(0, int(np.min(xs)) - 2)
    c1 = min(int(mask_shape[1]), int(np.max(xs)) + 3)
    return r0, r1, c0, c1


def build_node_local_feasible_region(
    *,
    node: NodeInfo,
    geometry_result: GeometryPreparationResult,
    edge_by_id: dict[int, EdgeInfo],
    config: dict[str, Any],
    extra_seed_points_rc: tuple[tuple[float, float], ...] = (),
) -> NodeLocalRegion:
    # node-local 区域同时吸收三类种子：
    # 1. node polygon 本体
    # 2. incident edge 的 inner corridor
    # 3. 显式 seam 端点
    # 这样 connector 模板既不会脱离节点腹地，也不会把真实连接端点裁掉。
    polygon_rc = tuple(tuple(map(float, item)) for item in (node.polygon_vertices_rc or ()))
    if len(polygon_rc) < 3:
        raise ValueError(f'node {node.node_id} polygon is required for junction connection')
    free_mask = np.asarray(geometry_result.free_mask) > 0
    polygon_mask = build_node_polygon_mask(polygon_rc, free_mask.shape)
    corridor_mask = build_incident_corridor_mask(
        node=node,
        edge_by_id=edge_by_id,
        mask_shape=polygon_mask.shape,
        robot_width_m=float(config.get('robot_width_m', 0.0)),
        resolution_m_per_px=float(geometry_result.resolution_m_per_px),
    )
    bbox_seed_mask = build_local_bbox_seed_mask(
        polygon_mask=polygon_mask,
        corridor_mask=corridor_mask,
        free_mask=free_mask,
        extra_seed_mask=build_extra_seed_mask(free_mask=free_mask, extra_seed_points_rc=extra_seed_points_rc),
    )
    # 先由种子联合区求出最小 local bbox，再在 bbox 内截取局部 free_mask 与 clearance 图，
    # 这样后续 connector 求解只在节点附近的局部区域工作。
    r0, r1, c0, c1 = compute_local_bbox(bbox_seed_mask, node_id=int(node.node_id), mask_shape=polygon_mask.shape)
    local_mask = (free_mask[r0:r1, c0:c1].astype(np.uint8) * 255).copy()
    clearance_dist_px = cv2.distanceTransform((local_mask > 0).astype(np.uint8), cv2.DIST_L2, 3)
    return {
        'node_id': int(node.node_id),
        'polygon_rc': polygon_rc,
        'mask': local_mask,
        'clearance_dist_px': clearance_dist_px,
        'resolution_m_per_px': float(geometry_result.resolution_m_per_px),
        'r0': int(r0),
        'c0': int(c0),
        'r1': int(r1),
        'c1': int(c1),
        'center_local_rc': (float(node.point_rc[0]) - float(r0), float(node.point_rc[1]) - float(c0)),
    }


def point_inside_polygon(point_rc: tuple[float, float], polygon_rc: tuple[tuple[float, float], ...]) -> bool:
    polygon_xy = np.array([[float(point[1]), float(point[0])] for point in polygon_rc], dtype=np.float32)
    return bool(cv2.pointPolygonTest(polygon_xy, (float(point_rc[1]), float(point_rc[0])), False) >= 0.0)


def project_point_to_local_mask(point_rc: tuple[float, float], local_region: NodeLocalRegion) -> tuple[float, float] | None:
    return snap_global_point_to_local_mask(point_rc, local_region)


def project_path_to_local_mask(path_points_rc: tuple[tuple[float, float], ...], local_region: NodeLocalRegion) -> tuple[tuple[float, float], ...]:
    projected: list[tuple[float, float]] = []
    for point in path_points_rc:
        snapped = project_point_to_local_mask(tuple(map(float, point)), local_region)
        if snapped is not None:
            # 只有成功吸附回 local mask 的点才保留，
            # 否则这条 connector path 会带着局部不可行点继续往下游传播。
            projected.append(tuple(map(float, snapped)))
    return tuple(dedup_consecutive_points(projected))


def project_connector_path_or_raise(path_points_rc: tuple[tuple[float, float], ...], local_region: NodeLocalRegion) -> tuple[tuple[float, float], ...]:
    projected_local_path = project_path_to_local_mask(path_points_rc, local_region)
    if len(projected_local_path) >= 2:
        return projected_local_path
    if len(path_points_rc) >= 2 and sqdist(path_points_rc[0], path_points_rc[-1]) <= 1e-6:
        snapped_start = project_point_to_local_mask(tuple(map(float, path_points_rc[0])), local_region)
        snapped_end = project_point_to_local_mask(tuple(map(float, path_points_rc[-1])), local_region)
        if snapped_start is not None and snapped_end is not None:
            return (tuple(map(float, snapped_start)), tuple(map(float, snapped_end)))
    raise ValueError('failed to project connector path into node-local feasible region')


def build_direct_connector(*, point_b: tuple[float, float], point_c: tuple[float, float], local_region: NodeLocalRegion) -> tuple[tuple[float, float], ...] | None:
    return try_polyline_connector((point_b, point_c), local_region=local_region)


def resolve_single_bend_pivot(*, p0: tuple[float, float], d0: tuple[float, float], p1: tuple[float, float], d1: tuple[float, float], local_region: NodeLocalRegion) -> tuple[float, float] | None:
    intersection = line_intersection(p0=p0, d0=d0, p1=p1, d1=d1)
    if intersection is None:
        return None
    corrected = snap_global_point_to_local_mask(intersection, local_region)
    if corrected is None:
        return None
    return tuple(map(float, corrected))


def build_single_bend_connector_from_tangent_intersection(*, point_b: tuple[float, float], point_c: tuple[float, float], from_tangent: tuple[float, float], to_tangent: tuple[float, float], local_region: NodeLocalRegion) -> tuple[tuple[float, float], ...] | None:
    corrected = resolve_single_bend_pivot(p0=point_b, d0=from_tangent, p1=point_c, d1=to_tangent, local_region=local_region)
    if corrected is None:
        return None
    return try_polyline_connector((point_b, corrected, point_c), local_region=local_region)


def build_smooth_candidate_curve(*, point_b: tuple[float, float], point_c: tuple[float, float], from_tangent: tuple[float, float], to_tangent: tuple[float, float], distance: float, scale: float) -> tuple[tuple[float, float], ...]:
    handle = max(1.0, float(distance) * float(scale))
    c1 = (float(point_b[0] + handle * from_tangent[0]), float(point_b[1] + handle * from_tangent[1]))
    c2 = (float(point_c[0] - handle * to_tangent[0]), float(point_c[1] - handle * to_tangent[1]))
    return tuple(sample_cubic_bezier(point_b, c1, c2, point_c, sample_count=32))


def snap_local_segment_endpoint(point_local_rc: tuple[int, int], local_region: NodeLocalRegion) -> tuple[int, int] | None:
    return nearest_nonzero_pixel(np.asarray(local_region['mask'], dtype=np.uint8), point_local_rc)


def rasterize_active_segment_mask(start_rc: tuple[int, int], end_rc: tuple[int, int], local_region: NodeLocalRegion) -> np.ndarray:
    line_mask = np.zeros_like(np.asarray(local_region['mask'], dtype=np.uint8))
    cv2.line(line_mask, (int(start_rc[1]), int(start_rc[0])), (int(end_rc[1]), int(end_rc[0])), 255, 1, cv2.LINE_8)
    return line_mask


def segment_is_feasible_in_local_region(start_rc: tuple[float, float], end_rc: tuple[float, float], *, local_region: NodeLocalRegion) -> bool:
    start = snap_local_segment_endpoint(to_local_pixel(start_rc, local_region), local_region)
    end = snap_local_segment_endpoint(to_local_pixel(end_rc, local_region), local_region)
    if start is None or end is None:
        return False
    active = rasterize_active_segment_mask(start, end, local_region) > 0
    return bool(np.any(active) and np.all((np.asarray(local_region['mask'], dtype=np.uint8) > 0)[active]))


def normalize_polyline_waypoints(waypoints: tuple[tuple[float, float], ...] | list[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    return tuple(dedup_consecutive_points(tuple((float(p[0]), float(p[1])) for p in waypoints)))


def try_polyline_connector(waypoints: tuple[tuple[float, float], ...] | list[tuple[float, float]], *, local_region: NodeLocalRegion) -> tuple[tuple[float, float], ...] | None:
    """按统一口径检查折线模板是否完整落在局部可行域内。"""

    # direct / single_bend / foldback 都复用这里的段级合法性检查。
    # 只要其中任一段越界，整个模板就失败，不在这里做局部修补。
    polyline = normalize_polyline_waypoints(waypoints)
    if len(polyline) < 2:
        return None
    for idx in range(1, len(polyline)):
        if not segment_is_feasible_in_local_region(polyline[idx - 1], polyline[idx], local_region=local_region):
            return None
    return tuple(polyline)


def curve_is_feasible(curve_rc: tuple[tuple[float, float], ...], *, local_region: NodeLocalRegion) -> bool:
    return len(curve_rc) >= 2 and all(segment_is_feasible_in_local_region(curve_rc[idx - 1], curve_rc[idx], local_region=local_region) for idx in range(1, len(curve_rc)))


def build_smooth_connector(*, point_b: tuple[float, float], point_c: tuple[float, float], from_tangent: tuple[float, float], to_tangent: tuple[float, float], local_region: NodeLocalRegion) -> tuple[tuple[float, float], ...] | None:
    distance = math.hypot(float(point_c[0] - point_b[0]), float(point_c[1] - point_b[1]))
    for scale in (0.20, 0.30, 0.40):
        curve = build_smooth_candidate_curve(
            point_b=point_b,
            point_c=point_c,
            from_tangent=from_tangent,
            to_tangent=to_tangent,
            distance=float(distance),
            scale=float(scale),
        )
        if curve_is_feasible(curve, local_region=local_region):
            return tuple(curve)
    return None


def collect_foldback_candidates(mask: np.ndarray, clearance: np.ndarray) -> np.ndarray:
    return np.argwhere((mask > 0) & (clearance > 1.0))


def select_best_foldback_candidate(*, candidates: np.ndarray, center_rc: tuple[float, float], clearance: np.ndarray) -> np.ndarray:
    return min(candidates, key=lambda item: (math.hypot(float(item[0]) - float(center_rc[0]), float(item[1]) - float(center_rc[1])), -float(clearance[int(item[0]), int(item[1])])))


def select_foldback_pivot(*, local_region: NodeLocalRegion) -> tuple[int, int]:
    mask = np.asarray(local_region['mask'], dtype=np.uint8)
    clearance = np.asarray(local_region['clearance_dist_px'], dtype=np.float32)
    candidates = collect_foldback_candidates(mask=mask, clearance=clearance)
    if candidates.size == 0:
        raise ValueError('foldback requires an interior turn zone with positive clearance')
    best = select_best_foldback_candidate(candidates=candidates, center_rc=tuple(local_region['center_local_rc']), clearance=clearance)
    return int(best[0]), int(best[1])


def classify_transition_connection(theta_deg: float) -> str:
    if theta_deg < 45.0:
        return 'direct'
    if theta_deg <= 120.0:
        return 'single_bend'
    return 'smooth_curve'


def build_transition_candidate(*, target_class: str, point_b: tuple[float, float], point_c: tuple[float, float], from_tangent: tuple[float, float], to_tangent: tuple[float, float], local_region: NodeLocalRegion) -> tuple[tuple[float, float], ...] | None:
    if target_class == 'direct':
        return build_direct_connector(point_b=point_b, point_c=point_c, local_region=local_region)
    if target_class == 'single_bend':
        return build_single_bend_connector_from_tangent_intersection(point_b=point_b, point_c=point_c, from_tangent=from_tangent, to_tangent=to_tangent, local_region=local_region)
    if target_class == 'smooth_curve':
        return build_smooth_connector(point_b=point_b, point_c=point_c, from_tangent=from_tangent, to_tangent=to_tangent, local_region=local_region)
    raise ValueError(f'invalid connection_class candidate: {target_class}')


def build_constructible_solution(*, theta_deg: float, connection_class: str, path_rc: tuple[tuple[float, float], ...]) -> NodeLocalConnectionSolution:
    return {
        'theta_deg': float(theta_deg),
        'connection_class': str(connection_class),
        'is_constructible': True,
        'failure_reason': '',
        'rule_geometry_rc': tuple(path_rc),
        'node_local_path_rc': tuple(path_rc),
    }


def build_failed_solution(*, theta_deg: float, connection_class: str) -> NodeLocalConnectionSolution:
    return {
        'theta_deg': float(theta_deg),
        'connection_class': str(connection_class),
        'is_constructible': False,
        'failure_reason': f'{connection_class} connector is not constructible under current node-local feasible region',
        'rule_geometry_rc': tuple(),
        'node_local_path_rc': tuple(),
    }


def solve_node_local_transition_connection(*, point_a: tuple[float, float], point_b: tuple[float, float], point_c: tuple[float, float], point_d: tuple[float, float], local_region: NodeLocalRegion) -> NodeLocalConnectionSolution:
    """在 direct / single_bend / smooth_curve 三类模板中按角度规则求解。"""

    # 这里不是多模板评分竞争，而是先按两侧切向夹角做模板分流。
    # 模板一旦确定，就只尝试那一类；成功则固化，失败则明确返回失败原因。
    from_tangent = normalize_vector((point_b[0] - point_a[0], point_b[1] - point_a[1]))
    to_tangent = normalize_vector((point_d[0] - point_c[0], point_d[1] - point_c[1]))
    theta_deg = connection_angle_deg(from_tangent, to_tangent)
    target_class = classify_transition_connection(theta_deg)
    candidate = build_transition_candidate(target_class=target_class, point_b=point_b, point_c=point_c, from_tangent=from_tangent, to_tangent=to_tangent, local_region=local_region)
    if candidate is not None:
        return build_constructible_solution(theta_deg=float(theta_deg), connection_class=str(target_class), path_rc=candidate)
    return build_failed_solution(theta_deg=float(theta_deg), connection_class=str(target_class))


def build_foldback_candidates(*, point_b: tuple[float, float], point_c: tuple[float, float], pivot_global: tuple[float, float]) -> tuple[tuple[tuple[float, float], ...], ...]:
    return (
        (point_b, pivot_global, point_c),
        (point_b, (point_b[0], pivot_global[1]), pivot_global, (point_c[0], pivot_global[1]), point_c),
        (point_b, (pivot_global[0], point_b[1]), pivot_global, (pivot_global[0], point_c[1]), point_c),
    )


def solve_node_local_foldback_connection(*, point_b: tuple[float, float], point_c: tuple[float, float], local_region: NodeLocalRegion) -> tuple[tuple[float, float], ...]:
    pivot_local = select_foldback_pivot(local_region=local_region)
    pivot_global = to_global_pixel(pivot_local, local_region)
    for candidate in build_foldback_candidates(point_b=point_b, point_c=point_c, pivot_global=pivot_global):
        polyline = try_polyline_connector(candidate, local_region=local_region)
        if polyline is not None:
            return polyline
    raise ValueError('foldback connector is not constructible under current template rules')


def resolve_segment_primitive_type(segment: SweepCadenceSegment) -> str:
    primitive_type = str(segment.get('primitive_type', 'transition'))
    if primitive_type == 'foldback':
        return 'foldback'
    if str(segment.get('connection_kind', 'forward')) == 'foldback':
        return 'foldback'
    return primitive_type


def solve_node_local_connection(*, point_a: tuple[float, float], point_b: tuple[float, float], point_c: tuple[float, float], point_d: tuple[float, float], local_region: NodeLocalRegion, segment: SweepCadenceSegment) -> NodeLocalConnectionSolution:
    primitive_type = resolve_segment_primitive_type(segment)
    if primitive_type == 'foldback':
        node_local_path = solve_node_local_foldback_connection(point_b=point_b, point_c=point_c, local_region=local_region)
        return build_constructible_solution(theta_deg=180.0, connection_class='foldback', path_rc=node_local_path)
    return solve_node_local_transition_connection(point_a=point_a, point_b=point_b, point_c=point_c, point_d=point_d, local_region=local_region)


def collect_adjacent_sweep_segment_lengths(*, from_sweep_path: tuple[tuple[float, float], ...], to_sweep_path: tuple[tuple[float, float], ...]) -> list[float]:
    samples: list[float] = []
    for path_rc in (from_sweep_path, to_sweep_path):
        samples.extend([float(math.hypot(path_rc[idx][0] - path_rc[idx - 1][0], path_rc[idx][1] - path_rc[idx - 1][1])) for idx in range(1, len(path_rc))])
    return samples


def derive_connection_sampling_step_px(*, from_sweep_path: tuple[tuple[float, float], ...], to_sweep_path: tuple[tuple[float, float], ...]) -> int:
    positive = [float(item) for item in collect_adjacent_sweep_segment_lengths(from_sweep_path=from_sweep_path, to_sweep_path=to_sweep_path) if float(item) > 1e-6]
    if not positive:
        raise ValueError('connection sampling requires positive point spacing from adjacent sweep paths')
    return max(1, int(round(float(median(positive)))))


def restore_sampled_path_endpoints(*, sampled: tuple[tuple[float, float], ...] | list[tuple[float, float]], geometric_path: tuple[tuple[float, float], ...]) -> list[tuple[float, float]]:
    out = list(sampled)
    out[0] = tuple(geometric_path[0])
    out[-1] = tuple(geometric_path[-1])
    return out


def sample_connection_path_like_sweep(*, geometric_path: tuple[tuple[float, float], ...], sampling_step_px: int) -> tuple[tuple[float, float], ...]:
    from .final_path_core import resample_path_uniformly
    sampled = resample_path_uniformly(geometric_path, spacing_px=int(sampling_step_px))
    if not sampled:
        return tuple(geometric_path)
    deduped = tuple(dedup_consecutive_points(restore_sampled_path_endpoints(sampled=sampled, geometric_path=geometric_path)))
    if len(deduped) < 2 and len(geometric_path) >= 2 and sqdist(geometric_path[0], geometric_path[-1]) <= 1e-6:
        return (tuple(geometric_path[0]), tuple(geometric_path[-1]))
    return deduped


def to_local_clearance_pixel(point_rc: tuple[float, float], local_region: NodeLocalRegion) -> tuple[int, int] | None:
    local_row = int(round(float(point_rc[0]) - float(local_region['r0'])))
    local_col = int(round(float(point_rc[1]) - float(local_region['c0'])))
    if not (0 <= local_row < local_region['clearance_dist_px'].shape[0] and 0 <= local_col < local_region['clearance_dist_px'].shape[1]):
        return None
    return local_row, local_col


def read_clearance_px(*, local_region: NodeLocalRegion, local_pixel: tuple[int, int]) -> float:
    clearance_px = float(local_region['clearance_dist_px'][local_pixel[0], local_pixel[1]])
    if clearance_px <= 0.0:
        raise ValueError('point has no local clearance')
    return float(clearance_px)


def clearance_px_to_width_m(clearance_px: float, resolution_m_per_px: float) -> float:
    return float(2.0 * clearance_px * resolution_m_per_px)


def collect_positive_clearances_px(*, points_rc: tuple[tuple[float, float], ...], local_region: NodeLocalRegion) -> list[float]:
    values: list[float] = []
    for point in points_rc:
        local_pixel = to_local_clearance_pixel(point, local_region)
        if local_pixel is None:
            # 路径点不落在当前 node-local region 里时，没法读取本地净空栅格，直接跳过。
            continue
        clearance_px = float(local_region['clearance_dist_px'][local_pixel[0], local_pixel[1]])
        if clearance_px > 0.0:
            values.append(clearance_px)
    return values


def min_clearance_width_m_along_path(*, node_local_path_points_rc: tuple[tuple[float, float], ...], local_region: NodeLocalRegion, resolution_m_per_px: float) -> float:
    positive = collect_positive_clearances_px(points_rc=node_local_path_points_rc, local_region=local_region)
    if not positive:
        raise ValueError('failed to sample positive local clearance along node-local path')
    return float(2.0 * min(positive) * resolution_m_per_px)


def build_endpoint_candidate_indices(node_local_path_points_rc: tuple[tuple[float, float], ...]) -> list[int]:
    candidate_indices = [0]
    if len(node_local_path_points_rc) > 1:
        candidate_indices.extend([1, len(node_local_path_points_rc) - 2, len(node_local_path_points_rc) - 1])
    return candidate_indices


def sample_positive_clearance_width_m(point_rc: tuple[float, float], local_region: NodeLocalRegion, resolution_m_per_px: float) -> float | None:
    local_pixel = to_local_clearance_pixel(point_rc, local_region)
    if local_pixel is None:
        return None
    clearance_px = float(local_region['clearance_dist_px'][local_pixel[0], local_pixel[1]])
    if clearance_px <= 0.0:
        return None
    return float(2.0 * clearance_px * resolution_m_per_px)


def min_clearance_width_m_near_path_ends(*, node_local_path_points_rc: tuple[tuple[float, float], ...], local_region: NodeLocalRegion, resolution_m_per_px: float) -> float:
    if not node_local_path_points_rc:
        raise ValueError('endpoint clearance sampling requires non-empty node-local path')
    widths = [
        width_m
        for idx in build_endpoint_candidate_indices(node_local_path_points_rc)
        if (width_m := sample_positive_clearance_width_m(node_local_path_points_rc[int(idx)], local_region, resolution_m_per_px)) is not None
    ]
    if not widths:
        raise ValueError('failed to sample positive local clearance near path ends')
    return float(min(widths))


def build_candidate_support_widths_m(*, upper_bound_m: float, resolution_m_per_px: float) -> list[float]:
    return [float(step) * float(resolution_m_per_px) for step in range(max(1, int(math.floor(float(upper_bound_m) / max(float(resolution_m_per_px), 1e-6)))), 0, -1)]


def to_local_band_points(node_local_path_points_rc: tuple[tuple[float, float], ...], local_region: NodeLocalRegion) -> list[tuple[int, int]]:
    return [(int(round(float(point[0]) - float(local_region['r0']))), int(round(float(point[1]) - float(local_region['c0'])))) for point in node_local_path_points_rc]


def draw_support_band_polyline(local_band_mask: np.ndarray, local_points: list[tuple[int, int]], support_radius_px: int) -> None:
    if len(local_points) < 2:
        return
    points_xy = np.array([[int(point[1]), int(point[0])] for point in local_points], dtype=np.int32)
    cv2.polylines(local_band_mask, [points_xy], False, 255, max(1, 2 * support_radius_px + 1), cv2.LINE_8)


def fill_support_band_disks(local_band_mask: np.ndarray, local_points: list[tuple[int, int]], support_radius_px: int) -> None:
    for row, col in local_points:
        cv2.circle(local_band_mask, (int(col), int(row)), int(support_radius_px), 255, -1, cv2.LINE_8)


def rasterize_support_band_mask(*, node_local_path_points_rc: tuple[tuple[float, float], ...], coverage_support_width_m: float, local_region: NodeLocalRegion, resolution_m_per_px: float) -> np.ndarray:
    support_radius_px = max(0, int(math.floor(0.5 * float(coverage_support_width_m) / resolution_m_per_px)))
    local_band_mask = np.zeros_like(np.asarray(local_region['mask'], dtype=np.uint8))
    local_points = to_local_band_points(node_local_path_points_rc, local_region)
    draw_support_band_polyline(local_band_mask, local_points, support_radius_px)
    fill_support_band_disks(local_band_mask, local_points, support_radius_px)
    return local_band_mask


def support_band_fits_local_region(*, band_mask: np.ndarray, local_region: NodeLocalRegion) -> bool:
    return bool(band_mask.size > 0 and np.all(np.asarray(local_region['mask'], dtype=np.uint8)[band_mask > 0] > 0))


def max_support_width_fitting_local_region(*, node_local_path_points_rc: tuple[tuple[float, float], ...], local_region: NodeLocalRegion, resolution_m_per_px: float, upper_bound_m: float) -> float:
    for width_m in build_candidate_support_widths_m(upper_bound_m=upper_bound_m, resolution_m_per_px=resolution_m_per_px):
        band_mask = rasterize_support_band_mask(node_local_path_points_rc=node_local_path_points_rc, coverage_support_width_m=width_m, local_region=local_region, resolution_m_per_px=resolution_m_per_px)
        if support_band_fits_local_region(band_mask=band_mask, local_region=local_region):
            return float(width_m)
    raise ValueError('failed to fit any positive connector support width into node-local feasible region')


def get_coverage_width_m(sweep: SweepInfo, lane_by_id: dict[int, CoverageLaneInfoItem]) -> float:
    lane = lane_by_id.get(int(sweep['coverage_lane_id']), {})
    return float(((lane.get('local_width_stats') or {}).get('coverage_width_m', 0.0)) or 0.0)


def resolve_neighbor_spacing_limit_m(*, from_sweep: SweepInfo, to_sweep: SweepInfo, lane_by_id: dict[int, CoverageLaneInfoItem]) -> float:
    neighbor_limits = [item for item in (get_coverage_width_m(from_sweep, lane_by_id), get_coverage_width_m(to_sweep, lane_by_id)) if item > 0.0]
    if not neighbor_limits:
        raise ValueError('connector coverage support width requires positive neighbor sweep spacing')
    return float(min(neighbor_limits))


def require_robot_width_m(config: dict[str, object]) -> float:
    robot_width_m = float(config.get('robot_width_m', 0.0))
    if robot_width_m <= 0.0:
        raise ValueError('connector coverage support width requires explicit positive robot_width_m')
    return float(robot_width_m)


def derive_connector_coverage_support_width(*, from_sweep: SweepInfo, to_sweep: SweepInfo, lane_by_id: dict[int, CoverageLaneInfoItem], geometry_result: GeometryPreparationResult, local_region: NodeLocalRegion, node_local_path_points_rc: tuple[tuple[float, float], ...], point_b: tuple[float, float], point_c: tuple[float, float], config: dict[str, object]) -> float:
    """把 connector 能承载的覆盖宽度收成一个正式米制真值。"""

    # 它先取几何上界的最小值，再做一次局部 mask 拟合。
    # 只有最终还能完整塞进 node-local 可行域的宽度，才允许写进 final path 真值。
    del point_b, point_c
    projected_local_path = project_connector_path_or_raise(node_local_path_points_rc, local_region)
    support_width_m = min(
        float(require_robot_width_m(config)),
        float(resolve_neighbor_spacing_limit_m(from_sweep=from_sweep, to_sweep=to_sweep, lane_by_id=lane_by_id)),
        float(min_clearance_width_m_along_path(node_local_path_points_rc=projected_local_path, local_region=local_region, resolution_m_per_px=float(geometry_result.resolution_m_per_px))),
        float(min_clearance_width_m_near_path_ends(node_local_path_points_rc=projected_local_path, local_region=local_region, resolution_m_per_px=float(geometry_result.resolution_m_per_px))),
    )
    support_width_m = min(
        float(support_width_m),
        float(max_support_width_fitting_local_region(node_local_path_points_rc=projected_local_path, local_region=local_region, resolution_m_per_px=float(geometry_result.resolution_m_per_px), upper_bound_m=float(support_width_m))),
    )
    if support_width_m <= 0.0:
        raise ValueError('failed to derive positive connector coverage support width')
    return float(support_width_m)


def validate_connection_endpoints(path_points_rc: tuple[tuple[float, float], ...], point_b: tuple[float, float], point_c: tuple[float, float]) -> None:
    if sqdist(path_points_rc[0], point_b) > 1e-6:
        raise ValueError('junction connection path does not start at point_b')
    if sqdist(path_points_rc[-1], point_c) > 1e-6:
        raise ValueError('junction connection path does not end at point_c')


def validate_projected_path_inside_local_region(projected_local_path: tuple[tuple[float, float], ...], local_region: NodeLocalRegion) -> None:
    for point in projected_local_path:
        local_row = int(round(float(point[0]) - float(local_region['r0'])))
        local_col = int(round(float(point[1]) - float(local_region['c0'])))
        if not (0 <= local_row < local_region['mask'].shape[0] and 0 <= local_col < local_region['mask'].shape[1]):
            raise ValueError('junction connection point is out of local feasible region bbox')
        if int(local_region['mask'][local_row, local_col]) == 0:
            raise ValueError('junction connection point is outside feasible region')


def validate_support_band_inside_local_region(*, node_local_path_points_rc: tuple[tuple[float, float], ...], coverage_support_width_m: float, local_region: NodeLocalRegion, resolution_m_per_px: float) -> None:
    if resolution_m_per_px <= 0.0:
        raise ValueError('support-band validation requires positive resolution_m_per_px')
    local_band_mask = rasterize_support_band_mask(node_local_path_points_rc=node_local_path_points_rc, coverage_support_width_m=coverage_support_width_m, local_region=local_region, resolution_m_per_px=resolution_m_per_px)
    band_pixels = np.argwhere(local_band_mask > 0)
    if band_pixels.size == 0:
        raise ValueError('junction connection support band is empty')
    feasible_mask = np.asarray(local_region['mask'], dtype=np.uint8)
    for row, col in band_pixels:
        if feasible_mask[int(row), int(col)] == 0:
            raise ValueError('junction connection support band leaves node-local feasible region')


def path_stays_near_local_center(path_rc: tuple[tuple[float, float], ...], *, local_region: NodeLocalRegion) -> bool:
    center = (float(local_region['center_local_rc'][0]) + float(local_region['r0']), float(local_region['center_local_rc'][1]) + float(local_region['c0']))
    mean_dist = sum(math.hypot(point[0] - center[0], point[1] - center[1]) for point in path_rc) / max(1, len(path_rc))
    return bool(mean_dist <= max(local_region['mask'].shape) * 0.75)


def validate_junction_connection(*, path_points_rc: tuple[tuple[float, float], ...], coverage_support_width_m: float, local_region: NodeLocalRegion, segment: SweepCadenceSegment, point_b: tuple[float, float], point_c: tuple[float, float]) -> None:
    if len(path_points_rc) < 2:
        raise ValueError('junction connection path_points_rc must contain at least 2 points')
    if float(coverage_support_width_m) <= 0.0:
        raise ValueError('coverage_support_width_m must be positive')
    projected_local_path = project_connector_path_or_raise(path_points_rc, local_region)
    validate_connection_endpoints(path_points_rc, point_b, point_c)
    validate_projected_path_inside_local_region(projected_local_path, local_region)
    validate_support_band_inside_local_region(node_local_path_points_rc=projected_local_path, coverage_support_width_m=coverage_support_width_m, local_region=local_region, resolution_m_per_px=float(local_region['resolution_m_per_px']))
    if str(segment.get('primitive_type', 'transition')) == 'foldback' and not path_stays_near_local_center(projected_local_path, local_region=local_region):
        raise ValueError('foldback path drifts too far from preferred node-local turn zone')


def resolve_segment_connector_kind(segment: SweepCadenceSegment) -> str:
    primitive_type = str(segment.get('primitive_type', 'transition'))
    if primitive_type == 'foldback':
        return 'foldback'
    return 'foldback' if str(segment.get('connection_kind', 'forward')) == 'foldback' else 'forward'


def resolve_segment_connection_type(segment: SweepCadenceSegment) -> str:
    return 'foldback' if resolve_segment_connector_kind(segment) == 'foldback' else 'transition'


def segment_is_foldback(segment: SweepCadenceSegment) -> bool:
    return bool(resolve_segment_connector_kind(segment) == 'foldback')


def require_via_node(*, node_by_id: dict[int, NodeInfo], via_node_id: int) -> NodeInfo:
    via_node = node_by_id.get(int(via_node_id))
    if via_node is None:
        raise ValueError(f'junction connection requires valid via_node_id, got: {via_node_id}')
    return via_node


def resolve_connection_endpoint_truths(*, from_sweep: SweepInfo, to_sweep: SweepInfo, from_end_type: str, to_end_type: str) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]:
    point_a, point_b = pick_from_endpoint_pair(to_path_tuple(from_sweep.get('path_rc', ())), from_end_type)
    point_c, point_d = pick_to_endpoint_pair(to_path_tuple(to_sweep.get('path_rc', ())), to_end_type)
    return point_a, point_b, point_c, point_d


def prepare_junction_connection_context(*, segment: SweepCadenceSegment, sweep_by_id: dict[int, SweepInfo], edge_by_id: dict[int, EdgeInfo], node_by_id: dict[int, NodeInfo], transition_by_id: dict[int, SweepTransitionCandidateItem], geometry_result: GeometryPreparationResult, from_sweep_path: tuple[tuple[float, float], ...], to_sweep_path: tuple[tuple[float, float], ...], config: dict[str, Any]) -> dict[str, Any]:
    from_sweep = sweep_by_id[int(segment['from_sweep_id'])]
    to_sweep = sweep_by_id[int(segment['to_sweep_id'])]
    from_end_type = segment_source_exit_end(segment, transition_by_id)
    to_end_type = segment_target_entry_end(segment, transition_by_id)
    via_node_id = segment_via_node_id(segment, transition_by_id, edge_by_id, from_sweep)
    via_node = require_via_node(node_by_id=node_by_id, via_node_id=via_node_id)
    point_a, point_b, point_c, point_d = resolve_connection_endpoint_truths(from_sweep=from_sweep, to_sweep=to_sweep, from_end_type=from_end_type, to_end_type=to_end_type)
    return {
        'from_sweep': from_sweep,
        'to_sweep': to_sweep,
        'primitive_type': str(segment.get('primitive_type', 'transition')),
        'connector_kind': resolve_segment_connector_kind(segment),
        'connection_type': resolve_segment_connection_type(segment),
        'is_foldback': bool(segment_is_foldback(segment)),
        'from_end_type': str(from_end_type),
        'to_end_type': str(to_end_type),
        'via_node_id': int(via_node_id),
        'via_node': via_node,
        'point_a': point_a,
        'point_b': point_b,
        'point_c': point_c,
        'point_d': point_d,
        'local_region': build_node_local_feasible_region(node=via_node, geometry_result=geometry_result, edge_by_id=edge_by_id, config=config, extra_seed_points_rc=(point_b, point_c)),
        'sampling_from_path': tuple(from_sweep_path) if len(from_sweep_path) >= 2 else to_path_tuple(from_sweep.get('path_rc', ())),
        'sampling_to_path': tuple(to_sweep_path) if len(to_sweep_path) >= 2 else to_path_tuple(to_sweep.get('path_rc', ())),
    }


def build_failed_junction_connection(*, route_id: int, context: dict[str, Any], connection_solution: dict[str, Any], failure_reason: str) -> FinalCoveragePathConnection:
    return make_failed_junction_connection(
        route_id=route_id,
        from_sweep_id=int(context['from_sweep']['sweep_id']),
        to_sweep_id=int(context['to_sweep']['sweep_id']),
        via_node_id=int(context['via_node_id']),
        connection_type=str(context['connection_type']),
        connector_kind=str(context['connector_kind']),
        point_a=context['point_a'],
        point_b=context['point_b'],
        point_c=context['point_c'],
        point_d=context['point_d'],
        theta_deg=float(connection_solution['theta_deg']),
        connection_class=str(connection_solution['connection_class']),
        failure_reason=str(failure_reason),
        rule_geometry_rc=tuple(connection_solution.get('rule_geometry_rc', ())),
        is_foldback=bool(context['is_foldback']),
        local_region=context['local_region'],
        from_end_type=str(context['from_end_type']),
        to_end_type=str(context['to_end_type']),
    )


def build_success_junction_connection(*, route_id: int, context: dict[str, Any], connection_solution: dict[str, Any], sampled_path: tuple[tuple[float, float], ...], coverage_support_width_m: float) -> FinalCoveragePathConnection:
    return make_success_junction_connection(
        route_id=route_id,
        from_sweep_id=int(context['from_sweep']['sweep_id']),
        to_sweep_id=int(context['to_sweep']['sweep_id']),
        via_node_id=int(context['via_node_id']),
        connection_type=str(context['connection_type']),
        connector_kind=str(context['connector_kind']),
        point_a=context['point_a'],
        point_b=context['point_b'],
        point_c=context['point_c'],
        point_d=context['point_d'],
        theta_deg=float(connection_solution['theta_deg']),
        connection_class=str(connection_solution['connection_class']),
        rule_geometry_rc=tuple(connection_solution.get('rule_geometry_rc', ())),
        sampled_path=tuple(sampled_path),
        coverage_support_width_m=float(coverage_support_width_m),
        is_foldback=bool(context['is_foldback']),
        local_region=context['local_region'],
        from_end_type=str(context['from_end_type']),
        to_end_type=str(context['to_end_type']),
    )


def build_junction_connection_for_segment(*, route_id: int, segment: SweepCadenceSegment, geometry_result: GeometryPreparationResult, sweep_by_id: dict[int, SweepInfo], edge_by_id: dict[int, EdgeInfo], node_by_id: dict[int, NodeInfo], lane_by_id: dict[int, CoverageLaneInfoItem], transition_by_id: dict[int, SweepTransitionCandidateItem], from_sweep_path: tuple[tuple[float, float], ...], to_sweep_path: tuple[tuple[float, float], ...], config: dict[str, Any]) -> FinalCoveragePathConnection:
    """为 cadence 的一段 segment 构造正式节点区连接 truth。"""

    # 这里按固定顺序推进：
    # 1. 解析 A/B/C/D 与 via_node 上下文
    # 2. 求 node-local 模板骨架
    # 3. 采样成 sweep 风格点列
    # 4. 推导 support width 并做最终校验
    context = prepare_junction_connection_context(segment=segment, sweep_by_id=sweep_by_id, edge_by_id=edge_by_id, node_by_id=node_by_id, transition_by_id=transition_by_id, geometry_result=geometry_result, from_sweep_path=from_sweep_path, to_sweep_path=to_sweep_path, config=config)
    connection_solution = solve_node_local_connection(point_a=context['point_a'], point_b=context['point_b'], point_c=context['point_c'], point_d=context['point_d'], local_region=context['local_region'], segment=segment)
    if not bool(connection_solution.get('is_constructible', True)):
        return build_failed_junction_connection(route_id=route_id, context=context, connection_solution=connection_solution, failure_reason=str(connection_solution.get('failure_reason', 'connector is not constructible under target rule class')))
    sampled_path = sample_connection_path_like_sweep(
        geometric_path=tuple(connection_solution['node_local_path_rc']),
        sampling_step_px=derive_connection_sampling_step_px(from_sweep_path=context['sampling_from_path'], to_sweep_path=context['sampling_to_path']),
    )
    try:
        coverage_support_width_m = derive_connector_coverage_support_width(
            from_sweep=context['from_sweep'],
            to_sweep=context['to_sweep'],
            lane_by_id=lane_by_id,
            geometry_result=geometry_result,
            local_region=context['local_region'],
            node_local_path_points_rc=sampled_path,
            point_b=context['point_b'],
            point_c=context['point_c'],
            config=config,
        )
        validate_junction_connection(
            path_points_rc=sampled_path,
            coverage_support_width_m=coverage_support_width_m,
            local_region=context['local_region'],
            segment=segment,
            point_b=context['point_b'],
            point_c=context['point_c'],
        )
    except ValueError as exc:
        return build_failed_junction_connection(route_id=route_id, context=context, connection_solution=connection_solution, failure_reason=str(exc))
    return build_success_junction_connection(route_id=route_id, context=context, connection_solution=connection_solution, sampled_path=sampled_path, coverage_support_width_m=float(coverage_support_width_m))


__all__ = [
    'NodeLocalConnectionSolution',
    'NodeLocalRegion',
    'build_direct_connector',
    'build_junction_connection_for_segment',
    'build_single_bend_connector_from_tangent_intersection',
    'build_smooth_candidate_curve',
    'build_smooth_connector',
    'build_node_local_feasible_region',
    'classify_transition_connection',
    'collect_adjacent_sweep_segment_lengths',
    'collect_foldback_candidates',
    'collect_positive_clearances_px',
    'curve_is_feasible',
    'derive_connection_sampling_step_px',
    'derive_connector_coverage_support_width',
    'fill_support_band_disks',
    'get_coverage_width_m',
    'max_support_width_fitting_local_region',
    'min_clearance_width_m_along_path',
    'min_clearance_width_m_near_path_ends',
    'nearest_nonzero_pixel',
    'normalize_polyline_waypoints',
    'path_stays_near_local_center',
    'point_inside_polygon',
    'project_connector_path_or_raise',
    'project_path_to_local_mask',
    'project_point_to_local_mask',
    'rasterize_active_segment_mask',
    'rasterize_support_band_mask',
    'read_clearance_px',
    'resolve_neighbor_spacing_limit_m',
    'resolve_segment_primitive_type',
    'resolve_single_bend_pivot',
    'restore_sampled_path_endpoints',
    'sample_connection_path_like_sweep',
    'sample_positive_clearance_width_m',
    'segment_is_feasible_in_local_region',
    'select_best_foldback_candidate',
    'select_foldback_pivot',
    'snap_global_point_to_local_mask',
    'snap_local_pixel_to_mask',
    'solve_node_local_connection',
    'solve_node_local_foldback_connection',
    'solve_node_local_transition_connection',
    'support_band_fits_local_region',
    'to_global_pixel',
    'to_local_band_points',
    'to_local_clearance_pixel',
    'to_local_pixel',
    'try_polyline_connector',
    'validate_connection_endpoints',
    'validate_junction_connection',
    'validate_projected_path_inside_local_region',
    'validate_support_band_inside_local_region',
]
