import json
import math
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import yaml
from PIL import Image

from algorithms.coverage_planning.contracts import CoveragePlanningDiagnostics
from algorithms.coverage_planning.modes import (
    AUTO_MODE,
    BASIC_MODE,
    CHANNEL_TOPOLOGY_GRAPH_MODE,
)

from ..adapters.coverage_planning_adapter import (
    CoveragePlannerConfig,
    CoveragePlanningRequest,
    build_region_mask_from_polygon,
    preprocess_total_map,
    run_formal_planner_request,
    route_coverage_plan,
    run_channel_topology_graph_adapter,
)

from ..models.annotations import Annotations
from ..models.coverage_path import CoveragePathManager, CoveragePathNode, point_in_polygon
from ..models.map_data import MapData
from .coverage_path_statistics import prepare_statistics_dir, write_room_statistics_file
from .room_identity import area_room_id, normalize_and_validate_area_room_ids
from .rebuild_room_partition_from_segmented_map import (
    RebuildConfig as PartitionRebuildConfig,
    build_partition,
    load_segmented_map,
)


@dataclass(frozen=True)
class CoverageBlockingPolicy:
    block_forbidden_zone: bool = True
    block_virtual_wall: bool = True
    block_no_coverage: bool = True
    block_pass_only: bool = False


DEFAULT_COVERAGE_BLOCKING_POLICY = CoverageBlockingPolicy()


def _normalize_export_planner_config(
    planner_config: Optional[CoveragePlannerConfig],
) -> CoveragePlannerConfig:
    """Return a formal planner config for coverage-repo auto generation."""

    cfg = planner_config or CoveragePlannerConfig(
        coverage_width_m=0.5,
        robot_width_m=0.4,
        open_kernel_m=0.8,
        obstacle_expand_m=0.8,
        auto_rotate=True,
        turn_constraint_enable=True,
    )
    return cfg


def current_timestamp() -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S%z")


def default_coverage_version() -> str:
    tz = timezone(timedelta(hours=8))
    return "master_" + datetime.now(tz).strftime("%Y%m%dT%H%M%S%z")


def world_to_image_pixel(wx: float, wy: float, resolution: float, origin_x: float, origin_y: float,
                         map_height: int) -> Tuple[int, int]:
    """编辑器图像坐标系: 原点在左上角。"""
    px = int(round((wx - origin_x) / resolution))
    py = int(round(map_height - (wy - origin_y) / resolution))
    return px, py


def world_to_grid_pixel(wx: float, wy: float, resolution: float, origin_x: float, origin_y: float) -> Tuple[int, int]:
    """算法消费的 OccupancyGrid / segmented_map 栅格坐标: 原点在左下角。"""
    u = int(round((wx - origin_x) / resolution))
    v = int(round((wy - origin_y) / resolution))
    return u, v


def build_segmented_map(map_data: MapData, annotations: Annotations) -> np.ndarray:
    normalize_and_validate_area_room_ids(annotations.area_labels)
    width = int(map_data.width)
    height = int(map_data.height)
    resolution = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])

    labels = np.zeros((height, width), dtype=np.int32)
    overlap = np.zeros((height, width), dtype=np.uint16)

    for area in sorted(annotations.area_labels, key=area_room_id):
        area_id = area_room_id(area)
        if area_id <= 0 or area_id > 4095:
            raise ValueError(f"area_id out of range: {area_id}")
        if not area.polygon or len(area.polygon) < 3:
            raise ValueError(f"area {area_id} polygon invalid")
        pts = np.array(
            [world_to_grid_pixel(float(wx), float(wy), resolution, origin_x, origin_y) for wx, wy in area.polygon],
            dtype=np.int32,
        ).reshape((-1, 1, 2))
        mask = np.zeros((height, width), dtype=np.uint8)
        cv2.fillPoly(mask, [pts], 255)
        overlap[mask > 0] += 1
        labels[mask > 0] = area_id

    if np.any(overlap > 1):
        raise ValueError("areas overlap in segmented map")
    return labels


def _build_area_mask_image(map_data: MapData, area) -> np.ndarray:
    resolution = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])
    height = int(map_data.height)
    mask = np.zeros((height, int(map_data.width)), dtype=np.uint8)
    if not area.polygon or len(area.polygon) < 3:
        return mask
    pts = np.array(
        [
            world_to_image_pixel(float(wx), float(wy), resolution, origin_x, origin_y, height)
            for wx, wy in area.polygon
        ],
        dtype=np.int32,
    ).reshape((-1, 1, 2))
    cv2.fillPoly(mask, [pts], 255)
    return mask


