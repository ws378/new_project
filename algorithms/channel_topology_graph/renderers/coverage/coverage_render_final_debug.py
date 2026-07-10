"""CoveragePlanning 的 FinalCoveragePath 与节点连接调试渲染。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ...contracts import CoveragePlanningResult, FinalCoveragePathConnection, GeometryPreparationResult
from .coverage_render_canvas import (
    draw_path_dashed_polyline as draw_path_dashed_polyline,
    draw_path_points as draw_path_points,
    draw_path_polyline as draw_path_polyline,
    draw_polygon as draw_polygon,
    draw_support_band as draw_support_band,
    render_gray as render_gray,
    to_path_tuple as to_path_tuple,
    write_image as write_image,
)
from .coverage_render_legends import draw_final_coverage_path_legend as draw_final_coverage_path_legend, draw_junction_summary_legend as draw_junction_summary_legend
from .coverage_render_markers import draw_failure_cross as draw_failure_cross, draw_filled_marker as draw_filled_marker, draw_hollow_marker as draw_hollow_marker, draw_text as draw_text, failure_marker_point as failure_marker_point
from .coverage_render_palette import (
    FAILED_CONNECTION_X_COLOR as _FAILED_CONNECTION_X_COLOR,
    JUNCTION_CONNECTION_COLOR as _JUNCTION_CONNECTION_COLOR,
    POLYGON_COLOR as _POLYGON_COLOR,
    SUPPORT_BAND_COLOR as _SUPPORT_BAND_COLOR,
    SWEEP_ID_TEXT_COLOR as _SWEEP_ID_TEXT_COLOR,
    UTURN_CONNECTION_COLOR as _UTURN_CONNECTION_COLOR,
)
from .coverage_render_state import final_coverage_path_info as final_coverage_path_info, junction_connections as junction_connections


_ROUTE_DEBUG_PALETTE = (
    (40, 130, 255),
    (60, 210, 80),
    (255, 120, 40),
    (220, 80, 220),
    (80, 220, 220),
    (180, 150, 255),
    (120, 180, 40),
    (255, 80, 120),
)
_REPEAT_CONNECTION_OUTLINE_COLOR = (0, 0, 0)


def connector_label(item: FinalCoveragePathConnection) -> str:
    connector_kind = str(item.get("connector_kind", "forward"))
    return "F" if connector_kind == "forward" else "B"


def route_debug_color(route_id: int) -> tuple[int, int, int]:
    """按 route_id 选择稳定调试色。"""

    # route_id 从 1 开始，因此这里减 1 后轮转 palette，保证同一 route 在整张图里颜色一致。
    return _ROUTE_DEBUG_PALETTE[(max(1, int(route_id)) - 1) % len(_ROUTE_DEBUG_PALETTE)]


def connection_midpoint(path_rc: tuple[tuple[float, float], ...]) -> tuple[float, float] | None:
    """选取连接路径的中部标签点。"""

    if not path_rc:
        return None
    return path_rc[int(len(path_rc) * 0.5)]


def draw_path_mid_arrow(
    canvas: np.ndarray,
    path_rc: tuple[tuple[float, float], ...],
    color: tuple[int, int, int],
    render_scale: int,
    *,
    thickness: int,
) -> None:
    """沿折线中段绘制方向箭头。"""

    if len(path_rc) < 2:
        return
    # 选中间段而不是首尾段，避免箭头压住 sweep 端点和文字标签。
    seg_index = max(1, min(len(path_rc) - 1, int(len(path_rc) * 0.5)))
    start_rc = path_rc[seg_index - 1]
    end_rc = path_rc[seg_index]
    start_xy = (
        int(round(float(start_rc[1]) * max(1, int(render_scale)))),
        int(round(float(start_rc[0]) * max(1, int(render_scale)))),
    )
    end_xy = (
        int(round(float(end_rc[1]) * max(1, int(render_scale)))),
        int(round(float(end_rc[0]) * max(1, int(render_scale)))),
    )
    cv2.arrowedLine(canvas, start_xy, end_xy, color, max(1, int(thickness)), cv2.LINE_AA, tipLength=0.18)


def repeat_transition_keys(result: CoveragePlanningResult) -> set[tuple[int, int, int]]:
    """从 cadence route segment 反查重复覆盖 transition。"""

    cadence_info = result.sweep_cadence_build_info.sweep_cadence_info if result.sweep_cadence_build_info is not None else {}
    repeat_keys: set[tuple[int, int, int]] = set()
    for route in tuple(cadence_info.get("routes", ())):
        route_id = int(route.get("route_id", -1))
        for segment in tuple(route.get("segments", ())):
            if str(segment.get("primitive_type", "")) != "transition":
                continue
            if not bool(segment.get("is_repeat_coverage_transition", False)):
                continue
            repeat_keys.add(
                (
                    route_id,
                    int(segment.get("from_sweep_id", -1)),
                    int(segment.get("to_sweep_id", -1)),
                )
            )
    return repeat_keys


def render_final_coverage_path_debug(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    render_scale: int,
) -> np.ndarray:
    canvas = render_gray(geometry_result.gray, render_scale)
    final_info = final_coverage_path_info(result)
    ordered_items = tuple(final_info.get("ordered_items", ()))
    repeat_keys = repeat_transition_keys(result)
    route_labeled_ids: set[int] = set()
    sweep_visit_count: dict[int, int] = {}
    for item in ordered_items:
        item_type = str(item.get("item_type", ""))
        route_id = int(item.get("route_id", 1))
        color = route_debug_color(route_id)
        if item_type == "sweep_segment":
            path_rc = to_path_tuple(item.get("sweep_points_rc", ()))
            if len(path_rc) < 1:
                continue
            # sweep 主段按 route 实色绘制，和 junction 虚线连接形成明确视觉区分。
            draw_path_polyline(canvas, path_rc, color, render_scale)
            draw_path_points(canvas, path_rc, color, render_scale, radius=2)
            sweep_id = int(item.get("sweep_id", -1))
            sweep_visit_count[sweep_id] = int(sweep_visit_count.get(sweep_id, 0)) + 1
            if sweep_id >= 0:
                label = f"S{sweep_id}"
                if sweep_visit_count[sweep_id] > 1:
                    # 重复出现的 sweep 显式标出 route 与访问序号，便于核对重复覆盖路径。
                    label = f"S{sweep_id} R{route_id}#{sweep_visit_count[sweep_id]}"
                draw_text(canvas, label, path_rc[int(len(path_rc) * 0.5)], _SWEEP_ID_TEXT_COLOR, render_scale)
            if route_id not in route_labeled_ids:
                # route 起点附近标 Rn，帮助人工把颜色和 route_id 对上。
                route_labeled_ids.add(route_id)
                draw_text(canvas, f"R{route_id}", path_rc[0], color, render_scale)
            continue
        elif item_type == "junction_connection":
            path_rc = to_path_tuple(item.get("junction_connection_points_rc", ()))
            if len(path_rc) < 1:
                continue
            from_sweep_id = int(item.get("from_sweep_id", -1))
            to_sweep_id = int(item.get("to_sweep_id", -1))
            is_repeat = (route_id, from_sweep_id, to_sweep_id) in repeat_keys
            if is_repeat:
                # repeat connector 先画黑色底线，再叠 route 色虚线，避免被误读成普通主连接。
                draw_path_polyline(canvas, path_rc, _REPEAT_CONNECTION_OUTLINE_COLOR, render_scale)
            # junction connection 保持虚线，但颜色跟随 route。
            draw_path_dashed_polyline(canvas, path_rc, color, render_scale, dash_len_px=6, gap_len_px=4)
            draw_path_points(canvas, path_rc, color, render_scale, radius=2)
            if is_repeat:
                draw_path_mid_arrow(canvas, path_rc, _REPEAT_CONNECTION_OUTLINE_COLOR, render_scale, thickness=3)
            draw_path_mid_arrow(canvas, path_rc, color, render_scale, thickness=2)
            label_point = connection_midpoint(path_rc)
            if label_point is not None:
                label = f"S{from_sweep_id}->S{to_sweep_id}"
                if is_repeat:
                    label = f"{label} repeat"
                draw_text(canvas, label, label_point, color, render_scale)
            continue
        else:
            continue
    for item in tuple(final_info.get("junction_connections", ())):
        if not bool(item.get("is_constructible", True)):
            draw_failure_cross(canvas, failure_marker_point(item), _FAILED_CONNECTION_X_COLOR, render_scale)
    draw_final_coverage_path_legend(canvas)
    return canvas


def render_junction_connection_summary(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    render_scale: int,
) -> np.ndarray:
    canvas = render_gray(geometry_result.gray, render_scale)
    node_items: dict[int, list[FinalCoveragePathConnection]] = {}
    for item in junction_connections(result):
        node_items.setdefault(int(item["via_node_id"]), []).append(item)
    for node in result.graph_info.nodes:
        polygon = tuple(node.polygon_vertices_rc or ())
        if polygon:
            draw_polygon(canvas, polygon, _POLYGON_COLOR, render_scale)
        point_rc = tuple(node.point_rc)
        color = _UTURN_CONNECTION_COLOR if any(str(item.get("connector_kind", "forward")) == "foldback" for item in node_items.get(int(node.node_id), ())) else _JUNCTION_CONNECTION_COLOR
        if int(node.node_id) in node_items:
            draw_filled_marker(canvas, point_rc, color, render_scale, radius=4)
            count = len(node_items[int(node.node_id)])
            min_support = min(float(item.get("coverage_support_width_m", 0.0)) for item in node_items[int(node.node_id)])
            draw_text(canvas, f"N{int(node.node_id)} C{count} S{min_support:.2f}", point_rc, color, render_scale)
    draw_junction_summary_legend(canvas)
    return canvas


def write_junction_connection_detail_visualizations(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    output_dir: Path,
    render_scale: int,
) -> tuple[Path, ...]:
    node_items: dict[int, list[FinalCoveragePathConnection]] = {}
    for item in junction_connections(result):
        node_items.setdefault(int(item["via_node_id"]), []).append(item)
    output_paths: list[Path] = []
    for node in result.graph_info.nodes:
        items = node_items.get(int(node.node_id), ())
        if not items:
            continue
        image = render_junction_connection_detail_for_node(
            geometry_result=geometry_result,
            result=result,
            node_id=int(node.node_id),
            render_scale=render_scale,
        )
        path = output_dir / f"junction_connection_debug_node_{int(node.node_id)}.png"
        write_image(path, image)
        output_paths.append(path)
    return tuple(output_paths)


def render_junction_connection_detail_for_node(*, geometry_result: GeometryPreparationResult, result: CoveragePlanningResult, node_id: int, render_scale: int) -> np.ndarray:
    canvas = render_gray(geometry_result.gray, render_scale)
    node = next((item for item in result.graph_info.nodes if int(item.node_id) == int(node_id)), None)
    if node is None:
        raise ValueError(f"node {node_id} not found")
    polygon = tuple(node.polygon_vertices_rc or ())
    if polygon:
        draw_polygon(canvas, polygon, _POLYGON_COLOR, render_scale)
    connections = [item for item in junction_connections(result) if int(item["via_node_id"]) == int(node_id)]
    for item in connections:
        path_rc = to_path_tuple(item.get("junction_connection_points_rc", ()))
        color = _UTURN_CONNECTION_COLOR if str(item.get("connector_kind", "forward")) == "foldback" else _JUNCTION_CONNECTION_COLOR
        support_width_px = float(item.get("coverage_support_width_m", 0.0)) / max(float(geometry_result.resolution_m_per_px), 1e-6)
        draw_support_band(canvas, path_rc, support_width_px, render_scale, _SUPPORT_BAND_COLOR)
        draw_path_polyline(canvas, path_rc, color, render_scale)
        if path_rc:
            draw_filled_marker(canvas, path_rc[0], color, render_scale, radius=3)
            draw_hollow_marker(canvas, path_rc[-1], color, render_scale, radius=4)
            draw_text(canvas, f"R{int(item['route_id'])}:{connector_label(item)}", path_rc[int(len(path_rc) * 0.5)], color, render_scale)
    return canvas
