"""CoveragePlanning 的 SweepGraph 调试渲染。"""

from __future__ import annotations

import math

import numpy as np

from ...contracts import CoveragePlanningResult, GeometryPreparationResult
from ...coverage_planning.coverage_lane_sweep.lane_path_sampling import sample_path_by_spacing
from ...coverage_planning.sweep_graph.sweep_graph_build import resolve_sweep_transition_candidates
from .coverage_render_canvas import (
    draw_path_dashed_polyline as draw_path_dashed_polyline,
    draw_path_points as draw_path_points,
    draw_path_polyline as draw_path_polyline,
    render_gray as render_gray,
    scaled_xy as scaled_xy,
    to_path_tuple as to_path_tuple,
)
from .coverage_render_legends import draw_transition_candidate_legend as draw_transition_candidate_legend
from .coverage_render_markers import draw_text as draw_text, pick_label_point_from_region as pick_label_point_from_region, pick_sweep_endpoint_by_end_type as pick_sweep_endpoint_by_end_type, draw_transition_with_mid_arrow as draw_transition_with_mid_arrow
from .coverage_render_palette import (
    AXIS_COLOR as _AXIS_COLOR,
    CENTER_SWEEP_COLOR as _CENTER_SWEEP_COLOR,
    FAILED_CONNECTION_X_COLOR as _FAILED_CONNECTION_X_COLOR,
    NEG_SWEEP_COLOR as _NEG_SWEEP_COLOR,
    PORT_VIEW_COLOR as _PORT_VIEW_COLOR,
    POS_SWEEP_COLOR as _POS_SWEEP_COLOR,
    REJECT_TRANSITION_COLOR as _REJECT_TRANSITION_COLOR,
    STRONG_TRANSITION_COLOR as _STRONG_TRANSITION_COLOR,
    SWEEP_TRANSITION_COLOR as _SWEEP_TRANSITION_COLOR,
    WEAK_TRANSITION_COLOR as _WEAK_TRANSITION_COLOR,
    FALLBACK_TRANSITION_COLOR as _FALLBACK_TRANSITION_COLOR,
)
from .coverage_render_state import (
    edge_by_coverage_lane_id as edge_by_coverage_lane_id,
    edge_coverage_info_by_edge_id as edge_coverage_info_by_edge_id,
    sweep_graph_info as sweep_graph_info,
    sweep_items as sweep_items,
    sweep_port_view_info as sweep_port_view_info,
    sweep_transition_candidate_info as sweep_transition_candidate_info,
)


def _draw_dashed_circle(
    canvas: np.ndarray,
    point_rc: tuple[float, float],
    radius_px: float,
    color: tuple[int, int, int],
    render_scale: int,
) -> None:
    """围绕指定点画一圈虚线圆。"""

    center_x, center_y = scaled_xy(point_rc, render_scale)
    radius = max(2, int(round(float(radius_px) * float(render_scale))))
    circumference = 2.0 * math.pi * float(radius)
    dash_len = max(6, int(round(0.05 * circumference)))
    gap_len = max(4, int(round(0.04 * circumference)))
    angle = 0.0
    while angle < 360.0:
        start_rad = math.radians(angle)
        end_rad = math.radians(min(360.0, angle + (360.0 * dash_len / max(1.0, circumference))))
        start_xy = (
            int(round(center_x + float(radius) * math.cos(start_rad))),
            int(round(center_y + float(radius) * math.sin(start_rad))),
        )
        end_xy = (
            int(round(center_x + float(radius) * math.cos(end_rad))),
            int(round(center_y + float(radius) * math.sin(end_rad))),
        )
        import cv2

        cv2.line(canvas, start_xy, end_xy, color, 1, cv2.LINE_AA)
        angle += 360.0 * float(dash_len + gap_len) / max(1.0, circumference)


def _draw_solid_point(
    canvas: np.ndarray,
    point_rc: tuple[float, float],
    color: tuple[int, int, int],
    render_scale: int,
    radius: int,
) -> None:
    """画实心点。"""

    import cv2

    col, row = scaled_xy(point_rc, render_scale)
    cv2.circle(canvas, (col, row), int(radius), color, -1, lineType=cv2.LINE_AA)