def _coverage_repo_issue(code: str, message: str) -> str:
    return f"{code}: {message}"


def detect_area_overlap_issues(map_data: MapData, annotations: Annotations) -> List[str]:
    if not map_data.metadata or not annotations.area_labels:
        return []
    resolution = float(map_data.metadata.resolution)
    area_masks = [
        (area_room_id(area), str(getattr(area, "name", area_room_id(area))), _build_area_mask_image(map_data, area))
        for area in sorted(annotations.area_labels, key=area_room_id)
    ]
    issues: List[str] = []
    for index, (left_id, left_name, left_mask) in enumerate(area_masks):
        for right_id, right_name, right_mask in area_masks[index + 1:]:
            overlap_pixels = int(np.count_nonzero((left_mask > 0) & (right_mask > 0)))
            if overlap_pixels <= 0:
                continue
            overlap_area_m2 = float(overlap_pixels) * resolution * resolution
            issues.append(
                _coverage_repo_issue(
                    "area_overlap",
                    (
                        f"区域 {left_id}({left_name}) 与区域 {right_id}({right_name}) "
                        f"重叠 {overlap_pixels} px / {overlap_area_m2:.3f} m^2"
                    ),
                )
            )
    return issues


def _sample_segment_pixels(
    start_xy: Tuple[float, float],
    end_xy: Tuple[float, float],
) -> List[Tuple[int, int]]:
    x0, y0 = float(start_xy[0]), float(start_xy[1])
    x1, y1 = float(end_xy[0]), float(end_xy[1])
    steps = max(1, int(math.ceil(max(abs(x1 - x0), abs(y1 - y0)))))
    points: List[Tuple[int, int]] = []
    for index in range(steps + 1):
        ratio = float(index) / float(steps)
        points.append((int(round(x0 + (x1 - x0) * ratio)), int(round(y0 + (y1 - y0) * ratio))))
    return list(dict.fromkeys(points))


def detect_path_consistency_issues(
    map_data: MapData,
    annotations: Annotations,
    path_manager: Optional[CoveragePathManager],
) -> List[str]:
    if path_manager is None or not path_manager.nodes or not map_data.metadata:
        return []
    area_by_id = {area_room_id(area): area for area in annotations.area_labels}
    masks_by_area_id = {
        area_room_id(area): _build_area_mask_image(map_data, area)
        for area in annotations.area_labels
    }
    if masks_by_area_id:
        stacked = np.zeros((int(map_data.height), int(map_data.width)), dtype=np.uint16)
        for mask in masks_by_area_id.values():
            stacked[mask > 0] += 1
        overlap_mask = stacked > 1
    else:
        overlap_mask = np.zeros((int(map_data.height), int(map_data.width)), dtype=bool)

    issues: List[str] = []
    nodes_by_room: Dict[int, List[CoveragePathNode]] = {}
    for node in path_manager.nodes:
        nodes_by_room.setdefault(int(node.room), []).append(node)

    height = int(map_data.height)
    width = int(map_data.width)
    for room_id, nodes in sorted(nodes_by_room.items()):
        if room_id not in area_by_id:
            issues.append(
                _coverage_repo_issue(
                    "path_room_missing",
                    f"覆盖路径引用不存在的区域 room={room_id}，点数={len(nodes)}",
                )
            )
            continue
        area_mask = masks_by_area_id[int(room_id)]
        sorted_nodes = sorted(nodes, key=lambda item: int(item.id))
        outside_point_count = 0
        overlap_point_count = 0
        out_of_bounds_count = 0
        foreign_area_hits: Dict[int, int] = {}
        for node in sorted_nodes:
            col = int(round(float(node.u)))
            row = int(round(float(node.v)))
            if row < 0 or row >= height or col < 0 or col >= width:
                out_of_bounds_count += 1
                continue
            if area_mask[row, col] == 0:
                outside_point_count += 1
                for other_area_id, other_mask in masks_by_area_id.items():
                    if other_area_id != room_id and other_mask[row, col] > 0:
                        foreign_area_hits[int(other_area_id)] = foreign_area_hits.get(int(other_area_id), 0) + 1
            if bool(overlap_mask[row, col]):
                overlap_point_count += 1

        crossing_segment_count = 0
        for current, nxt in zip(sorted_nodes, sorted_nodes[1:]):
            if int(current.room) != int(nxt.room):
                continue
            segment_crosses_outside = False
            for col, row in _sample_segment_pixels((float(current.u), float(current.v)), (float(nxt.u), float(nxt.v))):
                if row < 0 or row >= height or col < 0 or col >= width or area_mask[row, col] == 0:
                    segment_crosses_outside = True
                    break
            if segment_crosses_outside:
                crossing_segment_count += 1

        if out_of_bounds_count:
            issues.append(
                _coverage_repo_issue(
                    "path_point_out_of_map",
                    f"区域 {room_id} 覆盖路径有 {out_of_bounds_count} 个点落在地图外",
                )
            )
        if outside_point_count:
            foreign_summary = ""
            if foreign_area_hits:
                foreign_summary = "，其中落入其它区域: " + ", ".join(
                    f"{area_id}:{count}"
                    for area_id, count in sorted(foreign_area_hits.items())
                )
            issues.append(
                _coverage_repo_issue(
                    "path_point_outside_room",
                    f"区域 {room_id} 覆盖路径有 {outside_point_count} 个点落在所属区域外{foreign_summary}",
                )
            )
        if crossing_segment_count:
            issues.append(
                _coverage_repo_issue(
                    "path_segment_crosses_room_boundary",
                    f"区域 {room_id} 覆盖路径有 {crossing_segment_count} 条相邻路径段跨出所属区域",
                )
            )
        if overlap_point_count:
            issues.append(
                _coverage_repo_issue(
                    "path_point_in_area_overlap",
                    f"区域 {room_id} 覆盖路径有 {overlap_point_count} 个点落在区域重叠像素内",
                )
            )
    return issues


