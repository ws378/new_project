"""扇区模型拟合与 edge/corner 判型。"""

from __future__ import annotations

import numpy as np

from .common import SectorModel, angle_ccw_delta_deg, clamp01, wrap_deg
from .sector_line import pca_linearity


def empty_sector_model(
    sector_index: int,
    start_theta_deg: float,
    end_theta_deg: float,
    width_deg: float,
    center_theta_deg: float,
) -> SectorModel:
    """构造没有任何命中的 unknown sector。"""

    # unknown sector 统一使用一个固定空模板，避免主流程反复展开默认值。
    # 角域边界字段仍然要真实写入，便于调试时知道这是哪个 sector。
    # hit 相关字段全部清空，明确表达“该扇区没有任何支撑样本”。
    # 距离统计统一回落到 999.0，避免和正常近距离 hit 混淆。
    # min_relpos 固定为 0.5，表示既不偏左也不偏右。
    # 线性、跨度、厚度全部归零，明确表示不存在可解释线段结构。
    # focus/interior/edge/corner 评分也全部归零，防止上游误消费。
    # representative_point_rc 保持为空，因为这里没有最近命中点可记录。
    # edge_endpoints_rc 同样为空，因为 unknown sector 不应生成边端点。
    # 该模板的作用是给上游一个“结构完整但证据为空”的统一返回值。
    # 这样多扇区求解链不会因为某个扇区没 hit 而缺字段。
    return SectorModel(
        sector_index=sector_index,
        start_theta_deg=start_theta_deg,
        end_theta_deg=end_theta_deg,
        width_deg=width_deg,
        center_theta_deg=center_theta_deg,
        hit_points_rc=[],
        hit_distances_px=[],
        hit_angles_deg=[],
        min_hit_distance_px=999.0,
        mean_hit_distance_px=999.0,
        std_hit_distance_px=999.0,
        min_relpos=0.5,
        linearity=0.0,
        span_px=0.0,
        thickness_px=0.0,
        relative_span=0.0,
        focus_score=0.0,
        interior_score=0.0,
        edge_score=0.0,
        corner_score=0.0,
        chosen_type="unknown",
        representative_point_rc=None,
        edge_endpoints_rc=[],
    )


def distance_statistics(hit_distances_px: list[float]) -> tuple[int, float, float, float, float]:
    """提取 hit 距离分布里的核心统计量。"""

    # 这些统计量共同刻画“最短 hit 是否突出”和“距离平台是否平坦”。
    distances = np.asarray(hit_distances_px, dtype=np.float64)
    min_idx = int(np.argmin(distances))
    min_hit = float(distances[min_idx])
    mean_hit = float(np.mean(distances))
    std_hit = float(np.std(distances))
    p25_hit = float(np.percentile(distances, 25.0))
    # `p25_hit` 后续专门用于识别 edge-like 的平台深度。
    # `min_idx` 既决定代表点，也决定角域里的最短命中位置。
    return min_idx, min_hit, mean_hit, std_hit, p25_hit


def min_relative_position(
    start_theta_deg: float,
    width_deg: float,
    hit_angles_deg: list[float],
    min_idx: int,
) -> float:
    """计算最短命中点在扇区角域里的相对位置。"""

    # 宽度退化时直接回落到 0.5，表示“既不偏左也不偏右”。
    if width_deg <= 1e-6:
        return 0.5
    # 相对位置只比较当前最短命中角和 sector 起点之间的逆时针角距。
    relpos = angle_ccw_delta_deg(start_theta_deg, hit_angles_deg[min_idx]) / width_deg
    # 输出统一 clamp 到 [0, 1]，避免浮点边界误差把位置推到扇区外。
    # 这个位置量随后会直接进入 corner-like 的居中性评分。
    return float(max(0.0, min(1.0, relpos)))


