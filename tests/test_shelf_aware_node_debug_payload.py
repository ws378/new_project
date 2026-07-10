from __future__ import annotations

import json

import numpy as np
import pytest

from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.node_debug import (
    candidate_debug_payload,
    collect_unvisited_node_ids,
    node_debug_payload,
    save_node_debug_json,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.graph_build.grid_builder import (
    build_cell_candidates,
    build_coverage_graph,
    build_legacy_node_matrix,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import Node
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_graph_access import (
    TraversalGraphAccess,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_state import (
    TraversalState,
)
from tests.shelf_aware_graph_fixture import build_coverage_graph_from_legacy_node_fixture


def _node(row: int, col: int, *, obstacle: bool = False) -> Node:
    return Node(
        planning_point_px=(10 + col * 10, 10 + row * 10),
        grid_center_px=(10 + col * 10, 10 + row * 10),
        obstacle=obstacle,
        grid_row=row,
        grid_col=col,
    )


def test_node_debug_payload_requires_graph_and_state_inputs() -> None:
    with pytest.raises(TypeError):
        node_debug_payload("r0_c0")
    with pytest.raises(TypeError):
        candidate_debug_payload("r0_c0", 1.0)


def test_node_debug_payload_uses_graph_and_state_when_legacy_node_is_stale() -> None:
    start = _node(0, 0)
    accessible_neighbor = _node(0, 1)
    obstacle_neighbor = _node(1, 0, obstacle=True)
    start.neighbors.extend([accessible_neighbor, obstacle_neighbor])
    accessible_neighbor.neighbors.append(start)
    obstacle_neighbor.neighbors.append(start)
    nodes = [[start, accessible_neighbor], [obstacle_neighbor]]
    coverage_graph = build_coverage_graph_from_legacy_node_fixture(nodes)
    graph_access = TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=nodes,
        coverage_graph=coverage_graph,
    )
    traversal_state = TraversalState.from_start(
        accessible_cell_ids=graph_access.accessible_cell_ids(),
        start_cell_id=start.stable_id,
    )

    start.obstacle = True
    start.visited = False
    start.visit_count = 99
    obstacle_neighbor.obstacle = False

    payload = node_debug_payload(
        start.stable_id,
        include_neighbors=True,
        traversal_state=traversal_state,
        graph_access=graph_access,
    )

    assert payload["node_id"] == start.stable_id
    assert payload["obstacle"] is False
    assert payload["generated_planning_point_px_rotated"] == [10, 10]
    assert payload["generation_offset_from_grid_center_px"] == [0, 0]
    assert payload["generation_offset_distance_px"] == 0.0
    assert payload["generation_mode"] == "unspecified"
    assert payload["generation_status"] == "unspecified"
    assert payload["endpoint_alignment_applied"] is False
    assert payload["endpoint_alignment_offset_px"] == [0, 0]
    assert payload["visited"] is True
    assert payload["visit_count"] == 1
    assert payload["non_obstacle_neighbor_count"] == 1
    assert payload["obstacle_neighbor_count"] == 1
    assert payload["neighbor_ids"] == [accessible_neighbor.stable_id]

    obstacle_payload = node_debug_payload(
        obstacle_neighbor.stable_id,
        traversal_state=traversal_state,
        graph_access=graph_access,
    )
    assert obstacle_payload["obstacle"] is True
    assert obstacle_payload["visited"] is False
    assert obstacle_payload["visit_count"] == 0


def test_node_debug_payload_exposes_real_generation_provenance() -> None:
    room_map = np.zeros((30, 30), dtype=np.uint8)
    room_map[13, 15] = 255
    cell_grid = build_cell_candidates(
        room_map,
        (0, 0),
        (30, 30),
        10,
        robot_half_width_px=4.0,
        node_generation_mode="turn_cost_repaired_grid",
        repaired_grid_max_offset_factor=0.35,
        row_endpoint_alignment_enable=False,
    )
    coverage_graph = build_coverage_graph(cell_grid)
    legacy_node_matrix = build_legacy_node_matrix(cell_grid)
    graph_access = TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=legacy_node_matrix,
        coverage_graph=coverage_graph,
    )
    traversal_state = TraversalState.from_start(
        accessible_cell_ids=graph_access.accessible_cell_ids(),
        start_cell_id="r1_c1",
    )

    payload = node_debug_payload(
        "r1_c1",
        traversal_state=traversal_state,
        graph_access=graph_access,
    )

    assert payload["planning_point_px_rotated"] == [15, 13]
    assert payload["grid_center_px_rotated"] == [15, 15]
    assert payload["generated_planning_point_px_rotated"] == [15, 13]
    assert payload["generation_offset_from_grid_center_px"] == [0, -2]
    assert payload["generation_offset_distance_px"] == 2.0
    assert payload["generation_mode"] == "turn_cost_repaired_grid"
    assert payload["generation_status"] == "bounded_repaired"
    assert payload["endpoint_alignment_applied"] is False
    assert payload["endpoint_alignment_offset_px"] == [0, 0]


def test_candidate_debug_payload_and_unvisited_ids_use_state_and_graph_truth() -> None:
    start = _node(0, 0)
    target = _node(0, 1)
    blocked = _node(0, 2, obstacle=True)
    nodes = [[start, target, blocked]]
    coverage_graph = build_coverage_graph_from_legacy_node_fixture(nodes)
    graph_access = TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=nodes,
        coverage_graph=coverage_graph,
    )
    traversal_state = TraversalState.from_start(
        accessible_cell_ids=graph_access.accessible_cell_ids(),
        start_cell_id=start.stable_id,
    )

    target.obstacle = True
    target.visited = True
    target.visit_count = 7

    payload = candidate_debug_payload(
        target.stable_id,
        3.5,
        traversal_state=traversal_state,
        graph_access=graph_access,
    )

    assert payload["obstacle"] is False
    assert payload["visited"] is False
    assert payload["visit_count"] == 0
    assert payload["energy"] == 3.5
    assert collect_unvisited_node_ids(
        traversal_state=traversal_state,
        graph_access=graph_access,
    ) == [target.stable_id]


