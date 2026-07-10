from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from algorithms.channel_topology_graph.coverage_planning.coverage_lane_sweep.lane_sweep_geometry import (
    estimate_local_tangent,
)
from algorithms.channel_topology_graph.coverage_planning.coverage_lane_sweep.lane_sweep_specs import (
    smooth_center_reference_path,
)

from .territory_expansion import ExpandedTerritory


DEFAULT_GRID_SPACING_M = 1.0


@dataclass(frozen=True)
class DirectionGridResult:
    samples: tuple[dict[str, Any], ...]
    debug_info: dict[str, Any]


def normalize_undirected_angle(angle_rad: float) -> float:
    angle = float(angle_rad) % math.pi
    if angle < 0.0:
        angle += math.pi
    return float(angle)


def classify_axis_angle(axis_angle_rad: float) -> str:
    angle = normalize_undirected_angle(axis_angle_rad)
    horizontal_delta = min(abs(angle), abs(math.pi - angle))
    vertical_delta = abs(angle - 0.5 * math.pi)
    threshold = math.pi / 8.0
    if horizontal_delta <= threshold:
        return "horizontal"
    if vertical_delta <= threshold:
        return "vertical"
    return "diagonal"


def edge_reference_path(edge: Any) -> tuple[tuple[float, float], ...]:
    path = tuple((float(point[0]), float(point[1])) for point in tuple(edge.outer_path_rc or ()))
    if len(path) <= 2:
        return path
    return smooth_center_reference_path(path, window_radius=2)


def build_edge_references(graph_info: Any) -> dict[int, dict[str, Any]]:
    references: dict[int, dict[str, Any]] = {}
    for edge in graph_info.edges:
        edge_id = int(edge.edge_id)
        path = edge_reference_path(edge)
        if len(path) < 2:
            continue
        points = np.asarray(path, dtype=np.float64)
        tangents = tuple(estimate_local_tangent(path, idx) for idx in range(len(path)))
        references[edge_id] = {
            "path": path,
            "points": points,
            "tangents": tangents,
        }
    return references


def nearest_reference_index(points: np.ndarray, row: int, col: int) -> int:
    deltas = points - np.asarray((float(row), float(col)), dtype=np.float64)
    distances = np.sum(deltas * deltas, axis=1)
    return int(np.argmin(distances))


def build_direction_grid(
    *,
    geometry_result: Any,
    graph_info: Any,
    expanded: ExpandedTerritory,
    grid_spacing_m: float = DEFAULT_GRID_SPACING_M,
) -> DirectionGridResult:
    free_mask = np.where(np.asarray(geometry_result.free_mask) > 0, 255, 0).astype(np.uint8)
    labels = np.asarray(expanded.labels, dtype=np.int32)
    resolution_m_per_px = float(geometry_result.resolution_m_per_px)
    if resolution_m_per_px <= 0.0:
        raise ValueError("resolution_m_per_px must be positive")
    grid_spacing_px = max(1, int(round(float(grid_spacing_m) / resolution_m_per_px)))
    half_step_px = max(0, grid_spacing_px // 2)
    edge_refs = build_edge_references(graph_info)

    samples: list[dict[str, Any]] = []
    total_centers = 0
    skipped: dict[str, int] = {
        "outside_free": 0,
        "unassigned_edge": 0,
        "missing_edge_reference": 0,
    }
    height, width = free_mask.shape
    for row in range(half_step_px, height, grid_spacing_px):
        for col in range(half_step_px, width, grid_spacing_px):
            total_centers += 1
            if free_mask[row, col] == 0:
                skipped["outside_free"] += 1
                continue
            edge_id = int(labels[row, col])
            if edge_id < 0:
                skipped["unassigned_edge"] += 1
                continue
            reference = edge_refs.get(edge_id)
            if reference is None:
                skipped["missing_edge_reference"] += 1
                continue
            nearest_idx = nearest_reference_index(reference["points"], row, col)
            tangent_row, tangent_col = reference["tangents"][nearest_idx]
            axis_angle_rad = normalize_undirected_angle(math.atan2(float(tangent_row), float(tangent_col)))
            samples.append(
                {
                    "row": int(row),
                    "col": int(col),
                    "edge_id": int(edge_id),
                    "axis_angle_rad": float(axis_angle_rad),
                    "direction_vector_rc": [float(tangent_row), float(tangent_col)],
                    "confidence": 1.0,
                    "nearest_path_index": int(nearest_idx),
                    "axis_class": classify_axis_angle(axis_angle_rad),
                }
            )

    sample_count_by_edge: dict[int, int] = {}
    sample_count_by_axis_class: dict[str, int] = {"horizontal": 0, "vertical": 0, "diagonal": 0}
    for sample in samples:
        edge_id = int(sample["edge_id"])
        sample_count_by_edge[edge_id] = sample_count_by_edge.get(edge_id, 0) + 1
        axis_class = str(sample["axis_class"])
        sample_count_by_axis_class[axis_class] = sample_count_by_axis_class.get(axis_class, 0) + 1
    return DirectionGridResult(
        samples=tuple(samples),
        debug_info={
            "enabled": True,
            "method": "expanded_territory_edge_axis_grid",
            "direction_semantics": "undirected_axis_angle_rad_mod_pi",
            "grid_spacing_m": float(grid_spacing_m),
            "grid_spacing_px": int(grid_spacing_px),
            "total_grid_center_count": int(total_centers),
            "direction_sample_count": int(len(samples)),
            "direction_sample_ratio": float(len(samples) / total_centers) if total_centers else 0.0,
            "skipped_grid_center_count": {key: int(value) for key, value in skipped.items()},
            "sample_count_by_edge": {
                str(int(edge_id)): int(count)
                for edge_id, count in sorted(sample_count_by_edge.items())
            },
            "sample_count_by_axis_class": {
                key: int(value)
                for key, value in sorted(sample_count_by_axis_class.items())
            },
            "edge_reference_count": int(len(edge_refs)),
        },
    )


def direction_grid_to_axis_maps(
    direction_grid: DirectionGridResult,
    shape: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    axis_map = np.zeros(shape, dtype=np.float32)
    confidence_map = np.zeros(shape, dtype=np.float32)
    grid_spacing_px = max(1, int(direction_grid.debug_info.get("grid_spacing_px", 1)))
    half_step_px = max(1, grid_spacing_px // 2)
    height, width = shape
    for sample in direction_grid.samples:
        row = int(sample["row"])
        col = int(sample["col"])
        row0 = max(0, row - half_step_px)
        row1 = min(height, row + half_step_px)
        col0 = max(0, col - half_step_px)
        col1 = min(width, col + half_step_px)
        axis_map[row0:row1, col0:col1] = float(sample["axis_angle_rad"])
        confidence_map[row0:row1, col0:col1] = float(sample.get("confidence", 1.0))
    return axis_map, confidence_map
