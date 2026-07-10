"""交汇支撑求解中的 branch 与截断调试辅助。"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from .common import BranchDirection, ExitTrace, wrap_deg
from ..initial_node_edge.edge_paths import densify_line_rc as densify_line_rc_int


def build_single_branch_direction(
    *,
    segment_id: int,
    new_center_rc: tuple[int, int],
    exit_trace: ExitTrace,
) -> BranchDirection:
    """从单条 exit trace 构造 branch 方向对象。"""

    cut_point_rc = exit_trace.cut_point_rc
    theta_rad = math.atan2(float(cut_point_rc[0] - new_center_rc[0]), float(cut_point_rc[1] - new_center_rc[1]))
    theta_deg = wrap_deg(math.degrees(theta_rad))
    return BranchDirection(
        segment_id=int(segment_id),
        theta_deg=theta_deg,
        theta_rad=theta_rad,
        probe_a_rc=new_center_rc,
        probe_b_rc=cut_point_rc,
        path_rc=exit_trace.suffix_path_rc,
    )


def build_adjusted_local_path(
    *,
    new_center_rc: tuple[int, int],
    cut_point_rc: tuple[float, float],
    suffix_path_rc: list[tuple[int, int]],
) -> list[tuple[float, float]]:
    """构造从新中心重新接上 suffix 的局部调试路径。"""

    connector = densify_line_rc_int(
        (int(new_center_rc[0]), int(new_center_rc[1])),
        (int(round(cut_point_rc[0])), int(round(cut_point_rc[1]))),
    )
    return connector + [(float(r), float(c)) for r, c in suffix_path_rc[1:]]


def build_branches_from_cut_points(
    new_center_rc: tuple[int, int],
    exits: list[ExitTrace],
) -> list[BranchDirection]:
    """把截断点结果整理成 support 求解需要的 branch 方向。"""

    # 每条 exit 都会变成一条从新中心指向 cut point 的 branch 方向。
    # 这一步相当于把“出口几何”投影成“支撑分析关心的方向束”。
    # 后续 sector 评分并不关心旧 path 的全部细节，而更关心这些统一方向描述。
    branches: list[BranchDirection] = []
    for index, exit_trace in enumerate(exits):
        # `suffix_path_rc` 保留 cut 之后的 outward 路径，供支撑扇区直接使用。
        # probe_a/probe_b 则直接描述“从中心指向 cut 点”的基础方向线段。
        # 这使 branch 既有角度，也有后续继续向外延伸的路径真值。
        branches.append(
            build_single_branch_direction(
                segment_id=index,
                new_center_rc=new_center_rc,
                exit_trace=exit_trace,
            )
        )
    # 最终按角度排序，便于 sector 评估直接按环顺序消费。
    # 这一步不改 branch 几何，只整理消费顺序。
    # 因而 `segment_id` 仍然保留原 exit 序号，而非排序后位置。
    branches.sort(key=lambda item: float(item.theta_deg))
    return branches


def truncate_using_cut_points(
    best_eval,
    exits: list[ExitTrace],
    new_center_rc: tuple[int, int],
) -> list[dict[str, object]]:
    """把正式截断点和调整后局部路径整理成调试项。"""

    # 调试项同时保留原始 path、suffix path 和 center->cut connector。
    # 这个 helper 只负责生成调试视图，不回写任何正式拓扑结果。
    items: list[dict[str, object]] = []
    for index, exit_trace in enumerate(exits):
        cut_point_rc = tuple(map(float, exit_trace.cut_point_rc))
        # connector 是从新中心到截断点的局部直连路径，用于调试可视化。
        # 它让人眼能直接看出“新中心重新接到旧 branch”之后的几何连续性。
        adjusted = build_adjusted_local_path(
            new_center_rc=new_center_rc,
            cut_point_rc=cut_point_rc,
            suffix_path_rc=exit_trace.suffix_path_rc,
        )
        # adjusted_local_path_rc 表达的是“从新中心重新接上 suffix 后”的局部路径。
        # 这份调试视图不回写正式 edge，只用于人工核查截断效果。
        # 输出字段全部转成 JSON 友好的基础类型，便于直接落 debug。
        # 这里保留 old_center / entry / cut / suffix 四类关键点位，便于排查截断偏差。
        # 因而同一条 exit 在 debug 中能完整看到“截断前后”的路径关系。
        # 这对核查新中心连接是否过短或过长尤其有用。
        items.append(
            {
                "exit_index": int(index),
                "old_center_rc": [int(exit_trace.old_center_rc[0]), int(exit_trace.old_center_rc[1])],
                "entry_rc": [int(exit_trace.entry_rc[0]), int(exit_trace.entry_rc[1])],
                "path_rc": [[float(r), float(c)] for r, c in exit_trace.path_rc],
                "cut_point_rc": [float(cut_point_rc[0]), float(cut_point_rc[1])],
                "cut_index": int(exit_trace.cut_index),
                "stable_theta_deg": round(float(exit_trace.stable_theta_deg), 4),
                "suffix_path_rc": [[float(r), float(c)] for r, c in exit_trace.suffix_path_rc],
                "adjusted_local_path_rc": [[float(r), float(c)] for r, c in adjusted],
            }
        )
    # 最终结果是纯调试列表，不参与正式几何闭环。
    return items


def ray_first_hit(
    free_mask: np.ndarray,
    center_rc: tuple[int, int],
    theta_rad: float,
    max_radius_px: int,
) -> tuple[tuple[int, int] | None, float | None]:
    """沿一条射线找自由空间里的第一处障碍命中。"""

    # 射线按像素步进前进，直到撞墙或出界。
    # 这里显式沿用离散像素语义，而不是连续几何交点语义。
    # 这样命中结果可以直接和 free_mask 栅格判断保持一致。
    r0, c0 = center_rc
    dr = float(math.sin(theta_rad))
    dc = float(math.cos(theta_rad))
    last_pt: tuple[int, int] | None = None
    for step in range(1, max_radius_px + 1):
        rr = int(round(r0 + dr * step))
        cc = int(round(c0 + dc * step))
        if rr < 0 or rr >= free_mask.shape[0] or cc < 0 or cc >= free_mask.shape[1]:
            break
        pt = (rr, cc)
        # 浅角射线经 round 后可能多次落到同一个像素，这里先去重。
        # 去重后每个像素只检查一次，步长含义也更稳定。
        if pt == last_pt:
            continue
        last_pt = pt
        if free_mask[rr, cc] == 0:
            # 一旦命中障碍，返回命中点和对应步长。
            return pt, float(step)
    # 全程未命中则返回空值，交给上层决定是否视为开放扇区。
    # last_pt 去重是为了避免浅角射线因 round 造成重复采样。
    # 因而这条射线 helper 的输出天然带有“最近命中优先”的语义。
    # 调用方可用空值判定“当前方向在给定半径内没有支撑边界”。
    # 这类无命中结果通常会在 sector 评估里形成较弱支撑信号。
    return None, None


@lru_cache(maxsize=32)
def _ray_offset_table(
    *,
    ray_step_deg: float,
    max_radius_px: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Precompute floating ray deltas for one ray setting."""

    angles_deg = np.arange(0.0, 360.0, float(ray_step_deg), dtype=np.float64)
    steps = np.arange(1, int(max_radius_px) + 1, dtype=np.float64)
    theta_rad = np.deg2rad(angles_deg)
    row_deltas = np.sin(theta_rad[:, None]) * steps[None, :]
    col_deltas = np.cos(theta_rad[:, None]) * steps[None, :]
    step_values = np.broadcast_to(steps.astype(np.float32)[None, :], row_deltas.shape)
    unique_mask = np.ones(row_deltas.shape, dtype=bool)
    return angles_deg.astype(np.float32), row_deltas, col_deltas, step_values, unique_mask


