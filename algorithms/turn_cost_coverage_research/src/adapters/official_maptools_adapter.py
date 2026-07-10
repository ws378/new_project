"""把既有 MapTools 预处理结果适配为官方 pcpptc 输入。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from algorithms.channel_topology_graph.pipeline import PipelineStages
from algorithms.channel_topology_graph.pipeline.main_pipeline import normalize_pipeline_runtime_inputs
from algorithms.shelf_aware_ctg_research.src.ctg_territory_extractor import (
    build_ctg_stage_config,
    run_geometry_preparation,
)
from algorithms.shelf_aware_ctg_research.src.project_inputs import StudyInput, build_study_input


@dataclass(frozen=True)
class MapToolsOfficialAdapterConfig:
    """官方 PolygonInstance 所需的最小参数映射。"""

    penalty_strength: float = 40.0
    turn_cost: float = 10.0
    distance_cost: float = 1.0
    tool_radius_scale: float = 1.0


@dataclass(frozen=True)
class MapToolsOfficialInput:
    project_dir: Path
    area_id: int
    area_name: str
    component_index: int
    component_count: int
    study_input: StudyInput
    geometry_result: Any
    polygon_instance: Any
    tool_radius_m: float
    metadata: dict[str, Any]


def mask_to_single_polygon(
    mask: np.ndarray,
    *,
    resolution_m_per_px: float,
    repair_metadata: dict[str, Any] | None = None,
) -> Polygon:
    """将既有二值 mask 转为单连通 Shapely Polygon。

    这是输入适配，不做膨胀、腐蚀、平滑或连通域选择；如果既有预处理结果
    不是单连通 polygon，直接失败并交给 summary 记录原因。
    """

    binary = np.where(np.asarray(mask) > 0, 255, 0).astype(np.uint8)
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None or not contours:
        raise ValueError("preprocessed mask has no polygon contour")

    hierarchy_items = hierarchy[0]
    polygons: list[Polygon] = []
    repair_records: list[dict[str, Any]] = []
    for index, item in enumerate(hierarchy_items):
        parent = int(item[3])
        if parent != -1:
            continue
        shell = _contour_to_ring(contours[index], resolution_m_per_px)
        if len(shell) < 4:
            continue
        holes: list[list[tuple[float, float]]] = []
        child = int(item[2])
        while child != -1:
            hole = _contour_to_ring(contours[child], resolution_m_per_px)
            if len(hole) >= 4:
                holes.append(hole)
            child = int(hierarchy_items[child][0])
        poly = Polygon(shell, holes)
        if not poly.is_valid:
            before = {
                "contour_index": int(index),
                "before_geom_type": poly.geom_type,
                "before_area_m2": float(poly.area),
            }
            poly = poly.buffer(0)
            before.update(
                {
                    "after_geom_type": poly.geom_type,
                    "after_area_m2": float(poly.area),
                }
            )
            repair_records.append(before)
        if poly.is_empty:
            continue
        if isinstance(poly, MultiPolygon):
            polygons.extend(item for item in poly.geoms if not item.is_empty)
        else:
            polygons.append(poly)

    if not polygons:
        raise ValueError("preprocessed mask did not yield a valid polygon")

    merged = unary_union(polygons)
    if isinstance(merged, MultiPolygon):
        raise ValueError(f"preprocessed mask yielded {len(merged.geoms)} disconnected polygon components")
    if not isinstance(merged, Polygon) or merged.is_empty:
        raise ValueError(f"preprocessed mask yielded unsupported geometry: {merged.geom_type}")
    if repair_metadata is not None:
        repair_metadata.update(
            {
                "contour_count": int(len(contours)),
                "external_component_count": int(len(polygons)),
                "topology_repair_count": int(len(repair_records)),
                "topology_repairs": repair_records,
            }
        )
    return merged


def mask_to_component_polygons(
    mask: np.ndarray,
    *,
    resolution_m_per_px: float,
    repair_metadata: dict[str, Any] | None = None,
) -> list[Polygon]:
    """将既有二值 mask 转为一个或多个单连通 Polygon。

    这是多连通输入的结构拆分适配：不选择最大连通域，不补虚拟连接，
    也不改变既有预处理语义。
    """

    try:
        return [
            mask_to_single_polygon(
                mask,
                resolution_m_per_px=resolution_m_per_px,
                repair_metadata=repair_metadata,
            )
        ]
    except ValueError as exc:
        if "disconnected polygon components" not in str(exc):
            raise

    component_metadata: dict[str, Any] = {}
    polygons = _mask_to_raw_polygons(mask, resolution_m_per_px=resolution_m_per_px, repair_metadata=component_metadata)
    merged = unary_union(polygons)
    if isinstance(merged, Polygon):
        components = [merged]
    elif isinstance(merged, MultiPolygon):
        components = [item for item in merged.geoms if not item.is_empty]
    else:
        raise ValueError(f"preprocessed mask yielded unsupported geometry: {merged.geom_type}")
    components = sorted(components, key=lambda item: float(item.area), reverse=True)
    if repair_metadata is not None:
        repair_metadata.update(component_metadata)
        repair_metadata["component_count"] = int(len(components))
        repair_metadata["component_areas_m2"] = [float(item.area) for item in components]
        repair_metadata["split_policy"] = "split_all_disconnected_components_no_drop_no_virtual_bridge"
    return components


def _mask_to_raw_polygons(
    mask: np.ndarray,
    *,
    resolution_m_per_px: float,
    repair_metadata: dict[str, Any] | None = None,
) -> list[Polygon]:
    binary = np.where(np.asarray(mask) > 0, 255, 0).astype(np.uint8)
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None or not contours:
        raise ValueError("preprocessed mask has no polygon contour")

    hierarchy_items = hierarchy[0]
    polygons: list[Polygon] = []
    repair_records: list[dict[str, Any]] = []
    for index, item in enumerate(hierarchy_items):
        parent = int(item[3])
        if parent != -1:
            continue
        shell = _contour_to_ring(contours[index], resolution_m_per_px)
        if len(shell) < 4:
            continue
        holes: list[list[tuple[float, float]]] = []
        child = int(item[2])
        while child != -1:
            hole = _contour_to_ring(contours[child], resolution_m_per_px)
            if len(hole) >= 4:
                holes.append(hole)
            child = int(hierarchy_items[child][0])
        poly = Polygon(shell, holes)
        if not poly.is_valid:
            before = {
                "contour_index": int(index),
                "before_geom_type": poly.geom_type,
                "before_area_m2": float(poly.area),
            }
            poly = poly.buffer(0)
            before.update(
                {
                    "after_geom_type": poly.geom_type,
                    "after_area_m2": float(poly.area),
                }
            )
            repair_records.append(before)
        if poly.is_empty:
            continue
        if isinstance(poly, MultiPolygon):
            polygons.extend(item for item in poly.geoms if not item.is_empty)
        else:
            polygons.append(poly)

    if not polygons:
        raise ValueError("preprocessed mask did not yield a valid polygon")
    if repair_metadata is not None:
        repair_metadata.update(
            {
                "contour_count": int(len(contours)),
                "external_component_count": int(len(polygons)),
                "topology_repair_count": int(len(repair_records)),
                "topology_repairs": repair_records,
            }
        )
    return polygons


def build_maptools_official_input(
    project_dir: str | Path,
    *,
    area_id: int,
    output_dir: str | Path,
    apply_boundary_smoothing: bool = True,
    config: MapToolsOfficialAdapterConfig | None = None,
) -> MapToolsOfficialInput:
    inputs = build_maptools_official_inputs(
        project_dir,
        area_id=area_id,
        output_dir=output_dir,
        apply_boundary_smoothing=apply_boundary_smoothing,
        split_disconnected_components=False,
        config=config,
    )
    return inputs[0]


def build_maptools_official_inputs(
    project_dir: str | Path,
    *,
    area_id: int,
    output_dir: str | Path,
    apply_boundary_smoothing: bool = True,
    split_disconnected_components: bool = False,
    config: MapToolsOfficialAdapterConfig | None = None,
) -> list[MapToolsOfficialInput]:
    from algorithms.turn_cost_coverage_research.scripts.experiments.run_paper_official_algorithm_steps import (
        _install_official_path,
    )

    _install_official_path()
    from pcpptc.polygon_instance import PolygonInstance

    cfg = config or MapToolsOfficialAdapterConfig()
    output_root = Path(output_dir).expanduser().resolve()
    study_input = build_study_input(Path(project_dir).expanduser().resolve(), area_id, output_root)
    pipeline_config, stages = normalize_pipeline_runtime_inputs(
        config=build_ctg_stage_config(study_input, apply_boundary_smoothing=apply_boundary_smoothing),
        stages=PipelineStages(),
    )
    geometry_result = run_geometry_preparation(
        study_input=study_input,
        config=pipeline_config,
        stages=stages,
        raw_map=study_input.prepared_map,
        region_constraint=study_input.region_mask,
        source="turn_cost_official_maptools_adapter",
    )
    resolution = float(getattr(geometry_result, "resolution_m_per_px", study_input.map_resolution))
    tool_radius = float(study_input.public_config.coverage_width_m) / 2.0 * float(cfg.tool_radius_scale)
    polygon_repair_metadata: dict[str, Any] = {}
    if split_disconnected_components:
        feasible_polygons = mask_to_component_polygons(
            geometry_result.free_mask,
            resolution_m_per_px=resolution,
            repair_metadata=polygon_repair_metadata,
        )
    else:
        feasible_polygons = [
            mask_to_single_polygon(
                geometry_result.free_mask,
                resolution_m_per_px=resolution,
                repair_metadata=polygon_repair_metadata,
            )
        ]
    component_count = int(len(feasible_polygons))
    inputs: list[MapToolsOfficialInput] = []
    for component_index, feasible_polygon in enumerate(feasible_polygons):
        polygon_instance = PolygonInstance(
            feasible_area=feasible_polygon,
            original_area=feasible_polygon,
            valuable_areas=[(feasible_polygon, float(cfg.penalty_strength))],
            expensive_areas=[],
            turn_cost=float(cfg.turn_cost),
            distance_cost=float(cfg.distance_cost),
            tool_radius=tool_radius,
        )
        metadata = _build_adapter_metadata(
            study_input=study_input,
            geometry_result=geometry_result,
            feasible_polygon=feasible_polygon,
            polygon_repair_metadata=polygon_repair_metadata,
            cfg=cfg,
            tool_radius=tool_radius,
            resolution=resolution,
            component_index=component_index,
            component_count=component_count,
            split_disconnected_components=split_disconnected_components,
        )
        inputs.append(
            MapToolsOfficialInput(
                project_dir=study_input.project_dir,
                area_id=int(study_input.area.area_id),
                area_name=str(study_input.area.name),
                component_index=component_index,
                component_count=component_count,
                study_input=study_input,
                geometry_result=geometry_result,
                polygon_instance=polygon_instance,
                tool_radius_m=tool_radius,
                metadata=metadata,
            )
        )
    return inputs


def _build_adapter_metadata(
    *,
    study_input: StudyInput,
    geometry_result: Any,
    feasible_polygon: Polygon,
    polygon_repair_metadata: dict[str, Any],
    cfg: MapToolsOfficialAdapterConfig,
    tool_radius: float,
    resolution: float,
    component_index: int,
    component_count: int,
    split_disconnected_components: bool,
) -> dict[str, Any]:
    return {
        "adapter": "maptools_existing_preprocessing_to_official_polygon_instance",
        "adapter_scope": "只消费既有 geometry_preparation 输出；不新增预处理语义",
        "project_dir": str(study_input.project_dir),
        "project_name": study_input.project_dir.name,
        "area_id": int(study_input.area.area_id),
        "area_name": str(study_input.area.name),
        "component_index": int(component_index),
        "component_count": int(component_count),
        "component_split_enabled": bool(split_disconnected_components),
        "component_split_policy": "split_all_disconnected_components_no_drop_no_virtual_bridge",
        "resolution_m_per_px": resolution,
        "crop_box_px": list(getattr(geometry_result, "crop_box_px", ())),
        "free_pixel_count": int(np.count_nonzero(np.asarray(geometry_result.free_mask) > 0)),
        "region_pixel_count": int(np.count_nonzero(np.asarray(geometry_result.region_mask) > 0)),
        "polygon_area_m2": float(feasible_polygon.area),
        "polygon_bounds_m": [float(value) for value in feasible_polygon.bounds],
        "coverage_width_m": float(study_input.public_config.coverage_width_m),
        "robot_width_m": float(study_input.public_config.robot_width_m),
        "tool_radius_m": tool_radius,
        "tool_radius_scale": float(cfg.tool_radius_scale),
        "nominal_coverage_width_m": float(study_input.public_config.coverage_width_m),
        "penalty_strength": float(cfg.penalty_strength),
        "turn_cost": float(cfg.turn_cost),
        "distance_cost": float(cfg.distance_cost),
        "coverage_mode": "partial_penalty_only_no_hard_coverage",
        "valuable_area_policy": "使用既有 free_mask polygon 或其单连通 component 作为 valuable area；不做额外膨胀或软代价映射",
        "valuable_area_policy_note": "官方 partial-coverage 目标允许少覆盖并支付 penalty；connected_tour_feasible 不代表完整覆盖",
        "polygon_conversion": polygon_repair_metadata,
        "turn_cost_note": "PolygonInstance.turn_cost 会写入实例元数据；当前 PointBasedInstance 求解实际使用 run 参数 turn_factor",
    }


def _contour_to_ring(contour: np.ndarray, resolution_m_per_px: float) -> list[tuple[float, float]]:
    points = contour.reshape((-1, 2))
    if points.shape[0] < 3:
        return []
    ring = [
        (float(col) * float(resolution_m_per_px), -float(row) * float(resolution_m_per_px))
        for col, row in points
    ]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring
