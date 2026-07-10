from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.candidate_scoring import (
    CandidateScoreBreakdown,
    CandidateScoringContext,
    CandidateScoringGeometry,
    evaluate_candidate_score_for_geometry,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import (
    PlannerConfig,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_scoring_context import (
    TraversalScoringContext,
    build_traversal_scoring_context,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_phase_selectors import (
    select_global_fallback_phase,
    select_normal_neighbor_phase,
    select_revisit_bridge_phase,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_phase_query import (
    build_traversal_phase_query_context,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_ref import (
    TraversalCandidateRef,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_roles import (
    MOVE_SOURCE_GLOBAL_FALLBACK,
    MOVE_SOURCE_NORMAL_NEIGHBOR,
    MOVE_SOURCE_REVISIT_BRIDGE,
)


_FAKE_NODE_REGISTRY: dict[str, "FakeNode"] = {}


@dataclass
class FakeNode:
    stable_id: str
    planning_point_px: tuple[int, int]
    obstacle: bool = False
    visited: bool = False
    visit_count: int = 0
    neighbors: list["FakeNode"] = field(default_factory=list)
    grid_row: int = 0
    grid_col: int = 0
    grid_center_px: tuple[int, int] | None = None
    obstacle_ratio: float | None = None
    obstacle_ratio_filtered: bool = False

    def __post_init__(self) -> None:
        if self.grid_center_px is None:
            self.grid_center_px = self.planning_point_px
        _FAKE_NODE_REGISTRY[str(self.stable_id)] = self

    @property
    def adjusted_from_grid_center_px(self) -> bool:
        return self.planning_point_px != self.grid_center_px

    def count_non_obstacle_neighbors(self) -> int:
        return sum(1 for neighbor in self.neighbors if not neighbor.obstacle)


@dataclass
class FakeTraversalState:
    visited_ids: set[str] = field(default_factory=set)
    visit_counts: dict[str, int] = field(default_factory=dict)

    def is_visited_node(self, node: FakeNode) -> bool:
        raise AssertionError("生产遍历状态查询必须使用 cell id 口径")

    def is_visited_cell(self, cell_id: str) -> bool:
        return str(cell_id) in self.visited_ids

    def visit_count_for_node(self, node: FakeNode) -> int:
        raise AssertionError("生产遍历状态查询必须使用 cell id 口径")

    def visit_count_for_cell(self, cell_id: str) -> int:
        return int(self.visit_counts.get(str(cell_id), 0))


@dataclass
class FakeCell:
    cell_id: str
    grid_row: int
    grid_col: int
    grid_center_px: tuple[int, int]
    planning_point_px: tuple[int, int]
    obstacle: bool
    obstacle_ratio: float | None
    obstacle_ratio_filtered: bool
    adjusted_from_grid_center_px: bool
    generated_planning_point_px: tuple[int, int]
    generation_offset_from_grid_center_px: tuple[int, int]
    generation_offset_distance_px: float
    generation_mode: str
    generation_status: str
    endpoint_alignment_applied: bool
    endpoint_alignment_offset_px: tuple[int, int]
    neighbor_cell_ids: tuple[str, ...]
    accessible_neighbor_cell_ids: tuple[str, ...]


@dataclass
class FakeGraphAccess:
    nodes: list[FakeNode] = field(default_factory=list)
    graph_points_by_id: dict[str, tuple[int, int]] = field(default_factory=dict)
    graph_cell_ids_by_stable_id: dict[str, str] = field(default_factory=dict)

    def _graph_cell_id_for_node(self, node: FakeNode) -> str:
        return str(self.graph_cell_ids_by_stable_id.get(node.stable_id, node.stable_id))

    def node(self, cell_id: str) -> FakeNode:
        for node in self.nodes:
            if self._graph_cell_id_for_node(node) == str(cell_id):
                return node
            for neighbor in node.neighbors:
                if self._graph_cell_id_for_node(neighbor) == str(cell_id):
                    return neighbor
        for stable_id, graph_cell_id in self.graph_cell_ids_by_stable_id.items():
            if str(graph_cell_id) == str(cell_id) and str(stable_id) in _FAKE_NODE_REGISTRY:
                return _FAKE_NODE_REGISTRY[str(stable_id)]
        if str(cell_id) in _FAKE_NODE_REGISTRY:
            return _FAKE_NODE_REGISTRY[str(cell_id)]
        raise AssertionError(f"missing fake node: {cell_id}")

    def _cell_for_node(self, node: FakeNode) -> FakeCell:
        planning_point_px = self._planning_point_px_for_node(node)
        neighbor_ids = tuple(self._graph_cell_id_for_node(neighbor) for neighbor in node.neighbors)
        accessible_neighbor_ids = tuple(
            self._graph_cell_id_for_node(neighbor) for neighbor in node.neighbors if not neighbor.obstacle
        )
        generation_offset_from_grid_center_px = (
            int(planning_point_px[0] - node.grid_center_px[0]),
            int(planning_point_px[1] - node.grid_center_px[1]),
        )
        return FakeCell(
            cell_id=self._graph_cell_id_for_node(node),
            grid_row=int(node.grid_row),
            grid_col=int(node.grid_col),
            grid_center_px=(int(node.grid_center_px[0]), int(node.grid_center_px[1])),
            planning_point_px=(int(planning_point_px[0]), int(planning_point_px[1])),
            obstacle=bool(node.obstacle),
            obstacle_ratio=node.obstacle_ratio,
            obstacle_ratio_filtered=bool(node.obstacle_ratio_filtered),
            adjusted_from_grid_center_px=bool(planning_point_px != node.grid_center_px),
            generated_planning_point_px=(int(planning_point_px[0]), int(planning_point_px[1])),
            generation_offset_from_grid_center_px=generation_offset_from_grid_center_px,
            generation_offset_distance_px=float(math.hypot(
                generation_offset_from_grid_center_px[0],
                generation_offset_from_grid_center_px[1],
            )),
            generation_mode="test_graph_access",
            generation_status="test_graph_cell",
            endpoint_alignment_applied=False,
            endpoint_alignment_offset_px=(0, 0),
            neighbor_cell_ids=neighbor_ids,
            accessible_neighbor_cell_ids=accessible_neighbor_ids,
        )

    def cell(self, cell_id: str) -> FakeCell:
        return self._cell_for_node(self.node(cell_id))

    def _planning_point_px_for_node(self, node: FakeNode) -> tuple[int, int]:
        return self.graph_points_by_id.get(node.stable_id, node.planning_point_px)

    def planning_point_px_for_cell(self, cell_id: str) -> tuple[int, int]:
        if str(cell_id) in self.graph_points_by_id:
            return self.graph_points_by_id[str(cell_id)]
        return self._planning_point_px_for_node(self.node(cell_id))

    def accessible_neighbor_cell_ids(self, cell_id: str) -> tuple[str, ...]:
        return self.cell(cell_id).accessible_neighbor_cell_ids

    def unvisited_accessible_cell_ids(self, traversal_state: FakeTraversalState) -> list[str]:
        return [
            self._graph_cell_id_for_node(node)
            for node in self.nodes
            if not node.obstacle and not traversal_state.is_visited_cell(self._graph_cell_id_for_node(node))
        ]


def _empty_maps() -> tuple[np.ndarray, np.ndarray]:
    return np.zeros((4, 4), dtype=np.float32), np.zeros((4, 4), dtype=np.float32)


def _ref(node: FakeNode) -> TraversalCandidateRef:
    return TraversalCandidateRef(cell_id=node.stable_id)


def _context(
    *,
    config: PlannerConfig,
    point_path: list[tuple[float, float]] | None = None,
    coverage_width_px: int = 8,
    previous_travel_angle: float = 0.0,
    map_resolution: float = 0.05,
    local_residual_count: int = 0,
    history_clearance_index=None,
) -> TraversalScoringContext:
    local_direction_map, local_direction_confidence = _empty_maps()
    edge_label_map = np.ones((4, 4), dtype=np.int32)
    return TraversalScoringContext(
        point_path=[(0.0, 0.0)] if point_path is None else point_path,
        coverage_width_px=coverage_width_px,
        previous_travel_angle=previous_travel_angle,
        map_resolution=map_resolution,
        config=config,
        local_direction_map=local_direction_map,
        local_direction_confidence=local_direction_confidence,
        edge_label_map=edge_label_map,
        local_residual_count=local_residual_count,
        history_clearance_index=history_clearance_index,
    )


def _query_context(*, traversal_state: FakeTraversalState, graph_access: FakeGraphAccess, context: TraversalScoringContext):
    return build_traversal_phase_query_context(
        traversal_state=traversal_state,
        graph_access=graph_access,
        strategy=context.config.strategy,
    )


def _scoring_context(context: TraversalScoringContext, *, is_global_fallback: bool) -> CandidateScoringContext:
    return CandidateScoringContext(
        point_path=context.point_path,
        coverage_width_px=context.coverage_width_px,
        previous_travel_angle=context.previous_travel_angle,
        map_resolution=context.map_resolution,
        is_global_fallback=is_global_fallback,
        turn_constraint=context.config.turn_constraint,
        local_direction_map=context.local_direction_map,
        local_direction_confidence=context.local_direction_confidence,
        local_direction_cfg=context.config.local_direction,
        edge_label_map=context.edge_label_map,
        ctg_guidance_cfg=context.config.ctg_guidance,
        strategy_cfg=context.config.strategy,
        local_residual_count=context.local_residual_count,
        history_clearance_index=context.history_clearance_index,
    )


def _assert_scoring_context_matches(
    scoring_context: CandidateScoringContext,
    traversal_context: TraversalScoringContext,
    *,
    is_global_fallback: bool,
) -> None:
    assert scoring_context.point_path is traversal_context.point_path
    assert scoring_context.coverage_width_px == traversal_context.coverage_width_px
    assert scoring_context.previous_travel_angle == traversal_context.previous_travel_angle
    assert scoring_context.map_resolution == traversal_context.map_resolution
    assert scoring_context.is_global_fallback is is_global_fallback
    assert scoring_context.turn_constraint is traversal_context.config.turn_constraint
    assert scoring_context.local_direction_map is traversal_context.local_direction_map
    assert scoring_context.local_direction_confidence is traversal_context.local_direction_confidence
    assert scoring_context.local_direction_cfg is traversal_context.config.local_direction
    assert scoring_context.edge_label_map is traversal_context.edge_label_map
    assert scoring_context.ctg_guidance_cfg is traversal_context.config.ctg_guidance
    assert scoring_context.strategy_cfg is traversal_context.config.strategy
    assert scoring_context.local_residual_count == traversal_context.local_residual_count
    assert scoring_context.history_clearance_index is traversal_context.history_clearance_index


def test_build_traversal_scoring_context_preserves_explicit_inputs() -> None:
    config = PlannerConfig()
    point_path = [(1.0, 2.0), (3.0, 4.0)]
    local_direction_map, local_direction_confidence = _empty_maps()
    edge_label_map = np.ones((4, 4), dtype=np.int32)
    history_clearance_index = object()

    context = build_traversal_scoring_context(
        point_path=point_path,
        coverage_width_px=17,
        previous_travel_angle=1.25,
        map_resolution=0.08,
        config=config,
        local_direction_map=local_direction_map,
        local_direction_confidence=local_direction_confidence,
        edge_label_map=edge_label_map,
        local_residual_count=9,
        history_clearance_index=history_clearance_index,
    )

    assert context.point_path is point_path
    assert context.coverage_width_px == 17
    assert context.previous_travel_angle == 1.25
    assert context.map_resolution == 0.08
    assert context.config is config
    assert context.local_direction_map is local_direction_map
    assert context.local_direction_confidence is local_direction_confidence
    assert context.edge_label_map is edge_label_map
    assert context.local_residual_count == 9
    assert context.history_clearance_index is history_clearance_index

    no_history_context = build_traversal_scoring_context(
        point_path=point_path,
        coverage_width_px=17,
        previous_travel_angle=1.25,
        map_resolution=0.08,
        config=config,
        local_direction_map=local_direction_map,
        local_direction_confidence=local_direction_confidence,
        edge_label_map=edge_label_map,
        local_residual_count=9,
    )
    assert no_history_context.history_clearance_index is None


def test_normal_neighbor_phase_preserves_order_and_strict_energy_tie(monkeypatch):
    last_node = FakeNode("last", (0, 0))
    first = FakeNode("first", (1, 0))
    second = FakeNode("second", (2, 0))
    third = FakeNode("third", (3, 0))
    calls: list[str] = []
    energies = {"first": 5.0, "second": 3.0, "third": 3.0}
    config = PlannerConfig()
    context = _context(
        config=config,
        point_path=[(0.0, 0.0), (2.0, 0.0)],
        coverage_width_px=9,
        previous_travel_angle=0.75,
        map_resolution=0.1,
        local_residual_count=4,
    )

    def fake_score(geometry, **kwargs):
        candidate = first
        for node in (first, second, third):
            if geometry.candidate_point_px == node.planning_point_px:
                candidate = node
                break
        calls.append(candidate.stable_id)
        assert isinstance(geometry, CandidateScoringGeometry)
        assert geometry.location_point_px == last_node.planning_point_px
        assert geometry.candidate_point_px == candidate.planning_point_px
        _assert_scoring_context_matches(kwargs["context"], context, is_global_fallback=False)
        return CandidateScoreBreakdown(
            total_energy=energies[candidate.stable_id],
            components={"test_energy": energies[candidate.stable_id]},
            rejected_reasons=(),
            accepted=True,
            component_sum_valid=True,
        )

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_evaluation.evaluate_candidate_score_for_geometry",
        fake_score,
    )
    traversal_state = FakeTraversalState()
    graph_access = FakeGraphAccess()
    selection = select_normal_neighbor_phase(
        last_cell_id=last_node.stable_id,
        not_visited_neighbors=[_ref(first), _ref(second), _ref(third)],
        query_context=_query_context(traversal_state=traversal_state, graph_access=graph_access, context=context),
        context=context,
    )

    assert calls == ["first", "second", "third"]
    assert selection.selected_cell_id == second.stable_id
    assert selection.move_source == MOVE_SOURCE_NORMAL_NEIGHBOR
    assert selection.selected_energy == 3.0
    assert selection.phase_summary.candidate_count == 3
    assert selection.phase_summary.energy_evaluated_candidate_count == 3
    assert selection.phase_summary.accepted_candidate_count == 3
    assert selection.phase_summary.candidate_rank == 1
    assert [record.cell_id for record in selection.candidate_records] == ["first", "second", "third"]
    assert [record.total_energy for record in selection.candidate_records] == [5.0, 3.0, 3.0]
    assert [dict(record.score_components) for record in selection.candidate_records] == [
        {"test_energy": 5.0},
        {"test_energy": 3.0},
        {"test_energy": 3.0},
    ]
    assert all(record.score_component_sum_valid for record in selection.candidate_records)
    assert [record.rank_in_phase for record in selection.candidate_records] == [3, 1, 1]
    assert all(record.accepted for record in selection.candidate_records)
    assert all(record.move_source == MOVE_SOURCE_NORMAL_NEIGHBOR for record in selection.candidate_records)


def test_normal_neighbor_phase_uses_graph_cell_id_for_selection_and_records(monkeypatch):
    last_node = FakeNode("legacy_last", (900, 900))
    candidate = FakeNode("legacy_candidate", (901, 901))
    context = _context(config=PlannerConfig())

    def fake_score(geometry, **kwargs):
        assert geometry.location_point_px == (0, 0)
        assert geometry.candidate_point_px == (10, 0)
        return CandidateScoreBreakdown(
            total_energy=1.0,
            components={"test_energy": 1.0},
            rejected_reasons=(),
            accepted=True,
            component_sum_valid=True,
        )

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_evaluation.evaluate_candidate_score_for_geometry",
        fake_score,
    )
    graph_access = FakeGraphAccess(
        graph_cell_ids_by_stable_id={
            "legacy_last": "graph_last",
            "legacy_candidate": "graph_candidate",
        },
        graph_points_by_id={
            "graph_last": (0, 0),
            "graph_candidate": (10, 0),
        },
    )
    traversal_state = FakeTraversalState()
    selection = select_normal_neighbor_phase(
        last_cell_id="graph_last",
        not_visited_neighbors=[TraversalCandidateRef(cell_id="graph_candidate")],
        query_context=_query_context(traversal_state=traversal_state, graph_access=graph_access, context=context),
        context=context,
    )

    assert selection.selected_cell_id == "graph_candidate"
    assert [record.cell_id for record in selection.candidate_records] == ["graph_candidate"]


def test_normal_neighbor_phase_rejects_candidate_cell_id_missing_from_graph():
    last_node = FakeNode("last", (0, 0))
    candidate = FakeNode("legacy_candidate", (10, 0))

    try:
        traversal_state = FakeTraversalState()
        graph_access = FakeGraphAccess(
            graph_cell_ids_by_stable_id={
                "legacy_candidate": "graph_candidate",
            },
        )
        context = _context(config=PlannerConfig())
        select_normal_neighbor_phase(
            last_cell_id=last_node.stable_id,
            not_visited_neighbors=[TraversalCandidateRef(cell_id="wrong_cell")],
            query_context=_query_context(traversal_state=traversal_state, graph_access=graph_access, context=context),
            context=context,
        )
    except AssertionError as exc:
        assert "missing fake node: wrong_cell" in str(exc)
    else:
        raise AssertionError("candidate ref missing graph cell should fail")


def test_normal_neighbor_phase_scores_with_graph_snapshot_when_legacy_shell_geometry_is_stale():
    last_node = FakeNode("last", (900, 900))
    candidate = FakeNode("candidate", (901, 901))
    config = PlannerConfig()
    context = _context(
        config=config,
        point_path=[(0.0, 0.0)],
        coverage_width_px=8,
        previous_travel_angle=0.0,
        map_resolution=0.05,
        local_residual_count=0,
    )
    graph_access = FakeGraphAccess(
        nodes=[last_node, candidate],
        graph_points_by_id={
            "last": (0, 0),
            "candidate": (8, 0),
        }
    )

    traversal_state = FakeTraversalState()
    selection = select_normal_neighbor_phase(
        last_cell_id=last_node.stable_id,
        not_visited_neighbors=[TraversalCandidateRef(cell_id=candidate.stable_id)],
        query_context=_query_context(traversal_state=traversal_state, graph_access=graph_access, context=context),
        context=context,
    )
    expected_score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points((0, 0), (8, 0)),
        context=_scoring_context(context, is_global_fallback=False),
    )
    legacy_shell_score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points((0, 0), candidate.planning_point_px),
        context=_scoring_context(context, is_global_fallback=False),
    )

    assert selection.has_selection
    assert selection.selected_cell_id == candidate.stable_id
    assert selection.selected_energy == expected_score.total_energy
    assert selection.selected_energy != legacy_shell_score.total_energy


def test_candidate_local_residual_query_is_skipped_when_continue_weight_disabled(monkeypatch):
    last_node = FakeNode("last", (0, 0))
    candidate = FakeNode("candidate", (1, 0))
    config = PlannerConfig()
    config.strategy.local_residual_continue_weight = 0.0
    context = _context(config=config)

    def forbidden_residual_query(*_args, **_kwargs):
        raise AssertionError("local residual BFS should be skipped when continue weight is disabled")

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_phase_query.count_local_unvisited_nodes",
        forbidden_residual_query,
    )
    traversal_state = FakeTraversalState()
    graph_access = FakeGraphAccess()
    selection = select_normal_neighbor_phase(
        last_cell_id=last_node.stable_id,
        not_visited_neighbors=[_ref(candidate)],
        query_context=_query_context(traversal_state=traversal_state, graph_access=graph_access, context=context),
        context=context,
    )

    assert selection.has_selection
    assert selection.candidate_records[0].accepted is True


def test_normal_neighbor_phase_preserves_rejected_records_when_no_selection(monkeypatch):
    last_node = FakeNode("last", (0, 0))
    rejected = FakeNode("rejected", (1, 0))
    config = PlannerConfig()
    context = _context(config=config)

    def fake_score(geometry, **_kwargs):
        assert geometry.location_point_px == last_node.planning_point_px
        assert geometry.candidate_point_px == rejected.planning_point_px
        return CandidateScoreBreakdown(
            total_energy=None,
            components={},
            rejected_reasons=("shape_constraint",),
            accepted=False,
            component_sum_valid=False,
        )

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_evaluation.evaluate_candidate_score_for_geometry",
        fake_score,
    )
    traversal_state = FakeTraversalState()
    graph_access = FakeGraphAccess()
    selection = select_normal_neighbor_phase(
        last_cell_id=last_node.stable_id,
        not_visited_neighbors=[_ref(rejected)],
        query_context=_query_context(traversal_state=traversal_state, graph_access=graph_access, context=context),
        context=context,
    )

    assert not selection.has_selection
    assert selection.phase_summary.candidate_count == 1
    assert selection.phase_summary.energy_evaluated_candidate_count == 1
    assert selection.phase_summary.accepted_candidate_count == 0
    assert [record.cell_id for record in selection.candidate_records] == ["rejected"]
    assert selection.candidate_records[0].accepted is False
    assert selection.candidate_records[0].rejected_reasons == ("shape_constraint",)


