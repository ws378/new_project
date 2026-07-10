"""CoveragePlanning 内部共享的 rc 几何 helper。"""

from __future__ import annotations

import math
from typing import Any

from .common_units import px_to_m


def to_float_point(point: tuple[float, float]) -> tuple[float, float]:
    """把任意二元点统一压成 `(row, col)` 浮点点。"""

    # coverage planning 的 sweep、connector、final path 都以 rc 坐标作为主口径。
    # 这里不做 xy 转换，只负责消除 int/float/list/tuple 混排带来的细小差异。
    return float(point[0]), float(point[1])


def to_path_tuple(path_rc: Any) -> tuple[tuple[float, float], ...]:
    """把 path-like 输入统一压成稳定的 float rc 点列。"""

    # 这个 helper 是 coverage planning 内部路径对象的共同入口。
    # 子域代码不应各自重复 list/tuple/int/float 归一逻辑，否则 seam、距离和 compare 会出现细小漂移。
    return tuple(to_float_point(tuple(point)) for point in tuple(path_rc or ()))


def sqdist(p0: tuple[float, float], p1: tuple[float, float]) -> float:
    """计算两个 rc 点的平方距离。"""

    dr = float(p0[0] - p1[0])
    dc = float(p0[1] - p1[1])
    return float(dr * dr + dc * dc)


def distance_rc(p0: tuple[float, float], p1: tuple[float, float]) -> float:
    """计算两个 rc 点的欧氏距离。"""

    return float(sqdist(p0, p1) ** 0.5)


def segment_length(p0: tuple[float, float], p1: tuple[float, float]) -> float:
    """计算单段 rc 线段长度。"""

    return distance_rc(p0, p1)


def normalize_vector(vector_rc: tuple[float, float]) -> tuple[float, float]:
    """把 rc 向量归一化，零向量稳定返回零向量。"""

    norm = float((vector_rc[0] * vector_rc[0] + vector_rc[1] * vector_rc[1]) ** 0.5)
    if norm <= 1e-12:
        # 零向量没有稳定方向；返回零向量让上层显式处理缺方向语义。
        return 0.0, 0.0
    return float(vector_rc[0] / norm), float(vector_rc[1] / norm)


def angle_between_deg(v0: tuple[float, float], v1: tuple[float, float]) -> float:
    """计算两个 rc 向量的无符号夹角，范围为 `[0, 180]`。"""

    n0 = normalize_vector(v0)
    n1 = normalize_vector(v1)
    dot = max(-1.0, min(1.0, float(n0[0] * n1[0] + n0[1] * n1[1])))
    return float(math.degrees(math.acos(dot)))


def connection_angle_deg(v0: tuple[float, float], v1: tuple[float, float]) -> float:
    """连接构造层使用的无符号夹角口径。"""

    return float(angle_between_deg(v0, v1))


def normalize_signed_angle_deg(angle_deg: float) -> float:
    """把角度稳定规约到 `[-180, 180]`。"""

    # 这里保留 `180` 而不是压成 `-180`，
    # 是为了和 sweep candidate 已落盘的带符号端点转角口径保持一致。
    angle = float(angle_deg)
    while angle <= -180.0:
        angle += 360.0
    while angle > 180.0:
        angle -= 360.0
    return float(angle)


def signed_angle_between_vectors_deg(v0: tuple[float, float], v1: tuple[float, float]) -> float:
    """计算两个 rc 向量的带符号夹角，范围为 `[-180, 180]`。"""

    v0_len = math.hypot(float(v0[0]), float(v0[1]))
    v1_len = math.hypot(float(v1[0]), float(v1[1]))
    if v0_len <= 1e-9 or v1_len <= 1e-9:
        # 零长度方向没有真实角度，返回 NaN 让调用方按缺证据处理。
        return float('nan')
    cross = float(v0[0] * v1[1] - v0[1] * v1[0])
    dot = float(v0[0] * v1[0] + v0[1] * v1[1])
    return normalize_signed_angle_deg(math.degrees(math.atan2(cross, dot)))


