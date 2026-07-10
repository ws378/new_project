"""官方图顶点到方向场的坐标查询。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np

from .models import (
    MAPTOOLS_CROP_METER_FRAME,
    MAPTOOLS_CROP_TRANSFORM,
    GuidanceField,
    GuidanceQueryStatus,
    VertexDirectionHint,
)


def _vertex_xy(vertex: Any) -> tuple[float, float]:
    point = getattr(vertex, "point", vertex)
    if hasattr(point, "x") and hasattr(point, "y"):
        return float(point.x), float(point.y)
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        return float(point[0]), float(point[1])
    raise TypeError(f"unsupported vertex type: {type(vertex).__name__}")


def query_vertex_direction(
    vertex: Any,
    field: GuidanceField,
    *,
    min_confidence: float,
    expected_frame_id: str = MAPTOOLS_CROP_METER_FRAME,
    expected_coordinate_transform: str = MAPTOOLS_CROP_TRANSFORM,
) -> tuple[VertexDirectionHint | None, GuidanceQueryStatus]:
    """查询单个顶点方向。

    帧、尺寸或置信度不满足要求时 fail-closed：返回 None 和可记录状态。
    """

    if field.frame_id != expected_frame_id:
        return None, GuidanceQueryStatus(False, "disabled_frame_mismatch", field.frame_id)
    if field.coordinate_transform != expected_coordinate_transform:
        return None, GuidanceQueryStatus(False, "disabled_coordinate_transform_mismatch", field.coordinate_transform)
    if tuple(field.direction_rad_map.shape) != tuple(field.map_shape_rc):
        return None, GuidanceQueryStatus(False, "disabled_direction_shape_mismatch", str(field.direction_rad_map.shape))
    if tuple(field.confidence_map.shape) != tuple(field.map_shape_rc):
        return None, GuidanceQueryStatus(False, "disabled_confidence_shape_mismatch", str(field.confidence_map.shape))
    if field.resolution_m_per_px <= 0.0:
        return None, GuidanceQueryStatus(False, "disabled_invalid_resolution", str(field.resolution_m_per_px))

    x, y = _vertex_xy(vertex)
    row = int(round(-y / float(field.resolution_m_per_px)))
    col = int(round(x / float(field.resolution_m_per_px)))
    rows, cols = field.map_shape_rc
    if row < 0 or col < 0 or row >= rows or col >= cols:
        return None, GuidanceQueryStatus(True, "outside_map")
    confidence = float(field.confidence_map[row, col])
    if not np.isfinite(confidence) or confidence < float(min_confidence):
        return None, GuidanceQueryStatus(True, "below_min_confidence")
    angle = float(field.direction_rad_map[row, col])
    if not np.isfinite(angle):
        return None, GuidanceQueryStatus(True, "invalid_angle")
    return (
        VertexDirectionHint(
            preferred_angle_rad=angle,
            confidence=confidence,
            source=field.source,
            row=row,
            col=col,
        ),
        GuidanceQueryStatus(True, "hit"),
    )


def collect_vertex_guidance_stats(
    vertices: Iterable[Any],
    field: GuidanceField,
    *,
    min_confidence: float,
    sample_limit: int = 20,
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    samples: list[dict[str, Any]] = []
    confidences: list[float] = []
    vertex_count = 0
    for vertex in vertices:
        vertex_count += 1
        hint, status = query_vertex_direction(vertex, field, min_confidence=min_confidence)
        counts[status.status] = counts.get(status.status, 0) + 1
        if hint is not None:
            confidences.append(float(hint.confidence))
            if len(samples) < sample_limit:
                x, y = _vertex_xy(vertex)
                item = hint.to_dict()
                item["vertex_xy_m"] = [float(x), float(y)]
                samples.append(item)
    hit_count = int(counts.get("hit", 0))
    return {
        "field": field.to_metadata(),
        "query": {
            "min_confidence": float(min_confidence),
            "vertex_count": int(vertex_count),
            "hit_count": hit_count,
            "hit_ratio": hit_count / vertex_count if vertex_count > 0 else 0.0,
            "status_counts": counts,
            "average_confidence": float(np.mean(confidences)) if confidences else 0.0,
            "max_confidence": float(np.max(confidences)) if confidences else 0.0,
            "sample_limit": int(sample_limit),
            "samples": samples,
        },
    }
