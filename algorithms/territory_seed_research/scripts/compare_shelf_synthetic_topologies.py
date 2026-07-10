from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from algorithms.coverage_planning.contracts import CoveragePlannerConfig
from algorithms.coverage_planning.planners.shelf_aware_guarded import ShelfAwareCoveragePlanner
from algorithms.territory_seed_research.src.fourfloor_inputs import PACKAGE_ROOT


RESOLUTION_M_PER_PX = 0.05
COVERAGE_WIDTH_M = 0.5


@dataclass(frozen=True)
class SyntheticCase:
    name: str
    room_map: np.ndarray
    axis_map: np.ndarray
    confidence_map: np.ndarray
    start_xy: tuple[int, int]


def path_length_px(path_pixels: list[tuple[float, float]] | tuple[tuple[float, float], ...]) -> float:
    if len(path_pixels) < 2:
        return 0.0
    return float(
        sum(
            math.hypot(float(curr[0]) - float(prev[0]), float(curr[1]) - float(prev[1]))
            for prev, curr in zip(path_pixels, path_pixels[1:])
        )
    )


def turn_count(path_pixels: list[tuple[float, float]] | tuple[tuple[float, float], ...], threshold_deg: float) -> int:
    if len(path_pixels) < 3:
        return 0
    threshold = math.radians(float(threshold_deg))
    count = 0
    previous_angle: float | None = None
    for prev, curr in zip(path_pixels, path_pixels[1:]):
        dx = float(curr[0]) - float(prev[0])
        dy = float(curr[1]) - float(prev[1])
        if abs(dx) + abs(dy) <= 1e-6:
            continue
        angle = math.atan2(dy, dx)
        if previous_angle is not None:
            diff = abs(math.atan2(math.sin(angle - previous_angle), math.cos(angle - previous_angle)))
            if diff >= threshold:
                count += 1
        previous_angle = angle
    return int(count)


def apply_axis(axis_map: np.ndarray, confidence_map: np.ndarray, mask: np.ndarray, axis_angle_rad: float, confidence: float = 1.0) -> None:
    axis_map[mask] = float(axis_angle_rad) % math.pi
    confidence_map[mask] = float(confidence)


def build_l_corridor() -> SyntheticCase:
    room = np.zeros((160, 180), dtype=np.uint8)
    horizontal = np.zeros(room.shape, dtype=bool)
    vertical = np.zeros(room.shape, dtype=bool)
    horizontal[30:58, 18:150] = True
    vertical[30:140, 122:150] = True
    room[horizontal | vertical] = 255
    axis = np.zeros(room.shape, dtype=np.float32)
    conf = np.zeros(room.shape, dtype=np.float32)
    apply_axis(axis, conf, horizontal, 0.0)
    apply_axis(axis, conf, vertical, 0.5 * math.pi)
    conf[horizontal & vertical] = 0.0
    return SyntheticCase('l_corridor', room, axis, conf, (28, 44))


def build_cross_corridor() -> SyntheticCase:
    room = np.zeros((160, 180), dtype=np.uint8)
    horizontal = np.zeros(room.shape, dtype=bool)
    vertical = np.zeros(room.shape, dtype=bool)
    horizontal[68:96, 15:165] = True
    vertical[18:148, 76:104] = True
    room[horizontal | vertical] = 255
    axis = np.zeros(room.shape, dtype=np.float32)
    conf = np.zeros(room.shape, dtype=np.float32)
    apply_axis(axis, conf, horizontal, 0.0)
    apply_axis(axis, conf, vertical, 0.5 * math.pi)
    conf[horizontal & vertical] = 0.0
    return SyntheticCase('cross_corridor', room, axis, conf, (25, 82))


