#!/usr/bin/env python3
"""对已有覆盖路径做机器人几何与清扫 footprint 只读诊断。"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.turn_cost_coverage_research.src.diagnostics.path_window_diagnostics import (
    PathWindowDiagnosticConfig,
    detect_path_windows,
    normalize_angle_deg,
)


DEFAULT_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    theta: float
    source_index: int


@dataclass(frozen=True)
class GeometryConfig:
    reference_point: str = "rear_axle_center"
    rear_axle_to_front_m: float = 0.60
    rear_axle_to_rear_m: float = 0.20
    rear_axle_to_left_m: float = 0.30
    rear_axle_to_right_m: float = 0.30
    clearance_warning_m: float = 0.05
    left_brush_center_m: tuple[float, float] = (-0.15, 0.18)
    right_brush_center_m: tuple[float, float] = (0.15, 0.18)
    brush_radius_m: float = 0.14
    squeegee_y_m: float = -0.20
    squeegee_left_m: float = -0.40
    squeegee_right_m: float = 0.40
    squeegee_arc_depth_m: float = 0.07
    squeegee_effective_width_m: float = 0.03


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True, help="已有 ShelfAware+TurnCost 运行目录。")
    parser.add_argument(
        "--prepare-dir",
        type=Path,
        help="prepare_map 目录；默认使用 run-dir 同级目录下的 prepare_map。",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "algorithms" / "turn_cost_coverage_research" / "output",
        help="诊断输出根目录。",
    )
    parser.add_argument("--case-name", default="beiguoshangcheng_floor_3_area5", help="输出目录中的 case 名称。")
    parser.add_argument("--max-visual-size", type=int, default=1800, help="单张图长边最大像素。")
    return parser.parse_args()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_path(path: Path) -> list[Pose]:
    payload = _read_json(path)
    poses: list[Pose] = []
    for index, item in enumerate(payload):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            poses.append(Pose(x=float(item[0]), y=float(item[1]), theta=0.0, source_index=index))
            continue
        poses.append(
            Pose(
                x=float(item["x"]),
                y=float(item["y"]),
                theta=float(item.get("theta", 0.0)),
                source_index=int(item.get("index", index)),
            )
        )
    if len(poses) < 2:
        raise ValueError(f"path has too few poses: {path}")
    return poses


def _metadata_resolution(run_dir: Path) -> float:
    metadata_path = run_dir / "metadata.json"
    if metadata_path.is_file():
        metadata = _read_json(metadata_path)
        if "map_resolution" in metadata:
            return float(metadata["map_resolution"])
    region_path = run_dir / "region.json"
    if region_path.is_file():
        planner_params = _read_json(region_path).get("planner_params", {})
        # region.json 不总是包含 map resolution；保底使用项目当前通用分辨率。
        if "map_resolution" in planner_params:
            return float(planner_params["map_resolution"])
    return 0.05


def _coverage_width_px(run_dir: Path, resolution_m: float) -> int:
    metadata_path = run_dir / "metadata.json"
    if metadata_path.is_file():
        metadata = _read_json(metadata_path)
        if "coverage_width_px" in metadata:
            return int(metadata["coverage_width_px"])
        if "coverage_width_m" in metadata:
            return max(1, int(round(float(metadata["coverage_width_m"]) / resolution_m)))
    region_path = run_dir / "region.json"
    if region_path.is_file():
        params = _read_json(region_path).get("planner_params", {})
        if "coverage_width_m" in params:
            return max(1, int(round(float(params["coverage_width_m"]) / resolution_m)))
    return max(1, int(round(0.60 / resolution_m)))


def _planner_params(run_dir: Path) -> dict[str, Any]:
    region_path = run_dir / "region.json"
    if not region_path.is_file():
        return {}
    payload = _read_json(region_path)
    params = payload.get("planner_params", {})
    return params if isinstance(params, dict) else {}


def _path_window_config(run_dir: Path, resolution_m: float, coverage_width_m: float) -> PathWindowDiagnosticConfig:
    params = _planner_params(run_dir)
    turn_constraint = params.get("turn_constraint", {}) if isinstance(params.get("turn_constraint", {}), dict) else {}
    near_max_turn_deg = float(turn_constraint.get("near_max_turn_deg", 20.0))
    neighbor_max_turn_deg = float(turn_constraint.get("neighbor_max_turn_deg", 100.0))
    fallback_relax_dist_m = float(turn_constraint.get("fallback_relax_dist_m", max(2.0, coverage_width_m * 3.0)))
    return PathWindowDiagnosticConfig(
        resolution_m=resolution_m,
        straight_angle_tol_deg=near_max_turn_deg,
        sharp_turn_deg=max(60.0, min(90.0, neighbor_max_turn_deg * 0.7)),
        direction_change_deg=max(40.0, near_max_turn_deg * 2.0),
        zigzag_turn_sum_deg=max(90.0, neighbor_max_turn_deg),
        zigzag_direction_change_max_deg=max(30.0, near_max_turn_deg * 1.75),
        zigzag_max_window_length_m=max(coverage_width_m * 3.0, resolution_m * 8.0),
        long_jump_threshold_m=max(fallback_relax_dist_m, coverage_width_m * 3.0),
        threshold_source="planner_params.turn_constraint_and_coverage_width",
    )


def _resample_path(poses: list[Pose], step_px: float) -> list[Pose]:
    samples: list[Pose] = []
    for start, end in zip(poses[:-1], poses[1:]):
        dx = end.x - start.x
        dy = end.y - start.y
        distance = math.hypot(dx, dy)
        if distance <= 1e-6:
            continue
        steps = max(1, int(math.ceil(distance / step_px)))
        theta = math.atan2(dy, dx)
        for offset in range(steps):
            ratio = offset / steps
            samples.append(
                Pose(
                    x=start.x + dx * ratio,
                    y=start.y + dy * ratio,
                    theta=theta,
                    source_index=start.source_index,
                )
            )
    samples.append(poses[-1])
    return samples


def _local_to_image(pose: Pose, local_x_px: float, local_y_px: float) -> tuple[float, float]:
    forward = np.array([math.cos(pose.theta), math.sin(pose.theta)], dtype=np.float64)
    right = np.array([-math.sin(pose.theta), math.cos(pose.theta)], dtype=np.float64)
    point = np.array([pose.x, pose.y], dtype=np.float64) + local_x_px * right + local_y_px * forward
    return float(point[0]), float(point[1])


def _body_polygon_px(pose: Pose, geometry: GeometryConfig, resolution_m: float) -> np.ndarray:
    left = -geometry.rear_axle_to_left_m / resolution_m
    right = geometry.rear_axle_to_right_m / resolution_m
    rear = -geometry.rear_axle_to_rear_m / resolution_m
    front = geometry.rear_axle_to_front_m / resolution_m
    corners = (
        (left, rear),
        (right, rear),
        (right, front),
        (left, front),
    )
    return np.array([_local_to_image(pose, x, y) for x, y in corners], dtype=np.float32)


def _squeegee_points_px(pose: Pose, geometry: GeometryConfig, resolution_m: float) -> np.ndarray:
    xs = np.linspace(geometry.squeegee_left_m, geometry.squeegee_right_m, 9)
    normalized = (xs - geometry.squeegee_left_m) / (geometry.squeegee_right_m - geometry.squeegee_left_m)
    ys = geometry.squeegee_y_m - geometry.squeegee_arc_depth_m * np.sin(np.pi * normalized)
    points = [_local_to_image(pose, float(x / resolution_m), float(y / resolution_m)) for x, y in zip(xs, ys)]
    return np.array(points, dtype=np.int32)


def _brush_center_px(pose: Pose, center_m: tuple[float, float], resolution_m: float) -> tuple[int, int]:
    x, y = _local_to_image(pose, center_m[0] / resolution_m, center_m[1] / resolution_m)
    return int(round(x)), int(round(y))


def _polygon_roi(poly: np.ndarray, shape: tuple[int, int]) -> tuple[slice, slice, np.ndarray] | None:
    height, width = shape
    x, y, w, h = cv2.boundingRect(np.round(poly).astype(np.int32))
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(width, x + w)
    y1 = min(height, y + h)
    if x0 >= x1 or y0 >= y1:
        return None
    local_poly = np.round(poly).astype(np.int32) - np.array([x0, y0], dtype=np.int32)
    mask = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    cv2.fillConvexPoly(mask, local_poly, 255)
    return slice(y0, y1), slice(x0, x1), mask


def _diagnose_body(
    samples: list[Pose],
    free_mask: np.ndarray,
    geometry: GeometryConfig,
    resolution_m: float,
) -> tuple[np.ndarray, list[dict[str, Any]], list[dict[str, Any]]]:
    height, width = free_mask.shape
    distance_px = cv2.distanceTransform((free_mask > 0).astype(np.uint8), cv2.DIST_L2, 3)
    body_sweep = np.zeros_like(free_mask, dtype=np.uint8)
    collision_events: list[dict[str, Any]] = []
    tight_events: list[dict[str, Any]] = []
    clearance_warning_px = max(1.0, geometry.clearance_warning_m / resolution_m)

    # 风险判定不需要每一个插值点都画出事件，采样间隔控制可读性和运行时间。
    for sample_id, pose in enumerate(samples):
        poly = _body_polygon_px(pose, geometry, resolution_m)
        cv2.fillConvexPoly(body_sweep, np.round(poly).astype(np.int32), 255)
        roi = _polygon_roi(poly, (height, width))
        if roi is None:
            collision_events.append(_event_dict("collision", pose, poly, 0.0))
            continue
        ys, xs, mask = roi
        inside = mask > 0
        if not np.any(inside):
            continue
        free_values = free_mask[ys, xs][inside]
        min_clearance_px = float(np.min(distance_px[ys, xs][inside]))
        event = _event_dict(
            "collision" if np.any(free_values == 0) else "tight",
            pose,
            poly,
            min_clearance_px * resolution_m,
        )
        if np.any(free_values == 0):
            collision_events.append(event)
        elif min_clearance_px <= clearance_warning_px:
            tight_events.append(event)
    return body_sweep, collision_events, tight_events


def _event_dict(kind: str, pose: Pose, poly: np.ndarray, clearance_m: float) -> dict[str, Any]:
    return {
        "kind": kind,
        "path_index": int(pose.source_index),
        "x": float(pose.x),
        "y": float(pose.y),
        "theta": float(pose.theta),
        "clearance_m": float(clearance_m),
        "body_polygon": [[float(x), float(y)] for x, y in poly.tolist()],
    }


def _diagnose_cleaning(
    samples: list[Pose],
    shape: tuple[int, int],
    geometry: GeometryConfig,
    resolution_m: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    brush_mask = np.zeros(shape, dtype=np.uint8)
    squeegee_mask = np.zeros(shape, dtype=np.uint8)
    brush_radius_px = max(1, int(round(geometry.brush_radius_m / resolution_m)))
    squeegee_thickness_px = max(1, int(round(geometry.squeegee_effective_width_m / resolution_m)))

    for pose in samples:
        cv2.circle(brush_mask, _brush_center_px(pose, geometry.left_brush_center_m, resolution_m), brush_radius_px, 255, -1)
        cv2.circle(brush_mask, _brush_center_px(pose, geometry.right_brush_center_m, resolution_m), brush_radius_px, 255, -1)
        cv2.polylines(
            squeegee_mask,
            [_squeegee_points_px(pose, geometry, resolution_m)],
            isClosed=False,
            color=255,
            thickness=squeegee_thickness_px,
            lineType=cv2.LINE_AA,
        )
    cleaning = cv2.bitwise_or(brush_mask, squeegee_mask)
    return brush_mask, squeegee_mask, cleaning


def _shortest_yaw_steps(start_deg: float, end_deg: float, max_step_deg: float) -> list[float]:
    delta = normalize_angle_deg(float(end_deg) - float(start_deg))
    step_count = max(1, int(math.ceil(abs(delta) / max(1e-6, max_step_deg))))
    return [math.radians(float(start_deg) + delta * idx / step_count) for idx in range(step_count + 1)]


def _diagnose_turn_swept(
    path: list[Pose],
    windows: list[dict[str, Any]],
    free_mask: np.ndarray,
    geometry: GeometryConfig,
    resolution_m: float,
) -> tuple[np.ndarray, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """对需要转弯检查的局部窗口做 yaw 插值 swept footprint 诊断。"""

    body_turn_sweep = np.zeros_like(free_mask, dtype=np.uint8)
    distance_px = cv2.distanceTransform((free_mask > 0).astype(np.uint8), cv2.DIST_L2, 3)
    clearance_warning_px = max(1.0, geometry.clearance_warning_m / resolution_m)
    footprint_radius_m = math.hypot(
        max(geometry.rear_axle_to_left_m, geometry.rear_axle_to_right_m),
        max(geometry.rear_axle_to_front_m, geometry.rear_axle_to_rear_m),
    )
    max_yaw_step_deg = math.degrees(float(resolution_m) / max(footprint_radius_m, resolution_m))
    max_yaw_step_deg = max(2.0, min(12.0, max_yaw_step_deg))

    collision_by_window: dict[int, dict[str, Any]] = {}
    tight_by_window: dict[int, dict[str, Any]] = {}
    yaw_sample_count = 0
    for window in windows:
        center_index = int(window.get("center_index", -1))
        if center_index < 0 or center_index >= len(path):
            continue
        center_pose = path[center_index]
        yaws = _shortest_yaw_steps(
            float(window.get("entry_heading_deg", 0.0)),
            float(window.get("exit_heading_deg", 0.0)),
            max_yaw_step_deg,
        )
        for yaw in yaws:
            yaw_sample_count += 1
            pose = Pose(center_pose.x, center_pose.y, yaw, center_pose.source_index)
            poly = _body_polygon_px(pose, geometry, resolution_m)
            cv2.fillConvexPoly(body_turn_sweep, np.round(poly).astype(np.int32), 255)
            roi = _polygon_roi(poly, free_mask.shape)
            if roi is None:
                event = _event_dict("collision", pose, poly, 0.0)
            else:
                ys, xs, mask = roi
                inside = mask > 0
                free_values = free_mask[ys, xs][inside]
                min_clearance_px = float(np.min(distance_px[ys, xs][inside])) if np.any(inside) else 0.0
                event = _event_dict(
                    "collision" if np.any(free_values == 0) else "tight",
                    pose,
                    poly,
                    min_clearance_px * resolution_m,
                )
            event.update(
                {
                    "window_id": int(window.get("window_id", -1)),
                    "window_start_index": int(window.get("window_start_index", center_index)),
                    "window_end_index": int(window.get("window_end_index", center_index)),
                    "center_index": center_index,
                    "risk_reason": list(window.get("risk_reason", [])),
                    "entry_heading_deg": float(window.get("entry_heading_deg", 0.0)),
                    "exit_heading_deg": float(window.get("exit_heading_deg", 0.0)),
                }
            )
            window_key = (
                int(event["window_start_index"]),
                int(event["center_index"]),
                int(event["window_end_index"]),
                int(window.get("window_size", window.get("representative_window_size", 0))),
            )
            if event["kind"] == "collision":
                collision_by_window.setdefault(window_key, event)
                tight_by_window.pop(window_key, None)
                break
            if event["clearance_m"] <= geometry.clearance_warning_m and window_key not in collision_by_window:
                tight_by_window.setdefault(window_key, event)

    meta = {
        "yaw_source": "estimated_from_path_entry_exit_heading",
        "motion_model_assumption": "reference_point_in_place_yaw_interpolation_for_turn_windows",
        "max_yaw_step_deg": float(max_yaw_step_deg),
        "yaw_sample_count": int(yaw_sample_count),
        "checked_window_count": int(len(windows)),
    }
    return body_turn_sweep, list(collision_by_window.values()), list(tight_by_window.values()), meta


def _aggregate_turn_events_by_merged_windows(
    events: list[dict[str, Any]],
    merged_windows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把 raw candidate 事件聚合到合并窗口，避免同一物理风险重复计数。"""

    aggregated: dict[int, dict[str, Any]] = {}
    for event in events:
        event_start = int(event.get("window_start_index", event.get("center_index", -1)))
        event_end = int(event.get("window_end_index", event.get("center_index", -1)))
        for window in merged_windows:
            window_id = int(window.get("window_id", -1))
            window_start = int(window.get("window_start_index", -1))
            window_end = int(window.get("window_end_index", -1))
            if event_start <= window_end and event_end >= window_start:
                current = aggregated.get(window_id)
                if current is None or float(event.get("clearance_m", 0.0)) < float(current.get("clearance_m", 0.0)):
                    item = dict(event)
                    item["merged_window_id"] = window_id
                    item["merged_window_start_index"] = window_start
                    item["merged_window_end_index"] = window_end
                    aggregated[window_id] = item
                break
    return list(aggregated.values())