def pick_from_endpoint_pair(
    path_rc: tuple[tuple[float, float], ...],
    from_end_type: str,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """按 A/B 语义读取 from sweep 的相邻点与退出端点。"""

    if len(path_rc) < 2:
        raise ValueError('source sweep path requires at least 2 points to derive endpoint pair')
    if str(from_end_type) == 'src':
        # src 端离开时，A 是内侧相邻点，B 是 src 端点。
        return tuple(path_rc[1]), tuple(path_rc[0])
    if str(from_end_type) == 'dst':
        # dst 端离开时，A 是倒数第二点，B 是 dst 端点。
        return tuple(path_rc[-2]), tuple(path_rc[-1])
    raise ValueError(f'invalid from_end_type: {from_end_type}')


def pick_to_endpoint_pair(
    path_rc: tuple[tuple[float, float], ...],
    to_end_type: str,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """按 C/D 语义读取 to sweep 的进入端点与相邻点。"""

    if len(path_rc) < 2:
        raise ValueError('target sweep path requires at least 2 points to derive endpoint pair')
    if str(to_end_type) == 'src':
        # src 端进入时，C 是 src 端点，D 是内侧相邻点。
        return tuple(path_rc[0]), tuple(path_rc[1])
    if str(to_end_type) == 'dst':
        # dst 端进入时，C 是 dst 端点，D 是倒数第二点。
        return tuple(path_rc[-1]), tuple(path_rc[-2])
    raise ValueError(f'invalid to_end_type: {to_end_type}')


def endpoint_point_for_end_type(path_rc: tuple[tuple[float, float], ...], end_type: str) -> tuple[float, float]:
    """读取 src/dst 对应的真实端点。"""

    if not path_rc:
        raise ValueError('path_rc requires at least 1 point to derive endpoint point')
    if str(end_type) == 'src':
        return tuple(path_rc[0])
    if str(end_type) == 'dst':
        return tuple(path_rc[-1])
    raise ValueError(f'invalid end_type: {end_type}')


def endpoint_distance_px_between_paths(
    from_path_rc: tuple[tuple[float, float], ...],
    to_path_rc: tuple[tuple[float, float], ...],
    *,
    from_end_type: str,
    to_end_type: str,
) -> float:
    """按指定端型计算两条路径之间的像素端点距离。"""

    from_endpoint = endpoint_point_for_end_type(from_path_rc, from_end_type)
    to_endpoint = endpoint_point_for_end_type(to_path_rc, to_end_type)
    return distance_rc(from_endpoint, to_endpoint)


def sweep_endpoint_distance_between_sweeps(
    in_sweep: dict[str, Any],
    out_sweep: dict[str, Any],
    *,
    from_end_type: str,
    to_end_type: str,
) -> float:
    """按指定端型计算两条 sweep 之间的米制端点距离。"""

    in_path = to_path_tuple(in_sweep.get('path_rc', ()))
    out_path = to_path_tuple(out_sweep.get('path_rc', ()))
    if not in_path or not out_path:
        # 缺 path 时只能返回无证据距离；候选生成层会决定是否保留。
        return 0.0
    distance_px = endpoint_distance_px_between_paths(
        in_path,
        out_path,
        from_end_type=from_end_type,
        to_end_type=to_end_type,
    )
    return float(px_to_m(distance_px, resolve_sweep_resolution_m_per_px(in_sweep, out_sweep)))


def sweep_turn_delta_deg_between_sweeps(
    in_sweep: dict[str, Any],
    out_sweep: dict[str, Any],
    *,
    from_end_type: str,
    to_end_type: str,
) -> float:
    """按 A/B/C/D 端点语义计算 sweep 级带符号转角。"""

    in_path = to_path_tuple(in_sweep.get('path_rc', ()))
    out_path = to_path_tuple(out_sweep.get('path_rc', ()))
    if len(in_path) < 2 or len(out_path) < 2:
        return float('nan')
    point_a, point_b = pick_from_endpoint_pair(in_path, from_end_type)
    point_c, point_d = pick_to_endpoint_pair(out_path, to_end_type)
    from_vector = (float(point_b[0] - point_a[0]), float(point_b[1] - point_a[1]))
    to_vector = (float(point_d[0] - point_c[0]), float(point_d[1] - point_c[1]))
    return float(signed_angle_between_vectors_deg(from_vector, to_vector))


def min_sweep_endpoint_distance(in_sweep: dict[str, Any], out_sweep: dict[str, Any]) -> float:
    """返回两条 sweep 四种端点组合里的最短米制距离。"""

    in_path = to_path_tuple(in_sweep.get('path_rc', ()))
    out_path = to_path_tuple(out_sweep.get('path_rc', ()))
    if not in_path or not out_path:
        return 0.0
    endpoints = (in_path[0], in_path[-1])
    targets = (out_path[0], out_path[-1])
    distance_px = min(distance_rc(a, b) for a in endpoints for b in targets)
    return float(px_to_m(distance_px, resolve_sweep_resolution_m_per_px(in_sweep, out_sweep)))


def sweep_endpoint_distance_for_end_types(
    sweep: dict[str, Any],
    *,
    from_end_type: str,
    to_end_type: str,
) -> float:
    """计算同一条 sweep 两端之间的直接米制端点距离。"""

    path = to_path_tuple(sweep.get('path_rc', ()))
    if len(path) < 2:
        return 0.0
    point_a = endpoint_point_for_end_type(path, from_end_type)
    point_b = endpoint_point_for_end_type(path, to_end_type)
    return float(px_to_m(distance_rc(point_a, point_b), resolve_sweep_resolution_m_per_px(sweep)))


def resolve_sweep_resolution_m_per_px(*sweeps: dict[str, Any]) -> float:
    """从一组 sweep 中解析正的米/像素分辨率。"""

    for sweep in sweeps:
        resolution = float(sweep.get('resolution_m_per_px', 0.0))
        if resolution > 0.0:
            return resolution
    raise ValueError('sweep endpoint distance requires positive resolution_m_per_px')


def local_feasibility_from_geometry(*, endpoint_distance_m: float, turn_penalty_deg: float) -> float:
    """把端点距离和端点角度惩罚压成 0 到 1 的局部可行性分。"""

    distance_cost = max(0.0, float(endpoint_distance_m))
    turn_cost = max(0.0, float(turn_penalty_deg)) / 90.0
    return float(1.0 / (1.0 + distance_cost + turn_cost))


__all__ = (
    'angle_between_deg',
    'connection_angle_deg',
    'distance_rc',
    'endpoint_distance_px_between_paths',
    'endpoint_point_for_end_type',
    'local_feasibility_from_geometry',
    'min_sweep_endpoint_distance',
    'normalize_signed_angle_deg',
    'normalize_vector',
    'pick_from_endpoint_pair',
    'pick_to_endpoint_pair',
    'segment_length',
    'signed_angle_between_vectors_deg',
    'sqdist',
    'sweep_endpoint_distance_between_sweeps',
    'sweep_endpoint_distance_for_end_types',
    'sweep_turn_delta_deg_between_sweeps',
    'to_float_point',
    'to_path_tuple',
)
