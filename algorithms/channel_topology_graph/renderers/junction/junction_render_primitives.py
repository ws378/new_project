"""Junction rebuild 渲染底层图元。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def scaled_xy(point_rc: tuple[float, float], render_scale: int) -> tuple[int, int]:
    """把运行尺度 rc 点换成渲染尺度下的 OpenCV `(x, y)`。"""

    # 所有图元都共享同一套 rc -> xy 转换规则。
    # 抽成 helper 后，坐标口径和取整方式都集中在这一处。
    scale = max(1, int(render_scale))
    return (
        int(round(float(point_rc[1]) * scale)),
        int(round(float(point_rc[0]) * scale)),
    )


def path_points_xy(
    path_rc: tuple[tuple[float, float], ...] | list[tuple[float, float]],
    render_scale: int,
) -> np.ndarray:
    """把 rc 路径转成 OpenCV 折线需要的整数 xy 点列。"""

    # 折线和 polygon 边界都共享同一套路径坐标转换逻辑。
    # 返回值直接符合 OpenCV polyline 接口的整数点格式。
    return np.asarray([list(scaled_xy(point_rc, render_scale)) for point_rc in path_rc], dtype=np.int32)


def render_gray(gray: np.ndarray, render_scale: int) -> np.ndarray:
    """把灰度图渲染成 BGR。"""

    # 输入既可能是单通道灰度，也可能已经是三通道图。
    # 统一在这里收成可直接叠加彩色标记的 BGR 画布。
    if gray.ndim == 2:
        image = cv2.cvtColor(gray.astype(np.uint8), cv2.COLOR_GRAY2BGR)
    else:
        image = gray.copy()
    return upsample_nearest(image, render_scale)


def overlay_skeleton(base_gray: np.ndarray, skeleton_mask: np.ndarray, color: tuple[int, int, int], render_scale: int) -> np.ndarray:
    """把骨架叠加到底图上。"""

    # 先得到可渲染的 BGR 底图，再把骨架掩膜放大到同一尺度。
    # 骨架像素直接按指定颜色覆盖，保持观感最清晰。
    base = render_gray(base_gray, render_scale)
    scaled_mask = upsample_nearest(np.where(skeleton_mask > 0, 255, 0).astype(np.uint8), render_scale)
    base[scaled_mask > 0] = color
    return base


def draw_mask_points(
    canvas: np.ndarray,
    mask: np.ndarray,
    color: tuple[int, int, int],
    render_scale: int,
) -> None:
    """把掩膜按离散点直接画到底图上。"""

    # 这里不做连线，只忠实表达掩膜里哪些像素为真。
    # 因而它非常适合画局部窗口里的原始 mask 支撑点。
    # `np.argwhere` 输出的是 `(row, col)`，和本文件 rc 约定天然一致。
    for point_rc in np.argwhere(mask > 0):
        draw_single_pixel(canvas, (float(point_rc[0]), float(point_rc[1])), color, render_scale)
    # 最终观感类似“按像素着色”，而不是几何轮廓。
    # 这能避免掩膜边缘被错误解读成平滑曲线。
    # 对 skeleton / support mask 这类离散真值尤其重要。


def draw_point(canvas: np.ndarray, point_rc: tuple[float, float], color: tuple[int, int, int], render_scale: int, radius: int) -> None:
    """在渲染图上画点。"""

    # 先乘渲染倍率，再离散到画布像素坐标。
    # 先画白色描边，再画实心色块，能让点在灰底上更醒目。
    point_xy = scaled_xy(point_rc, render_scale)
    cv2.circle(canvas, point_xy, radius + 1, (255, 255, 255), -1, cv2.LINE_AA)
    cv2.circle(canvas, point_xy, radius, color, -1, cv2.LINE_AA)


def draw_single_pixel(
    canvas: np.ndarray,
    point_rc: tuple[float, float],
    color: tuple[int, int, int],
    render_scale: int,
) -> None:
    """在 8 倍底图上画单像素点。"""

    # 单像素标记主要用于表达稀疏离散点，而不是连续几何。
    # 边界检查放在这里统一做，调用方无需重复判断画布范围。
    # 越界点被自然丢弃，保证上游无需在每次调用前裁剪。
    cc, rr = scaled_xy(point_rc, render_scale)
    if 0 <= rr < canvas.shape[0] and 0 <= cc < canvas.shape[1]:
        canvas[rr, cc] = color


def draw_circle_outline(
    canvas: np.ndarray,
    point_rc: tuple[float, float],
    color: tuple[int, int, int],
    render_scale: int,
    radius_px: int,
) -> None:
    """以单个运行尺度点为圆心，画渲染尺度下的空心圈。"""

    # 这个 helper 用于强调某个点，但不遮挡底下的其它几何元素。
    # 半径参数已经按渲染尺度传入，因此这里不再额外乘 render_scale。
    # 常见用途是高亮当前中心、cut 点或候选点。
    point_xy = scaled_xy(point_rc, render_scale)
    cv2.circle(canvas, point_xy, int(radius_px), color, 1, cv2.LINE_8)


def draw_text(
    canvas: np.ndarray,
    text: str,
    point_rc: tuple[float, float],
    color: tuple[int, int, int],
    render_scale: int,
) -> None:
    """在点旁标注文本。"""

    # 文字落点固定相对目标点偏移，避免正好压在标记中心上。
    # 字体和字号在 junction 系列视图里保持统一。
    # 这样不同视图之间的标注风格不会漂移。
    cc, rr = scaled_xy(point_rc, render_scale)
    cv2.putText(canvas, text, (cc + 6, rr - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_8)


def draw_polyline(
    canvas: np.ndarray,
    path_rc: tuple[tuple[float, float], ...] | list[tuple[float, float]],
    color: tuple[int, int, int],
    render_scale: int,
    thickness: int = 1,
) -> None:
    """画路径折线。"""

    # 少于两个点时不可能形成折线，直接忽略。
    if len(path_rc) < 2:
        return
    # OpenCV 统一吃 `(x, y)` 整数坐标，因此这里先做 rc -> xy 转换。
    # 这类折线通常用于表示 edge path、branch path 或辅助方向线。
    # 这样调用方只要提供 rc 语义路径，不必关心具体渲染坐标系。
    pts = path_points_xy(path_rc, render_scale)
    cv2.polylines(canvas, [pts], False, color, thickness, cv2.LINE_8)
    # thickness 由调用方控制，便于区分主线与辅助线。
    # 因而同一个 helper 可以覆盖多种可视化语义层次。
    # 但它始终只画开口折线，不负责闭环 polygon。


def draw_path_points(
    canvas: np.ndarray,
    path_rc: tuple[tuple[float, float], ...] | list[tuple[float, float]],
    color: tuple[int, int, int],
    render_scale: int,
) -> None:
    """把路径按离散点直接画出来，不再连接。"""

    # 这种画法适合强调采样点分布，而不是路径连续形状。
    # 尤其适合观察 path 是否存在离散跳点或密度变化。
    # 因为每个点都独立落图，所以不会被 OpenCV 的连线插值掩盖问题。
    for point_rc in path_rc:
        draw_single_pixel(canvas, point_rc, color, render_scale)
    # 与 `_draw_polyline` 的差别在于这里只强调“点”，不强调“边”。
    # 因而它能更直接暴露离散采样质量。
    # 调试离群点或采样断裂时也更敏感。


def draw_segment(
    canvas: np.ndarray,
    start_rc: tuple[float, float],
    end_rc: tuple[float, float],
    color: tuple[int, int, int],
    render_scale: int,
) -> None:
    """画单条辅助线段。"""

    # 单段辅助线用于方向、sector 半径或临时几何说明。
    # 坐标统一在这里转成 OpenCV 所需的 `(x, y)` 形式。
    # 调用方只关心 rc 语义，不必自己做 xy 转换。
    # 这也保证了它和 `_draw_polyline` / `_draw_polygon_outline` 的取整规则一致。
    pt0 = scaled_xy(start_rc, render_scale)
    pt1 = scaled_xy(end_rc, render_scale)
    cv2.line(canvas, pt0, pt1, color, 1, cv2.LINE_8)
    # 线宽固定为 1，避免掩盖更重要的主路径几何。
    # 视觉语义也因此保持“辅助线”而不是“主体几何”。
    # 这使它很适合表达 sector 半径或方向参考线。


def draw_dashed_segment(
    canvas: np.ndarray,
    start_rc: tuple[float, float],
    end_rc: tuple[float, float],
    color: tuple[int, int, int],
    render_scale: int,
    dash_period: int = 6,
) -> None:
    """画单像素虚线段。"""

    # 虚线通过“沿段采样 + 跳过部分采样点”实现。
    start_rr = float(start_rc[0])
    start_cc = float(start_rc[1])
    end_rr = float(end_rc[0])
    end_cc = float(end_rc[1])
    steps = max(1, int(round(max(abs(end_rr - start_rr), abs(end_cc - start_cc)))))
    # 按 Chebyshev 步数采样，能保证水平/垂直/对角线都不会漏点。
    # 这里直接在 rc 空间采样，再交给 `_draw_single_pixel` 完成缩放和落点。
    # dash_period 控制的是“采样点周期”，而不是连续像素长度。
    # 因而不同方向上的 dash 视觉密度会保持相近。
    for step in range(steps + 1):
        if (step // max(1, dash_period)) % 2 == 1:
            continue
        # 当前采样点是否落在 dash 还是 gap，由周期位置决定。
        alpha = step / steps
        point_rc = (
            float(start_rr + (end_rr - start_rr) * alpha),
            float(start_cc + (end_cc - start_cc) * alpha),
        )
        # 线性插值保证 dash 中每个采样点都落在原始线段上。
        # 最终是否显示，还会再经过 `_draw_single_pixel` 的画布边界裁剪。
        draw_single_pixel(canvas, point_rc, color, render_scale)
    # 因而最终视觉效果是离散点构成的细虚线，而不是抗锯齿粗虚线。
    # 这更适合 junction debug 里辅助线的轻量表达。
    # 同时也避免 OpenCV 虚线 API 不稳定带来的样式漂移。
    # 代价是它更偏像素风格，但这正符合当前 debug 视图需求。
    # 因为该视图的重点是结构解释，而不是成品视觉美观。


def draw_polygon_outline(
    canvas: np.ndarray,
    polygon_rc: tuple[tuple[float, float], ...] | list[tuple[float, float]],
    color: tuple[int, int, int],
    render_scale: int,
) -> None:
    """画 polygon 边界，不做填充。"""

    # polygon 至少要有 3 个顶点才有边界意义。
    if len(polygon_rc) < 3:
        return
    # 这里同样统一做 rc -> xy 转换，保证和其它图元 helper 口径一致。
    # 仅描边不填充，避免挡住 polygon 内部的 sector 或 branch 可视化。
    # 同时闭合参数固定为 True，确保最后一条边不会被漏画。
    pts = path_points_xy(polygon_rc, render_scale)
    cv2.polylines(canvas, [pts], True, color, 1, cv2.LINE_8)
    # 这种画法更适合调试结构边界，而不是表达区域权重。
    # 因为内部其它元素通常比边界本身更值得保留。
    # 边界只承担“圈出范围”的职责。


def point_from_angle(
    center_rc: tuple[float, float],
    theta_deg: float,
    radius_px: float,
) -> tuple[float, float]:
    """按方向角和半径构造扇区辅助端点。"""

    # 图像坐标里，row 对应 `sin`，col 对应 `cos`。
    # 返回值保持浮点 rc，方便继续喂给其它渲染 helper。
    # 该 helper 常用于画 sector 辅助射线或圆周辅助点。
    # 因而它只负责几何构点，不直接参与绘制。
    theta_rad = np.deg2rad(float(theta_deg))
    return (float(center_rc[0] + radius_px * np.sin(theta_rad)), float(center_rc[1] + radius_px * np.cos(theta_rad)))


def path_midpoint(path_rc: tuple[tuple[float, float], ...] | list[tuple[float, float]]) -> tuple[float, float]:
    """取路径中点用于边编号标注。"""

    # 空路径时回原点占位，避免标注逻辑单独判空。
    # 非空路径则直接取离散点序列的中位位置。
    if not path_rc:
        return (0.0, 0.0)
    return tuple(map(float, path_rc[len(path_rc) // 2]))


def upsample_nearest(image: np.ndarray, render_scale: int) -> np.ndarray:
    """按最近邻放大渲染图。"""

    # 最近邻能最好保留像素级 mask / skeleton 的块状边界。
    # 当 scale 为 1 时直接复制，避免上游意外共享底层缓冲。
    scale = max(1, int(render_scale))
    if scale == 1:
        return image.copy()
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)


def write_image(path: str | Path, image: np.ndarray) -> None:
    """写图文件。"""

    # 输出目录在这里统一补齐，调用方只负责给出目标路径。
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 写图失败直接抛异常，避免上游误以为可视化已经落盘。
    if not cv2.imwrite(str(path), image):
        raise IOError(f"failed to write image: {path}")



__all__ = [
    "draw_circle_outline",
    "draw_dashed_segment",
    "draw_mask_points",
    "draw_path_points",
    "draw_polygon_outline",
    "draw_single_pixel",
    "draw_text",
    "path_midpoint",
    "point_from_angle",
    "render_gray",
    "write_image",
]
