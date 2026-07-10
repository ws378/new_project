"""junction_rebuild 结果的归一化。"""

from __future__ import annotations

from typing import Any

from ._common import normalize_path, normalize_point, to_jsonable


def normalize_junction_result(junction_result: Any) -> dict[str, Any]:
    """把 junction_rebuild 结果压成稳定、可 diff 的结构。"""

    nodes = sorted(
        (_normalize_node_info(item) for item in tuple(junction_result.node_info_list)),
        key=lambda item: int(item["node_id"]),
    )
    edges = sorted(
        (_normalize_edge_info(item) for item in tuple(junction_result.edge_info_list)),
        key=lambda item: int(item["edge_id"]),
    )
    return {
        "summary": {
            "node_count": int(len(nodes)),
            "edge_count": int(len(edges)),
            "junction_node_count": int(sum(1 for item in nodes if item["node_type"] == "junction")),
            "dead_end_node_count": int(sum(1 for item in nodes if item["node_type"] == "dead_end")),
            "polygon_node_count": int(sum(1 for item in nodes if item["polygon_vertices_rc"])),
            "edge_outer_path_count": int(sum(1 for item in edges if item["outer_path_rc"])),
            "edge_inner_path_count": int(sum(1 for item in edges if item["inner_path_rc"])),
        },
        "nodes": nodes,
        "edges": edges,
        "validation_info": to_jsonable(junction_result.validation_info),
        "meta": to_jsonable(junction_result.meta),
    }


def _normalize_node_info(node_info: Any) -> dict[str, Any]:
    """把正式节点对象转成稳定 JSON。"""

    return {
        "node_id": int(node_info.node_id),
        "node_type": str(node_info.node_type),
        "point_rc": normalize_point(node_info.point_rc),
        "incident_edge_ids": [int(edge_id) for edge_id in sorted(tuple(node_info.incident_edge_ids))],
        "degree": int(node_info.degree),
        "polygon_vertices_rc": normalize_path(node_info.polygon_vertices_rc),
        "validation_info": to_jsonable(node_info.validation_info),
    }


def _normalize_edge_info(edge_info: Any) -> dict[str, Any]:
    """把正式边对象转成稳定 JSON。"""

    return {
        "edge_id": int(edge_info.edge_id),
        "src_node_id": int(edge_info.src_node_id),
        "dst_node_id": int(edge_info.dst_node_id),
        "inner_path_rc": normalize_path(edge_info.inner_path_rc),
        "outer_path_rc": normalize_path(edge_info.outer_path_rc),
        "path_rc": normalize_path(edge_info.path_rc),
        "length_px": float(edge_info.length_px),
        "length_m": float(edge_info.length_m),
        "edge_type": str(edge_info.edge_type) if edge_info.edge_type is not None else None,
        "coverage_info": to_jsonable(edge_info.coverage_info),
        "validation_info": to_jsonable(edge_info.validation_info),
    }
