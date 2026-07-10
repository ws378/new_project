"""Coverage lane sweep 布局求解与结果装配 helper。"""

from __future__ import annotations

from typing import Any

import numpy as np

from .lane_common import distance, path_length_euclidean
from .lane_path_sampling import sample_path_by_spacing
from .lane_sweep_geometry import (
    count_uniform_sweeps_for_interval,
    estimate_local_tangent,
    normal_from_tangent,
    point_at_normal_offset,
    search_legal_point_along_normal,
    solve_primary_offset_run,
    solve_robust_target_sweep_count,
)


def initialize_layout_debug(
    sampled_anchors: tuple[tuple[float, float], ...],
    sampling_step_px: int,
    normal_search_px: int,
    effective_min_clearance_px: float,
    robust_quantile: float,
) -> dict[str, Any]:
    """初始化 sweep 布局求解的 debug 容器。"""

    return {
        'sampling_step_px': int(sampling_step_px),
        'normal_search_px': int(normal_search_px),
        'effective_min_clearance_px': float(effective_min_clearance_px),
        'anchor_count': int(len(sampled_anchors)),
        'anchors': [],
        'local_sweep_counts_raw': [],
        'local_sweep_counts_sorted': [],
        'robust_quantile': float(robust_quantile),
        'target_sweep_count': 0,
    }


def collect_lane_anchor_layouts(
    sampled_anchors: tuple[tuple[float, float], ...],
    free_mask: np.ndarray,
    allowed_domain_mask: np.ndarray,
    obstacle_distance_px: np.ndarray,
    normal_search_px: int,
    effective_min_clearance_px: float,
    sampling_step_px: int,
    layout_debug: dict[str, Any],
) -> tuple[list[dict[str, Any]] | None, list[int] | None]:
    """逐锚点收集横向可铺设观测结果。"""

    max_search_px = int(max(free_mask.shape))
    anchor_infos: list[dict[str, Any]] = []
    local_counts: list[int] = []
    for idx, anchor_rc in enumerate(sampled_anchors):
        tangent = estimate_local_tangent(sampled_anchors, idx)
        normal = normal_from_tangent(tangent, side_sign=1)
        center_point = search_legal_point_along_normal(
            anchor_rc=anchor_rc,
            normal_vec=normal,
            free_mask=free_mask,
            obstacle_distance_px=obstacle_distance_px,
            effective_min_clearance_px=effective_min_clearance_px,
            normal_search_px=normal_search_px,
        )
        if center_point is None:
            # 连中心参考点都找不到时，说明这条 anchor 在主轴附近已经没有合法净空，不宜继续铺 sweep。
            layout_debug['failed_anchor_index'] = int(idx)
            layout_debug['failed_reason'] = 'center_point_invalid'
            return None, None
        offset_run = solve_primary_offset_run(
            base_point_rc=center_point,
            normal_vec=normal,
            allowed_domain_mask=allowed_domain_mask,
            free_mask=free_mask,
            obstacle_distance_px=obstacle_distance_px,
            effective_min_clearance_px=effective_min_clearance_px,
            max_search_px=max_search_px,
        )
        if offset_run is None:
            # 找不到合法 offset 连续段，意味着该 anchor 沿法向没有可持续铺设的横向通道。
            layout_debug['failed_anchor_index'] = int(idx)
            layout_debug['failed_reason'] = 'offset_run_invalid'
            return None, None
        offset_min, offset_max = offset_run
        local_count = count_uniform_sweeps_for_interval(offset_min, offset_max, sampling_step_px)
        anchor_info = {
            'anchor_index': int(idx),
            'anchor_rc': anchor_rc,
            'center_point_rc': center_point,
            'normal_vec': normal,
            'offset_min_px': int(offset_min),
            'offset_max_px': int(offset_max),
            'local_sweep_count': int(local_count),
        }
        anchor_infos.append(anchor_info)
        local_counts.append(int(local_count))
        layout_debug['anchors'].append(
            {
                'anchor_index': int(idx),
                'anchor_rc': [float(anchor_rc[0]), float(anchor_rc[1])],
                'center_point_rc': [float(center_point[0]), float(center_point[1])],
                'normal_vec': [float(normal[0]), float(normal[1])],
                'offset_min_px': int(offset_min),
                'offset_max_px': int(offset_max),
                'interval_width_px': float(offset_max - offset_min),
                'local_sweep_count': int(local_count),
            }
        )
    return anchor_infos, local_counts


