"""GeometryPreparation stage 入口。"""

from __future__ import annotations

from typing import Any

from ..geometry_preparation import (
    build_space_masks,
    build_skeleton,
    clean_free_space,
    normalize_input,
    prune_short_side_branches,
)
from ..contracts import GeometryPreparationResult
from .geometry_preparation_validation import validate_geometry_preparation_result


def build_geometry_preparation_world(
    raw_map: Any,
    region_constraint: Any | None,
    config: dict[str, Any],
) -> tuple[Any, Any, Any]:
    """构建 geometry_preparation 统一参考系下的 frame、空间掩膜与清理后掩膜。"""

    # 这一步只负责把“输入世界”建稳，不负责骨架生成。
    frame = normalize_input(raw_map=raw_map, region_constraint=region_constraint, config=config)
    masks = build_space_masks(
        frame=frame,
        raw_map=raw_map,
        region_constraint=region_constraint,
        config=config,
    )
    cleaned_masks = clean_free_space(space_masks=masks, config=config)
    return frame, masks, cleaned_masks


def build_geometry_preparation_skeleton_outputs(
    frame: Any,
    cleaned_masks: Any,
    config: dict[str, Any],
) -> tuple[Any, Any, Any]:
    """构建 geometry_preparation 的 raw skeleton、pruned skeleton 与 pruning debug。"""

    # 骨架输出分成 raw/pruned/debug 三层，是为了显式保留“生成”和“修剪”两道责任边界。
    skeleton_view = build_skeleton(space_masks=cleaned_masks, config=config)
    pruned_skeleton_view, pruning_debug_info = prune_short_side_branches(
        skeleton_view=skeleton_view,
        resolution_m_per_px=frame.resolution_m_per_px,
        config=config,
    )
    return skeleton_view, pruned_skeleton_view, pruning_debug_info


def build_geometry_preparation(
    raw_map: Any,
    region_constraint: Any | None = None,
    config: dict[str, Any] | None = None,
) -> GeometryPreparationResult:
    """建立 geometry_preparation 的运行尺度几何世界。

    真实职责：
        把外部原始地图输入整理成统一的运行尺度几何结果，
        供 junction_rebuild 直接消费。

    Args:
        raw_map:
            原始地图输入。类型暂不限定，后续可对接图像、栅格或封装对象。
        region_constraint:
            可选区域约束。用于限制有效处理区域；为空时表示使用默认全局区域。
        config:
            geometry_preparation 阶段配置。单位和字段范围由后续实现细化。

    Returns:
        GeometryPreparationResult:
            geometry_preparation 正式输出。所有几何字段都必须处于运行尺度。

    副作用:
        当前函数不写文件、不修改全局状态；它只负责返回内存对象。
    """
    # geometry_preparation 允许空配置进入，但内部 helper 统一按 dict 读取参数。
    config = normalize_geometry_preparation_config(config)
    stage_outputs = build_geometry_preparation_stage_outputs(
        raw_map=raw_map,
        region_constraint=region_constraint,
        config=config,
    )
    return build_geometry_preparation_result(stage_outputs)


