"""Coverage lane sweep 法向几何与横向区间 helper。"""

from __future__ import annotations

import numpy as np

from .lane_common import normalize_vector


def collect_valid_offsets_along_normal(
    base_point_rc: tuple[float, float],
    normal_vec: tuple[float, float],
    allowed_domain_mask: np.ndarray,
    free_mask: np.ndarray,
    obstacle_distance_px: np.ndarray,
    effective_min_clearance_px: float,
    max_search_px: int,
) -> list[int]:
    """收集法向搜索范围内所有合法 offset。"""

    valid_offsets: list[int] = []
    for offset_px in range(-max_search_px, max_search_px + 1):
        row = int(round(float(base_point_rc[0]) + float(normal_vec[0]) * float(offset_px)))
        col = int(round(float(base_point_rc[1]) + float(normal_vec[1]) * float(offset_px)))
        if row < 0 or row >= free_mask.shape[0] or col < 0 or col >= free_mask.shape[1]:
            # 法向采样点一旦越出地图边界，就不能作为合法 sweep 中心。
            continue
        if allowed_domain_mask[row, col] == 0 or free_mask[row, col] == 0:
            # 必须同时满足“仍在当前 coverage lane 允许域里”以及“当前像素可通行”。
            # 任一条件不成立，都说明这个 offset 不能成为正式 sweep 中心。
            continue
        if float(obstacle_distance_px[row, col]) < float(effective_min_clearance_px):
            # 到障碍的净空不足时，虽然像素可能还是 free，但不满足正式 sweep 的安全净距要求。
            continue
        valid_offsets.append(int(offset_px))
    return valid_offsets


def solve_primary_offset_run(
    base_point_rc: tuple[float, float],
    normal_vec: tuple[float, float],
    allowed_domain_mask: np.ndarray,
    free_mask: np.ndarray,
    obstacle_distance_px: np.ndarray,
    effective_min_clearance_px: float,
    max_search_px: int,
) -> tuple[int, int] | None:
    """求锚点法向上的主连续合法偏移段。"""

    valid_offsets = collect_valid_offsets_along_normal(
        base_point_rc=base_point_rc,
        normal_vec=normal_vec,
        allowed_domain_mask=allowed_domain_mask,
        free_mask=free_mask,
        obstacle_distance_px=obstacle_distance_px,
        effective_min_clearance_px=effective_min_clearance_px,
        max_search_px=max_search_px,
    )
    if not valid_offsets:
        # 一个锚点沿法向完全找不到合法 offset 时，
        # 说明这一截局部横向区间已不存在可用 sweep 带宽。
        return None
    runs: list[tuple[int, int]] = []
    run_start = run_end = valid_offsets[0]
    for offset_px in valid_offsets[1:]:
        if offset_px == run_end + 1:
            # 连续整数 offset 说明它们属于同一段无断裂的合法横向区间。
            run_end = offset_px
            continue
        runs.append((int(run_start), int(run_end)))
        run_start = run_end = offset_px
    runs.append((int(run_start), int(run_end)))
    return min(
        runs,
        key=lambda item: (
            # 优先保留包含 0 的区间；若都不含 0，则选距离中心最近的那段。
            0.0 if item[0] <= 0 <= item[1] else float(min(abs(item[0]), abs(item[1]))),
            # 在中心性相近时，更长的连续区间更稳定，因此这里对长度取负号让它优先。
            -(item[1] - item[0]),
        ),
    )


def count_uniform_sweeps_for_interval(offset_min_px: int, offset_max_px: int, max_spacing_px: int) -> int:
    """根据局部横向区间求可均匀铺设的 sweep 条数。"""

    width_px = max(0.0, float(offset_max_px - offset_min_px))
    return 1 if width_px <= 1e-6 else int(max(1, int(np.ceil(width_px / float(max_spacing_px))) + 1))


def solve_robust_target_sweep_count(local_counts: list[int], quantile: float) -> int:
    """对局部 sweep 数做稳健分位数统计。"""

    if not local_counts:
        # 没有任何局部样本时，无法稳健估计目标条数，返回 0 让上层按“当前区域不可铺设”处理。
        return 0
    sorted_counts = sorted(int(item) for item in local_counts)
    clipped_quantile = min(1.0, max(0.0, float(quantile)))
    rank = max(0, min(len(sorted_counts) - 1, int(np.ceil(clipped_quantile * len(sorted_counts))) - 1))
    return int(sorted_counts[rank])