def _draw_segment(
    canvas: np.ndarray,
    start_rc: tuple[float, float],
    end_rc: tuple[float, float],
    color: tuple[int, int, int],
    render_scale: int,
    thickness: int = 1,
) -> None:
    """画一段细线。"""

    import cv2

    start_xy = scaled_xy(start_rc, render_scale)
    end_xy = scaled_xy(end_rc, render_scale)
    cv2.line(canvas, start_xy, end_xy, color, int(max(1, thickness)), cv2.LINE_AA)


def _resolve_failed_anchor_rc(
    lane_item: dict,
    edge_by_lane_id: dict[int, object],
    layout_debug: dict,
) -> tuple[float, float] | None:
    """从失败锚点索引恢复原始 anchor 位置。"""

    failed_anchor_index = layout_debug.get("failed_anchor_index")
    if failed_anchor_index is None:
        return None
    edge = edge_by_lane_id.get(int(lane_item["coverage_lane_id"]))
    if edge is None:
        return None
    outer_path = to_path_tuple(getattr(edge, "outer_path_rc", ()))
    if len(outer_path) < 2:
        return None
    spacing_px = int((lane_item.get("debug_info") or {}).get("sampling_step_px", 0))
    if spacing_px <= 0:
        return None
    sampled_anchors = sample_path_by_spacing(outer_path, spacing_px)
    idx = int(failed_anchor_index)
    if idx < 0 or idx >= len(sampled_anchors):
        return None
    return tuple(sampled_anchors[idx])


def render_sweep_node_chain_debug(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    render_scale: int,
) -> np.ndarray:
    """渲染所有 sweeps 的内部点链 debug 图。"""

    # 这张图把所有 sweep 当作“点链”来观察，而不是 final path 结果。
    canvas = render_gray(geometry_result.gray, render_scale)
    edge_coverage_by_id = edge_coverage_info_by_edge_id(result)
    sweeps_by_id = {int(item["sweep_id"]): item for item in sweep_items(result)}
    # 先把每条 active sweep 的点链本体画出来。
    for sweep in sweep_items(result):
        if not bool(sweep.get("active", True)):
            continue
        side_label = str(sweep.get("side_label", ""))
        if side_label == "center":
            color = _CENTER_SWEEP_COLOR
        elif side_label == "positive":
            color = _POS_SWEEP_COLOR
        else:
            color = _NEG_SWEEP_COLOR
        # sweep 仍然通过 source_edge_id 回溯所属 edge 几何。
        edge = next((item for item in result.graph_info.edges if int(item.edge_id) == int(sweep["source_edge_id"])), None)
        coverage_info = edge_coverage_by_id.get(int(sweep["source_edge_id"]))
        if coverage_info is not None and edge is not None and side_label == "center":
            # 只给中心 sweep 画参考几何线，避免所有 sweep 都叠主轴后把图糊掉。
            draw_path_polyline(canvas, edge.outer_path_rc, _AXIS_COLOR, render_scale)
            label_point = pick_label_point_from_region(tuple(to_path_tuple(edge.outer_path_rc)), ())
            if label_point is not None:
                draw_text(canvas, f"CL{int(coverage_info['coverage_lane_id'])}", label_point, _AXIS_COLOR, render_scale)
        path_rc = to_path_tuple(sweep.get("path_rc", ()))
        # sweep 统一画成虚线主链 + 离散采样点。
        draw_path_dashed_polyline(canvas, path_rc, color, render_scale, dash_len_px=6, gap_len_px=4)
        draw_path_points(canvas, path_rc, color, render_scale, radius=2)
        # 点链可视化的重点是观察 sweep 自身采样质量，而不是 lane 覆盖面。
        # 因而即使没有 CL 标签，也要完整保留 sweep 点链。

    # 最后再叠加 sweep graph transition，避免箭头被点链覆盖。
    for transition in resolve_sweep_transition_candidates(sweep_graph_info(result)):
        from_sweep = sweeps_by_id.get(int(transition["from_sweep_id"]))
        to_sweep = sweeps_by_id.get(int(transition["to_sweep_id"]))
        # 任一端 sweep 缺失就不画 transition。
        if from_sweep is None or to_sweep is None:
            continue
        start_rc = pick_sweep_endpoint_by_end_type(to_path_tuple(from_sweep.get("path_rc", ())), str(transition.get("from_end_type", "")))
        end_rc = pick_sweep_endpoint_by_end_type(to_path_tuple(to_sweep.get("path_rc", ())), str(transition.get("to_end_type", "")))
        # 端点挑选失败时，说明路径或端类型信息不完整。
        if start_rc is None or end_rc is None:
            continue
        # transition 统一使用中段箭头，减少对端点 marker 的遮挡。
        draw_transition_with_mid_arrow(canvas, start_rc, end_rc, _SWEEP_TRANSITION_COLOR, render_scale)
    # 这张图不额外加 legend，因为 transition 只有单一语义颜色。
    # 读图时重点是 sweep 点链和 transition 拓扑是否一致。
    return canvas


