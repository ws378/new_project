"""交汇 exit 路径恢复与截断规则。"""

from __future__ import annotations

import collections
import math

import numpy as np

from .common import (
    OFFSETS8,
    ExitTrace,
    path_from_prev,
    to_global,
    wrap_deg,
)
from .math import angle_diff_deg, cumulative_lengths, index_at_distance


def component_path_from_entry(
    comp_mask: np.ndarray,
    entry_local_rc: tuple[int, int],
    r0: int,
    c0: int,
) -> tuple[list[tuple[int, int]], float]:
    """从一个分量入口恢复到最远端的路径。"""

    # 组件恢复同样走 BFS，只不过这里边权取欧氏步长。
    # 输入是单个 component mask，因此这里天然不会跨分量串线。
    coords = np.argwhere(comp_mask > 0)
    comp_set = {tuple(map(int, rc)) for rc in coords}
    queue = collections.deque([entry_local_rc])
    parent = {entry_local_rc: None}
    dist = {entry_local_rc: 0.0}
    while queue:
        cur = queue.popleft()
        # 允许步进的范围严格限制在当前 component mask 内。
        # 八邻域步长直接按欧氏长度累加，使对角步不会被低估。
        for dr, dc in OFFSETS8:
            nxt = (cur[0] + dr, cur[1] + dc)
            if nxt not in comp_set or nxt in parent:
                continue
            parent[nxt] = cur
            dist[nxt] = dist[cur] + math.hypot(float(dr), float(dc))
            queue.append(nxt)
    # 终点定义为距入口最远点，用来代表该分量最 outward 的一端。
    end = max(dist, key=dist.get)
    path_local = path_from_prev(end, parent)
    # 输出路径统一恢复到全局坐标，并顺手去掉相邻重复点。
    # 终点选择“距入口最远点”，用来代表 outward 方向最稳定的一条路径。
    # 返回的长度仍是 local component 上累计出来的弧长。
    # 这使调用方既能得到路径，也能得到对应几何长度。
    # component 级路径恢复到这里结束，后续 cut 规则在更高层处理。
    # 因而这个 helper 的职责非常明确：恢复路径，不做截断。
    path_global = [to_global(point_rc, r0, c0) for point_rc in path_local]
    return dedupe_points(path_global), float(dist[end])