def signed_area_twice(point_a: tuple[float, float], point_b: tuple[float, float], point_c: tuple[float, float]) -> float:
    """计算三点有向面积的两倍值。"""

    return (float(point_b[0]) - float(point_a[0])) * (float(point_c[1]) - float(point_a[1])) - (float(point_b[1]) - float(point_a[1])) * (float(point_c[0]) - float(point_a[0]))


def point_on_segment(point_a: tuple[float, float], point_b: tuple[float, float], point_p: tuple[float, float]) -> bool:
    """判断点是否落在线段包围盒内。"""

    epsilon = 1e-6
    return min(float(point_a[0]), float(point_b[0])) - epsilon <= float(point_p[0]) <= max(float(point_a[0]), float(point_b[0])) + epsilon and min(float(point_a[1]), float(point_b[1])) - epsilon <= float(point_p[1]) <= max(float(point_a[1]), float(point_b[1])) + epsilon


def segments_intersect(point_a: tuple[float, float], point_b: tuple[float, float], point_c: tuple[float, float], point_d: tuple[float, float]) -> bool:
    """判断两条线段是否相交。"""

    area_abc = signed_area_twice(point_a, point_b, point_c)
    area_abd = signed_area_twice(point_a, point_b, point_d)
    area_cda = signed_area_twice(point_c, point_d, point_a)
    area_cdb = signed_area_twice(point_c, point_d, point_b)
    epsilon = 1e-6
    if abs(area_abc) <= epsilon and point_on_segment(point_a, point_b, point_c):
        return True
    if abs(area_abd) <= epsilon and point_on_segment(point_a, point_b, point_d):
        return True
    if abs(area_cda) <= epsilon and point_on_segment(point_c, point_d, point_a):
        return True
    if abs(area_cdb) <= epsilon and point_on_segment(point_c, point_d, point_b):
        return True
    return ((area_abc > 0.0) != (area_abd > 0.0)) and ((area_cda > 0.0) != (area_cdb > 0.0))


def interpolate_point(point_a: tuple[float, float], point_b: tuple[float, float], ratio: float) -> tuple[float, float]:
    """在线段内部按比例插值得到新点。"""

    clipped_ratio = min(1.0, max(0.0, float(ratio)))
    return (
        float(point_a[0]) + (float(point_b[0]) - float(point_a[0])) * clipped_ratio,
        float(point_a[1]) + (float(point_b[1]) - float(point_a[1])) * clipped_ratio,
    )


def solve_segment_intersection_point(point_a: tuple[float, float], point_b: tuple[float, float], point_c: tuple[float, float], point_d: tuple[float, float]) -> tuple[float, float] | None:
    """求两条非平行线段的交点。"""

    vector_ab = (float(point_b[0]) - float(point_a[0]), float(point_b[1]) - float(point_a[1]))
    vector_cd = (float(point_d[0]) - float(point_c[0]), float(point_d[1]) - float(point_c[1]))
    denominator = vector_ab[0] * vector_cd[1] - vector_ab[1] * vector_cd[0]
    if abs(denominator) <= 1e-6:
        return None
    vector_ac = (float(point_c[0]) - float(point_a[0]), float(point_c[1]) - float(point_a[1]))
    ratio_ab = (vector_ac[0] * vector_cd[1] - vector_ac[1] * vector_cd[0]) / denominator
    return (float(point_a[0]) + vector_ab[0] * ratio_ab, float(point_a[1]) + vector_ab[1] * ratio_ab)