def test_normal_neighbor_phase_record_energy_matches_geometry_score():
    last_node = FakeNode("last", (0, 0))
    candidate = FakeNode("candidate", (8, 0))
    config = PlannerConfig()
    context = _context(
        config=config,
        point_path=[(0.0, 0.0)],
        coverage_width_px=8,
        previous_travel_angle=0.0,
        map_resolution=0.05,
        local_residual_count=0,
    )

    traversal_state = FakeTraversalState()
    graph_access = FakeGraphAccess()
    selection = select_normal_neighbor_phase(
        last_cell_id=last_node.stable_id,
        not_visited_neighbors=[_ref(candidate)],
        query_context=_query_context(traversal_state=traversal_state, graph_access=graph_access, context=context),
        context=context,
    )
    expected_score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points(last_node.planning_point_px, candidate.planning_point_px),
        context=_scoring_context(context, is_global_fallback=False),
    )

    assert selection.has_selection
    assert selection.candidate_records[0].accepted is True
    assert expected_score.accepted is True
    assert selection.candidate_records[0].total_energy == expected_score.total_energy
    assert selection.selected_energy == expected_score.total_energy


def test_normal_neighbor_phase_scores_with_graph_snapshot_geometry_when_node_points_are_stale():
    last_node = FakeNode("last", (900, 900))
    candidate = FakeNode("candidate", (901, 901))
    config = PlannerConfig()
    context = _context(
        config=config,
        point_path=[(0.0, 0.0)],
        coverage_width_px=8,
        previous_travel_angle=0.0,
        map_resolution=0.05,
        local_residual_count=0,
    )
    graph_access = FakeGraphAccess(
        nodes=[last_node, candidate],
        graph_points_by_id={
            "last": (0, 0),
            "candidate": (8, 0),
        }
    )

    traversal_state = FakeTraversalState()
    selection = select_normal_neighbor_phase(
        last_cell_id=last_node.stable_id,
        not_visited_neighbors=[_ref(candidate)],
        query_context=_query_context(traversal_state=traversal_state, graph_access=graph_access, context=context),
        context=context,
    )
    expected_score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points((0, 0), (8, 0)),
        context=_scoring_context(context, is_global_fallback=False),
    )
    stale_node_score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points(last_node.planning_point_px, candidate.planning_point_px),
        context=_scoring_context(context, is_global_fallback=False),
    )

    assert selection.has_selection
    assert expected_score.accepted is True
    assert stale_node_score.accepted is True
    assert selection.selected_energy == expected_score.total_energy
    assert selection.candidate_records[0].total_energy == expected_score.total_energy
    assert selection.selected_energy != stale_node_score.total_energy