def build_room_binary(map_data: MapData, annotations: Annotations, area) -> Tuple[np.ndarray, Tuple[int, int]]:
    map_binary = build_total_free_map(map_data, annotations)

    resolution = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])
    height = int(map_data.height)

    pts = np.array(
        [world_to_image_pixel(float(wx), float(wy), resolution, origin_x, origin_y, height) for wx, wy in area.polygon],
        dtype=np.int32,
    ).reshape((-1, 1, 2))
    roi_mask = np.zeros_like(map_binary, dtype=np.uint8)
    cv2.fillPoly(roi_mask, [pts], 255)

    final_binary = cv2.bitwise_and(map_binary, roi_mask)

    centroid_x = sum(float(p[0]) for p in area.polygon) / len(area.polygon)
    centroid_y = sum(float(p[1]) for p in area.polygon) / len(area.polygon)
    start = world_to_image_pixel(centroid_x, centroid_y, resolution, origin_x, origin_y, height)
    return final_binary, start


def _fill_world_polygon(
    map_binary: np.ndarray,
    points,
    *,
    resolution: float,
    origin_x: float,
    origin_y: float,
    height: int,
    value: int,
) -> None:
    if not points or len(points) < 3:
        return
    zone_pts = np.array(
        [world_to_image_pixel(float(wx), float(wy), resolution, origin_x, origin_y, height) for wx, wy in points],
        dtype=np.int32,
    ).reshape((-1, 1, 2))
    cv2.fillPoly(map_binary, [zone_pts], int(value))


def _draw_world_polyline(
    map_binary: np.ndarray,
    points,
    *,
    resolution: float,
    origin_x: float,
    origin_y: float,
    height: int,
    value: int,
) -> None:
    if not points or len(points) < 2:
        return
    line_points = [
        world_to_image_pixel(float(wx), float(wy), resolution, origin_x, origin_y, height)
        for wx, wy in points
    ]
    for start, end in zip(line_points, line_points[1:]):
        cv2.line(map_binary, start, end, int(value), thickness=3)


