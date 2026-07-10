"""CoveragePlanning 的 SweepCadence 规则调试渲染。"""

from __future__ import annotations

import cv2
import numpy as np

from ...contracts import CoveragePlanningResult, GeometryPreparationResult
from ...coverage_planning.sweep_cadence.cadence_types import route_transition_ids
from ...coverage_planning.sweep_graph.sweep_graph_build import resolve_sweep_transition_candidates
from .coverage_render_canvas import (
    draw_path_points as draw_path_points,
    draw_path_polyline as draw_path_polyline,
    render_gray as render_gray,
    to_path_tuple as to_path_tuple,
)
from .coverage_render_cadence_support import (
    connection_truths as connection_truths,
    draw_connection_truth_markers as draw_connection_truth_markers,
    draw_focus_sweep_paths as draw_focus_sweep_paths,
    draw_light_cadence_relations as draw_light_cadence_relations,
    focus_bounds_from_points as focus_bounds_from_points,
    pick_connection_rule_color as pick_connection_rule_color,
)
from .coverage_render_legends import (
    draw_sweep_cadence_classification_inputs_legend as draw_sweep_cadence_classification_inputs_legend,
    draw_sweep_cadence_connection_rules_legend as draw_sweep_cadence_connection_rules_legend,
    draw_sweep_cadence_legend as draw_sweep_cadence_legend,
)
from .coverage_render_markers import (
    draw_failure_cross as draw_failure_cross,
    draw_filled_marker as draw_filled_marker,
    draw_hollow_marker as draw_hollow_marker,
    draw_text as draw_text,
    draw_transition_with_mid_arrow as draw_transition_with_mid_arrow,
    failure_marker_point as failure_marker_point,
    pick_sweep_endpoint_by_end_type as pick_sweep_endpoint_by_end_type,
)
from .coverage_render_palette import (
    CADENCE_BG_TRANSITION_COLOR as _CADENCE_BG_TRANSITION_COLOR,
    CADENCE_FG_TRANSITION_COLOR as _CADENCE_FG_TRANSITION_COLOR,
    FAILED_CONNECTION_X_COLOR as _FAILED_CONNECTION_X_COLOR,
)
from .coverage_render_state import sweep_cadence_info as sweep_cadence_info, sweep_graph_info as sweep_graph_info, sweep_items as sweep_items
from .coverage_render_sweep_debug import draw_sweep_chain_base as draw_sweep_chain_base


