"""Coverage 规划渲染图例 helper。"""

from __future__ import annotations

import cv2
import numpy as np

from .coverage_render_palette import (
    CADENCE_NEXT_POINT_COLOR as _CADENCE_NEXT_POINT_COLOR,
    CADENCE_PREV_POINT_COLOR as _CADENCE_PREV_POINT_COLOR,
    CADENCE_RELATION_LIGHT_COLOR as _CADENCE_RELATION_LIGHT_COLOR,
    CADENCE_RULE_BEND_COLOR as _CADENCE_RULE_BEND_COLOR,
    CADENCE_RULE_DIRECT_COLOR as _CADENCE_RULE_DIRECT_COLOR,
    CADENCE_RULE_SMOOTH_COLOR as _CADENCE_RULE_SMOOTH_COLOR,
    CADENCE_SWEEP_PATH_COLOR as _CADENCE_SWEEP_PATH_COLOR,
    FAILED_CONNECTION_X_COLOR as _FAILED_CONNECTION_X_COLOR,
    FALLBACK_TRANSITION_COLOR as _FALLBACK_TRANSITION_COLOR,
    FINAL_PATH_CONNECTOR_DEBUG_COLOR as _FINAL_PATH_CONNECTOR_DEBUG_COLOR,
    FINAL_PATH_SWEEP_DEBUG_COLOR as _FINAL_PATH_SWEEP_DEBUG_COLOR,
    JUNCTION_CONNECTION_COLOR as _JUNCTION_CONNECTION_COLOR,
    REJECT_TRANSITION_COLOR as _REJECT_TRANSITION_COLOR,
    STRONG_TRANSITION_COLOR as _STRONG_TRANSITION_COLOR,
    UTURN_CONNECTION_COLOR as _UTURN_CONNECTION_COLOR,
    WEAK_TRANSITION_COLOR as _WEAK_TRANSITION_COLOR,
)


def draw_transition_candidate_legend(canvas: np.ndarray) -> None:
    """在 transition candidate 调试图上加图例。"""

    # 图例项顺序直接对应 transition 候选从强到弱、从保留到拒绝的语义。
    # 这样读图时无需再回头比对文档。
    legend_items = (
        ("strong_keep", _STRONG_TRANSITION_COLOR),
        ("weak_keep", _WEAK_TRANSITION_COLOR),
        ("weak_keep_fallback", _FALLBACK_TRANSITION_COLOR),
        ("reject", _REJECT_TRANSITION_COLOR),
    )
    # 位置和尺寸都固定，确保不同 debug 图的图例视觉锚点一致。
    left = 14
    top = 18
    line_h = 22
    box_w = 230
    box_h = 12 + line_h * len(legend_items)
    # 先铺浅底，再画细边框，保证图例在彩色路径上仍然清晰可读。
    cv2.rectangle(canvas, (left - 8, top - 12), (left + box_w, top + box_h), (245, 245, 245), -1, cv2.LINE_AA)
    cv2.rectangle(canvas, (left - 8, top - 12), (left + box_w, top + box_h), (120, 120, 120), 1, cv2.LINE_AA)

    # 每个 legend item 都用“线段 + 箭头 + 文本”三件套表达。
    for idx, (label, color) in enumerate(legend_items):
        y = top + idx * line_h
        # 线段本身表示连接方向关系。
        cv2.line(canvas, (left, y), (left + 34, y), color, 1, cv2.LINE_AA)
        # 箭头强调 candidate 连接具有方向性，而不是无向邻接。
        cv2.arrowedLine(canvas, (left + 10, y), (left + 24, y), color, 1, cv2.LINE_AA, tipLength=0.45)
        # 文字始终使用统一深灰，避免喧宾夺主。
        cv2.putText(canvas, label, (left + 44, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 40), 1, cv2.LINE_AA)


