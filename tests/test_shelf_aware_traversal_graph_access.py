from __future__ import annotations

import pytest

from algorithms.coverage_planning.planners.shelf_aware_guarded.graph_build.grid_builder import (
    CellCandidate,
    CoverageCellGrid,
    build_coverage_graph,
    build_legacy_node_matrix,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import Node
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_graph_access import (
    TraversalGraphAccess,
)


class FakeTraversalState:
    def __init__(self, visited_ids: set[str] | None = None) -> None:
        self.visited_ids = set() if visited_ids is None else set(visited_ids)

    def is_visited_node(self, node: Node) -> bool:
        raise AssertionError("生产遍历状态查询必须使用 cell id 口径")

    def is_visited_cell(self, cell_id: str) -> bool:
        return str(cell_id) in self.visited_ids


def _cell(cell_id: tuple[int, int], *, obstacle: bool = False) -> CellCandidate:
    row, col = cell_id
    return CellCandidate(
        planning_point_px=(col * 10, row * 10),
        grid_center_px=(col * 10, row * 10),
        obstacle=obstacle,
        grid_row=row,
        grid_col=col,
    )


def _graph_and_nodes(cell_rows):
    cell_grid = CoverageCellGrid.from_rows(cell_rows)
    return build_coverage_graph(cell_grid), build_legacy_node_matrix(cell_grid)


def test_traversal_graph_access_reads_static_graph_snapshot_not_mutated_node_obstacle() -> None:
    start = _cell((0, 0), obstacle=False)
    neighbor = _cell((0, 1), obstacle=False)
    obstacle = _cell((0, 2), obstacle=True)
    start.neighbors = [neighbor, obstacle]
    neighbor.neighbors = [start]
    obstacle.neighbors = [start]
    coverage_graph, nodes = _graph_and_nodes([[start, neighbor, obstacle]])

    nodes[0][1].obstacle = True
    nodes[0][2].obstacle = False
    graph_access = TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=nodes,
        coverage_graph=coverage_graph,
    )

    assert graph_access.accessible_neighbor_cell_ids(start.stable_id) == (neighbor.stable_id,)
    assert graph_access.accessible_cell_ids() == (start.stable_id, neighbor.stable_id)


def test_traversal_graph_access_exposes_accessible_neighbor_cell_ids_from_static_graph() -> None:
    start = _cell((0, 0), obstacle=False)
    first = _cell((0, 1), obstacle=False)
    obstacle = _cell((0, 2), obstacle=True)
    second = _cell((0, 3), obstacle=False)
    start.neighbors = [first, obstacle, second]
    coverage_graph, nodes = _graph_and_nodes([[start, first, obstacle, second]])
    graph_access = TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=nodes,
        coverage_graph=coverage_graph,
    )

    assert graph_access.accessible_neighbor_cell_ids(start.stable_id) == (
        first.stable_id,
        second.stable_id,
    )


def test_traversal_graph_access_reads_static_geometry_snapshot_not_mutated_node_point() -> None:
    start = _cell((0, 0), obstacle=False)
    coverage_graph, nodes = _graph_and_nodes([[start]])
    nodes[0][0].planning_point_px = (999, 999)
    graph_access = TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=nodes,
        coverage_graph=coverage_graph,
    )

    assert graph_access.planning_point_px_for_cell(start.stable_id) == (0, 0)


def test_traversal_graph_access_exposes_static_cell_by_id() -> None:
    start = _cell((0, 0), obstacle=False)
    neighbor = _cell((0, 1), obstacle=False)
    start.neighbors = [neighbor]
    coverage_graph, nodes = _graph_and_nodes([[start, neighbor]])
    start.neighbors = []
    graph_access = TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=nodes,
        coverage_graph=coverage_graph,
    )

    cell = graph_access.cell(start.stable_id)

    assert cell.cell_id == start.stable_id
    assert cell.accessible_neighbor_cell_ids == (neighbor.stable_id,)


def test_traversal_graph_access_unvisited_nodes_follow_row_major_static_accessible_order() -> None:
    first = _cell((0, 0), obstacle=False)
    second = _cell((0, 1), obstacle=False)
    blocked = _cell((1, 0), obstacle=True)
    third = _cell((1, 1), obstacle=False)
    coverage_graph, nodes = _graph_and_nodes([[first, second], [blocked, third]])
    graph_access = TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=nodes,
        coverage_graph=coverage_graph,
    )

    state = FakeTraversalState(visited_ids={second.stable_id})

    assert graph_access.unvisited_accessible_cell_ids(state) == [first.stable_id, third.stable_id]


def test_traversal_graph_access_accessible_order_comes_from_graph_snapshot_not_legacy_matrix_order() -> None:
    first = _cell((0, 0), obstacle=False)
    second = _cell((0, 1), obstacle=False)
    third = _cell((1, 0), obstacle=False)
    coverage_graph, nodes = _graph_and_nodes([[first, second], [third]])
    first_node, second_node, third_node = nodes[0][0], nodes[0][1], nodes[1][0]
    graph_access = TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=[[third_node], [second_node, first_node]],
        coverage_graph=coverage_graph,
    )

    assert graph_access.accessible_cell_ids() == (
        first.stable_id,
        second.stable_id,
        third.stable_id,
    )
    assert [graph_access.legacy_node_mirror(cell_id) for cell_id in graph_access.accessible_cell_ids()] == [
        first_node,
        second_node,
        third_node,
    ]


def test_traversal_graph_access_rejects_duplicate_legacy_cell_ids() -> None:
    first = _cell((0, 0), obstacle=False)
    second = _cell((0, 1), obstacle=False)
    second.grid_row = first.grid_row
    second.grid_col = first.grid_col

    with pytest.raises(AssertionError, match="Duplicate coverage cell id"):
        CoverageCellGrid.from_rows([[first, second]])


def test_traversal_graph_access_rejects_accessible_graph_cell_without_legacy_node() -> None:
    first = _cell((0, 0), obstacle=False)
    second = _cell((0, 1), obstacle=False)
    coverage_graph, nodes = _graph_and_nodes([[first, second]])

    with pytest.raises(AssertionError, match=f"Traversal graph cell missing legacy node: {second.stable_id}"):
        TraversalGraphAccess.bind_legacy_mirror(
            legacy_mirror_matrix=[[nodes[0][0]]],
            coverage_graph=coverage_graph,
        )


def test_traversal_graph_access_rejects_legacy_node_without_graph_cell() -> None:
    first = _cell((0, 0), obstacle=False)
    stale = Node(
        planning_point_px=(30, 30),
        grid_center_px=(30, 30),
        obstacle=False,
        grid_row=3,
        grid_col=3,
    )
    coverage_graph, nodes = _graph_and_nodes([[first]])

    with pytest.raises(AssertionError, match=f"Legacy node missing traversal graph cell: {stale.stable_id}"):
        TraversalGraphAccess.bind_legacy_mirror(
            legacy_mirror_matrix=[[nodes[0][0], stale]],
            coverage_graph=coverage_graph,
        )
