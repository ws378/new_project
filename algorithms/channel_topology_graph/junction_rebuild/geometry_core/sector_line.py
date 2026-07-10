"""扇区点集的线性拟合与投影工具。"""

from __future__ import annotations

import numpy as np


def pca_linearity(points_rc: list[tuple[int, int]]) -> tuple[float, float, float, np.ndarray]:
    """估计一组 hit 点的线性程度、跨度和厚度。"""

    # 点太少时无法稳定做 PCA，直接退回零特征和默认方向。
    if len(points_rc) < 3:
        return 0.0, 0.0, 0.0, np.asarray([0.0, 1.0], dtype=np.float64)
    # PCA 在这里工作在 `(x, y)` 空间，方便后续投影与端点重建。
    # 这也是线性代数运算最自然的坐标表达。
    pts = np.asarray([[float(c), float(r)] for r, c in points_rc], dtype=np.float64)
    center_xy = np.mean(pts, axis=0)
    centered = pts - center_xy
    cov = np.cov(centered, rowvar=False)
    # 最大特征值对应的特征向量即主方向。
    evals, evecs = np.linalg.eigh(cov)
    order = np.argsort(evals)[::-1]
    evals = evals[order]
    evecs = evecs[:, order]
    line_dir_xy = evecs[:, 0]
    # proj/ortho 分别表示沿主方向和法向的分布。
    proj = centered @ line_dir_xy
    ortho = centered @ evecs[:, 1]
    total = max(float(evals[0] + evals[1]), 1e-6)
    linearity = float(evals[0] / total)
    span_px = float(np.max(proj) - np.min(proj))
    thickness_px = float(np.std(ortho))
    # 返回值同时包含主方向，供后续 edge-like 端点重建复用。
    # linearity 越接近 1，说明点集越接近一条细长直线。
    return linearity, span_px, thickness_px, line_dir_xy


def project_point_to_line(
    point_rc: tuple[int, int],
    line_center_xy: np.ndarray,
    line_dir_xy: np.ndarray,
) -> tuple[tuple[int, int], float]:
    """把点投影到拟合直线上。"""

    # 返回值同时包含投影点和在线方向上的标量坐标。
    # 标量坐标后续可直接拿来做线段裁剪。
    # 这让“点投影”和“线段区间裁剪”可以共用同一份结果。
    point_xy = np.asarray([float(point_rc[1]), float(point_rc[0])], dtype=np.float64)
    scalar = float((point_xy - line_center_xy) @ line_dir_xy)
    proj_xy = line_center_xy + scalar * line_dir_xy
    return (int(round(proj_xy[1])), int(round(proj_xy[0]))), scalar


__all__ = (
    "pca_linearity",
    "project_point_to_line",
)
