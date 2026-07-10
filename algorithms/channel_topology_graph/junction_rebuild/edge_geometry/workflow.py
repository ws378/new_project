"""边几何更新与内外路径切分主流程。"""

from __future__ import annotations

from typing import Any

from ...contracts import EdgeInfo, NodeInfo
from .paths import (
    dedupe_path as _dedupe_path,
    path_length_px as _path_length_px,
    rebuild_full_path as _rebuild_full_path,
)
from .split import intersect_path_with_node_polygons, split_path_by_hits


def truncation_or_center_rc(
    node: NodeInfo,
    endpoint_geometry: dict[str, Any] | None,
) -> tuple[float, float]:
    """优先取节点端正式截断点，否则退回节点中心。"""

    # 截断点是节点几何主链的正式结果，边重建应优先服从它。
    if endpoint_geometry is not None:
        return tuple(map(float, endpoint_geometry["truncation_point_rc"]))
    # 若该节点端尚未生成截断点，只能临时回落到节点中心保持边不断裂。
    # 这种回落只影响当前边端，不改写节点自身正式几何。
    return tuple(map(float, node.point_rc))


def connector_path(endpoint_geometry: dict[str, Any] | None) -> tuple[tuple[float, float], ...]:
    """读取节点端 inner connector path。"""

    # connector path 是节点内部从中心到截断点的离散连接线。
    if endpoint_geometry is None:
        return ()
    # 返回值统一转成浮点 rc，便于和 full path 其它片段直接拼接。
    return tuple(tuple(map(float, point_rc)) for point_rc in endpoint_geometry["inner_connector_path_rc"])


def core_path_rc(edge_runtime_item: dict[str, Any]) -> list[tuple[float, float]]:
    """读取边运行时缓存的 core path。"""

    # core path 是 junction_rebuild 内部的边主干，不含节点内部 connector。
    return [tuple(map(float, point_rc)) for point_rc in edge_runtime_item.get("core_path_rc", ())]


def full_path_for_edge(
    edge: EdgeInfo,
    src_node: NodeInfo,
    dst_node: NodeInfo,
    edge_runtime_item: dict[str, Any],
    src_endpoint: dict[str, Any] | None,
    dst_endpoint: dict[str, Any] | None,
) -> list[tuple[float, float]]:
    """把节点 connector 与 core path 重建成完整边路径。"""

    # 完整路径的口径始终是：
    # src center -> src inner connector -> core path -> dst inner connector -> dst center。
    # 这里只做路径拼装，不做 polygon 求交和内外路径裁剪。
    # 这样 full path 的定义在整个边几何阶段保持唯一。
    # 节点端截断点、节点内 connector 和边主干也因此在这里完成第一次汇合。
    # 后续所有 split/debug 字段都围绕这条 full path 展开。
    # 这让“完整路径是什么”在整个阶段里不再存在第二种解释。
    return _rebuild_full_path(
        src_center_rc=tuple(map(float, src_node.point_rc)),
        dst_center_rc=tuple(map(float, dst_node.point_rc)),
        src_trunc_rc=truncation_or_center_rc(src_node, src_endpoint),
        dst_trunc_rc=truncation_or_center_rc(dst_node, dst_endpoint),
        src_inner_connector_rc=connector_path(src_endpoint),
        dst_inner_connector_rc=connector_path(dst_endpoint),
        core_path_rc=core_path_rc(edge_runtime_item),
        src_contact_rc=tuple(map(float, edge_runtime_item.get("src_contact_rc", src_node.point_rc))),
        dst_contact_rc=tuple(map(float, edge_runtime_item.get("dst_contact_rc", dst_node.point_rc))),
    )


