from __future__ import annotations

import numpy as np

from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.coverage_graph import (
    build_coverage_graph_stage,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.graph_build.grid_builder import (
    CellCandidate,
    CoverageCellGrid,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import (
    Node,
    PlannerConfig,
)


class FakeCoverageGraph:
    cell_count = 1
    accessible_cell_count = 1
    accessible_edge_count = 0
    cells_by_id = {"r0_c0": object()}

    def accessible_cell_ids(self):
        return ("r0_c0",)

    def summary(self):
        return {
            "row_count": 1,
            "cell_count": 1,
            "accessible_cell_count": 1,
            "edge_count": 0,
            "accessible_edge_count": 0,
        }

    def cell(self, _cell_id):
        class FakeCell:
            obstacle = False

        return FakeCell()


def test_coverage_graph_stage_builds_legacy_nodes_and_trace_summary():
    room_map = np.zeros((30, 30), dtype=np.uint8)
    room_map[5:25, 5:25] = 255
    config = PlannerConfig()
    config.row_endpoint_alignment_enable = False
    config.node_obstacle_ratio_filter_enable = False

    result = build_coverage_graph_stage(
        rotated_room_map=room_map,
        coverage_width_px=10,
        robot_half_width_px=4.0,
        config=config,
    )

    assert result.min_room == (5, 5)
    assert result.max_room == (24, 24)
    assert result.coverage_graph.accessible_cell_count > 0
    static_cell_ids = tuple(cell.stable_id for cell in result.static_cell_grid.iter_cells())
    graph_cell_ids = tuple(cell.cell_id for cell in result.coverage_graph.cells)
    legacy_cell_ids = tuple(
        result.graph_access.legacy_node_mirror(cell.cell_id).stable_id
        for cell in result.coverage_graph.cells
    )
    assert graph_cell_ids == static_cell_ids
    assert legacy_cell_ids == static_cell_ids
    for cell in result.coverage_graph.cells:
        mirror = result.graph_access.legacy_node_mirror(cell.cell_id)
        assert mirror.planning_point_px == cell.planning_point_px
        assert mirror.grid_center_px == cell.grid_center_px
        assert mirror.obstacle == cell.obstacle
        assert tuple(str(neighbor.stable_id) for neighbor in mirror.neighbors) == cell.neighbor_cell_ids
    assert result.graph_access.coverage_graph is result.coverage_graph
    assert result.graph_access.accessible_cell_ids() == result.coverage_graph.accessible_cell_ids()
    assert len(result.graph_access.accessible_cell_ids()) == result.coverage_graph.accessible_cell_count
    assert result.stage_record.stage_name == "coverage_graph_build"
    assert result.stage_record.summary["node_generation_mode"] == config.node_generation_mode
    assert result.stage_record.summary["node_generation_profile"]["profile_id"] == "shelf_cell_adjusted_v1"
    assert result.stage_record.summary["node_generation_profile"]["status"] == "formal_baseline"
    assert result.stage_record.summary["node_generation_profile"]["applies_to_modes"] == ["shelf_aware"]
    assert result.stage_record.summary["coverage_width_px"] == 10
    assert result.stage_record.summary["accessible_cell_count"] == result.coverage_graph.accessible_cell_count
    assert result.stage_record.summary["accessible_edge_count"] == result.coverage_graph.accessible_edge_count
    assert result.stage_record.summary["rotated_min_room_px"] == [5, 5]
    assert result.stage_record.summary["rotated_max_room_px"] == [24, 24]


def test_coverage_graph_stage_passes_node_generation_settings(monkeypatch):
    room_map = np.zeros((20, 20), dtype=np.uint8)
    room_map[2:18, 3:17] = 255
    config = PlannerConfig()
    config.node_generation_mode = "turn_cost_repaired_grid"
    config.repaired_grid_max_offset_factor = 0.28
    config.row_endpoint_alignment_enable = True
    config.node_obstacle_ratio_filter_enable = True
    config.node_obstacle_ratio_threshold = 0.45
    fake_cell = CellCandidate(
        planning_point_px=(4, 4),
        grid_center_px=(4, 4),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    fake_node = Node(
        planning_point_px=(4, 4),
        grid_center_px=(4, 4),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    fake_cell_grid = CoverageCellGrid.from_rows([[fake_cell]])
    fake_nodes = [[fake_node]]
    captured = {}

    def fake_build_cell_candidates(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return fake_cell_grid

    def fake_build_legacy_node_matrix(cell_grid):
        captured["legacy_source"] = cell_grid
        return fake_nodes

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.coverage_graph.build_cell_candidates",
        fake_build_cell_candidates,
    )
    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.coverage_graph.build_coverage_graph",
        lambda cell_grid: FakeCoverageGraph(),
    )
    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.coverage_graph.build_legacy_node_matrix",
        fake_build_legacy_node_matrix,
    )

    result = build_coverage_graph_stage(
        rotated_room_map=room_map,
        coverage_width_px=8,
        robot_half_width_px=3.5,
        config=config,
    )

    assert captured["args"] == (room_map, (3, 2), (16, 17), 8)
    assert captured["kwargs"] == {
        "robot_half_width_px": 3.5,
        "node_generation_mode": "turn_cost_repaired_grid",
        "repaired_grid_max_offset_factor": 0.28,
        "row_endpoint_alignment_enable": True,
        "node_obstacle_ratio_filter_enable": True,
        "node_obstacle_ratio_threshold": 0.45,
    }
    assert captured["legacy_source"] is fake_cell_grid
    assert result.static_cell_grid is fake_cell_grid
    assert not hasattr(result, "legacy_node_matrix")
    assert not hasattr(result, "nodes")
    assert result.graph_access.legacy_node_mirror(fake_node.stable_id) is fake_node
    assert result.coverage_graph.summary()["accessible_cell_count"] == 1
    assert result.stage_record.summary["node_generation_profile"]["profile_id"] == "turn_cost_repaired_grid_v1"
    assert result.stage_record.summary["node_generation_profile"]["strategy"] == "regular_grid_with_bounded_repair"
    assert result.stage_record.summary["node_generation_profile"]["repaired_grid_max_offset_factor"] == 0.28
    assert result.stage_record.summary["node_generation_profile"]["row_endpoint_alignment_enable"] is True
