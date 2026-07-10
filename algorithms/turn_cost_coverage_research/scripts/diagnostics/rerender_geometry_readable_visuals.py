#!/usr/bin/env python3
"""把几何只读诊断结果重绘成高倍率、低遮挡的可读图。"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.turn_cost_coverage_research.scripts.diagnostics.run_geometry_coverage_readonly_diagnostic import (
    DEFAULT_FONT,
    GeometryConfig,
    Pose,
    _aggregate_turn_events_by_merged_windows,
    _base_canvas,
    _centerline_buffer,
    _coverage_width_px,
    _crop_bounds,
    _diagnose_body,
    _diagnose_cleaning,
    _diagnose_turn_swept,
    _exclude_tight_windows_with_collision,
    _load_path,
    _metadata_resolution,
    _path_window_config,
    _read_json,
    _resample_path,
)
from algorithms.turn_cost_coverage_research.src.diagnostics.path_window_diagnostics import detect_path_windows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagnostic_dirs", nargs="+", type=Path, help="已有几何只读诊断 case 目录。")
    parser.add_argument("--scale", type=int, default=8, help="底图放大倍率。")
    parser.add_argument("--path-width", type=int, default=2, help="放大后原路径线宽，默认保持细线。")
    parser.add_argument("--marker-radius", type=int, default=5, help="风险中心空心圈半径。")
    parser.add_argument("--max-body-events", type=int, default=180, help="风险概览最多绘制的平移风险事件数。")
    return parser.parse_args()


def _load_summary(case_dir: Path) -> dict[str, Any]:
    summary_path = case_dir / "summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(summary_path)
    return _read_json(summary_path)


def _load_case(summary: dict[str, Any]) -> tuple[Path, Path, list[Pose], np.ndarray, np.ndarray, np.ndarray, float, int]:
    run_dir = Path(summary["source_run_dir"])
    prepare_dir = Path(summary["prepare_dir"])
    path = _load_path(run_dir / "path_pixels.json")
    free_mask = cv2.imread(str(prepare_dir / "02_free_mask.png"), cv2.IMREAD_GRAYSCALE)
    prepared_map = cv2.imread(str(prepare_dir / "05_prepared_map.png"), cv2.IMREAD_GRAYSCALE)
    region_mask = cv2.imread(str(run_dir / "region_mask.png"), cv2.IMREAD_GRAYSCALE)
    if free_mask is None or prepared_map is None or region_mask is None:
        raise ValueError(f"failed to load masks for {run_dir}")
    resolution_m = _metadata_resolution(run_dir)
    coverage_width_px = _coverage_width_px(run_dir, resolution_m)
    return run_dir, prepare_dir, path, free_mask, prepared_map, region_mask, resolution_m, coverage_width_px


def _scale_image(image: np.ndarray, scale: int) -> np.ndarray:
    return cv2.resize(image, (image.shape[1] * scale, image.shape[0] * scale), interpolation=cv2.INTER_NEAREST)


def _shift_scale_point(x: float, y: float, bounds: tuple[int, int, int, int], scale: int) -> tuple[int, int]:
    x0, y0, _, _ = bounds
    return int(round((float(x) - x0) * scale)), int(round((float(y) - y0) * scale))


def _draw_path_scaled(
    image: np.ndarray,
    path: list[Pose],
    bounds: tuple[int, int, int, int],
    scale: int,
    width: int,
    color: tuple[int, int, int] = (255, 90, 0),
) -> None:
    points = np.array([_shift_scale_point(p.x, p.y, bounds, scale) for p in path], dtype=np.int32)
    if len(points) >= 2:
        cv2.polylines(image, [points], isClosed=False, color=color, thickness=max(1, width), lineType=cv2.LINE_AA)


def _draw_hollow_marker(
    image: np.ndarray,
    x: float,
    y: float,
    bounds: tuple[int, int, int, int],
    scale: int,
    color: tuple[int, int, int],
    radius: int,
    marker: int | None = None,
) -> None:
    center = _shift_scale_point(x, y, bounds, scale)
    cv2.circle(image, center, radius, color, 1, lineType=cv2.LINE_AA)
    if marker is not None:
        cv2.drawMarker(image, center, color, markerType=marker, markerSize=radius * 2 + 3, thickness=1)


def _draw_event_centers(
    image: np.ndarray,
    events: list[dict[str, Any]],
    bounds: tuple[int, int, int, int],
    scale: int,
    *,
    color: tuple[int, int, int],
    radius: int,
    marker: int | None,
    limit: int,
) -> None:
    for event in _spatially_thin_events(events, min_distance_px=10.0, limit=limit):
        _draw_hollow_marker(image, event["x"], event["y"], bounds, scale, color, radius, marker)


def _spatially_thin_events(
    events: list[dict[str, Any]],
    *,
    min_distance_px: float,
    limit: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for event in events:
        if all(math.hypot(float(event["x"]) - float(item["x"]), float(event["y"]) - float(item["y"])) >= min_distance_px for item in selected):
            selected.append(event)
        if len(selected) >= limit:
            break
    return selected


def _draw_event_boxes(
    image: np.ndarray,
    events: list[dict[str, Any]],
    bounds: tuple[int, int, int, int],
    scale: int,
    *,
    color: tuple[int, int, int],
    limit: int,
    dashed: bool = False,
) -> None:
    for event in events[:limit]:
        points = np.array(
            [_shift_scale_point(x, y, bounds, scale) for x, y in event.get("body_polygon", [])],
            dtype=np.int32,
        )
        if len(points) < 3:
            continue
        if dashed:
            _draw_dashed_polygon(image, points, color)
        else:
            cv2.polylines(image, [points], isClosed=True, color=color, thickness=1, lineType=cv2.LINE_AA)
        _draw_hollow_marker(image, event["x"], event["y"], bounds, scale, color, 4, cv2.MARKER_TILTED_CROSS)


def _draw_dashed_polygon(image: np.ndarray, points: np.ndarray, color: tuple[int, int, int]) -> None:
    pts = np.vstack([points.astype(np.float64), points[0].astype(np.float64)])
    for start, end in zip(pts[:-1], pts[1:]):
        vector = end - start
        length = float(np.linalg.norm(vector))
        if length <= 1e-6:
            continue
        direction = vector / length
        cursor = 0.0
        while cursor < length:
            next_cursor = min(length, cursor + 12.0)
            a = start + direction * cursor
            b = start + direction * next_cursor
            cv2.line(
                image,
                (int(round(a[0])), int(round(a[1]))),
                (int(round(b[0])), int(round(b[1]))),
                color,
                1,
                lineType=cv2.LINE_AA,
            )
            cursor += 20.0


def _draw_window_markers(
    image: np.ndarray,
    path: list[Pose],
    windows: list[dict[str, Any]],
    bounds: tuple[int, int, int, int],
    scale: int,
    radius: int,
) -> None:
    for window in windows:
        center_index = int(window.get("center_index", -1))
        if center_index < 0 or center_index >= len(path):
            continue
        reasons = set(str(value) for value in window.get("risk_reason", []))
        if "sharp_turn" in reasons:
            color = (0, 0, 255)
            marker = cv2.MARKER_TILTED_CROSS
        elif "short_zigzag" in reasons:
            color = (255, 0, 255)
            marker = cv2.MARKER_DIAMOND
        else:
            color = (0, 255, 255)
            marker = cv2.MARKER_CROSS
        pose = path[center_index]
        _draw_hollow_marker(image, pose.x, pose.y, bounds, scale, color, radius, marker)


def _title_canvas(image: np.ndarray, title: str, lines: list[str]) -> Image.Image:
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    title_height = 150 + 28 * max(0, len(lines) - 2)
    canvas = Image.new("RGB", (rgb.shape[1], rgb.shape[0] + title_height), (250, 250, 250))
    canvas.paste(Image.fromarray(rgb), (0, title_height))
    draw = ImageDraw.Draw(canvas)
    font_title = ImageFont.truetype(DEFAULT_FONT, 32)
    font = ImageFont.truetype(DEFAULT_FONT, 22)
    draw.text((18, 14), title, font=font_title, fill=(20, 20, 20))
    y = 62
    for line in lines:
        draw.text((20, y), line, font=font, fill=(35, 35, 35))
        y += 28
    return canvas


def _save(image: np.ndarray, title: str, lines: list[str], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _title_canvas(image, title, lines).save(output_path)


def _clean_legacy_outputs(output_dir: Path) -> None:
    legacy_names = {
        "00_路径优先_8x.png",
        "01_风险概览低遮挡_8x.png",
        "02_转弯yaw风险细框_8x.png",
        "03_转角窗口低遮挡_8x.png",
        "04_漏扫对比_8x.png",
        "05_局部风险窗口拼图_8x.png",
    }
    for name in legacy_names:
        path = output_dir / name
        if path.is_file():
            path.unlink()


def _make_local_montage(
    source_image: np.ndarray,
    events: list[dict[str, Any]],
    bounds: tuple[int, int, int, int],
    scale: int,
    output_path: Path,
    title: str,
) -> None:
    selected = _spatially_thin_events(events, min_distance_px=150.0, limit=6)
    if not selected:
        return
    tile_size = 1500
    half = tile_size // 2
    cols = 3
    rows = int(math.ceil(len(selected) / cols))
    montage = np.full((rows * tile_size, cols * tile_size, 3), 245, dtype=np.uint8)
    for index, event in enumerate(selected):
        cx, cy = _shift_scale_point(event["x"], event["y"], bounds, scale)
        x0 = max(0, cx - half)
        y0 = max(0, cy - half)
        x1 = min(source_image.shape[1], cx + half)
        y1 = min(source_image.shape[0], cy + half)
        crop = source_image[y0:y1, x0:x1].copy()
        if crop.shape[0] != tile_size or crop.shape[1] != tile_size:
            padded = np.full((tile_size, tile_size, 3), 245, dtype=np.uint8)
            padded[: crop.shape[0], : crop.shape[1]] = crop
            crop = padded
        row = index // cols
        col = index % cols
        montage[row * tile_size : (row + 1) * tile_size, col * tile_size : (col + 1) * tile_size] = crop
    _save(
        montage,
        title,
        [
            "每个小图是 8 倍图中的原始像素裁剪，不再整体缩小到全局视野。",
            "用于检查风险标记是否盖住路径，以及局部路径线距和交叉是否能看清。",
        ],
        output_path,
    )


def _render_one(case_dir: Path, scale: int, path_width: int, marker_radius: int, max_body_events: int) -> Path:
    case_dir = case_dir.expanduser().resolve()
    summary = _load_summary(case_dir)
    run_dir, _, path, free_mask, prepared_map, region_mask, resolution_m, coverage_width_px = _load_case(summary)
    geometry = GeometryConfig()
    target_mask = ((region_mask > 0) & (prepared_map > 0)).astype(np.uint8) * 255
    bounds = _crop_bounds(target_mask)
    x0, y0, x1, y1 = bounds
    base = _base_canvas(free_mask, target_mask)[y0:y1, x0:x1]
    base_scaled = _scale_image(base, scale)

    output_dir = case_dir / "可读放大8倍"
    output_dir.mkdir(parents=True, exist_ok=True)
    _clean_legacy_outputs(output_dir)

    samples = _resample_path(path, 1.0)
    body_sweep, body_collision, body_tight = _diagnose_body(samples, free_mask, geometry, resolution_m)
    coverage_width_m = float(coverage_width_px * resolution_m)
    window_config = _path_window_config(run_dir, resolution_m, coverage_width_m)
    path_windows_payload = detect_path_windows([(p.x, p.y) for p in path], window_config)
    merged_windows = list(path_windows_payload["windows"])
    candidate_windows = list(path_windows_payload["candidate_windows"])
    _, turn_collision_raw, turn_tight_raw, _ = _diagnose_turn_swept(
        path,
        candidate_windows,
        free_mask,
        geometry,
        resolution_m,
    )
    turn_collision = _aggregate_turn_events_by_merged_windows(turn_collision_raw, merged_windows)
    turn_tight = _exclude_tight_windows_with_collision(
        _aggregate_turn_events_by_merged_windows(turn_tight_raw, merged_windows),
        turn_collision,
    )
    brush_mask, squeegee_mask, cleaning_mask = _diagnose_cleaning(samples, free_mask.shape, geometry, resolution_m)
    centerline_mask = _centerline_buffer(path, free_mask.shape, coverage_width_px)
    cleaning_gap = ((target_mask > 0) & (cleaning_mask == 0)).astype(np.uint8) * 255
    centerline_gap = ((target_mask > 0) & (centerline_mask == 0)).astype(np.uint8) * 255

    case_name = str(summary.get("case_name", case_dir.name))
    common = [
        f"case={case_name}  scale={scale}x  path_width={path_width}px",
        "底图按比例放大，路径和风险标记保持细线；用于看清路径形态，不改变诊断指标。",
    ]

    path_only = base_scaled.copy()
    _draw_path_scaled(path_only, path, bounds, scale, path_width)
    _save(
        path_only,
        "路径优先图",
        common + ["蓝线=原始路径；不叠加风险标记。"],
        output_dir / "辅助_路径优先_8x.png",
    )

    overview = base_scaled.copy()
    _draw_path_scaled(overview, path, bounds, scale, path_width)
    _draw_event_centers(
        overview,
        body_collision,
        bounds,
        scale,
        color=(0, 0, 255),
        radius=marker_radius,
        marker=cv2.MARKER_TILTED_CROSS,
        limit=max_body_events,
    )
    _draw_event_centers(
        overview,
        body_tight,
        bounds,
        scale,
        color=(255, 0, 255),
        radius=marker_radius,
        marker=None,
        limit=max_body_events,
    )
    _draw_event_centers(
        overview,
        turn_collision,
        bounds,
        scale,
        color=(0, 0, 255),
        radius=marker_radius + 2,
        marker=cv2.MARKER_CROSS,
        limit=120,
    )
    _draw_event_centers(
        overview,
        turn_tight,
        bounds,
        scale,
        color=(255, 0, 255),
        radius=marker_radius + 2,
        marker=cv2.MARKER_CROSS,
        limit=120,
    )
    _save(
        overview,
        "只读几何诊断总览",
        common
        + [
            f"红=硬碰撞中心；洋红=紧贴风险中心；平移风险做空间抽稀，避免盖住路径。body_collision={len(body_collision)} body_tight={len(body_tight)}",
            f"turn_collision={len(turn_collision)} turn_tight={len(turn_tight)}",
        ],
        output_dir / "00_只读几何诊断总览_8x.png",
    )

    body_view = base_scaled.copy()
    body_sweep_crop = _scale_image(body_sweep[y0:y1, x0:x1], scale)
    body_outline = cv2.morphologyEx((body_sweep_crop > 0).astype(np.uint8) * 255, cv2.MORPH_GRADIENT, np.ones((3, 3), dtype=np.uint8))
    body_view[body_outline > 0] = (120, 120, 120)
    _draw_path_scaled(body_view, path, bounds, scale, path_width)
    _draw_event_centers(
        body_view,
        body_collision,
        bounds,
        scale,
        color=(0, 0, 255),
        radius=marker_radius,
        marker=cv2.MARKER_TILTED_CROSS,
        limit=max_body_events,
    )
    _draw_event_centers(
        body_view,
        body_tight,
        bounds,
        scale,
        color=(255, 0, 255),
        radius=marker_radius,
        marker=None,
        limit=max_body_events,
    )
    _save(
        body_view,
        "车体扫掠风险",
        common + ["灰色细线=车体扫掠范围外轮廓；红=硬碰撞中心；洋红=紧贴风险中心。"],
        output_dir / "01_车体扫掠风险_8x.png",
    )

    turn_view = base_scaled.copy()
    _draw_path_scaled(turn_view, path, bounds, scale, path_width)
    _draw_event_boxes(turn_view, turn_collision, bounds, scale, color=(0, 0, 255), limit=220)
    _draw_event_boxes(turn_view, turn_tight, bounds, scale, color=(255, 0, 255), limit=220, dashed=True)
    _save(
        turn_view,
        "转弯 yaw 风险细框图",
        common + ["红色细框=转弯扫掠硬碰撞；洋红虚线细框=转弯扫掠紧贴风险。"],
        output_dir / "02_转弯yaw扫掠风险_8x.png",
    )

    window_view = base_scaled.copy()
    _draw_path_scaled(window_view, path, bounds, scale, path_width)
    _draw_window_markers(window_view, path, merged_windows, bounds, scale, marker_radius + 1)
    _save(
        window_view,
        "转角窗口低遮挡图",
        common
        + [
            f"红叉=急转；黄十字=方向突变；洋红菱形=短距离连续折线。sharp={path_windows_payload['sharp_turn_window_count']} zigzag={path_windows_payload['continuous_zigzag_count']} direction={path_windows_payload['direction_change_window_count']}",
        ],
        output_dir / "03_转角窗口诊断_8x.png",
    )

    brush_view = base_scaled.copy()
    brush_crop = _scale_image(brush_mask[y0:y1, x0:x1], scale)
    brush_view[brush_crop > 0] = (80, 210, 80)
    _draw_path_scaled(brush_view, path, bounds, scale, path_width)
    _save(
        brush_view,
        "盘刷覆盖",
        common + ["绿色=盘刷 footprint 扫过区域；蓝线=原始路径。"],
        output_dir / "04_盘刷覆盖_8x.png",
    )

    squeegee_view = base_scaled.copy()
    squeegee_crop = _scale_image(squeegee_mask[y0:y1, x0:x1], scale)
    squeegee_view[squeegee_crop > 0] = (255, 180, 40)
    _draw_path_scaled(squeegee_view, path, bounds, scale, path_width)
    _save(
        squeegee_view,
        "刮水器覆盖",
        common + ["浅蓝=刮水器 footprint 扫过区域；蓝线=原始路径。"],
        output_dir / "05_刮水器覆盖_8x.png",
    )

    cleaning_gap_view = base_scaled.copy()
    gap_crop = _scale_image(cleaning_gap[y0:y1, x0:x1], scale)
    cleaning_gap_view[gap_crop > 0] = (0, 0, 255)
    _draw_path_scaled(cleaning_gap_view, path, bounds, scale, path_width)
    _save(
        cleaning_gap_view,
        "真实清扫漏扫",
        common + ["红色=真实清扫 footprint 未覆盖目标区；蓝线=原始路径。"],
        output_dir / "06_真实清扫漏扫_8x.png",
    )

    gap_view = base_scaled.copy()
    gap_crop = _scale_image(cleaning_gap[y0:y1, x0:x1], scale)
    centerline_gap_crop = _scale_image(centerline_gap[y0:y1, x0:x1], scale)
    gap_view[centerline_gap_crop > 0] = (0, 255, 255)
    gap_view[gap_crop > 0] = (0, 0, 255)
    _draw_path_scaled(gap_view, path, bounds, scale, path_width)
    _save(
        gap_view,
        "buffer 与真实清扫覆盖差异",
        common + ["黄色=中心线 buffer 漏扫；红色=真实清扫 footprint 漏扫；蓝线=原始路径。"],
        output_dir / "07_buffer与真实清扫覆盖差异_8x.png",
    )
    _make_local_montage(
        overview,
        turn_collision + turn_tight + body_collision + body_tight,
        bounds,
        scale,
        output_dir / "08_风险窗口放大_8x.png",
        "风险窗口放大",
    )
    _make_local_montage(
        overview,
        turn_collision + turn_tight + body_collision + body_tight,
        bounds,
        scale,
        output_dir / "辅助_局部风险窗口拼图_8x.png",
        "辅助局部风险窗口拼图",
    )

    manifest = {
        "version": "geometry_readable_visuals.v1",
        "source_case_dir": str(case_dir),
        "scale": scale,
        "path_width_px": path_width,
        "marker_radius_px": marker_radius,
        "outputs": sorted(str(path) for path in output_dir.glob("*.png")),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_dir)
    return output_dir


def main() -> None:
    args = parse_args()
    for diagnostic_dir in args.diagnostic_dirs:
        _render_one(diagnostic_dir, args.scale, args.path_width, args.marker_radius, args.max_body_events)


if __name__ == "__main__":
    main()
