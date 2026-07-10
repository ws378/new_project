import numpy as np
import pytest
from algorithms.coverage_planning.contracts import CoveragePlannerConfig
from algorithms.coverage_planning.planners.shelf_aware_guarded.shelf_aware_planner import (
    ShelfAwareCoveragePlanner,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.graph_build.grid_builder import (
    CellCandidate,
    CoverageCellGrid,
    build_cell_candidates,
    build_coverage_graph,
    build_legacy_node_matrix,
    complete_cell_test,
    repair_regular_grid_cell,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.graph_build.coverage_graph import (
    build_coverage_graph_view_from_cell_rows,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import Node
from algorithms.coverage_planning.planners.shelf_aware_guarded.graph_build.node_alignment import (
    align_column_segments_to_free_endpoints,
    align_row_segments_to_free_endpoints,
)


def _accessible_row(nodes, row_index):
    return [node for node in nodes[row_index] if not node.obstacle]


def _neighbor_ids(nodes):
    return {
        node.stable_id: tuple(neighbor.stable_id for neighbor in node.neighbors)
        for row in nodes
        for node in row
    }


def _flatten_nodes(nodes):
    return [node for row in nodes for node in row]


def _flatten_cells(cell_grid):
    return list(cell_grid.iter_cells())


def _build_legacy_mirror_from_cell_candidates(*args, **kwargs):
    return build_legacy_node_matrix(build_cell_candidates(*args, **kwargs))


def _assert_graph_matches_cell_grid(cell_grid):
    graph = build_coverage_graph(cell_grid)
    flattened_cells = _flatten_cells(cell_grid)

    assert tuple(cell.cell_id for cell in graph.cells) == tuple(cell.stable_id for cell in flattened_cells)
    assert graph.summary() == {
        "row_count": len(cell_grid.rows),
        "cell_count": len(flattened_cells),
        "accessible_cell_count": sum(1 for cell in flattened_cells if not cell.obstacle),
        "edge_count": sum(len(cell.neighbors) for cell in flattened_cells),
        "accessible_edge_count": sum(
            len([neighbor for neighbor in cell.neighbors if not neighbor.obstacle])
            for cell in flattened_cells
            if not cell.obstacle
        ),
    }

    for source_cell in flattened_cells:
        graph_cell = graph.cell(source_cell.stable_id)
        expected_accessible_neighbor_ids = (
            tuple(neighbor.stable_id for neighbor in source_cell.neighbors if not neighbor.obstacle)
            if not source_cell.obstacle
            else tuple()
        )
        assert graph_cell.cell_id == source_cell.stable_id
        assert graph_cell.grid_row == source_cell.grid_row
        assert graph_cell.grid_col == source_cell.grid_col
        assert graph_cell.grid_center_px == source_cell.grid_center_px
        assert graph_cell.planning_point_px == source_cell.planning_point_px
        assert graph_cell.obstacle == source_cell.obstacle
        assert graph_cell.obstacle_ratio == source_cell.obstacle_ratio
        assert graph_cell.obstacle_ratio_filtered == source_cell.obstacle_ratio_filtered
        assert graph_cell.adjusted_from_grid_center_px == source_cell.adjusted_from_grid_center_px
        assert graph_cell.generated_planning_point_px == source_cell.generated_planning_point_px
        assert graph_cell.generation_offset_from_grid_center_px == source_cell.generation_offset_from_grid_center_px
        assert graph_cell.generation_offset_distance_px == pytest.approx(source_cell.generation_offset_distance_px)
        assert graph_cell.generation_mode == source_cell.generation_mode
        assert graph_cell.generation_status == source_cell.generation_status
        assert graph_cell.endpoint_alignment_applied == source_cell.endpoint_alignment_applied
        assert graph_cell.endpoint_alignment_offset_px == source_cell.endpoint_alignment_offset_px
        assert graph_cell.neighbor_cell_ids == tuple(neighbor.stable_id for neighbor in source_cell.neighbors)
        assert graph_cell.accessible_neighbor_cell_ids == expected_accessible_neighbor_ids
    return graph


def _assert_legacy_nodes_match_cell_grid(nodes, cell_grid):
    flattened_nodes = _flatten_nodes(nodes)
    flattened_cells = _flatten_cells(cell_grid)

    assert tuple(node.stable_id for node in flattened_nodes) == tuple(cell.stable_id for cell in flattened_cells)
    for node, cell in zip(flattened_nodes, flattened_cells):
        assert node.grid_row == cell.grid_row
        assert node.grid_col == cell.grid_col
        assert node.grid_center_px == cell.grid_center_px
        assert node.planning_point_px == cell.planning_point_px
        assert node.obstacle == cell.obstacle
        assert node.obstacle_ratio == cell.obstacle_ratio
        assert node.obstacle_ratio_filtered == cell.obstacle_ratio_filtered
        assert tuple(neighbor.stable_id for neighbor in node.neighbors) == tuple(
            neighbor.stable_id for neighbor in cell.neighbors
        )


def test_row_endpoint_alignment_keeps_grid_topology_and_obstacle_pattern():
    room_map = np.zeros((30, 100), dtype=np.uint8)
    room_map[10:20, 13:88] = 255

    baseline = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (100, 30),
        10,
        robot_half_width_px=5.0,
        row_endpoint_alignment_enable=False,
    )
    aligned = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (100, 30),
        10,
        robot_half_width_px=5.0,
        row_endpoint_alignment_enable=True,
    )

    assert [[node.obstacle for node in row] for row in aligned] == [
        [node.obstacle for node in row] for row in baseline
    ]
    assert [[node.stable_id for node in row] for row in aligned] == [
        [node.stable_id for node in row] for row in baseline
    ]
    assert _neighbor_ids(aligned) == _neighbor_ids(baseline)


def test_row_endpoint_alignment_evenly_spreads_continuous_accessible_row_segment():
    room_map = np.zeros((30, 100), dtype=np.uint8)
    room_map[10:20, 13:88] = 255

    nodes = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (100, 30),
        10,
        robot_half_width_px=5.0,
        row_endpoint_alignment_enable=True,
    )

    row_nodes = _accessible_row(nodes, 1)
    xs = [node.planning_point_px[0] for node in row_nodes]
    gaps = np.diff(xs)

    assert xs[0] == 17
    assert xs[-1] == 83
    assert max(gaps) - min(gaps) <= 1
    assert len({node.planning_point_px for node in row_nodes}) == len(row_nodes)


