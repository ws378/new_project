from __future__ import annotations

import csv

import cv2
import numpy as np
from PIL import Image

from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.csv_debug import (
    save_debug_csv,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.metadata_payloads import (
    node_obstacle_ratio_filter_metadata,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.visualization import (
    visualize_node_obstacle_ratio_filter,
    visualize_nodes_and_path,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import Node, PlannerConfig
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_graph_access import (
    TraversalGraphAccess,
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


def _stale_graph_fixture():
    start = _node(0, 0)
    accessible_neighbor = _node(0, 1)
    obstacle_neighbor = _node(1, 0, obstacle=True)
    start.neighbors = [accessible_neighbor, obstacle_neighbor]
    accessible_neighbor.neighbors = [start]
    obstacle_neighbor.neighbors = [start]
    start.obstacle_ratio = 0.25
    start.obstacle_ratio_filtered = False
    nodes = [[start, accessible_neighbor], [obstacle_neighbor]]
    coverage_graph = build_coverage_graph_from_legacy_node_fixture(nodes)
    graph_access = TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=nodes,
        coverage_graph=coverage_graph,
    )

    start.obstacle = True
    start.planning_point_px = (90, 90)
    start.grid_center_px = (91, 91)
    start.neighbors = []
    start.obstacle_ratio = 0.99
    start.obstacle_ratio_filtered = True
    obstacle_neighbor.obstacle = False
    return nodes, graph_access, start, obstacle_neighbor


def test_debug_csv_reads_static_fields_from_graph_snapshot(tmp_path) -> None:
    nodes, graph_access, start, obstacle_neighbor = _stale_graph_fixture()
    csv_path = tmp_path / "energy_debug.csv"
    rotated_room_map = np.full((120, 120), 255, dtype=np.uint8)

    save_debug_csv(
        csv_path,
        graph_access,
        visited_points={(10, 10)},
        rotated_room_map=rotated_room_map,
        map_resolution=0.05,
        inverse_rotation=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32),
        min_room=(0, 0),
        max_room=(119, 119),
        map_origin=(0.0, 0.0),
        map_height=120,
    )

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    row_by_id = {row["node_id"]: row for row in rows}
    assert start.stable_id in row_by_id
    assert obstacle_neighbor.stable_id not in row_by_id
    assert row_by_id[start.stable_id]["planning_point_px_rotated_x"] == "10"
    assert row_by_id[start.stable_id]["planning_point_px_rotated_y"] == "10"
    assert row_by_id[start.stable_id]["grid_center_px_rotated_x"] == "10"
    assert row_by_id[start.stable_id]["generated_planning_point_px_rotated_x"] == "10"
    assert row_by_id[start.stable_id]["generated_planning_point_px_rotated_y"] == "10"
    assert row_by_id[start.stable_id]["generation_offset_from_grid_center_px_x"] == "0"
    assert row_by_id[start.stable_id]["generation_offset_from_grid_center_px_y"] == "0"
    assert row_by_id[start.stable_id]["generation_offset_distance_px"] == "0.000000"
    assert row_by_id[start.stable_id]["generation_mode"] == "unspecified"
    assert row_by_id[start.stable_id]["generation_status"] == "unspecified"
    assert row_by_id[start.stable_id]["endpoint_alignment_applied"] == "0"
    assert row_by_id[start.stable_id]["endpoint_alignment_offset_px_x"] == "0"
    assert row_by_id[start.stable_id]["endpoint_alignment_offset_px_y"] == "0"
    assert row_by_id[start.stable_id]["obstacle_ratio"] == "0.250000"
    assert row_by_id[start.stable_id]["obstacle_ratio_filtered"] == "0"
    assert row_by_id[start.stable_id]["status"] == "1"
    assert row_by_id[start.stable_id]["obstacle_neighbor_count"] == "1"
    assert row_by_id[start.stable_id]["non_obstacle_neighbor_count"] == "1"


def test_nodes_debug_image_reads_static_fields_from_graph_snapshot(tmp_path) -> None:
    nodes, graph_access, start, _ = _stale_graph_fixture()
    nodes_path = tmp_path / "nodes_debug.png"
    overlay_path = tmp_path / "path_overlay.png"

    visualize_nodes_and_path(
        rotated_room_map=np.zeros((120, 120), dtype=np.uint8),
        original_room_map=np.zeros((120, 120), dtype=np.uint8),
        graph_access=graph_access,
        pixel_poses=[],
        pixel_segments=[],
        jump_segments=[],
        output_nodes_path=nodes_path,
        output_overlay_path=overlay_path,
    )

    image = cv2.imread(str(nodes_path), cv2.IMREAD_COLOR)
    assert image is not None
    assert tuple(int(value) for value in image[10, 10]) == (0, 200, 0)
    assert tuple(int(value) for value in image[90, 90]) != (0, 200, 0)
    assert start.stable_id == "r0_c0"


def test_obstacle_ratio_metadata_reads_static_fields_from_graph_snapshot() -> None:
    nodes, graph_access, _, _ = _stale_graph_fixture()
    config = PlannerConfig()
    config.node_obstacle_ratio_filter_enable = True
    config.node_obstacle_ratio_threshold = 0.45

    payload = node_obstacle_ratio_filter_metadata(
        graph_access=graph_access,
        config=config,
    )

    assert payload == {
        "enable": True,
        "threshold": 0.45,
        "checked_node_count": 1,
        "filtered_node_count": 0,
    }


def test_obstacle_ratio_filter_image_reads_static_fields_from_graph_snapshot(tmp_path) -> None:
    nodes, graph_access, _, _ = _stale_graph_fixture()
    output_path = tmp_path / "node_obstacle_ratio_filter_debug.png"

    visualize_node_obstacle_ratio_filter(
        rotated_room_map=np.zeros((120, 120), dtype=np.uint8),
        graph_access=graph_access,
        output_path=output_path,
    )

    image = Image.open(output_path)
    assert image.width < 300
    assert image.height < 300
    assert image.getpixel((40, 40)) == (0, 90, 255)
