"""geometry_preparation 结果正式校验。"""

from __future__ import annotations

from typing import Any

import numpy as np


def require_gray_base_shape(gray: Any) -> tuple[int, int]:
    """锁定 geometry_preparation 所有掩膜共享的基准 shape。"""

    # gray 是 geometry_preparation 局部坐标系的唯一基准。
    # 只要它为空或不是二维图，后续所有 mask/skeleton 校验都失去参照。
    if not isinstance(gray, np.ndarray) or gray.ndim != 2 or getattr(gray, "size", 0) == 0:
        raise ValueError("gray must not be empty")
    return gray.shape


def validate_stage_masks_against_base_shape(
    base_shape: tuple[int, int],
    region_mask: Any,
    free_mask: Any,
    obstacle_mask: Any,
    after_open_mask: Any,
    skeleton_mask: Any,
    skeleton_pruned_mask: Any,
) -> None:
    """按统一基准 shape 校验所有正式掩膜。"""

    validate_binary_mask("region_mask", region_mask, base_shape)
    validate_binary_mask("free_mask", free_mask, base_shape)
    validate_binary_mask("obstacle_mask", obstacle_mask, base_shape)
    validate_binary_mask("after_open_mask", after_open_mask, base_shape)
    validate_binary_mask("skeleton_mask", skeleton_mask, base_shape)
    validate_binary_mask("skeleton_pruned_mask", skeleton_pruned_mask, base_shape)


def validate_geometry_preparation_primitives(
    free_mask: Any,
    skeleton_pixels_rc: tuple[tuple[int, int], ...],
    resolution_m_per_px: float,
) -> None:
    """校验 junction_rebuild 运行所需的最小几何前提。"""

    if int(np.count_nonzero(free_mask)) == 0:
        raise ValueError("free_mask must contain traversable pixels")
    if len(skeleton_pixels_rc) == 0:
        raise ValueError("skeleton_pruned_mask must contain skeleton pixels")
    if float(resolution_m_per_px) <= 0:
        # 分辨率一旦非正，后续所有米制换算都会整体失真，因此直接视为硬错误。
        raise ValueError("resolution_m_per_px must be positive")


def validate_geometry_preparation_cross_field_consistency(
    region_mask: np.ndarray,
    free_mask: np.ndarray,
    obstacle_mask: np.ndarray,
    skeleton_mask: np.ndarray,
    skeleton_pruned_mask: np.ndarray,
    crop_box_px: tuple[int, int, int, int],
    base_shape: tuple[int, int],
    skeleton_pixels_rc: tuple[tuple[int, int], ...],
) -> None:
    """校验几何结果各字段之间的闭环一致性。"""

    validate_crop_box(crop_box_px, base_shape)
    validate_mask_relations(
        region_mask=region_mask,
        free_mask=free_mask,
        obstacle_mask=obstacle_mask,
        skeleton_mask=skeleton_mask,
        skeleton_pruned_mask=skeleton_pruned_mask,
    )
    validate_skeleton_pixels_rc(skeleton_pruned_mask, skeleton_pixels_rc)


def build_geometry_preparation_validation_summary(
    gray: np.ndarray,
    crop_box_px: tuple[int, int, int, int],
    free_mask: np.ndarray,
    obstacle_mask: np.ndarray,
    skeleton_pixels_rc: tuple[tuple[int, int], ...],
    resolution_m_per_px: float,
) -> dict[str, Any]:
    """构造 geometry_preparation 的正式 validation 摘要。"""

    return {
        # gray_shape / crop_box_px 共同定义当前正式局部参考系。
        "gray_shape": tuple(int(v) for v in gray.shape),
        "crop_box_px": tuple(int(v) for v in crop_box_px),
        # 这些计数用于快速判断空间清理或骨架生成是否异常收缩。
        "free_pixel_count": int((free_mask > 0).sum()),
        "obstacle_pixel_count": int((obstacle_mask > 0).sum()),
        "skeleton_pixel_count": int(len(skeleton_pixels_rc)),
        "resolution_m_per_px": float(resolution_m_per_px),
    }


