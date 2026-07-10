"""基础几何准备中的骨架提取函数。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from .preprocessing import SpaceMasks


@dataclass(slots=True)
class SkeletonView:
    """骨架视图。

    真实职责：
        同时承载原始骨架、修剪后骨架以及骨架像素坐标，
        让后续短枝修剪和阶段结果装配都只面对同一套几何载体。

    Args:
        skeleton_mask:
            原始骨架掩膜。单位：0/255 掩膜。
        skeleton_pruned_mask:
            当前有效骨架掩膜。若还未修剪，可与 `skeleton_mask` 相同。
        skeleton_pixels_rc:
            当前有效骨架像素坐标集合。单位：运行尺度像素。
        method:
            骨架提取方法说明，用于调试和结果解释。
    """

    skeleton_mask: np.ndarray
    skeleton_pruned_mask: np.ndarray
    skeleton_pixels_rc: tuple[tuple[int, int], ...]
    method: str


def extract_skeleton_pixels(skeleton_mask: np.ndarray) -> tuple[tuple[int, int], ...]:
    """提取骨架像素坐标真值。"""

    return extract_pixels_rc(skeleton_mask)


def build_skeleton(
    space_masks: SpaceMasks,
    config: dict[str, Any] | None = None,
) -> SkeletonView:
    """从清理后的自由空间提取骨架。

    真实职责：
        基于稳定的自由空间掩膜生成一像素宽主干骨架，
        供后续短枝修剪和交汇重建直接消费。

    Args:
        space_masks:
            已完成空间清理的空间掩膜集合。
        config:
            骨架参数。当前预留接口，便于后续扩展骨架方法。

    Returns:
        SkeletonView:
            原始骨架视图。此时 `skeleton_pruned_mask` 与 `skeleton_mask` 相同。
    """

    normalize_skeleton_config(config)
    skeleton_mask, method = build_raw_skeleton(space_masks.after_open_mask)
    skeleton_pixels_rc = extract_skeleton_pixels(skeleton_mask)
    return build_initial_skeleton_view(
        skeleton_mask=skeleton_mask,
        skeleton_pixels_rc=skeleton_pixels_rc,
        method=method,
    )


def normalize_skeleton_config(config: dict[str, Any] | None) -> None:
    """规整骨架提取配置入口。"""

    # 当前骨架提取不直接读取配置，接口保留是为了后续扩展算法选型。
    _ = config
    # 这里显式吞掉 config，是为了让调用栈保留统一签名而不引入“未使用参数”噪音。


def build_raw_skeleton(mask: np.ndarray) -> tuple[np.ndarray, str]:
    """从清理后的自由空间直接生成原始骨架。"""

    # 原始骨架与当前有效骨架初始相同，修剪阶段再决定是否收缩。
    return skeletonize_mask(mask)


def build_initial_skeleton_view(
    *,
    skeleton_mask: np.ndarray,
    skeleton_pixels_rc: tuple[tuple[int, int], ...],
    method: str,
) -> SkeletonView:
    """组装未修剪阶段的初始 SkeletonView。"""

    # SkeletonView 把掩膜真值、像素列表和方法名一次性收口。
    # 这样修剪阶段无需再自己重新组装骨架对象。
    # 初始时 pruned 与 raw 相同，表达“尚未发生修剪”这一事实。
    return SkeletonView(
        skeleton_mask=skeleton_mask,
        skeleton_pruned_mask=skeleton_mask.copy(),
        skeleton_pixels_rc=skeleton_pixels_rc,
        method=method,
    )


def skeletonize_mask(mask: np.ndarray) -> tuple[np.ndarray, str]:
    """把二值自由空间掩膜细化成骨架。

    真实职责：
        优先使用 OpenCV 的 Zhang-Suen thinning，保证骨架尽量贴近现有研究实现；
        若环境不支持，再退回标准形态学骨架化。

    Args:
        mask:
            自由空间掩膜。单位：0/255 掩膜。

    Returns:
        tuple[np.ndarray, str]:
            骨架掩膜与方法名。
    """

    src = normalize_binary_mask(mask)
    if hasattr(cv2, "ximgproc") and hasattr(cv2.ximgproc, "thinning"):
        # 优先走 OpenCV thinning，可最大程度贴近现有研究主线。
        return skeletonize_with_opencv_thinning(src)
    # 环境不支持 thinning 时，再退到可重复的形态学方案。
    # 这个回退不是同精度替代，只是保证阶段仍能产出可调试结果。
    return skeletonize_morph(src), "morphological_fallback"


def normalize_binary_mask(mask: np.ndarray) -> np.ndarray:
    """把任意掩膜统一压成骨架算法使用的标准二值图。"""

    # 骨架化统一在标准二值图上执行，避免上游残值影响 thinning。
    return np.where(mask > 0, 255, 0).astype(np.uint8)


def skeletonize_with_opencv_thinning(src: np.ndarray) -> tuple[np.ndarray, str]:
    """用 OpenCV thinning 生成骨架。"""

    thinned = cv2.ximgproc.thinning(src, thinningType=cv2.ximgproc.THINNING_ZHANGSUEN)
    return np.where(thinned > 0, 255, 0).astype(np.uint8), "cv2.ximgproc.thinning"


def extract_pixels_rc(mask: np.ndarray) -> tuple[tuple[int, int], ...]:
    """提取掩膜中的像素坐标集合。"""

    # 显式像素列表是 junction_rebuild 建初始 node/edge 的直接输入之一。
    return tuple(tuple(map(int, point)) for point in np.argwhere(mask > 0))


def skeletonize_morph(mask: np.ndarray) -> np.ndarray:
    """用形态学迭代方式生成骨架。

    真实职责：
        在没有 `ximgproc.thinning` 的环境中提供可重复的退化方案，
        避免 geometry_preparation 直接失效。

    Args:
        mask:
            二值自由空间掩膜。单位：0/255 掩膜。

    Returns:
        np.ndarray:
            骨架掩膜。单位：0/255 掩膜。
    """

    src = normalize_binary_mask(mask)
    skeleton = np.zeros_like(src)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    while True:
        # 形态学开操作先剥掉局部边缘，再把“被剥掉但仍属于主干”的部分累积进骨架。
        opened = cv2.morphologyEx(src, cv2.MORPH_OPEN, element)
        temp = cv2.subtract(src, opened)
        eroded = cv2.erode(src, element)
        skeleton = cv2.bitwise_or(skeleton, temp)
        src = eroded
        # 迭代变量 `src` 每轮都收缩，直到不再有剩余自由空间。

        # 直到所有自由空间都被剥完，骨架才稳定收敛。
        if cv2.countNonZero(src) == 0:
            break
    # 返回值仍然强制压回 0/255，保持与主路径骨架表达一致。
    return np.where(skeleton > 0, 255, 0).astype(np.uint8)
