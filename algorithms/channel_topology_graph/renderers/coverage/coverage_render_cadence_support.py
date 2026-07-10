"""Coverage cadence debug 共用支撑 helper。"""

from __future__ import annotations

from typing import Any

import numpy as np

from ...contracts import CoveragePlanningResult
from ...coverage_planning.sweep_cadence.cadence_types import route_transition_ids
from ...coverage_planning.sweep_graph.sweep_graph_build import resolve_sweep_transition_candidates
from .coverage_render_canvas import draw_path_dashed_polyline as draw_path_dashed_polyline, draw_path_points as draw_path_points, to_path_tuple as to_path_tuple
from .coverage_render_markers import (
    draw_filled_marker as draw_filled_marker,
    draw_hollow_marker as draw_hollow_marker,
    draw_square_marker as draw_square_marker,
    draw_text as draw_text,
    draw_text_offset as draw_text_offset,
    draw_transition_with_mid_arrow as draw_transition_with_mid_arrow,
    pick_sweep_endpoint_by_end_type as pick_sweep_endpoint_by_end_type,
)
from .coverage_render_palette import (
    CADENCE_NEXT_POINT_COLOR as _CADENCE_NEXT_POINT_COLOR,
    CADENCE_PREV_POINT_COLOR as _CADENCE_PREV_POINT_COLOR,
    CADENCE_RELATION_LIGHT_COLOR as _CADENCE_RELATION_LIGHT_COLOR,
    CADENCE_RULE_BEND_COLOR as _CADENCE_RULE_BEND_COLOR,
    CADENCE_RULE_DIRECT_COLOR as _CADENCE_RULE_DIRECT_COLOR,
    CADENCE_RULE_SMOOTH_COLOR as _CADENCE_RULE_SMOOTH_COLOR,
    CADENCE_SWEEP_PATH_COLOR as _CADENCE_SWEEP_PATH_COLOR,
    SWEEP_ID_TEXT_COLOR as _SWEEP_ID_TEXT_COLOR,
)
from .coverage_render_state import junction_connections as junction_connections, sweep_cadence_info as sweep_cadence_info, sweep_graph_info as sweep_graph_info, sweep_items as sweep_items


def connection_truths(result: CoveragePlanningResult) -> tuple[dict[str, Any], ...]:
    """统一提取 final coverage path 阶段使用的连接真值条目。"""

    # 渲染层只读取 FinalCoveragePath 的正式结果真值。
    # 这里不再反向调用 FinalCoveragePath builder/helper，也不再借助算法内部 query 来补图。
    sweeps_by_id = {int(item["sweep_id"]): item for item in sweep_items(result)}
    collected: list[dict[str, Any]] = []
    for item in junction_connections(result):
        from_sweep = sweeps_by_id.get(int(item["from_sweep_id"]))
        to_sweep = sweeps_by_id.get(int(item["to_sweep_id"]))
        # 渲染层不创造第二套端点真值。
        # 若结果对象里某端 sweep 已断裂，这里直接跳过，避免再造语义。
        if from_sweep is None or to_sweep is None:
            continue
        collected.append(
            {
                "route_id": int(item["route_id"]),
                "connection_id": int(item["connection_id"]),
                "from_sweep_id": int(item["from_sweep_id"]),
                "to_sweep_id": int(item["to_sweep_id"]),
                "from_path_rc": tuple(tuple(map(float, point)) for point in to_path_tuple(from_sweep.get("path_rc", ()))),
                "to_path_rc": tuple(tuple(map(float, point)) for point in to_path_tuple(to_sweep.get("path_rc", ()))),
                "point_a_rc": tuple(map(float, item["point_a_rc"])),
                "point_b_rc": tuple(map(float, item["point_b_rc"])),
                "point_c_rc": tuple(map(float, item["point_c_rc"])),
                "point_d_rc": tuple(map(float, item["point_d_rc"])),
                "theta_deg": float(item["theta_deg"]),
                "connection_class": str(item["connection_class"]),
                "is_constructible": bool(item.get("is_constructible", True)),
                "failure_reason": str(item.get("failure_reason", "")),
                "rule_geometry_rc": tuple(tuple(map(float, point)) for point in to_path_tuple(item.get("rule_geometry_rc", ()))),
            }
        )
    # 返回 tuple，保证上层多次遍历时不会引入隐式生成器消耗。
    return tuple(collected)