def test_row_endpoint_alignment_evenly_spreads_continuous_accessible_column_segment():
    room_map = np.zeros((100, 30), dtype=np.uint8)
    room_map[13:88, 10:20] = 255

    nodes = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (30, 100),
        10,
        robot_half_width_px=5.0,
        row_endpoint_alignment_enable=True,
    )

    col_nodes = [row[1] for row in nodes if not row[1].obstacle]
    ys = [node.planning_point_px[1] for node in col_nodes]
    gaps = np.diff(ys)

    assert ys[0] == 17
    assert ys[-1] == 83
    assert max(gaps) - min(gaps) <= 1
    assert len({node.planning_point_px for node in col_nodes}) == len(col_nodes)


def test_row_endpoint_alignment_can_be_disabled():
    room_map = np.zeros((30, 100), dtype=np.uint8)
    room_map[10:20, 13:88] = 255

    nodes = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (100, 30),
        10,
        robot_half_width_px=5.0,
        row_endpoint_alignment_enable=False,
    )

    xs = [node.planning_point_px[0] for node in _accessible_row(nodes, 1)]
    assert xs == [15, 25, 35, 45, 55, 65, 75, 85]


def test_default_node_generation_adjusts_blocked_grid_center_inside_cell():
    room_map = np.zeros((30, 30), dtype=np.uint8)
    room_map[10:20, 10:20] = 255
    room_map[15, 15] = 0

    nodes = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (30, 30),
        10,
        robot_half_width_px=4.0,
        row_endpoint_alignment_enable=False,
    )

    node = nodes[1][1]
    assert node.grid_center_px == (15, 15)
    assert node.obstacle is False
    assert node.planning_point_px != node.grid_center_px
    assert room_map[node.planning_point_px[1], node.planning_point_px[0]] == 255


