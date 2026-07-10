from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .boundary_smoothing import BoundarySmoothingResult
from .direction_grid import DirectionGridResult
from .project_inputs import StudyInput
from .territory_expansion import ExpandedTerritory


def color_for_id(identifier: int) -> tuple[int, int, int]:
    rng = np.random.default_rng(int(identifier) * 7919 + 17)
    color = rng.integers(60, 240, size=3).tolist()
    return int(color[0]), int(color[1]), int(color[2])


def overlay_mask(base_gray: np.ndarray, mask: np.ndarray, color: tuple[int, int, int], alpha: float) -> np.ndarray:
    image = cv2.cvtColor(np.asarray(base_gray, dtype=np.uint8), cv2.COLOR_GRAY2BGR)
    color_layer = np.zeros_like(image)
    color_layer[:, :] = color
    active = np.asarray(mask) > 0
    image[active] = cv2.addWeighted(image, 1.0 - alpha, color_layer, alpha, 0)[active]
    return image


def save_binary(path: Path, mask: np.ndarray) -> None:
    cv2.imwrite(str(path), np.where(np.asarray(mask) > 0, 255, 0).astype(np.uint8))


def render_free_context(mask: np.ndarray) -> np.ndarray:
    return np.where(np.asarray(mask) > 0, 255, 0).astype(np.uint8)


def render_boundary_context(free_mask: np.ndarray, boundary_band: np.ndarray) -> np.ndarray:
    image = render_free_context(free_mask)
    image[np.asarray(boundary_band) > 0] = 150
    return image


def render_delta_context(free_mask: np.ndarray, delta_add: np.ndarray, delta_remove: np.ndarray) -> np.ndarray:
    image = render_free_context(free_mask)
    image[np.asarray(delta_add) > 0] = 220
    image[np.asarray(delta_remove) > 0] = 70
    return image


def draw_polyline(image: np.ndarray, path_rc: tuple[tuple[float, float], ...], color: tuple[int, int, int], thickness: int) -> None:
    points = [(int(round(col)), int(round(row))) for row, col in path_rc]
    for start, end in zip(points, points[1:]):
        cv2.line(image, start, end, color, thickness, cv2.LINE_AA)


def draw_polygon(image: np.ndarray, polygon_rc: tuple[tuple[float, float], ...], color: tuple[int, int, int], thickness: int) -> None:
    if len(polygon_rc) < 2:
        return
    points = np.asarray([[int(round(col)), int(round(row))] for row, col in polygon_rc], dtype=np.int32)
    cv2.polylines(image, [points], isClosed=True, color=color, thickness=thickness, lineType=cv2.LINE_AA)


def render_graph_overlay(geometry_result: Any, graph_info: Any) -> np.ndarray:
    image = cv2.cvtColor(np.asarray(geometry_result.gray, dtype=np.uint8), cv2.COLOR_GRAY2BGR)
    skeleton = np.asarray(geometry_result.skeleton_pruned_mask) > 0
    image[skeleton] = (255, 255, 0)
    for edge in graph_info.edges:
        draw_polyline(image, tuple(edge.outer_path_rc or ()), (0, 180, 255), 2)
    for node in graph_info.nodes:
        row, col = node.point_rc
        cv2.circle(image, (int(round(col)), int(round(row))), 4, (0, 0, 255), -1, cv2.LINE_AA)
        draw_polygon(image, tuple(node.polygon_vertices_rc or ()), (0, 80, 255), 1)
    return image


def render_territory_overlay(geometry_result: Any, lane_info: tuple[dict[str, Any], ...]) -> np.ndarray:
    base = cv2.cvtColor(np.asarray(geometry_result.gray, dtype=np.uint8), cv2.COLOR_GRAY2BGR)
    color_layer = np.zeros_like(base)
    alpha_mask = np.zeros(base.shape[:2], dtype=np.uint8)
    for lane in lane_info:
        edge_id = int(lane.get("source_edge_id", -1))
        if edge_id < 0:
            continue
        color = color_for_id(edge_id)
        for row, col in lane.get("territory_pixels", ()):
            row_i = int(row)
            col_i = int(col)
            if 0 <= row_i < color_layer.shape[0] and 0 <= col_i < color_layer.shape[1]:
                color_layer[row_i, col_i] = color
                alpha_mask[row_i, col_i] = 1
    blended = base.copy()
    blended[alpha_mask > 0] = cv2.addWeighted(base, 0.35, color_layer, 0.65, 0)[alpha_mask > 0]
    return blended


def render_expanded_territory_overlay(geometry_result: Any, expanded: ExpandedTerritory) -> np.ndarray:
    base = cv2.cvtColor(np.asarray(geometry_result.gray, dtype=np.uint8), cv2.COLOR_GRAY2BGR)
    color_layer = np.zeros_like(base)
    alpha_mask = np.zeros(base.shape[:2], dtype=np.uint8)
    for edge_id in sorted(int(item) for item in np.unique(expanded.labels) if int(item) >= 0):
        color = color_for_id(edge_id)
        active = expanded.labels == edge_id
        color_layer[active] = color
        alpha_mask[active] = 1
    blended = base.copy()
    blended[alpha_mask > 0] = cv2.addWeighted(base, 0.35, color_layer, 0.65, 0)[alpha_mask > 0]
    return blended


