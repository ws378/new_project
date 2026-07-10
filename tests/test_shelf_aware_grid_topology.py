from algorithms.coverage_planning.planners.shelf_aware_guarded.graph_build.grid_topology import (
    connect_grid_neighbors,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import Node


def _node(row: int, col: int) -> Node:
    return Node(
        planning_point_px=(col, row),
        grid_center_px=(col, row),
        obstacle=False,
        grid_row=row,
        grid_col=col,
    )


def test_connect_grid_neighbors_uses_eight_neighbor_topology():
    nodes = [[_node(row, col) for col in range(3)] for row in range(3)]

    connect_grid_neighbors(nodes)

    center_neighbor_ids = {neighbor.stable_id for neighbor in nodes[1][1].neighbors}
    corner_neighbor_ids = {neighbor.stable_id for neighbor in nodes[0][0].neighbors}

    assert center_neighbor_ids == {
        "r0_c0",
        "r0_c1",
        "r0_c2",
        "r1_c0",
        "r1_c2",
        "r2_c0",
        "r2_c1",
        "r2_c2",
    }
    assert corner_neighbor_ids == {"r0_c1", "r1_c0", "r1_c1"}