def build_ring_corridor() -> SyntheticCase:
    room = np.zeros((170, 210), dtype=np.uint8)
    room[20:150, 20:190] = 255
    room[55:115, 60:150] = 0
    free = room > 0
    axis = np.zeros(room.shape, dtype=np.float32)
    conf = np.zeros(room.shape, dtype=np.float32)
    top = free & (np.indices(room.shape)[0] < 55)
    bottom = free & (np.indices(room.shape)[0] >= 115)
    left = free & (np.indices(room.shape)[1] < 60)
    right = free & (np.indices(room.shape)[1] >= 150)
    apply_axis(axis, conf, top | bottom, 0.0)
    apply_axis(axis, conf, left | right, 0.5 * math.pi)
    corner = ((top | bottom) & (left | right))
    conf[corner] = 0.0
    return SyntheticCase('ring_corridor', room, axis, conf, (30, 35))


def build_noisy_corridor() -> SyntheticCase:
    room = np.zeros((130, 220), dtype=np.uint8)
    room[50:84, 15:205] = 255
    for idx, col in enumerate(range(25, 190, 24)):
        if idx % 2 == 0:
            room[50:62, col:col + 10] = 0
        else:
            room[72:84, col:col + 10] = 0
    # Keep a continuous center channel so the scenario is still a corridor.
    room[62:72, 15:205] = 255
    axis = np.zeros(room.shape, dtype=np.float32)
    conf = np.zeros(room.shape, dtype=np.float32)
    apply_axis(axis, conf, room > 0, 0.0)
    return SyntheticCase('noisy_corridor', room, axis, conf, (25, 66))


