from __future__ import annotations

from dataclasses import dataclass, field

from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_reachability import (
    count_frontier_reachability,
    count_local_unvisited_nodes,
)


@dataclass
class FakeNode:
    stable_id: str
    obstacle: bool = False
    visited: bool = False
    neighbors: list["FakeNode"] = field(default_factory=list)


@dataclass
class FakeTraversalState:
    visited_ids: set[str] = field(default_factory=set)

    def is_visited_node(self, node: FakeNode) -> bool:
        raise AssertionError("生产遍历状态查询必须使用 cell id 口径")

    def is_visited_cell(self, cell_id: str) -> bool:
        return str(cell_id) in self.visited_ids


class FakeGraphAccess:
    def __init__(self, nodes: list[FakeNode]) -> None:
        self.nodes = nodes

    def node(self, cell_id: str) -> FakeNode:
        for node in self.nodes:
            if node.stable_id == str(cell_id):
                return node
        raise AssertionError(f"missing fake node: {cell_id}")

    def accessible_neighbor_cell_ids(self, cell_id: str) -> tuple[str, ...]:
        node = self.node(cell_id)
        return tuple(str(neighbor.stable_id) for neighbor in node.neighbors if not neighbor.obstacle)

    def accessible_neighbors(self, node: FakeNode) -> list[FakeNode]:
        return [neighbor for neighbor in node.neighbors if not neighbor.obstacle]

    def cell_id_for_node(self, node: FakeNode) -> str:
        return str(node.stable_id)


def _link(left: FakeNode, right: FakeNode) -> None:
    left.neighbors.append(right)
    right.neighbors.append(left)


def test_frontier_reachability_counts_unvisited_neighbors_beyond_start_and_skips_obstacles() -> None:
    start = FakeNode("start", visited=True)
    visited_bridge = FakeNode("visited_bridge", visited=True)
    unvisited_frontier = FakeNode("unvisited_frontier")
    obstacle = FakeNode("obstacle", obstacle=True)
    blocked = FakeNode("blocked")
    _link(start, visited_bridge)
    _link(visited_bridge, unvisited_frontier)
    _link(start, obstacle)
    _link(obstacle, blocked)
    state = FakeTraversalState(visited_ids={"start", "visited_bridge"})
    graph_access = FakeGraphAccess([start, visited_bridge, unvisited_frontier, obstacle, blocked])

    assert count_frontier_reachability(start.stable_id, 0, traversal_state=state, graph_access=graph_access) == 0
    assert count_frontier_reachability(start.stable_id, 1, traversal_state=state, graph_access=graph_access) == 0
    assert count_frontier_reachability(start.stable_id, 2, traversal_state=state, graph_access=graph_access) == 1


def test_frontier_reachability_uses_cell_id_seen_set_for_cycles() -> None:
    start = FakeNode("start", visited=True)
    first = FakeNode("first")
    second = FakeNode("second")
    _link(start, first)
    _link(first, second)
    _link(second, start)
    state = FakeTraversalState()
    graph_access = FakeGraphAccess([start, first, second])

    assert count_frontier_reachability(start.stable_id, 3, traversal_state=state, graph_access=graph_access) == 2


def test_frontier_reachability_uses_traversal_state_instead_of_legacy_node_flag() -> None:
    start = FakeNode("start", visited=True)
    legacy_visited_but_state_unvisited = FakeNode("legacy_visited_but_state_unvisited", visited=True)
    legacy_unvisited_but_state_visited = FakeNode("legacy_unvisited_but_state_visited", visited=False)
    _link(start, legacy_visited_but_state_unvisited)
    _link(start, legacy_unvisited_but_state_visited)
    state = FakeTraversalState(visited_ids={"start", "legacy_unvisited_but_state_visited"})

    assert count_frontier_reachability(
        start.stable_id,
        1,
        traversal_state=state,
        graph_access=FakeGraphAccess([start, legacy_visited_but_state_unvisited, legacy_unvisited_but_state_visited]),
    ) == 1


def test_local_unvisited_count_excludes_start_node_and_counts_unvisited_nodes_within_depth() -> None:
    start = FakeNode("start")
    first = FakeNode("first")
    visited = FakeNode("visited", visited=True)
    second = FakeNode("second")
    obstacle = FakeNode("obstacle", obstacle=True)
    blocked = FakeNode("blocked")
    _link(start, first)
    _link(start, visited)
    _link(first, second)
    _link(start, obstacle)
    _link(obstacle, blocked)
    state = FakeTraversalState(visited_ids={"visited"})
    graph_access = FakeGraphAccess([start, first, visited, second, obstacle, blocked])

    assert count_local_unvisited_nodes(start.stable_id, 0, traversal_state=state, graph_access=graph_access) == 0
    assert count_local_unvisited_nodes(start.stable_id, 1, traversal_state=state, graph_access=graph_access) == 1
    assert count_local_unvisited_nodes(start.stable_id, 2, traversal_state=state, graph_access=graph_access) == 2


def test_local_unvisited_count_uses_cell_id_seen_set_for_cycles() -> None:
    start = FakeNode("start")
    first = FakeNode("first")
    second = FakeNode("second")
    _link(start, first)
    _link(first, second)
    _link(second, start)
    state = FakeTraversalState()
    graph_access = FakeGraphAccess([start, first, second])

    assert count_local_unvisited_nodes(start.stable_id, 3, traversal_state=state, graph_access=graph_access) == 2


def test_local_unvisited_count_uses_traversal_state_instead_of_legacy_node_flag() -> None:
    start = FakeNode("start")
    legacy_visited_but_state_unvisited = FakeNode("legacy_visited_but_state_unvisited", visited=True)
    legacy_unvisited_but_state_visited = FakeNode("legacy_unvisited_but_state_visited", visited=False)
    _link(start, legacy_visited_but_state_unvisited)
    _link(start, legacy_unvisited_but_state_visited)
    state = FakeTraversalState(visited_ids={"legacy_unvisited_but_state_visited"})

    assert count_local_unvisited_nodes(
        start.stable_id,
        1,
        traversal_state=state,
        graph_access=FakeGraphAccess([start, legacy_visited_but_state_unvisited, legacy_unvisited_but_state_visited]),
    ) == 1
