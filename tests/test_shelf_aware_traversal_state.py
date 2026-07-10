from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from algorithms.coverage_planning.planners.shelf_aware_guarded import (
    PlannerConfig,
    plan_coverage_path,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.graph_build.grid_builder import (
    build_cell_candidates,
    build_legacy_node_matrix,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal import (
    choose_initial_angle,
    initialize_traversal_runtime,
    run_traversal_loop,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_step_selection import (
    TraversalStepContext,
    select_next_traversal_candidate,
    sync_history_clearance_index,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_ref import (
    TraversalCandidateRef,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_summary import (
    CandidatePhaseSelection,
    CandidatePhaseSummary,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_cursor import (
    TraversalCursor,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_state import (
    TraversalState,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_graph_access import (
    TraversalGraphAccess,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_move import (
    normalize_turn_angle_deg,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_roles import (
    MOVE_SOURCE_GLOBAL_FALLBACK,
    MOVE_SOURCE_NORMAL_NEIGHBOR,
    MOVE_SOURCE_REVISIT_BRIDGE,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import Node
from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.provenance_payloads import (
    FINAL_SEGMENT_PROVENANCE_VERSION,
    TRAVERSAL_MOVE_TRACE_VERSION,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.decision_debug_payloads import (
    CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION,
)
from tests.shelf_aware_graph_fixture import build_coverage_graph_from_legacy_node_fixture


def _graph_access(nodes):
    return TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=nodes,
        coverage_graph=build_coverage_graph_from_legacy_node_fixture(nodes),
    )


def _build_legacy_mirror_from_cell_candidates(*args, **kwargs):
    return build_legacy_node_matrix(build_cell_candidates(*args, **kwargs))


def _graph_access_from_accessible_nodes(accessible_nodes):
    return _graph_access([list(accessible_nodes)])


def _move_trace_item_by_id(move_trace, move_id):
    return next(item for item in move_trace if item["move_id"] == move_id)


def _state_from_accessible_nodes(accessible_nodes, start):
    graph_access = _graph_access_from_accessible_nodes(accessible_nodes)
    state = TraversalState.from_start(
        accessible_cell_ids=[str(node.stable_id) for node in accessible_nodes],
        start_cell_id=str(start.stable_id),
    )
    return state


def test_traversal_state_initializes_from_explicit_static_cell_ids() -> None:
    state = TraversalState.from_start(
        accessible_cell_ids=["cell_a", "cell_b", "cell_c"],
        start_cell_id="cell_b",
    )

    assert state.current_cell_id == "cell_b"
    assert state.visited_cell_ids == {"cell_b"}
    assert state.visit_counts == {"cell_b": 1}
    assert state.path_cell_ids == ["cell_b"]
    assert state.remaining_unvisited_count == 2
    assert state.total_cell_count == 3


def test_traversal_state_snapshot_is_immutable_dynamic_read_model() -> None:
    state = TraversalState.from_start(
        accessible_cell_ids=["r0_c0", "r0_c1"],
        start_cell_id="r0_c0",
    )
    snapshot = state.to_snapshot()
    state.record_move(
        to_cell_id="r0_c1",
        heading_rad=0.0,
        was_first_visit=True,
        visit_count=1,
    )

    assert snapshot.current_cell_id == "r0_c0"
    assert snapshot.is_visited_cell("r0_c0") is True
    assert snapshot.is_visited_cell("r0_c1") is False
    assert snapshot.visit_count_for_cell("r0_c0") == 1
    assert snapshot.visit_count_for_cell("r0_c1") == 0


def test_traversal_state_rejects_start_outside_static_accessible_cells() -> None:
    with pytest.raises(AssertionError, match="start cell must be accessible"):
        TraversalState.from_start(
            accessible_cell_ids=["cell_a"],
            start_cell_id="cell_b",
        )


def test_traversal_state_rejects_duplicate_static_accessible_cells() -> None:
    with pytest.raises(AssertionError, match="accessible_cell_ids must be unique"):
        TraversalState.from_start(
            accessible_cell_ids=["cell_a", "cell_a"],
            start_cell_id="cell_a",
        )


def test_initialize_traversal_runtime_ignores_stale_legacy_visited_flags() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    stale_visited_neighbor = Node(
        planning_point_px=(20, 10),
        grid_center_px=(20, 10),
        obstacle=False,
        visited=True,
        visit_count=7,
        grid_row=0,
        grid_col=1,
    )
    start.neighbors.append(stale_visited_neighbor)
    stale_visited_neighbor.neighbors.append(start)
    config = PlannerConfig()

    runtime = initialize_traversal_runtime(
        start_cell_id=start.stable_id,
        config=config,
        graph_access=_graph_access([[start, stale_visited_neighbor]]),
    )

    assert runtime.traversal_state.visited_cell_ids == {str(start.stable_id)}
    assert runtime.traversal_state.visit_counts == {str(start.stable_id): 1}
    assert runtime.traversal_state.remaining_unvisited_count == 1


def test_initialize_traversal_runtime_does_not_write_legacy_start_visit_count() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        visited=True,
        visit_count=99,
        grid_row=0,
        grid_col=0,
    )
    config = PlannerConfig()

    runtime = initialize_traversal_runtime(
        start_cell_id=start.stable_id,
        config=config,
        graph_access=_graph_access([[start]]),
    )

    assert start.visited is True
    assert start.visit_count == 99
    assert runtime.traversal_state.visit_counts == {str(start.stable_id): 1}
    assert runtime.traversal_state.remaining_unvisited_count == 0


def test_initialize_traversal_runtime_uses_graph_snapshot_for_start_geometry() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    neighbor = Node(
        planning_point_px=(20, 10),
        grid_center_px=(20, 10),
        obstacle=False,
        grid_row=0,
        grid_col=1,
    )
    start.neighbors.append(neighbor)
    neighbor.neighbors.append(start)
    graph_access = _graph_access([[start, neighbor]])
    start.planning_point_px = (900, 900)
    neighbor.planning_point_px = (900, 901)

    runtime = initialize_traversal_runtime(
        start_cell_id=start.stable_id,
        config=PlannerConfig(),
        graph_access=graph_access,
    )

    assert runtime.fov_coverage_path == [(10.0, 10.0)]
    assert runtime.move_trace[0]["to_point_rotated_px"] == [10.0, 10.0]
    assert runtime.previous_travel_angle == 0.0


@pytest.mark.parametrize(
    ("neighbor_point", "expected_angle"),
    [
        ((20, 10), 0.0),
        ((0, 10), math.pi),
        ((10, 0), -0.5 * math.pi),
        ((10, 20), 0.5 * math.pi),
    ],
)
def test_choose_initial_angle_uses_graph_snapshot_neighbor_geometry(
    neighbor_point: tuple[int, int],
    expected_angle: float,
) -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    neighbor = Node(
        planning_point_px=neighbor_point,
        grid_center_px=neighbor_point,
        obstacle=False,
        grid_row=0,
        grid_col=1,
    )
    start.neighbors.append(neighbor)
    neighbor.neighbors.append(start)
    graph_access = _graph_access([[start, neighbor]])
    start.planning_point_px = (900, 900)
    neighbor.planning_point_px = (901, 901)

    assert choose_initial_angle(start.stable_id, graph_access=graph_access) == expected_angle


def test_choose_initial_angle_falls_back_to_right_without_accessible_neighbor() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )

    assert choose_initial_angle(start.stable_id, graph_access=_graph_access([[start]])) == 0.0


def test_traversal_state_revisit_does_not_reduce_remaining_count() -> None:
    room_map = np.zeros((30, 40), dtype=np.uint8)
    room_map[5:25, 5:35] = 255
    nodes = _build_legacy_mirror_from_cell_candidates(
        room_map,
        (0, 0),
        (40, 30),
        10,
        robot_half_width_px=2.0,
        row_endpoint_alignment_enable=False,
    )
    accessible = [node for row in nodes for node in row if not node.obstacle]
    start = accessible[0]

    state = _state_from_accessible_nodes(accessible, start)
    remaining_after_start = state.remaining_unvisited_count

    start_visit_count = state.visit_count_for_cell(start.stable_id) + 1
    state.record_move(
        to_cell_id=str(start.stable_id),
        heading_rad=0.0,
        was_first_visit=False,
        visit_count=start_visit_count,
    )

    assert state.visit_counts[start.stable_id] == 2
    assert state.remaining_unvisited_count == remaining_after_start
    assert state.path_cell_ids == [start.stable_id, start.stable_id]


def test_traversal_state_advances_history_clearance_index_size_by_one() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    state = _state_from_accessible_nodes([start], start)

    assert state.advance_history_clearance_index_size() == 1
    assert state.advance_history_clearance_index_size() == 2
    assert state.history_clearance_index_size == 2


def test_initialize_traversal_runtime_marks_start_and_builds_state() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    neighbor = Node(
        planning_point_px=(20, 10),
        grid_center_px=(20, 10),
        obstacle=False,
        grid_row=0,
        grid_col=1,
    )
    obstacle = Node(
        planning_point_px=(30, 10),
        grid_center_px=(30, 10),
        obstacle=True,
        grid_row=0,
        grid_col=2,
    )
    start.neighbors.append(neighbor)
    neighbor.neighbors.append(start)
    config = PlannerConfig()
    config.strategy.max_revisit_count = 3

    runtime = initialize_traversal_runtime(
        start_cell_id=start.stable_id,
        config=config,
        graph_access=_graph_access([[start, neighbor, obstacle]]),
    )

    assert not start.visited
    assert start.visit_count == 0
    assert not neighbor.visited
    assert neighbor.visit_count == 0
    assert not obstacle.visited
    assert obstacle.visit_count == 0
    assert runtime.fov_coverage_path == [(10.0, 10.0)]
    assert runtime.move_trace[0]["move_source"] == "start"
    assert runtime.move_trace[0]["to_node_id"] == start.stable_id
    assert runtime.move_trace[0]["to_point_rotated_px"] == [10.0, 10.0]
    assert runtime.cursor.cell_id == start.stable_id
    assert runtime.previous_travel_angle == 0.0
    assert runtime.accessible_cell_ids == (start.stable_id, neighbor.stable_id)
    assert not hasattr(runtime, "accessible_nodes")
    assert runtime.traversal_state.current_cell_id == start.stable_id
    assert runtime.traversal_state.path_cell_ids == [start.stable_id]
    assert runtime.traversal_state.previous_heading_rad is None
    assert runtime.traversal_state.remaining_unvisited_count == 1
    assert runtime.traversal_state.total_cell_count == 2
    assert runtime.max_total_steps == 8


def test_traversal_cursor_rejects_state_cell_mismatch() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    other = Node(
        planning_point_px=(20, 10),
        grid_center_px=(20, 10),
        obstacle=False,
        grid_row=0,
        grid_col=1,
    )
    state = TraversalState.from_start(
        accessible_cell_ids=[start.stable_id, other.stable_id],
        start_cell_id=start.stable_id,
    )
    cursor = TraversalCursor(cell_id=other.stable_id)

    with pytest.raises(AssertionError, match="TraversalCursor cell_id diverged"):
        cursor.assert_matches_state(state)


def test_sync_history_clearance_index_uses_state_progress() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    state = _state_from_accessible_nodes([start], start)
    short_path = [(float(index), 0.0) for index in range(12)]
    path = [(float(index), 0.0) for index in range(15)]
    longer_path = [(float(index), 0.0) for index in range(17)]
    added_points: list[tuple[float, float]] = []

    class FakeHistoryClearanceIndex:
        def add_point(self, point):
            added_points.append((float(point[0]), float(point[1])))

    assert sync_history_clearance_index(
        history_clearance_index=None,
        fov_coverage_path=path,
        traversal_state=state,
    ) is None

    index = FakeHistoryClearanceIndex()

    assert sync_history_clearance_index(
        history_clearance_index=index,
        fov_coverage_path=short_path,
        traversal_state=state,
    ) is index
    assert added_points == []
    assert state.history_clearance_index_size == 0

    assert sync_history_clearance_index(
        history_clearance_index=index,
        fov_coverage_path=path,
        traversal_state=state,
    ) is index
    assert added_points == [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    assert state.history_clearance_index_size == 3

    assert sync_history_clearance_index(
        history_clearance_index=index,
        fov_coverage_path=longer_path,
        traversal_state=state,
    ) is index
    assert added_points == [
        (0.0, 0.0),
        (1.0, 0.0),
        (2.0, 0.0),
        (3.0, 0.0),
        (4.0, 0.0),
    ]
    assert state.history_clearance_index_size == 5


def _phase_selection(cell_id: str, move_source: str) -> CandidatePhaseSelection:
    return CandidatePhaseSelection.selected(
        candidate_ref=TraversalCandidateRef.from_cell_id(cell_id),
        move_source=move_source,
        selected_energy=1.0,
        phase_summary=CandidatePhaseSummary.from_selected(
            candidate_count=1,
            energy_evaluated_candidate_count=1,
            accepted_energies=[1.0],
            selected_energy=1.0,
        ),
    )


@pytest.mark.parametrize(
    ("normal_has_selection", "revisit_has_selection", "expected_calls"),
    [
        (True, False, ["normal"]),
        (False, True, ["normal", "revisit"]),
        (False, False, ["normal", "revisit", "sync", "fallback"]),
    ],
)
def test_select_next_traversal_candidate_syncs_history_only_before_fallback(
    monkeypatch,
    normal_has_selection: bool,
    revisit_has_selection: bool,
    expected_calls: list[str],
) -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    target = Node(
        planning_point_px=(20, 10),
        grid_center_px=(20, 10),
        obstacle=False,
        grid_row=0,
        grid_col=1,
    )
    start.neighbors.append(target)
    target.neighbors.append(start)
    graph_access = _graph_access([[start, target]])
    traversal_state = TraversalState.from_start(
        accessible_cell_ids=[start.stable_id, target.stable_id],
        start_cell_id=start.stable_id,
    )
    cursor = TraversalCursor.from_cell_id(start.stable_id)
    config = PlannerConfig(write_artifacts=True)
    config.strategy.allow_revisit_bridge = True
    calls: list[str] = []

    def fake_normal_phase(**_kwargs):
        calls.append("normal")
        if normal_has_selection:
            return _phase_selection(target.stable_id, MOVE_SOURCE_NORMAL_NEIGHBOR)
        return CandidatePhaseSelection.empty()

    def fake_revisit_phase(**_kwargs):
        calls.append("revisit")
        if revisit_has_selection:
            return _phase_selection(target.stable_id, MOVE_SOURCE_REVISIT_BRIDGE)
        return CandidatePhaseSelection.empty()

    def fake_sync_history_clearance_index(**kwargs):
        calls.append("sync")
        return kwargs["history_clearance_index"]

    def fake_global_fallback_phase(**_kwargs):
        calls.append("fallback")
        return SimpleNamespace(
            selection=_phase_selection(target.stable_id, MOVE_SOURCE_GLOBAL_FALLBACK),
            debug_event={"fallback": True},
        )

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_step_selection.select_normal_neighbor_phase",
        fake_normal_phase,
    )
    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_step_selection.select_revisit_bridge_phase",
        fake_revisit_phase,
    )
    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_step_selection.sync_history_clearance_index",
        fake_sync_history_clearance_index,
    )
    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_step_selection.select_global_fallback_phase",
        fake_global_fallback_phase,
    )

    decision = select_next_traversal_candidate(
        cursor=cursor,
        context=TraversalStepContext(
            fov_coverage_path=[(float(index), 0.0) for index in range(16)],
            previous_travel_angle=0.0,
            traversal_state=traversal_state,
            graph_access=graph_access,
            history_clearance_index=object(),
            coverage_width_px=10,
            config=config,
            map_resolution=0.05,
            local_direction_map=np.zeros((30, 30), dtype=float),
            local_direction_confidence=np.zeros((30, 30), dtype=float),
            edge_label_map=None,
            step_counter=3,
        ),
    )

    assert calls == expected_calls
    if expected_calls[-1] == "fallback":
        assert decision.fallback_debug_event == {"fallback": True}
    else:
        assert decision.fallback_debug_event is None


def test_run_traversal_loop_updates_history_clearance_index_through_state(monkeypatch) -> None:
    chain = [
        Node(
            planning_point_px=(index * 10, 0),
            grid_center_px=(index * 10, 0),
            obstacle=False,
            grid_row=0,
            grid_col=index,
        )
        for index in range(14)
    ]
    detached = Node(
        planning_point_px=(200, 0),
        grid_center_px=(200, 0),
        obstacle=False,
        grid_row=1,
        grid_col=0,
    )
    for left, right in zip(chain, chain[1:]):
        left.neighbors.append(right)
        right.neighbors.append(left)
    nodes = [chain, [detached]]
    added_points: list[tuple[float, float]] = []

    class FakeHistoryClearanceIndex:
        def add_point(self, point):
            added_points.append((float(point[0]), float(point[1])))

        def min_distance(self, _candidate_point):
            return float("inf")

    def fake_build_history_clearance_index(*_args, **_kwargs):
        return FakeHistoryClearanceIndex()

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_step_selection.build_history_clearance_index",
        fake_build_history_clearance_index,
    )
    config = PlannerConfig(write_artifacts=True)
    config.local_direction.enable = False
    config.strategy.history_clearance_weight = 1.0

    result = run_traversal_loop(
        graph_access=_graph_access(nodes),
        start_cell_id=chain[0].stable_id,
        coverage_width_px=10,
        config=config,
        map_resolution=0.05,
        local_direction_map=np.zeros((50, 250), dtype=float),
        local_direction_confidence=np.zeros((50, 250), dtype=float),
        edge_label_map=None,
    )

    assert result.move_trace[-1]["move_source"] == "global_fallback"
    assert added_points == [(0.0, 0.0), (10.0, 0.0)]
    assert result.traversal_state_summary["history_clearance_index_size"] == 2
    assert result.traversal_state_summary["remaining_unvisited_count"] == 0


def test_traversal_state_records_global_fallback_without_changing_move_source() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    target = Node(
        planning_point_px=(30, 10),
        grid_center_px=(30, 10),
        obstacle=False,
        grid_row=0,
        grid_col=1,
    )
    nodes = [[start, target]]
    config = PlannerConfig(write_artifacts=True)
    config.local_direction.enable = False

    result = run_traversal_loop(
        graph_access=_graph_access(nodes),
        start_cell_id=start.stable_id,
        coverage_width_px=10,
        config=config,
        map_resolution=0.05,
        local_direction_map=np.zeros((50, 50), dtype=float),
        local_direction_confidence=np.zeros((50, 50), dtype=float),
        edge_label_map=None,
    )

    assert result.fov_coverage_path == [(10.0, 10.0), (30.0, 10.0)]
    assert len(result.move_trace) == 2
    assert result.move_trace[0]["move_id"] == "move_000001"
    assert result.move_trace[1]["move_id"] == "move_000002"
    assert result.move_trace[1]["move_source"] == "global_fallback"
    assert result.move_trace[1]["edge_role"] == "fallback_transfer"
    assert result.move_trace[1]["distance_px"] == pytest.approx(20.0)
    assert result.move_trace[1]["heading_rad"] == pytest.approx(0.0)
    assert result.move_trace[1]["turn_angle_deg"] == pytest.approx(0.0)
    assert result.move_trace[1]["phase_candidate_count"] == 1
    assert result.move_trace[1]["phase_energy_evaluated_candidate_count"] == 1
    assert result.move_trace[1]["phase_accepted_candidate_count"] == 1
    assert result.move_trace[1]["phase_rejected_before_energy_count"] == 0
    assert result.move_trace[1]["phase_candidate_rank"] == 1
    assert result.traversal_state_summary["path_cell_count"] == 2
    assert result.traversal_state_summary["remaining_unvisited_count"] == 0
    assert target.visited is False
    assert target.visit_count == 0


def test_run_traversal_loop_rejects_start_node_blocked_in_coverage_graph() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=True,
        grid_row=0,
        grid_col=0,
    )
    nodes = [[start]]
    config = PlannerConfig(write_artifacts=True)
    config.local_direction.enable = False

    with pytest.raises(AssertionError, match="start_cell_id must be accessible"):
        run_traversal_loop(
            graph_access=_graph_access(nodes),
            start_cell_id=start.stable_id,
            coverage_width_px=10,
            config=config,
            map_resolution=0.05,
            local_direction_map=np.zeros((30, 30), dtype=float),
            local_direction_confidence=np.zeros((30, 30), dtype=float),
            edge_label_map=None,
        )


def test_run_traversal_loop_uses_start_cell_id_accessibility_snapshot() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    graph_access = _graph_access([[start]])
    start.obstacle = True
    config = PlannerConfig(write_artifacts=True)
    config.local_direction.enable = False

    result = run_traversal_loop(
        graph_access=graph_access,
        start_cell_id=start.stable_id,
        coverage_width_px=10,
        config=config,
        map_resolution=0.05,
        local_direction_map=np.zeros((30, 30), dtype=float),
        local_direction_confidence=np.zeros((30, 30), dtype=float),
        edge_label_map=None,
    )

    assert result.fov_coverage_path == [(10.0, 10.0)]
    assert result.traversal_state_summary["current_cell_id"] == start.stable_id


def test_candidate_decision_debug_records_normal_success_phase() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    target = Node(
        planning_point_px=(20, 10),
        grid_center_px=(20, 10),
        obstacle=False,
        grid_row=0,
        grid_col=1,
    )
    start.neighbors.append(target)
    target.neighbors.append(start)
    config = PlannerConfig(write_artifacts=True)
    config.local_direction.enable = False

    nodes = [[start, target]]
    result = run_traversal_loop(
        graph_access=_graph_access(nodes),
        start_cell_id=start.stable_id,
        coverage_width_px=10,
        config=config,
        map_resolution=0.05,
        local_direction_map=np.zeros((40, 40), dtype=float),
        local_direction_confidence=np.zeros((40, 40), dtype=float),
        edge_label_map=None,
    )

    assert len(result.candidate_decision_debug_trace) == 1
    event = result.candidate_decision_debug_trace[0]
    assert event["selected_phase"] == "normal_neighbor"
    assert event["selected_cell_id"] == target.stable_id
    assert _move_trace_item_by_id(result.move_trace, event["selected_move_id"])["to_node_id"] == target.stable_id
    assert [phase["phase_name"] for phase in event["phases"]] == ["normal_neighbor"]
    assert event["phases"][0]["phase_summary"]["candidate_count"] == 1
    assert event["phases"][0]["candidate_records"][0]["accepted"] is True
    assert event["phases"][0]["candidate_records"][0]["score_components"]
    assert event["phases"][0]["candidate_records"][0]["score_component_sum_valid"] is True
    assert event["phases"][0]["candidate_records"][0]["rank_in_phase"] == 1


def test_candidate_decision_debug_records_revisit_success_after_normal_failure() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    bridge = Node(
        planning_point_px=(20, 10),
        grid_center_px=(20, 10),
        obstacle=False,
        grid_row=0,
        grid_col=1,
    )
    target = Node(
        planning_point_px=(10, 20),
        grid_center_px=(10, 20),
        obstacle=False,
        grid_row=1,
        grid_col=0,
    )
    start.neighbors.extend([bridge, target])
    bridge.neighbors.append(start)
    target.neighbors.append(start)
    config = PlannerConfig(write_artifacts=True)
    config.local_direction.enable = False
    config.strategy.allow_revisit_bridge = True
    config.strategy.max_revisit_count = 3

    nodes = [[start, bridge, target]]
    result = run_traversal_loop(
        graph_access=_graph_access(nodes),
        start_cell_id=start.stable_id,
        coverage_width_px=10,
        config=config,
        map_resolution=0.05,
        local_direction_map=np.zeros((40, 40), dtype=float),
        local_direction_confidence=np.zeros((40, 40), dtype=float),
        edge_label_map=None,
    )

    event = result.candidate_decision_debug_trace[1]
    assert event["selected_phase"] == "revisit_bridge"
    assert event["selected_cell_id"] == start.stable_id
    assert _move_trace_item_by_id(result.move_trace, event["selected_move_id"])["to_node_id"] == start.stable_id
    assert [phase["phase_name"] for phase in event["phases"]] == ["normal_neighbor", "revisit_bridge"]
    assert event["phases"][0]["has_selection"] is False
    assert event["phases"][1]["phase_summary"]["accepted_candidate_count"] == 1
    assert event["phases"][1]["candidate_records"][0]["cell_id"] == start.stable_id


def test_candidate_decision_debug_records_fallback_success_without_changing_fallback_debug() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    target = Node(
        planning_point_px=(30, 10),
        grid_center_px=(30, 10),
        obstacle=False,
        grid_row=0,
        grid_col=1,
    )
    config = PlannerConfig(write_artifacts=True)
    config.local_direction.enable = False

    nodes = [[start, target]]
    result = run_traversal_loop(
        graph_access=_graph_access(nodes),
        start_cell_id=start.stable_id,
        coverage_width_px=10,
        config=config,
        map_resolution=0.05,
        local_direction_map=np.zeros((50, 50), dtype=float),
        local_direction_confidence=np.zeros((50, 50), dtype=float),
        edge_label_map=None,
    )

    event = result.candidate_decision_debug_trace[0]
    assert event["selected_phase"] == "global_fallback"
    assert _move_trace_item_by_id(result.move_trace, event["selected_move_id"])["to_node_id"] == target.stable_id
    assert [phase["phase_name"] for phase in event["phases"]] == ["normal_neighbor", "global_fallback"]
    assert event["phases"][1]["candidate_records"][0]["cell_id"] == target.stable_id
    assert len(result.fallback_debug_trace) == 1
    assert result.fallback_debug_trace[0]["candidate_count"] == 1
    assert result.fallback_debug_trace[0]["selected_node_id"] == target.stable_id


def test_candidate_decision_debug_records_terminal_no_selection() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    config = PlannerConfig(write_artifacts=True)
    config.local_direction.enable = False

    nodes = [[start]]
    result = run_traversal_loop(
        graph_access=_graph_access(nodes),
        start_cell_id=start.stable_id,
        coverage_width_px=10,
        config=config,
        map_resolution=0.05,
        local_direction_map=np.zeros((30, 30), dtype=float),
        local_direction_confidence=np.zeros((30, 30), dtype=float),
        edge_label_map=None,
    )

    event = result.candidate_decision_debug_trace[0]
    assert event["selected_phase"] is None
    assert event["selected_cell_id"] is None
    assert event["selected_move_id"] is None
    assert [phase["phase_name"] for phase in event["phases"]] == ["normal_neighbor", "global_fallback"]
    assert event["phases"][0]["phase_summary"]["candidate_count"] == 0
    assert event["phases"][1]["phase_summary"]["candidate_count"] == 0


def test_candidate_decision_debug_trace_is_disabled_without_artifacts() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    target = Node(
        planning_point_px=(20, 10),
        grid_center_px=(20, 10),
        obstacle=False,
        grid_row=0,
        grid_col=1,
    )
    start.neighbors.append(target)
    target.neighbors.append(start)
    config = PlannerConfig(write_artifacts=False)
    config.local_direction.enable = False

    nodes = [[start, target]]
    result = run_traversal_loop(
        graph_access=_graph_access(nodes),
        start_cell_id=start.stable_id,
        coverage_width_px=10,
        config=config,
        map_resolution=0.05,
        local_direction_map=np.zeros((40, 40), dtype=float),
        local_direction_confidence=np.zeros((40, 40), dtype=float),
        edge_label_map=None,
    )

    assert result.candidate_decision_debug_trace == []


def test_traversal_move_turn_angle_uses_shortest_absolute_delta() -> None:
    assert normalize_turn_angle_deg(0.0, np.pi) == pytest.approx(180.0)
    assert normalize_turn_angle_deg(np.deg2rad(170.0), np.deg2rad(-170.0)) == pytest.approx(20.0)
    assert normalize_turn_angle_deg(None, 0.0) is None


def test_pipeline_trace_reports_traversal_state_without_changing_path(tmp_path: Path) -> None:
    room_map = np.zeros((60, 80), dtype=np.uint8)
    room_map[10:50, 10:70] = 255
    config = PlannerConfig(
        coverage_width_m=0.5,
        robot_width_m=0.2,
        write_artifacts=True,
        row_endpoint_alignment_enable=False,
        start_pixel=(15, 15),
    )

    path, artifacts = plan_coverage_path(
        room_map,
        {"resolution": 0.05, "origin": [0.0, 0.0, 0.0]},
        str(tmp_path),
        config,
    )

    assert artifacts.pipeline_trace_path is not None
    assert artifacts.artifact_manifest_path is not None
    assert artifacts.path_pixels_path is not None
    assert artifacts.path_generation_provenance_path is not None
    assert artifacts.final_segment_provenance_path is not None
    assert artifacts.candidate_decision_debug_path is not None
    payload = json.loads(Path(artifacts.pipeline_trace_path).read_text(encoding="utf-8"))
    manifest_payload = json.loads(Path(artifacts.artifact_manifest_path).read_text(encoding="utf-8"))
    assert manifest_payload["schema_version"] == "shelf_aware_guarded_artifact_manifest.v1"
    assert manifest_payload["result_contract"] == "CoveragePlanningResult"
    assert manifest_payload["artifact_role_note"] == (
        "Artifacts are evidence; CoveragePlanningResult remains the formal output truth."
    )
    assert manifest_payload["artifacts"]["path_generation_provenance"]["schema_or_format"] == TRAVERSAL_MOVE_TRACE_VERSION
    assert manifest_payload["artifacts"]["candidate_decision_debug"]["role"] == (
        "artifact_only_candidate_decision_evidence"
    )
    assert manifest_payload["artifacts"]["candidate_decision_debug"]["schema_or_format"] == (
        CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION
    )
    assert manifest_payload["artifacts"]["final_segment_provenance"]["role"] == "final_path_segment_source_evidence"
    assert manifest_payload["artifacts"]["final_segment_provenance"]["schema_or_format"] == FINAL_SEGMENT_PROVENANCE_VERSION
    assert manifest_payload["artifacts"]["final_path_transform_records"]["role"] == (
        "final_path_transform_manifest_embedded_in_metadata"
    )
    assert manifest_payload["artifacts"]["final_path_transform_records"]["schema_or_format"] == (
        "final_path_transform_records_v1"
    )
    input_stage = next(item for item in payload["stages"] if item["stage_name"] == "input_validation")
    assert input_stage["summary"]["coverage_width_px"] == 10
    assert input_stage["summary"]["robot_half_width_px"] == pytest.approx(2.0)
    rotation_stage = next(item for item in payload["stages"] if item["stage_name"] == "room_rotation")
    assert len(rotation_stage["summary"]["full_bounding_rect"]) == 4
    assert len(rotation_stage["summary"]["crop_rect"]) == 4
    assert rotation_stage["summary"]["rotated_crop_offset_px"]
    direction_stage = next(item for item in payload["stages"] if item["stage_name"] == "local_direction_field")
    assert direction_stage["summary"]["external_guidance_inputs"]["has_axis_direction_map"] is False
    graph_stage = next(item for item in payload["stages"] if item["stage_name"] == "coverage_graph_build")
    assert graph_stage["summary"]["rotated_min_room_px"]
    assert graph_stage["summary"]["rotated_max_room_px"]
    start_stage = next(item for item in payload["stages"] if item["stage_name"] == "start_cell_selection")
    assert start_stage["summary"]["requested_start_pixel"] == [15, 15]
    assert start_stage["summary"]["selected_cell_id"]
    traversal_stage = next(item for item in payload["stages"] if item["stage_name"] == "graph_traversal")
    state = traversal_stage["summary"]["traversal_state"]
    assert state["path_cell_count"] == traversal_stage["output_point_count"]
    assert state["remaining_unvisited_count"] == 0
    assert traversal_stage["summary"]["candidate_decision_event_count"] == state["path_cell_count"] - 1
    decision_debug_payload = json.loads(Path(artifacts.candidate_decision_debug_path).read_text(encoding="utf-8"))
    assert decision_debug_payload["schema_version"] == CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION
    assert decision_debug_payload["event_count"] == traversal_stage["summary"]["candidate_decision_event_count"]
    first_event = decision_debug_payload["events"][0]
    assert "current_cell_id" in first_event
    assert "selected_cell_id" in first_event
    assert "current_node_id" not in first_event
    assert "selected_node_id" not in first_event
    assert first_event["phases"][0]["phase_name"] == "normal_neighbor"
    assert "selected_cell_id" in first_event["phases"][0]
    assert "selected_node_id" not in first_event["phases"][0]
    assert "candidate_records" in first_event["phases"][0]
    first_record = first_event["phases"][0]["candidate_records"][0]
    assert "cell_id" in first_record
    assert "node_id" not in first_record
    assert first_record["score_components"]
    assert first_record["score_component_sum_valid"] is True
    path_pixels_payload = json.loads(Path(artifacts.path_pixels_path).read_text(encoding="utf-8"))
    assert path_pixels_payload[0]["index"] == 1
    assert {"x", "y", "theta"}.issubset(path_pixels_payload[0].keys())
    path_point_by_index = {item["index"]: item for item in path_pixels_payload}
    path_segments_payload = json.loads((tmp_path / "path_segments_pixels.json").read_text(encoding="utf-8"))
    assert path_segments_payload
    for segment in path_segments_payload:
        for point in segment:
            source_point = path_point_by_index[point["index"]]
            assert point["x"] == source_point["x"]
            assert point["y"] == source_point["y"]
    path_jump_segments_payload = json.loads((tmp_path / "path_jump_segments_pixels.json").read_text(encoding="utf-8"))
    for jump_segment in path_jump_segments_payload:
        for point in jump_segment:
            source_point = path_point_by_index[point["index"]]
            assert point["x"] == source_point["x"]
            assert point["y"] == source_point["y"]
    move_trace_payload = json.loads(Path(artifacts.path_generation_provenance_path).read_text(encoding="utf-8"))
    assert first_event["selected_move_id"] == move_trace_payload["items"][1]["move_id"]
    assert first_event["selected_cell_id"] == move_trace_payload["items"][1]["to_node_id"]
    assert move_trace_payload["version"] == TRAVERSAL_MOVE_TRACE_VERSION
    assert move_trace_payload["move_source_values"]
    assert move_trace_payload["edge_role_values"]
    assert move_trace_payload["items"][1]["from_point"]["pixel_x"] is not None
    assert move_trace_payload["items"][1]["to_point"]["pixel_y"] is not None
    assert len(move_trace_payload["items"]) == state["path_cell_count"]
    final_segment_payload = json.loads(Path(artifacts.final_segment_provenance_path).read_text(encoding="utf-8"))
    assert final_segment_payload["version"] == FINAL_SEGMENT_PROVENANCE_VERSION
    assert final_segment_payload["segment_count"] == max(0, len(path_pixels_payload) - 1)
    source_summary = final_segment_payload["source_summary"]
    assert (
        source_summary["matched_traversal_segment_count"]
        + source_summary["derived_final_geometry_segment_count"]
        == final_segment_payload["segment_count"]
    )
    assert move_trace_payload["items"][0]["move_id"] == "move_000001"
    assert move_trace_payload["items"][1]["move_id"] == "move_000002"
    assert move_trace_payload["items"][1]["distance_px"] > 0.0
    assert move_trace_payload["items"][1]["turn_angle_deg"] is not None
    assert move_trace_payload["items"][1]["phase_candidate_count"] >= 1
    assert move_trace_payload["items"][1]["phase_energy_evaluated_candidate_count"] >= 1
    assert move_trace_payload["items"][1]["phase_accepted_candidate_count"] >= 1
    assert move_trace_payload["items"][1]["phase_rejected_before_energy_count"] >= 0
    assert move_trace_payload["items"][1]["phase_candidate_rank"] >= 1
    pixel_path = json.loads(Path(artifacts.path_pixels_path).read_text(encoding="utf-8"))
    assert len(pixel_path) == len(path)
    expected_path_pixels = [
        (15.221704, 12.424744),
        (25.212187, 12.860937),
        (35.202671, 13.297131),
        (45.193153, 13.733326),
        (55.183636, 14.169519),
        (65.174118, 14.605713),
        (64.737923, 24.596195),
        (64.301735, 34.586678),
        (63.865536, 44.577164),
        (53.875053, 44.140968),
        (43.884571, 43.704773),
        (33.894089, 43.268578),
        (23.903605, 42.832382),
        (13.913123, 42.396194),
        (14.349317, 32.405708),
        (14.785511, 22.415226),
        (24.775993, 22.851419),
        (34.766476, 23.287613),
        (44.756958, 23.723808),
        (54.747440, 24.160002),
        (54.311245, 34.150482),
        (44.320763, 33.714287),
        (34.330280, 33.278099),
        (24.339800, 32.841904),
    ]
    assert [(round(item["x"], 6), round(item["y"], 6)) for item in pixel_path] == expected_path_pixels
    for pixel_pose, world_pose in zip(pixel_path, path):
        assert pixel_pose["index"] == world_pose["index"]
        assert pixel_pose["x"] == pytest.approx(world_pose["x"] / 0.05)
        assert pixel_pose["y"] == pytest.approx(60 - world_pose["y"] / 0.05)
    final_segment_payload = json.loads(Path(artifacts.final_segment_provenance_path).read_text(encoding="utf-8"))
    generation_move_ids = [
        item["generation_move"]["move_id"]
        for item in final_segment_payload["items"]
        if item["generation_move"] is not None
    ]
    assert generation_move_ids
    assert set(generation_move_ids).issubset({item["move_id"] for item in move_trace_payload["items"]})
    selected_move_ids = {
        event["selected_move_id"]
        for event in decision_debug_payload["events"]
        if event["selected_move_id"] is not None
    }
    assert selected_move_ids.issubset({item["move_id"] for item in move_trace_payload["items"]})
    assert set(generation_move_ids).issubset(selected_move_ids)
    assert path
