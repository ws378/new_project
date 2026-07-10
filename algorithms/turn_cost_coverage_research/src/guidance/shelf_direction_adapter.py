"""复用 shelf_aware_guarded 局部方向场作为官方流程观测输入。"""

from __future__ import annotations

from typing import Any

import numpy as np

from algorithms.coverage_planning.planners.shelf_aware_guarded.direction.field import (
    compute_local_direction_map,
)
from algorithms.coverage_planning.planners.shelf_aware_guarded.models import (
    LocalDirectionConfig,
)

from .models import MAPTOOLS_CROP_METER_FRAME, MAPTOOLS_CROP_TRANSFORM, GuidanceField


def _crop_box_tuple(value: Any) -> tuple[int, int, int, int] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return tuple(int(item) for item in value)
    return None


def build_shelf_direction_guidance(
    *,
    geometry_result: Any,
    coverage_width_m: float,
    tool_radius_m: float,
    official_hex_side_length_m: float,
    resolution_m_per_px: float,
    local_direction_config: LocalDirectionConfig | None = None,
) -> GuidanceField:
    """从既有 geometry_preparation free_mask 构建方向场。

    该函数只消费已有预处理结果，不新增区域拆分、pass-only 映射或语义预处理。
    """

    config = local_direction_config or LocalDirectionConfig()
    free_mask = np.asarray(geometry_result.free_mask)
    if free_mask.ndim != 2:
        raise ValueError("geometry_result.free_mask must be a 2D mask")
    room_map = np.where(free_mask > 0, 255, 0).astype(np.uint8)
    direction_window_width_m = max(
        float(coverage_width_m),
        2.0 * float(tool_radius_m),
        float(official_hex_side_length_m),
    )
    coverage_width_px = max(2, int(round(direction_window_width_m / float(resolution_m_per_px))))
    direction_map, confidence_map = compute_local_direction_map(room_map, coverage_width_px, config)
    crop_box_px = _crop_box_tuple(getattr(geometry_result, "crop_box_px", None))
    return GuidanceField(
        direction_rad_map=np.asarray(direction_map, dtype=np.float32),
        confidence_map=np.asarray(confidence_map, dtype=np.float32),
        resolution_m_per_px=float(resolution_m_per_px),
        frame_id=MAPTOOLS_CROP_METER_FRAME,
        map_shape_rc=(int(room_map.shape[0]), int(room_map.shape[1])),
        origin_rc=(0, 0),
        crop_box_px=crop_box_px,
        coordinate_transform=MAPTOOLS_CROP_TRANSFORM,
        source="shelf_aware_local_direction",
        metadata={
            "local_direction_config": config.to_dict(),
            "coverage_width_m": float(coverage_width_m),
            "tool_radius_m": float(tool_radius_m),
            "official_hex_side_length_m": float(official_hex_side_length_m),
            "direction_window_width_m": float(direction_window_width_m),
            "coverage_width_px": int(coverage_width_px),
            "free_mask_shape_rc": [int(room_map.shape[0]), int(room_map.shape[1])],
            "algorithm_impact": "artifact_only_no_path_change",
            "source_note": "复用 shelf_aware_guarded compute_local_direction_map；未复制其主规划器",
        },
    )
