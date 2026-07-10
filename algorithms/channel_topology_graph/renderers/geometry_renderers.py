"""GeometryPreparation 渲染正式入口。

真实职责：
    对外稳定暴露 geometry 领域的 summary/detail 写盘入口，
    由本文件直接承载 geometry_preparation 所需的渲染调度与绘图实现。

约束：
    本文件是 geometry 领域正式入口；
    不在这里承担跨领域聚合职责，也不把包级入口逻辑反向下沉到调用方。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..contracts import GeometryPreparationResult


def write_geometry_preparation_visualizations(
    result: GeometryPreparationResult,
    output_dir: str | Path,
    summary_viz: bool,
    detail_viz: bool,
    render_scale: int = 8,
) -> dict[str, Any]:
    """按开关写出 geometry_preparation 可视化结果。

    真实职责：
        把 geometry_preparation 的核心几何结果按 `summary/detail` 两层导出成图片，
        并且严格遵守开关：关闭时不生成目录、不执行渲染。

    Args:
        result:
            geometry_preparation 正式结果对象。
        output_dir:
            本次 geometry_preparation 可视化输出目录。
        summary_viz:
            是否生成模块总览图。
        detail_viz:
            是否生成逐轮修剪细节图。
        render_scale:
            渲染放大倍率。只影响导出图，不进入算法。

    Returns:
        dict[str, Any]:
            可视化输出摘要，包含实际写出的文件路径。
    """

    # 两个开关都关时，渲染层必须保持完全无副作用。
    if not summary_viz and not detail_viz:
        return {
            "write_summary_viz": False,
            "write_detail_viz": False,
            "summary_panel_path": None,
            "detail_dir": None,
        }

    # 真正要写图时才创建目录，避免空目录噪声。
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_panel_path: str | None = None
    detail_dir_path: str | None = None

    if summary_viz:
        # summary 图聚焦 geometry_preparation 总览，单文件即可快速判断是否异常。
        summary_panel = render_geometry_preparation_summary(result, render_scale=render_scale)
        summary_path = output_dir / "geometry_preparation_summary.png"
        write_image(summary_path, summary_panel)
        summary_panel_path = str(summary_path)

    if detail_viz:
        # detail 图按轮次导出，便于追修剪是否过度或未生效。
        detail_dir = output_dir / "details"
        detail_dir.mkdir(parents=True, exist_ok=True)
        write_geometry_preparation_details(result, detail_dir, render_scale=render_scale)
        detail_dir_path = str(detail_dir)
        # detail 目录路径只有在真正写出细节图时才会回填。

    # 返回值只记录真正的写出结果，不混入图像数组本体。
    # 调用方后续只需读取路径摘要即可决定是否把可视化信息挂回 meta。
    # 渲染层本身不修改结果对象，路径回写由 stage 层统一完成。
    # 这也让渲染层更容易在测试中被单独验证。
    # 返回结构本身也可直接进入过程记录或 smoke summary。
    # 开关语义和实际写盘结果在这里一一对应，便于上层核对。
    # 因而这个入口本质上是“渲染调度器”，不是具体绘图函数。
    return {
        "write_summary_viz": bool(summary_viz),
        "write_detail_viz": bool(detail_viz),
        "summary_panel_path": summary_panel_path,
        "detail_dir": detail_dir_path,
    }


def render_geometry_preparation_summary(
    result: GeometryPreparationResult,
    render_scale: int = 8,
) -> np.ndarray:
    """生成 geometry_preparation 总览图。"""

    # 总览图把 geometry_preparation 最关键的 6 个视角并排展示，方便人工快速扫一遍。
    panels = build_geometry_preparation_summary_panels(result, render_scale)
    # 固定三列布局，保证不同 case 的总览图结构一致。
    # 这样人工 diff 多个 case 时，不需要重新适应版式变化。
    # 总览图输出是 geometry_preparation 最主要的人工观察入口。
    # 只要这一张图正常，多数问题都能快速定位方向。
    # 因此这里优先保证“版式稳定”和“信息完整”，而不是极简图片数量。
    return grid_panels(panels, cols=3)


def build_geometry_preparation_summary_panels(
    result: GeometryPreparationResult,
    render_scale: int,
) -> list[np.ndarray]:
    """构造 geometry_preparation 总览图的固定 panel 集。"""

    gray = render_gray(result.gray, render_scale)
    region_overlay = overlay_mask(result.gray, result.region_mask, (80, 200, 80), 0.35, render_scale)
    free_overlay = overlay_mask(result.gray, result.free_mask, (60, 220, 255), 0.45, render_scale)
    open_overlay = overlay_mask(result.gray, result.after_open_mask, (255, 180, 60), 0.45, render_scale)
    # 两层骨架同时展示，是为了区分“骨架生成异常”和“修剪过度”。
    raw_skeleton_overlay = overlay_skeleton(result.gray, result.skeleton_mask, (255, 0, 0), render_scale)
    pruned_skeleton_overlay = overlay_skeleton(
        result.gray,
        result.skeleton_pruned_mask,
        (0, 255, 255),
        render_scale,
    )
    # region/free/after_open 三张空间图与骨架图一起，基本覆盖 geometry_preparation 主要判断面。

    panels = [
        label_panel(gray, "gray"),
        label_panel(region_overlay, "region"),
        label_panel(free_overlay, "free"),
        label_panel(open_overlay, "after_open"),
        label_panel(raw_skeleton_overlay, "skeleton_raw"),
        label_panel(pruned_skeleton_overlay, "skeleton_pruned"),
    ]
    return panels


def write_geometry_preparation_details(
    result: GeometryPreparationResult,
    detail_dir: str | Path,
    render_scale: int = 8,
) -> None:
    """写出 geometry_preparation 细节图。"""

    # detail 图全部从 pruning debug 中取材，不额外推导新真值。
    detail_dir = Path(detail_dir)
    pruning = (result.debug_info or {}).get("pruning", {})
    pruning_iterations = pruning.get("pruning_iterations", [])

    for index, item in iter_pruning_iterations(pruning_iterations):
        # 每轮 detail 都从调试字典读取上一轮已经保存的掩膜真值。
        removed_mask = item.get("removed_mask")
        skeleton_after_mask = item.get("skeleton_after_mask")
        if removed_mask is None or skeleton_after_mask is None:
            # 若当前调试信息没有保留可视化所需掩膜，就直接跳过该轮 detail。
            continue

        # 每轮 detail 固定展示“删掉什么”和“删完剩什么”两块面板。
        panel = build_pruning_iteration_panel(
            gray=result.gray,
            removed_mask=removed_mask,
            skeleton_after_mask=skeleton_after_mask,
            index=index,
            render_scale=render_scale,
        )
        # 文件名带轮次编号，保证 detail 输出顺序稳定可追踪。
        # 调试轮次即使中间有空缺，也不会影响已经写出的其它轮次。
        # 因此 detail 目录天然适合按时间顺序人工回放修剪过程。
        # 细节图输出和 summary 图相互独立，任一关闭都不影响另一方。
        # 这让调用方可以单独打开 detail，而不必先生成 summary。
        # 每轮 panel 都是固定两列，便于肉眼比对“删前删后”的局部变化。
        write_image(detail_dir / f"pruning_iter_{index:03d}.png", panel)


def iter_pruning_iterations(pruning_iterations: Any) -> list[tuple[int, dict[str, Any]]]:
    """给 pruning 轮次提供稳定编号。"""

    return [(index, item) for index, item in enumerate(pruning_iterations, start=1)]


def build_pruning_iteration_panel(
    gray: np.ndarray,
    removed_mask: np.ndarray,
    skeleton_after_mask: np.ndarray,
    index: int,
    render_scale: int,
) -> np.ndarray:
    """构造单轮 pruning detail 图。"""

    removed_overlay = overlay_mask(gray, removed_mask, (0, 0, 255), 0.55, render_scale)
    skeleton_after_overlay = overlay_skeleton(
        gray,
        skeleton_after_mask,
        (0, 255, 255),
        render_scale,
    )
    return grid_panels(
        [
            label_panel(removed_overlay, f"removed_iter_{index}"),
            label_panel(skeleton_after_overlay, f"skeleton_after_iter_{index}"),
        ],
        cols=2,
    )


def render_gray(gray: np.ndarray, render_scale: int) -> np.ndarray:
    """把灰度图渲染成 BGR 面板。"""

    # 单独抽 helper 是为了让所有 overlay 都共享同一底图放大逻辑。
    return upsample_nearest(to_bgr(gray), render_scale)


def overlay_mask(
    base_gray: np.ndarray,
    mask: np.ndarray,
    color: tuple[int, int, int],
    alpha: float,
    render_scale: int,
) -> np.ndarray:
    """把掩膜叠到灰度图上。"""

    # 先把底图和彩色掩膜对齐到同一渲染尺度，再做透明叠加。
    base = render_gray(base_gray, render_scale)
    scaled_mask = upsample_nearest(np.where(mask > 0, 255, 0).astype(np.uint8), render_scale)
    tinted = base.copy()
    # 仅在掩膜有效区域染色，底图其它部分保持原灰度。
    tinted[scaled_mask > 0] = color
    # 透明混合比由调用方显式决定，helper 不自己改策略。
    # 因而同一 helper 可以同时服务 region/free/after_open 三类掩膜叠加。
    return cv2.addWeighted(tinted, alpha, base, 1.0 - alpha, 0.0)


def overlay_skeleton(
    base_gray: np.ndarray,
    skeleton_mask: np.ndarray,
    color: tuple[int, int, int],
    render_scale: int,
) -> np.ndarray:
    """把骨架掩膜叠到灰度图上。"""

    # 骨架渲染不做透明混合，直接高亮像素更利于看连通性。
    base = render_gray(base_gray, render_scale)
    scaled_mask = upsample_nearest(np.where(skeleton_mask > 0, 255, 0).astype(np.uint8), render_scale)
    # 高亮颜色只覆盖骨架点，底图其余区域完整保留。
    base[scaled_mask > 0] = color
    # 直接着色比半透明叠加更容易看清骨架是否断裂。
    # 尤其在细线骨架上，透明叠加容易让线段发灰不清楚。
    return base


def label_panel(image: np.ndarray, label: str) -> np.ndarray:
    """给面板加标题。"""

    # 标题条高度固定，保证不同 panel 拼网格时顶部视觉一致。
    bar_height = 28
    title_bar = np.full((bar_height, image.shape[1], 3), 245, dtype=np.uint8)
    # 标题绘制使用统一字体和位置，保证整组 detail/summary 风格一致。
    cv2.putText(title_bar, label, (8, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (30, 30, 30), 1, cv2.LINE_AA)
    return np.vstack([title_bar, image])


def grid_panels(panels: list[np.ndarray], cols: int) -> np.ndarray:
    """把若干面板拼成网格。"""

    # 网格 helper 不接受空输入，避免生成无意义空白图。
    if not panels:
        raise ValueError("panels must not be empty")

    # 先统一 panel 尺寸，再按固定列数拼接。
    height = max(panel.shape[0] for panel in panels)
    width = max(panel.shape[1] for panel in panels)
    normalized = [pad_to_size(panel, height, width) for panel in panels]

    rows = []
    for start in range(0, len(normalized), cols):
        row_panels = normalized[start:start + cols]
        # 最后一行不足列数时补白板，维持网格矩形结构。
        while len(row_panels) < cols:
            row_panels.append(np.full((height, width, 3), 255, dtype=np.uint8))
        rows.append(np.hstack(row_panels))
    # 先横向拼每一行，再整体纵向堆叠，逻辑最直观。
    # 这种拼接方式也方便后续扩充更多 panel 而不改总布局逻辑。
    return np.vstack(rows)


def pad_to_size(image: np.ndarray, height: int, width: int) -> np.ndarray:
    """把面板补到统一尺寸。"""

    # 白底补边，避免不同面板尺寸导致拼图错位。
    out = np.full((height, width, 3), 255, dtype=np.uint8)
    out[: image.shape[0], : image.shape[1]] = image
    # 左上角对齐即可，不在这里做居中排版。
    return out


def upsample_nearest(image: np.ndarray, render_scale: int) -> np.ndarray:
    """按最近邻做渲染放大。"""

    # 最近邻放大能保留栅格边界，不把掩膜和骨架渲染成模糊块。
    scale = max(1, int(render_scale))
    if scale == 1:
        return image.copy()
    # 非 1 倍时统一走 OpenCV resize，避免手写 repeat 分支。
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)


def to_bgr(gray: np.ndarray) -> np.ndarray:
    """把单通道灰度图转成 BGR。"""

    # 单通道时显式扩成三通道，彩色叠加 helper 才能统一工作。
    if gray.ndim == 2:
        return cv2.cvtColor(gray.astype(np.uint8), cv2.COLOR_GRAY2BGR)
    # 已经是多通道图时只复制，不在渲染层重新解释颜色空间。
    return gray.copy()


def write_image(path: str | Path, image: np.ndarray) -> None:
    """写出图片文件。"""

    # 写盘前统一创建父目录，避免调用方提前管理层级。
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 写失败直接抛错，不把可视化问题静默吞掉。
    if not cv2.imwrite(str(path), image):
        raise IOError(f"failed to write image: {path}")
