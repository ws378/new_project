"""geometry_preparation 结果的归一化。"""

from __future__ import annotations

from typing import Any

from ._common import array_signature, mask_signature, normalize_index_point, to_jsonable


def normalize_geometry_result(geometry_result: Any) -> dict[str, Any]:
    """把 geometry_preparation 结果压成稳定、可 diff 的结构。"""

    skeleton_pixels = sorted(
        (normalize_index_point(point) for point in tuple(geometry_result.skeleton_pixels_rc)),
        key=lambda item: (int(item[0]), int(item[1])),
    )
    return {
        "summary": {
            "crop_box_px": [int(v) for v in tuple(geometry_result.crop_box_px)],
            "gray_shape": [int(v) for v in geometry_result.gray.shape],
            "resolution_m_per_px": float(geometry_result.resolution_m_per_px),
            "region_pixel_count": int((geometry_result.region_mask > 0).sum()),
            "free_pixel_count": int((geometry_result.free_mask > 0).sum()),
            "obstacle_pixel_count": int((geometry_result.obstacle_mask > 0).sum()),
            "after_open_pixel_count": int((geometry_result.after_open_mask > 0).sum()),
            "skeleton_raw_pixel_count": int((geometry_result.skeleton_mask > 0).sum()),
            "skeleton_pruned_pixel_count": int((geometry_result.skeleton_pruned_mask > 0).sum()),
            "skeleton_pixels_rc_count": int(len(skeleton_pixels)),
        },
        "gray": array_signature(geometry_result.gray),
        "region_mask": mask_signature(geometry_result.region_mask),
        "free_mask": mask_signature(geometry_result.free_mask),
        "obstacle_mask": mask_signature(geometry_result.obstacle_mask),
        "after_open_mask": mask_signature(geometry_result.after_open_mask),
        "skeleton_mask": mask_signature(geometry_result.skeleton_mask),
        "skeleton_pruned_mask": mask_signature(geometry_result.skeleton_pruned_mask),
        "skeleton_pixels_rc": skeleton_pixels,
        "debug_info": to_jsonable(geometry_result.debug_info),
        "validation_info": to_jsonable(geometry_result.validation_info),
        "meta": to_jsonable(geometry_result.meta),
    }
