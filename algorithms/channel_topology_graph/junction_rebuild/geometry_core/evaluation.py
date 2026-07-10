"""交汇 support/polygon 联合评估逻辑。"""

from __future__ import annotations

import math

import numpy as np

from .branch_support import build_branches_from_cut_points, ray_first_hits, truncate_using_cut_points
from .common import CandidateEval, ExitTrace, SectorModel, angle_ccw_delta_deg, wrap_deg
from .math import polygon_centroid_rc
from .sector_fit import fit_sector_model
from .sector_refine import refine_edge_endpoints_from_neighbors


def support_polygon_vertices(sectors: list[SectorModel], center_rc: tuple[int, int]) -> list[tuple[int, int]]:
    """由扇区 support 结果组装 polygon 顶点。"""

    # edge-like 扇区优先贡献一对端点，corner-like 扇区则贡献代表点。
    points: list[tuple[int, int]] = []
    for sector in sectors:
        if sector.chosen_type == "edge-like":
            points.extend(sector.edge_endpoints_rc)
        elif sector.representative_point_rc is not None:
            points.append(sector.representative_point_rc)
    # 少于三个顶点时无法组成有效 polygon。
    # 这种情况通常意味着支撑扇区不足以围出完整节点边界。
    if len(points) < 3:
        return []
    cr, cc = center_rc
    # 顶点先按相对中心的极角排序，保证 polygon 顶点环顺序稳定。
    points = sorted(
        points,
        key=lambda point_rc: wrap_deg(math.degrees(math.atan2(float(point_rc[0] - cr), float(point_rc[1] - cc)))),
    )
    dedup: list[tuple[int, int]] = []
    for point_rc in points:
        # 靠得过近的相邻点合并掉，避免 support 噪声把 polygon 顶点数吹高。
        if not dedup or math.hypot(point_rc[0] - dedup[-1][0], point_rc[1] - dedup[-1][1]) > 4.0:
            dedup.append(point_rc)
    # 首尾若其实是同一点，也只保留一次。
    if len(dedup) >= 3 and math.hypot(dedup[0][0] - dedup[-1][0], dedup[0][1] - dedup[-1][1]) <= 4.0:
        dedup.pop()
    # 返回结果已经是稳定环顺序，可直接进入面积与质心计算。
    # 这一步不会再对顶点做几何平滑，只保证顺序和去重。
    # 如果某些 sector 完全不给顶点，这里也不会替它们做补点。
    # 因而 polygon 顶点质量完全取决于 sector 评估结果本身。
    return dedup