def ray_first_hits(
    free_mask: np.ndarray,
    center_rc: tuple[int, int],
    *,
    ray_step_deg: float,
    max_radius_px: int,
) -> list[tuple[float, tuple[int, int] | None, float | None]]:
    """Return first obstacle hits for all rays around one center."""

    r0, c0 = int(center_rc[0]), int(center_rc[1])
    height, width = free_mask.shape[:2]
    angles_deg, row_deltas, col_deltas, steps, _unique_mask = _ray_offset_table(
        ray_step_deg=float(ray_step_deg),
        max_radius_px=int(max_radius_px),
    )
    rows = np.rint(float(r0) + row_deltas).astype(np.int32)
    cols = np.rint(float(c0) + col_deltas).astype(np.int32)
    unique_mask = np.ones(rows.shape, dtype=bool)
    if rows.shape[1] > 1:
        unique_mask[:, 1:] = (rows[:, 1:] != rows[:, :-1]) | (cols[:, 1:] != cols[:, :-1])
    valid = (rows >= 0) & (rows < height) & (cols >= 0) & (cols < width)
    sampled = free_mask[np.clip(rows, 0, height - 1), np.clip(cols, 0, width - 1)]
    blocked = valid & unique_mask & (sampled == 0)
    has_hit = np.any(blocked, axis=1)
    hit_indices = np.argmax(blocked, axis=1)
    hits: list[tuple[float, tuple[int, int] | None, float | None]] = []
    for ray_index, theta_deg in enumerate(angles_deg.tolist()):
        if not bool(has_hit[ray_index]):
            hits.append((float(theta_deg), None, None))
            continue
        step_index = int(hit_indices[ray_index])
        hits.append(
            (
                float(theta_deg),
                (int(rows[ray_index, step_index]), int(cols[ray_index, step_index])),
                float(steps[ray_index, step_index]),
            )
        )
    return hits


__all__ = (
    "build_branches_from_cut_points",
    "ray_first_hits",
    "truncate_using_cut_points",
    "ray_first_hit",
)