def render_sweep_cadence_debug(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    render_scale: int,
) -> np.ndarray:
    """渲染 SweepCadence 调试图。"""

    # 先铺灰底，再叠加统一 sweep 底座。
    # 所有 cadence 视图都从这一步开始，保证不同 debug 图对齐。
    canvas = render_gray(geometry_result.gray, render_scale)
    draw_sweep_chain_base(canvas, result, render_scale)
    # sweep 索引表用于把 transition 里的 id 映射回几何路径。
    sweeps_by_id = {int(item["sweep_id"]): item for item in sweep_items(result)}
    # 只有被 cadence route 实际采用的 transition 才算前景关系线。
    cadence_transition_ids = {int(transition_id) for route in tuple(sweep_cadence_info(result).get("routes", ())) for transition_id in route_transition_ids(route)}

    # 先画全体候选关系线，再用颜色和粗细区分 cadence 前景/背景。
    for transition in resolve_sweep_transition_candidates(sweep_graph_info(result)):
        from_sweep = sweeps_by_id.get(int(transition["from_sweep_id"]))
        to_sweep = sweeps_by_id.get(int(transition["to_sweep_id"]))
        # transition 一旦缺失端点 sweep，就无法可靠落图。
        if from_sweep is None or to_sweep is None:
            continue
        # 起点和终点都必须按 transition 记录的端类型选取。
        start_rc = pick_sweep_endpoint_by_end_type(to_path_tuple(from_sweep.get("path_rc", ())), str(transition.get("from_end_type", "")))
        end_rc = pick_sweep_endpoint_by_end_type(to_path_tuple(to_sweep.get("path_rc", ())), str(transition.get("to_end_type", "")))
        # 某一端路径退化时，这条关系线宁可不画，也不能猜测端点。
        if start_rc is None or end_rc is None:
            continue
        is_cadence = int(transition.get("candidate_id", transition.get("transition_id", -1))) in cadence_transition_ids
        # 被采用的 cadence 关系线更亮、更粗，箭头也更明显。
        color = _CADENCE_FG_TRANSITION_COLOR if is_cadence else _CADENCE_BG_TRANSITION_COLOR
        thickness = 2 if is_cadence else 1
        arrow_scale = 1.8 if is_cadence else 1.0
        # 箭头画在中段，避免吞掉两端的 sweep 端点标记。
        draw_transition_with_mid_arrow(canvas, start_rc, end_rc, color, render_scale, thickness=thickness, arrow_scale=arrow_scale)

    # route 级别再补首尾锚点，帮助人工检查每条 cadence 的覆盖方向。
    for route in tuple(sweep_cadence_info(result).get("routes", ())):
        # route 首尾锚点单独标出来，用于人工检查每条 cadence 的朝向和覆盖边界。
        start_sweep = sweeps_by_id.get(int(route["start_sweep_id"]))
        end_sweep = sweeps_by_id.get(int(route["end_sweep_id"]))
        if start_sweep is not None:
            # 起点用实心点，强调“从这里出发”。
            start_rc = pick_sweep_endpoint_by_end_type(to_path_tuple(start_sweep.get("path_rc", ())), str(route.get("start_end_type", "src")))
            if start_rc is not None:
                draw_filled_marker(canvas, start_rc, _CADENCE_FG_TRANSITION_COLOR, render_scale, radius=4)
                draw_text(canvas, f"Cad{int(route['route_id'])}", start_rc, _CADENCE_FG_TRANSITION_COLOR, render_scale)
        if end_sweep is not None:
            # 终点用空心点，与起点视觉区分。
            end_rc = pick_sweep_endpoint_by_end_type(to_path_tuple(end_sweep.get("path_rc", ())), str(route.get("end_end_type", "dst")))
            if end_rc is not None:
                draw_hollow_marker(canvas, end_rc, _CADENCE_FG_TRANSITION_COLOR, render_scale, radius=5)
    # 最后统一补图例，避免中间绘制逻辑反复关心 legend 布局。
    draw_sweep_cadence_legend(canvas)
    return canvas


def render_sweep_cadence_classification_inputs_debug(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    render_scale: int,
) -> np.ndarray:
    """渲染节拍分类输入调试图。"""

    # 这张图复用基础 cadence 图，只额外叠加 P/Q 输入端点。
    canvas = render_sweep_cadence_debug(geometry_result, result, render_scale)
    # 每条连接真值都落出同一套 A/B/C/D 端点，用于复核分类输入。
    for item in connection_truths(result):
        # marker 语义由 support helper 统一定义，保证所有 cadence 视图一致。
        draw_connection_truth_markers(canvas, item, render_scale, marker_radius=4, text_offset_y=12)
    # 图例只解释端点角色，不重复解释底层 cadence 关系线。
    draw_sweep_cadence_classification_inputs_legend(canvas)
    return canvas


def render_sweep_cadence_connection_rules_debug(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    render_scale: int,
) -> np.ndarray:
    """渲染按三类规则推导出的连接几何调试图。"""

    # 先画 sweep 底座，再用弱化关系线交代 cadence 已采纳的连接背景。
    canvas = render_gray(geometry_result.gray, render_scale)
    draw_sweep_chain_base(canvas, result, render_scale)
    draw_light_cadence_relations(canvas, result, render_scale)
    # 再叠加每条真值连接的 P/Q 端点和规则几何。
    for item in connection_truths(result):
        draw_connection_truth_markers(canvas, item, render_scale, marker_radius=4, text_offset_y=12)
        # 不可构造的连接只打失败叉，不再尝试画规则几何。
        if not bool(item.get("is_constructible", True)):
            draw_failure_cross(canvas, failure_marker_point(item), _FAILED_CONNECTION_X_COLOR, render_scale)
            continue
        # 规则几何路径由 FinalCoveragePath 真值预先给出，这里只负责按类别上色并落图。
        rule_kind = str(item.get("connection_class", ""))
        rule_path = to_path_tuple(item.get("rule_geometry_rc", ()))
        # 少于两个点时无法形成可见规则线。
        if len(rule_path) < 2:
            continue
        # 规则路径颜色只表达规则类别，不表达是否最终被采用。
        color = pick_connection_rule_color(rule_kind)
        draw_path_polyline(canvas, tuple(rule_path), color, render_scale)
        # 再补离散采样点，便于识别路径是否过稀或折点异常。
        draw_path_points(canvas, tuple(rule_path), color, render_scale, radius=1)
    # 规则图自己的 legend 放在最后，保证不会被路径覆盖。
    draw_sweep_cadence_connection_rules_legend(canvas)
    return canvas


