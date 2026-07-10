"""Junction rebuild 几何 overlay 语义层。"""

from __future__ import annotations

from typing import Any

import numpy as np

from ...contracts import JunctionRebuildResult
from .junction_render_palette import (
    AUX_GEOMETRY_COLOR as _AUX_GEOMETRY_COLOR,
    AUX_SCAN_COLOR as _AUX_SCAN_COLOR,
    EDGE_TEXT_FILL as _EDGE_TEXT_FILL,
    FULL_PATH_COLOR as _FULL_PATH_COLOR,
    INNER_PATH_COLOR as _INNER_PATH_COLOR,
    NODE_COLOR as _NODE_COLOR,
    NODE_TEXT_FILL as _NODE_TEXT_FILL,
    OUTER_PATH_COLOR as _OUTER_PATH_COLOR,
    POLYGON_COLOR as _POLYGON_COLOR,
)
from .junction_render_primitives import (
    draw_circle_outline as draw_circle_outline,
    draw_dashed_segment as draw_dashed_segment,
    draw_path_points as draw_path_points,
    draw_polygon_outline as draw_polygon_outline,
    draw_single_pixel as draw_single_pixel,
    draw_text as draw_text,
    path_midpoint as path_midpoint,
    point_from_angle as point_from_angle,
)


def draw_complete_junction_overlay(
    canvas: np.ndarray,
    result: JunctionRebuildResult,
    render_scale: int,
    focus_node_id: int | None = None,
) -> None:
    """在一张图上画出 junction rebuild 最终几何状态。"""

    # focus 模式下不只画目标节点本身，还要把相邻节点和边一起带出来。
    # 这样 detail 图才能解释“这个节点为何形成当前几何”。
    relevant_node_ids = collect_relevant_node_ids(result, focus_node_id)
    relevant_edge_ids = collect_relevant_edge_ids(result, relevant_node_ids)

    # 第一层先画节点 polygon 边界。
    # 它提供 junction 轮廓范围，但不会挡住后续更重要的路径和标记。
    for node in result.node_info_list:
        if int(node.node_id) not in relevant_node_ids:
            continue
        if node.polygon_vertices_rc:
            draw_polygon_outline(canvas, node.polygon_vertices_rc, _POLYGON_COLOR, render_scale)

    # 第二层画 edge 的 full / outer / inner 三组路径离散点。
    # 这几组点叠在一起时，能直接对比路径修正前后的空间关系。
    for edge in result.edge_info_list:
        if int(edge.edge_id) not in relevant_edge_ids:
            continue
        draw_path_points(canvas, edge.path_rc, _FULL_PATH_COLOR, render_scale)
        draw_path_points(canvas, edge.outer_path_rc, _OUTER_PATH_COLOR, render_scale)
        draw_path_points(canvas, edge.inner_path_rc, _INNER_PATH_COLOR, render_scale)
        # 边编号落在原始 path 中位点，保证标签位置稳定且易于回溯。
        draw_text(canvas, str(int(edge.edge_id)), path_midpoint(edge.path_rc), _EDGE_TEXT_FILL, render_scale)

    # 第三层叠加节点内部的 geometry debug 信息。
    # 这一层包含扇区、命中点、cut 点等解释性辅助几何。
    for node in result.node_info_list:
        if int(node.node_id) not in relevant_node_ids:
            continue
        geometry_debug = (node.debug_info or {}).get("junction_geometry")
        if geometry_debug is not None:
            draw_final_round_geometry(canvas=canvas, geometry_debug=geometry_debug, render_scale=render_scale)

    # 最后一层才画节点中心和节点编号。
    # 这样节点标记始终压在最上层，不会被 polygon 或路径点淹没。
    for node in result.node_info_list:
        if int(node.node_id) not in relevant_node_ids:
            continue
        draw_single_pixel(canvas, node.point_rc, _NODE_COLOR, render_scale)
        draw_circle_outline(canvas, node.point_rc, _NODE_COLOR, render_scale, radius_px=10)
        draw_text(canvas, str(int(node.node_id)), node.point_rc, _NODE_TEXT_FILL, render_scale)


