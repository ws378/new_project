"""多边形几何工具：切割（画线分割多边形）、交点计算、等高线提取等"""

from typing import List, Tuple, Optional
import cv2
import numpy as np
import math

from typing import List, Tuple, Optional

Point = Tuple[float, float]


def _cross(ax: float, ay: float, bx: float, by: float) -> float:
    return ax * by - ay * bx


def _side(p: Point, a: Point, b: Point) -> float:
    """Cross product (b-a) × (p-a). Positive = left side."""
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _line_intersection(p1: Point, p2: Point, a: Point, b: Point) -> Optional[Point]:
    """Return intersection point of line segments p1-p2 and a-b, or None."""
    denom = _cross(p2[0] - p1[0], p2[1] - p1[1], b[0] - a[0], b[1] - a[1])
    if abs(denom) < 1e-12:
        return None
    t = _cross(a[0] - p1[0], a[1] - p1[1], b[0] - a[0], b[1] - a[1]) / denom
    x = p1[0] + t * (p2[0] - p1[0])
    y = p1[1] + t * (p2[1] - p1[1])
    return (x, y)


def _is_point_on_segment(p: Point, a: Point, b: Point, eps: float = 1e-9) -> bool:
    """Check if point p lies on segment a-b (collinear + within bounding box)."""
    if abs(_side(p, a, b)) > eps:
        return False
    return min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps and \
           min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps


def _clip_polygon_by_halfplane(
    polygon: List[Point],
    a: Point,
    b: Point,
    keep_left: bool,
) -> List[Point]:
    """Clip polygon against the half-plane defined by line a→b.
    
    keep_left=True  →  keep points where side(p) >= 0
    keep_left=False →  keep points where side(p) <= 0
    
    Uses Sutherland-Hodgman algorithm.
    """
    if not polygon:
        return []

    output = []
    n = len(polygon)
    for i in range(n):
        p1 = polygon[i]
        p2 = polygon[(i + 1) % n]
        s1 = _side(p1, a, b)
        s2 = _side(p2, a, b)

        p1_inside = s1 >= 0 if keep_left else s1 <= 0
        p2_inside = s2 >= 0 if keep_left else s2 <= 0

        if p1_inside and p2_inside:
            output.append(p2)
        elif p1_inside and not p2_inside:
            inter = _line_intersection(p1, p2, a, b)
            if inter is not None:
                output.append(inter)
        elif not p1_inside and p2_inside:
            inter = _line_intersection(p1, p2, a, b)
            if inter is not None:
                output.append(inter)
                output.append(p2)

    # Remove consecutive duplicate points
    if len(output) > 1:
        cleaned = [output[0]]
        for p in output[1:]:
            px, py = p
            lx, ly = cleaned[-1]
            if (px - lx) ** 2 + (py - ly) ** 2 > 1e-12:
                cleaned.append(p)
        output = cleaned

    return output


def split_polygon_by_line(
    polygon: List[Point],
    line_start: Point,
    line_end: Point,
    min_area_factor: float = 0.05,
) -> Tuple[Optional[List[Point]], Optional[List[Point]]]:
    """Split a polygon by a cutting line.
    
    Returns (polygon_left, polygon_right) where left/right is relative to
    the direction from line_start to line_end (left = cross product >= 0).
    
    Either result may be None if the resulting polygon has < 3 points.
    """
    if len(polygon) < 3:
        return None, None

    # Extend the cutting line significantly beyond the polygon bounds to ensure clean cuts
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    dx = line_end[0] - line_start[0]
    dy = line_end[1] - line_start[1]
    length = max(max(xs) - min(xs), max(ys) - min(ys)) * 2.0
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return None, None
    norm = (dx ** 2 + dy ** 2) ** 0.5
    a_ext = (line_start[0] - dx / norm * length, line_start[1] - dy / norm * length)
    b_ext = (line_start[0] + dx / norm * length, line_start[1] + dy / norm * length)

    left_poly = _clip_polygon_by_halfplane(polygon, a_ext, b_ext, keep_left=True)
    right_poly = _clip_polygon_by_halfplane(polygon, a_ext, b_ext, keep_left=False)

    # Clean up: remove colinear points for both halves
    left_poly = _simplify_polygon(left_poly)
    right_poly = _simplify_polygon(right_poly)

    if len(left_poly) < 3:
        left_poly = None
    if len(right_poly) < 3:
        right_poly = None

    # If both resulting polygons are essentially the same (cut line missed),
    # return None for both
    if left_poly is not None and right_poly is not None:
        if _polygon_area(left_poly) < 1e-9 or _polygon_area(right_poly) < 1e-9:
            return None, None

    return left_poly, right_poly