def normalize_geometry_preparation_config(
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    """把 geometry_preparation 配置规整成普通 dict。"""

    # 统一转 dict 后，下游 helper 就不需要再处理 `None` 或自定义 Mapping 分支。
    return dict(config or {})


def build_geometry_preparation_stage_outputs(
    *,
    raw_map: Any,
    region_constraint: Any | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    """按 geometry_preparation 正式顺序构建子结果。"""

    # geometry_preparation 只负责建立统一几何世界，因此入口先统一原始输入表达。
    frame, masks, cleaned_masks = build_geometry_preparation_world(
        raw_map=raw_map,
        region_constraint=region_constraint,
        config=config,
    )
    # 区域、自由空间和障碍空间必须在同一局部参考系下建立，否则后续骨架会错位。
    # 这里先得到“原始语义掩膜”，再交给清理层做形态学收敛。
    # 只有这样，geometry_preparation 输出的所有数组才能共享同一 crop/reference frame。
    # clean_free_space 负责把自由空间修到可骨架化的状态，不改变坐标系。
    # 它输出的仍然是正式掩膜，不是仅供渲染的中间图。
    # 骨架只允许从清理后的自由空间生成，不能直接绕过空间清理层。
    # 先得到原始骨架，再做短侧枝修剪，方便保留两层调试真值。
    # 这样既能看“骨架生成是否异常”，也能看“修剪是否过度”。
    skeleton_view, pruned_skeleton_view, pruning_debug_info = build_geometry_preparation_skeleton_outputs(
        frame=frame,
        cleaned_masks=cleaned_masks,
        config=config,
    )
    return {
        "frame": frame,
        "masks": masks,
        "cleaned_masks": cleaned_masks,
        "skeleton_view": skeleton_view,
        "pruned_skeleton_view": pruned_skeleton_view,
        "pruning_debug_info": pruning_debug_info,
    }


def build_geometry_preparation_result(stage_outputs: dict[str, Any]) -> GeometryPreparationResult:
    """组装 geometry_preparation 正式结果。"""

    frame = stage_outputs["frame"]
    masks = stage_outputs["masks"]
    cleaned_masks = stage_outputs["cleaned_masks"]
    skeleton_view = stage_outputs["skeleton_view"]
    pruned_skeleton_view = stage_outputs["pruned_skeleton_view"]
    pruning_debug_info = stage_outputs["pruning_debug_info"]
    # validation_info 由正式输出字段反推，不直接依赖中间局部变量的“口头约定”。
    # GeometryPreparationResult 是 junction_rebuild 唯一允许读取的正式几何对象。
    # 因此这里要一次性把 gray/mask/skeleton/resolution/crop_box 全部装齐。
    result = GeometryPreparationResult(
        gray=frame.gray,
        region_mask=masks.region_mask,
        free_mask=cleaned_masks.free_mask,
        obstacle_mask=cleaned_masks.obstacle_mask,
        # after_open_mask 保留“开运算之后、最终 free/obstacle 判定之前”的正式中间结果，
        # 便于定位空间清理是否过强，而不是单纯作为渲染图层。
        after_open_mask=cleaned_masks.after_open_mask,
        # raw skeleton 与 pruned skeleton 同时保留，便于后续定位修剪副作用。
        skeleton_mask=skeleton_view.skeleton_mask,
        skeleton_pruned_mask=pruned_skeleton_view.skeleton_pruned_mask,
        # skeleton_pixels_rc 是 pruned skeleton 的显式索引真值，后续很多图算法直接消费它而不是重新扫描整图。
        skeleton_pixels_rc=pruned_skeleton_view.skeleton_pixels_rc,
        crop_box_px=frame.crop_box_px,
        resolution_m_per_px=frame.resolution_m_per_px,
        # debug_info 只保留“方法”和“修剪轨迹”，不把中间大数组直接挂回结果。
        # 这样 real-case 输出既可读，也不会因为数组膨胀而失控。
        debug_info={
            "skeleton_method": pruned_skeleton_view.method,
            "pruning": pruning_debug_info,
        },
        # 这里对外写出的是对象级闭环校验结果，而不是纯粹的 smoke 标记。
        # 下游只要拿到 validation_info，就能判断结果对象是否满足消费前提。
        validation_info=validate_geometry_preparation_result(
            region_mask=masks.region_mask,
            gray=frame.gray,
            free_mask=cleaned_masks.free_mask,
            obstacle_mask=cleaned_masks.obstacle_mask,
            after_open_mask=cleaned_masks.after_open_mask,
            skeleton_mask=skeleton_view.skeleton_mask,
            skeleton_pruned_mask=pruned_skeleton_view.skeleton_pruned_mask,
            crop_box_px=frame.crop_box_px,
            skeleton_pixels_rc=pruned_skeleton_view.skeleton_pixels_rc,
            resolution_m_per_px=frame.resolution_m_per_px,
        ),
        meta={
            "stage_name": "geometry_preparation",
        },
    )
    return result