def draw_native_geometry_overlay(
    canvas: np.ndarray,
    result: JunctionRebuildResult,
) -> None:
    """在原始尺寸底图上画纯几何结果。"""

    # native 视图不放大、不裁剪，目标是直接对照原始像素空间。
    # 因而这里统一把 render_scale 固定为 1。
    for node in result.node_info_list:
        if node.polygon_vertices_rc:
            draw_polygon_outline(canvas, node.polygon_vertices_rc, _POLYGON_COLOR, render_scale=1)

    # 边只画 outer / inner 两组结果，突出最终几何轮廓。
    # 原始 full path 在这个视图里信息量较低，就不重复叠加。
    for edge in result.edge_info_list:
        draw_path_points(canvas, edge.outer_path_rc, _OUTER_PATH_COLOR, render_scale=1)
        draw_path_points(canvas, edge.inner_path_rc, _INNER_PATH_COLOR, render_scale=1)

    # 节点中心最后补上，方便直接目测几何是否围绕节点收拢。
    for node in result.node_info_list:
        draw_single_pixel(canvas, node.point_rc, _NODE_COLOR, render_scale=1)


def draw_final_round_geometry(
    canvas: np.ndarray,
    geometry_debug: dict[str, Any],
    render_scale: int,
) -> None:
    """画单个节点最终轮扇区、扫描命中点、截断点和扇区圆心。"""

    # evaluation center 是扇区扫描使用的中心。
    # 它和最终 node center 不一定完全重合，因此需要分别标出来。
    sector_center_rc = tuple(map(float, geometry_debug["evaluation_center_rc"]))
    final_center_rc = tuple(map(float, geometry_debug["final_node_center_rc"]))
    draw_single_pixel(canvas, sector_center_rc, _AUX_GEOMETRY_COLOR, render_scale)
    draw_circle_outline(canvas, sector_center_rc, _AUX_GEOMETRY_COLOR, render_scale, radius_px=10)

    # truncation 记录 polygon 裁断后的 cut 点及相关路径。
    # cut 点单独圈出来，便于判断边界收缩是否发生在预期位置。
    for truncation_item in geometry_debug.get("truncation", []):
        cut_point_rc = tuple(map(float, truncation_item["cut_point_rc"]))
        draw_single_pixel(canvas, cut_point_rc, _AUX_GEOMETRY_COLOR, render_scale)
        draw_circle_outline(canvas, cut_point_rc, _AUX_GEOMETRY_COLOR, render_scale, radius_px=10)

    # support sector 既要画角度范围，也要画扫描命中点。
    # 代表点额外高亮，用于解释该扇区最终选择了哪个方向。
    for sector_item in geometry_debug.get("support_sectors", []):
        draw_sector_range(canvas, sector_center_rc, sector_item, render_scale)
        for hit_point_rc in sector_item.get("hit_points_rc", []):
            draw_single_pixel(canvas, tuple(map(float, hit_point_rc)), _AUX_SCAN_COLOR, render_scale)
        representative_point = sector_item.get("representative_point_rc")
        if representative_point is not None:
            draw_single_pixel(canvas, tuple(map(float, representative_point)), _AUX_GEOMETRY_COLOR, render_scale)

    # 最终 node center 作为结论点最后落图，和中间分析过程点区分开。
    draw_single_pixel(canvas, final_center_rc, _NODE_COLOR, render_scale)


def draw_sector_range(
    canvas: np.ndarray,
    sector_center_rc: tuple[float, float],
    sector_item: dict[str, Any],
    render_scale: int,
    radius_px: float = 24.0,
) -> None:
    """画单个扇区的起止边界虚线。"""

    # 扇区边界只需要从中心向外延伸一小段，用于表达角度张角。
    # radius_px 因而是视觉辅助长度，不是任何真实拓扑半径。
    start_point_rc = point_from_angle(sector_center_rc, float(sector_item["start_theta_deg"]), radius_px)
    end_point_rc = point_from_angle(sector_center_rc, float(sector_item["end_theta_deg"]), radius_px)
    # 起止边界都画成虚线，避免它们和主路径几何混淆。
    # 两条线共享同一颜色语义，强调它们属于同一扇区范围。
    draw_dashed_segment(canvas, sector_center_rc, start_point_rc, _AUX_GEOMETRY_COLOR, render_scale)
    draw_dashed_segment(canvas, sector_center_rc, end_point_rc, _AUX_GEOMETRY_COLOR, render_scale)