def write_edge_geometry(
    edge: EdgeInfo,
    full_path_rc: list[tuple[float, float]],
    src_inner_path_rc: list[tuple[float, float]],
    dst_inner_path_rc: list[tuple[float, float]],
    outer_path_rc: list[tuple[float, float]],
    used_fallback: bool,
    hits: dict[str, Any],
    src_trunc_rc: tuple[float, float],
    dst_trunc_rc: tuple[float, float],
    resolution_m_per_px: float,
) -> None:
    """把重建后的路径、长度与调试字段写回边对象。"""

    # inner path 统一收成 src 内部路径 + 反向 dst 内部路径。
    edge.inner_path_rc = tuple(
        (float(point_rc[0]), float(point_rc[1]))
        for point_rc in _dedupe_path(src_inner_path_rc[:-1] + list(reversed(dst_inner_path_rc)))
    )
    # outer/full path 都按浮点 rc 写回，和合同字段口径保持一致。
    # outer_path_rc 只保留节点 polygon 之外的正式通道段。
    edge.outer_path_rc = tuple((float(point_rc[0]), float(point_rc[1])) for point_rc in outer_path_rc)
    edge.path_rc = tuple((float(point_rc[0]), float(point_rc[1])) for point_rc in full_path_rc)
    edge.length_px = float(_path_length_px(full_path_rc))
    edge.length_m = float(edge.length_px * resolution_m_per_px)
    # debug_info 里保留 split 命中和 fallback 使用情况，便于基线比对。
    # 这里不会删除旧 debug 字段，而是只覆盖本阶段直接负责的几何部分。
    # `src_inner_path_rc` / `dst_inner_path_rc` 也保留下来，便于排查节点内切分问题。
    # 命中索引和命中点一起保存，便于回放 split 的裁剪位置。
    # 节点端截断点也在这里显式落盘，避免后续调试再去 runtime 拼字段。
    # 这些字段组合起来，已经足够重建一次 split 的全部关键上下文。
    # 因而 edge.debug_info 会成为边切分基线对账的第一现场。
    # 这里刻意不再保存多余中间量，避免 debug 结构无限膨胀。
    # 但 inner/outer/full 三段和命中点则全部保留，保证可解释性。
    edge.debug_info = {
        **(edge.debug_info or {}),
        "split_hits": {
            "src_hit_index": hits["src_hit_index"],
            "dst_hit_index": hits["dst_hit_index"],
            "src_hit_point_rc": hits["src_hit_point_rc"],
            "dst_hit_point_rc": hits["dst_hit_point_rc"],
        },
        "src_inner_path_rc": [[float(r), float(c)] for r, c in src_inner_path_rc],
        "dst_inner_path_rc": [[float(r), float(c)] for r, c in dst_inner_path_rc],
        "src_truncation_point_rc": [float(src_trunc_rc[0]), float(src_trunc_rc[1])],
        "dst_truncation_point_rc": [float(dst_trunc_rc[0]), float(dst_trunc_rc[1])],
        "split_used_fallback": bool(used_fallback),
    }
    # 至此边对象上的正式几何字段就全部落稳。
    # 后续 compact / validate 阶段不再改写这些几何字段。
    # 这保证长度、路径和调试信息始终来自同一轮 split 结果。
    # 因而任一字段异常时，都可以直接回看这一轮的 split debug。
    # inner/outer/full 三套路径也在这里一次性保持同步。


def rebuild_edge_geometry(
    node_map: dict[int, NodeInfo],
    edge_map: dict[int, EdgeInfo],
    edge_runtime: dict[int, dict[str, Any]],
    resolution_m_per_px: float,
) -> dict[str, Any]:
    """根据节点 polygon 与交点结果重建边几何。"""

    updated_edge_count = 0
    fallback_split_count = 0
    for edge_id, edge in edge_map.items():
        edge_runtime_item = edge_runtime.get(int(edge_id), {})
        # 只有仍然 active 的边才参与正式几何重建。
        if not bool(edge_runtime_item.get("active", False)):
            continue

        src_node = node_map[int(edge.src_node_id)]
        dst_node = node_map[int(edge.dst_node_id)]
        # pure cycle cut 的 self-loop edge 已经在初始建边阶段形成完整正式几何；
        # 这里不能再按普通“双端不同节点”流程重切，否则会把回环压坏成单点路径。
        if str(edge_runtime_item.get("synthetic_reason", "")) == "pure_cycle_cut":
            updated_edge_count += 1
            # pure_cycle_cut 已经在初始建边时写好了完整 inner/outer/full path，这里只计数不重算。
            continue
        endpoint_geometry = edge_runtime_item.get("endpoint_geometry", {})
        src_endpoint = endpoint_geometry.get(int(edge.src_node_id))
        dst_endpoint = endpoint_geometry.get(int(edge.dst_node_id))
        # endpoint_geometry 以 node_id 为键，显式区分边两端的节点内几何。
        # 这避免 src/dst 两端的截断信息在对称边上被混用。

        full_path_rc = full_path_for_edge(
            edge=edge,
            src_node=src_node,
            dst_node=dst_node,
            edge_runtime_item=edge_runtime_item,
            src_endpoint=src_endpoint,
            dst_endpoint=dst_endpoint,
        )
        hits = intersect_path_with_node_polygons(
            full_path_rc=full_path_rc,
            src_node=src_node,
            dst_node=dst_node,
        )
        outer_path_rc, src_inner_path_rc, dst_inner_path_rc, used_fallback = split_path_by_hits(
            path_rc=full_path_rc,
            hits=hits,
            src_node=src_node,
            dst_node=dst_node,
        )
        if used_fallback:
            fallback_split_count += 1

        write_edge_geometry(
            edge=edge,
            full_path_rc=full_path_rc,
            src_inner_path_rc=src_inner_path_rc,
            dst_inner_path_rc=dst_inner_path_rc,
            outer_path_rc=outer_path_rc,
            used_fallback=used_fallback,
            hits=hits,
            src_trunc_rc=truncation_or_center_rc(src_node, src_endpoint),
            dst_trunc_rc=truncation_or_center_rc(dst_node, dst_endpoint),
            resolution_m_per_px=resolution_m_per_px,
        )
        updated_edge_count += 1

    return {
        "updated_edge_count": updated_edge_count,
        "fallback_split_count": fallback_split_count,
    }


__all__ = (
    "rebuild_edge_geometry",
)