def render_sweep_port_view_debug(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    render_scale: int,
) -> np.ndarray:
    """渲染节点口的 sweep 空间排序。"""

    # port view 图复用 sweep 底座，只额外强调节点口的排序关系。
    canvas = render_gray(geometry_result.gray, render_scale)
    draw_sweep_chain_base(canvas, result, render_scale)
    sweeps_by_id = {int(item["sweep_id"]): item for item in sweep_items(result)}
    nodes_by_id = {int(node.node_id): node for node in result.graph_info.nodes}

    # 每个 port view item 表示一个节点某一侧端口上的 sweep 排序结果。
    for item in tuple(sweep_port_view_info(result).get("items", ())):
        node = nodes_by_id.get(int(item["node_id"]))
        if node is None:
            continue
        node_rc = (float(node.point_rc[0]), float(node.point_rc[1]))
        ordered_ids = [int(sweep_id) for sweep_id in item.get("ordered_port_sweep_ids", ())]
        port_side = str(item.get("port_side", ""))
        # rank 直接按 ordered_port_sweep_ids 的顺序展开。
        for rank, sweep_id in enumerate(ordered_ids):
            sweep = sweeps_by_id.get(sweep_id)
            if sweep is None:
                continue
            endpoint = pick_sweep_endpoint_by_end_type(to_path_tuple(sweep.get("path_rc", ())), port_side)
            # endpoint 不存在时，说明该 sweep 无法在当前 port_side 上解释。
            if endpoint is None:
                continue
            # 从 node 指向 endpoint 的箭头直接表达 port 排序朝向。
            draw_transition_with_mid_arrow(canvas, node_rc, endpoint, _PORT_VIEW_COLOR, render_scale)
            # 标签里的 `Pnode:rank` 组合用于快速回查排序结果。
            draw_text(canvas, f"P{int(item['node_id'])}:{rank}", endpoint, _PORT_VIEW_COLOR, render_scale)
        # 同一节点同一侧的多个 sweep 会形成一组放射状排序箭头。
        # 这些箭头的长度不代表权重，只代表端口到 sweep 端点的空间关系。
    # port view 的核心是相对顺序，因此不再额外区分强弱或类别。
    # 一旦排序不合理，通常能从同一节点的一组标签顺序中直接看出来。
    return canvas


