from __future__ import annotations

from typing import Any, Sequence

from algorithms.coverage_planning.planners.shelf_aware_guarded.graph_build.grid_builder import (
    CellCandidate,
    CoverageCellGrid,
    build_coverage_graph,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_graph_access import (
    TraversalGraphAccess,
)


def cell_grid_from_legacy_node_fixture(legacy_node_matrix: Sequence[Sequence[Any]]) -> CoverageCellGrid:
    """Copy a legacy-node test fixture into explicit static cell candidates."""

    cell_by_id: dict[str, CellCandidate] = {}
    cell_rows: list[list[CellCandidate]] = []
    for row in legacy_node_matrix:
        cell_row: list[CellCandidate] = []
        for node in row:
            cell = CellCandidate(
                planning_point_px=(int(node.planning_point_px[0]), int(node.planning_point_px[1])),
                grid_center_px=(int(node.grid_center_px[0]), int(node.grid_center_px[1])),
                obstacle=bool(node.obstacle),
                grid_row=int(node.grid_row),
                grid_col=int(node.grid_col),
                obstacle_ratio=None if node.obstacle_ratio is None else float(node.obstacle_ratio),
                obstacle_ratio_filtered=bool(node.obstacle_ratio_filtered),
            )
            cell_by_id[cell.stable_id] = cell
            cell_row.append(cell)
        cell_rows.append(cell_row)

    for node_row, cell_row in zip(legacy_node_matrix, cell_rows):
        for node, cell in zip(node_row, cell_row):
            cell.neighbors = [cell_by_id[str(neighbor.stable_id)] for neighbor in node.neighbors]

    return CoverageCellGrid.from_rows(cell_rows)


def build_coverage_graph_from_legacy_node_fixture(legacy_node_matrix: Sequence[Sequence[Any]]):
    """Build a graph from copied static cells, not directly from legacy nodes."""

    return build_coverage_graph(cell_grid_from_legacy_node_fixture(legacy_node_matrix))


def bind_graph_access_from_legacy_node_fixture(legacy_node_matrix: Sequence[Sequence[Any]]) -> TraversalGraphAccess:
    """Bind legacy node mirrors to a graph built from explicit static cell fixtures."""

    return TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=legacy_node_matrix,
        coverage_graph=build_coverage_graph_from_legacy_node_fixture(legacy_node_matrix),
    )
