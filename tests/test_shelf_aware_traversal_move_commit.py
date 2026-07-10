from __future__ import annotations

import math

from algorithms.coverage_planning.planners.shelf_aware_guarded.models import Node
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_summary import (
    CandidatePhaseSelection,
    CandidatePhaseSummary,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_ref import (
    TraversalCandidateRef,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_cursor import (
    TraversalCursor,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_graph_access import (
    TraversalGraphAccess,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_move import (
    TraversalMove,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_move_commit import (
    commit_selected_traversal_move,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_state import (
    TraversalState,
)
from tests.shelf_aware_graph_fixture import build_coverage_graph_from_legacy_node_fixture


def _state_from_accessible_nodes(accessible_nodes, start):
    graph_access = _graph_access([list(accessible_nodes)])
    state = TraversalState.from_start(
        accessible_cell_ids=[str(node.stable_id) for node in accessible_nodes],
        start_cell_id=str(start.stable_id),
    )
    return state


def _graph_access(nodes):
    return TraversalGraphAccess.bind_legacy_mirror(
        legacy_mirror_matrix=nodes,
        coverage_graph=build_coverage_graph_from_legacy_node_fixture(nodes),
    )


def _cursor(node):
    return TraversalCursor.from_cell_id(node.stable_id)


def test_commit_selected_traversal_move_updates_traversal_state_and_trace() -> None:
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
    accessible_nodes = [start, target]
    graph_access = _graph_access([[start, target]])
    traversal_state = _state_from_accessible_nodes(accessible_nodes, start)
    fov_coverage_path = [(10.0, 10.0)]
    move_trace = [
        TraversalMove.start(
            to_node_id=str(start.stable_id),
            to_point_rotated_px=(10.0, 10.0),
        ).to_trace_item()
    ]
    selection = CandidatePhaseSelection.selected(
        candidate_ref=TraversalCandidateRef(cell_id=target.stable_id),
        move_source="normal_neighbor",
        selected_energy=4.5,
        revisit_frontier_score=0,
        phase_summary=CandidatePhaseSummary.from_selected(
            candidate_count=3,
            energy_evaluated_candidate_count=2,
            accepted_energies=[4.5, 9.0],
            selected_energy=4.5,
            rejected_before_energy_count=1,
        ),
    )

    committed = commit_selected_traversal_move(
        last_cursor=_cursor(start),
        next_selection=selection,
        fov_coverage_path=fov_coverage_path,
        move_trace=move_trace,
        traversal_state=traversal_state,
        graph_access=graph_access,
        previous_travel_angle=0.5 * math.pi,
        step_counter=1,
        local_residual_count=2,
    )

    assert committed.next_cursor.cell_id == target.stable_id
    assert committed.heading_rad == 0.0
    assert fov_coverage_path == [(10.0, 10.0), (20.0, 10.0)]
    assert target.visited is False
    assert target.visit_count == 0
    assert traversal_state.current_cell_id == target.stable_id
    assert traversal_state.remaining_unvisited_count == 0
    assert move_trace[-1] == committed.trace_item
    assert move_trace[-1]["move_source"] == "normal_neighbor"
    assert move_trace[-1]["edge_role"] == "coverage_lane"
    assert move_trace[-1]["selected_energy"] == 4.5
    assert move_trace[-1]["turn_angle_deg"] == 90.0
    assert move_trace[-1]["phase_candidate_count"] == 3
    assert move_trace[-1]["phase_rejected_before_energy_count"] == 1


def test_commit_selected_traversal_move_uses_selection_cell_id_for_graph_snapshot() -> None:
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
    accessible_nodes = [start, target]
    graph_access = _graph_access([[start, target]])
    traversal_state = _state_from_accessible_nodes(accessible_nodes, start)
    fov_coverage_path = [(10.0, 10.0)]
    move_trace: list[dict[str, object]] = []
    selection = CandidatePhaseSelection.selected(
        candidate_ref=TraversalCandidateRef(cell_id=target.stable_id),
        move_source="normal_neighbor",
        selected_energy=4.5,
        phase_summary=CandidatePhaseSummary.from_selected(
            candidate_count=1,
            energy_evaluated_candidate_count=1,
            accepted_energies=[4.5],
            selected_energy=4.5,
        ),
    )

    committed = commit_selected_traversal_move(
        last_cursor=_cursor(start),
        next_selection=selection,
        fov_coverage_path=fov_coverage_path,
        move_trace=move_trace,
        traversal_state=traversal_state,
        graph_access=graph_access,
        previous_travel_angle=0.0,
        step_counter=1,
        local_residual_count=0,
    )

    assert committed.next_cursor.cell_id == target.stable_id
    assert target.visited is False
    assert target.visit_count == 0
    assert fov_coverage_path[-1] == (20.0, 10.0)
    assert move_trace[-1]["to_node_id"] == target.stable_id


def test_commit_selected_traversal_move_keeps_remaining_count_on_revisit() -> None:
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
    accessible_nodes = [start, target]
    graph_access = _graph_access([[start, target]])
    traversal_state = _state_from_accessible_nodes(accessible_nodes, start)
    before_remaining = traversal_state.remaining_unvisited_count
    fov_coverage_path = [(10.0, 10.0)]
    move_trace: list[dict[str, object]] = []
    selection = CandidatePhaseSelection.selected(
        candidate_ref=TraversalCandidateRef(cell_id=start.stable_id),
        move_source="revisit_bridge",
        selected_energy=8.0,
        revisit_frontier_score=5,
        phase_summary=CandidatePhaseSummary.from_selected(
            candidate_count=1,
            energy_evaluated_candidate_count=1,
            accepted_energies=[8.0],
            selected_energy=8.0,
        ),
    )

    commit_selected_traversal_move(
        last_cursor=_cursor(start),
        next_selection=selection,
        fov_coverage_path=fov_coverage_path,
        move_trace=move_trace,
        traversal_state=traversal_state,
        graph_access=graph_access,
        previous_travel_angle=0.0,
        step_counter=2,
        local_residual_count=0,
    )

    assert start.visit_count == 0
    assert traversal_state.visit_count_for_cell(start.stable_id) == 2
    assert traversal_state.remaining_unvisited_count == before_remaining
    assert move_trace[-1]["move_source"] == "revisit_bridge"
    assert move_trace[-1]["edge_role"] == "revisit_bridge"
    assert move_trace[-1]["revisit_frontier_score"] == 5


def test_commit_selected_traversal_move_uses_traversal_state_for_first_visit() -> None:
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
        visited=True,
        visit_count=3,
        grid_row=0,
        grid_col=1,
    )
    traversal_state = TraversalState(
        current_cell_id=str(start.stable_id),
        visited_cell_ids={str(start.stable_id)},
        visit_counts={str(start.stable_id): 1},
        path_cell_ids=[str(start.stable_id)],
        previous_heading_rad=None,
        step_index=0,
        remaining_unvisited_count=1,
        total_cell_count=2,
    )
    selection = CandidatePhaseSelection.selected(
        candidate_ref=TraversalCandidateRef(cell_id=target.stable_id),
        move_source="normal_neighbor",
        selected_energy=2.0,
        phase_summary=CandidatePhaseSummary.from_selected(
            candidate_count=1,
            energy_evaluated_candidate_count=1,
            accepted_energies=[2.0],
            selected_energy=2.0,
        ),
    )
    graph_access = _graph_access([[start, target]])
    fov_coverage_path = [(10.0, 10.0)]
    move_trace: list[dict[str, object]] = []

    commit_selected_traversal_move(
        last_cursor=_cursor(start),
        next_selection=selection,
        fov_coverage_path=fov_coverage_path,
        move_trace=move_trace,
        traversal_state=traversal_state,
        graph_access=graph_access,
        previous_travel_angle=0.0,
        step_counter=1,
        local_residual_count=0,
    )

    assert target.visit_count == 3
    assert traversal_state.visit_counts[str(target.stable_id)] == 1
    assert traversal_state.remaining_unvisited_count == 0
    assert str(target.stable_id) in traversal_state.visited_cell_ids


def test_commit_selected_traversal_move_uses_traversal_state_visit_count_for_revisit() -> None:
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
        visited=True,
        visit_count=99,
        grid_row=0,
        grid_col=1,
    )
    traversal_state = TraversalState(
        current_cell_id=str(start.stable_id),
        visited_cell_ids={str(start.stable_id), str(target.stable_id)},
        visit_counts={str(start.stable_id): 1, str(target.stable_id): 2},
        path_cell_ids=[str(start.stable_id)],
        previous_heading_rad=None,
        step_index=0,
        remaining_unvisited_count=0,
        total_cell_count=2,
    )
    selection = CandidatePhaseSelection.selected(
        candidate_ref=TraversalCandidateRef(cell_id=target.stable_id),
        move_source="revisit_bridge",
        selected_energy=3.0,
        revisit_frontier_score=2,
        phase_summary=CandidatePhaseSummary.from_selected(
            candidate_count=1,
            energy_evaluated_candidate_count=1,
            accepted_energies=[3.0],
            selected_energy=3.0,
        ),
    )
    graph_access = _graph_access([[start, target]])

    commit_selected_traversal_move(
        last_cursor=_cursor(start),
        next_selection=selection,
        fov_coverage_path=[(10.0, 10.0)],
        move_trace=[],
        traversal_state=traversal_state,
        graph_access=graph_access,
        previous_travel_angle=0.0,
        step_counter=1,
        local_residual_count=0,
    )

    assert target.visit_count == 99
    assert traversal_state.visit_counts[str(target.stable_id)] == 3
    assert traversal_state.remaining_unvisited_count == 0


def test_commit_selected_traversal_move_uses_traversal_state_visit_count_for_global_fallback_first_visit() -> None:
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
        visited=True,
        visit_count=99,
        grid_row=0,
        grid_col=1,
    )
    traversal_state = TraversalState(
        current_cell_id=str(start.stable_id),
        visited_cell_ids={str(start.stable_id)},
        visit_counts={str(start.stable_id): 1},
        path_cell_ids=[str(start.stable_id)],
        previous_heading_rad=None,
        step_index=0,
        remaining_unvisited_count=1,
        total_cell_count=2,
    )
    selection = CandidatePhaseSelection.selected(
        candidate_ref=TraversalCandidateRef(cell_id=target.stable_id),
        move_source="global_fallback",
        selected_energy=7.0,
        phase_summary=CandidatePhaseSummary.from_selected(
            candidate_count=1,
            energy_evaluated_candidate_count=1,
            accepted_energies=[7.0],
            selected_energy=7.0,
        ),
    )
    move_trace: list[dict[str, object]] = []
    graph_access = _graph_access([[start, target]])

    commit_selected_traversal_move(
        last_cursor=_cursor(start),
        next_selection=selection,
        fov_coverage_path=[(10.0, 10.0)],
        move_trace=move_trace,
        traversal_state=traversal_state,
        graph_access=graph_access,
        previous_travel_angle=0.0,
        step_counter=1,
        local_residual_count=0,
    )

    assert target.visit_count == 99
    assert traversal_state.visit_counts[str(target.stable_id)] == 1
    assert traversal_state.remaining_unvisited_count == 0
    assert move_trace[-1]["move_source"] == "global_fallback"
    assert move_trace[-1]["edge_role"] == "fallback_transfer"


def test_commit_selected_traversal_move_uses_graph_snapshot_for_geometry() -> None:
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
    graph_access = _graph_access([[start, target]])
    start.planning_point_px = (999, 999)
    target.planning_point_px = (999, 1000)
    traversal_state = _state_from_accessible_nodes([start, target], start)
    selection = CandidatePhaseSelection.selected(
        candidate_ref=TraversalCandidateRef(cell_id=target.stable_id),
        move_source="normal_neighbor",
        selected_energy=1.0,
        phase_summary=CandidatePhaseSummary.from_selected(
            candidate_count=1,
            energy_evaluated_candidate_count=1,
            accepted_energies=[1.0],
            selected_energy=1.0,
        ),
    )
    fov_coverage_path = [(10.0, 10.0)]
    move_trace: list[dict[str, object]] = []

    committed = commit_selected_traversal_move(
        last_cursor=_cursor(start),
        next_selection=selection,
        fov_coverage_path=fov_coverage_path,
        move_trace=move_trace,
        traversal_state=traversal_state,
        graph_access=graph_access,
        previous_travel_angle=0.5 * math.pi,
        step_counter=1,
        local_residual_count=0,
    )

    assert committed.heading_rad == 0.0
    assert fov_coverage_path == [(10.0, 10.0), (30.0, 10.0)]
    assert move_trace[-1]["from_point_rotated_px"] == [10.0, 10.0]
    assert move_trace[-1]["to_point_rotated_px"] == [30.0, 10.0]
    assert move_trace[-1]["distance_px"] == 20.0
    assert move_trace[-1]["turn_angle_deg"] == 90.0


def test_commit_selected_traversal_move_rejects_selection_node_id_graph_mismatch() -> None:
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
    traversal_state = _state_from_accessible_nodes([start, target], start)
    selection = CandidatePhaseSelection.selected(
        candidate_ref=TraversalCandidateRef(cell_id="wrong_cell"),
        move_source="normal_neighbor",
        selected_energy=1.0,
        phase_summary=CandidatePhaseSummary.from_selected(
            candidate_count=1,
            energy_evaluated_candidate_count=1,
            accepted_energies=[1.0],
            selected_energy=1.0,
        ),
    )
    graph_access = _graph_access([[start, target]])

    try:
        commit_selected_traversal_move(
            last_cursor=_cursor(start),
            next_selection=selection,
            fov_coverage_path=[(10.0, 10.0)],
            move_trace=[],
            traversal_state=traversal_state,
            graph_access=graph_access,
            previous_travel_angle=0.0,
            step_counter=1,
            local_residual_count=0,
        )
    except AssertionError as exc:
        assert "Coverage graph cell missing" in str(exc)
    else:
        raise AssertionError("selection node_id graph mismatch should fail")


def test_commit_selected_traversal_move_rejects_stale_last_cursor() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    stale_current = Node(
        planning_point_px=(20, 10),
        grid_center_px=(20, 10),
        obstacle=False,
        grid_row=0,
        grid_col=1,
    )
    target = Node(
        planning_point_px=(30, 10),
        grid_center_px=(30, 10),
        obstacle=False,
        grid_row=0,
        grid_col=2,
    )
    graph_access = _graph_access([[start, stale_current, target]])
    traversal_state = _state_from_accessible_nodes([start, stale_current, target], start)
    selection = CandidatePhaseSelection.selected(
        candidate_ref=TraversalCandidateRef(cell_id=target.stable_id),
        move_source="normal_neighbor",
        selected_energy=1.0,
        phase_summary=CandidatePhaseSummary.from_selected(
            candidate_count=1,
            energy_evaluated_candidate_count=1,
            accepted_energies=[1.0],
            selected_energy=1.0,
        ),
    )

    try:
        commit_selected_traversal_move(
            last_cursor=_cursor(stale_current),
            next_selection=selection,
            fov_coverage_path=[(10.0, 10.0)],
            move_trace=[],
            traversal_state=traversal_state,
            graph_access=graph_access,
            previous_travel_angle=0.0,
            step_counter=1,
            local_residual_count=0,
        )
    except AssertionError as exc:
        assert "TraversalCursor cell_id diverged" in str(exc)
    else:
        raise AssertionError("stale last cursor should fail")


def test_commit_selected_traversal_move_rejects_empty_selection() -> None:
    start = Node(
        planning_point_px=(10, 10),
        grid_center_px=(10, 10),
        obstacle=False,
        grid_row=0,
        grid_col=0,
    )
    traversal_state = _state_from_accessible_nodes([start], start)
    graph_access = _graph_access([[start]])

    try:
        commit_selected_traversal_move(
            last_cursor=_cursor(start),
            next_selection=CandidatePhaseSelection.empty(),
            fov_coverage_path=[(10.0, 10.0)],
            move_trace=[],
            traversal_state=traversal_state,
            graph_access=graph_access,
            previous_travel_angle=0.0,
            step_counter=1,
            local_residual_count=0,
        )
    except AssertionError as exc:
        assert "empty traversal selection" in str(exc)
    else:
        raise AssertionError("empty traversal selection should fail")