def test_turn_cost_regular_grid_node_generation_keeps_blocked_center_as_obstacle():
    room_map = np.zeros((30, 30), dtype=np.uint8)
    room_map[10:20, 10:20] = 255
    room_map[15, 15] = 0

    nodes = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (30, 30),
        10,
        robot_half_width_px=4.0,
        node_generation_mode="turn_cost_regular_grid",
        row_endpoint_alignment_enable=False,
    )

    node = nodes[1][1]
    assert node.grid_center_px == (15, 15)
    assert node.planning_point_px == node.grid_center_px
    assert node.obstacle is True
    assert node.visited is False
    assert node.visit_count == 0


def test_build_nodes_generation_modes_keep_legacy_node_and_graph_signatures_aligned():
    room_map = np.zeros((30, 30), dtype=np.uint8)
    room_map[10:20, 10:20] = 255
    room_map[15, 15] = 0

    cases = {
        "shelf_cell_adjusted": {
            "obstacle": False,
            "planning_point_px": (10, 10),
            "generation_status": "cell_adjusted",
        },
        "turn_cost_regular_grid": {
            "obstacle": True,
            "planning_point_px": (15, 15),
            "generation_status": "regular_grid_blocked",
        },
        "turn_cost_repaired_grid": {
            "obstacle": False,
            "planning_point_px": (15, 13),
            "generation_status": "bounded_repaired",
        },
    }

    for mode, expected in cases.items():
        cell_grid = build_cell_candidates(
            room_map,
            (0, 0),
            (30, 30),
            10,
            robot_half_width_px=4.0,
            node_generation_mode=mode,
            row_endpoint_alignment_enable=False,
            node_obstacle_ratio_filter_enable=False,
        )
        graph = _assert_graph_matches_cell_grid(cell_grid)
        nodes = build_legacy_node_matrix(cell_grid)
        _assert_legacy_nodes_match_cell_grid(nodes, cell_grid)

        center_node = nodes[1][1]
        center_cell = graph.cell("r1_c1")
        assert center_node.stable_id == "r1_c1"
        assert center_node.grid_center_px == (15, 15)
        assert center_node.obstacle is expected["obstacle"]
        assert center_node.planning_point_px == expected["planning_point_px"]
        assert center_cell.obstacle is center_node.obstacle
        assert center_cell.planning_point_px == center_node.planning_point_px
        assert center_cell.generation_mode == mode
        assert center_cell.generation_status == expected["generation_status"]
        assert center_cell.generated_planning_point_px == expected["planning_point_px"]
        assert center_cell.generation_offset_from_grid_center_px == (
            center_cell.generated_planning_point_px[0] - center_cell.grid_center_px[0],
            center_cell.generated_planning_point_px[1] - center_cell.grid_center_px[1],
        )
        assert center_cell.endpoint_alignment_applied is False
        assert center_cell.endpoint_alignment_offset_px == (0, 0)
        assert center_cell.generation_offset_distance_px == pytest.approx(
            float(np.hypot(
                center_cell.generated_planning_point_px[0] - center_cell.grid_center_px[0],
                center_cell.generated_planning_point_px[1] - center_cell.grid_center_px[1],
            ))
        )


