"""topology_graph_build 结果的归一化。"""

from __future__ import annotations

from typing import Any

from ._common import normalize_point, to_jsonable


def normalize_topology_result(topology_result: Any) -> dict[str, Any]:
    """把 topology_graph_build 结果压成稳定、可 diff 的结构。"""

    incident_port_info = dict(topology_result.incident_port_info or {})
    node_local_connection_hypothesis_info = dict(topology_result.node_local_connection_hypothesis_info or {})
    incident_port_items = tuple(incident_port_info.get("items", ()))
    hypothesis_items = tuple(node_local_connection_hypothesis_info.get("items", ()))
    return {
        "summary": {
            "graph_node_count": int(len(topology_result.graph_info.nodes)),
            "graph_edge_count": int(len(topology_result.graph_info.edges)),
            "ordered_incident_node_count": int(
                len(dict(topology_result.graph_info.meta).get("ordered_incident_edges_by_node", {}))
            ),
            "incident_port_count": int(len(incident_port_items)),
            "node_with_ports_count": int(len(dict(incident_port_info.get("items_by_node", {})))),
            "node_local_hypothesis_count": int(len(hypothesis_items)),
            "node_with_hypotheses_count": int(
                len(dict(node_local_connection_hypothesis_info.get("items_by_node", {})))
            ),
        },
        "graph_info": _normalize_graph_info(topology_result.graph_info),
        "incident_port_info": _normalize_incident_port_info(incident_port_info),
        "node_local_connection_hypothesis_info": _normalize_node_local_connection_hypothesis_info(
            node_local_connection_hypothesis_info
        ),
        "validation_info": to_jsonable(topology_result.validation_info),
        "meta": to_jsonable(topology_result.meta),
    }


def _normalize_incident_port_info(incident_port_info: dict[str, Any]) -> dict[str, Any]:
    """归一当前 topology contract 的 incident port 图层。"""

    return {
        "summary": to_jsonable(incident_port_info.get("summary", {})),
        "items": [
            {
                "port_id": int(item["port_id"]),
                "via_node_id": int(item["via_node_id"]),
                "node_type": str(item["node_type"]),
                "edge_id": int(item["edge_id"]),
                "end_type": str(item["end_type"]),
                "peer_node_id": int(item["peer_node_id"]),
                "contact_rc": _normalize_optional_point(item.get("contact_rc")),
                "heading_deg_image": _normalize_optional_float(item.get("heading_deg_image")),
                "cw_order_index": int(item["cw_order_index"]),
            }
            for item in sorted(
                tuple(incident_port_info.get("items", ())),
                key=lambda current: int(current["port_id"]),
            )
        ],
    }


def _normalize_node_local_connection_hypothesis_info(
    node_local_connection_hypothesis_info: dict[str, Any],
) -> dict[str, Any]:
    """归一当前 topology contract 的 node-local hypothesis 图层。"""

    return {
        "summary": to_jsonable(node_local_connection_hypothesis_info.get("summary", {})),
        "items": [
            {
                "hypothesis_id": int(item["hypothesis_id"]),
                "via_node_id": int(item["via_node_id"]),
                "in_port_id": int(item["in_port_id"]),
                "out_port_id": int(item["out_port_id"]),
                "in_edge_id": int(item["in_edge_id"]),
                "in_end_type": str(item["in_end_type"]),
                "in_peer_node_id": int(item["in_peer_node_id"]),
                "out_edge_id": int(item["out_edge_id"]),
                "out_end_type": str(item["out_end_type"]),
                "out_peer_node_id": int(item["out_peer_node_id"]),
                "turn_delta_deg_image": _normalize_optional_float(item.get("turn_delta_deg_image")),
                "cw_steps_from_in_to_out": int(item["cw_steps_from_in_to_out"]),
                "ccw_steps_from_in_to_out": int(item["ccw_steps_from_in_to_out"]),
                "connection_kind": str(item["connection_kind"]),
                "base_confidence": _normalize_optional_float(item.get("base_confidence")),
                "reason_tags": [str(tag) for tag in tuple(item.get("reason_tags", ()))],
            }
            for item in sorted(
                tuple(node_local_connection_hypothesis_info.get("items", ())),
                key=lambda current: int(current["hypothesis_id"]),
            )
        ],
    }


def _normalize_graph_info(graph_info: Any) -> dict[str, Any]:
    """归一 topology graph 对象里仅在该阶段建立的派生图层。"""

    graph_meta = dict(graph_info.meta)
    ordered_incident_edges_by_node = dict(graph_meta.get("ordered_incident_edges_by_node", {}))
    endpoint_geometry_by_edge = dict(graph_meta.get("edge_endpoint_geometry_by_edge", {}))
    return {
        "summary": {
            "node_count": int(len(graph_info.nodes)),
            "edge_count": int(len(graph_info.edges)),
            "stage": str(graph_meta.get("stage", "")),
        },
        "ordered_incident_edges_by_node": [
            {
                "node_id": int(node_id),
                "items": [
                    {
                        "edge_id": int(item["edge_id"]),
                        "role": str(item["role"]),
                        "peer_node_id": int(item["peer_node_id"]),
                        "contact_rc": normalize_point(item["contact_rc"]),
                        "tangent_vec_rc": normalize_point(item["tangent_vec_rc"]),
                        "heading_deg_image": _normalize_optional_float(item.get("heading_deg_image")),
                        "node_point_rc": normalize_point(item["node_point_rc"]),
                        "cw_order_index": int(item["cw_order_index"]),
                        "cw_prev_edge_id": int(item["cw_prev_edge_id"]),
                        "cw_next_edge_id": int(item["cw_next_edge_id"]),
                    }
                    for item in sorted(tuple(items), key=lambda current: int(current["cw_order_index"]))
                ],
            }
            for node_id, items in sorted(ordered_incident_edges_by_node.items(), key=lambda item: int(item[0]))
        ],
        "edge_endpoint_geometry_by_edge": [
            {
                "edge_id": int(edge_id),
                "src": _normalize_endpoint(endpoint_info["src"]),
                "dst": _normalize_endpoint(endpoint_info["dst"]),
            }
            for edge_id, endpoint_info in sorted(
                endpoint_geometry_by_edge.items(),
                key=lambda item: int(item[0]),
            )
        ],
    }


def _normalize_endpoint(endpoint: dict[str, Any]) -> dict[str, Any]:
    """归一边端点几何。"""

    return {
        "contact_rc": normalize_point(endpoint["contact_rc"]),
        "tangent_vec_rc": normalize_point(endpoint["tangent_vec_rc"]),
        "heading_deg_image": _normalize_optional_float(endpoint.get("heading_deg_image")),
    }


def _normalize_optional_point(point_rc: Any) -> list[float] | None:
    """归一可空点。"""

    if point_rc is None:
        return None
    return normalize_point(point_rc)


def _normalize_optional_float(value: Any) -> float | None:
    """归一可空浮点数。"""

    if value is None:
        return None
    return float(value)