def _apply_derived_regions_to_free_map(map_binary: np.ndarray, annotations: Annotations, action_type: str) -> None:
    iter_regions = getattr(annotations, "iter_derived_constraint_regions", None)
    decode_region_mask = getattr(annotations, "decode_derived_constraint_region_mask", None)
    if not callable(iter_regions) or not callable(decode_region_mask):
        return
    for region in iter_regions(action_type):
        x, y, width, height = (int(value) for value in region.bbox_px)
        if width <= 0 or height <= 0:
            continue
        region_mask = decode_region_mask(region)
        if region_mask.size == 0:
            continue
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(map_binary.shape[1], x + width)
        y1 = min(map_binary.shape[0], y + height)
        if x1 <= x0 or y1 <= y0:
            continue
        region_x0 = x0 - x
        region_y0 = y0 - y
        region_x1 = region_x0 + (x1 - x0)
        region_y1 = region_y0 + (y1 - y0)
        roi = map_binary[y0:y1, x0:x1]
        roi_region = region_mask[region_y0:region_y1, region_x0:region_x1]
        roi[roi_region > 0] = 0


def build_total_free_map(
    map_data: MapData,
    annotations: Annotations,
    *,
    blocking_policy: CoverageBlockingPolicy | None = None,
) -> np.ndarray:
    policy = blocking_policy or DEFAULT_COVERAGE_BLOCKING_POLICY
    img_arr = np.array(map_data.get_display_image())
    map_binary = np.zeros_like(img_arr, dtype=np.uint8)
    map_binary[img_arr > 250] = 255

    resolution = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])
    height = int(map_data.height)

    if policy.block_forbidden_zone:
        for zone in annotations.forbidden_zones:
            _fill_world_polygon(
                map_binary,
                zone.polygon,
                resolution=resolution,
                origin_x=origin_x,
                origin_y=origin_y,
                height=height,
                value=0,
            )

    if policy.block_pass_only:
        for zone in annotations.pass_only_zones:
            _fill_world_polygon(
                map_binary,
                zone.polygon,
                resolution=resolution,
                origin_x=origin_x,
                origin_y=origin_y,
                height=height,
                value=0,
            )

    iter_segments = getattr(annotations, "iter_constraint_segments", None)
    if callable(iter_segments):
        if policy.block_forbidden_zone:
            for segment in iter_segments("forbidden_zone", closed=True):
                _fill_world_polygon(
                    map_binary,
                    segment.points,
                    resolution=resolution,
                    origin_x=origin_x,
                    origin_y=origin_y,
                    height=height,
                    value=0,
                )
        if policy.block_virtual_wall:
            for segment in iter_segments("virtual_wall", closed=False):
                _draw_world_polyline(
                    map_binary,
                    segment.points,
                    resolution=resolution,
                    origin_x=origin_x,
                    origin_y=origin_y,
                    height=height,
                    value=0,
                )
        if policy.block_no_coverage:
            for segment in iter_segments("no_coverage", closed=True):
                _fill_world_polygon(
                    map_binary,
                    segment.points,
                    resolution=resolution,
                    origin_x=origin_x,
                    origin_y=origin_y,
                    height=height,
                    value=0,
                )

    if policy.block_forbidden_zone:
        _apply_derived_regions_to_free_map(map_binary, annotations, "forbidden_zone")
    if policy.block_no_coverage:
        _apply_derived_regions_to_free_map(map_binary, annotations, "no_coverage")

    return map_binary


def build_selected_area_planning_map(
    total_free_map: np.ndarray,
    region_mask: np.ndarray,
) -> np.ndarray:
    return np.where((np.asarray(total_free_map) > 0) & (np.asarray(region_mask) > 0), 255, 0).astype(np.uint8)


def build_area_region_mask(map_data: MapData, area) -> np.ndarray:
    resolution = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])
    height = int(map_data.height)
    polygon_px = [
        world_to_image_pixel(float(wx), float(wy), resolution, origin_x, origin_y, height)
        for wx, wy in area.polygon
    ]
    region_mask = build_region_mask_from_polygon(
        shape=(int(map_data.height), int(map_data.width)),
        polygon_px=polygon_px,
    )
    if region_mask is None:
        raise ValueError(f"area {area_room_id(area)} polygon invalid")
    return region_mask


def build_path_segments(nodes: List[CoveragePathNode]) -> List[Dict]:
    if not nodes:
        return []
    segments: List[Dict] = []
    start_idx = 0
    current_segment = int(nodes[0].segment)
    for idx, node in enumerate(nodes[1:], start=1):
        if int(node.segment) != current_segment:
            segments.append({
                "segment_id": current_segment,
                "start_index": start_idx,
                "end_index": idx - 1,
                "type": "source_chunk",
            })
            start_idx = idx
            current_segment = int(node.segment)
    segments.append({
        "segment_id": current_segment,
        "start_index": start_idx,
        "end_index": len(nodes) - 1,
        "type": "source_chunk",
    })
    return segments