def polygon_area(points_rc: list[tuple[int, int]]) -> float:
    """计算 polygon 面积。"""

    # 少于三个点时面积按零处理。
    if len(points_rc) < 3:
        return 0.0
    # 先转成 `(x, y)`，再按标准鞋带公式计算。
    # 这里返回绝对面积，不保留顶点顺序的正负号信息。
    pts = np.asarray([[float(c), float(r)] for r, c in points_rc], dtype=np.float64)
    x = pts[:, 0]
    y = pts[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def evaluate_center_candidate(
    free_mask: np.ndarray,
    center_rc: tuple[int, int],
    branches,
    ray_step_deg: float,
    ray_max_radius_px: int,
    refined_center_rc: tuple[int, int],
) -> CandidateEval | None:
    """评估单个中心候选点。"""

    # 候选中心必须落在 mask 内部且位于自由空间。
    rr, cc = center_rc
    if rr < 0 or rr >= free_mask.shape[0] or cc < 0 or cc >= free_mask.shape[1]:
        return None
    if free_mask[rr, cc] == 0:
        # 中心候选落在障碍里时，后续所有射线统计都失去意义，必须整点淘汰。
        return None

    # sectors_meta 只保留相邻 branch 之间的角域边界。
    # 这些角域定义了当前中心候选下各扇区的责任范围。
    sectors_meta = []
    for index in range(len(branches)):
        sectors_meta.append((branches[index].theta_deg, branches[(index + 1) % len(branches)].theta_deg))
    # 分支数量越多，后续 sector 数量也越多。
    # 这里默认 branches 已经按 stable theta 排好序。

    # 沿 360 度均匀打射线，把命中点按 sector 分桶。
    # 射线越密，sector hit 分布越细，但代价也越高。
    hit_angles: list[float] = []
    hit_points: list[tuple[int, int]] = []
    hit_dists: list[float] = []
    for theta_deg, hit_rc, hit_dist in ray_first_hits(
        free_mask,
        center_rc,
        ray_step_deg=float(ray_step_deg),
        max_radius_px=int(ray_max_radius_px),
    ):
        if hit_rc is None or hit_dist is None:
            # 没命中障碍时，这条射线不给任何 sector 贡献样本。
            continue
        hit_angles.append(float(theta_deg))
        hit_points.append(hit_rc)
        hit_dists.append(float(hit_dist))

    assigned_sector = np.full(len(hit_angles), -1, dtype=np.int32)
    if hit_angles:
        hit_angle_array = np.asarray(hit_angles, dtype=np.float64)
        for index, (start_deg, end_deg) in enumerate(sectors_meta):
            span_deg = angle_ccw_delta_deg(start_deg, end_deg)
            # 空角域不参与分桶，直接跳过。
            if span_deg <= 0.0:
                continue
            delta = (hit_angle_array - wrap_deg(float(start_deg))) % 360.0
            mask = (assigned_sector < 0) & (delta >= 0.0) & (delta <= span_deg)
            assigned_sector[mask] = int(index)
        # 如果没有落入任何有效角域，这条射线就被自然丢弃。

    # 每个 sector 的桶数据再落成正式 SectorModel。
    # 没拿到 hit 的 sector 也会生成模型，只是内部统计会偏弱。
    sectors: list[SectorModel] = []
    for index, (start_deg, end_deg) in enumerate(sectors_meta):
        indices = np.flatnonzero(assigned_sector == int(index))
        angles = [hit_angles[int(item)] for item in indices.tolist()]
        points = [hit_points[int(item)] for item in indices.tolist()]
        dists = [hit_dists[int(item)] for item in indices.tolist()]
        # fit_sector_model 会把原始命中分布转成更稳定的结构化特征。
        sectors.append(
            fit_sector_model(
                sector_index=index,
                start_theta_deg=float(start_deg),
                end_theta_deg=float(end_deg),
                hit_angles_deg=angles,
                hit_points_rc=points,
                hit_distances_px=dists,
            )
        )

    # sector 端点先做一轮邻域修正，再进入 polygon/score 阶段。
    sectors = refine_edge_endpoints_from_neighbors(sectors, free_mask)
    polygon = support_polygon_vertices(sectors, center_rc)
    area = polygon_area(polygon)
    # 评分由 support 强度、polygon 合法性和若干惩罚项共同组成。
    # 其中 shift_penalty 抑制中心候选相对 refined center 的过大漂移。
    shift_penalty = 0.02 * math.hypot(center_rc[0] - refined_center_rc[0], center_rc[1] - refined_center_rc[1])
    edge_count = sum(1 for sector in sectors if sector.chosen_type == "edge-like")
    unknown_penalty = sum(1 for sector in sectors if sector.chosen_type == "unknown") * 2.0
    boundary_penalty = sum(max(0.0, 0.22 - sector.interior_score) for sector in sectors if sector.chosen_type == "corner-like")
    support_score = sum(max(sector.edge_score, sector.corner_score) for sector in sectors)
    polygon_bonus = 0.6 if len(polygon) >= 3 and area >= 1500.0 else 0.0
    # edge-like 太多时会给轻微惩罚，避免模型过度偏向边而失去角点约束。
    # unknown_penalty 则直接打击无解释扇区过多的中心候选。
    # polygon_bonus 只在面积和顶点数都达标时生效，避免噪声 polygon 抬分。
    # 各项系数都是经验参数，核心目标是把候选中心排出相对优先级。
    # 因而这里更关注相对排序，而不是绝对分值大小。
    # 最终 score 会和其它中心候选的 score 做横向比较。
    score = support_score + polygon_bonus - 0.18 * edge_count - 0.45 * boundary_penalty - shift_penalty - unknown_penalty
    # 分数不是物理量，而是经验性排序指标。

    # 最终返回的 CandidateEval 会被后续 round 逻辑直接消费。
    # 它同时携带评分、polygon 和每个 sector 的细节。
    # 后续如果要比较多个中心候选，比较的就是这里的 score。
    # 因而 score 之外的细节字段也要一起保留，供调试解释。
    return CandidateEval(
        center_rc=center_rc,
        score=float(score),
        edge_count=int(edge_count),
        polygon_vertices_rc=polygon,
        sectors=sectors,
    )


def evaluate_round(
    center_rc: tuple[int, int] | tuple[float, float],
    exits: list[ExitTrace],
    free_mask01: np.ndarray,
    ray_step_deg: float,
    ray_max_radius_px: int,
    include_truncation_debug: bool = True,
) -> tuple[CandidateEval | None, list[dict[str, object]] | None, tuple[float, float] | None]:
    """执行一轮完整的中心-support-polygon 联合求解。"""

    # round 输入中心先量化到像素中心，和 mask/ray 逻辑保持一致。
    center_int_rc = (int(round(float(center_rc[0]))), int(round(float(center_rc[1]))))
    # exits 先变成 branch 方向束，再围绕该中心做一次完整评估。
    branches = build_branches_from_cut_points(center_int_rc, exits)
    # refined_center_rc 暂时就沿用当前中心本身，后续若有新策略可独立调整。
    best_eval = evaluate_center_candidate(
        free_mask=free_mask01,
        center_rc=center_int_rc,
        branches=branches,
        ray_step_deg=ray_step_deg,
        ray_max_radius_px=ray_max_radius_px,
        refined_center_rc=center_int_rc,
    )
    # 若该中心候选完全不可用，则整轮求解直接失败。
    if best_eval is None:
        return None, None, None
    # 截断调试项和 polygon centroid 都基于 best_eval 的最终结果推导。
    # 这使 round 的所有输出都严格绑定同一个中心候选评估结果。
    truncation_items = truncate_using_cut_points(best_eval, exits, center_int_rc) if include_truncation_debug else []
    if best_eval.polygon_vertices_rc:
        centroid_rc = polygon_centroid_rc([tuple(map(float, p)) for p in best_eval.polygon_vertices_rc])
    else:
        # 退化 polygon 时，质心直接退回中心候选本身。
        centroid_rc = (float(center_int_rc[0]), float(center_int_rc[1]))
    # round 不做二次迭代，只返回这一轮的最优结果。
    # 外层若需要多轮 refinement，应自行再次调用。
    return best_eval, truncation_items, centroid_rc


__all__ = (
    "support_polygon_vertices",
    "polygon_area",
    "evaluate_center_candidate",
    "evaluate_round",
)
