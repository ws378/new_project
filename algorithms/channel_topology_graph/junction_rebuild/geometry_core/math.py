"""交汇几何核心里复用的长度、角度与 polygon 数学工具。"""

from __future__ import annotations

import math


def cumulative_lengths(points_rc: list[tuple[int, int]]) -> list[float]:
    """累积路径长度。"""

    # 累积表让后续按弧长找 cut/probe 点时不必重复积分。
    out = [0.0]
    for (r0, c0), (r1, c1) in zip(points_rc[:-1], points_rc[1:]):
        out.append(out[-1] + math.hypot(float(r1 - r0), float(c1 - c0)))
    # 返回结果长度与输入点数保持一致。
    return out


def index_at_distance(cumlen: list[float], distance_px: float) -> int:
    """在累积长度表里找达到指定长度的索引。"""

    # 返回第一个达到目标长度的位置，保持 cut/probe 点选择稳定。
    # 这里显式取“第一个达到”而非最近点，避免 cut 落在目标弧长之前。
    target = float(distance_px)
    for index, value in enumerate(cumlen):
        if value >= target:
            return index
    # 若目标超过路径总长，就回落到最后一个点。
    return len(cumlen) - 1


def angle_diff_deg(a_deg: float, b_deg: float) -> float:
    """计算两个方向角的最小夹角。"""

    # 最小夹角总落在 [0, 180]，便于稳定性阈值直接比较。
    delta = abs((float(a_deg) - float(b_deg)) % 360.0)
    return min(delta, 360.0 - delta)


def polygon_centroid_rc(polygon_rc: list[tuple[float, float]]) -> tuple[float, float]:
    """计算 polygon 质心。"""

    if not polygon_rc:
        raise ValueError("empty polygon")
    # 计算时先转成 `(x, y)` 形式，最后再映回 `(r, c)`。
    # 这是因为鞋带公式天然按笛卡尔 `(x, y)` 展开，更容易直接复用标准写法。
    # 但对外接口仍坚持 rc 口径，避免调用方再做一轮坐标系转换。
    pts = [(float(c), float(r)) for r, c in polygon_rc]
    area2 = 0.0
    cx = 0.0
    cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        # `cross` 同时决定有向面积和质心加权项。
        cross = x0 * y1 - x1 * y0
        area2 += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(area2) < 1e-6:
        # 退化 polygon 直接退回顶点均值，避免除零。
        ys = [r for r, _ in polygon_rc]
        xs = [c for _, c in polygon_rc]
        return (float(sum(ys) / len(ys)), float(sum(xs) / len(xs)))
    area = area2 * 0.5
    cx /= 6.0 * area
    cy /= 6.0 * area
    # 输出重新换回 `(row, col)` 语义，和其余几何 helper 对齐。
    # 这样 polygon 质心可以直接喂回局部 rc 几何逻辑。
    # 非退化 polygon 在这里沿用标准鞋带公式。
    # 公式分支与退化分支最终都返回同一 `(r, c)` 口径。
    # 调用方无需关心 polygon 是否退化，直接消费质心结果即可。
    return (float(cy), float(cx))


__all__ = (
    "cumulative_lengths",
    "index_at_distance",
    "angle_diff_deg",
    "polygon_centroid_rc",
)
