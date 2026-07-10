"""Junction rebuild 视图装配与写盘层。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ...contracts import GeometryPreparationResult, JunctionRebuildResult
from .junction_render_overlay import crop_focus_region as crop_focus_region, draw_complete_junction_overlay as draw_complete_junction_overlay, draw_native_geometry_overlay as draw_native_geometry_overlay
from .junction_render_palette import AUX_GEOMETRY_COLOR as _AUX_GEOMETRY_COLOR, NODE_COLOR as _NODE_COLOR, NODE_TEXT_FILL as _NODE_TEXT_FILL, SKELETON_COLOR as _SKELETON_COLOR
from .junction_render_primitives import (
    draw_circle_outline as draw_circle_outline,
    draw_mask_points as draw_mask_points,
    draw_single_pixel as draw_single_pixel,
    draw_text as draw_text,
    render_gray as render_gray,
    write_image as write_image,
)


def build_empty_junction_visualization_result() -> dict[str, Any]:
    """返回关闭全部开关时的空写盘结果。"""

    return {
        "write_summary_viz": False,
        "write_detail_viz": False,
        "summary_panel_path": None,
        "native_geometry_path": None,
        "detail_dir": None,
    }


def build_junction_visualization_result(
    summary_viz: bool,
    detail_viz: bool,
    summary_panel_path: str | None,
    native_geometry_path: str | None,
    detail_dir_path: str | None,
) -> dict[str, Any]:
    """构造 junction rebuild 可视化写盘摘要。"""

    return {
        "write_summary_viz": bool(summary_viz),
        "write_detail_viz": bool(detail_viz),
        "summary_panel_path": summary_panel_path,
        "native_geometry_path": native_geometry_path,
        "detail_dir": detail_dir_path,
    }


def write_junction_summary_outputs(
    geometry_result: GeometryPreparationResult,
    result: JunctionRebuildResult,
    output_dir: Path,
    render_scale: int,
) -> tuple[str, str]:
    """写出 summary 与 native geometry 两张总览图。"""

    summary_panel = render_junction_rebuild_summary(geometry_result, result, render_scale)
    summary_path = output_dir / "junction_rebuild_summary.png"
    write_image(summary_path, summary_panel)

    native_geometry = render_junction_rebuild_native_geometry(geometry_result, result)
    native_path = output_dir / "junction_rebuild_native_geometry.png"
    write_image(native_path, native_geometry)
    return str(summary_path), str(native_path)


def write_junction_detail_outputs(
    geometry_result: GeometryPreparationResult,
    result: JunctionRebuildResult,
    output_dir: Path,
    render_scale: int,
) -> str:
    """写出 junction rebuild detail 目录。"""

    detail_dir = output_dir / "details"
    detail_dir.mkdir(parents=True, exist_ok=True)
    write_junction_rebuild_details(geometry_result, result, detail_dir, render_scale)
    return str(detail_dir)


def write_junction_rebuild_visualizations(
    geometry_result: GeometryPreparationResult,
    result: JunctionRebuildResult,
    output_dir: str | Path,
    summary_viz: bool,
    detail_viz: bool,
    render_scale: int = 8,
) -> dict[str, Any]:
    """按开关写出 junction rebuild 可视化结果。"""

    # 两个开关都关闭时，不创建任何文件，只返回空结果清单。
    if not summary_viz and not detail_viz:
        return build_empty_junction_visualization_result()

    # 输出根目录统一由这里创建。
    # 下游 helper 都假定父目录已经就绪。
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_panel_path: str | None = None
    native_geometry_path: str | None = None
    detail_dir_path: str | None = None
    # 路径字段先初始化为 None，保证返回结构稳定。

    # summary 模式会同时产出放大叠加图和原始尺寸纯几何图。
    # 两张图分别服务于“解释过程”和“对照几何”的不同场景。
    if summary_viz:
        summary_panel_path, native_geometry_path = write_junction_summary_outputs(
            geometry_result=geometry_result,
            result=result,
            output_dir=output_dir,
            render_scale=render_scale,
        )

    # detail 模式会再按 merge group 和节点局部写出多张细节图。
    if detail_viz:
        # detail helper 自身不返回路径列表，因此这里单独记录目录路径。
        # 目录名固定为 `details`，便于用户快速浏览节点局部图。
        detail_dir_path = write_junction_detail_outputs(
            geometry_result=geometry_result,
            result=result,
            output_dir=output_dir,
            render_scale=render_scale,
        )

    # 返回字典保留显式布尔字段，方便 pipeline 上层直接判断是否写盘。
    # 同时保留 summary/native/detail 三类产物的独立路径入口。
    # 调用方因此可以按需只消费某一类产物，而不必猜目录结构。
    return build_junction_visualization_result(
        summary_viz=summary_viz,
        detail_viz=detail_viz,
        summary_panel_path=summary_panel_path,
        native_geometry_path=native_geometry_path,
        detail_dir_path=detail_dir_path,
    )


def render_junction_rebuild_summary(
    geometry_result: GeometryPreparationResult,
    result: JunctionRebuildResult,
    render_scale: int = 8,
) -> np.ndarray:
    """生成 junction rebuild 统一最终叠加图。"""

    # 先把灰底放大到统一渲染尺度。
    canvas = render_gray(geometry_result.gray, render_scale)
    # skeleton 作为底层参考先落图，帮助解释 junction 生成来源。
    draw_mask_points(canvas, geometry_result.skeleton_pruned_mask, _SKELETON_COLOR, render_scale)
    # 再叠加完整 junction 几何 overlay，保持结构层次清晰。
    draw_complete_junction_overlay(canvas=canvas, result=result, render_scale=render_scale)
    return canvas


def render_junction_rebuild_native_geometry(
    geometry_result: GeometryPreparationResult,
    result: JunctionRebuildResult,
) -> np.ndarray:
    """生成原始尺寸的纯几何结果图。"""

    # native geometry 图固定用原图尺寸，不做 render_scale 放大。
    canvas = render_gray(geometry_result.gray, render_scale=1)
    # 这里只画纯几何，不再叠加 skeleton 或额外 debug 元素。
    draw_native_geometry_overlay(canvas, result)
    # 返回值可直接用于和原始像素语义做逐像素对照。
    return canvas


def write_junction_rebuild_details(
    geometry_result: GeometryPreparationResult,
    result: JunctionRebuildResult,
    detail_dir: str | Path,
    render_scale: int = 8,
) -> None:
    """写出 junction rebuild 节点级细节图。"""

    # 细节图目录由上层传入，这里只负责填充内容。
    detail_dir = Path(detail_dir)
    merge_groups = (result.debug_info or {}).get("merge_groups_applied", [])
    # 第一批 detail 图先解释 merge group 的 survivor 关系。
    for index, group in enumerate(merge_groups, start=1):
        panel = render_gray(geometry_result.gray, render_scale)
        # merge group 图同样保留 skeleton 底层，方便解释合并依据。
        draw_mask_points(panel, geometry_result.skeleton_pruned_mask, _SKELETON_COLOR, render_scale)
        for node in result.node_info_list:
            # survivor 节点用主节点色，其余被合并节点用辅助色。
            color = _NODE_COLOR if int(node.node_id) == int(group["survivor_node_id"]) else _AUX_GEOMETRY_COLOR
            draw_single_pixel(panel, node.point_rc, color, render_scale)
            draw_circle_outline(panel, node.point_rc, color, render_scale, radius_px=10)
            draw_text(panel, str(int(node.node_id)), node.point_rc, _NODE_TEXT_FILL, render_scale)
        # 每个 merge group 一张独立图，文件名按序号稳定排序。
        # 这批图不裁切，目的是看清一次 merge 涉及的所有节点相对位置。
        write_image(detail_dir / f"merge_group_{index:03d}.png", panel)

    # 第二批 detail 图按最终 junction 节点逐个输出局部 focus 图。
    for node in result.node_info_list:
        if node.node_type != "junction":
            continue
        panel = render_gray(geometry_result.gray, render_scale)
        # detail panel 先铺 skeleton，再叠 focus overlay，层次和总览图一致。
        draw_mask_points(panel, geometry_result.skeleton_pruned_mask, _SKELETON_COLOR, render_scale)
        # overlay 内部会自动筛出与 focus 节点直接相关的边和节点。
        draw_complete_junction_overlay(
            canvas=panel,
            result=result,
            render_scale=render_scale,
            focus_node_id=int(node.node_id),
        )
        # 最终只裁出 focus 节点局部，减少无关背景区域。
        cropped = crop_focus_region(
            image=panel,
            result=result,
            render_scale=render_scale,
            focus_node_id=int(node.node_id),
            margin_px=32,
        )
        # 输出文件名直接绑定 node_id，便于人工定位具体节点。
        # 裁切后的图片更适合人工逐节点核查，不会被全图背景稀释。
        write_image(detail_dir / f"node_{int(node.node_id):03d}.png", cropped)