def test_build_cell_candidates_generation_provenance_status_variants():
    free_map = np.ones((30, 30), dtype=np.uint8) * 255
    blocked_map = np.zeros((30, 30), dtype=np.uint8)
    far_repair_map = np.zeros((30, 30), dtype=np.uint8)
    far_repair_map[10, 10] = 255

    free_cell = build_coverage_graph(build_cell_candidates(
        free_map,
        (0, 0),
        (30, 30),
        10,
        robot_half_width_px=4.0,
        node_generation_mode="turn_cost_repaired_grid",
        row_endpoint_alignment_enable=False,
    )).cell("r1_c1")
    assert free_cell.generation_status == "center_free"
    assert free_cell.generated_planning_point_px == free_cell.grid_center_px
    assert free_cell.generation_offset_from_grid_center_px == (0, 0)

    shelf_failed = build_coverage_graph(build_cell_candidates(
        blocked_map,
        (0, 0),
        (30, 30),
        10,
        robot_half_width_px=4.0,
        node_generation_mode="shelf_cell_adjusted",
        row_endpoint_alignment_enable=False,
    )).cell("r1_c1")
    assert shelf_failed.obstacle is True
    assert shelf_failed.generation_status == "cell_adjust_failed"
    assert shelf_failed.generated_planning_point_px == shelf_failed.grid_center_px

    repair_failed = build_coverage_graph(build_cell_candidates(
        far_repair_map,
        (0, 0),
        (30, 30),
        10,
        robot_half_width_px=4.0,
        node_generation_mode="turn_cost_repaired_grid",
        repaired_grid_max_offset_factor=0.35,
        row_endpoint_alignment_enable=False,
    )).cell("r1_c1")
    assert repair_failed.obstacle is True
    assert repair_failed.generation_status == "repair_failed"
    assert repair_failed.generated_planning_point_px == repair_failed.grid_center_px


def test_cell_candidates_are_static_source_for_graph_and_legacy_node_mirror():
    room_map = np.zeros((30, 30), dtype=np.uint8)
    room_map[10:20, 10:20] = 255
    room_map[15, 15] = 0

    cell_grid = build_cell_candidates(
        room_map,
        (0, 0),
        (30, 30),
        10,
        robot_half_width_px=4.0,
        node_generation_mode="turn_cost_repaired_grid",
        row_endpoint_alignment_enable=False,
    )
    graph = build_coverage_graph(cell_grid)
    legacy_nodes = build_legacy_node_matrix(cell_grid)
    center_cell_before_legacy_mutation = graph.cell("r1_c1")

    assert isinstance(cell_grid, CoverageCellGrid)
    assert not hasattr(cell_grid.rows[1][1], "visited")
    assert not hasattr(cell_grid.rows[1][1], "visit_count")
    _assert_graph_matches_cell_grid(cell_grid)
    _assert_legacy_nodes_match_cell_grid(legacy_nodes, cell_grid)
    assert tuple(cell.cell_id for cell in graph.cells) == tuple(
        node.stable_id for node in _flatten_nodes(legacy_nodes)
    )
    assert graph.cell("r1_c1").planning_point_px == legacy_nodes[1][1].planning_point_px
    assert graph.cell("r1_c1").neighbor_cell_ids == tuple(
        neighbor.stable_id for neighbor in legacy_nodes[1][1].neighbors
    )

    legacy_nodes[1][1].planning_point_px = (999, 999)
    legacy_nodes[1][1].obstacle = True
    legacy_nodes[1][1].neighbors = []

    assert center_cell_before_legacy_mutation.planning_point_px == (15, 13)
    assert center_cell_before_legacy_mutation.obstacle is False
    assert center_cell_before_legacy_mutation.neighbor_cell_ids == tuple(
        neighbor.stable_id for neighbor in cell_grid.rows[1][1].neighbors
    )


def test_build_coverage_graph_rejects_non_cell_grid_static_source():
    node = Node(
        planning_point_px=(10, 20),
        grid_center_px=(10, 20),
        obstacle=False,
        grid_row=1,
        grid_col=2,
    )

    with pytest.raises(AssertionError, match="build_coverage_graph expects CoverageCellGrid static source"):
        build_coverage_graph([[node]])


def test_coverage_graph_view_rejects_legacy_node_rows_directly():
    node = Node(
        planning_point_px=(10, 20),
        grid_center_px=(10, 20),
        obstacle=False,
        grid_row=1,
        grid_col=2,
    )

    with pytest.raises(AssertionError, match="static cell candidates, not legacy Node mirrors"):
        build_coverage_graph_view_from_cell_rows([[node]])