def validate_geometry_preparation_result(
    region_mask: Any,
    gray: Any,
    free_mask: Any,
    obstacle_mask: Any,
    after_open_mask: Any,
    skeleton_mask: Any,
    skeleton_pruned_mask: Any,
    crop_box_px: tuple[int, int, int, int],
    skeleton_pixels_rc: tuple[tuple[int, int], ...],
    resolution_m_per_px: float,
) -> dict[str, Any]:
    """校验 geometry_preparation 结果是否具备下游消费条件。

    真实职责：
        对灰度图、自由空间、骨架和分辨率做最小闭环检查，
        防止 junction_rebuild 拿到空洞或不完整的几何世界。
    """

    # 先锁住灰度图这个“公共基准 shape”，后续所有掩膜都必须与它严格对齐。
    base_shape = require_gray_base_shape(gray)
    # base_shape 一旦确定，后续所有数组级关系都要以它为唯一参照。
    # 逐类掩膜做同口径校验，避免某一层偷偷引入非二值或错 shape 数据。
    validate_stage_masks_against_base_shape(
        base_shape=base_shape,
        region_mask=region_mask,
        free_mask=free_mask,
        obstacle_mask=obstacle_mask,
        after_open_mask=after_open_mask,
        skeleton_mask=skeleton_mask,
        skeleton_pruned_mask=skeleton_pruned_mask,
    )

    # 自由空间、骨架和分辨率是 junction_rebuild 能否运行的最小物理前提。
    validate_geometry_preparation_primitives(
        free_mask=free_mask,
        skeleton_pixels_rc=skeleton_pixels_rc,
        resolution_m_per_px=resolution_m_per_px,
    )
    # 单字段通过后，再做跨字段关系校验，避免“各自合法、组合失真”。
    # crop_box 控制局部坐标系闭环，mask relation 控制像素语义闭环。
    # skeleton_pixels_rc 则补上“显式索引集合”和掩膜的一致性闭环。
    validate_geometry_preparation_cross_field_consistency(
        region_mask=region_mask,
        free_mask=free_mask,
        obstacle_mask=obstacle_mask,
        skeleton_mask=skeleton_mask,
        skeleton_pruned_mask=skeleton_pruned_mask,
        crop_box_px=crop_box_px,
        base_shape=base_shape,
        skeleton_pixels_rc=skeleton_pixels_rc,
    )

    # 返回显式摘要而不是单纯返回 True，后续可以直接挂到 result.validation_info。
    # 摘要层只暴露最常被人工核对的 shape/计数/分辨率信息。
    # 这些字段也正是 real-case summary 会优先展示的内容。
    # 校验层不返回中间数组，避免 validation_info 膨胀成另一份结果对象。
    # 摘要字段名也尽量贴 stage summary 口径，方便人工横向比对。
    return build_geometry_preparation_validation_summary(
        gray=gray,
        crop_box_px=crop_box_px,
        free_mask=free_mask,
        obstacle_mask=obstacle_mask,
        skeleton_pixels_rc=skeleton_pixels_rc,
        resolution_m_per_px=resolution_m_per_px,
    )


def validate_binary_mask(name: str, mask: Any, expected_shape: tuple[int, int]) -> None:
    """校验掩膜基础约束。"""

    # geometry_preparation 所有正式掩膜都必须是二维数组，避免后续 OpenCV/Numpy 语义漂移。
    if not isinstance(mask, np.ndarray) or mask.ndim != 2:
        raise ValueError(f"{name} must be a 2D numpy array")
    # shape 一旦不齐，所有像素级逻辑都会错位，因此这里直接拒绝。
    if mask.shape != expected_shape:
        raise ValueError(f"{name} shape mismatch: expected {expected_shape}, got {mask.shape}")
    # 二值约束锁住 0/255 语义，避免下游把灰度中间态误当正式掩膜。
    unique_values = set(int(v) for v in np.unique(mask))
    if not unique_values.issubset({0, 255}):
        # 这里拒绝灰度残值，是为了锁住正式掩膜的二值语义，避免下游 helper 各自解释阈值。
        raise ValueError(f"{name} must be binary 0/255, got {sorted(unique_values)}")