def test_save_node_debug_json_uses_graph_geometry_when_legacy_node_is_stale(tmp_path) -> None:
    node = _node(0, 0)
    nodes = [[node]]
    coverage_graph = build_coverage_graph_from_legacy_node_fixture(nodes)
    graph_access = TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=nodes,
        coverage_graph=coverage_graph,
    )
    traversal_state = TraversalState.from_start(
        accessible_cell_ids=graph_access.accessible_cell_ids(),
        start_cell_id=node.stable_id,
    )
    node.planning_point_px = (30, 30)
    node.obstacle = True
    node.visited = False
    node.visit_count = 99
    json_path = tmp_path / "node_debug_enriched.json"
    rotated_room_map = np.full((40, 40), 255, dtype=np.uint8)
    rotated_room_map[:, 0] = 0

    save_node_debug_json(
        json_path,
        rotated_room_map=rotated_room_map,
        map_resolution=0.1,
        inverse_rotation=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32),
        map_origin=(1.0, 2.0),
        map_height=50,
        graph_access=graph_access,
        traversal_state=traversal_state.to_snapshot(),
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert len(payload) == 1
    assert payload[0]["node_id"] == node.stable_id
    assert payload[0]["obstacle"] is False
    assert payload[0]["planning_point_px_rotated"] == [10, 10]
    assert payload[0]["planning_point_pixel"] == [10.0, 10.0]
    assert payload[0]["planning_point_world"] == [2.0, 6.0]
    assert 0.8 < payload[0]["min_distance_m"] < 1.2
    assert payload[0]["visited"] is True
    assert payload[0]["visit_count"] == 1