def _exclude_tight_windows_with_collision(
    tight_events: list[dict[str, Any]],
    collision_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    collision_window_ids = {int(event.get("merged_window_id", -1)) for event in collision_events}
    return [event for event in tight_events if int(event.get("merged_window_id", -1)) not in collision_window_ids]


def _centerline_buffer(path: list[Pose], shape: tuple[int, int], thickness_px: int) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    points = np.array([[int(round(p.x)), int(round(p.y))] for p in path], dtype=np.int32)
    if len(points) >= 2:
        cv2.polylines(mask, [points], isClosed=False, color=255, thickness=max(1, thickness_px), lineType=cv2.LINE_AA)
    return mask


def _ratio(mask: np.ndarray, target: np.ndarray) -> float:
    target_bool = target > 0
    total = int(np.count_nonzero(target_bool))
    if total == 0:
        return 0.0
    return float(np.count_nonzero((mask > 0) & target_bool) / total)


def _crop_bounds(region_mask: np.ndarray, margin: int = 90) -> tuple[int, int, int, int]:
    ys, xs = np.where(region_mask > 0)
    if len(xs) == 0:
        height, width = region_mask.shape
        return 0, 0, width, height
    height, width = region_mask.shape
    x0 = max(0, int(xs.min()) - margin)
    y0 = max(0, int(ys.min()) - margin)
    x1 = min(width, int(xs.max()) + margin)
    y1 = min(height, int(ys.max()) + margin)
    return x0, y0, x1, y1


def _base_canvas(free_mask: np.ndarray, target_mask: np.ndarray) -> np.ndarray:
    canvas = np.zeros((*free_mask.shape, 3), dtype=np.uint8)
    canvas[free_mask > 0] = (236, 236, 236)
    canvas[free_mask == 0] = (26, 26, 26)
    target = target_mask > 0
    canvas[target] = (205, 235, 205)
    return canvas


def _paint_mask(image: np.ndarray, mask: np.ndarray, color: tuple[int, int, int]) -> None:
    active = mask > 0
    if np.any(active):
        image[active] = color


def _draw_path(image: np.ndarray, path: list[Pose], color: tuple[int, int, int], thickness: int = 2) -> None:
    points = np.array([[int(round(p.x)), int(round(p.y))] for p in path], dtype=np.int32)
    if len(points) >= 2:
        cv2.polylines(image, [points], isClosed=False, color=color, thickness=thickness, lineType=cv2.LINE_AA)


def _draw_dashed_polyline(
    image: np.ndarray,
    points: np.ndarray,
    color: tuple[int, int, int],
    thickness: int = 2,
    dash_px: float = 10.0,
    gap_px: float = 7.0,
    closed: bool = True,
) -> None:
    pts = points.astype(np.float64)
    if closed and len(pts) > 1:
        pts = np.vstack([pts, pts[0]])
    for start, end in zip(pts[:-1], pts[1:]):
        vector = end - start
        length = float(np.linalg.norm(vector))
        if length <= 1e-6:
            continue
        direction = vector / length
        cursor = 0.0
        while cursor < length:
            segment_end = min(length, cursor + dash_px)
            a = start + direction * cursor
            b = start + direction * segment_end
            cv2.line(
                image,
                (int(round(a[0])), int(round(a[1]))),
                (int(round(b[0])), int(round(b[1]))),
                color,
                thickness,
                lineType=cv2.LINE_AA,
            )
            cursor += dash_px + gap_px


def _draw_events(
    image: np.ndarray,
    events: Iterable[dict[str, Any]],
    max_items: int = 220,
) -> None:
    for count, event in enumerate(events):
        if count >= max_items:
            break
        poly = np.array(event["body_polygon"], dtype=np.int32)
        if event.get("kind") == "tight":
            _draw_dashed_polyline(image, poly, (255, 0, 255), thickness=2)
            cv2.circle(image, (int(round(event["x"])), int(round(event["y"]))), 4, (255, 0, 255), -1)
        else:
            cv2.polylines(image, [poly], isClosed=True, color=(0, 0, 255), thickness=2, lineType=cv2.LINE_AA)
            center = (int(round(event["x"])), int(round(event["y"])))
            cv2.circle(image, center, 5, (0, 0, 255), -1)
            cv2.drawMarker(image, center, (0, 0, 255), markerType=cv2.MARKER_TILTED_CROSS, markerSize=12, thickness=2)


def _draw_event_markers(
    image: np.ndarray,
    events: Iterable[dict[str, Any]],
    max_items: int = 260,
) -> None:
    for count, event in enumerate(events):
        if count >= max_items:
            break
        center = (int(round(event["x"])), int(round(event["y"])))
        color = (255, 0, 255) if event.get("kind") == "tight" else (0, 0, 255)
        cv2.circle(image, center, 6, color, -1, lineType=cv2.LINE_AA)
        cv2.circle(image, center, 10, color, 2, lineType=cv2.LINE_AA)


def _resize_with_title(
    image: np.ndarray,
    title: str,
    lines: list[str],
    output_path: Path,
    max_visual_size: int,
) -> None:
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    height, width = rgb.shape[:2]
    scale = min(1.0, max_visual_size / max(height, width))
    if scale < 1.0:
        rgb = cv2.resize(rgb, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
    title_height = 170 + 26 * max(0, len(lines) - 3)
    canvas = Image.new("RGB", (rgb.shape[1], rgb.shape[0] + title_height), (250, 250, 250))
    canvas.paste(Image.fromarray(rgb), (0, title_height))
    draw = ImageDraw.Draw(canvas)
    font_title = ImageFont.truetype(DEFAULT_FONT, 28)
    font = ImageFont.truetype(DEFAULT_FONT, 20)
    draw.text((18, 14), title, font=font_title, fill=(20, 20, 20))
    y = 58
    for line in lines:
        draw.text((20, y), line, font=font, fill=(35, 35, 35))
        y += 26
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def _extract_crop(image: np.ndarray, bounds: tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = bounds
    return image[y0:y1, x0:x1].copy()


def _component_count(mask: np.ndarray, min_area: int = 12) -> int:
    count, labels, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    _ = labels
    return int(sum(1 for idx in range(1, count) if int(stats[idx, cv2.CC_STAT_AREA]) >= min_area))


def _event_clusters(events: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    min_distance = 90.0
    for event in events:
        if all(math.hypot(event["x"] - item["x"], event["y"] - item["y"]) >= min_distance for item in selected):
            selected.append(event)
        if len(selected) >= limit:
            break
    return selected


def _make_zoom_montage(
    base: np.ndarray,
    path: list[Pose],
    events: list[dict[str, Any]],
    output_path: Path,
    max_visual_size: int,
) -> None:
    selected = _event_clusters(events, limit=6)
    if not selected:
        selected = []
    tile_size = 420
    title_height = 130
    cols = 3
    rows = max(1, math.ceil(max(1, len(selected)) / cols))
    montage = np.full((rows * tile_size, cols * tile_size, 3), 245, dtype=np.uint8)
    if not selected:
        empty = base.copy()
        _draw_path(empty, path, (255, 90, 0), 2)
        h, w = empty.shape[:2]
        cx, cy = w // 2, h // 2
        selected = [{"x": cx, "y": cy, "kind": "none", "path_index": 0, "body_polygon": []}]
    for idx, event in enumerate(selected):
        row = idx // cols
        col = idx % cols
        cx = int(round(event["x"]))
        cy = int(round(event["y"]))
        half = 190
        x0 = max(0, cx - half)
        y0 = max(0, cy - half)
        x1 = min(base.shape[1], cx + half)
        y1 = min(base.shape[0], cy + half)
        crop = base[y0:y1, x0:x1].copy()
        _draw_path(crop, [Pose(p.x - x0, p.y - y0, p.theta, p.source_index) for p in path], (255, 90, 0), 2)
        if event.get("body_polygon"):
            shifted = np.array(event["body_polygon"], dtype=np.int32) - np.array([x0, y0], dtype=np.int32)
            cv2.polylines(crop, [shifted], True, (0, 0, 255), 2, lineType=cv2.LINE_AA)
            cv2.circle(crop, (cx - x0, cy - y0), 5, (0, 0, 255), -1)
        crop = cv2.resize(crop, (tile_size, tile_size), interpolation=cv2.INTER_AREA)
        montage[row * tile_size : (row + 1) * tile_size, col * tile_size : (col + 1) * tile_size] = crop
    _resize_with_title(
        montage,
        "局部风险放大图",
        [
            "每个小图围绕一个风险采样点，蓝线是路径，红框是该姿态下车体 footprint。",
            "用途：检查风险点是否确实落在端点、路口、斜插或窄通道附近。",
        ],
        output_path,
        max_visual_size,
    )


def _draw_path_windows(image: np.ndarray, path: list[Pose], windows: list[dict[str, Any]], max_items: int = 500) -> None:
    for window in windows[:max_items]:
        start = max(0, int(window["window_start_index"]))
        end = min(len(path) - 1, int(window["window_end_index"]))
        if end <= start:
            continue
        reasons = set(str(value) for value in window.get("risk_reason", []))
        if "sharp_turn" in reasons:
            color = (0, 0, 255)
            marker = cv2.MARKER_TILTED_CROSS
        elif "short_zigzag" in reasons:
            color = (255, 0, 255)
            marker = cv2.MARKER_DIAMOND
        elif "direction_change" in reasons:
            color = (0, 255, 255)
            marker = cv2.MARKER_CROSS
        else:
            color = (0, 165, 255)
            marker = cv2.MARKER_STAR
        center_index = int(window.get("center_index", (start + end) // 2))
        if 0 <= center_index < len(path):
            center = (int(round(path[center_index].x)), int(round(path[center_index].y)))
            cv2.drawMarker(image, center, color, markerType=marker, markerSize=14, thickness=2)
            cv2.circle(
                image,
                center,
                8,
                color,
                2,
                lineType=cv2.LINE_AA,
            )


def run_diagnostic(args: argparse.Namespace) -> Path:
    run_dir = args.run_dir.expanduser().resolve()
    prepare_dir = args.prepare_dir.expanduser().resolve() if args.prepare_dir else run_dir.parent / "prepare_map"
    if not run_dir.is_dir():
        raise FileNotFoundError(run_dir)
    free_mask_path = prepare_dir / "02_free_mask.png"
    prepared_map_path = prepare_dir / "05_prepared_map.png"
    region_mask_path = run_dir / "region_mask.png"
    path_path = run_dir / "path_pixels.json"
    for path in (free_mask_path, prepared_map_path, region_mask_path, path_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    free_mask = cv2.imread(str(free_mask_path), cv2.IMREAD_GRAYSCALE)
    prepared_map = cv2.imread(str(prepared_map_path), cv2.IMREAD_GRAYSCALE)
    region_mask = cv2.imread(str(region_mask_path), cv2.IMREAD_GRAYSCALE)
    if free_mask is None or prepared_map is None or region_mask is None:
        raise ValueError("failed to load diagnostic masks")
    if free_mask.shape != region_mask.shape:
        raise ValueError(f"mask shape mismatch: free={free_mask.shape}, region={region_mask.shape}")

    path = _load_path(path_path)
    resolution_m = _metadata_resolution(run_dir)
    coverage_width_px = _coverage_width_px(run_dir, resolution_m)
    coverage_width_m = float(coverage_width_px * resolution_m)
    geometry = GeometryConfig()
    sample_step_px = 1.0
    samples = _resample_path(path, sample_step_px)

    window_config = _path_window_config(run_dir, resolution_m, coverage_width_m)
    path_points = [(pose.x, pose.y) for pose in path]
    path_window_diagnostics = detect_path_windows(path_points, window_config)
    path_windows = list(path_window_diagnostics["windows"])
    turn_check_windows = list(path_window_diagnostics["candidate_windows"])
    turn_sweep, turn_collision_events, turn_tight_events, turn_meta = _diagnose_turn_swept(
        path,
        turn_check_windows,
        free_mask,
        geometry,
        resolution_m,
    )
    turn_collision_windows = _aggregate_turn_events_by_merged_windows(turn_collision_events, path_windows)
    turn_tight_windows = _aggregate_turn_events_by_merged_windows(turn_tight_events, path_windows)
    turn_tight_windows = _exclude_tight_windows_with_collision(turn_tight_windows, turn_collision_windows)
    body_sweep, collision_events, tight_events = _diagnose_body(samples, free_mask, geometry, resolution_m)
    brush_mask, squeegee_mask, cleaning_mask = _diagnose_cleaning(samples, free_mask.shape, geometry, resolution_m)
    centerline_mask = _centerline_buffer(path, free_mask.shape, coverage_width_px)

    target_mask = ((region_mask > 0) & (prepared_map > 0)).astype(np.uint8) * 255
    cleaning_gap = ((target_mask > 0) & (cleaning_mask == 0)).astype(np.uint8) * 255
    centerline_gap = ((target_mask > 0) & (centerline_mask == 0)).astype(np.uint8) * 255

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_dir = args.output_root.expanduser().resolve() / f"run_{timestamp}_geometry_readonly_diagnostic" / args.case_name
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "path_window_diagnostics.json").write_text(
        json.dumps(path_window_diagnostics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    pose_sampling_policy = {
        "translation_sample_step_px": float(sample_step_px),
        "translation_sample_step_m": float(sample_step_px * resolution_m),
        "yaw_source": turn_meta["yaw_source"],
        "motion_model_assumption": turn_meta["motion_model_assumption"],
        "max_yaw_step_deg": float(turn_meta["max_yaw_step_deg"]),
        "yaw_sample_count": int(turn_meta["yaw_sample_count"]),
        "translation_sample_count": int(len(samples)),
    }
    (output_dir / "pose_sampling_meta.json").write_text(
        json.dumps(pose_sampling_policy, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    bounds = _crop_bounds(target_mask)
    base = _base_canvas(free_mask, target_mask)
    x0, y0, x1, y1 = bounds

    overview = base.copy()
    _draw_path(overview, path, (255, 90, 0), 2)
    _draw_event_markers(overview, tight_events, max_items=180)
    _draw_event_markers(overview, collision_events, max_items=180)
    _draw_event_markers(overview, turn_tight_events, max_items=120)
    _draw_event_markers(overview, turn_collision_events, max_items=120)
    _resize_with_title(
        _extract_crop(overview, bounds),
        "只读几何诊断总览",
        [
            f"case={args.case_name}  path_points={len(path)}  samples={len(samples)}  resolution={resolution_m:.3f}m/px",
            "蓝线=原路径  红点/叉=车体硬碰撞  洋红点=紧贴风险；总览不叠加清扫覆盖，避免遮挡。",
            f"body_collision={len(collision_events)}  body_tight={len(tight_events)}  turn_collision={len(turn_collision_windows)}  turn_tight={len(turn_tight_windows)}",
        ],
        output_dir / "00_只读几何诊断总览.png",
        args.max_visual_size,
    )

    body_view = base.copy()
    _draw_path(body_view, path, (255, 90, 0), 2)
    _draw_events(body_view, tight_events, max_items=240)
    _draw_events(body_view, collision_events, max_items=240)
    _resize_with_title(
        _extract_crop(body_view, bounds),
        "车体平移 swept footprint 风险",
        [
            "蓝线=原路径；红色实线框/叉=硬碰撞采样姿态；洋红虚线框=紧贴风险采样姿态。",
            "这张图只看刚性车体，不看盘刷和刮水器覆盖。",
            f"body_swept_collision_count={len(collision_events)}  body_tight_clearance_count={len(tight_events)}",
        ],
        output_dir / "01_车体扫掠风险.png",
        args.max_visual_size,
    )

    turn_view = base.copy()
    _draw_path(turn_view, path, (255, 90, 0), 2)
    _draw_events(turn_view, turn_tight_windows, max_items=240)
    _draw_events(turn_view, turn_collision_windows, max_items=240)
    _resize_with_title(
        _extract_crop(turn_view, bounds),
        "转弯 yaw 插值 swept footprint 风险",
        [
            "蓝线=原路径；只在 3/5/7 点窗口触发的转弯位置做 yaw 插值检查。",
            "红色实线框/叉=转弯扫掠硬碰撞；洋红虚线框=转弯扫掠紧贴风险。",
            f"turn_swept_collision_count={len(turn_collision_windows)}  turn_swept_tight_clearance_count={len(turn_tight_windows)}",
        ],
        output_dir / "02_转弯yaw扫掠风险.png",
        args.max_visual_size,
    )

    window_view = base.copy()
    _draw_path(window_view, path, (255, 90, 0), 2)
    _draw_path_windows(window_view, path, path_windows)
    _resize_with_title(
        _extract_crop(window_view, bounds),
        "3/5/7 点转角窗口诊断",
        [
            "蓝线=原路径；红=单点急转；洋红=短距离连续折线；黄=局部方向突变。",
            "窗口只用于触发诊断和后续归因，不代表要修改路径。",
            f"sharp_turn={path_window_diagnostics['sharp_turn_window_count']}  zigzag={path_window_diagnostics['continuous_zigzag_count']}  direction_change={path_window_diagnostics['direction_change_window_count']}",
        ],
        output_dir / "03_转角窗口诊断.png",
        args.max_visual_size,
    )

    brush_view = base.copy()
    _paint_mask(brush_view, brush_mask, (80, 210, 80))
    _draw_path(brush_view, path, (255, 90, 0), 2)
    _resize_with_title(
        _extract_crop(brush_view, bounds),
        "盘刷覆盖",
        [
            "绿色区域=盘刷 footprint 扫过区域；蓝线=原路径。",
            "该图单独展示盘刷，避免与刮水器和漏扫图层混色。",
            f"brush_coverage_ratio={_ratio(brush_mask, target_mask):.4f}",
        ],
        output_dir / "04_盘刷覆盖.png",
        args.max_visual_size,
    )

    squeegee_view = base.copy()
    _paint_mask(squeegee_view, squeegee_mask, (255, 180, 40))
    _draw_path(squeegee_view, path, (255, 90, 0), 2)
    _resize_with_title(
        _extract_crop(squeegee_view, bounds),
        "刮水器覆盖",
        [
            "浅蓝区域=刮水器 footprint 扫过区域；蓝线=原路径。",
            "刮水器当前按软覆盖诊断，不参与刚性碰撞。",
            f"squeegee_coverage_ratio={_ratio(squeegee_mask, target_mask):.4f}",
        ],
        output_dir / "05_刮水器覆盖.png",
        args.max_visual_size,
    )

    gap_view = base.copy()
    _paint_mask(gap_view, cleaning_gap, (0, 255, 255))
    _draw_path(gap_view, path, (255, 90, 0), 2)
    _resize_with_title(
        _extract_crop(gap_view, bounds),
        "真实清扫 footprint 漏扫",
        [
            "黄色区域=目标区未被盘刷或刮水器覆盖；蓝线=原路径。",
            "该图用于判断中心线 buffer 覆盖率是否高估真实清扫覆盖。",
            f"cleaning_footprint_coverage_ratio={_ratio(cleaning_mask, target_mask):.4f}  gap_area_m2={np.count_nonzero(cleaning_gap > 0) * resolution_m * resolution_m:.3f}",
        ],
        output_dir / "06_真实清扫漏扫.png",
        args.max_visual_size,
    )

    gap_compare = base.copy()
    _paint_mask(gap_compare, centerline_gap, (0, 255, 255))
    _paint_mask(gap_compare, cleaning_gap, (0, 0, 255))
    _draw_path(gap_compare, path, (255, 90, 0), 2)
    _resize_with_title(
        _extract_crop(gap_compare, bounds),
        "中心线 buffer 与真实清扫 footprint 漏扫对比",
        [
            "黄色=中心线 buffer 判断的漏扫；红色=真实清扫 footprint 判断的漏扫；红色覆盖黄色时以真实清扫漏扫为准。",
            "红色明显多于黄色时，说明只看 coverage_width_m buffer 会高估覆盖。",
            f"buffer={_ratio(centerline_mask, target_mask):.4f}  cleaning={_ratio(cleaning_mask, target_mask):.4f}  delta={_ratio(centerline_mask, target_mask)-_ratio(cleaning_mask, target_mask):.4f}",
        ],
        output_dir / "07_buffer与真实清扫覆盖差异.png",
        args.max_visual_size,
    )

    risk_base = _extract_crop(base, bounds)
    shifted_path = [Pose(p.x - x0, p.y - y0, p.theta, p.source_index) for p in path]
    shifted_events: list[dict[str, Any]] = []
    for event in collision_events[:300] + tight_events[:300] + turn_collision_windows[:200] + turn_tight_windows[:200]:
        shifted = dict(event)
        shifted["x"] = float(event["x"] - x0)
        shifted["y"] = float(event["y"] - y0)
        shifted["body_polygon"] = [[float(px - x0), float(py - y0)] for px, py in event["body_polygon"]]
        shifted_events.append(shifted)
    _make_zoom_montage(
        risk_base,
        shifted_path,
        shifted_events,
        output_dir / "08_风险窗口放大.png",
        args.max_visual_size,
    )

    summary = {
        "version": "geometry_coverage_readonly_diagnostic.v1",
        "source_run_dir": str(run_dir),
        "prepare_dir": str(prepare_dir),
        "case_name": args.case_name,
        "diagnostic_scope": "read_only_no_path_modification",
        "geometry_source": "sample_geometry_until_robot_calibration_is_confirmed",
        "geometry": geometry.__dict__,
        "collision_mask_policy": "free_mask_zero_is_obstacle",
        "target_mask_policy": "region_mask AND prepared_map",
        "pose_sampling_policy": pose_sampling_policy,
        "resolution_m": resolution_m,
        "coverage_width_px": coverage_width_px,
        "coverage_width_m": coverage_width_m,
        "target_definition": "region_mask AND prepared_map",
        "target_area_m2": float(np.count_nonzero(target_mask > 0) * resolution_m * resolution_m),
        "path_point_count": len(path),
        "sample_count": len(samples),
        "body_swept_collision_count": len(collision_events),
        "body_tight_clearance_count": len(tight_events),
        "turn_swept_collision_count": len(turn_collision_windows),
        "turn_swept_tight_clearance_count": len(turn_tight_windows),
        "turn_swept_collision_candidate_event_count": len(turn_collision_events),
        "turn_swept_tight_clearance_candidate_event_count": len(turn_tight_events),
        "sharp_turn_window_count": int(path_window_diagnostics["sharp_turn_window_count"]),
        "continuous_zigzag_count": int(path_window_diagnostics["continuous_zigzag_count"]),
        "direction_change_window_count": int(path_window_diagnostics["direction_change_window_count"]),
        "path_window_candidate_count": int(path_window_diagnostics["candidate_window_count"]),
        "path_window_merged_count": int(path_window_diagnostics["merged_window_count"]),
        "cleaning_footprint_coverage_ratio": _ratio(cleaning_mask, target_mask),
        "cleaning_footprint_gap_area_m2": float(np.count_nonzero(cleaning_gap > 0) * resolution_m * resolution_m),
        "brush_coverage_ratio": _ratio(brush_mask, target_mask),
        "squeegee_coverage_ratio": _ratio(squeegee_mask, target_mask),
        "buffer_coverage_ratio": _ratio(centerline_mask, target_mask),
        "buffer_coverage_vs_cleaning_coverage_delta": _ratio(centerline_mask, target_mask) - _ratio(cleaning_mask, target_mask),
        "cleaning_gap_component_count": _component_count(cleaning_gap),
        "centerline_gap_component_count": _component_count(centerline_gap),
        "collision_events_preview": collision_events[:50],
        "tight_events_preview": tight_events[:50],
        "turn_collision_events_preview": turn_collision_windows[:50],
        "turn_tight_events_preview": turn_tight_windows[:50],
        "turn_collision_candidate_events_preview": turn_collision_events[:50],
        "turn_tight_candidate_events_preview": turn_tight_events[:50],
        "artifacts": {
            "overview": str(output_dir / "00_只读几何诊断总览.png"),
            "body_swept_risk": str(output_dir / "01_车体扫掠风险.png"),
            "turn_swept_risk": str(output_dir / "02_转弯yaw扫掠风险.png"),
            "path_window_diagnostics": str(output_dir / "03_转角窗口诊断.png"),
            "brush_coverage": str(output_dir / "04_盘刷覆盖.png"),
            "squeegee_coverage": str(output_dir / "05_刮水器覆盖.png"),
            "cleaning_gap": str(output_dir / "06_真实清扫漏扫.png"),
            "buffer_vs_cleaning": str(output_dir / "07_buffer与真实清扫覆盖差异.png"),
            "risk_zoom": str(output_dir / "08_风险窗口放大.png"),
            "path_window_json": str(output_dir / "path_window_diagnostics.json"),
            "pose_sampling_meta": str(output_dir / "pose_sampling_meta.json"),
        },
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_dir)
    return output_dir


def main() -> None:
    try:
        run_diagnostic(parse_args())
    except Exception as exc:  # pragma: no cover - command-line failure path
        print(f"ERROR: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