def validate_crop_box(crop_box_px: tuple[int, int, int, int], gray_shape: tuple[int, int]) -> None:
    """校验裁剪框合法性。"""

    # 裁剪框固定采用 top/left/bottom/right 四元表达，长度不对直接视为脏数据。
    if len(crop_box_px) != 4:
        raise ValueError("crop_box_px must contain 4 integers")
    top, left, bottom, right = (int(v) for v in crop_box_px)
    # 裁剪框必须形成正面积矩形，不能接受倒序或越界零宽/零高框。
    if not (top >= 0 and left >= 0 and bottom > top and right > left):
        # 这里拒绝零宽/零高或倒序框，因为那会直接破坏局部坐标系定义。
        raise ValueError(f"crop_box_px is invalid: {crop_box_px}")
    # geometry_preparation 结果里的 gray 已经是裁剪后局部图，因此 shape 必须严格对齐裁剪框尺寸。
    # 这里不允许“近似一致”，因为像素级错一行都会让坐标系错位。
    if (bottom - top, right - left) != gray_shape:
        raise ValueError(
            f"crop_box_px does not match gray shape: crop_box={crop_box_px}, gray_shape={gray_shape}"
        )


def validate_mask_relations(
    region_mask: np.ndarray,
    free_mask: np.ndarray,
    obstacle_mask: np.ndarray,
    skeleton_mask: np.ndarray,
    skeleton_pruned_mask: np.ndarray,
) -> None:
    """校验不同掩膜之间的几何关系。"""

    # 自由空间与障碍都必须留在 region 内，否则说明有效区域裁剪已经失真。
    if np.any((free_mask > 0) & (region_mask == 0)):
        raise ValueError("free_mask must stay inside region_mask")
    if np.any((obstacle_mask > 0) & (region_mask == 0)):
        raise ValueError("obstacle_mask must stay inside region_mask")
    # 自由/障碍重叠意味着语义冲突，下游无法判断该像素是否可走。
    if np.any((free_mask > 0) & (obstacle_mask > 0)):
        raise ValueError("free_mask and obstacle_mask must not overlap")
    # 骨架是自由空间内部的中心线，绝不能落到障碍或区域外。
    # 这里只要求 raw skeleton 在 free 内，pruned skeleton 再额外要求是 raw 的子集。
    # 这对应“生成阶段”和“修剪阶段”两层不同的几何约束。
    if np.any((skeleton_mask > 0) & (free_mask == 0)):
        raise ValueError("skeleton_mask must stay inside free_mask")
    # 修剪只能删除骨架像素，不能凭空长出新骨架。
    if np.any((skeleton_pruned_mask > 0) & (skeleton_mask == 0)):
        raise ValueError("skeleton_pruned_mask must be a subset of skeleton_mask")


def validate_skeleton_pixels_rc(
    skeleton_pruned_mask: np.ndarray,
    skeleton_pixels_rc: tuple[tuple[int, int], ...],
) -> None:
    """校验骨架像素坐标与掩膜的一致性。"""

    # 像素坐标列表既是显式索引真值，也是与掩膜互校的对象级契约。
    height, width = skeleton_pruned_mask.shape
    point_set = set()
    for point_rc in skeleton_pixels_rc:
        # 每个点都必须是标准 `(row, col)` 二元坐标。
        if len(point_rc) != 2:
            raise ValueError(f"invalid skeleton point: {point_rc}")
        r, c = (int(point_rc[0]), int(point_rc[1]))
        # 坐标越界说明坐标系和裁剪框已经不一致。
        if not (0 <= r < height and 0 <= c < width):
            raise ValueError(f"skeleton point out of bounds: {(r, c)}")
        # 显式列表不允许重复点，否则很多路径/邻域逻辑会重复消费同一像素。
        if (r, c) in point_set:
            raise ValueError(f"duplicated skeleton point: {(r, c)}")
        # 列表里的每个点都必须能回指到修剪后骨架掩膜中的有效像素。
        if skeleton_pruned_mask[r, c] == 0:
            raise ValueError(f"skeleton point missing in mask: {(r, c)}")
        point_set.add((r, c))

    # 最后做“双向闭环”：掩膜上的点不能多，显式列表里的点也不能少。
    # 这里故意做集合全等，而不是只校验子集，防止静默漏点。
    mask_point_set = {tuple(map(int, point)) for point in np.argwhere(skeleton_pruned_mask > 0)}
    if point_set != mask_point_set:
        raise ValueError("skeleton_pixels_rc must match skeleton_pruned_mask exactly")
