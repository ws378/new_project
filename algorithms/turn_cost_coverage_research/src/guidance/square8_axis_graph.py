"""MapTools 场景的 square8 axis-guided 图构建实验。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import networkx as nx

from .models import GuidanceField
from .vertex_guidance import query_vertex_direction


@dataclass(frozen=True)
class Square8AxisGraphConfig:
    grid_step_m: float
    diagonal_cost_multiplier: float = 1.15
    axis_confidence_threshold: float = 0.60
    axis_angle_tolerance_deg: float = 25.0
    diagonal_axis_suppress_confidence: float = 0.60
    bridge_disconnected_components: bool = True
    bridge_max_step_factor: float = 4.0
    bridge_cost_multiplier: float = 4.0

    def __post_init__(self) -> None:
        if self.grid_step_m <= 0:
            raise ValueError("grid_step_m must be positive")
        if self.diagonal_cost_multiplier <= 0:
            raise ValueError("diagonal_cost_multiplier must be positive")
        if not 0 <= self.axis_confidence_threshold <= 1:
            raise ValueError("axis_confidence_threshold must be in [0, 1]")
        if self.axis_angle_tolerance_deg < 0 or self.axis_angle_tolerance_deg > 90:
            raise ValueError("axis_angle_tolerance_deg must be in [0, 90]")
        if not 0 <= self.diagonal_axis_suppress_confidence <= 1:
            raise ValueError("diagonal_axis_suppress_confidence must be in [0, 1]")
        if self.bridge_max_step_factor <= 0:
            raise ValueError("bridge_max_step_factor must be positive")
        if self.bridge_cost_multiplier <= 0:
            raise ValueError("bridge_cost_multiplier must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "grid_step_m": float(self.grid_step_m),
            "diagonal_cost_multiplier": float(self.diagonal_cost_multiplier),
            "axis_confidence_threshold": float(self.axis_confidence_threshold),
            "axis_angle_tolerance_deg": float(self.axis_angle_tolerance_deg),
            "diagonal_axis_suppress_confidence": float(self.diagonal_axis_suppress_confidence),
            "bridge_disconnected_components": bool(self.bridge_disconnected_components),
            "bridge_max_step_factor": float(self.bridge_max_step_factor),
            "bridge_cost_multiplier": float(self.bridge_cost_multiplier),
        }


def _axis_distance(angle: float, axis: float) -> float:
    return abs(((float(angle) - float(axis) + 0.5 * math.pi) % math.pi) - 0.5 * math.pi)


def _edge_orientation(p0: Any, p1: Any) -> float:
    return math.atan2(float(p1.y) - float(p0.y), float(p1.x) - float(p0.x)) % math.pi


def _distance(p0: Any, p1: Any) -> float:
    return math.hypot(float(p0.x) - float(p1.x), float(p0.y) - float(p1.y))


def _guidance_hint(vertex: Any, guidance_field: GuidanceField | None, min_confidence: float) -> Any | None:
    if guidance_field is None:
        return None
    hint, status = query_vertex_direction(vertex, guidance_field, min_confidence=min_confidence)
    if status.status != "hit":
        return None
    return hint


def _edge_cost_multiplier(
    *,
    v0: Any,
    v1: Any,
    is_diagonal: bool,
    guidance_field: GuidanceField | None,
    config: Square8AxisGraphConfig,
) -> float:
    multiplier = config.diagonal_cost_multiplier if is_diagonal else 1.0
    if guidance_field is None:
        return multiplier
    hints = [
        _guidance_hint(v0, guidance_field, config.axis_confidence_threshold),
        _guidance_hint(v1, guidance_field, config.axis_confidence_threshold),
    ]
    hints = [hint for hint in hints if hint is not None]
    if not hints:
        return multiplier
    edge_angle = _edge_orientation(v0.point, v1.point)
    tolerance = math.radians(config.axis_angle_tolerance_deg)
    aligned_count = sum(1 for hint in hints if _axis_distance(edge_angle, hint.preferred_angle_rad) <= tolerance)
    if aligned_count == len(hints):
        return multiplier * 0.90
    if is_diagonal and any(hint.confidence >= config.diagonal_axis_suppress_confidence for hint in hints):
        return multiplier * 2.50
    return multiplier * 1.20


def create_square8_axis_guided_graph(
    *,
    polygonal_area: Any,
    point_vertex_cls: Any,
    config: Square8AxisGraphConfig,
    guidance_field: GuidanceField | None,
) -> tuple[list[Any], nx.Graph, dict[str, Any]]:
    """创建 4 邻为主、受控 8 邻为辅的 square grid graph。

    后续仍交给官方 PointBasedInstance/fractional/matching 流程。
    """

    bb = polygonal_area.get_bounding_box()
    min_x, min_y = float(bb[0][0]), float(bb[0][1])
    max_x, max_y = float(bb[1][0]), float(bb[1][1])
    step = float(config.grid_step_m)
    cols = int(math.floor((max_x - min_x) / step)) + 1
    rows = int(math.floor((max_y - min_y) / step)) + 1
    by_index: dict[tuple[int, int], Any] = {}
    points: list[Any] = []
    for row in range(rows + 1):
        y = min_y + row * step
        if y > max_y + 1e-9:
            continue
        for col in range(cols + 1):
            x = min_x + col * step
            if x > max_x + 1e-9:
                continue
            vertex = point_vertex_cls((x, y))
            if not polygonal_area.as_shapely_polygon().contains(vertex.point.to_shapely()):
                continue
            by_index[(row, col)] = vertex
            points.append(vertex)

    graph = nx.Graph()
    graph.add_nodes_from(points)
    stats = {
        "candidate_node_count": int((rows + 1) * (cols + 1)),
        "grid_point_count": int(len(points)),
        "orthogonal_edge_count": 0,
        "diagonal_edge_count": 0,
        "diagonal_suppressed_by_corner_cutting": 0,
        "diagonal_suppressed_by_line_of_sight": 0,
        "orthogonal_suppressed_by_line_of_sight": 0,
        "edge_multiplier_min": None,
        "edge_multiplier_max": None,
    }

    def add_edge(a: tuple[int, int], b: tuple[int, int], is_diagonal: bool) -> None:
        v0 = by_index.get(a)
        v1 = by_index.get(b)
        if v0 is None or v1 is None:
            return
        if is_diagonal and (by_index.get((a[0], b[1])) is None or by_index.get((b[0], a[1])) is None):
            stats["diagonal_suppressed_by_corner_cutting"] += 1
            return
        if not polygonal_area.has_line_of_sight(v0.point, v1.point):
            key = "diagonal_suppressed_by_line_of_sight" if is_diagonal else "orthogonal_suppressed_by_line_of_sight"
            stats[key] += 1
            return
        multiplier = _edge_cost_multiplier(
            v0=v0,
            v1=v1,
            is_diagonal=is_diagonal,
            guidance_field=guidance_field,
            config=config,
        )
        graph.add_edge(v0, v1, cost_multiplier=float(multiplier), is_diagonal=bool(is_diagonal))
        stats["diagonal_edge_count" if is_diagonal else "orthogonal_edge_count"] += 1
        stats["edge_multiplier_min"] = multiplier if stats["edge_multiplier_min"] is None else min(float(stats["edge_multiplier_min"]), multiplier)
        stats["edge_multiplier_max"] = multiplier if stats["edge_multiplier_max"] is None else max(float(stats["edge_multiplier_max"]), multiplier)

    for row, col in list(by_index):
        add_edge((row, col), (row + 1, col), False)
        add_edge((row, col), (row, col + 1), False)
        add_edge((row, col), (row + 1, col + 1), True)
        add_edge((row, col), (row + 1, col - 1), True)
    bridge_stats = _connect_components_with_los_bridges(
        graph=graph,
        polygonal_area=polygonal_area,
        max_length=float(config.bridge_max_step_factor) * step,
        bridge_cost_multiplier=float(config.bridge_cost_multiplier),
    ) if config.bridge_disconnected_components else {"bridge_edge_count": 0, "bridge_attempt_status": "disabled"}
    stats["graph_node_count"] = int(graph.number_of_nodes())
    stats["graph_edge_count"] = int(graph.number_of_edges())
    stats["config"] = config.to_dict()
    stats["bridges"] = bridge_stats
    stats["algorithm_impact"] = "non_official_square8_axis_guided_graph_backend"
    return points, graph, stats


def _connect_components_with_los_bridges(
    *,
    graph: nx.Graph,
    polygonal_area: Any,
    max_length: float,
    bridge_cost_multiplier: float,
) -> dict[str, Any]:
    bridge_count = 0
    rejected_by_length = 0
    rejected_by_los = 0
    while nx.number_connected_components(graph) > 1:
        components = [list(component) for component in nx.connected_components(graph)]
        components.sort(key=len, reverse=True)
        base = components[0]
        best_pair = None
        best_distance = None
        for component in components[1:]:
            for v0 in base:
                for v1 in component:
                    edge_distance = float(_distance(v0, v1))
                    if edge_distance > max_length:
                        rejected_by_length += 1
                        continue
                    if not polygonal_area.has_line_of_sight(v0.point, v1.point):
                        rejected_by_los += 1
                        continue
                    if best_distance is None or edge_distance < best_distance:
                        best_distance = edge_distance
                        best_pair = (v0, v1)
        if best_pair is None:
            return {
                "bridge_edge_count": int(bridge_count),
                "bridge_attempt_status": "failed_no_los_pair_within_limit",
                "remaining_component_count": int(nx.number_connected_components(graph)),
                "bridge_max_length_m": float(max_length),
                "rejected_by_length": int(rejected_by_length),
                "rejected_by_los": int(rejected_by_los),
            }
        graph.add_edge(
            best_pair[0],
            best_pair[1],
            cost_multiplier=float(bridge_cost_multiplier),
            multiplier=float(bridge_cost_multiplier),
            is_diagonal=False,
            is_component_bridge=True,
        )
        bridge_count += 1
    return {
        "bridge_edge_count": int(bridge_count),
        "bridge_attempt_status": "success",
        "remaining_component_count": int(nx.number_connected_components(graph)),
        "bridge_max_length_m": float(max_length),
        "rejected_by_length": int(rejected_by_length),
        "rejected_by_los": int(rejected_by_los),
    }