def test_coverage_cell_grid_rejects_duplicate_static_cell_ids():
    first = CellCandidate(
        planning_point_px=(5, 5),
        grid_center_px=(5, 5),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    duplicate = CellCandidate(
        planning_point_px=(15, 5),
        grid_center_px=(15, 5),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )

    with pytest.raises(AssertionError, match=f"Duplicate coverage cell id: {first.stable_id}"):
        CoverageCellGrid.from_rows([[first, duplicate]])


def test_build_nodes_obstacle_ratio_filter_is_reflected_in_coverage_graph_snapshot():
    room_map = np.ones((30, 30), dtype=np.uint8) * 255
    room_map[12:20, 12:15] = 0

    cell_grid = build_cell_candidates(
        room_map,
        (0, 0),
        (30, 30),
        10,
        robot_half_width_px=4.0,
        row_endpoint_alignment_enable=False,
        node_obstacle_ratio_filter_enable=True,
        node_obstacle_ratio_threshold=0.3,
    )
    graph = _assert_graph_matches_cell_grid(cell_grid)
    nodes = build_legacy_node_matrix(cell_grid)
    _assert_legacy_nodes_match_cell_grid(nodes, cell_grid)

    filtered_node = nodes[1][1]
    filtered_cell = graph.cell("r1_c1")
    assert filtered_node.grid_center_px == (15, 15)
    assert filtered_node.planning_point_px == (15, 15)
    assert filtered_node.obstacle is True
    assert filtered_node.obstacle_ratio_filtered is True
    assert filtered_node.obstacle_ratio is not None
    assert filtered_node.obstacle_ratio == pytest.approx(0.328125)
    assert filtered_cell.obstacle is True
    assert filtered_cell.obstacle_ratio == filtered_node.obstacle_ratio
    assert filtered_cell.obstacle_ratio_filtered is True
    assert filtered_cell.accessible_neighbor_cell_ids == tuple()


def test_build_nodes_endpoint_alignment_final_points_are_graph_truth():
    room_map = np.zeros((30, 100), dtype=np.uint8)
    room_map[10:20, 13:88] = 255

    cell_grid = build_cell_candidates(
        room_map,
        (0, 0),
        (100, 30),
        10,
        robot_half_width_px=5.0,
        row_endpoint_alignment_enable=True,
    )
    graph = _assert_graph_matches_cell_grid(cell_grid)
    nodes = build_legacy_node_matrix(cell_grid)
    _assert_legacy_nodes_match_cell_grid(nodes, cell_grid)

    row_nodes = _accessible_row(nodes, 1)
    row_cell_points = [graph.cell(node.stable_id).planning_point_px for node in row_nodes]
    assert [point[0] for point in row_cell_points] == [17, 26, 36, 45, 55, 64, 74, 83]
    assert [point[1] for point in row_cell_points] == [node.planning_point_px[1] for node in row_nodes]
    assert any(graph.cell(node.stable_id).endpoint_alignment_applied for node in row_nodes)
    assert any(graph.cell(node.stable_id).endpoint_alignment_offset_px != (0, 0) for node in row_nodes)
    assert all(graph.cell(node.stable_id).generation_mode == "shelf_cell_adjusted" for node in row_nodes)
    first_cell = graph.cell(row_nodes[0].stable_id)
    assert first_cell.generated_planning_point_px == (15, 15)
    assert first_cell.planning_point_px == (17, 14)
    assert first_cell.generation_status == "center_free"
    assert first_cell.generation_offset_from_grid_center_px == (0, 0)
    assert first_cell.endpoint_alignment_offset_px == (2, -1)


def test_build_nodes_eight_neighbor_topology_keeps_obstacle_neighbors_but_filters_accessible_edges():
    room_map = np.zeros((30, 30), dtype=np.uint8)
    room_map[10:20, 10:20] = 255

    cell_grid = build_cell_candidates(
        room_map,
        (0, 0),
        (30, 30),
        10,
        robot_half_width_px=4.0,
        node_generation_mode="turn_cost_regular_grid",
        row_endpoint_alignment_enable=False,
    )
    graph = _assert_graph_matches_cell_grid(cell_grid)
    nodes = build_legacy_node_matrix(cell_grid)
    _assert_legacy_nodes_match_cell_grid(nodes, cell_grid)

    center_node = nodes[1][1]
    center_cell = graph.cell("r1_c1")
    assert center_node.obstacle is False
    assert len(center_node.neighbors) == 8
    assert center_cell.neighbor_cell_ids == tuple(neighbor.stable_id for neighbor in center_node.neighbors)
    assert center_cell.accessible_neighbor_cell_ids == tuple()

    obstacle_node = nodes[0][0]
    obstacle_cell = graph.cell("r0_c0")
    assert obstacle_node.obstacle is True
    assert "r1_c1" in obstacle_cell.neighbor_cell_ids
    assert obstacle_cell.accessible_neighbor_cell_ids == tuple()


def test_coverage_graph_view_separates_static_cells_from_traversal_state():
    room_map = np.zeros((30, 30), dtype=np.uint8)
    room_map[10:20, 10:20] = 255

    cell_grid = build_cell_candidates(
        room_map,
        (0, 0),
        (30, 30),
        10,
        robot_half_width_px=4.0,
        row_endpoint_alignment_enable=False,
    )
    nodes = build_legacy_node_matrix(cell_grid)
    graph = _assert_graph_matches_cell_grid(cell_grid)

    assert graph.summary()["cell_count"] == 9
    assert graph.summary()["accessible_cell_count"] == 1
    assert graph.summary()["edge_count"] == sum(len(node.neighbors) for row in nodes for node in row)
    assert graph.summary()["accessible_edge_count"] == 0
    assert graph.cell("r1_c1").planning_point_px == nodes[1][1].planning_point_px
    assert graph.cell("r1_c1").neighbor_cell_ids == tuple(neighbor.stable_id for neighbor in nodes[1][1].neighbors)
    assert graph.cell("r1_c1").accessible_neighbor_cell_ids == tuple()

    nodes[1][1].visited = True
    nodes[1][1].visit_count = 7

    assert graph.cell("r1_c1").obstacle is False
    assert not hasattr(graph.cell("r1_c1"), "visited")
    assert not hasattr(graph.cell("r1_c1"), "visit_count")


def test_coverage_graph_view_freezes_static_fields_after_source_cell_mutation():
    start = CellCandidate(
        planning_point_px=(10, 20),
        grid_center_px=(12, 22),
        obstacle=False,
        grid_row=1,
        grid_col=2,
    )
    neighbor = CellCandidate(
        planning_point_px=(30, 40),
        grid_center_px=(30, 40),
        obstacle=False,
        grid_row=1,
        grid_col=3,
    )
    obstacle = CellCandidate(
        planning_point_px=(50, 60),
        grid_center_px=(50, 60),
        obstacle=True,
        grid_row=1,
        grid_col=4,
    )
    start.neighbors = [neighbor, obstacle]
    neighbor.neighbors = [start]
    obstacle.neighbors = [start]
    start.obstacle_ratio = 0.25
    start.obstacle_ratio_filtered = False

    graph = build_coverage_graph_view_from_cell_rows([[start, neighbor, obstacle]])
    start_cell = graph.cell(start.stable_id)

    start.planning_point_px = (900, 901)
    start.grid_center_px = (902, 903)
    start.obstacle = True
    start.neighbors = []
    start.obstacle_ratio = 0.99
    start.obstacle_ratio_filtered = True
    neighbor.obstacle = True
    obstacle.obstacle = False

    assert start_cell.planning_point_px == (10, 20)
    assert start_cell.grid_center_px == (12, 22)
    assert start_cell.obstacle is False
    assert start_cell.obstacle_ratio == 0.25
    assert start_cell.obstacle_ratio_filtered is False
    assert start_cell.adjusted_from_grid_center_px is True
    assert start_cell.generated_planning_point_px == (10, 20)
    assert start_cell.generation_offset_from_grid_center_px == (-2, -2)
    assert start_cell.generation_offset_distance_px == pytest.approx(float(np.hypot(2, 2)))
    assert start_cell.endpoint_alignment_applied is False
    assert start_cell.endpoint_alignment_offset_px == (0, 0)
    assert start_cell.neighbor_cell_ids == (neighbor.stable_id, obstacle.stable_id)
    assert start_cell.accessible_neighbor_cell_ids == (neighbor.stable_id,)
    assert graph.accessible_cell_ids() == (start.stable_id, neighbor.stable_id)


def test_coverage_graph_view_rejects_duplicate_cell_ids():
    first = CellCandidate(
        planning_point_px=(10, 20),
        grid_center_px=(10, 20),
        obstacle=False,
        grid_row=1,
        grid_col=2,
    )
    duplicate = CellCandidate(
        planning_point_px=(30, 40),
        grid_center_px=(30, 40),
        obstacle=False,
        grid_row=1,
        grid_col=2,
    )

    with pytest.raises(AssertionError, match="Duplicate coverage cell id: r1_c2"):
        build_coverage_graph_view_from_cell_rows([[first, duplicate]])


def test_coverage_graph_view_separates_all_neighbors_from_accessible_neighbors():
    obstacle = CellCandidate(
        planning_point_px=(0, 0),
        grid_center_px=(0, 0),
        obstacle=True,
        grid_row=0,
        grid_col=0,
    )
    center = CellCandidate(
        planning_point_px=(1, 0),
        grid_center_px=(1, 0),
        obstacle=False,
        grid_row=0,
        grid_col=1,
    )
    accessible = CellCandidate(
        planning_point_px=(2, 0),
        grid_center_px=(2, 0),
        obstacle=False,
        grid_row=0,
        grid_col=2,
    )
    obstacle.neighbors = [center]
    center.neighbors = [obstacle, accessible]
    accessible.neighbors = [center]

    graph = build_coverage_graph_view_from_cell_rows([[obstacle, center, accessible]])

    assert graph.cell(center.stable_id).neighbor_cell_ids == (
        obstacle.stable_id,
        accessible.stable_id,
    )
    assert graph.cell(obstacle.stable_id).accessible_neighbor_cell_ids == tuple()
    assert graph.cell(center.stable_id).accessible_neighbor_cell_ids == (accessible.stable_id,)
    assert graph.summary()["edge_count"] == 4
    assert graph.summary()["accessible_edge_count"] == 2
    assert graph.summary()["accessible_edge_count"] <= graph.summary()["edge_count"]


def test_turn_cost_repaired_grid_repairs_blocked_center_with_nearby_free_point():
    room_map = np.zeros((30, 30), dtype=np.uint8)
    room_map[10:20, 10:20] = 255
    room_map[15, 15] = 0

    nodes = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (30, 30),
        10,
        robot_half_width_px=4.0,
        node_generation_mode="turn_cost_repaired_grid",
        row_endpoint_alignment_enable=False,
    )

    node = nodes[1][1]
    assert node.grid_center_px == (15, 15)
    assert node.obstacle is False
    assert node.planning_point_px != node.grid_center_px
    assert room_map[node.planning_point_px[1], node.planning_point_px[0]] == 255
    assert abs(node.planning_point_px[0] - 15) <= 2
    assert abs(node.planning_point_px[1] - 15) <= 2