def shrink_head_and_tail_to_avoid_segment_intersection(
    path_points: tuple[tuple[float, float], ...],
    anchor_points: tuple[tuple[float, float], ...],
    offset_profile: tuple[float, ...],
) -> tuple[tuple[tuple[float, float], ...], tuple[tuple[float, float], ...], tuple[float, ...]]:
    """若首段与尾段相交，则对首尾两端做局部回缩。"""

    trimmed_path = list(path_points)
    for _ in range(8):
        if len(trimmed_path) < 4:
            break
        head_start, head_end = tuple(trimmed_path[0]), tuple(trimmed_path[1])
        tail_start, tail_end = tuple(trimmed_path[-2]), tuple(trimmed_path[-1])
        if not segments_intersect(head_start, head_end, tail_start, tail_end):
            break
        intersection_point = solve_segment_intersection_point(head_start, head_end, tail_start, tail_end)
        if intersection_point is None:
            break
        trimmed_path[0] = interpolate_point(intersection_point, head_end, 0.5)
        trimmed_path[-1] = interpolate_point(intersection_point, tail_start, 0.5)
    return tuple(trimmed_path), tuple(anchor_points), tuple(offset_profile)


def smooth_center_reference_path(center_points: tuple[tuple[float, float], ...], window_radius: int = 2) -> tuple[tuple[float, float], ...]:
    """对原始 center_point 链做轻量平顺。"""

    if len(center_points) <= 2 or window_radius <= 0:
        return center_points
    smoothed: list[tuple[float, float]] = []
    count = len(center_points)
    for idx in range(count):
        if idx == 0 or idx == count - 1:
            smoothed.append(center_points[idx])
            continue
        window = center_points[max(0, idx - window_radius):min(count, idx + window_radius + 1)]
        smoothed.append((float(sum(point[0] for point in window) / len(window)), float(sum(point[1] for point in window) / len(window))))
    # 滑窗平均会改变相邻点的弧长节拍，尤其在首尾和拐角附近容易出现“长段 + 短段”成对堆积。
    # sweep.path_rc 是最终可视化和后续 cadence 消费的离散点列，因此平顺后必须再次按同一条折线弧长均匀化。
    return resample_reference_path_to_uniform_count(tuple(smoothed), count)


def resample_reference_path_to_uniform_count(
    path_points: tuple[tuple[float, float], ...],
    target_count: int,
) -> tuple[tuple[float, float], ...]:
    """把参考路径按固定点数重新弧长均匀化。"""

    if target_count <= 0:
        return ()
    if len(path_points) <= 1 or target_count <= 1:
        return tuple(path_points[:1])
    total_length = path_length_euclidean(path_points)
    if total_length <= 1e-6:
        # 所有点退化到同一位置时，保留首点重复没有意义，直接返回一个点表达退化状态。
        return (tuple(path_points[0]),)
    # 固定输出点数等于原 anchor 数，保证 offset 序列、normal 序列和 path 点序列仍是一一对应关系。
    target_distances = tuple(float(total_length) * float(idx) / float(target_count - 1) for idx in range(target_count))
    return tuple(interpolate_path_at_distance(path_points, target_distance) for target_distance in target_distances)


def interpolate_path_at_distance(
    path_points: tuple[tuple[float, float], ...],
    target_distance: float,
) -> tuple[float, float]:
    """沿折线按累计弧长插值得到一个点。"""

    if target_distance <= 0.0:
        return (float(path_points[0][0]), float(path_points[0][1]))
    traveled = 0.0
    for idx in range(1, len(path_points)):
        start_point = path_points[idx - 1]
        end_point = path_points[idx]
        segment_length = distance(start_point, end_point)
        if segment_length <= 1e-6:
            # 零长段不贡献弧长，跳过可避免局部重复点影响目标距离定位。
            continue
        next_traveled = traveled + segment_length
        if target_distance <= next_traveled:
            ratio = (float(target_distance) - traveled) / segment_length
            return interpolate_point(start_point, end_point, ratio)
        traveled = next_traveled
    # 浮点累计误差可能让最后一个目标距离略超总长，此时强制回到原尾点，保证收尾完整。
    return (float(path_points[-1][0]), float(path_points[-1][1]))


