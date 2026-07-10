"""基础几何准备中的空间掩膜构造 helper。"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from .conversions import derive_obstacle_expand_px, derive_open_kernel_px, extract_mask_array, to_uint8_mask
from .cropping import crop_mask_by_box
from .core import InputFrame


def seal_crop_boundary_as_obstacle(
    region_mask: np.ndarray,
    free_mask: np.ndarray,
    obstacle_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Force the local crop outer border to behave as obstacle inside the active region."""

    height, width = region_mask.shape
    if height == 0 or width == 0:
        return free_mask, obstacle_mask
    boundary_mask = np.zeros_like(region_mask, dtype=np.uint8)
    boundary_mask[0, :] = 255
    boundary_mask[-1, :] = 255
    boundary_mask[:, 0] = 255
    boundary_mask[:, -1] = 255
    active_boundary = (boundary_mask > 0) & (region_mask > 0)
    if not np.any(active_boundary):
        return free_mask, obstacle_mask
    sealed_free = np.where(active_boundary, 0, free_mask).astype(np.uint8)
    sealed_obstacle = np.where(active_boundary | (obstacle_mask > 0), 255, 0).astype(np.uint8)
    return sealed_free, sealed_obstacle


def build_region_mask(
    frame: InputFrame,
    raw_map: Any,
    region_constraint: Any | None,
    config: dict[str, Any] | None = None,
) -> np.ndarray:
    """建立有效处理区域掩膜。"""

    # 该 helper 当前不直接读取配置，保留参数只是保持预处理接口对齐。
    _ = config
    # 区域掩膜优先从显式约束对象中读取，其次再回看 raw_map。
    full_region_mask = extract_mask_array(region_constraint, "region_mask")
    if full_region_mask is None and isinstance(region_constraint, np.ndarray):
        full_region_mask = region_constraint
    if full_region_mask is None and isinstance(region_constraint, dict) and "mask" in region_constraint:
        full_region_mask = extract_mask_array(region_constraint, "mask")
    if full_region_mask is None:
        full_region_mask = extract_mask_array(raw_map, "region_mask")

    # 若调用方完全没给区域约束，就默认整张局部图都有效。
    if full_region_mask is None:
        return np.full_like(frame.gray, 255, dtype=np.uint8)

    # 一旦拿到全图掩膜，就必须按统一 crop_box 裁到局部参考系。
    region_mask = crop_mask_by_box(mask=to_uint8_mask(full_region_mask), crop_box_px=frame.crop_box_px)
    # 区域掩膜最终也强制压成严格 0/255 二值图。
    # 这样 region/free/obstacle 三张图后续可以用完全同一套二值逻辑处理。
    return np.where(region_mask > 0, 255, 0).astype(np.uint8)


def build_obstacle_mask(
    frame: InputFrame,
    raw_map: Any,
    region_mask: np.ndarray,
    config: dict[str, Any] | None = None,
) -> np.ndarray:
    """建立障碍空间掩膜。"""

    if config is None:
        config = {}

    # 障碍掩膜优先使用显式 obstacle truth，避免灰度阈值猜测覆盖真实输入。
    full_obstacle_mask = extract_mask_array(raw_map, "obstacle_mask")
    if full_obstacle_mask is not None:
        obstacle_mask = crop_mask_by_box(to_uint8_mask(full_obstacle_mask), frame.crop_box_px)
        # 即使显式障碍也只在 region 内生效，区域外统一保持 0。
        return np.where((obstacle_mask > 0) & (region_mask > 0), 255, 0).astype(np.uint8)

    # 若只有自由空间真值，则通过区域内取反得到障碍。
    full_free_mask = extract_mask_array(raw_map, "free_mask")
    if full_free_mask is not None:
        free_mask = crop_mask_by_box(to_uint8_mask(full_free_mask), frame.crop_box_px)
        # 这里的障碍是 region 内 free 的补集，而不是整图补集。
        # 也就是说，区域外不被解释成障碍，只是“当前阶段不关心”。
        return np.where((region_mask > 0) & (free_mask == 0), 255, 0).astype(np.uint8)

    # 最后才退回灰度阈值法，这属于兼容路径而不是首选真值来源。
    threshold = int(config.get("obstacle_threshold", 127))
    # 阈值法也必须受 region 约束，避免局部处理区域外出现伪障碍。
    return np.where((region_mask > 0) & (frame.gray <= threshold), 255, 0).astype(np.uint8)


def build_free_mask(
    region_mask: np.ndarray,
    obstacle_mask: np.ndarray,
    raw_map: Any,
    crop_box_px: tuple[int, int, int, int],
) -> np.ndarray:
    """从区域掩膜和障碍掩膜推导自由空间。"""

    # 显式 free mask 一旦存在，就优先尊重外部真值。
    full_free_mask = extract_mask_array(raw_map, "free_mask")
    if full_free_mask is not None:
        free_mask = crop_mask_by_box(to_uint8_mask(full_free_mask), crop_box_px)
        # 显式 free 进入局部参考系后，仍然只在 region 内保留。
        return np.where((region_mask > 0) & (free_mask > 0), 255, 0).astype(np.uint8)

    # 否则按“区域内非障碍即自由”的最小闭环规则推导。
    # 这条兜底规则保证在只给障碍时也能构造完整空间语义。
    return np.where((region_mask > 0) & (obstacle_mask == 0), 255, 0).astype(np.uint8)


def morphology_open(
    mask: np.ndarray,
    resolution_m_per_px: float,
    config: dict[str, Any] | None = None,
) -> np.ndarray:
    """对自由空间做保守开运算。"""

    if config is None:
        config = {}

    # 形态学核大小统一按运行尺度像素求解，避免不同地图分辨率下效果漂移。
    kernel_px = derive_open_kernel_px(config, resolution_m_per_px)
    if kernel_px <= 1:
        # 核退化到 1 时开运算无实际意义，直接复制原掩膜。
        return mask.copy()

    # 开运算只服务“消毛刺”，不引入新的灰度或多值语义。
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_px, kernel_px))
    opened = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, kernel)
    # 输出重新压成严格二值图，便于后续骨架阶段直接消费。
    # 这里不再额外与 region 求交，区域约束在上游/下游统一处理。
    return np.where(opened > 0, 255, 0).astype(np.uint8)


def morphology_obstacle_expand(
    mask: np.ndarray,
    resolution_m_per_px: float,
    config: dict[str, Any] | None = None,
) -> np.ndarray:
    """对白色自由空间做一次腐蚀，语义上等价于障碍物膨胀。"""

    if config is None:
        config = {}

    kernel_px = derive_obstacle_expand_px(config, resolution_m_per_px)
    if kernel_px <= 1:
        return mask.copy()

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_px, kernel_px))
    eroded = cv2.erode(mask.astype(np.uint8), kernel, iterations=1)
    return np.where(eroded > 0, 255, 0).astype(np.uint8)