def draw_axis_debug(case: SyntheticCase, output_path: Path) -> None:
    image = cv2.cvtColor(case.room_map, cv2.COLOR_GRAY2BGR)
    step = 20
    line_len = 7
    for row in range(step // 2, case.room_map.shape[0], step):
        for col in range(step // 2, case.room_map.shape[1], step):
            if case.room_map[row, col] == 0 or float(case.confidence_map[row, col]) <= 0.0:
                continue
            angle = float(case.axis_map[row, col])
            dx = int(round(math.cos(angle) * line_len))
            dy = int(round(math.sin(angle) * line_len))
            cv2.line(image, (col - dx, row - dy), (col + dx, row + dy), (255, 255, 255), 1, cv2.LINE_AA)
            cv2.circle(image, (col, row), 1, (0, 0, 0), -1)
    cv2.imwrite(str(output_path), image)


def copy_overlay(artifacts_dir: Path, output_path: Path) -> str:
    source = artifacts_dir / 'path_overlay.png'
    if source.is_file():
        shutil.copyfile(source, output_path)
    return str(output_path) if output_path.is_file() else ''


def write_comparison(baseline_overlay: str, axis_overlay: str, output_path: Path) -> str:
    baseline = cv2.imread(baseline_overlay, cv2.IMREAD_COLOR) if baseline_overlay else None
    axis = cv2.imread(axis_overlay, cv2.IMREAD_COLOR) if axis_overlay else None
    if baseline is None or axis is None:
        return ''
    height = max(baseline.shape[0], axis.shape[0])
    width = max(baseline.shape[1], axis.shape[1])

    def pad(image: np.ndarray, label: str) -> np.ndarray:
        canvas = np.zeros((height, width, 3), dtype=np.uint8)
        canvas[: image.shape[0], : image.shape[1]] = image
        cv2.rectangle(canvas, (0, 0), (min(width, 280), 28), (245, 245, 245), -1)
        cv2.putText(canvas, label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 1, cv2.LINE_AA)
        return canvas

    cv2.imwrite(str(output_path), np.concatenate([pad(baseline, 'baseline'), pad(axis, 'axis prior')], axis=1))
    return str(output_path)


def run_planner(case: SyntheticCase, case_dir: Path, variant: str, axis_enabled: bool) -> dict[str, object]:
    variant_root = case_dir / variant
    planner = ShelfAwareCoveragePlanner(
        CoveragePlannerConfig(
            planner_mode='shelf_aware_guarded',
            coverage_width_m=COVERAGE_WIDTH_M,
            robot_width_m=COVERAGE_WIDTH_M,
            artifacts_output_root=str(variant_root),
            write_artifacts=True,
        )
    )
    result = planner.plan(
        case.room_map,
        RESOLUTION_M_PER_PX,
        case.start_xy,
        local_axis_direction_map=case.axis_map if axis_enabled else None,
        local_axis_confidence_map=case.confidence_map if axis_enabled else None,
    )
    artifacts_dir = Path(result.artifacts_dir) if result.artifacts_dir else variant_root
    overlay = copy_overlay(artifacts_dir, case_dir / f'{variant}_path_overlay.png')
    length_px = path_length_px(tuple(result.path_pixels))
    return {
        'success': bool(result.success),
        'error_code': int(result.error_code),
        'error_message': str(result.error_message or ''),
        'path_pixel_point_count': int(len(result.path_pixels)),
        'path_length_px': float(length_px),
        'path_length_m': float(length_px * RESOLUTION_M_PER_PX),
        'turn_count_45deg': turn_count(tuple(result.path_pixels), 45.0),
        'turn_count_90deg': turn_count(tuple(result.path_pixels), 90.0),
        'artifacts_dir': str(artifacts_dir),
        'path_overlay': overlay,
    }


def run_case(case: SyntheticCase, run_dir: Path) -> dict[str, object]:
    case_dir = run_dir / case.name
    case_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(case_dir / '01_map.png'), case.room_map)
    draw_axis_debug(case, case_dir / '02_axis_prior.png')
    baseline = run_planner(case, case_dir, 'baseline', False)
    axis_prior = run_planner(case, case_dir, 'axis_prior', True)
    comparison_overlay = write_comparison(
        str(baseline.get('path_overlay', '')),
        str(axis_prior.get('path_overlay', '')),
        case_dir / '03_path_comparison.png',
    )
    summary = {
        'case': case.name,
        'map_shape': list(case.room_map.shape),
        'free_pixel_count': int(np.count_nonzero(case.room_map > 0)),
        'start_xy': [int(case.start_xy[0]), int(case.start_xy[1])],
        'baseline': baseline,
        'axis_prior': axis_prior,
        'comparison': {
            'path_point_delta': int(axis_prior.get('path_pixel_point_count', 0)) - int(baseline.get('path_pixel_point_count', 0)),
            'path_length_delta_m': float(axis_prior.get('path_length_m', 0.0)) - float(baseline.get('path_length_m', 0.0)),
            'turn_count_90deg_delta': int(axis_prior.get('turn_count_90deg', 0)) - int(baseline.get('turn_count_90deg', 0)),
            'comparison_overlay': comparison_overlay,
        },
    }
    (case_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


def build_cases() -> tuple[SyntheticCase, ...]:
    return (
        build_l_corridor(),
        build_cross_corridor(),
        build_ring_corridor(),
        build_noisy_corridor(),
    )


def main() -> None:
    run_dir = PACKAGE_ROOT / 'output' / ('run_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_synthetic_shelf_compare')
    run_dir.mkdir(parents=True, exist_ok=True)
    summaries = [run_case(case, run_dir) for case in build_cases()]
    (run_dir / 'summary.json').write_text(json.dumps({'cases': summaries}, ensure_ascii=False, indent=2), encoding='utf-8')
    for summary in summaries:
        print(
            '{case}: baseline={b_points} axis={a_points} len_delta_m={len_delta:.3f} turn90_delta={turn_delta}'.format(
                case=summary['case'],
                b_points=summary['baseline']['path_pixel_point_count'],
                a_points=summary['axis_prior']['path_pixel_point_count'],
                len_delta=summary['comparison']['path_length_delta_m'],
                turn_delta=summary['comparison']['turn_count_90deg_delta'],
            )
        )
    print(run_dir)


if __name__ == '__main__':
    main()