def solve_offset_sequence_for_side(
    *,
    anchor_infos: list[dict[str, Any]],
    target_offsets: tuple[float, ...],
    sampling_step_px: int,
    previous_sequence: tuple[float, ...] | None,
    debug_key: str,
    layout_debug: dict[str, Any],
) -> tuple[float, ...]:
    """在每个 anchor 的合法区间内求一条渐变 offset 序列。"""

    solved: list[float] = []
    change_limit_px = max(2, int(round(float(sampling_step_px) * 1.25)))
    predecessor_weight = 0.75 if previous_sequence is not None else 0.0
    for idx, anchor_info in enumerate(anchor_infos):
        offset_min = int(anchor_info['offset_min_px'])
        offset_max = int(anchor_info['offset_max_px'])
        offset_min, offset_max = min(offset_min, offset_max), max(offset_min, offset_max)
        candidate_offsets = np.arange(offset_min, offset_max + 1, dtype=np.int32)
        target_offset = float(target_offsets[idx])
        if idx > 0:
            prev_value = float(solved[idx - 1])
            lower = max(offset_min, int(np.floor(prev_value - change_limit_px)))
            upper = min(offset_max, int(np.ceil(prev_value + change_limit_px)))
            if lower <= upper:
                candidate_offsets = np.arange(lower, upper + 1, dtype=np.int32)
        values = candidate_offsets.astype(np.float64)
        costs = (values - target_offset) ** 2
        if idx > 0:
            prev_value = float(solved[idx - 1])
            costs += 1.5 * ((values - prev_value) ** 2)
        if idx >= 2:
            prev_prev_value = float(solved[idx - 2])
            costs += 2.5 * ((values - (2.0 * float(solved[idx - 1]) - prev_prev_value)) ** 2)
        if previous_sequence is not None:
            costs += predecessor_weight * ((values - float(previous_sequence[idx])) ** 2)
        best_offset = float(candidate_offsets[int(np.argmin(costs))])
        solved.append(best_offset)
        layout_debug['anchors'][idx].setdefault(debug_key, []).append(float(best_offset))
    return tuple(solved)