def test_repair_regular_grid_cell_prefers_center_near_point_over_farthest_obstacle_point():
    room_map = np.zeros((30, 30), dtype=np.uint8)
    room_map[10:20, 10:20] = 255
    room_map[15, 15] = 0
    room_map[10:14, 10:14] = 255

    ok, repaired = repair_regular_grid_cell(room_map, (15, 15), 10, robot_half_width_px=4.0, max_offset_factor=0.35)
    default_ok, default_point = complete_cell_test(room_map, (15, 15), 10)

    assert ok is True
    assert default_ok is True
    assert room_map[repaired[1], repaired[0]] == 255
    assert (repaired[0] - 15) ** 2 + (repaired[1] - 15) ** 2 <= (
        (default_point[0] - 15) ** 2 + (default_point[1] - 15) ** 2
    )


def test_shelf_aware_public_config_passes_node_generation_mode_to_planner_config():
    planner = ShelfAwareCoveragePlanner(
        CoveragePlannerConfig(
            planner_mode="shelf_aware",
            shelf_node_generation_mode="turn_cost_regular_grid",
        )
    )

    planner_config = planner._build_planner_config(
        np.ones((20, 20), dtype=np.uint8) * 255,
        starting_position=(10, 10),
    )

    assert planner_config.node_generation_mode == "turn_cost_regular_grid"
    assert planner_config.planner_params_dict()["node_generation_mode"] == "turn_cost_regular_grid"


