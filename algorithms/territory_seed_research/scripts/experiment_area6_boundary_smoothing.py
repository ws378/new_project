from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from algorithms.channel_topology_graph.contracts import JunctionRebuildResult
from algorithms.channel_topology_graph.geometry_preparation.pruning import build_neighbor_mask_map
from algorithms.channel_topology_graph.io import write_geometry_preparation_summary, write_junction_rebuild_summary
from algorithms.channel_topology_graph.io.result_jsonable import to_jsonable
from algorithms.channel_topology_graph.pipeline import PipelineInput, PipelineStages
from algorithms.channel_topology_graph.pipeline.main_pipeline import (
    normalize_pipeline_runtime_inputs,
    run_geometry_preparation_stage,
)
from algorithms.channel_topology_graph.renderers import (
    write_geometry_preparation_visualizations,
    write_junction_rebuild_visualizations,
)
from algorithms.channel_topology_graph.stages.junction_rebuild import (
    build_junction_rebuild_result,
    build_junction_rebuild_stage_outputs,
    normalize_junction_rebuild_inputs,
)
from algorithms.territory_seed_research.src.boundary_smoothing import apply_majority_smoothing
from algorithms.territory_seed_research.src.ctg_territory_extractor import build_ctg_stage_config
from algorithms.territory_seed_research.src.fourfloor_inputs import DEFAULT_PROJECT_DIR, PACKAGE_ROOT, build_study_input


AREA_ID = 6


@dataclass(frozen=True)
class SmoothingVariant:
    name: str
    majority_radius_m: float
    boundary_band_m: float
    obstacle_threshold: float = 0.5


def make_run_dir() -> Path:
    run_name = "run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_area6_boundary_smoothing"
    run_dir = PACKAGE_ROOT / "output" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def normalize_mask(mask: np.ndarray) -> np.ndarray:
    return np.where(np.asarray(mask) > 0, 255, 0).astype(np.uint8)


def apply_smoothing_variant(
    free_mask: np.ndarray,
    region_mask: np.ndarray,
    resolution_m_per_px: float,
    variant: SmoothingVariant,
) -> tuple[np.ndarray, dict[str, Any]]:
    smoothing = apply_majority_smoothing(
        free_mask=free_mask,
        region_mask=region_mask,
        resolution_m_per_px=resolution_m_per_px,
        majority_radius_m=variant.majority_radius_m,
        boundary_band_m=variant.boundary_band_m,
        obstacle_threshold=variant.obstacle_threshold,
    )
    debug = {
        "variant": variant.__dict__,
        **smoothing.debug_info,
        "operations": [smoothing.debug_info],
        "boundary_band": smoothing.boundary_band,
        "delta_add": smoothing.delta_add,
        "delta_remove": smoothing.delta_remove,
    }
    return smoothing.smoothed_free_mask, debug


def geometry_config_for(study_input: Any) -> tuple[Any, Any]:
    config_obj, stages = normalize_pipeline_runtime_inputs(
        config=build_ctg_stage_config(study_input),
        stages=PipelineStages(),
    )
    return config_obj, stages


def run_geometry_on_map(
    study_input: Any,
    raw_map: np.ndarray,
    region_mask: np.ndarray,
    run_dir: Path,
    name: str,
) -> tuple[Any, Any, Any]:
    config_obj, stages = geometry_config_for(study_input)
    geometry_result = run_geometry_preparation_stage(
        pipeline_input=PipelineInput(
            raw_map=np.asarray(raw_map),
            region_constraint=np.asarray(region_mask),
            meta={"source": "area6_boundary_smoothing", "variant": name},
        ),
        config=config_obj,
        stages=stages,
    )
    out_dir = run_dir / name / "geometry_preparation"
    write_geometry_preparation_summary(geometry_result, out_dir, extra_meta={"variant": name})
    write_geometry_preparation_visualizations(geometry_result, out_dir / "viz", True, True, render_scale=8)
    return geometry_result, config_obj, stages


