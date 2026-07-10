from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from ...contracts import CoveragePlanningRequest
from .channel_topology_graph_adapter import build_channel_topology_graph_config, build_region_mask_from_request

FOUR_NEIGHBORS: tuple[tuple[int, int], ...] = ((-1, 0), (0, -1), (0, 1), (1, 0))
DEAD_END_EDGE_TYPES = {"dead_end_one_side", "dead_end_both_sides"}


@dataclass(frozen=True)
class ShelfAwareCtgAuxiliaryMaps:
    edge_label_map: np.ndarray
    junction_label_map: np.ndarray
    debug_info: dict[str, Any]


def build_junction_label_map(shape: tuple[int, int], graph_info: Any) -> np.ndarray:
    labels = np.full(shape, -1, dtype=np.int32)
    for node in getattr(graph_info, "nodes", ()): 
        polygon_rc = tuple(getattr(node, "polygon_vertices_rc", None) or ())
        if len(polygon_rc) < 3:
            continue
        points_xy = np.array(
            [[int(round(float(col))), int(round(float(row)))] for row, col in polygon_rc],
            dtype=np.int32,
        )
        cv2.fillPoly(labels, [points_xy.reshape((-1, 1, 2))], int(getattr(node, "node_id", -1)))
    return labels


def edge_territory_owner_map(geometry_result: Any, graph_info: Any) -> np.ndarray:
    from algorithms.channel_topology_graph.coverage_planning.coverage_lane_sweep.lane_regions import (
        build_node_polygon_mask,
        derive_outer_path_owner_map,
    )

    free_mask = np.where(np.asarray(geometry_result.free_mask) > 0, 255, 0).astype(np.uint8)
    node_polygon_mask = build_node_polygon_mask(free_mask.shape, graph_info.nodes)
    constrained_free_mask = np.where(node_polygon_mask > 0, 0, free_mask).astype(np.uint8)
    return derive_outer_path_owner_map(
        graph_info=graph_info,
        constrained_free_mask=constrained_free_mask,
    )


def dead_end_edge_ids(graph_info: Any) -> set[int]:
    return {
        int(edge.edge_id)
        for edge in getattr(graph_info, "edges", ())
        if str(getattr(edge, "edge_type", "") or "") in DEAD_END_EDGE_TYPES
    }


def expand_edge_label_components(
    *,
    free_mask: np.ndarray,
    labels: np.ndarray,
    edge_id: int,
) -> None:
    allowed = np.where((free_mask > 0) & ((labels == -1) | (labels == int(edge_id))), 255, 0).astype(np.uint8)
    if int(np.count_nonzero(allowed)) == 0:
        return
    num_labels, component_labels = cv2.connectedComponents(allowed, connectivity=4)
    if int(num_labels) <= 1:
        return
    seed_component_ids = np.unique(component_labels[labels == int(edge_id)])
    seed_component_ids = seed_component_ids[seed_component_ids > 0]
    if int(seed_component_ids.size) == 0:
        return
    labels[np.isin(component_labels, seed_component_ids)] = int(edge_id)


def build_expanded_edge_label_map(geometry_result: Any, graph_info: Any) -> tuple[np.ndarray, dict[str, Any]]:
    free_mask = np.where(np.asarray(geometry_result.free_mask) > 0, 255, 0).astype(np.uint8)
    labels = edge_territory_owner_map(geometry_result, graph_info)
    expandable_edge_ids = dead_end_edge_ids(graph_info)

    for edge_id in sorted(expandable_edge_ids):
        expand_edge_label_components(
            free_mask=free_mask,
            labels=labels,
            edge_id=int(edge_id),
        )

    unique_labels, unique_counts = np.unique(labels[labels >= 0], return_counts=True)
    pixel_count_by_edge = {
        str(int(edge_id)): int(count)
        for edge_id, count in zip(unique_labels.tolist(), unique_counts.tolist())
    }
    return labels, {
        "seed_edge_count": int(len(pixel_count_by_edge)),
        "expanded_edge_ids": [int(edge_id) for edge_id in sorted(expandable_edge_ids)],
        "pixel_count_by_edge": pixel_count_by_edge,
    }


def paste_local_labels_to_full_map(
    *,
    local_labels: np.ndarray,
    crop_box_px: tuple[int, int, int, int],
    full_shape: tuple[int, int],
) -> np.ndarray:
    top, left, bottom, right = tuple(int(value) for value in crop_box_px)
    full_labels = np.full(full_shape, -1, dtype=np.int32)
    target = full_labels[top:bottom, left:right]
    h = min(target.shape[0], local_labels.shape[0])
    w = min(target.shape[1], local_labels.shape[1])
    if h > 0 and w > 0:
        target[:h, :w] = local_labels[:h, :w]
    return full_labels


def _build_ctg_auxiliary_config(request: CoveragePlanningRequest, *, boundary_smoothing_enable: bool | None) -> Any:
    from algorithms.channel_topology_graph.pipeline.main_pipeline import PipelineConfig

    config_payload = build_channel_topology_graph_config(request)
    if boundary_smoothing_enable is not None:
        geometry_config = dict(config_payload.get("geometry_preparation", {}) or {})
        geometry_config["boundary_smoothing_enable"] = bool(boundary_smoothing_enable)
        nested = dict(geometry_config.get("boundary_smoothing", {}) or {})
        nested["enable"] = bool(boundary_smoothing_enable)
        geometry_config["boundary_smoothing"] = nested
        config_payload["geometry_preparation"] = geometry_config
    return PipelineConfig(**config_payload)


def _run_ctg_auxiliary_pipeline(
    request: CoveragePlanningRequest,
    *,
    boundary_smoothing_enable: bool | None,
) -> tuple[Any, Any]:
    from algorithms.channel_topology_graph.pipeline.main_pipeline import (
        PipelineInput,
        PipelineStages,
        build_pipeline_runtime_context,
        normalize_pipeline_runtime_inputs,
        run_geometry_preparation_stage,
        run_junction_rebuild_stage,
        run_topology_graph_build_stage,
    )

    region_mask = build_region_mask_from_request(request)
    pipeline_input = PipelineInput(
        raw_map=np.asarray(request.prepared_map),
        region_constraint=region_mask,
        meta={
            "source": "shelf_aware_ctg_auxiliary",
            "map_yaml_path": str(request.map_yaml_path or ""),
        },
    )
    config_obj, stages = normalize_pipeline_runtime_inputs(
        config=_build_ctg_auxiliary_config(request, boundary_smoothing_enable=boundary_smoothing_enable),
        stages=PipelineStages(),
    )
    runtime_context = build_pipeline_runtime_context(config_obj)
    geometry_result = run_geometry_preparation_stage(
        pipeline_input=pipeline_input,
        config=config_obj,
        stages=stages,
    )
    runtime_context["geometry_preparation_result"] = geometry_result
    junction_result = run_junction_rebuild_stage(
        geometry_preparation_result=geometry_result,
        config=config_obj,
        stages=stages,
        runtime_context=runtime_context,
    )
    topology_result = run_topology_graph_build_stage(
        junction_rebuild_result=junction_result,
        config=config_obj,
        stages=stages,
        runtime_context=runtime_context,
    )
    return geometry_result, topology_result


def build_shelf_aware_ctg_auxiliary_maps(request: CoveragePlanningRequest) -> ShelfAwareCtgAuxiliaryMaps:
    fallback_debug: dict[str, Any] = {
        "used": False,
        "reason": "",
        "fallback": "",
    }
    try:
        geometry_result, topology_result = _run_ctg_auxiliary_pipeline(
            request,
            boundary_smoothing_enable=None,
        )
    except ValueError as exc:
        if "path too short" not in str(exc):
            raise
        fallback_debug = {
            "used": True,
            "reason": str(exc),
            "fallback": "retry_ctg_auxiliary_with_boundary_smoothing_disabled",
        }
        geometry_result, topology_result = _run_ctg_auxiliary_pipeline(
            request,
            boundary_smoothing_enable=False,
        )

    coverage_lane_count = 0
    if bool(getattr(request.public_config, "shelf_ctg_auxiliary_build_sweeps", False)):
        from algorithms.channel_topology_graph.coverage_planning import build_coverage_lane_sweep_info

        coverage_lane_sweep_info = build_coverage_lane_sweep_info(
            graph_info=topology_result.graph_info,
            geometry_result=geometry_result,
            config=config_obj.coverage_planning,
        )
        coverage_lane_count = int(len(tuple(coverage_lane_sweep_info.coverage_lane_info)))

    local_edge_labels, edge_debug = build_expanded_edge_label_map(
        geometry_result,
        topology_result.graph_info,
    )
    local_junction_labels = build_junction_label_map(
        np.asarray(geometry_result.free_mask).shape,
        topology_result.graph_info,
    )
    full_shape = np.asarray(request.prepared_map).shape[:2]
    edge_label_map = paste_local_labels_to_full_map(
        local_labels=local_edge_labels,
        crop_box_px=geometry_result.crop_box_px,
        full_shape=full_shape,
    )
    junction_label_map = paste_local_labels_to_full_map(
        local_labels=local_junction_labels,
        crop_box_px=geometry_result.crop_box_px,
        full_shape=full_shape,
    )
    return ShelfAwareCtgAuxiliaryMaps(
        edge_label_map=edge_label_map,
        junction_label_map=junction_label_map,
        debug_info={
            "enabled": True,
            "geometry_crop_box_px": list(geometry_result.crop_box_px),
            "boundary_smoothing": dict((geometry_result.debug_info or {}).get("boundary_smoothing", {})),
            "graph_node_count": int(len(topology_result.graph_info.nodes)),
            "graph_edge_count": int(len(topology_result.graph_info.edges)),
            "coverage_lane_count": int(coverage_lane_count),
            "coverage_lane_sweeps_built": bool(getattr(request.public_config, "shelf_ctg_auxiliary_build_sweeps", False)),
            "edge_territory": edge_debug,
            "junction_labeled_pixel_count": int(np.count_nonzero(junction_label_map >= 0)),
            "topology_short_edge_fallback": fallback_debug,
        },
    )
