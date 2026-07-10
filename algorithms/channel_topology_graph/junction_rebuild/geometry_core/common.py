"""交汇几何核心的公共类型与基础工具。"""

from __future__ import annotations

import collections
from dataclasses import dataclass


@dataclass(slots=True)
class ExitTrace:
    """单条 outward exit 的截断结果。"""

    old_center_rc: tuple[int, int]
    exit_index: int
    entry_rc: tuple[int, int]
    cut_index: int
    cut_point_rc: tuple[int, int]
    path_rc: list[tuple[int, int]]
    suffix_path_rc: list[tuple[int, int]]
    stable_theta_deg: float


@dataclass(slots=True)
class BranchDirection:
    """从当前节点中心指向单条 outward branch 的稳定方向。"""

    segment_id: int
    theta_deg: float
    theta_rad: float
    probe_a_rc: tuple[int, int]
    probe_b_rc: tuple[int, int]
    path_rc: list[tuple[int, int]]


@dataclass(slots=True)
class SectorModel:
    """两个相邻 branch 之间的支撑扇区评估结果。"""

    sector_index: int
    start_theta_deg: float
    end_theta_deg: float
    width_deg: float
    center_theta_deg: float
    hit_points_rc: list[tuple[int, int]]
    hit_distances_px: list[float]
    hit_angles_deg: list[float]
    min_hit_distance_px: float
    mean_hit_distance_px: float
    std_hit_distance_px: float
    min_relpos: float
    linearity: float
    span_px: float
    thickness_px: float
    relative_span: float
    focus_score: float
    interior_score: float
    edge_score: float
    corner_score: float
    chosen_type: str
    representative_point_rc: tuple[int, int] | None
    edge_endpoints_rc: list[tuple[int, int]]


@dataclass(slots=True)
class CandidateEval:
    """单个中心候选点在 support/polygon 竞争下的综合结果。"""

    center_rc: tuple[int, int]
    score: float
    edge_count: int
    polygon_vertices_rc: list[tuple[int, int]]
    sectors: list[SectorModel]


OFFSETS8: tuple[tuple[int, int], ...] = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
)
RING8: tuple[tuple[int, int], ...] = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, 1), (1, 1), (1, 0),
    (1, -1), (0, -1),
)


def neighbors8(rc: tuple[int, int]) -> list[tuple[int, int]]:
    """返回一个像素的 8 邻域。"""

    # 邻域顺序固定，便于 BFS 和局部几何逻辑保持一致。
    r, c = rc
    return [(r + dr, c + dc) for dr, dc in OFFSETS8]


def to_local(rc: tuple[int, int], r0: int, c0: int) -> tuple[int, int]:
    """把全局坐标转为局部窗口坐标。"""

    # 局部窗口原点固定取 crop 左上角。
    return (int(rc[0] - r0), int(rc[1] - c0))


def to_global(rc: tuple[int, int], r0: int, c0: int) -> tuple[int, int]:
    """把局部窗口坐标转回全局坐标。"""

    # 全局恢复与 `to_local` 保持完全对称。
    return (int(rc[0] + r0), int(rc[1] + c0))


def wrap_deg(angle_deg: float) -> float:
    """把任意角度归一化到 [0, 360)。"""

    # 统一角度环空间表达，避免 sector/branch 比较时混入负角。
    value = float(angle_deg) % 360.0
    if value < 0.0:
        value += 360.0
    # 输出始终落在标准半开环区间内。
    return value


def angle_ccw_delta_deg(start_deg: float, end_deg: float) -> float:
    """计算从起始角逆时针转到终止角的夹角。"""

    # 逆时针夹角统一在 [0, 360) 中表达。
    return (wrap_deg(end_deg) - wrap_deg(start_deg)) % 360.0


def clamp01(value: float) -> float:
    """把分数裁到 [0, 1]。"""

    # 支撑评分类指标统一落到标准分数区间。
    return max(0.0, min(1.0, float(value)))