def test_normal_neighbor_phase_samples_guidance_maps_with_graph_snapshot_geometry():
    last_node = FakeNode("last", (900, 900))
    candidate = FakeNode("candidate", (901, 901))
    config = PlannerConfig()
    config.local_direction.enable = True
    config.local_direction.energy_weight = 7.0
    config.local_direction.min_confidence = 0.1
    config.ctg_guidance.enable = True
    config.ctg_guidance.same_edge_reward = 2.0
    config.ctg_guidance.edge_switch_penalty = 11.0

    local_direction_map = np.full((4, 4), math.pi / 2.0, dtype=np.float32)
    local_direction_confidence = np.ones((4, 4), dtype=np.float32)
    local_direction_map[0, 2] = 0.0
    edge_label_map = np.full((4, 4), 3, dtype=np.int32)
    edge_label_map[0, 0] = 7
    edge_label_map[0, 2] = 7
    context = TraversalScoringContext(
        point_path=[(0.0, 0.0)],
        coverage_width_px=8,
        previous_travel_angle=0.0,
        map_resolution=0.05,
        config=config,
        local_direction_map=local_direction_map,
        local_direction_confidence=local_direction_confidence,
        edge_label_map=edge_label_map,
        local_residual_count=0,
    )
    graph_access = FakeGraphAccess(
        nodes=[last_node, candidate],
        graph_points_by_id={
            "last": (0, 0),
            "candidate": (2, 0),
        }
    )

    traversal_state = FakeTraversalState()
    selection = select_normal_neighbor_phase(
        last_cell_id=last_node.stable_id,
        not_visited_neighbors=[_ref(candidate)],
        query_context=_query_context(traversal_state=traversal_state, graph_access=graph_access, context=context),
        context=context,
    )
    expected_score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points((0, 0), (2, 0)),
        context=_scoring_context(context, is_global_fallback=False),
    )
    stale_node_score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points(last_node.planning_point_px, candidate.planning_point_px),
        context=_scoring_context(context, is_global_fallback=False),
    )

    assert selection.has_selection
    assert expected_score.accepted is True
    assert stale_node_score.accepted is True
    assert selection.selected_energy == expected_score.total_energy
    assert selection.selected_energy != stale_node_score.total_energy
    score_components = dict(selection.candidate_records[0].score_components)
    assert score_components["local_direction_cost"] == 0.0
    assert score_components["ctg_same_edge_reward"] == -2.0