def _simplify_polygon(poly: List[Point], eps: float = 1e-9) -> List[Point]:
    """Remove colinear points and consecutive duplicates from polygon."""
    if len(poly) < 3:
        return poly
    result = [poly[0]]
    for i in range(1, len(poly) - 1):
        curr = poly[i]
        # Skip consecutive duplicate
        if abs(curr[0] - result[-1][0]) < eps and abs(curr[1] - result[-1][1]) < eps:
            continue
        prev = result[-1]
        nxt = poly[i + 1]
        if abs(_side(curr, prev, nxt)) > eps:
            result.append(curr)
    last = poly[-1]
    if abs(last[0] - result[-1][0]) < eps and abs(last[1] - result[-1][1]) < eps:
        pass  # last equals previous, skip
    else:
        result.append(last)
    return result


def _polygons_overlap(poly1: List[Point], poly2: List[Point]) -> bool:
    """检查两个多边形是否有重叠（顶点包含或边相交）。"""
    # 顶点包含测试
    arr1 = np.array(poly1, dtype=np.float32).reshape((-1, 1, 2))
    arr2 = np.array(poly2, dtype=np.float32).reshape((-1, 1, 2))
    for v in poly1:
        if cv2.pointPolygonTest(arr2, (float(v[0]), float(v[1])), False) >= 0:
            return True
    for v in poly2:
        if cv2.pointPolygonTest(arr1, (float(v[0]), float(v[1])), False) >= 0:
            return True
    # 边相交测试
    for i in range(len(poly1)):
        a1, b1 = poly1[i], poly1[(i + 1) % len(poly1)]
        for j in range(len(poly2)):
            a2, b2 = poly2[j], poly2[(j + 1) % len(poly2)]
            inter = _line_intersection(a1, b1, a2, b2)
            if inter is not None:
                # 交点必须在两条线段上
                if (_is_point_on_segment(inter, a1, b1) and
                    _is_point_on_segment(inter, a2, b2)):
                    return True
    return False


def _nearest_point_on_boundary(
    pt: Point, subject: List[Point]
) -> Tuple[Point, float]:
    """返回 subject 边界上离 pt 最近的点及距离。"""
    best_pt, best_d = pt, float("inf")
    for si in range(len(subject)):
        sa, sb = subject[si], subject[(si + 1) % len(subject)]
        dx, dy = sb[0] - sa[0], sb[1] - sa[1]
        denom = dx * dx + dy * dy
        if denom < 1e-12:
            continue
        t = ((pt[0] - sa[0]) * dx + (pt[1] - sa[1]) * dy) / denom
        t = max(0.0, min(1.0, t))
        px, py = sa[0] + t * dx, sa[1] + t * dy
        d = math.hypot(pt[0] - px, pt[1] - py)
        if d < best_d:
            best_d, best_pt = d, (px, py)
    return best_pt, best_d


