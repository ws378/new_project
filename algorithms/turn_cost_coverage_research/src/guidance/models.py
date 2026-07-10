"""方向引导数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


MAPTOOLS_CROP_METER_FRAME = "maptools_existing_preprocessing_crop_meter_frame"
MAPTOOLS_CROP_TRANSFORM = "x_col_resolution_y_negative_row_resolution"


@dataclass(frozen=True)
class GuidanceField:
    """与 MapTools 既有预处理 crop 坐标系对齐的方向场。"""

    direction_rad_map: np.ndarray
    confidence_map: np.ndarray
    resolution_m_per_px: float
    frame_id: str
    map_shape_rc: tuple[int, int]
    origin_rc: tuple[int, int]
    crop_box_px: tuple[int, int, int, int] | None
    coordinate_transform: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def preflight_status(self) -> tuple[bool, str]:
        if self.frame_id != MAPTOOLS_CROP_METER_FRAME:
            return False, "disabled_frame_mismatch"
        if self.coordinate_transform != MAPTOOLS_CROP_TRANSFORM:
            return False, "disabled_coordinate_transform_mismatch"
        if tuple(self.direction_rad_map.shape) != tuple(self.map_shape_rc):
            return False, "disabled_direction_shape_mismatch"
        if tuple(self.confidence_map.shape) != tuple(self.map_shape_rc):
            return False, "disabled_confidence_shape_mismatch"
        if self.resolution_m_per_px <= 0.0:
            return False, "disabled_invalid_resolution"
        return True, "enabled"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "frame_id": self.frame_id,
            "coordinate_transform": self.coordinate_transform,
            "resolution_m_per_px": float(self.resolution_m_per_px),
            "map_shape_rc": [int(self.map_shape_rc[0]), int(self.map_shape_rc[1])],
            "origin_rc": [int(self.origin_rc[0]), int(self.origin_rc[1])],
            "crop_box_px": list(self.crop_box_px) if self.crop_box_px is not None else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class VertexDirectionHint:
    preferred_angle_rad: float
    confidence: float
    source: str
    row: int
    col: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "preferred_angle_rad": float(self.preferred_angle_rad),
            "confidence": float(self.confidence),
            "source": self.source,
            "row": int(self.row),
            "col": int(self.col),
        }


@dataclass(frozen=True)
class GuidanceQueryStatus:
    enabled: bool
    status: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "status": self.status,
            "reason": self.reason,
        }


def guidance_disabled_config(mode: str = "none", reason: str = "disabled_by_cli") -> dict[str, Any]:
    return {
        "enabled": False,
        "mode": mode,
        "status": reason,
        "algorithm_impact": "none",
        "formal_planner_migration": "不涉及；未启用方向引导",
    }
