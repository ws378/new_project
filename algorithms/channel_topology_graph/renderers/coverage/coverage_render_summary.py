"""CoveragePlanning 的 coverage lane 与 sweep 总览渲染。"""

from __future__ import annotations

import cv2
import numpy as np

from ...contracts import CoveragePlanningResult, GeometryPreparationResult
from .coverage_render_canvas import (
    draw_path_points as draw_path_points,
    draw_polygon as draw_polygon,
    draw_region_points as draw_region_points,
    fill_region_points as fill_region_points,
    render_gray as render_gray,
    to_path_tuple as to_path_tuple,
)
from .coverage_render_markers import draw_text as draw_text, pick_label_point_from_region as pick_label_point_from_region
from .coverage_render_palette import (
    AXIS_COLOR as _AXIS_COLOR,
    CENTER_SWEEP_COLOR as _CENTER_SWEEP_COLOR,
    LANE_REGION_COLOR as _LANE_REGION_COLOR,
    NEG_SWEEP_COLOR as _NEG_SWEEP_COLOR,
    POLYGON_COLOR as _POLYGON_COLOR,
    POS_SWEEP_COLOR as _POS_SWEEP_COLOR,
    TERRITORY_PALETTE as _TERRITORY_PALETTE,
)
from .coverage_render_state import edge_coverage_info_by_edge_id as edge_coverage_info_by_edge_id, find_edge as find_edge, sweep_items as sweep_items


def render_coverage_lanes_summary(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    render_scale: int,
) -> np.ndarray:
    """渲染 coverage lane 总览。

    这张图只看 coverage lane 本体：
    - endpoint polygon 约束
    - outer_path 主轴
    - 有效区域
    """

    # 底图统一来自 geometry_result.gray，保证各 summary 视图对齐。
    canvas = render_gray(geometry_result.gray, render_scale)
    edge_coverage_by_id = edge_coverage_info_by_edge_id(result)
    # 节点 polygon 先整体落图，提供 coverage lane 的终端约束边界。
    for node in result.graph_info.nodes:
        draw_polygon(canvas, tuple(node.polygon_vertices_rc or ()), _POLYGON_COLOR, render_scale)

    # 再逐 edge 叠加激活 coverage lane 的主轴与有效区域。
    for edge in result.graph_info.edges:
        coverage_info = edge_coverage_by_id.get(int(edge.edge_id))
        # 未激活的 coverage lane 不参与当前轮 summary。
        if coverage_info is None or not bool(coverage_info.get("active", True)):
            continue
        # outer_path 作为 coverage lane 参考主轴，用更细的点列方式表达。
        draw_path_points(canvas, edge.outer_path_rc, _AXIS_COLOR, render_scale, radius=1)
        effective_region_pixels = tuple(tuple(point) for point in coverage_info.get("effective_region_pixels", ()))
        # effective region 直接按离散像素点铺开，更忠实反映真实区域结果。
        draw_region_points(canvas, effective_region_pixels, _LANE_REGION_COLOR, render_scale)
        label_point = pick_label_point_from_region(effective_region_pixels, edge.outer_path_rc)
        # 标签优先落在 region 内部，否则就退回 outer_path 附近。
        if label_point is not None:
            draw_text(
                canvas,
                f"CL{int(coverage_info['coverage_lane_id'])}",
                label_point,
                _LANE_REGION_COLOR,
                render_scale,
            )
    # 这张总览图故意不再叠额外 legend，减少对主区域的遮挡。
    # 读图时应主要关注 axis 和 effective region 的空间重合关系。
    return canvas


def render_coverage_lane_territory_summary(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    render_scale: int,
) -> np.ndarray:
    """单独渲染 `outer_path_rc` 的 territory 势力范围。"""

    # territory 视图需要一张可单独做半透明混合的 overlay。
    canvas = render_gray(geometry_result.gray, render_scale)
    overlay = canvas.copy()
    # 只收集 active 的 coverage lane，避免未启用 edge 污染势力范围视图。
    active_edge_coverages = [
        (edge, edge.coverage_info)
        for edge in result.graph_info.edges
        if edge.coverage_info is not None and bool(edge.coverage_info.get("active", True))
    ]
    # 先把每条 lane 的 territory 填到 overlay 上。
    for idx, (_, coverage_info) in enumerate(active_edge_coverages):
        territory_pixels = tuple(tuple(point) for point in coverage_info.get("territory_pixels", ()))
        if not territory_pixels:
            continue
        color = _TERRITORY_PALETTE[idx % len(_TERRITORY_PALETTE)]
        # palette 循环复用，保证 lane 数量多时仍有稳定颜色分配。
        fill_region_points(overlay, territory_pixels, color, render_scale)

    # 半透明色块表达“势力范围”，底图仍必须看得见，所以用整体 alpha 叠加。
    canvas = cv2.addWeighted(overlay, 0.35, canvas, 0.65, 0.0)
    # alpha 固定在这里，避免不同 territory 图出现观感漂移。

    # polygon 边界后画，避免被 territory 色块吞掉。
    for node in result.graph_info.nodes:
        draw_polygon(canvas, tuple(node.polygon_vertices_rc or ()), _POLYGON_COLOR, render_scale)

    # 再补每条 lane 的主轴和 territory 标签，帮助识别颜色归属。
    for idx, (edge, coverage_info) in enumerate(active_edge_coverages):
        color = _TERRITORY_PALETTE[idx % len(_TERRITORY_PALETTE)]
        draw_path_points(canvas, edge.outer_path_rc, color, render_scale, radius=1)
        territory_pixels = tuple(tuple(point) for point in coverage_info.get("territory_pixels", ()))
        label_point = pick_label_point_from_region(territory_pixels, edge.outer_path_rc)
        # 标签直接绑定 coverage_lane_id，便于和日志及下游表格对照。
        if label_point is not None:
            draw_text(canvas, f"T{int(coverage_info['coverage_lane_id'])}", label_point, color, render_scale)
    # 最终输出既保留 territory 面积感，也保留 lane 主轴定位信息。
    return canvas