def score_features(
    width_deg: float,
    min_relpos: float,
    linearity: float,
    thickness_px: float,
    relative_span: float,
    min_hit: float,
    mean_hit: float,
    std_hit: float,
    p25_hit: float,
) -> tuple[float, float, float, float]:
    """把局部统计量折算成 corner/edge 判型分数。"""

    # 下面这些 score 都是经验型特征归一化，不是物理量。
    # 每个分数都被 clamp 到 [0, 1]，便于后续线性组合。
    focus = (mean_hit - min_hit) / max(mean_hit, 1.0)
    focus_score = clamp01((focus - 0.03) / 0.20)
    interior_score = clamp01((0.45 - abs(min_relpos - 0.5)) / 0.45)
    # 线性、厚度与相对跨度共同决定“像不像一段边”。
    linearity_score = clamp01((linearity - 0.90) / 0.10)
    thinness_score = clamp01((10.0 - thickness_px) / 10.0)
    relspan_score = clamp01((relative_span - 0.25) / 0.75)
    wide_score = clamp01((width_deg - 60.0) / 120.0)
    # 距离分布越平，越像 edge-like 平台；越尖锐，越像 corner-like 峰值。
    std_ratio = std_hit / max(mean_hit, 1.0)
    flatness_score = clamp01((0.35 - std_ratio) / 0.35)
    compact_score = clamp01((0.90 - relative_span) / 0.90)
    narrow_score = clamp01((120.0 - width_deg) / 120.0)
    platform_depth = (p25_hit - min_hit) / max(mean_hit, 1.0)
    platform_score = clamp01((0.18 - platform_depth) / 0.18)
    # 到这里为止，特征仍然是“局部统计解释量”，还不是最终判型分数。
    # 这些中间分数都会被复用到 edge_base 和 corner_score 两条聚合路径里。
    # 因而这里先统一收口，再做最终权重组合。

    # edge_base 偏向“线性、细、长、平”的扇区。
    # 这些特征共同刻画“像一段边”的几何样子。
    edge_base = (
        0.24 * linearity_score
        + 0.18 * thinness_score
        + 0.22 * relspan_score
        + 0.18 * platform_score
        + 0.10 * wide_score
        + 0.08 * flatness_score
    )
    # edge_gate 起到硬门控作用，防止某单项过强把明显非边扇区误判成边。
    # 只有同时满足几个关键条件，edge_base 才会被充分放大。
    # 它的设计目标不是重新排序，而是抑制伪 edge-like 高分。
    edge_gate = min(
        linearity_score,
        thinness_score,
        clamp01((relative_span - 0.55) / 0.45),
        clamp01((width_deg - 50.0) / 130.0),
    )
    edge_score = edge_base * (0.35 + 0.65 * edge_gate)
    # corner_score 则更强调局部尖锐、内聚和角域居中。
    # 它更像“角点支撑”的证据聚合，而不是“线段支撑”的证据聚合。
    # 因而相对跨度越小、最短 hit 越居中时，corner_score 越容易占优。
    corner_score = (
        0.35 * focus_score
        + 0.25 * interior_score
        + 0.20 * compact_score
        + 0.10 * narrow_score
        + 0.10 * (1.0 - 0.5 * linearity_score)
    )
    # 返回值里保留 focus/interior，供 SectorModel 调试字段直接落盘。
    return focus_score, interior_score, edge_score, corner_score


def edge_like_endpoints(
    hit_points_rc: list[tuple[int, int]],
    line_dir_xy: np.ndarray,
) -> list[tuple[int, int]]:
    """按 hit 点主方向恢复 edge-like 扇区端点。"""

    # 端点取投影分布的 10/90 分位，避免极端离群点主导端点位置。
    # 这里仍然是基于 hit 点统计，而不是强行延长到整个扇区边界。
    # 先在连续空间上恢复端点，再统一四舍五入回像素格。
    pts = np.asarray([[float(c), float(r)] for r, c in hit_points_rc], dtype=np.float64)
    center_xy = np.mean(pts, axis=0)
    proj = (pts - center_xy) @ line_dir_xy
    q0 = float(np.percentile(proj, 10.0))
    q1 = float(np.percentile(proj, 90.0))
    point0_xy = center_xy + q0 * line_dir_xy
    point1_xy = center_xy + q1 * line_dir_xy
    # 输出坐标重新映回 rc 语义，直接供 SectorModel 保存。
    # 这里不额外做 hit 吸附，吸附逻辑留给邻角裁剪阶段统一处理。
    # 这样端点求解和端点修正的职责边界保持清晰。
    return [
        (int(round(point0_xy[1])), int(round(point0_xy[0]))),
        (int(round(point1_xy[1])), int(round(point1_xy[0]))),
    ]


