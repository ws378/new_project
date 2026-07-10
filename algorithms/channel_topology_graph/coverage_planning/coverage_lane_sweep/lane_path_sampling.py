"""Coverage lane 主轴路径采样 helper。"""

from __future__ import annotations

from .lane_common import distance, path_length_euclidean


def sample_path_by_spacing(
    path_rc: tuple[tuple[float, float], ...],
    spacing_px: int,
) -> tuple[tuple[float, float], ...]:
    """按参考步长对 path 做自适应均匀采样。"""

    if len(path_rc) <= 1:
        return tuple(path_rc)
    if spacing_px <= 0:
        raise ValueError('spacing_px must be positive')
    total_length = path_length_euclidean(path_rc)
    if total_length <= 0.0:
        return (path_rc[0],)
    if total_length <= float(spacing_px):
        # 整条 path 比目标步长还短时，只保留首尾即可，避免为了凑采样点制造伪密度。
        return (path_rc[0], path_rc[-1]) if path_rc[0] != path_rc[-1] else (path_rc[0],)

    sampled = [path_rc[0]]
    traveled = 0.0
    target_distances = build_uniform_sample_distances(total_length, spacing_px)
    target_index = 0
    for idx in range(1, len(path_rc)):
        start_point = path_rc[idx - 1]
        end_point = path_rc[idx]
        segment_length = distance(start_point, end_point)
        if segment_length <= 0.0:
            continue
        while target_index < len(target_distances) and traveled + segment_length >= target_distances[target_index]:
            ratio = (target_distances[target_index] - traveled) / segment_length
            sampled.append(interpolate_point(start_point, end_point, ratio))
            target_index += 1
        traveled += segment_length
    if distance(sampled[-1], path_rc[-1]) > 1e-6:
        # 尾点必须显式补回，保证采样后的 sweep 仍然完整覆盖原 path 末端。
        sampled.append(path_rc[-1])
    return tuple(sampled)


def build_uniform_sample_distances(total_length_px: float, ref_step_px: int) -> tuple[float, ...]:
    """根据参考步长反推更均匀的目标弧长采样位置。"""

    if total_length_px <= 0.0:
        return ()
    step_px = max(1, int(ref_step_px))
    expected_steps = max(1, int(-(-float(total_length_px) // float(step_px))))
    adaptive_step = max(1.0, float(total_length_px) / float(expected_steps))
    distances: list[float] = []
    current = adaptive_step
    while current < float(total_length_px):
        distances.append(float(current))
        current += adaptive_step
    if distances and float(total_length_px) - distances[-1] <= 0.2 * adaptive_step:
        return tuple(distances[:-1])
    return tuple(distances)


def interpolate_point(
    start_point_rc: tuple[float, float],
    end_point_rc: tuple[float, float],
    ratio: float,
) -> tuple[float, float]:
    """在线段内部按比例插值得到采样点。"""

    clipped_ratio = min(1.0, max(0.0, float(ratio)))
    return (
        float(start_point_rc[0]) + (float(end_point_rc[0]) - float(start_point_rc[0])) * clipped_ratio,
        float(start_point_rc[1]) + (float(end_point_rc[1]) - float(start_point_rc[1])) * clipped_ratio,
    )


__all__ = ('build_uniform_sample_distances', 'interpolate_point', 'sample_path_by_spacing')