def draw_connection_truth_markers(
    canvas: np.ndarray,
    item: dict[str, Any],
    render_scale: int,
    *,
    marker_radius: int,
    text_offset_y: int,
) -> None:
    """为一条连接真值画出 P/Q 四个端点及其标签。"""

    # A/B 对应前一条 sweep 的尾侧语义点。
    # 空心 + 实心的组合用于区分进入局部规则构造前后的关键位置。
    draw_hollow_marker(canvas, item["point_a_rc"], _CADENCE_PREV_POINT_COLOR, render_scale, radius=marker_radius)
    draw_filled_marker(canvas, item["point_b_rc"], _CADENCE_PREV_POINT_COLOR, render_scale, radius=marker_radius)
    # C/D 对应后一条 sweep 的首侧语义点。
    # 这里故意换成方形，以便与 P 组形成稳定视觉对照。
    draw_square_marker(canvas, item["point_c_rc"], _CADENCE_NEXT_POINT_COLOR, render_scale, half_size=marker_radius, filled=True)
    draw_square_marker(canvas, item["point_d_rc"], _CADENCE_NEXT_POINT_COLOR, render_scale, half_size=marker_radius, filled=False)
    # 文本只标出 P 和 Q 两个主参考点。
    # A/C 是辅助端点，读图时依靠符号配对即可理解。
    draw_text_offset(canvas, "P", item["point_b_rc"], _CADENCE_PREV_POINT_COLOR, render_scale, -10, text_offset_y)
    draw_text_offset(canvas, "Q", item["point_c_rc"], _CADENCE_NEXT_POINT_COLOR, render_scale, 8, text_offset_y)


def pick_connection_rule_color(rule_kind: str) -> tuple[int, int, int]:
    """按规则类型选择调试颜色。"""

    # direct 是默认规则。
    # 其余规则只在命中时覆盖颜色，不引入额外分支复杂度。
    if rule_kind == "single_bend":
        return _CADENCE_RULE_BEND_COLOR
    if rule_kind == "smooth_curve":
        return _CADENCE_RULE_SMOOTH_COLOR
    return _CADENCE_RULE_DIRECT_COLOR


def focus_bounds_from_points(
    focus_points: tuple[tuple[float, float], ...],
    image_shape: tuple[int, ...],
    *,
    pad_rc: float = 32.0,
) -> tuple[float, float, float, float]:
    """根据 focus 点组推导局部裁剪范围。"""

    # focus 图只需要覆盖 P/Q 四点附近局部，因此按 rc 包围盒扩展留白即可。
    r_values = [float(point[0]) for point in focus_points]
    c_values = [float(point[1]) for point in focus_points]
    # 包围盒完全在 rc 空间里计算，避免这里过早引入 render_scale。
    # 这样调用方后续无论用什么放大倍率，都能复用同一组 rc 边界。
    # 上下界同时夹回原图尺寸，避免后续切片越界。
    r0 = max(0.0, min(r_values) - pad_rc)
    c0 = max(0.0, min(c_values) - pad_rc)
    # image_shape 读取的是原图尺寸，因此右下界也保持 rc 像素口径。
    r1 = min(float(image_shape[0] - 1), max(r_values) + pad_rc)
    c1 = min(float(image_shape[1] - 1), max(c_values) + pad_rc)
    return (r0, c0, r1, c1)


