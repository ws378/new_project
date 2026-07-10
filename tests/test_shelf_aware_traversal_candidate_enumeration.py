from __future__ import annotations

from dataclasses import dataclass, field

from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_candidate_enumeration import (
    list_global_fallback_candidates,
    list_normal_neighbor_candidates,
    list_revisit_bridge_candidates,
)


@dataclass
class FakeNode:
    stable_id: str
    obstacle: bool = False
    visited: bool = False
    visit_count: int = 0
    neighbors: list["FakeNode"] = field(default_factory=list)


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
class FakeGraphAccess:
    nodes: list[FakeNode]

    def node(self, cell_id: str) -> FakeNode:
        for node in self.nodes:
            if node.stable_id == str(cell_id):
                return node
            for neighbor in node.neighbors:
                if neighbor.stable_id == str(cell_id):
                    return neighbor
        raise AssertionError(f"missing fake node: {cell_id}")

    def accessible_neighbor_cell_ids(self, cell_id: str) -> tuple[str, ...]:
        node = self.node(cell_id)
        return tuple(str(neighbor.stable_id) for neighbor in node.neighbors if not neighbor.obstacle)

    def accessible_neighbors(self, node: FakeNode) -> list[FakeNode]:
        return [neighbor for neighbor in node.neighbors if not neighbor.obstacle]

    def cell_id_for_node(self, node: FakeNode) -> str:
        return str(node.stable_id)

    def unvisited_accessible_nodes(self, traversal_state: FakeTraversalState) -> list[FakeNode]:
        return [
            node
            for node in self.nodes
            if not node.obstacle and not traversal_state.is_visited_cell(node.stable_id)
        ]

    def unvisited_accessible_cell_ids(self, traversal_state: FakeTraversalState) -> list[str]:
        return [str(node.stable_id) for node in self.unvisited_accessible_nodes(traversal_state)]


def _ids(candidate_refs) -> list[str]:
    return [candidate_ref.cell_id for candidate_ref in candidate_refs]


def _candidate_cell_ids(candidate_refs) -> list[str]:
    return [candidate_ref.cell_id for candidate_ref in candidate_refs]


def test_normal_neighbor_candidates_preserve_neighbor_order_and_filter_only_unvisited_accessible() -> None:
    last = FakeNode("last")
    first = FakeNode("first")
    obstacle = FakeNode("obstacle", obstacle=True)
    visited = FakeNode("visited", visited=True)
    second = FakeNode("second")
    last.neighbors = [first, obstacle, visited, second]
    state = FakeTraversalState(visited_ids={"visited"})

    candidates = list_normal_neighbor_candidates(last.stable_id, traversal_state=state, graph_access=FakeGraphAccess([last]))

    assert _ids(candidates) == ["first", "second"]
    assert _candidate_cell_ids(candidates) == [first.stable_id, second.stable_id]


def test_normal_neighbor_candidates_use_traversal_state_instead_of_legacy_node_flag() -> None:
    last = FakeNode("last")
    legacy_visited_but_state_unvisited = FakeNode("legacy_visited_but_state_unvisited", visited=True)
    legacy_unvisited_but_state_visited = FakeNode("legacy_unvisited_but_state_visited", visited=False)
    last.neighbors = [legacy_visited_but_state_unvisited, legacy_unvisited_but_state_visited]
    state = FakeTraversalState(visited_ids={"legacy_unvisited_but_state_visited"})

    assert _ids(list_normal_neighbor_candidates(last.stable_id, traversal_state=state, graph_access=FakeGraphAccess([last]))) == [
        "legacy_visited_but_state_unvisited",
    ]


def test_revisit_bridge_candidates_preserve_neighbor_order_and_only_apply_visit_limit() -> None:
    last = FakeNode("last")
    first = FakeNode("first", visited=True, visit_count=0)
    obstacle = FakeNode("obstacle", obstacle=True, visit_count=0)
    under_limit = FakeNode("under_limit", visited=True, visit_count=2)
    at_limit = FakeNode("at_limit", visited=True, visit_count=3)
    never_visited = FakeNode("never_visited", visited=False, visit_count=0)
    last.neighbors = [first, obstacle, under_limit, at_limit, never_visited]
    state = FakeTraversalState(
        visit_counts={
            "first": 0,
            "under_limit": 2,
            "at_limit": 3,
            "never_visited": 0,
        }
    )

    assert _ids(
        list_revisit_bridge_candidates(last.stable_id, traversal_state=state, graph_access=FakeGraphAccess([last]), max_revisit_count=3)
    ) == [
        "first",
        "under_limit",
        "never_visited",
    ]


def test_revisit_bridge_candidates_use_traversal_state_visit_count() -> None:
    last = FakeNode("last")
    legacy_over_limit_but_state_under = FakeNode("legacy_over_limit_but_state_under", visit_count=9)
    legacy_under_limit_but_state_over = FakeNode("legacy_under_limit_but_state_over", visit_count=0)
    last.neighbors = [legacy_over_limit_but_state_under, legacy_under_limit_but_state_over]
    state = FakeTraversalState(
        visit_counts={
            "legacy_over_limit_but_state_under": 1,
            "legacy_under_limit_but_state_over": 4,
        }
    )

    assert _ids(
        list_revisit_bridge_candidates(last.stable_id, traversal_state=state, graph_access=FakeGraphAccess([last]), max_revisit_count=3)
    ) == [
        "legacy_over_limit_but_state_under",
    ]


def test_global_fallback_candidates_preserve_row_major_order_and_filter_unvisited_accessible() -> None:
    current_unvisited = FakeNode("current_unvisited")
    obstacle = FakeNode("obstacle", obstacle=True)
    visited = FakeNode("visited", visited=True)
    second = FakeNode("second")
    third = FakeNode("third")
    state = FakeTraversalState(visited_ids={"visited"})

    assert _ids(
        list_global_fallback_candidates(
            traversal_state=state,
            graph_access=FakeGraphAccess([current_unvisited, obstacle, visited, second, third]),
        )
    ) == [
        "current_unvisited",
        "second",
        "third",
    ]


def test_global_fallback_candidates_use_traversal_state_instead_of_legacy_node_flag() -> None:
    legacy_visited_but_state_unvisited = FakeNode("legacy_visited_but_state_unvisited", visited=True)
    legacy_unvisited_but_state_visited = FakeNode("legacy_unvisited_but_state_visited", visited=False)
    state = FakeTraversalState(visited_ids={"legacy_unvisited_but_state_visited"})

    assert _ids(
        list_global_fallback_candidates(
            traversal_state=state,
            graph_access=FakeGraphAccess([legacy_visited_but_state_unvisited, legacy_unvisited_but_state_visited]),
        )
    ) == ["legacy_visited_but_state_unvisited"]
