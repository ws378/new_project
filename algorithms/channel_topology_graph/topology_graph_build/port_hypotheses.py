from __future__ import annotations

"""incident port 与 node-local connection hypothesis 构造。"""

_FORWARD_KINDS = {"through", "turn", "cycle_through"}
_FOLDBACK_KINDS = {"dead_end_return", "foldback"}

from typing import Any

from ..contracts import GraphInfo


def normalize_heading_delta_deg(theta_deg: float) -> float:
    """把角度归一化到 `[-180, 180)`。"""

    normalized = float(theta_deg)
    while normalized < -180.0:
        normalized += 360.0
    while normalized >= 180.0:
        normalized -= 360.0
    # 统一半开区间后，后续 straight/foldback 阈值判断才不会在 `180/-180` 上抖动。
    return float(normalized)


def build_incident_port_info(graph_info: GraphInfo) -> dict[str, Any]:
    """把节点顺时针 incident 边视图收口成正式 incident port 对象。"""

    ordered = dict(graph_info.meta.get("ordered_incident_edges_by_node", {}))
    node_type_by_id = {int(node.node_id): str(node.node_type) for node in graph_info.nodes}
    items: list[dict[str, Any]] = []
    items_by_node: dict[int, list[dict[str, Any]]] = {}

    for node_id in sorted(int(key) for key in ordered.keys()):
        local_items: list[dict[str, Any]] = []
        for incident in ordered.get(node_id, []):
            contact_rc = incident.get("contact_rc")
            # incident port 是 sweep/topology 之间真正会复用的局部接口，所以这里只保留最小正式字段。
            item = {
                "port_id": int(len(items) + 1),
                "via_node_id": int(node_id),
                "node_type": node_type_by_id.get(int(node_id), "junction"),
                "edge_id": int(incident["edge_id"]),
                "end_type": str(incident.get("end_type", incident.get("role", "src"))),
                "peer_node_id": int(incident["peer_node_id"]),
                "contact_rc": None if contact_rc is None else [float(contact_rc[0]), float(contact_rc[1])],
                "heading_deg_image": (
                    None if incident.get("heading_deg_image") is None else float(incident["heading_deg_image"])
                ),
                "cw_order_index": int(incident.get("cw_order_index", len(local_items))),
            }
            items.append(item)
            local_items.append(item)
        if local_items:
            items_by_node[int(node_id)] = local_items

    return {
        "items": tuple(items),
        "items_by_node": items_by_node,
        "summary": {
            "port_count": int(len(items)),
            "node_with_ports_count": int(len(items_by_node)),
        },
    }


def classify_hypothesis_geometry(
    *,
    in_port: dict[str, Any],
    out_port: dict[str, Any],
    degree: int,
    straight_tol_deg: float = 35.0,
    uturn_tol_deg: float = 30.0,
) -> tuple[str, float, tuple[str, ...], float | None, int, int]:
    """按节点局部几何给正式 hypothesis 分类。"""

    in_heading = in_port.get("heading_deg_image")
    out_heading = out_port.get("heading_deg_image")
    heading_into_node = None if in_heading is None else normalize_heading_delta_deg(float(in_heading) + 180.0)
    heading_from_node = None if out_heading is None else float(out_heading)
    turn_delta = None
    if heading_into_node is not None and heading_from_node is not None:
        turn_delta = normalize_heading_delta_deg(float(heading_from_node) - float(heading_into_node))

    in_idx = int(in_port.get("cw_order_index", 0))
    out_idx = int(out_port.get("cw_order_index", 0))
    cw_steps = int((out_idx - in_idx) % degree) if degree > 0 else 0
    ccw_steps = int((in_idx - out_idx) % degree) if degree > 0 else 0

    # 节点局部几何若已经表现出接近 180 度的折返，就直接收成 foldback。
    # 这一层不再保留 历史同类折返标签，避免 topology 主线继续扩散历史语义。
    # 这里表达的是“节点局部的真折返趋势”，至于后面是否真的被 cadence 采用，属于下游决策。
    if turn_delta is not None and abs(abs(float(turn_delta)) - 180.0) <= float(uturn_tol_deg):
        return "foldback", 0.2, ("geometry:obvious_foldback",), turn_delta, cw_steps, ccw_steps
    if turn_delta is not None and abs(float(turn_delta)) <= float(straight_tol_deg):
        return "through", 1.0, ("geometry:straight",), turn_delta, cw_steps, ccw_steps
    if min(cw_steps, ccw_steps) == 1:
        return "turn", 0.8, ("geometry:adjacent_turn",), turn_delta, cw_steps, ccw_steps
    return "turn", 0.5, ("geometry:undetermined_turn",), turn_delta, cw_steps, ccw_steps