def test_row_endpoint_alignment_does_not_collapse_segment_when_local_free_projection_is_narrow():
    room_map = np.zeros((30, 100), dtype=np.uint8)
    room_map[10:20, 20:90] = 255
    room_map[10:20, 40:90] = 0
    room_map[15:20, 40:90] = 255

    nodes = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (100, 30),
        10,
        robot_half_width_px=5.0,
        row_endpoint_alignment_enable=True,
    )

    xs = [node.planning_point_px[0] for node in _accessible_row(nodes, 1)]
    assert xs[0] == 24
    assert xs[-1] == 81
    assert xs[-1] - xs[0] >= 55


def test_row_endpoint_alignment_only_changes_x_axis():
    room_map = np.zeros((40, 100), dtype=np.uint8)
    room_map[15:25, 12:88] = 255
    room_map[20, 12:45] = 0

    nodes = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (100, 40),
        10,
        robot_half_width_px=5.0,
        row_endpoint_alignment_enable=False,
    )
    before_grid_y = [node.grid_center_px[1] for node in _accessible_row(nodes, 2)]
    before_planning_y = [node.planning_point_px[1] for node in _accessible_row(nodes, 2)]

    align_row_segments_to_free_endpoints(room_map, nodes, 10, 5.0)

    assert [node.grid_center_px[1] for node in _accessible_row(nodes, 2)] == before_grid_y
    assert [node.planning_point_px[1] for node in _accessible_row(nodes, 2)] == before_planning_y