def draw_sweep_cadence_legend(canvas: np.ndarray) -> None:
    """在 SweepCadence 图上加图例。"""

    # kind 字段决定左侧示意符号的绘法。
    # 文本标签则保持业务命名，方便和日志、调试输出对应。
    legend_items = (
        ("Sweep path", _CADENCE_SWEEP_PATH_COLOR, "line"),
        ("Cadence relation", _CADENCE_RULE_DIRECT_COLOR, "arrow"),
        ("P-1 / P", _CADENCE_PREV_POINT_COLOR, "circle_pair"),
        ("Q / Q+1", _CADENCE_NEXT_POINT_COLOR, "square_pair"),
    )
    # 这一组图例比 transition 图略窄，但仍共用同一套左上角布局。
    left = 14
    top = 18
    line_h = 22
    box_w = 220
    box_h = 12 + line_h * len(legend_items)
    # 浅色背景能隔离底图噪声，特别是覆盖在复杂路径云上时。
    cv2.rectangle(canvas, (left - 8, top - 12), (left + box_w, top + box_h), (245, 245, 245), -1, cv2.LINE_AA)
    cv2.rectangle(canvas, (left - 8, top - 12), (left + box_w, top + box_h), (120, 120, 120), 1, cv2.LINE_AA)

    # 不同 kind 用不同基本图元，让路径、关系和端点角色一眼可分。
    for idx, (label, color, kind) in enumerate(legend_items):
        y = top + idx * line_h
        if kind == "line":
            # Sweep path 只需要一条细线即可表达“轨迹”语义。
            cv2.line(canvas, (left, y), (left + 34, y), color, 1, cv2.LINE_AA)
        elif kind == "arrow":
            # Cadence relation 同时画线和箭头，强调前后方向。
            cv2.line(canvas, (left, y), (left + 34, y), color, 2, cv2.LINE_AA)
            cv2.arrowedLine(canvas, (left + 10, y), (left + 24, y), color, 2, cv2.LINE_AA, tipLength=0.45)
        elif kind == "circle_pair":
            # 空心 + 实心圆区分 P-1 与 P 两个时序角色。
            cv2.circle(canvas, (left + 10, y), 4, color, 2, cv2.LINE_AA)
            cv2.circle(canvas, (left + 24, y), 4, color, -1, cv2.LINE_AA)
        else:
            # 方块对应用于 Q / Q+1，和圆点组形成稳定对照。
            cv2.rectangle(canvas, (left + 6, y - 4), (left + 14, y + 4), color, -1, cv2.LINE_AA)
            cv2.rectangle(canvas, (left + 20, y - 4), (left + 28, y + 4), color, 2, cv2.LINE_AA)
        # 文本列宽固定，防止不同图例项长度影响布局节奏。
        cv2.putText(canvas, label, (left + 44, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 40), 1, cv2.LINE_AA)


def draw_sweep_cadence_classification_inputs_legend(canvas: np.ndarray) -> None:
    """给分类输入调试图绘制 P/Q 端点图例。"""

    # 这张图只关心分类输入端点，因此图例刻意保持最小集合。
    legend_items = (
        ("P-1 / P", _CADENCE_PREV_POINT_COLOR, "circle_pair"),
        ("Q / Q+1", _CADENCE_NEXT_POINT_COLOR, "square_pair"),
    )
    # 位置下沉到 top=84，避免遮挡分类图上方更关键的标题信息。
    left = 14
    top = 84
    line_h = 22
    box_w = 180
    box_h = 12 + line_h * len(legend_items)
    # 背景框和其他 legend helper 保持相同视觉规范。
    cv2.rectangle(canvas, (left - 8, top - 12), (left + box_w, top + box_h), (245, 245, 245), -1, cv2.LINE_AA)
    cv2.rectangle(canvas, (left - 8, top - 12), (left + box_w, top + box_h), (120, 120, 120), 1, cv2.LINE_AA)
    # 两类端点继续沿用“圆对 / 方块对”的视觉语义。
    for idx, (label, color, kind) in enumerate(legend_items):
        y = top + idx * line_h
        if kind == "circle_pair":
            # 先前时序点用圆形，延续 sweep cadence 主图的约定。
            cv2.circle(canvas, (left + 10, y), 4, color, 2, cv2.LINE_AA)
            cv2.circle(canvas, (left + 24, y), 4, color, -1, cv2.LINE_AA)
        else:
            # 后续时序点用方形，与 P 组天然区分。
            cv2.rectangle(canvas, (left + 6, y - 4), (left + 14, y + 4), color, -1, cv2.LINE_AA)
            cv2.rectangle(canvas, (left + 20, y - 4), (left + 28, y + 4), color, 2, cv2.LINE_AA)
        # 说明文字只承担释义，不参与额外高亮。
        cv2.putText(canvas, label, (left + 44, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 40), 1, cv2.LINE_AA)


def draw_sweep_cadence_connection_rules_legend(canvas: np.ndarray) -> None:
    """给连接规则调试图绘制规则类型与端点图例。"""

    # 这一组图例同时覆盖“背景关系线”“规则类别”“端点角色”三种语义。
    # 因而图例项数量更多，但顺序仍按读图优先级排列。
    legend_items = (
        ("Cadence relation(bg)", _CADENCE_RELATION_LIGHT_COLOR),
        ("Direct", _CADENCE_RULE_DIRECT_COLOR),
        ("Single bend", _CADENCE_RULE_BEND_COLOR),
        ("Smooth curve", _CADENCE_RULE_SMOOTH_COLOR),
        ("P-1 / P", _CADENCE_PREV_POINT_COLOR),
        ("Q / Q+1", _CADENCE_NEXT_POINT_COLOR),
    )
    # 布局尺寸按 item 数自动扩展，避免手工同步修改高度。
    left = 14
    top = 18
    line_h = 22
    box_w = 220
    box_h = 12 + line_h * len(legend_items)
    # 边框和底色与其它图例保持统一，减小跨图认知切换成本。
    cv2.rectangle(canvas, (left - 8, top - 12), (left + box_w, top + box_h), (245, 245, 245), -1, cv2.LINE_AA)
    cv2.rectangle(canvas, (left - 8, top - 12), (left + box_w, top + box_h), (120, 120, 120), 1, cv2.LINE_AA)
    # 根据 label 分派示意符号，而不是单独增加结构字段。
    # 这里更看重图例文本和业务术语的一一对应。
    for idx, (label, color) in enumerate(legend_items):
        y = top + idx * line_h
        if label == "P-1 / P":
            # P 组依旧是空心 + 实心圆。
            cv2.circle(canvas, (left + 10, y), 4, color, 2, cv2.LINE_AA)
            cv2.circle(canvas, (left + 24, y), 4, color, -1, cv2.LINE_AA)
        elif label == "Q / Q+1":
            # Q 组依旧是实心 + 描边方块。
            cv2.rectangle(canvas, (left + 6, y - 4), (left + 14, y + 4), color, -1, cv2.LINE_AA)
            cv2.rectangle(canvas, (left + 20, y - 4), (left + 28, y + 4), color, 2, cv2.LINE_AA)
        elif label == "Cadence relation(bg)":
            # 背景关系线故意画得更细，避免和真正规则线抢视觉焦点。
            cv2.line(canvas, (left, y), (left + 34, y), color, 1, cv2.LINE_AA)
            cv2.arrowedLine(canvas, (left + 10, y), (left + 24, y), color, 1, cv2.LINE_AA, tipLength=0.45)
        else:
            # 规则类型统一用加粗线表示，但具体颜色区分 direct / bend / smooth。
            cv2.line(canvas, (left, y), (left + 34, y), color, 2, cv2.LINE_AA)
        # 所有文字都对齐到同一列，确保扫描阅读效率。
        cv2.putText(canvas, label, (left + 44, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 40), 1, cv2.LINE_AA)