def build_pair_hypothesis(
    *,
    via_node_id: int,
    in_port: dict[str, Any],
    out_port: dict[str, Any],
    degree: int,
    connection_kind: str | None = None,
    base_confidence: float | None = None,
    reason_tags: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """构造单条 node-local hypothesis。"""

    if connection_kind is None or base_confidence is None or reason_tags is None:
        connection_kind, base_confidence, reason_tags, turn_delta, cw_steps, ccw_steps = classify_hypothesis_geometry(
            in_port=in_port,
            out_port=out_port,
            degree=degree,
        )
    else:
        in_heading = in_port.get("heading_deg_image")
        out_heading = out_port.get("heading_deg_image")
        heading_into_node = None if in_heading is None else normalize_heading_delta_deg(float(in_heading) + 180.0)
        heading_from_node = None if out_heading is None else float(out_heading)
        turn_delta = (
            None
            if heading_into_node is None or heading_from_node is None
            else normalize_heading_delta_deg(float(heading_from_node) - float(heading_into_node))
        )
        cw_steps = int((int(out_port.get("cw_order_index", 0)) - int(in_port.get("cw_order_index", 0))) % max(1, degree))
        ccw_steps = int((int(in_port.get("cw_order_index", 0)) - int(out_port.get("cw_order_index", 0))) % max(1, degree))

    return {
        "hypothesis_id": -1,
        "via_node_id": int(via_node_id),
        "in_port_id": int(in_port["port_id"]),
        "out_port_id": int(out_port["port_id"]),
        "in_edge_id": int(in_port["edge_id"]),
        "in_end_type": str(in_port["end_type"]),
        "in_peer_node_id": int(in_port["peer_node_id"]),
        "out_edge_id": int(out_port["edge_id"]),
        "out_end_type": str(out_port["end_type"]),
        "out_peer_node_id": int(out_port["peer_node_id"]),
        "turn_delta_deg_image": turn_delta,
        "cw_steps_from_in_to_out": int(cw_steps),
        "ccw_steps_from_in_to_out": int(ccw_steps),
        "connection_kind": str(connection_kind),
        "base_confidence": float(base_confidence),
        "reason_tags": tuple(reason_tags),
    }


def append_hypothesis(
    *,
    items: list[dict[str, Any]],
    items_by_node: dict[int, list[dict[str, Any]]],
    summary: dict[str, int],
    item: dict[str, Any],
) -> None:
    """把 hypothesis 写入正式集合与摘要。"""

    item = dict(item)
    item["hypothesis_id"] = int(len(items) + 1)
    items.append(item)
    items_by_node.setdefault(int(item["via_node_id"]), []).append(item)
    connection_kind = str(item["connection_kind"])
    if connection_kind in _FORWARD_KINDS:
        summary["forward_count"] += 1
    elif connection_kind in _FOLDBACK_KINDS:
        summary["foldback_count"] += 1


def build_node_local_connection_hypothesis_info(
    graph_info: GraphInfo,
    incident_port_info: dict[str, Any],
) -> dict[str, Any]:
    """基于正式 incident ports 构造 node-local connection hypotheses。"""

    items: list[dict[str, Any]] = []
    items_by_node: dict[int, list[dict[str, Any]]] = {}
    summary = {
        "forward_count": 0,
        "foldback_count": 0,
    }
    node_by_id = {int(node.node_id): node for node in graph_info.nodes}

    for node_id, local_ports in sorted(incident_port_info.get("items_by_node", {}).items()):
        node = node_by_id[int(node_id)]
        ordered_ports = sorted(
            list(local_ports),
            key=lambda item: (int(item.get("cw_order_index", 0)), int(item["port_id"])),
        )
        degree = int(len(ordered_ports))
        if degree == 0:
            # 没有 incident port 的节点对局部连接假设没有贡献，直接跳过。
            continue

        if bool(getattr(node, "is_virtual", False)) and str(getattr(node, "virtual_reason", None)) == "pure_cycle_cut":
            if degree < 2:
                # pure_cycle_cut 理论上应有两个 port；不足两端时宁可不产出 through 假设。
                continue
            append_hypothesis(
                items=items,
                items_by_node=items_by_node,
                summary=summary,
                item=build_pair_hypothesis(
                    via_node_id=int(node_id),
                    in_port=ordered_ports[0],
                    out_port=ordered_ports[1],
                    degree=degree,
                    connection_kind="cycle_through",
                    base_confidence=1.0,
                    reason_tags=("synthetic:pure_cycle_cut",),
                ),
            )
            append_hypothesis(
                items=items,
                items_by_node=items_by_node,
                summary=summary,
                item=build_pair_hypothesis(
                    via_node_id=int(node_id),
                    in_port=ordered_ports[1],
                    out_port=ordered_ports[0],
                    degree=degree,
                    connection_kind="cycle_through",
                    base_confidence=1.0,
                    reason_tags=("synthetic:pure_cycle_cut",),
                ),
            )
            continue

        if str(node.node_type) == "dead_end" and degree == 1:
            port = ordered_ports[0]
            # 单端 dead_end 的正式语义只能是“进来后原端返回”，不能再生成 through/turn 假设。
            append_hypothesis(
                items=items,
                items_by_node=items_by_node,
                summary=summary,
                item=build_pair_hypothesis(
                    via_node_id=int(node_id),
                    in_port=port,
                    out_port=port,
                    degree=degree,
                    connection_kind="dead_end_return",
                    base_confidence=1.0,
                    reason_tags=("synthetic:dead_end_single_port",),
                ),
            )
            continue

        if degree < 2:
            # 普通节点若连两个 port 都没有，就不存在可连接的 in->out 对。
            continue

        for in_port in ordered_ports:
            for out_port in ordered_ports:
                if int(in_port["port_id"]) == int(out_port["port_id"]):
                    # 普通节点的 pair 假设只讨论“从一条边进、从另一条边出”，不在这里制造 self-pair。
                    continue
                append_hypothesis(
                    items=items,
                    items_by_node=items_by_node,
                    summary=summary,
                    item=build_pair_hypothesis(
                        via_node_id=int(node_id),
                        in_port=in_port,
                        out_port=out_port,
                        degree=degree,
                    ),
                )

    return {
        "items": tuple(items),
        "items_by_node": items_by_node,
        "summary": {
            "hypothesis_count": int(len(items)),
            "node_with_hypotheses_count": int(len(items_by_node)),
            **summary,
        },
    }
