import numpy as np

from algorithms.coverage_planning.planners.shelf_aware_guarded.graph_build.grid_builder import (
    build_cell_candidates,
    build_legacy_node_matrix,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.graph_build.node_filtering import (
    filter_nodes_by_obstacle_ratio,
    obstacle_ratio_around_point,
)


def _build_legacy_mirror_from_cell_candidates(*args, **kwargs):
    return build_legacy_node_matrix(build_cell_candidates(*args, **kwargs))


def test_obstacle_ratio_treats_outside_map_as_obstacle():
    room_map = np.ones((10, 10), dtype=np.uint8) * 255

    ratio = obstacle_ratio_around_point(room_map, (0, 0), 4)

    assert ratio == 0.75


def test_obstacle_ratio_filter_marks_dense_obstacle_window_as_obstacle():
    room_map = np.ones((30, 30), dtype=np.uint8) * 255
    room_map[11:17, 11:17] = 0
    nodes = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (30, 30),
        10,
        robot_half_width_px=4.0,
        row_endpoint_alignment_enable=False,
    )
    node = nodes[1][1]
    node.planning_point_px = (14, 14)

    filter_nodes_by_obstacle_ratio(room_map, nodes, robot_width_px=8.0, threshold=0.45)

    assert node.obstacle is True
    assert node.visited is False
    assert node.visit_count == 0
    assert node.obstacle_ratio_filtered is True
    assert node.obstacle_ratio > 0.45


def test_obstacle_ratio_filter_does_not_write_traversal_state() -> None:
    room_map = np.ones((30, 30), dtype=np.uint8) * 255
    room_map[11:17, 11:17] = 0
    nodes = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (30, 30),
        10,
        robot_half_width_px=4.0,
        row_endpoint_alignment_enable=False,
    )
    node = nodes[1][1]
    node.planning_point_px = (14, 14)
    node.visited = True
    node.visit_count = 7

    filter_nodes_by_obstacle_ratio(room_map, nodes, robot_width_px=8.0, threshold=0.45)

    assert node.obstacle is True
    assert node.obstacle_ratio_filtered is True
    assert node.visited is True
    assert node.visit_count == 7


def test_obstacle_ratio_filter_keeps_sparse_obstacle_window_accessible():
    room_map = np.ones((30, 30), dtype=np.uint8) * 255
    room_map[14, 14] = 0
    nodes = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (30, 30),
        10,
        robot_half_width_px=4.0,
        row_endpoint_alignment_enable=False,
    )
    node = nodes[1][1]
    node.planning_point_px = (14, 14)

    filter_nodes_by_obstacle_ratio(room_map, nodes, robot_width_px=8.0, threshold=0.45)

    assert node.obstacle is False
    assert node.obstacle_ratio_filtered is False
    assert node.obstacle_ratio < 0.45
