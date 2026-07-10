"""初始建边使用的像素路径工具。"""

from __future__ import annotations

import numpy as np


def densify_line_rc(
    start_rc: tuple[int, int] | tuple[float, float],
    end_rc: tuple[int, int] | tuple[float, float],
) -> list[tuple[int, int]]:
    """把节点中心与接触点之间的短连接线离散成像素序列。"""

    # 这里输出整型像素，用于初始建边阶段的骨架拼接。
    r0, c0 = float(start_rc[0]), float(start_rc[1])
    r1, c1 = float(end_rc[0]), float(end_rc[1])
    steps = max(1, int(round(max(abs(r1 - r0), abs(c1 - c0)))))
    out: list[tuple[int, int]] = []
    for step in range(steps + 1):
        alpha = step / steps
        rr = int(round(r0 + (r1 - r0) * alpha))
        cc = int(round(c0 + (c1 - c0) * alpha))
        # round 后的重复像素只保留一次，保持路径离散序列单调前进。
        if not out or out[-1] != (rr, cc):
            out.append((rr, cc))
    # 输出覆盖起止两端，便于直接拼接到骨架路径。
    # 这条像素链也可直接用于 contact 桥接。
    # 它的职责就是提供最简单稳定的离散连线。
    # 因而这里不引入任何额外平滑或抽稀策略。
    return out


def dedupe_path(path_rc: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """去除路径里相邻重复点。"""

    # 这个 helper 只做相邻去重，不改变点序。
    out: list[tuple[int, int]] = []
    for point_rc in path_rc:
        if not out or out[-1] != point_rc:
            out.append(point_rc)
    # 因而输出仍然可视为原路径的稳定化版本。
    # 唯一变化是去掉相邻重复像素。
    return out


def path_length_px(path_rc: list[tuple[int, int]]) -> float:
    """计算路径欧氏长度。"""

    # 单点或空路径长度都视为零。
    if len(path_rc) < 2:
        return 0.0
    length_px = 0.0
    for p0, p1 in zip(path_rc[:-1], path_rc[1:]):
        # 初始建边这里沿用欧氏长度，避免对角步被低估。
        length_px += float(np.hypot(p1[0] - p0[0], p1[1] - p0[1]))
    # 累计结果是浮点像素长度，而非 geodesic 步数。
    return length_px


__all__ = (
    "densify_line_rc",
    "dedupe_path",
    "path_length_px",
)