def fit_sector_model(
    sector_index: int,
    start_theta_deg: float,
    end_theta_deg: float,
    hit_angles_deg: list[float],
    hit_points_rc: list[tuple[int, int]],
    hit_distances_px: list[float],
) -> SectorModel:
    """评估单个扇区更像 corner 还是 edge。"""

    # 扇区角宽和中心角是所有后续特征的基础。
    width_deg = angle_ccw_delta_deg(start_theta_deg, end_theta_deg)
    center_theta_deg = wrap_deg(start_theta_deg + 0.5 * width_deg)
    # 没有任何 hit 时，直接退回 unknown sector。
    # 这类扇区既不能稳定支持角点，也不能稳定支持边段。
    if not hit_points_rc:
        return empty_sector_model(
            sector_index=sector_index,
            start_theta_deg=start_theta_deg,
            end_theta_deg=end_theta_deg,
            width_deg=width_deg,
            center_theta_deg=center_theta_deg,
        )

    # 命中距离分布的统计量用来刻画“是否存在尖锐角点”。
    # 最短 hit 越突出，corner 候选通常越明显。
    min_idx, min_hit, mean_hit, std_hit, p25_hit = distance_statistics(hit_distances_px)
    # PCA 特征用来刻画“这批 hit 是否更像一条边界线”。
    linearity, span_px, thickness_px, line_dir_xy = pca_linearity(hit_points_rc)
    relative_span = span_px / max(mean_hit, 1.0)
    # relative_span 表达“hit 沿主方向铺开的程度”。
    # 同一组 hit 因而同时提供“尖锐角”与“平直边”两类证据。

    # min_relpos 表示最小命中点在扇区角域里的相对位置。
    min_relpos = min_relative_position(start_theta_deg, width_deg, hit_angles_deg, min_idx)
    # 居中命中的角点通常更像 corner-like 支撑，而不是边界平台。
    # 接下来统一把局部统计量折算成 edge/corner 分数，保持判型路径单一。
    # 这样上游只面对最终判型，不需要理解中间全部统计细节。
    focus_score, interior_score, edge_score, corner_score = score_features(
        width_deg=width_deg,
        min_relpos=min_relpos,
        linearity=linearity,
        thickness_px=thickness_px,
        relative_span=relative_span,
        min_hit=min_hit,
        mean_hit=mean_hit,
        std_hit=std_hit,
        p25_hit=p25_hit,
    )

    # 最终只保留两类：edge-like 与 corner-like。
    chosen_type = "edge-like" if edge_score > corner_score else "corner-like"
    representative_point_rc = hit_points_rc[min_idx]
    edge_endpoints_rc: list[tuple[int, int]] = []
    # 只有 edge-like 才真正拟合一条线段端点。
    # corner-like 则保留最近命中点作为代表点。
    # 这样上游 polygon 组装时，可以直接按类型决定取一对端点还是单代表点。
    # 判型一旦落定，这里就把 sector 的“几何载体”也一并定下来。
    if chosen_type == "edge-like":
        edge_endpoints_rc = edge_like_endpoints(hit_points_rc, line_dir_xy)
        representative_point_rc = None

    # 最终所有扇区都统一落成 SectorModel，供上游多边形求解使用。
    # 这样上游不需要关心该扇区到底来自哪种判型路径。
    # 命中原始样本也一并保留，方便调试时回放分数来源。
    # SectorModel 在这里既承担正式结果，也承担解释性 debug 载体。
    # 因而该结构体会同时被正式求解链和过程记录链复用。
    # 这也保证后续 stage 若要追查判型原因，不需要回头重算局部统计量。
    return SectorModel(
        sector_index=sector_index,
        start_theta_deg=float(start_theta_deg),
        end_theta_deg=float(end_theta_deg),
        width_deg=float(width_deg),
        center_theta_deg=float(center_theta_deg),
        hit_points_rc=hit_points_rc,
        hit_distances_px=[float(item) for item in hit_distances_px],
        hit_angles_deg=[float(item) for item in hit_angles_deg],
        min_hit_distance_px=min_hit,
        mean_hit_distance_px=mean_hit,
        std_hit_distance_px=std_hit,
        min_relpos=min_relpos,
        linearity=float(linearity),
        span_px=float(span_px),
        thickness_px=float(thickness_px),
        relative_span=float(relative_span),
        focus_score=float(focus_score),
        interior_score=float(interior_score),
        edge_score=float(edge_score),
        corner_score=float(corner_score),
        chosen_type=chosen_type,
        representative_point_rc=representative_point_rc,
        edge_endpoints_rc=edge_endpoints_rc,
    )


__all__ = (
    "fit_sector_model",
)