def draw_junction_summary_legend(canvas: np.ndarray) -> None:
    """给节点连接汇总图绘制节点状态图例。"""

    # 这张图只强调节点状态，因此图例简化成两种节点颜色。
    legend_items = (
        ("Node with transition connector", _JUNCTION_CONNECTION_COLOR),
        ("Node with foldback connector", _UTURN_CONNECTION_COLOR),
    )
    # 盒子尺寸依旧按 item 数量自动推导，避免魔法常数散落。
    left = 14
    top = 18
    line_h = 22
    box_w = 220
    box_h = 12 + line_h * len(legend_items)
    # 统一浅底框保证彩色点符号在任意背景上都可辨认。
    cv2.rectangle(canvas, (left - 8, top - 12), (left + box_w, top + box_h), (245, 245, 245), -1, cv2.LINE_AA)
    cv2.rectangle(canvas, (left - 8, top - 12), (left + box_w, top + box_h), (120, 120, 120), 1, cv2.LINE_AA)
    # 节点状态直接用实心圆复用主图中的节点视觉语言。
    for idx, (label, color) in enumerate(legend_items):
        y = top + idx * line_h
        # 左侧点符号只表达颜色，不再引入额外边框语义。
        cv2.circle(canvas, (left + 16, y), 5, color, -1, cv2.LINE_AA)
        # 标签文本解释颜色含义，避免用户猜测。
        cv2.putText(canvas, label, (left + 32, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 40), 1, cv2.LINE_AA)


def draw_final_coverage_path_legend(canvas: np.ndarray) -> None:
    """给 FinalCoveragePath 调试图绘制路径与失败标记图例。"""

    # final coverage path 图需要同时解释 sweep、connector 和失败标记。
    # 因而这里用 kind 区分连续路径和离散失败符号。
    legend_items = (
        ("Sweep path", _FINAL_PATH_SWEEP_DEBUG_COLOR, "line"),
        ("Connector path", _FINAL_PATH_CONNECTOR_DEBUG_COLOR, "line"),
        ("Failed connector", _FAILED_CONNECTION_X_COLOR, "x"),
    )
    # 布局沿用统一左上角模板，减小多张 debug 图之间的跳读成本。
    left = 14
    top = 18
    line_h = 22
    box_w = 220
    box_h = 12 + line_h * len(legend_items)
    # 浅底 + 细边框是 coverage 系列 debug legend 的统一皮肤。
    cv2.rectangle(canvas, (left - 8, top - 12), (left + box_w, top + box_h), (245, 245, 245), -1, cv2.LINE_AA)
    cv2.rectangle(canvas, (left - 8, top - 12), (left + box_w, top + box_h), (120, 120, 120), 1, cv2.LINE_AA)
    # line 类型画连续路径，x 类型画失败连接的叉号。
    for idx, (label, color, kind) in enumerate(legend_items):
        y = top + idx * line_h
        if kind == "x":
            # 叉号比短线更容易被读成“失败/断开”。
            cv2.line(canvas, (left + 4, y - 6), (left + 28, y + 6), color, 1, cv2.LINE_AA)
            cv2.line(canvas, (left + 4, y + 6), (left + 28, y - 6), color, 1, cv2.LINE_AA)
        else:
            # 路径除了主线，再补三个点，强调这是离散采样路径而不是抽象箭头。
            cv2.line(canvas, (left, y), (left + 34, y), color, 1, cv2.LINE_AA)
            for dot_x in (left + 6, left + 16, left + 26):
                cv2.circle(canvas, (dot_x, y), 2, color, -1, cv2.LINE_AA)
        # 文本列统一放在右侧，读取顺序和其他图例一致。
        cv2.putText(canvas, label, (left + 44, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 40), 1, cv2.LINE_AA)



__all__ = [
    "draw_final_coverage_path_legend",
    "draw_junction_summary_legend",
    "draw_sweep_cadence_classification_inputs_legend",
    "draw_sweep_cadence_connection_rules_legend",
    "draw_sweep_cadence_legend",
    "draw_transition_candidate_legend",
]