def render_expanded_territory_direction_grid(
    geometry_result: Any,
    expanded: ExpandedTerritory,
    direction_grid: DirectionGridResult,
) -> np.ndarray:
    image = render_expanded_territory_overlay(geometry_result, expanded)
    grid_spacing_px = int(direction_grid.debug_info.get("grid_spacing_px", 20))
    arrow_half_length = max(5, int(round(float(grid_spacing_px) * 0.32)))
    for sample in direction_grid.samples:
        row = int(sample["row"])
        col = int(sample["col"])
        tangent_row, tangent_col = sample["direction_vector_rc"]
        delta_col = int(round(float(tangent_col) * float(arrow_half_length)))
        delta_row = int(round(float(tangent_row) * float(arrow_half_length)))
        start = (int(col - delta_col), int(row - delta_row))
        end = (int(col + delta_col), int(row + delta_row))
        cv2.line(image, start, end, (20, 20, 20), 3, cv2.LINE_AA)
        cv2.line(image, start, end, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.circle(image, (col, row), 2, (20, 20, 20), -1, cv2.LINE_AA)
    return image


def render_edge_direction_overlay(geometry_result: Any, graph_info: Any) -> np.ndarray:
    image = cv2.cvtColor(np.asarray(geometry_result.gray, dtype=np.uint8), cv2.COLOR_GRAY2BGR)
    for edge in graph_info.edges:
        path = tuple(edge.outer_path_rc or ())
        if len(path) < 2:
            continue
        color = color_for_id(int(edge.edge_id))
        draw_polyline(image, path, color, 2)
        mid_idx = len(path) // 2
        start = path[max(0, mid_idx - 1)]
        end = path[min(len(path) - 1, mid_idx + 1)]
        start_xy = (int(round(start[1])), int(round(start[0])))
        end_xy = (int(round(end[1])), int(round(end[0])))
        cv2.arrowedLine(image, start_xy, end_xy, color, 2, cv2.LINE_AA, tipLength=0.35)
        cv2.putText(
            image,
            str(int(edge.edge_id)),
            end_xy,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return image


def write_visualizations(
    study_input: StudyInput,
    ctg: dict[str, Any],
    expanded: ExpandedTerritory,
    direction_grid: DirectionGridResult,
    output_dir: Path,
) -> None:
    geometry_result = ctg["geometry_result"]
    graph_info = ctg["topology_result"].graph_info
    lane_info = tuple(ctg["coverage_lane_sweep_info"].coverage_lane_info)

    save_binary(output_dir / "01_prepared_map.png", study_input.prepared_map)
    cv2.imwrite(str(output_dir / "02_region_mask.png"), overlay_mask(study_input.prepared_map, study_input.region_mask, (0, 180, 0), 0.55))
    cv2.imwrite(str(output_dir / "03_ctg_skeleton_graph.png"), render_graph_overlay(geometry_result, graph_info))
    cv2.imwrite(str(output_dir / "04_territory_seed_overlay.png"), render_territory_overlay(geometry_result, lane_info))

    junction_overlay = cv2.cvtColor(np.asarray(geometry_result.gray, dtype=np.uint8), cv2.COLOR_GRAY2BGR)
    for node in graph_info.nodes:
        draw_polygon(junction_overlay, tuple(node.polygon_vertices_rc or ()), (0, 0, 255), 2)
    cv2.imwrite(str(output_dir / "05_junction_polygon_overlay.png"), junction_overlay)
    cv2.imwrite(str(output_dir / "06_edge_direction_overlay.png"), render_edge_direction_overlay(geometry_result, graph_info))
    cv2.imwrite(str(output_dir / "07_expanded_territory_overlay.png"), render_expanded_territory_overlay(geometry_result, expanded))
    cv2.imwrite(str(output_dir / "08_expanded_territory_direction_grid.png"), render_expanded_territory_direction_grid(geometry_result, expanded, direction_grid))


def write_boundary_smoothing_visualizations(smoothing: BoundarySmoothingResult, output_dir: Path) -> None:
    smoothing_dir = output_dir / "boundary_smoothing"
    raw_dir = smoothing_dir / "raw_masks"
    smoothing_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    save_binary(raw_dir / "original_free.png", smoothing.original_free_mask)
    save_binary(raw_dir / "boundary_band.png", smoothing.boundary_band)
    save_binary(raw_dir / "delta_add_free.png", smoothing.delta_add)
    save_binary(raw_dir / "delta_remove_free.png", smoothing.delta_remove)
    save_binary(raw_dir / "smoothed_free.png", smoothing.smoothed_free_mask)
    cv2.imwrite(str(smoothing_dir / "01_boundary_band.png"), render_boundary_context(smoothing.original_free_mask, smoothing.boundary_band))
    cv2.imwrite(str(smoothing_dir / "02_delta_add_free.png"), render_delta_context(smoothing.original_free_mask, smoothing.delta_add, np.zeros_like(smoothing.delta_remove)))
    cv2.imwrite(str(smoothing_dir / "03_delta_remove_free.png"), render_delta_context(smoothing.original_free_mask, np.zeros_like(smoothing.delta_add), smoothing.delta_remove))
    cv2.imwrite(str(smoothing_dir / "04_smoothed_free.png"), render_free_context(smoothing.smoothed_free_mask))
    cv2.imwrite(str(smoothing_dir / "05_boundary_delta_context.png"), render_delta_context(smoothing.original_free_mask, smoothing.delta_add, smoothing.delta_remove))
