"""Coverage 规划渲染底层画布与几何原语。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np


def scaled_xy(point_rc: tuple[float, float], render_scale: int) -> tuple[int, int]:
    """把运行尺度 rc 点转成渲染尺度下的 OpenCV `(x, y)`。"""

    # 画点、画折线和打标签都共享这套坐标换算规则。
    # 统一 helper 后，取整策略和倍率处理都不会在各函数里漂移。
    scale = max(1, int(render_scale))
    return (
        int(round(float(point_rc[1]) * scale)),
        int(round(float(point_rc[0]) * scale)),
    )


def path_points_xy(path_rc: tuple[tuple[float, float], ...], render_scale: int) -> np.ndarray:
    """把 rc 路径转成 OpenCV 需要的整数 xy 点列。"""

    # 路径画法统一经由这个 helper，避免各处各写一遍 rc -> xy 转换。
    return np.array([list(scaled_xy(point_rc, render_scale)) for point_rc in path_rc], dtype=np.int32)


def draw_dashed_segment_xy(
    canvas: np.ndarray,
    start_xy: tuple[int, int],
    end_xy: tuple[int, int],
    color: tuple[int, int, int],
    dash_len_px: int,
    gap_len_px: int,
) -> None:
    """在画布上画一段已经缩放到 xy 空间的虚线段。"""

    # 这个 helper 只负责单段 dash/gap 采样，不关心整条路径的段顺序。
    # 因而输入已经必须是渲染尺度下的整数 xy 坐标。
    dash = max(1, int(dash_len_px))
    gap = max(1, int(gap_len_px))
    # 一个 pattern 周期由一段 dash 和一段 gap 组成。
    pattern = dash + gap
    dx = float(end_xy[0] - start_xy[0])
    dy = float(end_xy[1] - start_xy[1])
    # 段长在 xy 空间计算，和最终屏幕呈现保持一致。
    seg_len = float((dx * dx + dy * dy) ** 0.5)
    # 退化短段没有虚线意义，直接跳过。
    if seg_len <= 1e-6:
        return
    # `distance` 始终表示当前已经推进到该段上的哪一个位置。
    distance = 0.0
    while distance < seg_len:
        # 每次循环只负责画出当前周期里的可见 dash 部分。
        dash_start = distance
        dash_end = min(distance + float(dash), seg_len)
        start_ratio = dash_start / seg_len
        end_ratio = dash_end / seg_len
        # 通过线性插值把标量距离映回实际像素坐标。
        # 这样虚线段的几何中心仍然严格落在原始线段上。
        p0 = (
            int(round(float(start_xy[0]) + dx * start_ratio)),
            int(round(float(start_xy[1]) + dy * start_ratio)),
        )
        p1 = (
            int(round(float(start_xy[0]) + dx * end_ratio)),
            int(round(float(start_xy[1]) + dy * end_ratio)),
        )
        # 单个 dash 仍由普通实线段画出，视觉上最稳定。
        cv2.line(canvas, p0, p1, color, 1, cv2.LINE_AA)
        # 每次画完一个 dash 后直接跳过一个 gap。
        distance += float(pattern)


def render_gray(gray: np.ndarray, render_scale: int) -> np.ndarray:
    """把运行尺度灰度图放大到渲染尺度，并转成 BGR。"""

    # 渲染层统一在这里做最近邻放大，保持像素级地图边界不被模糊。
    # 转成 BGR 后，后续所有彩色覆盖都可以直接原地绘制。
    # 这也是 coverage 渲染画布的统一入口。
    # 输入始终按灰度图理解，不在这里区分具体地图来源。
    if render_scale <= 1:
        gray_render = gray
    else:
        gray_render = cv2.resize(
            gray,
            (int(gray.shape[1] * render_scale), int(gray.shape[0] * render_scale)),
            interpolation=cv2.INTER_NEAREST,
        )
    return cv2.cvtColor(gray_render, cv2.COLOR_GRAY2BGR)


def draw_polygon(
    canvas: np.ndarray,
    polygon_rc: tuple[tuple[float, float], ...],
    color: tuple[int, int, int],
    render_scale: int,
) -> None:
    """画节点 polygon。"""

    # polygon 少于 3 点时不具备闭环边界意义。
    if len(polygon_rc) < 3:
        return
    # OpenCV 需要 `(x, y)` 整数点列，因此这里先从 rc 转成 xy。
    # 画法只描边不填充，避免盖住底图上的其它 coverage 元素。
    # 这类 polygon 主要用来表达节点边界，而不是区域面积。
    pts = path_points_xy(polygon_rc, render_scale)
    cv2.polylines(canvas, [pts], True, color, 1, cv2.LINE_AA)


def draw_region_points(
    canvas: np.ndarray,
    region_pixels_rc: tuple[tuple[int, int], ...],
    color: tuple[int, int, int],
    render_scale: int,
) -> None:
    """用点云方式画 coverage lane 有效区域。"""

    # 这种画法忠实保留离散 region 像素，不尝试补洞或连通。
    # 它更适合 debug 视图，而不是正式区域着色。
    # 每个 region 点都会被单独投到渲染画布上。
    # 因而可以直接观察 coverage 区域的像素离散形态。
    for row, col in region_pixels_rc:
        draw_row = int(row * render_scale)
        draw_col = int(col * render_scale)
        cv2.circle(canvas, (draw_col, draw_row), 1, color, -1, lineType=cv2.LINE_AA)
    # 点云方式的优势是能直接看出原始采样密度。


def fill_region_points(
    canvas: np.ndarray,
    region_pixels_rc: tuple[tuple[int, int], ...],
    color: tuple[int, int, int],
    render_scale: int,
) -> None:
    """把 region 画成半透明叠加前的实心色块。"""

    # 每个 region 像素都扩成一个渲染尺度的小方块。
    # 这样做适合给区域打底色，而不是画稀疏点云。
    # 方块边界也因此严格贴合原始栅格。
    # 最终效果更接近“填格子”而不是“撒点”。
    for row, col in region_pixels_rc:
        top = int(row * render_scale)
        left = int(col * render_scale)
        bottom = min(int((row + 1) * render_scale), canvas.shape[0])
        right = min(int((col + 1) * render_scale), canvas.shape[1])
        canvas[top:bottom, left:right] = color


def draw_path_points(
    canvas: np.ndarray,
    path_rc: tuple[tuple[float, float], ...],
    color: tuple[int, int, int],
    render_scale: int,
    radius: int,
) -> None:
    """只画离散路径点，不连线。"""

    # 点绘更适合表达采样序列或稀疏离散路径。
    # 对 sweep 端点或重采样点的可视化尤其直观。
    # 半径由调用方控制，便于区分主点和辅助点。
    # 同时也避免折线把局部采样密度“视觉平均化”。
    for row_f, col_f in path_rc:
        col, row = scaled_xy((row_f, col_f), render_scale)
        cv2.circle(canvas, (col, row), int(radius), color, -1, lineType=cv2.LINE_AA)
    # 这里不试图表达点与点之间的连通关系。


def draw_path_polyline(
    canvas: np.ndarray,
    path_rc: tuple[tuple[float, float], ...],
    color: tuple[int, int, int],
    render_scale: int,
) -> None:
    """把离散路径画成细折线，用于表示参考几何线。"""

    # 少于两个点时无法形成折线。
    if len(path_rc) < 2:
        return
    # 坐标统一从 rc 转成 OpenCV 所需的 xy 整数点。
    # 它主要服务参考路径或主干路径的连续几何表达。
    # 与 `_draw_path_points` 相比，这里强调的是连通关系。
    points_xy = path_points_xy(path_rc, render_scale)
    cv2.polylines(canvas, [points_xy], False, color, 1, cv2.LINE_AA)
    # 线宽固定为 1，避免与 support band 这种粗线语义混淆。


def draw_support_band(
    canvas: np.ndarray,
    path_rc: tuple[tuple[float, float], ...],
    support_width_px: float,
    render_scale: int,
    band_color: tuple[int, int, int],
) -> None:
    """用半透明粗线表达连接段的覆盖支撑宽度。"""

    # 没有路径或支撑宽度非正时，不存在可绘制支撑带。
    if len(path_rc) < 2 or float(support_width_px) <= 0.0:
        return
    # 先画到 overlay，再以固定透明度回混到原画布。
    # 这样可以保留底图纹理，同时让支撑宽度有明显存在感。
    # support band 的线宽直接来自覆盖支撑宽度，不再额外修饰。
    # 颜色语义也因此能稳定对应“支撑带”而不是“路径中心线”。
    thickness = max(1, int(round(float(support_width_px) * float(render_scale))))
    overlay = canvas.copy()
    points_xy = path_points_xy(path_rc, render_scale)
    cv2.polylines(overlay, [points_xy], False, band_color, thickness, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.28, canvas, 0.72, 0.0, dst=canvas)
    # overlay 策略能避免粗线把原图完全涂死。


def draw_path_dashed_polyline(
    canvas: np.ndarray,
    path_rc: tuple[tuple[float, float], ...],
    color: tuple[int, int, int],
    render_scale: int,
    dash_len_px: int,
    gap_len_px: int,
) -> None:
    """把单条 sweep 的点链画成虚线。"""

    # 虚线按每段分别采样，避免长折线跨段时 dash 相位漂移过大。
    if len(path_rc) < 2:
        return
    # 每段都按自身长度切分 dash/gap，不跨段累计残余长度。
    # 这样折点前后不会因为模式衔接而出现难以解释的残缺 dash。
    # 上层只需要提供整条路径，单段细节完全由 helper 消化。
    # 这也让整条 sweep 虚线路径的规则更容易解释。

    for idx in range(1, len(path_rc)):
        start_xy = scaled_xy(path_rc[idx - 1], render_scale)
        end_xy = scaled_xy(path_rc[idx], render_scale)
        draw_dashed_segment_xy(canvas, start_xy, end_xy, color, dash_len_px, gap_len_px)
    # 因而整条虚线路径只是单段虚线的稳定串联。


def to_path_tuple(path_rc: Any) -> tuple[tuple[float, float], ...]:
    """把任意路径容器转成浮点坐标元组。"""

    # 渲染侧统一使用不可变浮点路径，避免上游容器类型差异渗透进来。
    return tuple((float(point_rc[0]), float(point_rc[1])) for point_rc in path_rc)


def write_image(output_path: Path, image: np.ndarray) -> None:
    """写图到磁盘。"""

    # 写盘失败直接抛异常，避免上层把“没落盘”误判成“没有输出需求”。
    if not cv2.imwrite(str(output_path), image):
        raise RuntimeError(f"failed to write image: {output_path}")



__all__ = [
    "draw_path_dashed_polyline",
    "draw_path_points",
    "draw_path_polyline",
    "draw_polygon",
    "draw_region_points",
    "fill_region_points",
    "draw_support_band",
    "render_gray",
    "to_path_tuple",
    "write_image",
]