def build_return_points(poses: List[Dict]) -> List[Dict]:
    points = []
    for idx, pose in enumerate(poses[:2], start=1):
        points.append({
            "x": float(pose["x"]),
            "y": float(pose["y"]),
            "priority": idx,
        })
    return points


def repair_path_rooms_from_area_labels(
    path_manager: Optional[CoveragePathManager],
    annotations: Annotations,
) -> int:
    """Assign path room_id from the containing Area Label polygon before save/export."""

    if path_manager is None or not path_manager.nodes or not annotations.area_labels:
        return 0

    normalize_and_validate_area_room_ids(annotations.area_labels)
    areas = sorted(annotations.area_labels, key=area_room_id)
    changed = 0

    for node in path_manager.nodes:
        for area in areas:
            if area.polygon and point_in_polygon((float(node.x), float(node.y)), area.polygon):
                inferred_room = area_room_id(area)
                if int(node.room) != inferred_room:
                    node.room_id = inferred_room
                    changed += 1
                break

    if changed:
        path_manager.renumber_nodes()
        path_manager.is_dirty = True
    return changed


def build_planner_diagnostics_payload(diagnostics: CoveragePlanningDiagnostics | None) -> Dict[str, Any]:
    """Convert formal routing diagnostics into a stable export payload."""

    if diagnostics is None:
        return CoveragePlanningDiagnostics().to_summary_dict()
    return diagnostics.to_summary_dict()


def make_common_meta(coverage_version: str) -> Dict:
    return {
        "source": "editor_auto",
        "status": "candidate",
        "approved_by": "",
        "coverage_version": coverage_version,
        "master_version": "",
        "candidate_version": coverage_version,
        "locked": False,
        "editable": True,
        "pending_review": True,
        "approved_at": "",
        "generated_at": current_timestamp(),
    }


