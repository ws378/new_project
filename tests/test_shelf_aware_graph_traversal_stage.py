from __future__ import annotations

import numpy as np

from algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.graph_traversal import (
    GraphTraversalStageInput,
    run_graph_traversal_stage,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import (
    PlannerConfig,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal import (
    TraversalResult,
)


def test_run_graph_traversal_stage_passes_inputs_and_records_trace(monkeypatch):
    graph_access = object()
    start_cell_id = "cell_start"
    config = PlannerConfig()
    local_direction_map = np.ones((3, 4), dtype=np.float32)
    local_direction_confidence = np.full((3, 4), 0.75, dtype=np.float32)
    edge_label_map = np.zeros((3, 4), dtype=np.int32)
    calls: list[dict[str, object]] = []

    def fake_run_traversal_loop(**kwargs):
        calls.append(kwargs)
        return TraversalResult(
            fov_coverage_path=[(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)],
            move_trace=[{"source": "start"}, {"source": "normal"}],
            fallback_debug_trace=[{"step": 2}],
            traversal_state_summary={
                "total_cell_count": 7,
                "visited_cell_count": 3,
            },
            candidate_decision_debug_trace=[{"step": 1}, {"step": 2}],
        )

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.pipeline.graph_traversal.run_traversal_loop",
        fake_run_traversal_loop,
    )

    result = run_graph_traversal_stage(
        GraphTraversalStageInput(
            graph_access=graph_access,
            start_cell_id=start_cell_id,
            coverage_width_px=12,
            config=config,
            map_resolution=0.05,
            local_direction_map=local_direction_map,
            local_direction_confidence=local_direction_confidence,
            rotated_edge_label_map=edge_label_map,
        )
    )

    assert calls == [
        {
            "graph_access": graph_access,
            "start_cell_id": start_cell_id,
            "coverage_width_px": 12,
            "config": config,
            "map_resolution": 0.05,
            "local_direction_map": local_direction_map,
            "local_direction_confidence": local_direction_confidence,
            "edge_label_map": edge_label_map,
        }
    ]
    assert result.traversal_result.fov_coverage_path[-1] == (5.0, 6.0)
    assert result.stage_record.stage_name == "graph_traversal"
    assert result.stage_record.mutates_path is True
    assert result.stage_record.output_point_count == 3
    assert result.stage_record.summary == {
        "move_trace_count": 2,
        "fallback_event_count": 1,
        "candidate_decision_event_count": 2,
        "traversal_state": {
            "total_cell_count": 7,
            "visited_cell_count": 3,
        },
    }


def test_graph_traversal_stage_input_has_no_legacy_start_node_field() -> None:
    stage_input = GraphTraversalStageInput(
        graph_access=object(),
        start_cell_id="cell_start",
        coverage_width_px=12,
        config=PlannerConfig(),
        map_resolution=0.05,
        local_direction_map=np.zeros((1, 1), dtype=np.float32),
        local_direction_confidence=np.zeros((1, 1), dtype=np.float32),
        rotated_edge_label_map=None,
    )

    assert stage_input.start_cell_id == "cell_start"
    assert not hasattr(stage_input, "start_node")