def test_column_endpoint_alignment_only_changes_y_axis():
    room_map = np.zeros((100, 40), dtype=np.uint8)
    room_map[12:88, 15:25] = 255
    room_map[12:45, 20] = 0

    nodes = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (40, 100),
        10,
        robot_half_width_px=5.0,
        row_endpoint_alignment_enable=False,
    )
    align_row_segments_to_free_endpoints(room_map, nodes, 10, 5.0)
    col_nodes = [row[2] for row in nodes if not row[2].obstacle]
    before_grid_x = [node.grid_center_px[0] for node in col_nodes]
    before_planning_x = [node.planning_point_px[0] for node in col_nodes]

    align_column_segments_to_free_endpoints(room_map, nodes, 10, 5.0)

    after_col_nodes = [row[2] for row in nodes if not row[2].obstacle]
    assert [node.grid_center_px[0] for node in after_col_nodes] == before_grid_x
    assert [node.planning_point_px[0] for node in after_col_nodes] == before_planning_x


def test_single_point_segments_align_to_obstacle_midpoint():
    room_map = np.zeros((30, 50), dtype=np.uint8)
    room_map[10:20, 20:30] = 255

    nodes = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (50, 30),
        10,
        robot_half_width_px=5.0,
        row_endpoint_alignment_enable=True,
    )

    row_nodes = _accessible_row(nodes, 1)
    assert len(row_nodes) == 1
    assert row_nodes[0].planning_point_px == (24, 14)