def render_sweep_transition_candidate_debug(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    render_scale: int,
) -> np.ndarray:
    """渲染 sweep transition 候选分级图。"""

    # 这张图在 sweep 底座之上，只强调 transition candidate 的分级颜色。
    canvas = render_gray(geometry_result.gray, render_scale)
    draw_sweep_chain_base(canvas, result, render_scale)
    sweeps_by_id = {int(item["sweep_id"]): item for item in sweep_items(result)}
    node_center_by_id = {
        int(node.node_id): (float(node.point_rc[0]), float(node.point_rc[1])) for node in result.graph_info.nodes
    }
    # 候选项逐条展开，每条颜色都只表达 selection_level。
    for item in tuple(sweep_transition_candidate_info(result).get("items", ())):
        # 颜色只表达 strong/weak/fallback/reject 的候选分级，不表达最终 cadence 采用与否。
        from_sweep = sweeps_by_id.get(int(item["from_sweep_id"]))
        to_sweep = sweeps_by_id.get(int(item["to_sweep_id"]))
        via_node_rc = node_center_by_id.get(int(item["via_node_id"]))
        # 缺任一关键实体就无法稳定绘制候选关系。
        if from_sweep is None or to_sweep is None or via_node_rc is None:
            continue
        start_rc = pick_sweep_endpoint_by_end_type(to_path_tuple(from_sweep.get("path_rc", ())), str(item.get("from_end_type", "")))
        end_rc = pick_sweep_endpoint_by_end_type(to_path_tuple(to_sweep.get("path_rc", ())), str(item.get("to_end_type", "")))
        # 端点解析失败时，直接跳过该候选，避免错误连接线。
        if start_rc is None or end_rc is None:
            continue
        level = str(item.get("selection_level", "reject"))
        # 色彩分级严格跟 selection_level 一一对应。
        if level == "strong_keep":
            color = _STRONG_TRANSITION_COLOR
        elif level == "weak_keep_fallback":
            color = _FALLBACK_TRANSITION_COLOR
        elif level == "weak_keep":
            color = _WEAK_TRANSITION_COLOR
        else:
            color = _REJECT_TRANSITION_COLOR
        # 同一 helper 绘制箭头，保证所有候选线样式一致。
        draw_transition_with_mid_arrow(canvas, start_rc, end_rc, color, render_scale)
        # via_node_rc 在这张图里只用于校验节点存在，不额外单独落点。
        # 这能避免节点中心被大量候选关系线和文字反复覆盖。
    # 图例最后补齐颜色语义说明。
    # strong/weak/fallback/reject 四档语义全靠 legend 解码，因此必须保留。
    # 因而候选图即使独立导出，也不会丢失颜色解释。
    draw_transition_candidate_legend(canvas)
    return canvas


def render_sweep_node_snap_overlay(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    render_scale: int,
) -> np.ndarray:
    """仿照历史 sweep_node_snap_overlay 渲染 anchor 到参考路径的吸附关系。"""

    canvas = render_gray(geometry_result.gray, render_scale)
    edge_by_lane_id = edge_by_coverage_lane_id(result)
    lane_items = tuple(getattr(result.coverage_lane_sweep_info, "coverage_lane_info", ())) if result.coverage_lane_sweep_info is not None else ()
    sweeps_by_lane_id: dict[int, list[dict]] = {}
    for sweep in sweep_items(result):
        sweeps_by_lane_id.setdefault(int(sweep["coverage_lane_id"]), []).append(dict(sweep))

    sweep_path_color = (255, 80, 40)
    success_point_color = _CENTER_SWEEP_COLOR
    failed_point_color = (160, 160, 160)
    snap_line_color = (0, 255, 255)
    search_radius_px = 0.0

    for lane_item in lane_items:
        debug_info = dict(lane_item.get("debug_info") or {})
        layout_debug = dict(debug_info.get("sweep_layout_debug") or {})
        if not layout_debug:
            continue
        search_radius_px = max(search_radius_px, float(layout_debug.get("normal_search_px", 0)))
        lane_sweeps = tuple(sweeps_by_lane_id.get(int(lane_item["coverage_lane_id"]), ()))
        for sweep in lane_sweeps:
            sweep_path = to_path_tuple(sweep.get("path_rc", ()))
            if len(sweep_path) >= 2:
                draw_path_dashed_polyline(
                    canvas,
                    sweep_path,
                    sweep_path_color,
                    render_scale,
                    dash_len_px=6,
                    gap_len_px=4,
                )
            anchor_points = tuple(
                (float(point[0]), float(point[1]))
                for point in sweep.get("anchor_points_rc", ())
            )
            path_points = tuple(
                (float(point[0]), float(point[1]))
                for point in sweep.get("path_rc", ())
            )
            for anchor_rc, path_point_rc in zip(anchor_points, path_points):
                _draw_segment(canvas, anchor_rc, path_point_rc, snap_line_color, render_scale, thickness=1)
                _draw_solid_point(canvas, path_point_rc, success_point_color, render_scale, radius=3)
                radius_px = float(layout_debug.get("normal_search_px", 0))
                if radius_px > 0.0:
                    _draw_dashed_circle(canvas, path_point_rc, radius_px, success_point_color, render_scale)

        failed_anchor_rc = _resolve_failed_anchor_rc(lane_item, edge_by_lane_id, layout_debug)
        if failed_anchor_rc is not None:
            _draw_solid_point(canvas, failed_anchor_rc, failed_point_color, render_scale, radius=3)
            radius_px = float(layout_debug.get("normal_search_px", 0))
            if radius_px > 0.0:
                _draw_dashed_circle(canvas, failed_anchor_rc, radius_px, failed_point_color, render_scale)
            failed_reason = str(layout_debug.get("failed_reason", "failed"))
            draw_text(canvas, failed_reason, failed_anchor_rc, _FAILED_CONNECTION_X_COLOR, render_scale)

    return canvas