def graph_distances(
    start: tuple[int, int],
    allowed: set[tuple[int, int]],
) -> tuple[dict[tuple[int, int], int], dict[tuple[int, int], tuple[int, int] | None]]:
    """在骨架像素图上做无权 geodesic 最短路。"""

    # BFS 足以表达这里的无权 geodesic 距离，不需要更复杂最短路算法。
    # `allowed` 直接编码可走像素集合，因此这层 helper 不关心外部 mask 形状。
    dist = {start: 0}
    prev: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    queue = collections.deque([start])
    while queue:
        cur = queue.popleft()
        # 只在允许像素集合内扩展，保证结果始终局限在局部骨架上。
        # 一旦某点进了 `dist`，说明它的最短 geodesic 已经确定。
        for nxt in neighbors8(cur):
            if nxt in allowed and nxt not in dist:
                dist[nxt] = dist[cur] + 1
                prev[nxt] = cur
                queue.append(nxt)
    # 同时返回距离表和前驱表，便于调用方既能筛选又能恢复路径。
    # `dist` 与 `prev` 的键空间保持完全一致。
    # 对于不可达点，两张表都不会出现对应条目。
    return dist, prev


def path_from_prev(
    goal: tuple[int, int],
    prev: dict[tuple[int, int], tuple[int, int] | None],
) -> list[tuple[int, int]]:
    """根据前驱表恢复路径。"""

    # 从 goal 反向追父节点，再整体翻转成正向路径。
    path: list[tuple[int, int]] = []
    cur: tuple[int, int] | None = goal
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    # 路径恢复不做合法性检查，默认前驱表来自同一轮 BFS。
    # 调用方若传入不存在的 goal，会在字典访问处自然暴露错误。
    # 因而这个 helper 保持非常薄，只负责恢复顺序。
    return path[::-1]


def build_local_context(
    old_points_global: list[tuple[int, int]],
    new_center_global: tuple[int, int],
    skeleton_points_global: set[tuple[int, int]],
    shape_hw: tuple[int, int],
    margin_px: int,
) -> dict[str, object]:
    """构造节点局部工作域。"""

    # 局部窗口既要覆盖旧中心，也要覆盖新中心，并留出 margin 供支撑评估使用。
    # rows/cols 在这里统一从所有旧点和新中心汇总，避免窗口只围绕单一点构建。
    # 这样 clustered exit 的多旧点场景不会把局部裁剪框收得过紧。
    rows = [point_rc[0] for point_rc in old_points_global] + [new_center_global[0]]
    cols = [point_rc[1] for point_rc in old_points_global] + [new_center_global[1]]
    r0 = max(0, min(rows) - margin_px)
    c0 = max(0, min(cols) - margin_px)
    r1 = min(shape_hw[0], max(rows) + margin_px + 1)
    c1 = min(shape_hw[1], max(cols) + margin_px + 1)
    # 骨架点集先裁到局部窗口，再统一转到 local 坐标系。
    # 这一步只保留窗口里的真值骨架，避免后续 support 评估扫描无关区域。
    # local 坐标后续会直接拿去做 polygon、射线和 branch 方向分析。
    original_points_local = {
        (point_rc[0] - r0, point_rc[1] - c0)
        for point_rc in skeleton_points_global
        if r0 <= point_rc[0] < r1 and c0 <= point_rc[1] < c1
    }
    old_points_local = [to_local(point_rc, r0, c0) for point_rc in old_points_global]
    # 返回字典统一收口局部窗口、旧点、新点和局部骨架真值。
    # 之后 clustered/single-exit/support 逻辑都基于这份上下文工作。
    # 局部窗口边界也一起保留，便于 local/global 坐标来回转换。
    # 这也是 geometry core 各子模块共享的唯一局部世界描述。
    # 调用方不需要再自己拼装局部窗口字段，直接消费这份字典即可。
    # 这样局部窗口口径一旦修正，只需要改这一处即可全链生效。
    return {
        "crop_box": [int(r0), int(r1), int(c0), int(c1)],
        "original_points_local": original_points_local,
        "old_points_global": old_points_global,
        "old_points_local": old_points_local,
        "new_center_global": new_center_global,
        "new_center_local": to_local(new_center_global, r0, c0),
    }


__all__ = (
    "ExitTrace",
    "BranchDirection",
    "SectorModel",
    "CandidateEval",
    "_OFFSETS8",
    "_RING8",
    "neighbors8",
    "to_local",
    "to_global",
    "wrap_deg",
    "angle_ccw_delta_deg",
    "clamp01",
    "graph_distances",
    "path_from_prev",
    "build_local_context",
)