def build_partial_junction_result(stage_outputs: dict[str, Any], validation_error: Exception) -> JunctionRebuildResult:
    return JunctionRebuildResult(
        node_info_list=tuple(stage_outputs["node_info_list"]),
        edge_info_list=tuple(stage_outputs["edge_info_list"]),
        debug_info={
            "merge_groups": stage_outputs["merge_debug"],
            "merge_groups_applied": stage_outputs["merge_apply_debug"].get("merge_groups_applied", []),
            "post_geometry_merge": stage_outputs["post_geometry_merge_debug"],
            "node_geometry": stage_outputs["node_geometry_debug"],
            "edge_geometry": stage_outputs["edge_geometry_debug"],
            "compact": stage_outputs["compact_debug"],
            "partial_result_reason": "junction_rebuild_result_validation_failed",
        },
        validation_info={
            "valid": False,
            "error_type": type(validation_error).__name__,
            "error_message": str(validation_error),
        },
        meta={"stage_name": "junction_rebuild", "partial": True},
    )


def run_junction_diagnostic(geometry_result: Any, config_obj: Any, run_dir: Path, name: str) -> dict[str, Any]:
    out_dir = run_dir / name / "junction_rebuild"
    junction_config, junction_context = normalize_junction_rebuild_inputs(config_obj.junction_rebuild, {})
    try:
        stage_outputs = build_junction_rebuild_stage_outputs(
            geometry_preparation_result=geometry_result,
            config=junction_config,
        )
        try:
            result = build_junction_rebuild_result(stage_outputs=stage_outputs, context=junction_context)
            status = "ok"
            error_payload = None
        except Exception as exc:
            result = build_partial_junction_result(stage_outputs, exc)
            status = "failed"
            error_payload = {
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "traceback": traceback.format_exc(),
            }
        write_junction_rebuild_summary(result, out_dir, extra_meta={"variant": name, "status": status})
        write_junction_rebuild_visualizations(geometry_result, result, out_dir / "viz", True, True, render_scale=8)
        missing_polygon_nodes = [
            node
            for node in result.node_info_list
            if str(node.node_type) == "junction" and len(tuple(node.polygon_vertices_rc or ())) == 0
        ]
        payload = {
            "status": status,
            "error": error_payload,
            "node_count": int(len(result.node_info_list)),
            "edge_count": int(len(result.edge_info_list)),
            "junction_count": int(sum(1 for node in result.node_info_list if str(node.node_type) == "junction")),
            "missing_polygon_junction_count": int(len(missing_polygon_nodes)),
            "missing_polygon_junction_nodes": [
                {
                    "node_id": int(node.node_id),
                    "point_rc": [float(node.point_rc[0]), float(node.point_rc[1])],
                    "degree": int(node.degree),
                    "incident_edge_ids": [int(item) for item in tuple(node.incident_edge_ids or ())],
                }
                for node in missing_polygon_nodes
            ],
            "node_geometry_debug": to_jsonable(result.debug_info.get("node_geometry", {})),
        }
        (out_dir / "diagnostic.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
    except Exception as exc:
        payload = {
            "status": "stage_error",
            "error": {
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "traceback": traceback.format_exc(),
            },
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "diagnostic.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload


def skeleton_branch_metrics(mask: np.ndarray) -> dict[str, Any]:
    skeleton01 = np.where(mask > 0, 1, 0).astype(np.uint8)
    neighbor_masks = build_neighbor_mask_map(skeleton01)
    neighbor_count = np.array([bin(int(value)).count("1") for value in range(256)], dtype=np.uint8)
    counts = neighbor_count[neighbor_masks]
    return {
        "skeleton_pixel_count": int(np.count_nonzero(skeleton01)),
        "endpoint_pixel_count": int(np.count_nonzero((skeleton01 > 0) & (counts == 1))),
        "branch_pixel_count": int(np.count_nonzero((skeleton01 > 0) & (counts >= 3))),
    }


def write_mask(path: Path, mask: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), normalize_mask(mask))


def write_gray(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.asarray(image, dtype=np.uint8))


def free_context_gray(free_mask: np.ndarray) -> np.ndarray:
    return np.where(np.asarray(free_mask) > 0, 255, 0).astype(np.uint8)


def boundary_context_gray(free_mask: np.ndarray, boundary_band: np.ndarray) -> np.ndarray:
    image = free_context_gray(free_mask)
    image[np.asarray(boundary_band) > 0] = 150
    return image


def delta_context_gray(
    free_mask: np.ndarray,
    delta_add: np.ndarray,
    delta_remove: np.ndarray,
) -> np.ndarray:
    image = free_context_gray(free_mask)
    image[np.asarray(delta_add) > 0] = 220
    image[np.asarray(delta_remove) > 0] = 70
    return image


def overlay_skeleton(gray: np.ndarray, skeleton_mask: np.ndarray, color_bgr: tuple[int, int, int]) -> np.ndarray:
    image = cv2.cvtColor(np.asarray(gray, dtype=np.uint8), cv2.COLOR_GRAY2BGR)
    image[np.asarray(skeleton_mask) > 0] = color_bgr
    return image


def label_image(image: np.ndarray, text: str) -> np.ndarray:
    canvas = image.copy()
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 24), (245, 245, 245), -1)
    cv2.putText(canvas, text, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 1, cv2.LINE_AA)
    return canvas


