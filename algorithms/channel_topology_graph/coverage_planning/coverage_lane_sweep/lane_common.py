"""Coverage lane 内部共用的路径与几何 helper。"""

from __future__ import annotations

from typing import Any

import numpy as np


EIGHT_NEIGHBORS: tuple[tuple[int, int], ...] = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
)


def mask_to_points(mask: np.ndarray) -> list[tuple[int, int]]:
    """把二值掩膜转成 `(row, col)` 点集。"""

    rows, cols = np.where(mask > 0)
    return [(int(row), int(col)) for row, col in zip(rows.tolist(), cols.tolist())]


def to_path_tuple(path_rc: Any) -> tuple[tuple[float, float], ...]:
    """把任意路径容器统一转成浮点坐标元组。"""

    # 这里不做路径合法性校验，只负责把容器类型统一成合同字段常用的浮点 tuple。
    return tuple((float(point_rc[0]), float(point_rc[1])) for point_rc in path_rc)


def vector_norm(row_delta: float, col_delta: float) -> float:
    """计算二维向量的欧氏范数。"""

    return float((row_delta * row_delta + col_delta * col_delta) ** 0.5)


def distance(point_a_rc: tuple[float, float], point_b_rc: tuple[float, float]) -> float:
    """计算两个 `(row, col)` 点的欧氏距离。"""

    return vector_norm(float(point_a_rc[0]) - float(point_b_rc[0]), float(point_a_rc[1]) - float(point_b_rc[1]))


def path_length_euclidean(path_rc: tuple[tuple[float, float], ...]) -> float:
    """计算离散路径的欧氏累计长度。"""

    return float(sum(distance(path_rc[idx - 1], path_rc[idx]) for idx in range(1, len(path_rc))))


def normalize_vector(row_delta: float, col_delta: float) -> tuple[float, float]:
    """把二维向量归一化。"""

    norm = vector_norm(row_delta, col_delta)
    return (1.0, 0.0) if norm <= 1e-6 else (float(row_delta / norm), float(col_delta / norm))


__all__ = ('EIGHT_NEIGHBORS', 'distance', 'mask_to_points', 'normalize_vector', 'path_length_euclidean', 'to_path_tuple', 'vector_norm')
