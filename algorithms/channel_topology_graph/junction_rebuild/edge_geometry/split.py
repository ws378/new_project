"""边路径与节点 polygon 的命中和切分逻辑。"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from ...contracts import NodeInfo
from .paths import dedupe_path


def intersect_path_with_node_polygons(
    full_path_rc: list[tuple[float, float]],
    src_node: NodeInfo,
    dst_node: NodeInfo,
) -> dict[str, Any]:
    """求完整边路径与两端节点 polygon 的命中信息。"""

    # 这里分别检查路径点是否落在 src/dst polygon 内，用于后续裁出 outer 主段。
    # 命中结果只记录索引和对应点位，保持下游 split 逻辑足够轻量。
    src_inside = path_inside_polygon_flags(full_path_rc, src_node.polygon_vertices_rc)
    dst_inside = path_inside_polygon_flags(full_path_rc, dst_node.polygon_vertices_rc)
    # src/dst 命中索引分别由各自的翻转规则独立求出。
    src_hit_index = find_src_hit_index(src_inside)
    dst_hit_index = find_dst_hit_index(dst_inside)
    # 返回结果保持 JSON 友好，不直接暴露 numpy 或 polygon 对象。
    # 上层只依赖命中索引和命中点，不依赖中间布尔序列。
    return {
        "src_hit_index": src_hit_index,
        "dst_hit_index": dst_hit_index,
        "src_hit_point_rc": None if src_hit_index is None else [float(v) for v in full_path_rc[src_hit_index]],
        "dst_hit_point_rc": None if dst_hit_index is None else [float(v) for v in full_path_rc[dst_hit_index]],
    }


def split_path_by_hits(
    path_rc: list[tuple[float, float]],
    hits: dict[str, Any],
    src_node: NodeInfo,
    dst_node: NodeInfo,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]], list[tuple[float, float]], bool]:
    """按研究算法主线把完整边路径切成 inner/outer。"""

    # 双侧命中都有效时走正常切分，否则退回 bridge 降级逻辑。
    # 这样切分策略对上层保持单一接口，不暴露具体命中异常细节。
    # 上层只需要消费统一的三段路径与 fallback 标记。
    if has_valid_hits_on_both_sides(hits):
        # 正常切分不需要 node 几何额外参与。
        return build_split_from_hits(path_rc=path_rc, hits=hits)
    # bridge 降级只在现有 path 上退回可用切分，不再向 inner path 注入节点中心点，
    # 避免把节点点位硬塞进正式边几何真值里。
    return build_split_with_fallback_bridge(
        path_rc=path_rc,
        hits=hits,
        src_node=src_node,
        dst_node=dst_node,
    )


def has_valid_hits_on_both_sides(hits: dict[str, Any]) -> bool:
    """判断 src/dst 两侧是否都找到了可用命中点。"""

    # 两侧都要命中，且 src 命中必须位于 dst 命中之前，才算可正常切分。
    src_hit_index = hits.get("src_hit_index")
    dst_hit_index = hits.get("dst_hit_index")
    # 任一侧缺失都直接失败，不尝试猜测命中点。
    if src_hit_index is None or dst_hit_index is None:
        return False
    # 顺序异常说明路径没有形成“先离开 src 再进入 dst”的正常主段。
    return int(src_hit_index) < int(dst_hit_index)


def build_split_from_hits(
    path_rc: list[tuple[float, float]],
    hits: dict[str, Any],
) -> tuple[list[tuple[float, float]], list[tuple[float, float]], list[tuple[float, float]], bool]:
    """在两侧命中都有效时按交点正常切分。"""

    # outer path 保留两次命中之间的主体区段，inner path 则各自回到节点内部。
    # dst inner 需要反转，保证其方向仍然是“由外向内”回到节点中心。
    # 这样三段路径的方向语义在 src/dst 两侧保持对称。
    src_hit_index = int(hits["src_hit_index"])
    dst_hit_index = int(hits["dst_hit_index"])
    # 交点本身保留在主体段里，避免主段与内段之间出现断点。
    outer_path_rc = list(path_rc[src_hit_index : dst_hit_index + 1])
    src_inner_path_rc = dedupe_path(list(path_rc[: src_hit_index + 1]))
    dst_inner_path_rc = dedupe_path(list(reversed(path_rc[dst_hit_index:])))
    return outer_path_rc, src_inner_path_rc, dst_inner_path_rc, False


def build_split_with_fallback_bridge(
    path_rc: list[tuple[float, float]],
    hits: dict[str, Any],
    src_node: NodeInfo,
    dst_node: NodeInfo,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]], list[tuple[float, float]], bool]:
    """在命中不足时构建 fallback bridge。"""

    # 完全没有路径时，直接退化为中心到中心的最小 bridge。
    if not path_rc:
        bridge = [tuple(map(float, src_node.point_rc)), tuple(map(float, dst_node.point_rc))]
        # 这里的 bridge 不是高保真几何，只是保证边对象最少仍有一条可解释连线。
        return bridge, [bridge[0]], [bridge[-1]], True

    src_hit_index = hits.get("src_hit_index")
    dst_hit_index = hits.get("dst_hit_index")

    # src 侧若无命中，就退回到离开起点后的第一个可用离散点；
    # dst 侧若无命中，就退回到进入终点前的最后一个可用离散点。
    # 这里沿用旧口径：fallback 只在现有 path 上取 bridge，不额外注入 node center。
    src_bridge_index = 1 if src_hit_index is None and len(path_rc) > 1 else int(src_hit_index or 0)
    dst_bridge_index = (
        len(path_rc) - 2 if dst_hit_index is None and len(path_rc) > 1 else int(dst_hit_index or (len(path_rc) - 1))
    )
    # bridge 索引仍然要钳回有效路径范围，避免空命中时越界。
    src_bridge_index = max(0, min(src_bridge_index, len(path_rc) - 1))
    dst_bridge_index = max(0, min(dst_bridge_index, len(path_rc) - 1))
    if dst_bridge_index < src_bridge_index:
        # 一旦两端顺序异常，就直接退回整条路径，保证输出仍然单调连续。
        src_bridge_index = 0
        dst_bridge_index = len(path_rc) - 1

    outer_path_rc = list(path_rc[src_bridge_index : dst_bridge_index + 1])
    src_inner_path_rc = dedupe_path(list(path_rc[: src_bridge_index + 1]))
    dst_inner_path_rc = dedupe_path(list(reversed(path_rc[dst_bridge_index:])))
    return outer_path_rc, src_inner_path_rc, dst_inner_path_rc, True


def path_inside_polygon_flags(
    path_rc: list[tuple[float, float]],
    polygon_vertices_rc: tuple[tuple[float, float], ...] | None,
) -> list[bool]:
    """判断路径点是否落在 polygon 内。"""

    if not polygon_vertices_rc:
        return [False for _ in path_rc]

    polygon_xy = np.asarray([[float(c), float(r)] for r, c in polygon_vertices_rc], dtype=np.float32)
    flags: list[bool] = []
    for point_rc in path_rc:
        dist = cv2.pointPolygonTest(polygon_xy, (float(point_rc[1]), float(point_rc[0])), False)
        flags.append(dist >= 0)
    return flags


def find_src_hit_index(src_inside: list[bool]) -> int | None:
    """找路径首次离开 src polygon 的位置。"""

    for index, is_inside in enumerate(src_inside):
        if not is_inside:
            return max(0, index - 1)
    return None


def find_dst_hit_index(dst_inside: list[bool]) -> int | None:
    """找路径最后进入 dst polygon 的位置。"""

    for index in range(len(dst_inside) - 1, -1, -1):
        if not dst_inside[index]:
            return min(len(dst_inside) - 1, index + 1)
    return None


__all__ = (
    "intersect_path_with_node_polygons",
    "split_path_by_hits",
    "path_inside_polygon_flags",
    "find_src_hit_index",
    "find_dst_hit_index",
    "has_valid_hits_on_both_sides",
    "build_split_from_hits",
    "build_split_with_fallback_bridge",
)
