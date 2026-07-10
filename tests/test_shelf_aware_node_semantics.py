from __future__ import annotations

import numpy as np

from algorithms.coverage_planning.planners.shelf_aware_guarded.models import Node
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_graph_access import (
    TraversalGraphAccess,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.final_path.node_semantics import (
    build_node_semantics,
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


def test_node_semantics_reads_static_graph_snapshot_when_legacy_node_is_stale() -> None:
    start = _node(0, 0)
    accessible_neighbor = _node(0, 1)
    obstacle_neighbor = _node(1, 0, obstacle=True)
    start.neighbors = [accessible_neighbor, obstacle_neighbor]
    accessible_neighbor.neighbors = [start]
    obstacle_neighbor.neighbors = [start]
    nodes = [[start, accessible_neighbor], [obstacle_neighbor]]
    start_cell_id = start.stable_id
    accessible_neighbor_cell_id = accessible_neighbor.stable_id
    obstacle_neighbor_cell_id = obstacle_neighbor.stable_id
    coverage_graph = build_coverage_graph_from_legacy_node_fixture(nodes)
    graph_access = TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=nodes,
        coverage_graph=coverage_graph,
    )

    start.obstacle = True
    start.planning_point_px = (90, 90)
    start.grid_row = 9
    start.grid_col = 9
    start.neighbors = []
    accessible_neighbor.obstacle = True
    obstacle_neighbor.obstacle = False
    rotated_room_map = np.full((120, 120), 255, dtype=np.uint8)
    rotated_room_map[10, 9] = 0

    payload = build_node_semantics(
        graph_access=graph_access,
        free_mask=np.full((120, 120), 255, dtype=np.uint8),
        territory_label_map=None,
        junction_label_map=None,
        inverse_rotation_matrix=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32),
        rotated_room_map=rotated_room_map,
        coverage_width_px=4,
        coverage_width_m=0.2,
        resolution_m_per_px=0.05,
    )

    start_record = payload["node_by_id"][start_cell_id]
    assert obstacle_neighbor_cell_id not in payload["node_by_id"]
    assert payload["summary"]["node_count"] == 2
    assert [item["node_id"] for item in payload["nodes"]] == [
        start_cell_id,
        accessible_neighbor_cell_id,
    ]
    assert start_record["grid_row"] == 0
    assert start_record["grid_col"] == 0
    assert start_record["planning_point_pixel"] == [10.0, 10.0]
    assert start_record["quality_features"]["degree"] == 1
    assert start_record["quality_features"]["obstacle_neighbor_count"] == 1
    assert start_record["quality_features"]["min_distance_m"] < 0.1