def render_coverage_lane_effective_region_summary(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    render_scale: int,
) -> np.ndarray:
    """单独渲染 coverage lane 的 effective region。"""

    # effective region 图强调“可覆盖区域”，不再展示 territory 色块。
    canvas = render_gray(geometry_result.gray, render_scale)
    edge_coverage_by_id = edge_coverage_info_by_edge_id(result)
    for node in result.graph_info.nodes:
        # polygon 是 effective region 的硬约束边界，弱化但必须保留。
        draw_polygon(canvas, tuple(node.polygon_vertices_rc or ()), _POLYGON_COLOR, render_scale)

    # 每条 active lane 都画出 effective region + 主轴 + 标签。
    for edge in result.graph_info.edges:
        coverage_info = edge_coverage_by_id.get(int(edge.edge_id))
        if coverage_info is None or not bool(coverage_info.get("active", True)):
            continue
        effective_region_pixels = tuple(tuple(point) for point in coverage_info.get("effective_region_pixels", ()))
        # effective region 用统一颜色，强调它们共享同一类语义。
        draw_region_points(canvas, effective_region_pixels, _LANE_REGION_COLOR, render_scale)
        # 主轴保留，是为了让人能直接判断 effective region 是否围绕该 edge 主体段建立。
        draw_path_points(canvas, edge.outer_path_rc, _AXIS_COLOR, render_scale, radius=1)
        label_point = pick_label_point_from_region(effective_region_pixels, edge.outer_path_rc)
        # 标签落在 region 内部，帮助快速对应 lane id。
        if label_point is not None:
            draw_text(
                canvas,
                f"ER{int(coverage_info['coverage_lane_id'])}",
                label_point,
                _LANE_REGION_COLOR,
                render_scale,
            )
    # 最终视图保留最少视觉元素，只服务于 effective region 验证。
    # 因而不会再叠 territory 或 sweep 结果，避免语义串扰。
    # 读图时应主要检查有效区域是否沿主轴两侧均匀展开。
    return canvas


def render_coverage_sweeps_summary(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    render_scale: int,
) -> np.ndarray:
    """渲染 sweeps 铺设结果。"""

    # sweep 总览要同时展示 node polygon 和所有 active sweeps。
    canvas = render_gray(geometry_result.gray, render_scale)
    for node in result.graph_info.nodes:
        draw_polygon(canvas, tuple(node.polygon_vertices_rc or ()), _POLYGON_COLOR, render_scale)

    edge_coverage_by_id = edge_coverage_info_by_edge_id(result)
    # sweep 按 side_label 着色，反映 center / positive / negative 三种角色。
    for sweep in sweep_items(result):
        if not bool(sweep.get("active", True)):
            continue
        side_label = str(sweep["side_label"])
        if side_label == "center":
            color = _CENTER_SWEEP_COLOR
        elif side_label == "positive":
            color = _POS_SWEEP_COLOR
        else:
            color = _NEG_SWEEP_COLOR
        # sweep 本体直接画离散点列，便于观察铺设密度和方向。
        draw_path_points(canvas, to_path_tuple(sweep["path_rc"]), color, render_scale, radius=2)
        edge = find_edge(result, int(sweep["source_edge_id"]))
        # coverage lane 信息优先从 edge 实体拿，缺失时再退回索引表。
        coverage_info = edge.coverage_info if edge is not None else edge_coverage_by_id.get(int(sweep["source_edge_id"]))
        label_point = pick_label_point_from_region(tuple(tuple(point) for point in sweep["path_rc"]), ())
        # 只有拿到 lane 信息和标签位置时，才补 sweep/lane 联合标签。
        if coverage_info is not None and label_point is not None:
            draw_text(
                canvas,
                f"S{int(sweep['sweep_id'])}/CL{int(coverage_info['coverage_lane_id'])}",
                label_point,
                color,
                render_scale,
            )
        # 标签缺失时仍然保留 sweep 本体，避免因为局部几何异常而整条 sweep 消失。
    # center / positive / negative 三色共同构成一张完整 sweep 铺设图。
    # 因此颜色是这张图的主要阅读入口。
    # 结合 polygon 边界，可以快速判断 sweep 是否越界。
    # 同一 sweep 的标签同时给出其所属 coverage lane，便于追踪来源。
    # 这张图的核心是 sweep 本体，因此不额外放 legend 挤占空间。
    return canvas