def test_revisit_bridge_phase_rejects_candidates_without_frontier_before_energy(monkeypatch):
    last_node = FakeNode("last", (0, 0))
    rejected = FakeNode("rejected", (1, 0), visit_count=1)
    accepted = FakeNode("accepted", (2, 0), visit_count=99)
    obstacle = FakeNode("obstacle", (3, 0), obstacle=True)
    over_limit = FakeNode("over_limit", (4, 0), visit_count=5)
    last_node.neighbors = [rejected, obstacle, accepted, over_limit]
    state_for_test = FakeTraversalState(
        visit_counts={
            "rejected": 1,
            "accepted": 2,
            "over_limit": 5,
        }
    )
    frontier_scores = {"rejected": 0, "accepted": 2}
    energy_calls: list[str] = []
    config = PlannerConfig()
    config.strategy.max_revisit_count = 3
    context = _context(
        config=config,
        coverage_width_px=11,
        previous_travel_angle=1.25,
        map_resolution=0.2,
        local_residual_count=6,
    )

    def fake_frontier(candidate_cell_id, _depth, *, traversal_state: FakeTraversalState, graph_access):
        assert traversal_state is state_for_test
        assert isinstance(graph_access, FakeGraphAccess)
        return frontier_scores[str(candidate_cell_id)]

    def fake_score(geometry, **kwargs):
        candidate = accepted
        assert isinstance(geometry, CandidateScoringGeometry)
        assert geometry.location_point_px == last_node.planning_point_px
        assert geometry.candidate_point_px == accepted.planning_point_px
        energy_calls.append(candidate.stable_id)
        _assert_scoring_context_matches(kwargs["context"], context, is_global_fallback=False)
        assert kwargs["revisit_frontier_score"] == 2
        assert kwargs["candidate_visit_count"] == 2
        return CandidateScoreBreakdown(
            total_energy=7.0,
            components={"test_energy": 7.0},
            rejected_reasons=(),
            accepted=True,
            component_sum_valid=True,
        )

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_phase_query.count_frontier_reachability",
        fake_frontier,
    )
    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_evaluation.evaluate_candidate_score_for_geometry",
        fake_score,
    )
    graph_access = FakeGraphAccess([last_node])
    selection = select_revisit_bridge_phase(
        last_cell_id=last_node.stable_id,
        query_context=_query_context(traversal_state=state_for_test, graph_access=graph_access, context=context),
        context=context,
    )

    assert energy_calls == ["accepted"]
    assert selection.selected_cell_id == accepted.stable_id
    assert selection.move_source == MOVE_SOURCE_REVISIT_BRIDGE
    assert selection.revisit_frontier_score == 2
    assert selection.phase_summary.candidate_count == 2
    assert selection.phase_summary.energy_evaluated_candidate_count == 1
    assert selection.phase_summary.accepted_candidate_count == 1
    assert selection.phase_summary.rejected_before_energy_count == 1
    assert [record.cell_id for record in selection.candidate_records] == ["rejected", "accepted"]
    assert selection.candidate_records[0].rejected_before_energy is True
    assert selection.candidate_records[0].rejected_reasons == ("no_unvisited_frontier",)
    assert selection.candidate_records[0].rank_in_phase is None
    assert selection.candidate_records[1].accepted is True
    assert selection.candidate_records[1].total_energy == 7.0
    assert selection.candidate_records[1].rank_in_phase == 1


