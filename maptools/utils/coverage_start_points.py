"""Project-local persistence for remembered coverage start points."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Mapping

from ..models.annotations import AreaLabel, Annotations
from ..models.coverage_path import point_in_polygon
from .room_identity import area_room_id

COVERAGE_START_POINTS_SCHEMA_VERSION = 1
COVERAGE_START_POINTS_FILENAME = "coverage_start_points.json"


def coverage_start_points_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / COVERAGE_START_POINTS_FILENAME


def area_label_fingerprint(area_label: AreaLabel) -> str:
    """Return a stable fingerprint for an area polygon, independent of name."""

    normalized_points = [
        [round(float(x), 6), round(float(y), 6)]
        for x, y in area_label.polygon
    ]
    payload = json.dumps(
        {
            "room_id": area_room_id(area_label),
            "polygon": normalized_points,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def valid_start_point_for_area(area_label: AreaLabel, start_world_xy) -> tuple[float, float] | None:
    if start_world_xy is None or len(area_label.polygon) < 3:
        return None
    point = (float(start_world_xy[0]), float(start_world_xy[1]))
    if not point_in_polygon(point, area_label.polygon):
        return None
    return point


def filter_valid_start_points(
    annotations: Annotations,
    start_points_by_area_id: Mapping[int, tuple[float, float]],
) -> dict[int, tuple[float, float]]:
    areas_by_id = {area_room_id(area): area for area in annotations.area_labels}
    valid: dict[int, tuple[float, float]] = {}
    for area_id, point in dict(start_points_by_area_id or {}).items():
        area = areas_by_id.get(int(area_id))
        if area is None:
            continue
        valid_point = valid_start_point_for_area(area, point)
        if valid_point is not None:
            valid[int(area_id)] = valid_point
    return valid


def build_coverage_start_points_payload(
    annotations: Annotations,
    start_points_by_area_id: Mapping[int, tuple[float, float]],
) -> dict[str, object]:
    areas_by_id = {area_room_id(area): area for area in annotations.area_labels}
    records = []
    for area_id, point in sorted(dict(start_points_by_area_id or {}).items()):
        area = areas_by_id.get(int(area_id))
        if area is None:
            continue
        valid_point = valid_start_point_for_area(area, point)
        if valid_point is None:
            continue
        records.append(
            {
                "room_id": area_room_id(area),
                "area_fingerprint": area_label_fingerprint(area),
                "start_world_xy": [float(valid_point[0]), float(valid_point[1])],
            }
        )
    return {
        "schema_version": COVERAGE_START_POINTS_SCHEMA_VERSION,
        "start_points": records,
    }


def save_coverage_start_points(
    project_dir: str | Path,
    annotations: Annotations,
    start_points_by_area_id: Mapping[int, tuple[float, float]],
) -> Path:
    path = coverage_start_points_path(project_dir)
    payload = build_coverage_start_points_payload(annotations, start_points_by_area_id)
    if not payload["start_points"]:
        if path.exists():
            path.unlink()
        return path
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_coverage_start_points(project_dir: str | Path, annotations: Annotations) -> dict[int, tuple[float, float]]:
    path = coverage_start_points_path(project_dir)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("coverage start points payload must be an object")
    schema_version = int(payload.get("schema_version", 0))
    if schema_version != COVERAGE_START_POINTS_SCHEMA_VERSION:
        raise ValueError(f"unsupported coverage start points schema_version={schema_version}")
    records = payload.get("start_points")
    if not isinstance(records, list):
        raise ValueError("start_points must be a list")

    areas_by_id = {area_room_id(area): area for area in annotations.area_labels}
    loaded: dict[int, tuple[float, float]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            area_id = int(record.get("room_id", record.get("area_id")))
        except (TypeError, ValueError):
            continue
        area = areas_by_id.get(area_id)
        if area is None:
            continue
        if str(record.get("area_fingerprint", "")) != area_label_fingerprint(area):
            continue
        point = record.get("start_world_xy")
        if not isinstance(point, Iterable):
            continue
        point_values = list(point)
        if len(point_values) < 2:
            continue
        valid_point = valid_start_point_for_area(area, (point_values[0], point_values[1]))
        if valid_point is not None:
            loaded[area_id] = valid_point
    return loaded