def write_skeleton_comparison(
    path: Path,
    gray: np.ndarray,
    baseline_skeleton: np.ndarray,
    variant_skeleton: np.ndarray,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    before = label_image(overlay_skeleton(gray, baseline_skeleton, (0, 255, 255)), "baseline pruned skeleton")
    after = label_image(overlay_skeleton(gray, variant_skeleton, (255, 0, 0)), "smoothed pruned skeleton")
    delta = cv2.cvtColor(np.asarray(gray, dtype=np.uint8), cv2.COLOR_GRAY2BGR)
    removed = (np.asarray(baseline_skeleton) > 0) & (np.asarray(variant_skeleton) == 0)
    added = (np.asarray(variant_skeleton) > 0) & (np.asarray(baseline_skeleton) == 0)
    kept = (np.asarray(variant_skeleton) > 0) & (np.asarray(baseline_skeleton) > 0)
    delta[kept] = (180, 180, 180)
    delta[removed] = (0, 0, 255)
    delta[added] = (0, 220, 0)
    delta = label_image(delta, "skeleton delta: red removed, green added")
    cv2.imwrite(str(path), np.concatenate([before, after, delta], axis=1))


def write_overlay_visuals(base_free: np.ndarray, variant_dir: Path, debug: dict[str, Any], smoothed_free: np.ndarray) -> None:
    boundary_band = debug["boundary_band"]
    delta_add = debug["delta_add"]
    delta_remove = debug["delta_remove"]

    write_mask(variant_dir / "raw_masks" / "boundary_band.png", boundary_band)
    write_mask(variant_dir / "raw_masks" / "delta_add_free.png", delta_add)
    write_mask(variant_dir / "raw_masks" / "delta_remove_free.png", delta_remove)
    write_mask(variant_dir / "raw_masks" / "smoothed_free.png", smoothed_free)

    write_gray(variant_dir / "01_boundary_band.png", boundary_context_gray(base_free, boundary_band))
    write_gray(variant_dir / "02_delta_add_free.png", delta_context_gray(base_free, delta_add, np.zeros_like(delta_remove)))
    write_gray(variant_dir / "03_delta_remove_free.png", delta_context_gray(base_free, np.zeros_like(delta_add), delta_remove))
    write_gray(variant_dir / "04_smoothed_free.png", free_context_gray(smoothed_free))
    write_gray(variant_dir / "05_boundary_delta_context.png", delta_context_gray(base_free, delta_add, delta_remove))


def write_run_overview(run_dir: Path, baseline_geometry: Any, variant_geometries: dict[str, Any]) -> None:
    panels = [label_image(overlay_skeleton(baseline_geometry.gray, baseline_geometry.skeleton_pruned_mask, (0, 255, 255)), "baseline")]
    for name, geometry in variant_geometries.items():
        panels.append(label_image(overlay_skeleton(geometry.gray, geometry.skeleton_pruned_mask, (255, 0, 0)), name))
    max_h = max(panel.shape[0] for panel in panels)
    max_w = max(panel.shape[1] for panel in panels)
    padded = []
    for panel in panels:
        canvas = np.zeros((max_h, max_w, 3), dtype=np.uint8)
        canvas[: panel.shape[0], : panel.shape[1]] = panel
        padded.append(canvas)
    rows = []
    for index in range(0, len(padded), 2):
        row_items = padded[index : index + 2]
        if len(row_items) == 1:
            row_items.append(np.zeros_like(row_items[0]))
        rows.append(np.concatenate(row_items, axis=1))
    cv2.imwrite(str(run_dir / "skeleton_variant_overview.png"), np.concatenate(rows, axis=0))


def variants() -> list[SmoothingVariant]:
    return [
        SmoothingVariant("majority_r025_band035", 0.25, 0.35),
        SmoothingVariant("majority_r025_band035_t025", 0.25, 0.35, 0.25),
        SmoothingVariant("majority_r025_band050", 0.25, 0.50),
    ]


def run_experiment() -> Path:
    run_dir = make_run_dir()
    study_input = build_study_input(DEFAULT_PROJECT_DIR, AREA_ID, run_dir)
    baseline_geometry, baseline_config, _ = run_geometry_on_map(
        study_input,
        study_input.prepared_map,
        study_input.region_mask,
        run_dir,
        "baseline",
    )
    baseline_junction = run_junction_diagnostic(baseline_geometry, baseline_config, run_dir, "baseline")

    base_free = normalize_mask(baseline_geometry.free_mask)
    metrics: dict[str, Any] = {
        "area_id": AREA_ID,
        "project_dir": str(DEFAULT_PROJECT_DIR),
        "baseline": {
            "geometry": skeleton_branch_metrics(baseline_geometry.skeleton_pruned_mask),
            "junction": baseline_junction,
        },
        "variants": {},
    }
    variant_geometries: dict[str, Any] = {}
    for variant in variants():
        variant_dir = run_dir / variant.name
        smoothed_free, debug = apply_smoothing_variant(
            base_free,
            baseline_geometry.region_mask,
            float(baseline_geometry.resolution_m_per_px),
            variant,
        )
        write_overlay_visuals(base_free, variant_dir, debug, smoothed_free)
        variant_raw_map = np.where(smoothed_free > 0, 255, 0).astype(np.uint8)
        geometry_result, config_obj, _ = run_geometry_on_map(
            study_input,
            variant_raw_map,
            baseline_geometry.region_mask,
            run_dir,
            variant.name,
        )
        variant_geometries[variant.name] = geometry_result
        write_skeleton_comparison(
            variant_dir / "06_pruned_skeleton_before_after.png",
            baseline_geometry.gray,
            baseline_geometry.skeleton_pruned_mask,
            geometry_result.skeleton_pruned_mask,
        )
        junction_payload = run_junction_diagnostic(geometry_result, config_obj, run_dir, variant.name)
        variant_metrics = {
            **{key: value for key, value in debug.items() if key not in {"boundary_band", "delta_add", "delta_remove"}},
            "geometry": {
                "raw_skeleton": skeleton_branch_metrics(geometry_result.skeleton_mask),
                "pruned_skeleton": skeleton_branch_metrics(geometry_result.skeleton_pruned_mask),
            },
            "junction": junction_payload,
        }
        metrics["variants"][variant.name] = variant_metrics
        (variant_dir / "smoothing_debug.json").write_text(
            json.dumps(to_jsonable(variant_metrics), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    write_run_overview(run_dir, baseline_geometry, variant_geometries)
    (run_dir / "metrics.json").write_text(json.dumps(to_jsonable(metrics), ensure_ascii=False, indent=2), encoding="utf-8")
    return run_dir


def main() -> None:
    print(run_experiment())


if __name__ == "__main__":
    main()
