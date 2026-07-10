from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from ..models.annotations import Annotations
from ..models.coverage_path import CoveragePathManager, CoveragePathNode, recompute_dist
from ..models.map_data import MapData


@dataclass
class CoverageRepoImportSummary:
    map_id: str
    map_yaml: str
    rooms: int
    nodes: int
    segments: int
    area_labels: int


@dataclass
class CoverageRepoImportResult:
    map_id: str
    loaded_map_path: str
    imported_rooms: int
    imported_nodes: int
    imported_segments: int
    imported_area_labels: int
    summary: CoverageRepoImportSummary


def detect_yaml_kind(yaml_path: str) -> str:
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if _is_map_yaml(data):
        return "map"
    if _is_coverage_repo_yaml(data):
        return "coverage_repo"
    return "unknown"


def import_coverage_repo(
    coverage_yaml_path: str,
    map_data: MapData,
    path_manager: CoveragePathManager,
    annotations: Optional[Annotations] = None,
    restore_area_labels: bool = True,
) -> CoverageRepoImportResult:
    coverage_path = Path(coverage_yaml_path).expanduser().resolve()
    with coverage_path.open("r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}

    if not _is_coverage_repo_yaml(payload):
        raise ValueError("not a valid coverage repo yaml")

    map_id = str(payload.get("map_id", "")).strip()
    loaded_map_path = _ensure_matching_map_loaded(coverage_path, map_id, map_data)

    nodes = _build_nodes_from_payload(payload, map_data)
    path_manager.set_nodes(recompute_dist(nodes))
    path_manager.current_file_path = str(coverage_path)
    path_manager.is_dirty = False

    area_label_count = 0
    if annotations is not None and restore_area_labels:
        partition_path = coverage_path.with_name("room_partition_master.yaml")
        if partition_path.exists():
            area_label_count = _import_room_partition(partition_path, annotations)

    segment_count = len(
        [seg for item in payload.get("paths", []) for seg in item.get("segments", [])]
    )
    summary = CoverageRepoImportSummary(
        map_id=map_id,
        map_yaml=loaded_map_path,
        rooms=len(payload.get("paths", [])),
        nodes=len(nodes),
        segments=segment_count,
        area_labels=area_label_count,
    )
    return CoverageRepoImportResult(
        map_id=map_id,
        loaded_map_path=loaded_map_path,
        imported_rooms=summary.rooms,
        imported_nodes=summary.nodes,
        imported_segments=segment_count,
        imported_area_labels=area_label_count,
        summary=summary,
    )


def import_area_labels_json(area_json_path: str, annotations: Annotations) -> int:
    area_path = Path(area_json_path).expanduser().resolve()
    with area_path.open("r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}

    areas = payload.get("areas", [])
    annotations.area_labels = []
    max_area_id = 0
    for item in areas:
        area_id = int(item.get("area_id", 0))
        polygon = item.get("polygon") or []
        if area_id <= 0 or len(polygon) < 3:
            continue
        name = str(item.get("name", f"Room {area_id}"))
        annotations.add_area_label(
            [(float(p[0]), float(p[1])) for p in polygon],
            name=name,
            area_id=area_id,
        )
        max_area_id = max(max_area_id, area_id)
    annotations._next_area_id = max(max_area_id + 1, annotations._next_area_id)
    return len(annotations.area_labels)


def _is_map_yaml(data: Dict) -> bool:
    return isinstance(data, dict) and "image" in data and "resolution" in data and "origin" in data


def _is_coverage_repo_yaml(data: Dict) -> bool:
    return isinstance(data, dict) and "map_id" in data and isinstance(data.get("paths"), list)


def _ensure_matching_map_loaded(coverage_path: Path, map_id: str, map_data: MapData) -> str:
    current_map_id = Path(map_data.yaml_path).stem if map_data.yaml_path else ""
    if map_data.metadata and current_map_id == map_id:
        return map_data.yaml_path

    for candidate in _candidate_map_paths(coverage_path, map_id):
        if candidate.exists() and map_data.load(str(candidate)):
            return str(candidate)

    if map_data.metadata:
        raise ValueError(
            f"coverage map_id={map_id} does not match current map={current_map_id}, and no matching map yaml was found"
        )
    raise ValueError(f"could not locate base map yaml for coverage map_id={map_id}")


def _candidate_map_paths(coverage_path: Path, map_id: str) -> List[Path]:
    repo_dir = coverage_path.parent
    output_root = repo_dir.parent
    candidates: List[Path] = []

    project_json_candidates = [
        output_root / "project.json",
        output_root.parent / "project.json",
    ]
    for project_json in project_json_candidates:
        if not project_json.exists():
            continue
        try:
            import json

            data = json.loads(project_json.read_text(encoding="utf-8"))
            map_yaml_path = str(data.get("map_yaml_path", "")).strip()
            if map_yaml_path:
                map_yaml = Path(map_yaml_path).expanduser()
                if map_yaml.is_absolute():
                    candidates.append(map_yaml)
                else:
                    candidates.append((project_json.parent / map_yaml).resolve())
        except Exception:
            pass

    candidates.append((output_root / f"{map_id}.yaml").resolve())
    candidates.append((output_root / "map.yaml").resolve())

    unique: List[Path] = []
    seen = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _build_nodes_from_payload(payload: Dict, map_data: MapData) -> List[CoveragePathNode]:
    if not map_data.metadata:
        raise ValueError("map must be loaded before importing coverage repo")

    resolution = float(map_data.metadata.resolution)
    origin_x = float(map_data.metadata.origin[0])
    origin_y = float(map_data.metadata.origin[1])
    height = int(map_data.height)

    nodes: List[CoveragePathNode] = []
    global_id = 0
    for item in payload.get("paths", []):
        room_id = int(item.get("room_id", 0))
        poses = item.get("poses", [])
        if not poses:
            continue

        segment_ids = _expand_segment_ids(item.get("segments", []), len(poses))
        for idx, pose in enumerate(poses):
            x = float(pose["x"])
            y = float(pose["y"])
            yaw = float(pose.get("theta", 0.0))
            u = (x - origin_x) / resolution
            v = height - (y - origin_y) / resolution
            nodes.append(
                CoveragePathNode(
                    id=global_id,
                    room=room_id,
                    segment=segment_ids[idx],
                    x=x,
                    y=y,
                    yaw=yaw,
                    u=u,
                    v=v,
                    acc_dist=0.0,
                    room_dist=0.0,
                    seg_dist=0.0,
                )
            )
            global_id += 1
    return nodes


def _expand_segment_ids(segments: List[Dict], pose_count: int) -> List[int]:
    if pose_count <= 0:
        return []
    if not segments:
        return [0] * pose_count

    segment_ids = [0] * pose_count
    covered = [False] * pose_count
    for seg in segments:
        segment_id = int(seg.get("segment_id", 0))
        start_index = int(seg.get("start_index", 0))
        end_index = int(seg.get("end_index", pose_count - 1))
        if start_index < 0 or end_index >= pose_count or start_index > end_index:
            raise ValueError(
                f"invalid segment range: segment_id={segment_id}, start={start_index}, end={end_index}, poses={pose_count}"
            )
        for idx in range(start_index, end_index + 1):
            segment_ids[idx] = segment_id
            covered[idx] = True

    if not all(covered):
        first_defined = next((segment_ids[idx] for idx, ok in enumerate(covered) if ok), 0)
        for idx, ok in enumerate(covered):
            if not ok:
                segment_ids[idx] = first_defined
    return segment_ids


def _import_room_partition(partition_yaml_path: Path, annotations: Annotations) -> int:
    with partition_yaml_path.open("r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}

    rooms = payload.get("rooms", [])
    annotations.area_labels = []
    max_area_id = 0
    for room in rooms:
        room_id = int(room.get("room_id", 0))
        polygon = room.get("polygon") or []
        if len(polygon) < 3:
            continue
        world_polygon = [(float(p[0]), float(p[1])) for p in polygon]
        annotations.add_area_label(world_polygon, name=f"Room {room_id}", area_id=room_id)
        max_area_id = max(max_area_id, room_id)
    annotations._next_area_id = max(max_area_id + 1, annotations._next_area_id)
    return len(annotations.area_labels)
