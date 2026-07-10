"""topology_graph_build 测试。"""

from __future__ import annotations

import numpy as np

from algorithms.channel_topology_graph.stages.geometry_preparation import build_geometry_preparation
from algorithms.channel_topology_graph.stages.junction_rebuild import build_junction_rebuild
from algorithms.channel_topology_graph.stages.topology_graph_build import build_topology_graph


def build_cross_map(height: int = 80, width: int = 80) -> np.ndarray:
    """构造一个十字通道测试图。"""

    raw = np.zeros((height, width), dtype=np.uint8)
    raw[10:70, 36:44] = 255
    raw[36:44, 10:70] = 255
    return raw


def build_ring_cycle_map(size: int = 80) -> np.ndarray:
    """构造纯回环测试图。"""

    raw = np.zeros((size, size), dtype=np.uint8)
    raw[10:70, 10:70] = 255
    raw[22:58, 22:58] = 0
    return raw



def build_dead_end_corridor_map(size: int = 80) -> np.ndarray:
    """构造单条走廊、两端都是 dead_end 的测试图。"""

    raw = np.zeros((size, size), dtype=np.uint8)
    raw[30:50, 10:70] = 255
    return raw


def _build_geometry(raw: np.ndarray):
    """统一构造 geometry_preparation 结果。"""

    return build_geometry_preparation(
        raw_map={"gray": raw, "resolution_m_per_px": 0.05},
        config={"open_kernel_px": 1, "short_side_branch_px": 6},
    )


def _build_junction_result(raw: np.ndarray):
    """统一构造 junction_rebuild 结果。"""

    geometry_result = _build_geometry(raw)
    return build_junction_rebuild(
        geometry_preparation_result=geometry_result,
        config={
            "intersection_merge_geodesic_px": 12,
            "summary_viz": False,
            "detail_viz": False,
        },
    )


def test_build_topology_graph_builds_formal_graph_info() -> None:
    """topology_graph_build 必须第一次正式建立 graph_info。"""

    junction_result = _build_junction_result(build_cross_map())
    result = build_topology_graph(junction_result)

    assert len(result.graph_info.nodes) == len(junction_result.node_info_list)
    assert len(result.graph_info.edges) == len(junction_result.edge_info_list)
    assert result.validation_info["graph_info"]["valid"] is True


def test_ordered_incident_edges_exist_for_degree_ge_2_nodes() -> None:
    """度数大于等于 2 的节点必须有顺时针 incident edge 顺序。"""

    junction_result = _build_junction_result(build_cross_map())
    result = build_topology_graph(junction_result)

    ordered = result.graph_info.meta["ordered_incident_edges_by_node"]
    rich_nodes = [node for node in result.graph_info.nodes if node.degree >= 2]
    assert rich_nodes
    for node in rich_nodes:
        items = ordered[int(node.node_id)]
        assert len(items) == int(node.degree)
        assert all("cw_order_index" in item for item in items)
        assert all("cw_prev_edge_id" in item for item in items)
        assert all("cw_next_edge_id" in item for item in items)


def test_incident_ports_are_emitted_as_formal_stage_output() -> None:
    """topology_graph_build 必须把 incident port 作为正式结果写出。"""

    junction_result = _build_junction_result(build_cross_map())
    result = build_topology_graph(junction_result)

    port_info = result.incident_port_info
    assert port_info is not None
    assert port_info["items"]
    assert port_info["summary"]["port_count"] == len(port_info["items"])
    assert all("end_type" in item for item in port_info["items"])
    assert all("cw_order_index" in item for item in port_info["items"])


def test_topology_graph_build_validation_layers_are_closed() -> None:
    """topology_graph_build 当前只需要锁 graph / incident port / node-local hypothesis 三层校验。"""

    junction_result = _build_junction_result(build_cross_map())
    result = build_topology_graph(junction_result)

    assert result.validation_info["graph_info"]["valid"] is True
    assert result.validation_info["incident_ports"]["valid"] is True
    assert result.validation_info["node_local_connection_hypotheses"]["valid"] is True


def test_node_local_connection_hypotheses_are_emitted_as_formal_stage_output() -> None:
    """topology_graph_build 必须把 node-local hypothesis 作为正式结果写出。"""

    junction_result = _build_junction_result(build_cross_map())
    result = build_topology_graph(junction_result)

    hypothesis_info = result.node_local_connection_hypothesis_info
    assert hypothesis_info is not None
    assert hypothesis_info["items"]
    assert hypothesis_info["summary"]["hypothesis_count"] == len(hypothesis_info["items"])
    assert all("connection_kind" in item for item in hypothesis_info["items"])
    assert all("base_confidence" in item for item in hypothesis_info["items"])


