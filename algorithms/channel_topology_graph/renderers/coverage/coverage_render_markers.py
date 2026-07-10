"""Coverage 规划渲染标记与文字 helper。"""

from __future__ import annotations

import cv2
import numpy as np

from ...contracts import FinalCoveragePathConnection


def scaled_xy(point_rc: tuple[float, float], render_scale: int) -> tuple[int, int]:
    """把 rc 坐标转成渲染尺度下的 OpenCV `(x, y)`。"""

    # 文字、marker 和失败叉都共享同一套坐标换算规则。
    # 取整规则也集中在这里，避免不同 helper 的落点出现半像素偏差。
    scale = max(1, int(render_scale))
    return (
        int(round(float(point_rc[1]) * scale)),
        int(round(float(point_rc[0]) * scale)),
    )


def draw_text(
    canvas: np.ndarray,
    text: str,
    point_rc: tuple[float, float],
    color: tuple[int, int, int],
    render_scale: int,
) -> None:
    """在目标点附近画纯文字。"""

    # 文字锚点统一按 rc -> 画布像素转换。
    # 固定偏移能避免文字正好压在 marker 圆心上。
    # 这个 helper 只负责纯文字，不额外画任何底座标记。
    col, row = scaled_xy(point_rc, render_scale)
    cv2.putText(canvas, str(text), (col + 3, row - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1, cv2.LINE_AA)


def draw_text_offset(
    canvas: np.ndarray,
    text: str,
    point_rc: tuple[float, float],
    color: tuple[int, int, int],
    render_scale: int,
    offset_x_px: int,
    offset_y_px: int,
) -> None:
    """在目标点附近按像素偏移画文字。"""

    # 这个 helper 允许调用方显式控制偏移方向与距离。
    # 适合多标签同时围绕同一点排布的场景。
    # 像素偏移参数在这里不乘 render_scale，调用方传的就是最终偏移量。
    col, row = scaled_xy(point_rc, render_scale)
    # 文字风格仍与 `_draw_text` 保持一致，只是偏移来源不同。
    # 因此两种文字 helper 可以在同一张图里混用而不显得突兀。
    # 实际传给 OpenCV 的仍是一组普通文字参数，没有特殊路径效果。
    # 这保证它和其它文字渲染 helper 的视觉基线一致。
    cv2.putText(
        canvas,
        str(text),
        (col + int(offset_x_px), row + int(offset_y_px)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.35,
        color,
        1,
        cv2.LINE_AA,
    )
    # 因而调用方可以在同一视觉体系下自由安排多个标签位置。
    # 这个 helper 自己不做碰撞规避，只负责忠实执行给定偏移。
    # 偏移策略的决策权保持在更上层的布局逻辑里。
    # 这也让 debug 视图可以按需要灵活堆叠多组文字说明。
    # 渲染层的职责仅限于“画”，不负责“布局求优”。
    # 统一的 `cv2.putText` 参数也确保文字风格不会漂移。
    # 所有额外复杂度都收敛在偏移量本身，而不是绘制参数上。


def draw_transition_with_mid_arrow(
    canvas: np.ndarray,
    start_rc: tuple[float, float],
    end_rc: tuple[float, float],
    color: tuple[int, int, int],
    render_scale: int,
    thickness: int = 1,
    arrow_scale: float = 1.0,
) -> None:
    """画连接细线，并在中部补一支箭头。"""

    # 先画完整连接线，再在中段叠一支方向箭头。
    # 这样既能看到完整 seam，也能读出连接方向。
    start_xy = scaled_xy(start_rc, render_scale)
    end_xy = scaled_xy(end_rc, render_scale)
    cv2.line(canvas, start_xy, end_xy, color, int(max(1, thickness)), cv2.LINE_AA)

    dx = float(end_xy[0] - start_xy[0])
    dy = float(end_xy[1] - start_xy[1])
    length = float((dx * dx + dy * dy) ** 0.5)
    # 零长度连接没有方向意义，直接退回。
    if length <= 1e-6:
        return
    # `ux/uy` 是连接方向的单位向量，供箭头长度和位置计算复用。
    ux = dx / length
    uy = dy / length
    # 箭头长度对超短段和超长段都做了夹紧，避免视觉比例失衡。
    # 同时还允许上层通过 arrow_scale 做轻量调节。
    arrow_len = min(22.0, max(5.0, 0.25 * length * float(max(0.5, arrow_scale))))
    mid_x = 0.5 * float(start_xy[0] + end_xy[0])
    mid_y = 0.5 * float(start_xy[1] + end_xy[1])
    # 箭头固定围绕中点展开，避免贴近端点后和 marker/label 冲突。
    # 中点方案也能保证正反向连接的箭头位置一致。
    # 因而视觉注意力会自然落在连接关系本身，而不是某个端点。
    arrow_start = (
        int(round(mid_x - 0.5 * arrow_len * ux)),
        int(round(mid_y - 0.5 * arrow_len * uy)),
    )
    arrow_end = (
        int(round(mid_x + 0.5 * arrow_len * ux)),
        int(round(mid_y + 0.5 * arrow_len * uy)),
    )
    # tipLength 取固定比例，保证中段箭头的形状一致。
    # 箭头绘制放在最后，确保它压在线段之上而更醒目。
    cv2.arrowedLine(canvas, arrow_start, arrow_end, color, int(max(1, thickness)), cv2.LINE_AA, tipLength=0.45)
    # 整个 helper 的输出因此稳定分成“底线 + 中段箭头”两个视觉层次。
    # 这种画法对长短连接都比较稳健。
    # 也便于图例与图面保持一致的视觉语义。


def pick_label_point_from_region(
    region_pixels_rc: tuple[tuple[float, float], ...],
    fallback_path_rc: tuple[tuple[float, float], ...],
) -> tuple[float, float] | None:
    """为文字标签挑一个尽量居中的位置。"""

    # 优先用 region 中部像素，标签更容易落在语义区域内部。
    if region_pixels_rc:
        mid_index = int(len(region_pixels_rc) * 0.5)
        return float(region_pixels_rc[mid_index][0]), float(region_pixels_rc[mid_index][1])
    # region 不存在时，再退回路径中点。
    # 这样标签至少还能跟着几何主线走，不会彻底丢失落点。
    # 两者都为空时才返回空，要求上层决定是否跳过标注。
    if fallback_path_rc:
        mid_index = int(len(fallback_path_rc) * 0.5)
        return float(fallback_path_rc[mid_index][0]), float(fallback_path_rc[mid_index][1])
    return None


def pick_sweep_endpoint_by_end_type(
    path_rc: tuple[tuple[float, float], ...],
    end_type: str,
) -> tuple[float, float] | None:
    """按 src/dst 语义取 sweep 端点。"""

    # 渲染层只接受 src/dst 两种端点语义。
    if not path_rc:
        return None
    # 空路径直接回空，避免下游误把原点当成合法端点。
    if str(end_type) == "src":
        return path_rc[0]
    if str(end_type) == "dst":
        return path_rc[-1]
    # 未知端点语义不做猜测，直接显式返回空。
    # 这样错误语义会在渲染结果里自然表现为“没有端点标记”。
    return None


def draw_filled_marker(
    canvas: np.ndarray,
    point_rc: tuple[float, float],
    color: tuple[int, int, int],
    render_scale: int,
    radius: int,
) -> None:
    """画实心圆标记。"""

    # 实心圆适合表达“确定采用/选中”的点。
    # 坐标缩放和取整统一由 `_scaled_xy` 控制。
    col, row = scaled_xy(point_rc, render_scale)
    # 半径参数已经是渲染尺度半径，不再额外缩放。
    cv2.circle(canvas, (col, row), int(radius), color, -1, lineType=cv2.LINE_AA)


def draw_hollow_marker(
    canvas: np.ndarray,
    point_rc: tuple[float, float],
    color: tuple[int, int, int],
    render_scale: int,
    radius: int,
) -> None:
    """画空心圆标记。"""

    # 空心圆更适合表达候选点或辅助点，避免完全遮住底图。
    # 外框厚度固定为 2，保证高亮但不过分粗重。
    col, row = scaled_xy(point_rc, render_scale)
    # 它和实心圆共享同一中心定位规则。
    cv2.circle(canvas, (col, row), int(radius), color, 2, lineType=cv2.LINE_AA)


def draw_square_marker(
    canvas: np.ndarray,
    point_rc: tuple[float, float],
    color: tuple[int, int, int],
    render_scale: int,
    half_size: int,
    filled: bool,
) -> None:
    """画方形标记。"""

    # 方形标记常用于和圆形标记区分不同语义类别。
    # filled 参数只控制填充方式，不改变外框尺寸。
    # 中心点同样沿用 `_scaled_xy` 的统一坐标转换口径。
    col, row = scaled_xy(point_rc, render_scale)
    top_left = (col - int(half_size), row - int(half_size))
    bottom_right = (col + int(half_size), row + int(half_size))
    # OpenCV 里 thickness=-1 表示填充矩形，其余值表示描边。
    # 这层语义转换集中在这里，调用方只传布尔开关即可。
    thickness = -1 if filled else 2
    cv2.rectangle(canvas, top_left, bottom_right, color, thickness, cv2.LINE_AA)
    # 因而 filled=False 时可以稳定得到同尺寸空心方框。
    # 这一点对比不同语义 marker 时很重要。
    # 同尺寸也是保证图例和图面一致性的前提。
    # 这样调用方只需关心语义，不必再手工补齐尺寸差。


def failure_marker_point(item: FinalCoveragePathConnection) -> tuple[float, float]:
    """从失败连接的两端 seam 点估计打叉位置。"""

    # 失败打叉位置取 seam 中点，能同时表达“失败发生在两段之间”。
    point_b = tuple(map(float, item["point_b_rc"]))
    point_c = tuple(map(float, item["point_c_rc"]))
    # 这里不看路径细节，只依赖连接条目里已经记录好的 seam 点。
    # 返回值保持浮点 rc，方便继续交给统一的 marker helper 处理。
    return (
        0.5 * (float(point_b[0]) + float(point_c[0])),
        0.5 * (float(point_b[1]) + float(point_c[1])),
    )


def draw_failure_cross(
    canvas: np.ndarray,
    point_rc: tuple[float, float],
    color: tuple[int, int, int],
    render_scale: int,
) -> None:
    """在指定点画失败连接的红叉。"""

    # 红叉尺寸会随 render_scale 放大，确保在高倍率图上仍然可见。
    col, row = scaled_xy(point_rc, render_scale)
    half = max(6, int(round(1.4 * float(render_scale))))
    # 两条对角线共享同一中心和尺度，保证叉形对称。
    cv2.line(canvas, (col - half, row - half), (col + half, row + half), color, 2, cv2.LINE_AA)
    # 第二条线只翻转一侧方向，形成标准失败叉。
    # 与圆点/方点不同，失败叉天然不会遮掉中心内部的细节。
    cv2.line(canvas, (col - half, row + half), (col + half, row - half), color, 2, cv2.LINE_AA)



__all__ = [
    "draw_failure_cross",
    "draw_filled_marker",
    "draw_hollow_marker",
    "draw_square_marker",
    "draw_text",
    "draw_text_offset",
    "draw_transition_with_mid_arrow",
    "failure_marker_point",
    "pick_label_point_from_region",
    "pick_sweep_endpoint_by_end_type",
]