def test_revisit_bridge_phase_scores_with_graph_snapshot_geometry_when_node_points_are_stale(monkeypatch):
    last_node = FakeNode("last", (900, 900))
    candidate = FakeNode("candidate", (901, 901), visit_count=1)
    last_node.neighbors = [candidate]
    config = PlannerConfig()
    config.strategy.max_revisit_count = 3
    context = _context(
        config=config,
        point_path=[(0.0, 0.0)],
        coverage_width_px=8,
        previous_travel_angle=0.0,
        map_resolution=0.05,
        local_residual_count=0,
    )
    graph_access = FakeGraphAccess(
        nodes=[last_node, candidate],
        graph_points_by_id={
            "last": (0, 0),
            "candidate": (8, 0),
        },
    )

    def fake_frontier(candidate_cell_id, _depth, *, traversal_state, graph_access):
        assert candidate_cell_id == candidate.stable_id
        return 2

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_phase_query.count_frontier_reachability",
        fake_frontier,
    )
    traversal_state = FakeTraversalState(visit_counts={candidate.stable_id: 1})
    selection = select_revisit_bridge_phase(
        last_cell_id=last_node.stable_id,
        query_context=_query_context(traversal_state=traversal_state, graph_access=graph_access, context=context),
        context=context,
    )
    expected_score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points((0, 0), (8, 0)),
        context=_scoring_context(context, is_global_fallback=False),
        candidate_visit_count=1,
        revisit_frontier_score=2,
    )
    stale_node_score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points(last_node.planning_point_px, candidate.planning_point_px),
        context=_scoring_context(context, is_global_fallback=False),
        candidate_visit_count=1,
        revisit_frontier_score=2,
    )

    assert selection.has_selection
    assert selection.selected_cell_id == candidate.stable_id
    assert expected_score.accepted is True
    assert stale_node_score.accepted is True
    assert selection.selected_energy == expected_score.total_energy
    assert selection.candidate_records[0].total_energy == expected_score.total_energy
    assert selection.selected_energy != stale_node_score.total_energy


