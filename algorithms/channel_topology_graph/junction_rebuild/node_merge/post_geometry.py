"""边切分后二次交汇合并候选判定。

这个模块只处理 junction_rebuild 内部已经完成 polygon 与 edge split 之后才暴露的语义：
如果两端交汇 polygon 已经把一条 junction-junction 边压到几乎没有外部通道段，
它不应继续作为普通 coverage lane 进入下游，而应回到节点合并层收口。
"""

from __future__ import annotations

from typing import Any

from ...contracts import EdgeInfo, NodeInfo
from ..edge_geometry.paths import path_length_px
from .groups import graph_components


def post_geometry_outer_path_min_length_m(config: dict[str, Any]) -> float:
    """读取二次合并的 outer path 米制短边门限。"""

    # 使用米制门限，避免同一 20px 在不同分辨率地图上表达不同真实宽度。
    return float(config.get("post_geometry_merge_outer_path_min_length_m", 0.5))


def post_geometry_full_path_max_merge_length_m(config: dict[str, Any]) -> float:
    """读取允许直接合并的完整边长上限。"""

    # full path 上限用于区分“本来就是短内部边”和“长边被 polygon 异常侵蚀”。
    # 后者不直接合并，否则可能把真实长通道两端交汇错误收成一个节点。
    return float(config.get("post_geometry_merge_full_path_max_merge_length_m", 3.0))


def post_geometry_outer_path_anomaly_ratio(config: dict[str, Any]) -> float:
    """读取 outer/full 比例异常门限。"""

    # 比例门限专门标记 polygon/split 侵蚀异常，不直接作为普通合并条件。
    return float(config.get("post_geometry_merge_outer_path_anomaly_ratio", 0.1))


def max_post_geometry_merge_iterations(config: dict[str, Any]) -> int:
    """读取二次合并最大迭代次数。"""

    # 合并后必须重建 polygon 与 edge split；限制轮数可避免异常图上无限震荡。
    return max(0, int(config.get("max_post_geometry_merge_iterations", 2)))


