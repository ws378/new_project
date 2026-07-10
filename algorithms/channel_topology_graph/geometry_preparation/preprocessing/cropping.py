"""基础几何准备中的裁剪与局部参考系 helper。"""

from __future__ import annotations

from typing import Any

import numpy as np


def derive_crop_box(
    region_constraint: Any | None,
    image_shape: tuple[int, ...],
    config: dict[str, Any] | None = None,
) -> tuple[int, int, int, int]:
    """解析并裁切有效处理区域。"""

    if config is None:
        config = {}

    # 裁剪框最终一定要落在当前图像边界内，因此先冻结原图尺寸。
    height, width = int(image_shape[0]), int(image_shape[1])
    if height <= 0 or width <= 0:
        raise ValueError("image_shape must describe a non-empty image")

    # 优先级固定为显式配置 -> 区域掩膜 -> 约束对象内置 crop -> 全图默认。
    crop_box = extract_crop_box(config)
    if crop_box is None and isinstance(region_constraint, np.ndarray):
        # 直接给掩膜时，按掩膜外接矩形推回 crop。
        crop_box = crop_box_from_mask(region_constraint, pad_px=int(config.get("crop_pad_px", 0)))
    if crop_box is None:
        # 非数组约束对象继续尝试从其内部字段提取 crop 信息。
        crop_box = extract_crop_box(region_constraint)
    if crop_box is None:
        # 真正没有任何局部约束时，才回退到整图。
        crop_box = (0, 0, height, width)

    # 归一化阶段会把越界 crop 拉回图像范围，但不会容忍空矩形。
    top, left, bottom, right = (int(v) for v in crop_box)
    # 上下左右都要分别裁回边界，并保证最终至少保留 1 像素面积。
    top = max(0, min(top, height))
    left = max(0, min(left, width))
    bottom = max(top + 1, min(bottom, height))
    right = max(left + 1, min(right, width))
    if bottom <= top or right <= left:
        raise ValueError("crop_box_px resolves to an empty area")
    # 返回值已经是合法局部参考系中的标准四元组。
    # 下游所有局部 rc 坐标都默认以这个 box 为原点参考。
    return (top, left, bottom, right)


def crop_gray_by_box(gray: np.ndarray, crop_box_px: tuple[int, int, int, int]) -> np.ndarray:
    """按裁剪框提取局部灰度图。"""

    # 灰度图裁剪直接沿 `(top, left, bottom, right)` slice 语义执行。
    top, left, bottom, right = crop_box_px
    cropped = gray[top:bottom, left:right]
    if cropped.size == 0:
        raise ValueError("cropped gray image is empty")
    # 返回连续数组，避免后续 OpenCV 在 view 上额外触发隐式拷贝。
    return np.ascontiguousarray(cropped)


def extract_crop_box(source: Any) -> tuple[int, int, int, int] | None:
    """从输入中提取裁剪框。"""

    # `None` 表示未显式提供，由上层继续尝试其它来源。
    if source is None:
        return None
    if isinstance(source, np.ndarray):
        # 单独给掩膜时，按其非零区域自动回推 crop。
        return crop_box_from_mask(source, pad_px=0)
    if isinstance(source, dict) and "crop_box_px" in source:
        # 显式 crop_box 字段可以直接收用。
        value = source["crop_box_px"]
    elif isinstance(source, dict) and "region_mask" in source:
        # dict 内的 `region_mask` / `mask` 都支持带独立 pad 一起传入。
        pad_px = int(source.get("crop_pad_px", 0))
        mask = source["region_mask"]
        if isinstance(mask, np.ndarray):
            return crop_box_from_mask(mask, pad_px=pad_px)
        # 键存在但值不是数组时，不在这里报错，而是继续按“无可用 crop 信息”处理。
        return None
    elif isinstance(source, dict) and "mask" in source:
        pad_px = int(source.get("crop_pad_px", 0))
        mask = source["mask"]
        if isinstance(mask, np.ndarray):
            return crop_box_from_mask(mask, pad_px=pad_px)
        return None
    else:
        # 其余对象仅当其本身就是四元组时才继续尝试。
        value = source

    # 最终只接受标准四元组，不在这里做更复杂的对象解读。
    if isinstance(value, (tuple, list)) and len(value) == 4:
        return tuple(int(v) for v in value)
    # 其余情况统一视作“未提供 crop”，让上层继续走兜底逻辑。
    # 这样 `_extract_crop_box` 本身始终保持“只解析、不兜底”的单一职责。
    return None


def crop_box_from_mask(mask: np.ndarray, pad_px: int) -> tuple[int, int, int, int] | None:
    """从掩膜推导裁剪框，并可选外扩一圈 pad。"""

    # 非零点的外接矩形就是局部处理区域的最小闭包。
    points = np.argwhere(mask > 0)
    if points.size == 0:
        return None
    # 这里不做边界裁切，留给上层统一按原图尺寸收口。
    top = int(points[:, 0].min()) - int(pad_px)
    left = int(points[:, 1].min()) - int(pad_px)
    bottom = int(points[:, 0].max()) + 1 + int(pad_px)
    right = int(points[:, 1].max()) + 1 + int(pad_px)
    # 返回的仍是原图坐标系 crop，尚未限制到合法边界。
    return (top, left, bottom, right)


def crop_mask_by_box(mask: np.ndarray, crop_box_px: tuple[int, int, int, int]) -> np.ndarray:
    """按裁剪框提取局部掩膜。"""

    # 掩膜裁剪与灰度图裁剪必须共用完全相同的 box 语义。
    top, left, bottom, right = crop_box_px
    cropped = mask[top:bottom, left:right]
    if cropped.size == 0:
        raise ValueError("cropped mask is empty")
    # 连续数组返回可以减少后续形态学与骨架运算的隐式复制。
    return np.ascontiguousarray(cropped)


__all__ = [
    "crop_gray_by_box",
    "crop_mask_by_box",
    "derive_crop_box",
]