def test_revisit_bridge_phase_preserves_pre_energy_records_when_no_selection(monkeypatch):
    last_node = FakeNode("last", (0, 0))
    rejected = FakeNode("rejected", (1, 0), visit_count=1)
    last_node.neighbors = [rejected]
    config = PlannerConfig()
    config.strategy.max_revisit_count = 3
    context = _context(config=config)

    def fake_frontier(candidate_cell_id, _depth, *, traversal_state, graph_access):
        return 0

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_phase_query.count_frontier_reachability",
        fake_frontier,
    )
    traversal_state = FakeTraversalState(visit_counts={neighbor.stable_id: neighbor.visit_count for neighbor in last_node.neighbors})
    graph_access = FakeGraphAccess([last_node])
    selection = select_revisit_bridge_phase(
        last_cell_id=last_node.stable_id,
        query_context=_query_context(traversal_state=traversal_state, graph_access=graph_access, context=context),
        context=context,
    )

    assert not selection.has_selection
    assert selection.phase_summary.candidate_count == 1
    assert selection.phase_summary.energy_evaluated_candidate_count == 0
    assert selection.phase_summary.accepted_candidate_count == 0
    assert selection.phase_summary.rejected_before_energy_count == 1
    assert [record.cell_id for record in selection.candidate_records] == ["rejected"]
    assert selection.candidate_records[0].rejected_before_energy is True
    assert selection.candidate_records[0].rejected_reasons == ("no_unvisited_frontier",)


