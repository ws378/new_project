from __future__ import annotations

import numpy as np
import pytest

from algorithms.coverage_planning.planners.shelf_aware_guarded.models import (
    Node,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.start_cell import (
    select_start_cell_stage,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_graph_access import (
    TraversalGraphAccess,
)
from tests.shelf_aware_graph_fixture import (
    bind_graph_access_from_legacy_node_fixture,
    build_coverage_graph_from_legacy_node_fixture,
)


def _graph_access(nodes):
    return bind_graph_access_from_legacy_node_fixture(nodes)


def test_select_start_cell_stage_rotates_start_and_records_selected_node():
    far_node = Node(
        planning_point_px=(30, 30),
        grid_center_px=(30, 30),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    near_node = Node(
        planning_point_px=(12, 23),
        grid_center_px=(12, 23),
        obstacle=False,
        grid_row=0,
        grid_col=1,
    )
    obstacle_node = Node(
        planning_point_px=(11, 22),
        grid_center_px=(11, 22),
        obstacle=True,
        grid_row=1,
        grid_col=0,
    )
    nodes = [[far_node, near_node], [obstacle_node]]
    rotation_matrix = np.array([[1.0, 0.0, 10.0], [0.0, 1.0, 20.0]], dtype=np.float32)

    graph_access = _graph_access(nodes)
    result = select_start_cell_stage(
        graph_access=graph_access,
        chosen_start_pixel=(2, 3),
        rotation_matrix=rotation_matrix,
    )

    assert result.chosen_start_pixel == (2, 3)
    assert result.rotated_start_pixel == (12, 23)
    assert result.start_cell_id == "r0_c1"
    assert not hasattr(result, "start_node")
    assert graph_access.legacy_node_mirror(result.start_cell_id) is near_node
    assert result.stage_record.stage_name == "start_cell_selection"
    assert result.stage_record.summary["requested_start_pixel"] == [2, 3]
    assert result.stage_record.summary["rotated_start_pixel"] == [12, 23]
    assert result.stage_record.summary["selected_cell_id"] == "r0_c1"
    assert result.stage_record.summary["distance_to_rotated_start_px"] == 0.0


def test_select_start_cell_stage_preserves_last_equal_distance_tie_behavior():
    first_equal = Node(
        planning_point_px=(9, 10),
        grid_center_px=(9, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    second_equal = Node(
        planning_point_px=(11, 10),
        grid_center_px=(11, 10),
        obstacle=False,
        grid_row=0,
        grid_col=1,
    )
    nodes = [[first_equal, second_equal]]
    identity = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)

    graph_access = _graph_access(nodes)
    result = select_start_cell_stage(
        graph_access=graph_access,
        chosen_start_pixel=(10, 10),
        rotation_matrix=identity,
    )

    assert result.start_cell_id == "r0_c1"
    assert graph_access.legacy_node_mirror(result.start_cell_id) is second_equal
    assert result.stage_record.summary["selected_cell_id"] == "r0_c1"


def test_select_start_cell_stage_keeps_first_accessible_when_no_better_node_exists():
    first_accessible = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    obstacle_node = Node(
        planning_point_px=(5, 5),
        grid_center_px=(5, 5),
        obstacle=True,
        grid_row=0,
        grid_col=1,
    )
    nodes = [[obstacle_node], [first_accessible]]
    identity = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)

    graph_access = _graph_access(nodes)
    result = select_start_cell_stage(
        graph_access=graph_access,
        chosen_start_pixel=(5, 5),
        rotation_matrix=identity,
    )

    assert result.start_cell_id == "r0_c0"
    assert graph_access.legacy_node_mirror(result.start_cell_id) is first_accessible
    assert result.stage_record.summary["selected_cell_id"] == "r0_c0"


def test_select_start_cell_stage_reads_accessibility_from_coverage_graph_snapshot():
    graph_accessible = Node(
        planning_point_px=(5, 5),
        grid_center_px=(5, 5),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    graph_blocked = Node(
        planning_point_px=(6, 5),
        grid_center_px=(6, 5),
        obstacle=True,
        grid_row=0,
        grid_col=1,
    )
    nodes = [[graph_accessible, graph_blocked]]
    coverage_graph = build_coverage_graph_from_legacy_node_fixture(nodes)
    graph_accessible.obstacle = True
    graph_blocked.obstacle = False
    identity = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)

    graph_access = TraversalGraphAccess.bind_legacy_mirror(legacy_mirror_matrix=nodes, coverage_graph=coverage_graph)
    result = select_start_cell_stage(
        graph_access=graph_access,
        chosen_start_pixel=(6, 5),
        rotation_matrix=identity,
    )

    assert result.start_cell_id == "r0_c0"
    assert graph_access.legacy_node_mirror(result.start_cell_id) is graph_accessible
    assert result.stage_record.summary["selected_cell_id"] == "r0_c0"


def test_select_start_cell_stage_reads_geometry_from_coverage_graph_snapshot():
    near_node = Node(
        planning_point_px=(12, 23),
        grid_center_px=(12, 23),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    far_node = Node(
        planning_point_px=(50, 50),
        grid_center_px=(50, 50),
        obstacle=False,
        grid_row=0,
        grid_col=1,
    )
    nodes = [[near_node, far_node]]
    coverage_graph = build_coverage_graph_from_legacy_node_fixture(nodes)
    near_node.planning_point_px = (200, 200)
    far_node.planning_point_px = (12, 23)
    identity = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)

    graph_access = TraversalGraphAccess.bind_legacy_mirror(legacy_mirror_matrix=nodes, coverage_graph=coverage_graph)
    result = select_start_cell_stage(
        graph_access=graph_access,
        chosen_start_pixel=(12, 23),
        rotation_matrix=identity,
    )

    assert result.start_cell_id == "r0_c0"
    assert graph_access.legacy_node_mirror(result.start_cell_id) is near_node
    assert result.stage_record.summary["selected_cell_id"] == "r0_c0"
    assert result.stage_record.summary["selected_planning_point_rotated_px"] == [12, 23]
    assert result.stage_record.summary["distance_to_rotated_start_px"] == 0.0


def test_select_start_cell_stage_raises_legacy_error_when_graph_has_no_accessible_node():
    blocked = Node(
        planning_point_px=(5, 5),
        grid_center_px=(5, 5),
        obstacle=True,
        grid_row=0,
        grid_col=0,
    )
    nodes = [[blocked]]
    identity = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)

    with pytest.raises(ValueError, match="房间内没有可通行节点"):
        select_start_cell_stage(
            graph_access=_graph_access(nodes),
            chosen_start_pixel=(5, 5),
            rotation_matrix=identity,
        )