def collect_relevant_node_ids(result: JunctionRebuildResult, focus_node_id: int | None) -> set[int]:
    """收集本次渲染需要显示的节点集合。"""

    # 全局视图直接返回所有节点，不做筛选。
    if focus_node_id is None:
        return {int(node.node_id) for node in result.node_info_list}
    # focus 视图至少保留目标节点自身。
    relevant = {int(focus_node_id)}
    for edge in result.edge_info_list:
        # 任何和 focus 节点相连的边，都会把两端节点一起带入局部视图。
        if int(edge.src_node_id) == int(focus_node_id) or int(edge.dst_node_id) == int(focus_node_id):
            relevant.add(int(edge.src_node_id))
            relevant.add(int(edge.dst_node_id))
    return relevant


def collect_relevant_edge_ids(result: JunctionRebuildResult, relevant_node_ids: set[int]) -> set[int]:
    """收集本次渲染需要显示的边集合。"""

    # 边筛选标准故意取“任一端点命中”。
    # 这样 focus 节点的外连边不会因为另一端超出局部集合而被漏掉。
    return {
        int(edge.edge_id)
        for edge in result.edge_info_list
        if int(edge.src_node_id) in relevant_node_ids or int(edge.dst_node_id) in relevant_node_ids
    }


def crop_focus_region(
    image: np.ndarray,
    result: JunctionRebuildResult,
    render_scale: int,
    focus_node_id: int,
    margin_px: int,
) -> np.ndarray:
    """按节点局部范围裁出 detail 图。"""

    # 裁剪区域以目标节点为核心，并逐步吸纳与它直接相关的几何证据点。
    focus_node = next(node for node in result.node_info_list if int(node.node_id) == int(focus_node_id))
    # 节点中心永远是裁剪框的基准种子。
    coords: list[tuple[float, float]] = [tuple(map(float, focus_node.point_rc))]
    if focus_node.polygon_vertices_rc:
        # 节点 polygon 顶点定义了局部几何主体边界。
        coords.extend(tuple(map(float, point_rc)) for point_rc in focus_node.polygon_vertices_rc)
    geometry_debug = (focus_node.debug_info or {}).get("junction_geometry", {})
    # debug polygon 可能比最终 polygon 更完整，裁剪时也要纳入。
    coords.extend(tuple(map(float, point_rc)) for point_rc in geometry_debug.get("polygon_vertices_rc", []))
    for truncation_item in geometry_debug.get("truncation", []):
        # cut 点和截断路径会把局部范围进一步拉开，不能漏掉。
        coords.append(tuple(map(float, truncation_item["cut_point_rc"])))
        coords.extend(tuple(map(float, point_rc)) for point_rc in truncation_item.get("path_rc", []))
    for sector_item in geometry_debug.get("support_sectors", []):
        # 代表点体现最终方向选择。
        rep = sector_item.get("representative_point_rc")
        if rep is not None:
            coords.append(tuple(map(float, rep)))
        # 命中点则体现扫描观察到的有效支持范围。
        coords.extend(tuple(map(float, point_rc)) for point_rc in sector_item.get("hit_points_rc", []))

    # 与 focus 节点直接相连的 edge path 也会影响 detail 图解释范围。
    for edge in result.edge_info_list:
        if int(edge.src_node_id) == int(focus_node_id) or int(edge.dst_node_id) == int(focus_node_id):
            coords.extend(tuple(map(float, point_rc)) for point_rc in edge.path_rc)

    # 所有点统一乘渲染倍率后再计算裁剪框。
    # margin_px 提供稳定留白，避免边缘标注被截断。
    rows = [int(round(point_rc[0] * render_scale)) for point_rc in coords]
    cols = [int(round(point_rc[1] * render_scale)) for point_rc in coords]
    r0 = max(0, min(rows) - margin_px)
    c0 = max(0, min(cols) - margin_px)
    # 上下界最终都再夹回图像范围，保证切片安全。
    r1 = min(image.shape[0], max(rows) + margin_px + 1)
    c1 = min(image.shape[1], max(cols) + margin_px + 1)
    return image[r0:r1, c0:c1].copy()



__all__ = [
    "crop_focus_region",
    "draw_complete_junction_overlay",
    "draw_native_geometry_overlay",
]
