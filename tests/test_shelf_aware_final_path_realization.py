from __future__ import annotations

import numpy as np

from algorithms.coverage_planning.planners.shelf_aware_guarded.final_path.realization import (
    FinalPathRealizationInput,
    realize_final_path,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.final_path.transform_record import (
    FINAL_PATH_PROVENANCE_POLICY_SEMANTIC_PATH_ARTIFACT,
    FINAL_PATH_TRANSFORM_FINAL_PATH_GEOMETRY,
    FINAL_PATH_TRANSFORM_ISOLATED_JUMP_CLEANUP,
    FINAL_PATH_TRANSFORM_SEMANTIC_GLOBAL_PATH,
    FINAL_PATH_TRANSFORM_SIMPLIFY_ROTATED_PATH,
    FINAL_PATH_TRANSFORM_TYPE_GEOMETRIC_FORMATTING,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import (
    Node,
    PlannerConfig,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_graph_access import (
    TraversalGraphAccess,
)
from tests.shelf_aware_graph_fixture import build_coverage_graph_from_legacy_node_fixture


def test_final_path_realization_keeps_stage_contract_when_semantic_and_cleanup_disabled():
    config = PlannerConfig()
    config.semantic_path_enable = False
    config.strategy.simplify_enable = False
    config.isolated_jump_cleanup.enable = False
    inverse_rotation = np.array([[1.0, 0.0, 10.0], [0.0, 1.0, 20.0]], dtype=np.float32)
    fov_path = [(0.0, 0.0), (3.0, 0.0), (3.0, 4.0)]
    node = Node(
        planning_point_px=(0, 0),
        grid_center_px=(0, 0),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    nodes = [[node]]
    graph_access = TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=nodes,
        coverage_graph=build_coverage_graph_from_legacy_node_fixture(nodes),
    )

    result = realize_final_path(
        FinalPathRealizationInput(
            fov_coverage_path=fov_path,
            graph_access=graph_access,
            planning_room_map=np.full((8, 8), 255, dtype=np.uint8),
            rotated_room_map=np.full((8, 8), 255, dtype=np.uint8),
            inverse_rotation=inverse_rotation,
            coverage_width_px=4,
            map_resolution=0.05,
            config=config,
        )
    )

    assert result.simplified_fov_path == fov_path
    assert result.pixel_points_raw == [(10.0, 20.0), (13.0, 20.0), (13.0, 24.0)]
    assert result.baseline_pixel_points == result.pixel_points
    assert result.node_semantics_payload is None
    assert result.semantic_path_payload is None
    assert result.jump_cleanup_result.debug == {"enabled": False}
    assert [record.stage_name for record in result.pipeline_stage_records] == [
        "simplify_rotated_path",
        "semantic_global_path",
        "isolated_jump_cleanup",
        "final_path_geometry",
    ]
    assert result.pipeline_stage_records[1].status == "skipped"
    assert result.pipeline_stage_records[2].summary["changed"] is False
    assert result.pipeline_stage_records[3].summary["segment_count"] == 2
    assert len(result.pixel_poses) == 3
    assert len(result.pixel_segments) == 1
    assert [record.name for record in result.transform_records] == [
        FINAL_PATH_TRANSFORM_SIMPLIFY_ROTATED_PATH,
        FINAL_PATH_TRANSFORM_SEMANTIC_GLOBAL_PATH,
        FINAL_PATH_TRANSFORM_ISOLATED_JUMP_CLEANUP,
        FINAL_PATH_TRANSFORM_FINAL_PATH_GEOMETRY,
    ]
    assert all(record.allowed_in_formal for record in result.transform_records)
    assert all(record.point_count_delta == 0 for record in result.transform_records)
    assert result.transform_records[0].enabled is False
    assert result.transform_records[1].enabled is False
    assert result.transform_records[2].enabled is False
    assert result.transform_records[3].transform_type == FINAL_PATH_TRANSFORM_TYPE_GEOMETRIC_FORMATTING


def test_final_path_realization_records_semantic_payload_after_baseline_path(monkeypatch):
    config = PlannerConfig()
    config.semantic_path_enable = True
    config.strategy.simplify_enable = False
    config.isolated_jump_cleanup.enable = False
    inverse_rotation = np.array([[1.0, 0.0, 10.0], [0.0, 1.0, 20.0]], dtype=np.float32)
    fov_path = [(0.0, 0.0), (2.0, 0.0)]
    semantic_payload = {"summary": {"node_count": 2}}
    received_baseline: list[tuple[float, float]] = []
    node = Node(
        planning_point_px=(0, 0),
        grid_center_px=(0, 0),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    nodes = [[node]]
    graph_access = TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=nodes,
        coverage_graph=build_coverage_graph_from_legacy_node_fixture(nodes),
    )

    def fake_node_semantics(**kwargs):
        assert kwargs["coverage_width_px"] == 4
        assert kwargs["resolution_m_per_px"] == 0.05
        assert kwargs["graph_access"] is graph_access
        return semantic_payload

    def fake_semantic_path(**kwargs):
        received_baseline.extend(kwargs["pixel_points"])
        assert kwargs["node_semantics_payload"] is semantic_payload
        return {
            "path_points": [(10.0, 20.0), (12.0, 20.0), (12.0, 22.0)],
            "summary": {"enabled": True, "inserted_point_count": 1},
        }

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.final_path.realization.build_node_semantics",
        fake_node_semantics,
    )
    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.final_path.realization.build_semantic_global_path",
        fake_semantic_path,
    )

    result = realize_final_path(
        FinalPathRealizationInput(
            fov_coverage_path=fov_path,
            graph_access=graph_access,
            planning_room_map=np.full((4, 4), 255, dtype=np.uint8),
            rotated_room_map=np.full((4, 4), 255, dtype=np.uint8),
            inverse_rotation=inverse_rotation,
            coverage_width_px=4,
            map_resolution=0.05,
            config=config,
        )
    )

    assert received_baseline == [(10.0, 20.0), (12.0, 20.0)]
    assert result.baseline_pixel_points == [(10.0, 20.0), (12.0, 20.0)]
    assert result.pixel_points == [(10.0, 20.0), (12.0, 20.0), (12.0, 22.0)]
    assert result.node_semantics_payload is semantic_payload
    assert result.semantic_path_payload["summary"]["inserted_point_count"] == 1
    semantic_stage = result.pipeline_stage_records[1]
    assert semantic_stage.stage_name == "semantic_global_path"
    assert semantic_stage.status == "completed"
    assert semantic_stage.input_point_count == 2
    assert semantic_stage.output_point_count == 3
    semantic_transform = result.transform_records[1]
    assert semantic_transform.name == FINAL_PATH_TRANSFORM_SEMANTIC_GLOBAL_PATH
    assert semantic_transform.enabled is True
    assert semantic_transform.point_count_delta == 1
    assert semantic_transform.added_point_count == 1
    assert semantic_transform.changes_path_points is True
    assert semantic_transform.provenance_policy == FINAL_PATH_PROVENANCE_POLICY_SEMANTIC_PATH_ARTIFACT