def write_segmented_map_files(repo_dir: Path, map_id: str, map_version: int, coverage_version: str,
                              labels: np.ndarray, map_data: MapData) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    labels.tofile(repo_dir / "segmented_map_master.bin")
    preview = np.zeros(labels.shape, dtype=np.uint8)
    nonzero = labels > 0
    if np.any(nonzero):
        max_label = max(int(labels[nonzero].max()), 1)
        preview[nonzero] = np.clip(labels[nonzero] * (255.0 / max_label), 1, 255).astype(np.uint8)
    Image.fromarray(preview).save(repo_dir / "segmented_map.png")

    meta = {
        "map_id": map_id,
        "map_version": str(map_version),
        "coverage_version": coverage_version,
        "encoding": "32SC1",
        "width": int(map_data.width),
        "height": int(map_data.height),
        "step": int(map_data.width) * 4,
        "source": "editor_export",
        "frame_id": "map",
        "resolution": float(map_data.metadata.resolution),
        "origin": {
            "x": float(map_data.metadata.origin[0]),
            "y": float(map_data.metadata.origin[1]),
            "z": float(map_data.metadata.origin[2]),
        },
    }
    (repo_dir / "segmented_map_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_paths_yaml(repo_dir: Path, map_id: str, map_version: int, coverage_version: str,
                     room_paths: List[Dict]) -> None:
    payload = {
        "map_id": map_id,
        "map_version": map_version,
        "coverage_version": coverage_version,
        "meta": make_common_meta(coverage_version),
        "paths": room_paths,
    }
    with (repo_dir / "coverage_path_master.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)


def build_global_room_ids_from_paths(room_paths: List[Dict]) -> List[int]:
    return [int(item["room_id"]) for item in room_paths]


def write_sequence_yaml(repo_dir: Path, map_id: str, map_version: int, coverage_version: str,
                        room_ids: List[int]) -> None:
    payload = {
        "map_id": map_id,
        "map_version": map_version,
        "coverage_version": coverage_version,
        "meta": make_common_meta(coverage_version),
        "room_sequence_spec": {
            "map_id": map_id,
            "map_version": map_version,
            "coverage_version": coverage_version,
            "revision": 1,
            "name": "editor_auto_candidate",
            "allow_auto_fill": False,
            "fixed_prefix_rooms": [],
            "fixed_suffix_rooms": [],
            "sequences": [{"room_ids": room_ids}],
        },
    }
    with (repo_dir / "room_sequence_master.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)


def write_meta_json(
    repo_dir: Path,
    map_id: str,
    map_version: int,
    coverage_version: str,
    room_count: int,
    path_count: int,
    room_planner_diagnostics: Dict[int, Dict[str, Any]],
) -> None:
    payload = {
        "map_id": map_id,
        "map_version": str(map_version),
        "coverage_version": coverage_version,
        "source": "editor_auto",
        "status": "candidate",
        "approved_by": "",
        "master_version": "",
        "candidate_version": coverage_version,
        "locked": False,
        "editable": True,
        "pending_review": True,
        "approved_at": "",
        "generated_at": current_timestamp(),
        "rooms": room_count,
        "paths": path_count,
        "planner_diagnostics_by_room": {
            str(room_id): room_planner_diagnostics[int(room_id)]
            for room_id in sorted(room_planner_diagnostics)
        },
        "failed_rooms": [],
        "continue_on_room_failure": False,
        "segmentation_sec": 0.0,
        "sequence_sec": 0.0,
        "exploration_sec": 0.0,
    }
    (repo_dir / "meta.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_outputs(labels: np.ndarray, room_paths: List[Dict], room_ids: List[int]) -> None:
    valid_room_ids = sorted(int(v) for v in np.unique(labels) if int(v) > 0)
    if not valid_room_ids:
        raise ValueError("segmented_map has no valid room labels")
    room_set = set(valid_room_ids)

    for item in room_paths:
        room_id = int(item["room_id"])
        if room_id not in room_set:
            raise ValueError(f"path room_id not in segmented_map: {room_id}")
        poses = item.get("poses", [])
        if not poses:
            raise ValueError(f"path poses empty for room {room_id}")
        for seg in item.get("segments", []):
            start_index = int(seg["start_index"])
            end_index = int(seg["end_index"])
            if start_index < 0 or end_index >= len(poses) or start_index > end_index:
                raise ValueError(f"segment index invalid for room {room_id}")

    if not room_ids:
        raise ValueError("room sequence is empty")
    seen_room_ids = set()
    for room_id in room_ids:
        room_id = int(room_id)
        if room_id not in room_set:
            raise ValueError(f"sequence room_id not in segmented_map: {room_id}")
        if room_id in seen_room_ids:
            raise ValueError(f"duplicate room_id in sequence: {room_id}")
        seen_room_ids.add(room_id)


def write_room_partition(repo_dir: Path, map_id: str, map_version: int, coverage_version: str) -> None:
    labels_loaded, segmented_meta = load_segmented_map(
        repo_dir / "segmented_map_master.bin",
        repo_dir / "segmented_map_meta.json",
    )
    partition = build_partition(labels_loaded, segmented_meta, PartitionRebuildConfig())
    partition["map_id"] = map_id
    partition["map_version"] = map_version
    partition["meta"] = make_common_meta(coverage_version)
    with (repo_dir / "room_partition_master.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(partition, f, allow_unicode=True, sort_keys=False)


def append_generated_path(manager: CoveragePathManager, map_data: MapData, area, path_world) -> None:
    res = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])
    height = int(map_data.height)
    base_idx = len(manager.nodes)
    for idx, pose in enumerate(path_world):
        u = (pose.x - origin_x) / res
        v = height - (pose.y - origin_y) / res
        manager.nodes.append(CoveragePathNode(
            id=base_idx + idx,
            room=area_room_id(area),
            segment=0,
            x=float(pose.x),
            y=float(pose.y),
            yaw=float(pose.theta),
            u=float(u),
            v=float(v),
            acc_dist=0.0,
            room_dist=0.0,
            seg_dist=0.0,
        ))
    manager.renumber_nodes()
    manager.is_dirty = True


def ensure_paths(
    map_data: MapData,
    annotations: Annotations,
    path_manager: Optional[CoveragePathManager],
    planner_config: Optional[CoveragePlannerConfig],
    auto_generate_missing: bool,
    allow_partial_export: bool,
) -> List[Tuple[int, List[CoveragePathNode], Dict[str, Any]]]:
    repair_path_rooms_from_area_labels(path_manager, annotations)

    existing_by_room: Dict[int, List[CoveragePathNode]] = {}
    if path_manager is not None and path_manager.nodes:
        for node in path_manager.nodes:
            existing_by_room.setdefault(int(node.room), []).append(node)
    areas = sorted(annotations.area_labels, key=area_room_id)
    if allow_partial_export and 0 in existing_by_room and areas:
        area_ids = {area_room_id(area) for area in areas}
        if len(area_ids) == 1:
            target_room = next(iter(area_ids))
            if target_room not in existing_by_room:
                existing_by_room[target_room] = list(existing_by_room[0])
    if not existing_by_room and not auto_generate_missing:
        raise ValueError("no coverage paths available; auto-generation disabled")
    normalized_config = _normalize_export_planner_config(planner_config)
    planner_mode = getattr(normalized_config, "planner_mode", BASIC_MODE)
    total_free_map = build_total_free_map(map_data, annotations)

    paths: List[Tuple[int, List[CoveragePathNode], Dict[str, Any]]] = []
    for area in areas:
        room_id = area_room_id(area)
        if room_id in existing_by_room and existing_by_room[room_id]:
            nodes = sorted(existing_by_room[room_id], key=lambda node: node.id)
            paths.append((room_id, nodes, build_planner_diagnostics_payload(None)))
            continue
        if not auto_generate_missing:
            if allow_partial_export:
                continue
            raise ValueError(f"missing coverage path for room {room_id}")

        _, start_px = build_room_binary(map_data, annotations, area)
        region_mask = build_area_region_mask(map_data, area)
        selected_area_planning_map = build_selected_area_planning_map(total_free_map, region_mask)
        request = CoveragePlanningRequest(
            prepared_map=preprocess_total_map(
                raw_map=selected_area_planning_map,
                resolution_m_per_px=float(map_data.metadata.resolution),
                open_kernel_m=float(getattr(normalized_config, "open_kernel_m", 0.6)),
                obstacle_expand_m=float(getattr(normalized_config, "obstacle_expand_m", 0.6)),
                region_mask=region_mask,
            ),
            map_resolution=float(map_data.metadata.resolution),
            starting_position_px=start_px,
            map_origin_xy=(float(map_data.metadata.origin[0]), float(map_data.metadata.origin[1])),
            region_mask=region_mask,
            region_polygon_px=tuple(
                world_to_image_pixel(
                    float(wx),
                    float(wy),
                    float(map_data.metadata.resolution),
                    float(map_data.metadata.origin[0]),
                    float(map_data.metadata.origin[1]),
                    int(map_data.height),
                )
                for wx, wy in area.polygon
            ),
            map_yaml_path=Path(map_data.yaml_path) if map_data.yaml_path else None,
            public_config=replace(normalized_config, write_artifacts=True),
        )
        if planner_mode in {AUTO_MODE, CHANNEL_TOPOLOGY_GRAPH_MODE}:
            result = (
                route_coverage_plan(request)
                if planner_mode == AUTO_MODE
                else run_channel_topology_graph_adapter(request)
            )
            if not result.success or not result.path:
                raise RuntimeError(f"coverage planning failed for room {room_id}: {result.error_message}")
            path_world = result.path
        else:
            result = run_formal_planner_request(request, planner_mode)
            if not result.success or not result.path:
                raise RuntimeError(f"coverage planning failed for room {room_id}: {result.error_message}")
            path_world = result.path

        temp_manager = CoveragePathManager()
        append_generated_path(temp_manager, map_data, area, path_world)
        paths.append((room_id, list(temp_manager.nodes), build_planner_diagnostics_payload(result.diagnostics)))
        if path_manager is not None:
            append_generated_path(path_manager, map_data, area, path_world)
    return paths


@dataclass
class CoverageRepoPreflightResult:
    ok: bool
    issues: List[str]
    output_root: Path
    repo_dir: Path
    expected_files: List[str]
    area_count: int
    warnings: List[str] = field(default_factory=list)


def run_export_preflight(
    map_data: MapData,
    annotations: Annotations,
    output_root: str,
    map_id: str,
    path_manager: Optional[CoveragePathManager] = None,
) -> CoverageRepoPreflightResult:
    output_root_path = Path(output_root).expanduser().resolve()
    repo_dir = output_root_path / map_id
    issues: List[str] = []

    if not map_data.metadata:
        issues.append("未加载地图元数据")
    if not annotations.area_labels:
        issues.append("未标注任何区域")
    if not output_root_path.exists():
        parent = output_root_path.parent
        if not parent.exists() or not os.access(parent, os.W_OK):
            issues.append(f"输出目录不可创建: {output_root_path}")
    elif not os.access(output_root_path, os.W_OK):
        issues.append(f"输出目录不可写: {output_root_path}")
    issues.extend(detect_area_overlap_issues(map_data, annotations))
    path_warnings = detect_path_consistency_issues(map_data, annotations, path_manager)

    expected_files = [
        f"{map_id}/coverage_path_master.yaml",
        f"{map_id}/room_sequence_master.yaml",
        f"{map_id}/room_partition_master.yaml",
        f"{map_id}/segmented_map_master.bin",
        f"{map_id}/segmented_map_meta.json",
        f"{map_id}/segmented_map.png",
        f"{map_id}/meta.json",
    ]
    return CoverageRepoPreflightResult(
        ok=not issues,
        issues=issues,
        warnings=path_warnings,
        output_root=output_root_path,
        repo_dir=repo_dir,
        expected_files=expected_files,
        area_count=len(annotations.area_labels),
    )


@dataclass
class CoverageRepoExportResult:
    repo_dir: Path
    coverage_version: str
    room_count: int
    path_count: int
    output_files: List[str]
    planner_diagnostics_by_room: Dict[int, Dict[str, Any]]


def export_coverage_repo(
    map_data: MapData,
    annotations: Annotations,
    output_root: str,
    map_id: str,
    map_version: int = 1,
    coverage_version: Optional[str] = None,
    path_manager: Optional[CoveragePathManager] = None,
    planner_config: Optional[CoveragePlannerConfig] = None,
    nav2_root: Optional[str] = None,
    auto_generate_missing: bool = False,
    allow_partial_export: bool = False,
) -> CoverageRepoExportResult:
    preflight = run_export_preflight(map_data, annotations, output_root, map_id, path_manager=path_manager)
    if not preflight.ok:
        raise ValueError("; ".join(preflight.issues))

    coverage_version = coverage_version or default_coverage_version()
    repo_dir = Path(output_root).expanduser().resolve() / map_id
    labels = build_segmented_map(map_data, annotations)
    write_segmented_map_files(repo_dir, map_id, map_version, coverage_version, labels, map_data)

    room_paths: List[Dict] = []
    room_planner_diagnostics: Dict[int, Dict[str, Any]] = {}
    statistics_dir = repo_dir / "coverage_path_statistics"
    prepare_statistics_dir(statistics_dir)

    for room_id, nodes, planner_diagnostics in (
        ensure_paths(
            map_data,
            annotations,
            path_manager,
            planner_config,
            auto_generate_missing,
            allow_partial_export,
        )
    ):
        nodes = list(nodes)
        write_room_statistics_file(statistics_dir, int(room_id), nodes)
        poses = [{"x": float(node.x), "y": float(node.y), "theta": float(node.yaw)} for node in nodes]
        room_paths.append({
            "room_id": int(room_id),
            "segments": build_path_segments(nodes),
            "return_points": build_return_points(poses),
            "confirmed": False,
            "planner_diagnostics": planner_diagnostics,
            "poses": poses,
        })
        room_planner_diagnostics[int(room_id)] = planner_diagnostics

    room_ids = build_global_room_ids_from_paths(room_paths)
    validate_outputs(labels, room_paths, room_ids)
    write_paths_yaml(repo_dir, map_id, map_version, coverage_version, room_paths)
    write_sequence_yaml(repo_dir, map_id, map_version, coverage_version, room_ids)
    write_meta_json(
        repo_dir,
        map_id,
        map_version,
        coverage_version,
        len(room_ids),
        len(room_paths),
        room_planner_diagnostics,
    )
    write_room_partition(repo_dir, map_id, map_version, coverage_version)
    output_files = list(preflight.expected_files)
    output_files.extend(
        f"{map_id}/coverage_path_statistics/coverage_path_statistics_{room_id}.txt"
        for room_id in room_ids
    )
    return CoverageRepoExportResult(
        repo_dir=repo_dir,
        coverage_version=coverage_version,
        room_count=len(room_ids),
        path_count=len(room_paths),
        output_files=output_files,
        planner_diagnostics_by_room=room_planner_diagnostics,
    )
