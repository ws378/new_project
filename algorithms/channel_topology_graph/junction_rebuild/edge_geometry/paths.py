"""边完整路径重建与通用路径工具。"""

from __future__ import annotations

import numpy as np


def rebuild_full_path(
    src_center_rc: tuple[float, float],
    dst_center_rc: tuple[float, float],
    src_trunc_rc: tuple[float, float],
    dst_trunc_rc: tuple[float, float],
    src_inner_connector_rc: tuple[tuple[float, float], ...],
    dst_inner_connector_rc: tuple[tuple[float, float], ...],
    core_path_rc: list[tuple[float, float]],
    src_contact_rc: tuple[float, float],
    dst_contact_rc: tuple[float, float],
) -> list[tuple[float, float]]:
    """按“src 内部段 + 主体路径 + dst 内部段”重建完整边路径。"""

    # 节点内部 connector 若已由节点几何求出，就优先复用；
    # 若缺失，则退回到“中心点 -> truncation 点”的离散直线补段。
    if src_inner_connector_rc:
        src_inner_path_rc = [tuple(map(float, point_rc)) for point_rc in src_inner_connector_rc]
    else:
        src_inner_path_rc = densify_line_rc(src_center_rc, src_trunc_rc)

    if dst_inner_connector_rc:
        dst_inner_path_rc = [tuple(map(float, point_rc)) for point_rc in dst_inner_connector_rc]
    else:
        # 这里先按“dst 中心 -> dst truncation”生成，再在最终拼接时整体反向，
        # 保证最终 tail 仍然是从主体段回到 dst 中心。
        dst_inner_path_rc = densify_line_rc(dst_center_rc, dst_trunc_rc)

    # core path 代表 polygon 外的主体骨架方向。
    # 两端 contact 只负责把主体骨架接回到节点边界，不改写主体方向。
    core_oriented_rc = densify_core_contacts(
        src_contact_rc=src_contact_rc,
        dst_contact_rc=dst_contact_rc,
        core_path_rc=core_path_rc,
    )

    # 正式 truncation 点要先回投到离散主体链上，之后才能稳定抽取中段。
    src_cut_index = nearest_path_index(core_oriented_rc, src_trunc_rc)
    dst_cut_index = nearest_path_index(core_oriented_rc, dst_trunc_rc)
    if dst_cut_index < src_cut_index:
        # 若主体方向与 src/dst 语义相反，就整体翻转语义，保持最终 full path
        # 始终是“src 中心 -> dst 中心”的方向约定。
        src_cut_index, dst_cut_index = dst_cut_index, src_cut_index
        src_trunc_rc, dst_trunc_rc = dst_trunc_rc, src_trunc_rc
        src_inner_path_rc, dst_inner_path_rc = dst_inner_path_rc, src_inner_path_rc
        # 连同两端 inner path 一起交换，才能保证后续拼接仍然左右一致。

    core_middle_rc = list(core_oriented_rc[src_cut_index : dst_cut_index + 1])
    if not core_middle_rc:
        core_middle_rc = [
            (float(src_trunc_rc[0]), float(src_trunc_rc[1])),
            (float(dst_trunc_rc[0]), float(dst_trunc_rc[1])),
        ]
    else:
        # 正式主体段两端必须落在正式 truncation 点，不保留旧 contact 点位。
        core_middle_rc[0] = (float(src_trunc_rc[0]), float(src_trunc_rc[1]))
        core_middle_rc[-1] = (float(dst_trunc_rc[0]), float(dst_trunc_rc[1]))

    dst_tail_rc = list(reversed(dst_inner_path_rc))
    # 拼接时只去掉相邻重复点，不做抽稀，保持几何真值与长度口径稳定。
    full_path_rc = dedupe_path(src_inner_path_rc[:-1] + core_middle_rc + dst_tail_rc[1:])
    if not full_path_rc:
        # 理论上不应为空；若极端异常发生，就退回到最保守的四点骨架。
        full_path_rc = dedupe_path([src_center_rc, src_trunc_rc, dst_trunc_rc, dst_center_rc])
    return full_path_rc


def densify_core_contacts(
    src_contact_rc: tuple[float, float],
    dst_contact_rc: tuple[float, float],
    core_path_rc: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """把 contact 点与主体骨架拼成连续路径。"""

    if not core_path_rc:
        return dedupe_path(densify_line_rc(src_contact_rc, dst_contact_rc))

    # 只在主体骨架两端补齐 contact 缺口，不重写骨架内部顺序。
    head_rc = densify_line_rc(src_contact_rc, core_path_rc[0])
    tail_rc = densify_line_rc(core_path_rc[-1], dst_contact_rc)
    return dedupe_path(head_rc[:-1] + core_path_rc + tail_rc[1:])


def nearest_path_index(path_rc: list[tuple[float, float]], point_rc: tuple[float, float]) -> int:
    """找离目标点最近的离散路径索引。"""

    if not path_rc:
        return 0
    return min(
        range(len(path_rc)),
        key=lambda index: (
            (float(path_rc[index][0]) - float(point_rc[0])) ** 2
            + (float(path_rc[index][1]) - float(point_rc[1])) ** 2,
            index,
        ),
    )


def densify_line_rc(
    start_rc: tuple[float, float],
    end_rc: tuple[float, float],
) -> list[tuple[float, float]]:
    """把短直线离散成连续像素级路径。"""

    row_0, col_0 = float(start_rc[0]), float(start_rc[1])
    row_1, col_1 = float(end_rc[0]), float(end_rc[1])
    steps = max(1, int(round(max(abs(row_1 - row_0), abs(col_1 - col_0)))))
    out: list[tuple[float, float]] = []
    for step in range(steps + 1):
        alpha = step / steps
        point_rc = (
            float(row_0 + (row_1 - row_0) * alpha),
            float(col_0 + (col_1 - col_0) * alpha),
        )
        if not out or np.hypot(out[-1][0] - point_rc[0], out[-1][1] - point_rc[1]) > 1e-6:
            out.append(point_rc)
    return out


def dedupe_path(path_rc: list[tuple[int, int]] | list[tuple[float, float]]) -> list[tuple[float, float]]:
    """去掉路径中的相邻重复点。"""

    out: list[tuple[float, float]] = []
    for point_rc in path_rc:
        point = (float(point_rc[0]), float(point_rc[1]))
        if not out or np.hypot(out[-1][0] - point[0], out[-1][1] - point[1]) > 1e-6:
            out.append(point)
    return out


def path_length_px(path_rc: list[tuple[float, float]]) -> float:
    """按欧氏距离累计路径长度。"""

    if len(path_rc) < 2:
        return 0.0
    return float(
        sum(np.hypot(point_b[0] - point_a[0], point_b[1] - point_a[1]) for point_a, point_b in zip(path_rc[:-1], path_rc[1:]))
    )


__all__ = (
    "densify_core_contacts",
    "nearest_path_index",
    "densify_line_rc",
    "dedupe_path",
    "path_length_px",
    "rebuild_full_path",
)