def draw_sweep_chain_base(
    canvas: np.ndarray,
    result: CoveragePlanningResult,
    render_scale: int,
) -> None:
    """给调试图铺统一的 sweep 底座。"""

    # 这个 helper 负责 SweepGraph / SweepCadence 调试图的公共底座。
    edge_by_lane_id = edge_by_coverage_lane_id(result)
    # 每条 active sweep 都要画出自身路径，并在 center 情况下补 lane 主轴。
    for sweep in sweep_items(result):
        # inactive sweep 在所有 debug 底座里都保持静默。
        if not bool(sweep.get("active", True)):
            continue
        side_label = str(sweep.get("side_label", ""))
        # 颜色分派完全由 side_label 驱动，保持跨图一致。
        if side_label == "center":
            color = _CENTER_SWEEP_COLOR
        elif side_label == "positive":
            color = _POS_SWEEP_COLOR
        else:
            color = _NEG_SWEEP_COLOR

        # coverage lane id 可直接映射回所属 edge，用于拿主轴 outer_path。
        edge = edge_by_lane_id.get(int(sweep["coverage_lane_id"]))
        # 只有 center sweep 才补 outer_path 主轴，避免三组 sweep 都叠轴线过密。
        if edge is not None and side_label == "center":
            draw_path_polyline(canvas, edge.outer_path_rc, _AXIS_COLOR, render_scale)
            label_point = pick_label_point_from_region(tuple(to_path_tuple(edge.outer_path_rc)), ())
            if label_point is not None:
                draw_text(canvas, f"CL{int(sweep['coverage_lane_id'])}", label_point, _AXIS_COLOR, render_scale)
            # CL 标签只出现一次参考轴附近，不会贴到每条 side sweep 上。
        path_rc = to_path_tuple(sweep.get("path_rc", ()))
        # sweep 路径统一采用虚线 + 点列样式，和其它 debug 图保持一致。
        # 这也让上层不同 debug 图在视觉上共享同一套 sweep 表达。
        draw_path_dashed_polyline(canvas, path_rc, color, render_scale, dash_len_px=6, gap_len_px=4)
        draw_path_points(canvas, path_rc, color, render_scale, radius=2)
        # 因而上层只要调用这个 helper，就能得到完整 sweep 背景层。
    # base 层不区分 transition、candidate 或 cadence，只负责铺 sweep 自身几何。
    # 这能保证不同 debug 图之间的底图语义稳定。
    # center sweep 附带的 axis/CL 标签，是帮助读图建立 lane 对应关系。
    # 其余 positive/negative sweep 则只保留自身颜色和路径。
    # 底座 helper 自身不负责画任何 transition 或 legend。



__all__ = [
    "draw_sweep_chain_base",
    "render_sweep_node_chain_debug",
    "render_sweep_node_snap_overlay",
    "render_sweep_port_view_debug",
    "render_sweep_transition_candidate_debug",
]