def test_global_fallback_phase_selects_lowest_unvisited_node_and_writes_debug(monkeypatch):
    last_node = FakeNode("last", (0, 0), grid_row=0, grid_col=0, visited=True, visit_count=88)
    selected = FakeNode("selected", (1, 0), grid_row=0, grid_col=1, visited=True, visit_count=77)
    ignored_obstacle = FakeNode("ignored_obstacle", (2, 0), obstacle=True, grid_row=0, grid_col=2)
    ignored_visited = FakeNode("ignored_visited", (3, 0), visited=True, grid_row=0, grid_col=3)
    other = FakeNode("other", (0, 1), grid_row=1, grid_col=0)
    none_energy = FakeNode("none_energy", (1, 1), grid_row=1, grid_col=1)
    nodes = [[last_node, selected, ignored_obstacle, ignored_visited], [other, none_energy]]
    energies = {"last": 9.0, "selected": 2.0, "other": 5.0, "none_energy": None}
    calls: list[str] = []
    config = PlannerConfig()
    history_clearance_index = object()
    context = _context(
        config=config,
        point_path=[(0.0, 0.0), (1.0, 0.0)],
        coverage_width_px=13,
        previous_travel_angle=1.5,
        map_resolution=0.15,
        local_residual_count=1,
        history_clearance_index=history_clearance_index,
    )

    def fake_score(geometry, **kwargs):
        candidate = last_node
        for node in (last_node, selected, other, none_energy):
            if geometry.candidate_point_px == node.planning_point_px:
                candidate = node
                break
        calls.append(candidate.stable_id)
        assert isinstance(geometry, CandidateScoringGeometry)
        assert geometry.location_point_px == last_node.planning_point_px
        assert geometry.candidate_point_px == candidate.planning_point_px
        _assert_scoring_context_matches(kwargs["context"], context, is_global_fallback=True)
        energy = energies[candidate.stable_id]
        if energy is None:
            return CandidateScoreBreakdown(
                total_energy=None,
                components={},
                rejected_reasons=("shape_constraint",),
                accepted=False,
                component_sum_valid=False,
            )
        return CandidateScoreBreakdown(
            total_energy=energy,
            components={"test_energy": energy},
            rejected_reasons=(),
            accepted=True,
            component_sum_valid=True,
        )

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_evaluation.evaluate_candidate_score_for_geometry",
        fake_score,
    )
    traversal_state = FakeTraversalState(
        visited_ids={ignored_visited.stable_id},
        visit_counts={ignored_visited.stable_id: 1},
    )
    graph_access = FakeGraphAccess([last_node, selected, ignored_obstacle, ignored_visited, other, none_energy])
    result = select_global_fallback_phase(
        last_cell_id=last_node.stable_id,
        query_context=_query_context(traversal_state=traversal_state, graph_access=graph_access, context=context),
        context=context,
        step_counter=4,
        write_artifacts=True,
    )

    assert calls == ["last", "selected", "other", "none_energy"]
    assert result.selection.selected_cell_id == selected.stable_id
    assert result.selection.move_source == MOVE_SOURCE_GLOBAL_FALLBACK
    assert result.selection.selected_energy == 2.0
    assert result.selection.phase_summary.candidate_count == 4
    assert result.selection.phase_summary.energy_evaluated_candidate_count == 4
    assert result.selection.phase_summary.accepted_candidate_count == 3
    assert [record.cell_id for record in result.selection.candidate_records] == ["last", "selected", "other", "none_energy"]
    assert [record.rank_in_phase for record in result.selection.candidate_records] == [3, 1, 2, None]
    assert result.selection.candidate_records[-1].accepted is False
    assert result.selection.candidate_records[-1].rejected_reasons == ("shape_constraint",)
    assert result.debug_event is not None
    assert result.debug_event["step"] == 4
    assert result.debug_event["path_index_before_selection"] == 2
    assert result.debug_event["current_node"]["node_id"] == "last"
    assert result.debug_event["current_node"]["visited"] is False
    assert result.debug_event["current_node"]["visit_count"] == 0
    assert result.debug_event["local_residual_count"] == 1
    assert result.debug_event["unvisited_node_count_before_selection"] == 4
    assert result.debug_event["unvisited_node_ids_before_selection"] == ["last", "selected", "other", "none_energy"]
    assert result.debug_event["candidate_count"] == 3
    assert [item["node_id"] for item in result.debug_event["candidates"]] == ["selected", "other", "last"]
    assert result.debug_event["candidates"][0]["visited"] is False
    assert result.debug_event["candidates"][0]["visit_count"] == 0
    assert result.debug_event["selected_node_id"] == "selected"
    assert result.debug_event["selected_energy"] == 2.0