def build_lane_sweep_specs(
    axis_path: tuple[tuple[float, float], ...],
    free_mask: np.ndarray,
    allowed_domain_mask: np.ndarray,
    obstacle_distance_px: np.ndarray,
    sampling_step_px: int,
    normal_search_px: int,
    effective_min_clearance_px: float,
    robust_quantile: float = 0.9,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    """从主轴直接解出整条 lane 的 sweep 铺设方案。"""

    sampled_anchors = sample_path_by_spacing(axis_path, sampling_step_px)
    layout_debug = initialize_layout_debug(sampled_anchors, sampling_step_px, normal_search_px, effective_min_clearance_px, robust_quantile)
    if len(sampled_anchors) < 2:
        return None, layout_debug
    anchor_infos, local_counts = collect_lane_anchor_layouts(
        sampled_anchors=sampled_anchors,
        free_mask=free_mask,
        allowed_domain_mask=allowed_domain_mask,
        obstacle_distance_px=obstacle_distance_px,
        normal_search_px=normal_search_px,
        effective_min_clearance_px=effective_min_clearance_px,
        sampling_step_px=sampling_step_px,
        layout_debug=layout_debug,
    )
    if anchor_infos is None or local_counts is None:
        return None, layout_debug
    target_count = solve_robust_target_sweep_count(local_counts, robust_quantile)
    if target_count <= 0:
        layout_debug['failed_reason'] = 'target_count_invalid'
        return None, layout_debug
    layout_debug['local_sweep_counts_raw'] = [int(item) for item in local_counts]
    layout_debug['local_sweep_counts_sorted'] = sorted(int(item) for item in local_counts)
    layout_debug['target_sweep_count'] = int(target_count)

    center_reference_path = smooth_center_reference_path(tuple(tuple(item['center_point_rc']) for item in anchor_infos), window_radius=2)
    stable_normals = tuple(normal_from_tangent(estimate_local_tangent(center_reference_path, idx), side_sign=1) for idx in range(len(center_reference_path)))
    center_index = int((target_count - 1) // 2)
    center_offsets = solve_offset_sequence_for_side(
        anchor_infos=anchor_infos,
        target_offsets=tuple(0.0 for _ in anchor_infos),
        sampling_step_px=sampling_step_px,
        previous_sequence=None,
        debug_key='center_offset_sequence_px',
        layout_debug=layout_debug,
    )

    ordered_sequences: list[tuple[float, ...]] = []
    negative_sequences: list[tuple[float, ...]] = []
    previous = center_offsets
    for level in range(1, center_index + 1):
        previous = solve_offset_sequence_for_side(
            anchor_infos=anchor_infos,
            target_offsets=tuple(value - float(sampling_step_px) for value in previous),
            sampling_step_px=sampling_step_px,
            previous_sequence=previous,
            debug_key=f'negative_level_{level}_offset_sequence_px',
            layout_debug=layout_debug,
        )
        negative_sequences.append(previous)
    ordered_sequences.extend(reversed(negative_sequences))
    ordered_sequences.append(center_offsets)

    previous = center_offsets
    for level in range(1, int(target_count - center_index)):
        previous = solve_offset_sequence_for_side(
            anchor_infos=anchor_infos,
            target_offsets=tuple(value + float(sampling_step_px) for value in previous),
            sampling_step_px=sampling_step_px,
            previous_sequence=previous,
            debug_key=f'positive_level_{level}_offset_sequence_px',
            layout_debug=layout_debug,
        )
        ordered_sequences.append(previous)

    sweep_specs: list[dict[str, Any]] = []
    for sweep_index, sequence in enumerate(ordered_sequences):
        path_points = tuple(
            point_at_normal_offset(center_reference_path[idx], stable_normals[idx], int(round(offset_px)))
            for idx, offset_px in enumerate(sequence)
        )
        anchor_points = tuple(tuple(item['anchor_rc']) for item in anchor_infos)
        offset_profile = tuple(float(item) for item in sequence)
        path_points, anchor_points, offset_profile = shrink_head_and_tail_to_avoid_segment_intersection(path_points, anchor_points, offset_profile)
        # offset 后的 sweep 点列在拐角处仍可能出现局部 chord 变短。
        # 正式输出的 `path_rc` 本身必须收尾完整且点距均匀，所以这里在最终点列上再做固定点数弧长均匀化。
        # 点数不变，后续 sweep_id / port rank / cadence 仍能按原 sweep 粒度稳定消费。
        path_points = resample_reference_path_to_uniform_count(path_points, len(path_points))
        path_length_px = path_length_euclidean(path_points)
        if len(path_points) < 2 or path_length_px <= 1.0:
            continue
        if sweep_index == center_index:
            side_label, side_level = 'center', 0
        elif sweep_index > center_index:
            side_label, side_level = 'positive', int(sweep_index - center_index)
        else:
            side_label, side_level = 'negative', int(center_index - sweep_index)
        sweep_specs.append(
            {
                'path_rc': [list(point) for point in path_points],
                'anchor_points_rc': [list(point) for point in anchor_points],
                'offset_profile_px': [float(item) for item in offset_profile],
                'side_label': side_label,
                'side_level': int(side_level),
                'path_length_px': float(path_length_px),
                'target_count': int(target_count),
                'anchor_count': int(len(anchor_infos)),
            }
        )
    layout_debug['center_reference_path_rc'] = [list(point) for point in center_reference_path]
    layout_debug['stable_normal_vecs'] = [list(item) for item in stable_normals]
    layout_debug['mean_offsets_px'] = [float(np.mean(spec['offset_profile_px'])) if spec['offset_profile_px'] else 0.0 for spec in sweep_specs]
    layout_debug['center_sweep_index'] = int(center_index)
    layout_debug['final_sweep_count_generated'] = int(len(sweep_specs))
    return (sweep_specs or None), layout_debug



__all__ = (
    'build_lane_sweep_specs',
    'collect_lane_anchor_layouts',
    'initialize_layout_debug',
    'segments_intersect',
    'shrink_head_and_tail_to_avoid_segment_intersection',
)