def draw_focus_sweep_paths(canvas: np.ndarray, target: dict[str, Any], render_scale: int) -> tuple[tuple[tuple[float, float], ...], tuple[tuple[float, float], ...]]:
    """在 focus 视图上画出参与该规则的两条 sweep。"""

    # focus 图里只保留 from / to 两条 sweep，避免其他路径干扰规则判断。
    from_path = tuple(tuple(map(float, point)) for point in tuple(target.get("from_path_rc", ())))
    to_path = tuple(tuple(map(float, point)) for point in tuple(target.get("to_path_rc", ())))
    if len(from_path) < 2 or len(to_path) < 2:
        return ((), ())
    # 两条 sweep 都画成虚线 + 离散采样点，延续 cadence debug 的统一视觉语言。
    draw_path_dashed_polyline(canvas, from_path, _CADENCE_SWEEP_PATH_COLOR, render_scale, dash_len_px=6, gap_len_px=4)
    draw_path_points(canvas, from_path, _CADENCE_SWEEP_PATH_COLOR, render_scale, radius=2)
    draw_path_dashed_polyline(canvas, to_path, _CADENCE_SWEEP_PATH_COLOR, render_scale, dash_len_px=6, gap_len_px=4)
    draw_path_points(canvas, to_path, _CADENCE_SWEEP_PATH_COLOR, render_scale, radius=2)
    # from / to 标签使用 target 自带的 sweep id，保证与被聚焦条目严格一致。
    # sweep 编号落在各自路径中部，便于人工核对关系输入。
    draw_text(canvas, f"{int(target['from_sweep_id'])}", from_path[int(len(from_path) * 0.5)], _SWEEP_ID_TEXT_COLOR, render_scale)
    draw_text(canvas, f"{int(target['to_sweep_id'])}", to_path[int(len(to_path) * 0.5)], _SWEEP_ID_TEXT_COLOR, render_scale)
    return (from_path, to_path)


def draw_light_cadence_relations(
    canvas: np.ndarray,
    result: CoveragePlanningResult,
    render_scale: int,
) -> None:
    """以弱化样式叠加 cadence 中已选中的关系线。"""

    # 这里只画已经被 cadence route 采用的关系线。
    # 颜色刻意弱化，是为了让后续规则几何保持主视觉层级。
    # 因而这个 helper 的输出本质上是“背景参考层”，不是主结果层。
    sweeps_by_id = {int(item["sweep_id"]): item for item in sweep_items(result)}
    cadence_transition_ids = {int(transition_id) for route in tuple(sweep_cadence_info(result).get("routes", ())) for transition_id in route_transition_ids(route)}
    # 所有 transition 都先遍历一遍，再只挑 cadence 已采用的子集。
    for transition in resolve_sweep_transition_candidates(sweep_graph_info(result)):
        if int(transition.get("candidate_id", transition.get("transition_id", -1))) not in cadence_transition_ids:
            continue
        # 从 id 反查 sweep 实体，是为了继续读取其实际路径几何。
        from_sweep = sweeps_by_id.get(int(transition["from_sweep_id"]))
        to_sweep = sweeps_by_id.get(int(transition["to_sweep_id"]))
        # 任一端 sweep 丢失，就无法确定真实关系线端点。
        if from_sweep is None or to_sweep is None:
            continue
        # 起止点都必须按 route 记录的端类型挑选，否则线段方向会错。
        start_rc = pick_sweep_endpoint_by_end_type(to_path_tuple(from_sweep.get("path_rc", ())), str(transition.get("from_end_type", "")))
        end_rc = pick_sweep_endpoint_by_end_type(to_path_tuple(to_sweep.get("path_rc", ())), str(transition.get("to_end_type", "")))
        # 某端退化时直接跳过，避免画出误导性的背景箭头。
        if start_rc is None or end_rc is None:
            continue
        # 这里不再区分强弱，只统一回到“背景 cadence 参考关系”的视觉层。
        # 背景箭头固定用细线和较小箭头，不抢规则线的视觉优先级。
        # 具体采用哪一种规则，会由上层 debug 图再额外叠加表达。
        draw_transition_with_mid_arrow(
            canvas,
            start_rc,
            end_rc,
            _CADENCE_RELATION_LIGHT_COLOR,
            render_scale,
            thickness=1,
            arrow_scale=1.0,
        )



__all__ = [
    "connection_truths",
    "draw_connection_truth_markers",
    "draw_focus_sweep_paths",
    "draw_light_cadence_relations",
    "focus_bounds_from_points",
    "pick_connection_rule_color",
]