def render_sweep_cadence_connection_rule_focus_debug(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    render_scale: int,
    *,
    from_sweep_id: int,
    to_sweep_id: int,
) -> np.ndarray:
    """只渲染一条指定节拍关系的局部规则图。"""

    # 先在所有 truth 中找到目标 sweep 对应的那一条连接。
    target = None
    for item in connection_truths(result):
        # focus 图是按 sweep 对精确定位的，不按 route_id 或 node_id 模糊匹配。
        if int(item["from_sweep_id"]) == int(from_sweep_id) and int(item["to_sweep_id"]) == int(to_sweep_id):
            target = item
            break
    # 如果目标关系不存在，就直接返回灰底，显式表达“无此关系”。
    if target is None:
        return render_gray(geometry_result.gray, render_scale)

    # 局部裁剪范围只围绕 P/Q 四点展开。
    focus_points = (
        tuple(target["point_a_rc"]),
        tuple(target["point_b_rc"]),
        tuple(target["point_c_rc"]),
        tuple(target["point_d_rc"]),
    )
    # 这里不把规则路径本身纳入裁剪框，是为了让 focus 图稳定围绕输入端点展开。
    r0, c0, r1, c1 = focus_bounds_from_points(focus_points, geometry_result.gray.shape, pad_rc=32.0)

    # 先在完整画布上画局部需要的 sweep 和规则，再统一裁切。
    canvas = render_gray(geometry_result.gray, render_scale)
    # 这样可以复用全图坐标系，不必为局部图单独做坐标平移。
    from_path, to_path = draw_focus_sweep_paths(canvas, target, render_scale)
    # 参与关系的任一 sweep 退化时，局部图就退回空灰底，避免输出误导图。
    if len(from_path) < 2 or len(to_path) < 2:
        return render_gray(geometry_result.gray, render_scale)

    # 规则路径或失败叉只保留目标 connection 自身。
    rule_kind = str(target.get("connection_class", ""))
    rule_path = to_path_tuple(target.get("rule_geometry_rc", ()))
    color = pick_connection_rule_color(rule_kind)
    # 颜色选择和总览图保持一致，便于人在两张图之间对照。
    # constructible 决定画规则几何还是失败叉，这里不再混画两者。
    if bool(target.get("is_constructible", True)):
        draw_path_polyline(canvas, tuple(rule_path), color, render_scale)
        draw_path_points(canvas, tuple(rule_path), color, render_scale, radius=1)
    else:
        draw_failure_cross(canvas, failure_marker_point(target), _FAILED_CONNECTION_X_COLOR, render_scale)

    # 端点标记比总览图稍大，便于在局部裁切图中快速识别。
    draw_connection_truth_markers(canvas, target, render_scale, marker_radius=5, text_offset_y=14)

    # rc 包围盒转成放大后画布上的像素裁剪框。
    # 这里仍保持左闭右开切片语义，便于和 numpy 切片一致。
    x0 = int(round(c0 * float(render_scale)))
    y0 = int(round(r0 * float(render_scale)))
    x1 = int(round(c1 * float(render_scale)))
    y1 = int(round(r1 * float(render_scale)))
    # `copy()` 明确切断和大画布的共享，避免后续标题写入反向污染原图。
    crop = canvas[y0:y1, x0:x1].copy()
    # 标题补充目标 sweep 对和 theta，方便导出后独立阅读。
    # theta 直接取 target 中记录的值，避免这里重复推导。
    cv2.putText(
        crop,
        f"{int(from_sweep_id)} -> {int(to_sweep_id)}  theta={float(target['theta_deg']):.1f}",
        (12, 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (30, 30, 30),
        1,
        cv2.LINE_AA,
    )
    return crop