def build_uniform_offsets_in_interval(offset_min_px: int, offset_max_px: int, count: int) -> tuple[int, ...]:
    """在单个横向区间内按统一条数回填均匀 offsets。"""

    if count <= 0:
        # 条数非正时，不应返回任何 offset。
        return ()
    if count == 1:
        # 单条 sweep 时优先让它穿过中心 0；若 0 不在区间内，再退回区间中点。
        return (0,) if offset_min_px <= 0 <= offset_max_px else (int(round((float(offset_min_px) + float(offset_max_px)) * 0.5)),)
    return tuple(int(round(item)) for item in np.linspace(float(offset_min_px), float(offset_max_px), int(count)).tolist())


def point_at_normal_offset(base_point_rc: tuple[float, float], normal_vec: tuple[float, float], offset_px: int) -> tuple[float, float]:
    """按法向 offset 生成当前 sweep 点。"""

    return (
        float(base_point_rc[0]) + float(normal_vec[0]) * float(offset_px),
        float(base_point_rc[1]) + float(normal_vec[1]) * float(offset_px),
    )


def ordered_normal_search_offsets(normal_search_px: int) -> list[int]:
    """按既定规则生成法向搜索顺序。"""

    offsets = [0]
    for value in range(1, normal_search_px + 1):
        # 搜索顺序固定成 0, +1, -1, +2, -2 ...
        # 目的是优先保留靠近 anchor 的局部中心，不让单侧偏移先抢走候选。
        offsets.extend([value, -value])
    return offsets


def search_legal_point_along_normal(
    anchor_rc: tuple[float, float],
    normal_vec: tuple[float, float],
    free_mask: np.ndarray,
    obstacle_distance_px: np.ndarray,
    effective_min_clearance_px: float,
    normal_search_px: int,
) -> tuple[float, float] | None:
    """沿局部法向搜索第一个合法中心点。"""

    for offset in ordered_normal_search_offsets(normal_search_px):
        row = int(round(float(anchor_rc[0]) + float(normal_vec[0]) * float(offset)))
        col = int(round(float(anchor_rc[1]) + float(normal_vec[1]) * float(offset)))
        if row < 0 or row >= free_mask.shape[0] or col < 0 or col >= free_mask.shape[1]:
            continue
        if free_mask[row, col] == 0:
            # 这里找的是“第一个可作为中心点的合法像素”，非 free 区域不能拿来做回退中心。
            continue
        if float(obstacle_distance_px[row, col]) < float(effective_min_clearance_px):
            # 即便 free，也不能牺牲净空约束去强行放置 sweep 中心。
            continue
        # 第一个满足条件的点就是当前 anchor 的正式回退中心，不再继续向更远偏移搜索。
        return float(row), float(col)
    return None


def estimate_local_tangent(
    path_rc: tuple[tuple[float, float], ...] | list[tuple[float, float]],
    index: int,
) -> tuple[float, float]:
    """估计当前点的局部切向。"""

    if len(path_rc) <= 1:
        return (1.0, 0.0)
    if index <= 0:
        start_point, end_point = path_rc[0], path_rc[1]
    elif index >= len(path_rc) - 1:
        start_point, end_point = path_rc[-2], path_rc[-1]
    else:
        start_point, end_point = path_rc[index - 1], path_rc[index + 1]
    return normalize_vector(float(end_point[0]) - float(start_point[0]), float(end_point[1]) - float(start_point[1]))


def normal_from_tangent(tangent_vec: tuple[float, float], side_sign: int) -> tuple[float, float]:
    """由切向得到局部法向。"""

    tangent_row, tangent_col = tangent_vec
    normal_row, normal_col = -float(tangent_col), float(tangent_row)
    if side_sign < 0:
        normal_row, normal_col = -normal_row, -normal_col
    return normalize_vector(normal_row, normal_col)


def solve_main_direction(path_rc: tuple[tuple[float, float], ...]) -> str:
    """根据 outer_path 的整体端点方向求 coverage 主方向。"""

    if len(path_rc) < 2:
        return 'UNKNOWN'
    row_delta = abs(float(path_rc[-1][0]) - float(path_rc[0][0]))
    col_delta = abs(float(path_rc[-1][1]) - float(path_rc[0][1]))
    return 'HORIZONTAL' if col_delta >= row_delta else 'VERTICAL'


__all__ = (
    'build_uniform_offsets_in_interval',
    'collect_valid_offsets_along_normal',
    'count_uniform_sweeps_for_interval',
    'estimate_local_tangent',
    'normal_from_tangent',
    'ordered_normal_search_offsets',
    'point_at_normal_offset',
    'search_legal_point_along_normal',
    'solve_main_direction',
    'solve_primary_offset_run',
    'solve_robust_target_sweep_count',
)
