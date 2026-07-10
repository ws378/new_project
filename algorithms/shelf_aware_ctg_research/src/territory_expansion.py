from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from algorithms.channel_topology_graph.coverage_planning.coverage_lane_sweep.lane_regions import (
    build_node_polygon_mask,
    derive_outer_path_territory_pixels,
)


FOUR_NEIGHBORS: tuple[tuple[int, int], ...] = ((-1, 0), (0, -1), (0, 1), (1, 0))
DEAD_END_EDGE_TYPES = {"dead_end_one_side", "dead_end_both_sides"}


@dataclass(frozen=True)
class ExpandedTerritory:
    labels: np.ndarray
    pixel_count_by_edge: dict[int, int]
    expanded_edge_ids: tuple[int, ...]


def edge_territory_seed_map(geometry_result: Any, graph_info: Any) -> dict[int, list[tuple[int, int]]]:
    free_mask = np.where(np.asarray(geometry_result.free_mask) > 0, 255, 0).astype(np.uint8)
    node_polygon_mask = build_node_polygon_mask(free_mask.shape, graph_info.nodes)
    constrained_free_mask = np.where(node_polygon_mask > 0, 0, free_mask).astype(np.uint8)
    territories = derive_outer_path_territory_pixels(
        graph_info=graph_info,
        constrained_free_mask=constrained_free_mask,
    )
    return {
        int(edge_id): [tuple((int(row), int(col))) for row, col in tuple(points)]
        for edge_id, points in territories.items()
        if points
    }


def dead_end_edge_ids(graph_info: Any) -> set[int]:
    return {
        int(edge.edge_id)
        for edge in graph_info.edges
        if str(edge.edge_type or "") in DEAD_END_EDGE_TYPES
    }


def flood_fill_edge_seed(
    *,
    free_mask: np.ndarray,
    labels: np.ndarray,
    edge_id: int,
    seeds: list[tuple[int, int]],
) -> None:
    height, width = free_mask.shape
    queue: deque[tuple[int, int]] = deque()
    for row, col in seeds:
        if free_mask[row, col] == 0:
            continue
        if labels[row, col] not in (-1, edge_id):
            continue
        labels[row, col] = edge_id
        queue.append((row, col))

    while queue:
        row, col = queue.popleft()
        for d_row, d_col in FOUR_NEIGHBORS:
            next_row = row + d_row
            next_col = col + d_col
            if next_row < 0 or next_row >= height or next_col < 0 or next_col >= width:
                continue
            if free_mask[next_row, next_col] == 0 or labels[next_row, next_col] != -1:
                continue
            labels[next_row, next_col] = edge_id
            queue.append((next_row, next_col))


def expand_dead_end_territories(geometry_result: Any, graph_info: Any, _lane_info: tuple[dict[str, Any], ...]) -> ExpandedTerritory:
    free_mask = np.where(np.asarray(geometry_result.free_mask) > 0, 255, 0).astype(np.uint8)
    labels = np.full(free_mask.shape, -1, dtype=np.int32)
    seeds_by_edge = edge_territory_seed_map(geometry_result, graph_info)
    expandable_edge_ids = dead_end_edge_ids(graph_info)

    for edge_id, seeds in seeds_by_edge.items():
        for row, col in seeds:
            if free_mask[row, col] > 0 and labels[row, col] == -1:
                labels[row, col] = int(edge_id)

    for edge_id in sorted(expandable_edge_ids):
        flood_fill_edge_seed(
            free_mask=free_mask,
            labels=labels,
            edge_id=int(edge_id),
            seeds=seeds_by_edge.get(int(edge_id), []),
        )

    pixel_count_by_edge: dict[int, int] = {}
    for edge_id in sorted(int(item) for item in np.unique(labels) if int(item) >= 0):
        pixel_count_by_edge[int(edge_id)] = int(np.count_nonzero(labels == int(edge_id)))
    return ExpandedTerritory(
        labels=labels,
        pixel_count_by_edge=pixel_count_by_edge,
        expanded_edge_ids=tuple(sorted(expandable_edge_ids)),
    )