def dedupe_points(points_rc: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """去掉路径相邻重复点。"""

    # 只去除相邻近重复点，不做更激进的路径简化。
    out: list[tuple[int, int]] = []
    for point_rc in points_rc:
        point_int = (int(point_rc[0]), int(point_rc[1]))
        if not out or math.hypot(out[-1][0] - point_int[0], out[-1][1] - point_int[1]) > 1.0:
            out.append(point_int)
    # 这样保留下来的点序列仍然和原路径顺序严格一致。
    # 去重阈值取 1 像素，主要用于消掉离散化造成的相邻重复点。
    return out


def stable_heading_deg(points_rc: list[tuple[int, int]], i0: int, i1: int) -> float:
    """取路径上一段的稳定方向角。"""

    # 方向角统一按图像坐标 `(dr, dc)` 解释，再包到 [0, 360)。
    point_a = points_rc[i0]
    point_b = points_rc[i1]
    # 调用方保证 `i1` 位于 `i0` 之后，因此方向始终沿 outward path 前进。
    return wrap_deg(math.degrees(math.atan2(float(point_b[0] - point_a[0]), float(point_b[1] - point_a[1]))))


def cut_index_by_stability(
    path_rc: list[tuple[int, int]],
    min_cut_px: float,
    probe_px: float,
    verify_px: float,
    stable_angle_deg: float,
) -> int:
    """按稳定方向规则求截断点索引。"""

    # 极短路径没有足够 probe 空间时，直接退到末端附近。
    if len(path_rc) < 3:
        # 点数太少时无法形成“probe 段 + verify 段”，只能把 cut 放到末端附近。
        return max(0, len(path_rc) - 1)
    cumlen = cumulative_lengths(path_rc)
    last_valid = len(path_rc) - 1
    for idx in range(len(path_rc) - 2):
        # 截断点至少要超过最小切断距离，避免离中心太近。
        if cumlen[idx] < min_cut_px:
            # 还没走出最小切断距离的部分，哪怕方向稳定也不能当正式 cut。
            continue
        idx_b = max(index_at_distance(cumlen, cumlen[idx] + probe_px), min(last_valid, idx + 1))
        idx_c = max(index_at_distance(cumlen, cumlen[idx] + probe_px + verify_px), min(last_valid, idx_b + 1))
        heading_a = stable_heading_deg(path_rc, idx, idx_b)
        heading_b = stable_heading_deg(path_rc, idx_b, idx_c)
        # 当前后两段方向已经足够稳定时，就把中间 probe 点作为 cut。
        if angle_diff_deg(heading_a, heading_b) <= stable_angle_deg:
            return idx_b
    # 若始终找不到稳定段，就退回一条相对保守的 fallback 距离。
    # 这个 fallback 同时受最小切断距离和尾部预留距离双重约束。
    # 它的目标不是最优，而是尽量避免 cut 落在极端不稳定位置。
    # 所以这里宁可保守一点，也不把 cut 推到 branch 根部附近。
    # fallback 一旦生效，说明路径上没有找到足够稳定的 probe 段。
    # 这种情况在非常短或弯折剧烈的 branch 上更常见。
    fallback = index_at_distance(
        cumlen,
        min(max(min_cut_px, 0.35 * cumlen[-1]), max(0.0, cumlen[-1] - 3.0)),
    )
    return max(1, min(last_valid, fallback))


def exit_from_branch_path(
    branch_id: int,
    old_center_global: tuple[int, int],
    new_center_global: tuple[int, int],
    path_global: list[tuple[int, int]],
    entry_global: tuple[int, int],
    min_cut_px: float,
    probe_px: float,
    verify_px: float,
    stable_angle_deg: float,
    extra_push_px: float = 0.0,
) -> ExitTrace:
    """从单条 outward path 上解出正式截断点。"""

    # 先按稳定性规则拿到 cut 索引，再按需要额外向外推一点。
    # 这里始终围绕 path_global 工作，避免 local/global path 混用后 cut 语义漂移。
    # 因而最终 cut point、suffix 和 stable_theta 都直接落在全局坐标系。
    cut_idx = cut_index_by_stability(path_global, min_cut_px, probe_px, verify_px, stable_angle_deg)
    if extra_push_px > 0.0 and len(path_global) >= 2:
        cumlen = cumulative_lengths(path_global)
        pushed_idx = index_at_distance(cumlen, cumlen[cut_idx] + extra_push_px)
        # extra push 只允许把 cut 往外推，不允许回退到更靠近根部的位置。
        # 这样 clustered exit 在支撑不足时可以增大外推，但不会破坏最小稳定 cut。
        cut_idx = max(cut_idx, min(len(path_global) - 1, pushed_idx))
    cut_point_rc = path_global[cut_idx]
    # stable_theta_deg 表达的是从新中心看向 cut point 的正式方向。
    # 这也是后续按角度排序和 sector 环顺序的统一依据。
    # suffix_path_rc 则表达从 cut 点开始继续向外的剩余路径。
    # ExitTrace 里同时保留原 path 和 suffix，方便后续 support/debug 各取所需。
    # 因而 ExitTrace 是 single-exit / clustered-exit 共用的正式出口载体。
    # 这使两条 exit 提取逻辑在后续模块里可以共享同一消费接口。
    stable_theta_deg = wrap_deg(
        math.degrees(
            math.atan2(
                float(cut_point_rc[0] - new_center_global[0]),
                float(cut_point_rc[1] - new_center_global[1]),
            )
        )
    )
    # 这里不再做排序，排序留给更高层统一按 stable_theta_deg 处理。
    # 本函数只负责把一条 branch path 转成单条正式出口真值。
    # 输出一旦生成，就视为该 branch 的正式 cut 解释。
    return ExitTrace(
        old_center_rc=old_center_global,
        exit_index=int(branch_id),
        entry_rc=entry_global,
        cut_index=int(cut_idx),
        cut_point_rc=cut_point_rc,
        path_rc=path_global,
        suffix_path_rc=path_global[cut_idx:],
        stable_theta_deg=stable_theta_deg,
    )


__all__ = (
    "component_path_from_entry",
    "dedupe_points",
    "stable_heading_deg",
    "cut_index_by_stability",
    "exit_from_branch_path",
)
