"""基础几何准备中的预处理核心对象与正式入口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .conversions import derive_resolution, remove_small_free_islands, to_gray
from .cropping import crop_gray_by_box, derive_crop_box


@dataclass(slots=True)
class InputFrame:
    """统一后的输入帧。

    真实职责：
        把原始输入收敛成单通道灰度图、统一裁剪框和统一分辨率表达，
        让后续所有几何运算都在同一局部参考系内进行。

    Args:
        gray:
            裁剪后的运行尺度灰度图。单位：像素强度。
        crop_box_px:
            裁剪框，格式为 `(top, left, bottom, right)`。单位：运行尺度像素。
        resolution_m_per_px:
            运行尺度米/像素分辨率。单位：米/像素。
    """

    gray: np.ndarray
    crop_box_px: tuple[int, int, int, int]
    resolution_m_per_px: float


@dataclass(slots=True)
class SpaceMasks:
    """空间掩膜集合。

    真实职责：
        统一承载区域约束、自由空间、障碍空间以及开运算后的稳定空间，
        供骨架提取阶段直接消费。

    Args:
        region_mask:
            有效处理区域。单位：0/255 掩膜。
        free_mask:
            可通行自由空间。单位：0/255 掩膜。
        obstacle_mask:
            不可通行障碍空间。单位：0/255 掩膜。
        after_open_mask:
            对自由空间做保守开运算后的结果。单位：0/255 掩膜。
    """

    region_mask: np.ndarray
    free_mask: np.ndarray
    obstacle_mask: np.ndarray
    after_open_mask: np.ndarray


def normalize_input(
    raw_map: Any,
    region_constraint: Any | None = None,
    config: dict[str, Any] | None = None,
) -> InputFrame:
    """把原始输入统一成运行尺度输入帧。

    真实职责：
        解析原始地图、裁剪范围和分辨率来源，保证后续所有 `rc` 坐标
        都指向同一块局部运行尺度图像。

    Args:
        raw_map:
            原始地图输入。当前支持 `numpy.ndarray` 或带灰度图字段的字典。
        region_constraint:
            区域约束。当前支持 `None`、`crop_box_px` 字典或区域掩膜。
        config:
            geometry_preparation 配置。可提供默认裁剪框和分辨率覆盖值。

    Returns:
        InputFrame:
            统一后的输入帧。

    副作用:
        无。本函数只构造内存对象。
    """

    config = dict(config or {})

    # 灰度图是后续所有空间表达的底图，因此必须先统一成单通道格式。
    gray_full = to_gray(raw_map, config)
    # crop_box 与分辨率分别收口，避免后续 helper 再各自解释输入。
    crop_box_px = derive_crop_box(region_constraint, gray_full.shape, config)

    # 先裁图再做后续掩膜，可以保证所有局部坐标天然落在同一参考系里。
    # 如果先做整图掩膜再裁图，不同 helper 很容易各自带着原图坐标假设继续计算。
    gray = crop_gray_by_box(gray_full, crop_box_px)
    resolution_m_per_px = derive_resolution(raw_map, config)
    # InputFrame 是 geometry_preparation 所有局部几何计算共享的统一入口对象。
    return InputFrame(gray=gray, crop_box_px=crop_box_px, resolution_m_per_px=resolution_m_per_px)


def build_space_masks(
    frame: InputFrame,
    raw_map: Any,
    region_constraint: Any | None = None,
    config: dict[str, Any] | None = None,
) -> SpaceMasks:
    """建立区域、自由空间和障碍空间掩膜。

    真实职责：
        把外部输入中可能分散在灰度图、区域掩膜、自由空间掩膜里的空间信息
        收敛成一套稳定的空间表示，供骨架提取直接使用。

    Args:
        frame:
            已完成裁剪和分辨率统一的输入帧。
        raw_map:
            原始地图输入，用于解析显式提供的 mask。
        region_constraint:
            区域约束，用于构造有效区域掩膜。
        config:
            预处理参数。

    Returns:
        SpaceMasks:
            空间掩膜集合。
    """

    config = dict(config or {})

    # 延迟导入避免预处理核心入口与空间 mask helper 子模块之间形成循环依赖。
    from .space_masks import (
        build_free_mask,
        build_obstacle_mask,
        build_region_mask,
        morphology_obstacle_expand,
        morphology_open,
        seal_crop_boundary_as_obstacle,
    )

    # 区域 -> 障碍 -> 自由 的顺序不能乱，因为自由默认依赖障碍反推。
    region_mask = build_region_mask(frame, raw_map, region_constraint, config)
    obstacle_mask = build_obstacle_mask(frame, raw_map, region_mask, config)
    free_mask = build_free_mask(region_mask, obstacle_mask, raw_map, frame.crop_box_px)
    free_mask, obstacle_mask = seal_crop_boundary_as_obstacle(
        region_mask=region_mask,
        free_mask=free_mask,
        obstacle_mask=obstacle_mask,
    )
    # 这里一旦 free/obstacle 建好，后续阶段就只认这套局部真值，不再回看灰度阈值或原始 mask 来源。
    # 这三张 mask 在这里第一次进入统一局部参考系下的闭环关系。
    # 一旦这一步完成，后续骨架与修剪就不必再回看 raw_map 原始表达。

    # 开运算的目标是去掉小尺度锯齿和离散毛刺，而不是改变通道主干拓扑。
    if bool(config.get("input_is_prepared_map", False)):
        # prepared_map 已经是公共预处理的正式输出；这里不能再做第二轮产品级 opening。
        after_open_mask = free_mask.copy()
    else:
        after_open_mask = morphology_open(
            mask=free_mask,
            resolution_m_per_px=frame.resolution_m_per_px,
            config=config,
        )
        after_open_mask = morphology_obstacle_expand(
            mask=after_open_mask,
            resolution_m_per_px=frame.resolution_m_per_px,
            config=config,
        )
    # SpaceMasks 把 geometry_preparation 空间层真值收成一个稳定对象，便于后续阶段直接消费。
    # 返回对象里既保留原始 free，也保留 after_open，方便后续清理层二次处理。
    # 这也是 stage-1 调试时能同时查看“开运算前”和“开运算后”的原因。
    return SpaceMasks(
        region_mask=region_mask,
        free_mask=free_mask,
        obstacle_mask=obstacle_mask,
        after_open_mask=after_open_mask,
    )


def clean_free_space(
    space_masks: SpaceMasks,
    config: dict[str, Any] | None = None,
) -> SpaceMasks:
    """对自由空间做保守清理。

    真实职责：
        移除明显不应进入骨架的自由空间孤岛，同时把自由空间重新约束回有效区域，
        避免形态学操作在边界处引入伪结构。

    Args:
        space_masks:
            原始空间掩膜集合。
        config:
            清理参数。可选字段：
            `min_free_component_px`，表示允许保留的最小自由空间连通域面积。

    Returns:
        SpaceMasks:
            清理后的空间掩膜集合。
    """

    config = dict(config or {})

    if bool(config.get("input_is_prepared_map", False)):
        # 阶段2正式 prepared_map 已经做过 opening 与小孤岛清理；
        # geometry_preparation 这里不再重复承担产品级形态学职责。
        cleaned_free_mask = np.where(
            (space_masks.after_open_mask > 0) & (space_masks.region_mask > 0),
            255,
            0,
        ).astype(np.uint8)
    else:
        # 小孤岛过滤发生在 after_open 基础上，而不是原始 free_mask 上。
        min_free_component_px = int(config.get("min_free_component_px", 160))
        cleaned_free_mask = remove_small_free_islands(space_masks.after_open_mask, min_free_component_px)
    # 这样可以先借助开运算消毛刺，再借助面积门限去掉离散孤岛。
    # 两步都只在自由空间层发生，不直接改 region 或 resolution 真值。

    # 开运算和连通域过滤都可能在边界附近留下无意义像素，因此要再次约束回区域内。
    cleaned_free_mask = np.where(
        (cleaned_free_mask > 0) & (space_masks.region_mask > 0),
        255,
        0,
    ).astype(np.uint8)

    # 障碍掩膜始终只在有效区域内解释，区域外保持 0 可以避免下游误判成真实障碍。
    # 清理后的障碍也应与 cleaned_free_mask 严格互补，保持语义闭环。
    cleaned_obstacle_mask = np.where(
        space_masks.region_mask > 0,
        np.where(cleaned_free_mask > 0, 0, 255),
        0,
    ).astype(np.uint8)
    from .space_masks import seal_crop_boundary_as_obstacle
    cleaned_free_mask, cleaned_obstacle_mask = seal_crop_boundary_as_obstacle(
        region_mask=space_masks.region_mask,
        free_mask=cleaned_free_mask,
        obstacle_mask=cleaned_obstacle_mask,
    )
    # after_open_mask 在清理后与 free_mask 对齐，表示“可骨架化的最终自由空间”。
    # 返回对象仍沿用 SpaceMasks，避免下游关心清理前后的具体来源。
    return SpaceMasks(
        region_mask=space_masks.region_mask,
        free_mask=cleaned_free_mask,
        obstacle_mask=cleaned_obstacle_mask,
        after_open_mask=cleaned_free_mask,
    )


__all__ = (
    "InputFrame",
    "SpaceMasks",
    "normalize_input",
    "build_space_masks",
    "clean_free_space",
)