def subtract_polygon(
    subject: List[Point],
    clip: List[Point],
) -> Tuple[Optional[List[Point]], Optional[List[Point]]]:
    """从 subject 多边形中减去 clip 多边形。

    基于 OpenCV mask 的栅格化方法，支持任意多边形（凸/凹均可）。
    clip 完全在 subject 内部时自动用几何桥接将孔洞转为缺口，
    返回 (带缺口的单多边形, 切出多边形)。
    若 subject 被完全裁掉，剩余为 None。
    若 clip 与 subject 不重叠，返回 (subject, None)。
    """
    if len(subject) < 3 or len(clip) < 3:
        return list(subject), None

    # 快速检测：不重叠则直接返回
    if not _polygons_overlap(subject, clip):
        return list(subject), None

    # 将多边形转换为像素坐标进行 mask 操作
    all_pts = subject + clip
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    margin = 1.0
    min_x, max_x = min(xs) - margin, max(xs) + margin
    min_y, max_y = min(ys) - margin, max(ys) + margin

    scale = 100.0  # 像素/单位，保证足够精度
    w = int((max_x - min_x) * scale) + 3
    h = int((max_y - min_y) * scale) + 3

    def to_px(pt):
        return int(round((pt[0] - min_x) * scale)), int(round((pt[1] - min_y) * scale))

    def to_world(px, py):
        return px / scale + min_x, py / scale + min_y

    subject_px = np.array([to_px(p) for p in subject], dtype=np.int32)
    clip_px = np.array([to_px(p) for p in clip], dtype=np.int32)
    subject_mask = np.zeros((h, w), dtype=np.uint8)
    clip_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(subject_mask, [subject_px], 255)
    cv2.fillPoly(clip_mask, [clip_px], 255)

    # 检测 clip 是否完全在 subject 内部
    subj_arr = np.array(subject, dtype=np.float32).reshape((-1, 1, 2))
    clip_fully_inside = all(
        cv2.pointPolygonTest(subj_arr, (float(x), float(y)), False) >= 0
        for (x, y) in clip
    )

    _bridge_added = False
    if clip_fully_inside:
        # 掩膜桥接：在 clip 上附加一个细长矩形"尾部"延伸到 subject 边界，
        # 使剩余区域变为单连通，findContours 可提取单个外轮廓（带可见缺口）。
        best_cv_idx = -1
        best_sv = None
        min_d = float("inf")
        for ci, cv in enumerate(clip):
            sv, d = _nearest_point_on_boundary(cv, subject)
            if d < min_d:
                min_d, best_cv_idx = d, ci
                best_sv = sv

        BRIDGE_WIDTH_M = 0.2
        if best_cv_idx >= 0 and best_sv is not None:
            bc = clip[best_cv_idx]
            dx = bc[0] - best_sv[0]
            dy = bc[1] - best_sv[1]
            length = math.hypot(dx, dy)
            if length > 1e-6:
                perp_x = -dy / length * BRIDGE_WIDTH_M / 2.0
                perp_y = dx / length * BRIDGE_WIDTH_M / 2.0
                bridge_rect = [
                    (best_sv[0] - perp_x, best_sv[1] - perp_y),
                    (bc[0] - perp_x, bc[1] - perp_y),
                    (bc[0] + perp_x, bc[1] + perp_y),
                    (best_sv[0] + perp_x, best_sv[1] + perp_y),
                ]
                bridge_rect_px = np.array([to_px(p) for p in bridge_rect], dtype=np.int32)
                cv2.fillPoly(clip_mask, [bridge_rect_px], 255)
                _bridge_added = True

    # 剩余 = subject - clip
    remaining_mask = cv2.bitwise_and(subject_mask, cv2.bitwise_not(clip_mask))
    cut_out_mask = cv2.bitwise_and(subject_mask, clip_mask)

    cnt_rem, hierarchy = cv2.findContours(remaining_mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    cnt_cut, _ = cv2.findContours(cut_out_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if cnt_rem is None or len(cnt_rem) == 0:
        return None, list(clip)

    outer_contours = []
    hole_contours = []
    for i, c in enumerate(cnt_rem):
        area = cv2.contourArea(c)
        if area < 4:
            continue
        if hierarchy is not None and hierarchy[0][i][3] >= 0:
            hole_contours.append(c)
        else:
            outer_contours.append(c)

    if not outer_contours:
        return None, list(clip)

    if hole_contours:
        # 仍然有孔洞（桥接失效），返回原 subject
        return list(subject), list(clip)

    largest_outer = max(outer_contours, key=cv2.contourArea)
    remaining = [to_world(pt[0][0], pt[0][1]) for pt in largest_outer]
    # DP 简化（2 像素容差），同时保留桥接缺口
    eps_dp = 2.0 / scale
    rem_arr = np.array(remaining, dtype=np.float32).reshape((-1, 1, 2))
    rem_arr = cv2.approxPolyDP(rem_arr, eps_dp, closed=True)
    remaining = [(float(pt[0][0]), float(pt[0][1])) for pt in rem_arr]
    if len(remaining) < 3:
        return None, list(clip)

    cut_out = None
    if _bridge_added:
        # 桥接模式下 cut_out 应精确等于用户画的 clip 多边形（不包含桥接矩形）
        cut_out = list(clip)
    elif cnt_cut is not None and len(cnt_cut) > 0:
        largest_cut = max(cnt_cut, key=cv2.contourArea)
        cut_out = [to_world(pt[0][0], pt[0][1]) for pt in largest_cut]
        cut_out_arr = np.array(cut_out, dtype=np.float32).reshape((-1, 1, 2))
        cut_out_arr = cv2.approxPolyDP(cut_out_arr, eps_dp, closed=True)
        cut_out = [(float(pt[0][0]), float(pt[0][1])) for pt in cut_out_arr]
        if len(cut_out) < 3:
            cut_out = None

    return remaining, cut_out


def _polygon_area(poly: List[Point]) -> float:
    """Signed area of polygon."""
    if len(poly) < 3:
        return 0.0
    area = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def extract_contour_polylines(
    binary_map: np.ndarray,
    resolution: float,
    step_m: float = 0.5,
    start_offset_m: float = 0.3,
    layer_gap_m: float = 0.5,
    contour_layers: int = 0,
    min_perimeter_factor: float = 1.0,
) -> List[List[Tuple[float, float]]]:
    """Extract contour polylines from a binary map as pixel-coordinate polylines.
    
    Returns a list of polylines, where each polyline is a list of (col, row) pixel coordinates
    (image convention: origin at top-left, x=col, y=row).
    The caller is responsible for converting to world coordinates via origin + resolution.
    This is a standalone contour extraction that does NOT build a graph — it simply
    traces the distance-transform threshold contours.
    """
    step_px = int(round(step_m / resolution))
    if step_px < 1:
        step_px = 1
    start_offset_px = int(round(start_offset_m / resolution))
    layer_gap_px = int(round(layer_gap_m / resolution))
    if layer_gap_px < 1:
        layer_gap_px = 1

    free = (binary_map > 0).astype(np.uint8) * 255
    # 加1像素黑色边框确保空白地图也有背景（距离变换需要至少一个0像素）
    free = cv2.copyMakeBorder(free, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    h_orig, w_orig = free.shape[0] - 2, free.shape[1] - 2
    dist = cv2.distanceTransform(free, cv2.DIST_L2, 5)
    dist = dist[1:-1, 1:-1]  # 去掉边框，恢复原始尺寸
    max_d = float(dist.max())
    if max_d < 1:
        return []

    num_layers: int
    if contour_layers > 0:
        num_layers = contour_layers
    else:
        if layer_gap_px <= 0:
            num_layers = 1
        else:
            num_layers = max(1, int(max_d / layer_gap_px) + 1)

    min_perimeter = step_px * min_perimeter_factor

    all_polylines: List[List[Tuple[float, float]]] = []
    d = float(start_offset_px)
    seen_polylines: set[bytes] = set()

    for _ in range(num_layers):
        if d >= max_d:
            break
        mask = (dist >= d).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        for contour in contours:
            pts = contour.squeeze(axis=1)
            if pts.ndim != 2 or pts.shape[0] < 2:
                continue

            # Arc length filter
            cum = [0.0]
            for i in range(1, len(pts)):
                dx = float(pts[i, 0]) - float(pts[i - 1, 0])
                dy = float(pts[i, 1]) - float(pts[i - 1, 1])
                cum.append(cum[-1] + math.hypot(dx, dy))
            total = cum[-1]
            if total < min_perimeter:
                continue

            # Deduplicate similar polylines (by coarse hash of first/last point)
            if len(pts) > 2:
                key = bytes([int(pts[0, 0]) % 100, int(pts[0, 1]) % 100,
                             int(pts[-1, 0]) % 100, int(pts[-1, 1]) % 100])
                if key in seen_polylines:
                    continue
                seen_polylines.add(key)

            # Sample points along contour at step_px intervals
            poly_px: List[Tuple[float, float]] = []
            t = 0.0
            idx = 0
            while t < total and idx < len(pts):
                while idx < len(cum) - 1 and cum[idx + 1] < t:
                    idx += 1
                col = float(pts[idx, 0])
                row = float(pts[idx, 1])
                poly_px.append((col, row))
                t += float(step_px)

            if len(poly_px) >= 2:
                all_polylines.append(poly_px)

        d += float(layer_gap_px)

    return all_polylines


def partition_contour_outer_region(
    contour_polylines_px: List[List[Tuple[float, float]]],
    free_mask: np.ndarray,
    grid_size_px: int = 20,
) -> List[List[Tuple[float, float]]]:
    """将等高线外侧自由空间用规则网格分割成矩形区域标签。

    通过距离变换计算等高线等距线区域（dist >= start_offset_px），
    将自由空间划分成 grid_size_px × grid_size_px 的单元格，
    只保留位于该区域内的单元格（等高线"外侧"=远离障碍物一侧），
    相邻单元格合并后返回。

    Args:
        contour_polylines_px: 等高线像素坐标列表（用于推断 start_offset_px）
        free_mask: 自由空间掩膜（1=free, 0=obstacle）
        grid_size_px: 网格像素尺寸（默认 20px ≈ 1m @ 0.05m/px）

    Returns:
        List of polygons，每个多边形是 4 顶点 (col, row) 列表。
    """
    h, w = free_mask.shape[:2]

    # 直接通过距离变换计算 "等高线内侧区域" (dist >= start_offset_px)
    # contour_polylines 的采样步长 ≈ 相邻点距离中位数
    if contour_polylines_px:
        # 用第一条等高线的相邻点间距估算 start_offset_px
        ref = np.array(contour_polylines_px[0], dtype=np.float32)
        if len(ref) >= 2:
            dx = np.diff(ref[:, 0])
            dy = np.diff(ref[:, 1])
            step = np.median(np.sqrt(dx**2 + dy**2))
        else:
            step = 10.0
    else:
        step = 10.0

    start_offset_px = max(1, int(round(step * 0.6)))  # ~60% of step_px
    fore = ((free_mask > 0).astype(np.uint8) * 255)
    fore = cv2.copyMakeBorder(fore, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    dist = cv2.distanceTransform(fore, cv2.DIST_L2, 5)
    dist = dist[1:-1, 1:-1]
    safe_mask = (dist >= start_offset_px).astype(np.uint8)  # 等高线内侧 = dist >= threshold

    # 生成规则网格
    cell_map: dict[tuple[int, int], bool] = {}
    for x0 in range(0, w, grid_size_px):
        x1 = min(x0 + grid_size_px, w)
        if x1 - x0 < grid_size_px // 2:
            continue
        for y0 in range(0, h, grid_size_px):
            y1 = min(y0 + grid_size_px, h)
            if y1 - y0 < grid_size_px // 2:
                continue
            cx, cy = int((x0 + x1) / 2.0), int((y0 + y1) / 2.0)
            inside = bool(0 <= cx < w and 0 <= cy < h and free_mask[cy, cx] == 1 and safe_mask[cy, cx] == 1)
            cell_map[(x0, y0)] = inside

    active_cells = [(x0, y0) for (x0, y0), ok in cell_map.items() if ok]
    if not active_cells:
        return []

    step_x = step_y = grid_size_px
    rows: dict[int, list[tuple[int, int]]] = {}
    for x0, y0 in sorted(active_cells, key=lambda p: (p[1], p[0])):
        x1 = min(x0 + step_x, w)
        rows.setdefault(y0, []).append((x0, x1))

    # 水平合并
    merged_rows: dict[int, list[tuple[int, int]]] = {}
    for y0, segs in rows.items():
        segs.sort()
        cur = list(segs[0])
        merged: list[tuple[int, int]] = []
        for seg in segs[1:]:
            if seg[0] == cur[1]:
                cur[1] = seg[1]
            else:
                merged.append(tuple(cur))
                cur = list(seg)
        merged.append(tuple(cur))
        merged_rows[y0] = merged

    # 垂直合并
    y_segs = sorted(merged_rows.keys())
    rects: list[tuple[int, int, int, int]] = []
    for y0 in y_segs:
        if not merged_rows[y0]:
            continue
        for x0, x1 in list(merged_rows[y0]):
            y1 = y0 + step_y
            while y1 in merged_rows:
                if (x0, x1) not in merged_rows.get(y1, []):
                    break
                y1 += step_y
            all_ok = True
            for yy in range(y0 + step_y, y1, step_y):
                if (x0, x1) not in merged_rows.get(yy, []):
                    all_ok = False
                    break
            if all_ok:
                rects.append((x0, x1, y0, y1))
                for yy in range(y0, y1, step_y):
                    if yy in merged_rows:
                        merged_rows[yy] = [s for s in merged_rows[yy] if s != (x0, x1)]
            else:
                rects.append((x0, x1, y0, y0 + step_y))

    cells = [[(float(x0), float(y0)), (float(x1), float(y0)),
              (float(x1), float(y1)), (float(x0), float(y1))]
             for x0, x1, y0, y1 in rects]

    return cells


def extract_outer_boundary_polygon(
    binary_mask: np.ndarray,
    resolution: float,
    simplify_eps_m: float = 0.3,
    min_area_px: int = 100,
) -> Optional[List[Tuple[float, float]]]:
    """提取自由空间最外层边界多边形（像素坐标 (col, row)）。

    用 cv2.findContours(RETR_EXTERNAL) 找最大外轮廓，
    然后用 Douglas-Peucker 简化（approxPolyDP），
    返回单个 (col, row) 像素坐标多边形列表。
    没有有效自由空间时返回 None。
    """
    fore = (binary_mask > 0).astype(np.uint8) * 255
    contours, hierarchy = cv2.findContours(fore, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < min_area_px:
        return None

    eps_px = max(1.0, simplify_eps_m / resolution)
    approx = cv2.approxPolyDP(largest, eps_px, closed=True)

    polygon = [(float(pt[0][0]), float(pt[0][1])) for pt in approx]
    return polygon if len(polygon) >= 3 else None