def derive_post_geometry_merge_candidates(
    *,
    node_map: dict[int, NodeInfo],
    edge_map: dict[int, EdgeInfo],
    node_runtime: dict[int, dict[str, Any]],
    edge_runtime: dict[int, dict[str, Any]],
    resolution_m_per_px: float,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """从 edge split 结果中提取可执行二次交汇合并候选。"""

    candidates: list[dict[str, Any]] = []
    outer_min_m = post_geometry_outer_path_min_length_m(config)
    full_max_m = post_geometry_full_path_max_merge_length_m(config)
    for view in iter_post_geometry_edge_views(
        node_map=node_map,
        edge_map=edge_map,
        node_runtime=node_runtime,
        edge_runtime=edge_runtime,
        resolution_m_per_px=resolution_m_per_px,
    ):
        if (
            view["outer_path_length_m"] < outer_min_m
            and view["full_path_length_m"] <= full_max_m
            and bool(view["split_evidence"]["reliable_split_hits"])
        ):
            # A 类：完整边本身不长，polygon 外部段又小于真实可覆盖长度下限。
            # 但它还必须有可靠 split hits，证明 outer 段确实由两端 polygon 命中点夹出。
            candidates.append(
                build_post_geometry_candidate_record(
                    view=view,
                    action="merge",
                    reason="outer_path_too_short",
                    config=config,
                )
            )
    return candidates


def derive_post_split_geometry_anomalies(
    *,
    node_map: dict[int, NodeInfo],
    edge_map: dict[int, EdgeInfo],
    node_runtime: dict[int, dict[str, Any]],
    edge_runtime: dict[int, dict[str, Any]],
    resolution_m_per_px: float,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """从 edge split 结果中提取不参与合并的几何异常。"""

    anomalies: list[dict[str, Any]] = []
    outer_min_m = post_geometry_outer_path_min_length_m(config)
    full_max_m = post_geometry_full_path_max_merge_length_m(config)
    anomaly_ratio = post_geometry_outer_path_anomaly_ratio(config)
    for view in iter_post_geometry_edge_views(
        node_map=node_map,
        edge_map=edge_map,
        node_runtime=node_runtime,
        edge_runtime=edge_runtime,
        resolution_m_per_px=resolution_m_per_px,
    ):
        outer_is_tiny = view["outer_path_length_m"] < outer_min_m
        full_can_merge = view["full_path_length_m"] <= full_max_m
        split_is_reliable = bool(view["split_evidence"]["reliable_split_hits"])
        if outer_is_tiny and full_can_merge and split_is_reliable:
            # 已经满足 A 类 merge 的可靠内部短边，不再重复归入 anomaly。
            continue

        if outer_is_tiny and full_can_merge and not split_is_reliable:
            # 外部段很短但 split hits 不可靠时，不能把 fallback 或顺序异常伪装成内部短边。
            anomalies.append(
                build_post_geometry_candidate_record(
                    view=view,
                    action="debug_anomaly",
                    reason="unreliable_split_hits_for_short_outer_path",
                    config=config,
                )
            )
            continue

        if outer_is_tiny and not full_can_merge:
            # B 类：外部段极短但整条边很长，优先视为 polygon/split 侵蚀异常。
            # 这里不直接合并，避免把真实长通道两端交汇误收成一个节点。
            anomalies.append(
                build_post_geometry_candidate_record(
                    view=view,
                    action="debug_anomaly",
                    reason="long_edge_with_tiny_outer_path",
                    config=config,
                )
            )
            continue

        if view["outer_ratio"] < anomaly_ratio:
            # B 类：outer/full 比例极低，说明边主体大部分被节点 polygon 吞掉。
            # 即使 outer 绝对长度不小，也应进入 debug，而不是悄悄放入下游。
            anomalies.append(
                build_post_geometry_candidate_record(
                    view=view,
                    action="debug_anomaly",
                    reason="outer_path_ratio_too_low",
                    config=config,
                )
            )
    return anomalies


def iter_post_geometry_edge_views(
    *,
    node_map: dict[int, NodeInfo],
    edge_map: dict[int, EdgeInfo],
    node_runtime: dict[int, dict[str, Any]],
    edge_runtime: dict[int, dict[str, Any]],
    resolution_m_per_px: float,
) -> list[dict[str, Any]]:
    """收集可被 post-geometry 规则审查的 junction-junction edge 视图。"""

    views: list[dict[str, Any]] = []
    for edge_id in sorted(edge_map):
        if not bool(edge_runtime.get(edge_id, {}).get("active", False)):
            # 只审查当前仍作为正式拓扑候选存在的边；已失效边不应再次驱动 merge。
            continue
        edge = edge_map[edge_id]
        src_node = node_map.get(int(edge.src_node_id))
        dst_node = node_map.get(int(edge.dst_node_id))
        if src_node is None or dst_node is None:
            # 边端点缺失属于前置闭环问题，不在二次合并规则里补救。
            continue
        if not bool(node_runtime.get(int(src_node.node_id), {}).get("active", False)):
            # inactive 节点已经不属于当前拓扑表，不允许继续触发合并。
            continue
        if not bool(node_runtime.get(int(dst_node.node_id), {}).get("active", False)):
            # 两端都必须是当前 active 节点，否则候选证据会引用旧对象。
            continue
        if src_node.node_type != "junction" or dst_node.node_type != "junction":
            # dead_end 短边可能是真实末端通道，不能按交汇内部边直接吞并。
            continue

        full_path_length_px = float(path_length_px(list(edge.path_rc)))
        if full_path_length_px <= 0.0:
            # 没有完整边长就不能稳定计算比例；交给对象校验暴露，而不是用猜测合并。
            continue
        outer_path_length_px = float(path_length_px(list(edge.outer_path_rc)))
        views.append(
            {
                "edge_id": int(edge.edge_id),
                "src_node_id": int(edge.src_node_id),
                "dst_node_id": int(edge.dst_node_id),
                "outer_path_length_px": outer_path_length_px,
                "full_path_length_px": full_path_length_px,
                "outer_path_length_m": float(outer_path_length_px * float(resolution_m_per_px)),
                "full_path_length_m": float(full_path_length_px * float(resolution_m_per_px)),
                "outer_ratio": float(outer_path_length_px / full_path_length_px),
                "split_evidence": split_evidence_for_edge(edge),
            }
        )
    return views


def split_evidence_for_edge(edge: EdgeInfo) -> dict[str, Any]:
    """从 edge.debug_info 中提取 post-geometry merge 所需的 split 证据。"""

    debug_info = edge.debug_info or {}
    split_hits = debug_info.get("split_hits", {}) or {}
    src_hit_index = split_hits.get("src_hit_index")
    dst_hit_index = split_hits.get("dst_hit_index")
    split_used_fallback = bool(debug_info.get("split_used_fallback", False))
    reliable_split_hits = (
        src_hit_index is not None
        and dst_hit_index is not None
        and int(src_hit_index) < int(dst_hit_index)
        and not split_used_fallback
    )
    return {
        "reliable_split_hits": bool(reliable_split_hits),
        "split_used_fallback": split_used_fallback,
        "src_hit_index": None if src_hit_index is None else int(src_hit_index),
        "dst_hit_index": None if dst_hit_index is None else int(dst_hit_index),
        "hit_index_gap": (
            None
            if src_hit_index is None or dst_hit_index is None
            else int(dst_hit_index) - int(src_hit_index)
        ),
        "src_hit_point_rc": split_hits.get("src_hit_point_rc"),
        "dst_hit_point_rc": split_hits.get("dst_hit_point_rc"),
    }


def build_post_geometry_candidate_record(
    *,
    view: dict[str, Any],
    action: str,
    reason: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """组装二次合并候选调试记录。"""

    # debug 同时保留 m 与 px：正式判断读 m，回看图像几何时仍可定位到像素尺度。
    return {
        "edge_id": int(view["edge_id"]),
        "src_node_id": int(view["src_node_id"]),
        "dst_node_id": int(view["dst_node_id"]),
        "outer_path_length_px": float(view["outer_path_length_px"]),
        "full_path_length_px": float(view["full_path_length_px"]),
        "outer_path_length_m": float(view["outer_path_length_m"]),
        "full_path_length_m": float(view["full_path_length_m"]),
        "outer_ratio": float(view["outer_ratio"]),
        "split_evidence": view["split_evidence"],
        "action": str(action),
        "reason": str(reason),
        "thresholds": {
            "outer_path_min_length_m": post_geometry_outer_path_min_length_m(config),
            "full_path_max_merge_length_m": post_geometry_full_path_max_merge_length_m(config),
            "outer_path_anomaly_ratio": post_geometry_outer_path_anomaly_ratio(config),
        },
    }


def derive_post_geometry_merge_groups(
    candidates: list[dict[str, Any]],
) -> list[list[int]]:
    """把二次合并候选边收成节点 merge group。"""

    adjacency: dict[int, set[int]] = {}
    for candidate in candidates:
        if str(candidate.get("action")) != "merge":
            # anomaly 只进入 debug，不参与节点合并。
            continue
        src_node_id = int(candidate["src_node_id"])
        dst_node_id = int(candidate["dst_node_id"])
        adjacency.setdefault(src_node_id, set()).add(dst_node_id)
        adjacency.setdefault(dst_node_id, set()).add(src_node_id)
        # 多条短内部边串联时，连通分量会自然合成同一个 merge group。

    return [list(component) for component in graph_components(adjacency) if len(component) > 1]


def validate_post_geometry_merge_result(
    *,
    node_map: dict[int, NodeInfo],
    edge_map: dict[int, EdgeInfo],
    node_runtime: dict[int, dict[str, Any]],
    edge_runtime: dict[int, dict[str, Any]],
    merge_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """校验一次 post-geometry merge 写回后的内部闭环。"""

    errors: list[str] = []
    inactive_node_ids = {
        int(node_id)
        for node_id, runtime in node_runtime.items()
        if not bool(runtime.get("active", False))
    }
    for edge_id, edge in edge_map.items():
        if not bool(edge_runtime.get(int(edge_id), {}).get("active", False)):
            continue
        if int(edge.src_node_id) in inactive_node_ids or int(edge.dst_node_id) in inactive_node_ids:
            errors.append(f"active edge {edge_id} references inactive node")
        is_non_synthetic_self_loop = (
            int(edge.src_node_id) == int(edge.dst_node_id)
            and str(edge_runtime.get(int(edge_id), {}).get("synthetic_reason", "")) != "pure_cycle_cut"
        )
        if is_non_synthetic_self_loop:
            errors.append(f"active edge {edge_id} became self-loop after post-geometry merge")

    for candidate in merge_candidates:
        edge_id = int(candidate["edge_id"])
        if bool(edge_runtime.get(edge_id, {}).get("active", False)):
            errors.append(f"post-geometry internal edge {edge_id} is still active")

    return {
        "valid": not errors,
        "error_count": int(len(errors)),
        "errors": errors,
        "checked_merge_edge_ids": [int(candidate["edge_id"]) for candidate in merge_candidates],
    }


__all__ = (
    "derive_post_geometry_merge_candidates",
    "derive_post_geometry_merge_groups",
    "derive_post_split_geometry_anomalies",
    "iter_post_geometry_edge_views",
    "max_post_geometry_merge_iterations",
    "post_geometry_full_path_max_merge_length_m",
    "post_geometry_outer_path_anomaly_ratio",
    "post_geometry_outer_path_min_length_m",
    "split_evidence_for_edge",
    "validate_post_geometry_merge_result",
)