def test_global_fallback_phase_scores_with_graph_snapshot_geometry_when_node_points_are_stale():
    last_node = FakeNode("last", (900, 900), visited=True)
    candidate = FakeNode("candidate", (901, 901))
    config = PlannerConfig()
    config.strategy.fallback_jump_weight = 2.0
    config.strategy.fallback_heading_weight = 3.0
    context = _context(
        config=config,
        point_path=[(0.0, 0.0)],
        coverage_width_px=8,
        previous_travel_angle=0.0,
        map_resolution=0.05,
        local_residual_count=0,
    )
    graph_access = FakeGraphAccess(
        nodes=[last_node, candidate],
        graph_points_by_id={
            "last": (0, 0),
            "candidate": (8, 0),
        },
    )

    traversal_state = FakeTraversalState(visited_ids={"last"})
    result = select_global_fallback_phase(
        last_cell_id=last_node.stable_id,
        query_context=_query_context(traversal_state=traversal_state, graph_access=graph_access, context=context),
        context=context,
        step_counter=7,
        write_artifacts=False,
    )
    expected_score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points((0, 0), (8, 0)),
        context=_scoring_context(context, is_global_fallback=True),
    )
    stale_node_score = evaluate_candidate_score_for_geometry(
        CandidateScoringGeometry.from_points(last_node.planning_point_px, candidate.planning_point_px),
        context=_scoring_context(context, is_global_fallback=True),
    )

    assert result.selection.has_selection
    assert result.selection.selected_cell_id == candidate.stable_id
    assert expected_score.accepted is True
    assert stale_node_score.accepted is True
    assert result.selection.selected_energy == expected_score.total_energy
    assert result.selection.candidate_records == ()
    assert result.selection.selected_energy != stale_node_score.total_energy


def test_global_fallback_phase_preserves_records_when_no_candidate_is_accepted(monkeypatch):
    last_node = FakeNode("last", (0, 0), grid_row=0, grid_col=0)
    rejected = FakeNode("rejected", (1, 0), grid_row=0, grid_col=1)
    nodes = [[last_node, rejected]]
    config = PlannerConfig()
    context = _context(config=config, history_clearance_index=object())

    def fake_score(geometry, **_kwargs):
        assert geometry.location_point_px == last_node.planning_point_px
        return CandidateScoreBreakdown(
            total_energy=None,
            components={},
            rejected_reasons=("turn_constraint",),
            accepted=False,
            component_sum_valid=False,
        )

    monkeypatch.setattr(
        "algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_evaluation.evaluate_candidate_score_for_geometry",
        fake_score,
    )
    traversal_state = FakeTraversalState(
        visited_ids={node.stable_id for row in nodes for node in row if node.visited},
        visit_counts={node.stable_id: node.visit_count for row in nodes for node in row if node.visit_count > 0},
    )
    graph_access = FakeGraphAccess([last_node, rejected])
    result = select_global_fallback_phase(
        last_cell_id=last_node.stable_id,
        query_context=_query_context(traversal_state=traversal_state, graph_access=graph_access, context=context),
        context=context,
        step_counter=5,
        write_artifacts=True,
    )

    assert not result.selection.has_selection
    assert result.selection.phase_summary.candidate_count == 2
    assert result.selection.phase_summary.energy_evaluated_candidate_count == 2
    assert result.selection.phase_summary.accepted_candidate_count == 0
    assert [record.cell_id for record in result.selection.candidate_records] == ["last", "rejected"]
    assert all(record.rejected_reasons == ("turn_constraint",) for record in result.selection.candidate_records)
    assert result.debug_event is not None
    assert result.debug_event["candidate_count"] == 0
    assert result.debug_event["candidates"] == []
    assert result.debug_event["selected_node_id"] is None
    assert result.debug_event["selected_energy"] is None
