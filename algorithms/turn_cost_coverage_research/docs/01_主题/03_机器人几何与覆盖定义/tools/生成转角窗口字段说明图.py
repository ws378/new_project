#!/usr/bin/env python3
"""生成转角窗口字段计算说明图和案例数据。"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from matplotlib import font_manager
import matplotlib.pyplot as plt
import numpy as np


Point = tuple[float, float]
FONT_PATH = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
if FONT_PATH.is_file():
    font_manager.fontManager.addfont(str(FONT_PATH))
plt.rcParams["font.family"] = ["Noto Sans CJK JP", "DejaVu Sans"]
plt.rcParams["font.sans-serif"] = ["Noto Sans CJK JP", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


@dataclass(frozen=True)
class WindowCase:
    name: str
    points: list[Point]
    window_size: int
    center_index: int
    source: str
    description: str


def normalize_angle_deg(angle: float) -> float:
    while angle < -180.0:
        angle += 360.0
    while angle > 180.0:
        angle -= 360.0
    return float(angle)


def heading_deg(a: Point, b: Point) -> float:
    return float(math.degrees(math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0]))))


def distance(a: Point, b: Point) -> float:
    return float(math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1])))


def turn_delta_deg(points: Sequence[Point], index: int) -> float:
    if index <= 0 or index >= len(points) - 1:
        return 0.0
    return normalize_angle_deg(heading_deg(points[index], points[index + 1]) - heading_deg(points[index - 1], points[index]))


def segment_lengths(points: Sequence[Point]) -> list[float]:
    return [distance(a, b) for a, b in zip(points, points[1:])]


def window_metrics(
    points: Sequence[Point],
    *,
    center_index: int,
    window_size: int,
    resolution_m: float,
    straight_angle_tol_deg: float,
    long_jump_threshold_m: float,
) -> dict[str, object]:
    half = window_size // 2
    start = max(0, center_index - half)
    end = min(len(points) - 1, center_index + half)
    local = list(points[start : end + 1])
    local_turns = [turn_delta_deg(points, idx) for idx in range(start + 1, end)]
    abs_turns = [abs(value) for value in local_turns]
    local_lengths_px = segment_lengths(local)
    local_lengths_m = [value * resolution_m for value in local_lengths_px]
    entry_heading = heading_deg(points[start], points[start + 1]) if start + 1 <= end else 0.0
    exit_heading = heading_deg(points[end - 1], points[end]) if end - 1 >= start else entry_heading
    direction_change = abs(normalize_angle_deg(exit_heading - entry_heading))
    turn_angle = max(abs_turns) if abs_turns else 0.0
    turn_angle_sum = float(sum(abs_turns))
    signs = [1 if value > 0 else -1 if value < 0 else 0 for value in local_turns if abs(value) > 1e-6]
    alternating = any(a * b < 0 for a, b in zip(signs, signs[1:]))
    window_length_m = float(sum(local_lengths_m))
    max_segment_length_m = float(max(local_lengths_m) if local_lengths_m else 0.0)
    short_window_m = max(1e-9, window_length_m)
    is_short_zigzag = bool(
        window_size >= 5
        and alternating
        and turn_angle_sum >= max(90.0, direction_change + 45.0)
        and short_window_m <= max(1.2, long_jump_threshold_m)
    )
    long_jump_nearby = max_segment_length_m >= long_jump_threshold_m

    straight_before_m = estimate_straight_length(
        points,
        center_index=center_index,
        direction=-1,
        resolution_m=resolution_m,
        angle_tol_deg=straight_angle_tol_deg,
        long_jump_threshold_m=long_jump_threshold_m,
    )
    straight_after_m = estimate_straight_length(
        points,
        center_index=center_index,
        direction=1,
        resolution_m=resolution_m,
        angle_tol_deg=straight_angle_tol_deg,
        long_jump_threshold_m=long_jump_threshold_m,
    )

    risk_reason: list[str] = []
    if turn_angle >= 70.0:
        risk_reason.append("sharp_turn")
    if is_short_zigzag:
        risk_reason.append("short_zigzag")
    if window_size >= 7 and direction_change >= 45.0:
        risk_reason.append("direction_change")
    if long_jump_nearby:
        risk_reason.append("long_jump_nearby")
    if not risk_reason:
        risk_reason.append("normal_reference")

    requires_turn_swept_check = any(item != "normal_reference" for item in risk_reason) or min(
        straight_before_m, straight_after_m
    ) < 0.4

    return {
        "window_start_index": int(start),
        "window_end_index": int(end),
        "center_index": int(center_index),
        "window_size": int(window_size),
        "window_length_m": round(window_length_m, 4),
        "entry_heading_deg": round(float(entry_heading), 2),
        "exit_heading_deg": round(float(exit_heading), 2),
        "turn_angle_deg": round(float(turn_angle), 2),
        "turn_angle_sum_deg": round(float(turn_angle_sum), 2),
        "direction_change_deg": round(float(direction_change), 2),
        "straight_length_before_m": round(float(straight_before_m), 4),
        "straight_length_after_m": round(float(straight_after_m), 4),
        "max_segment_length_m": round(float(max_segment_length_m), 4),
        "local_turns_deg": [round(float(value), 2) for value in local_turns],
        "risk_reason": risk_reason,
        "requires_turn_swept_check": bool(requires_turn_swept_check),
    }


def estimate_straight_length(
    points: Sequence[Point],
    *,
    center_index: int,
    direction: int,
    resolution_m: float,
    angle_tol_deg: float,
    long_jump_threshold_m: float,
) -> float:
    if len(points) < 2:
        return 0.0
    if direction < 0:
        segment_start = max(0, center_index - 1)
        if segment_start <= 0:
            return 0.0
        base_heading = heading_deg(points[segment_start - 1], points[segment_start])
        cursor = segment_start
        total = 0.0
        while cursor > 0:
            current_heading = heading_deg(points[cursor - 1], points[cursor])
            seg_m = distance(points[cursor - 1], points[cursor]) * resolution_m
            if seg_m >= long_jump_threshold_m or abs(normalize_angle_deg(current_heading - base_heading)) > angle_tol_deg:
                break
            total += seg_m
            cursor -= 1
        return float(total)
    segment_start = min(len(points) - 2, center_index)
    if segment_start >= len(points) - 1:
        return 0.0
    base_heading = heading_deg(points[segment_start], points[segment_start + 1])
    cursor = segment_start
    total = 0.0
    while cursor < len(points) - 1:
        current_heading = heading_deg(points[cursor], points[cursor + 1])
        seg_m = distance(points[cursor], points[cursor + 1]) * resolution_m
        if seg_m >= long_jump_threshold_m or abs(normalize_angle_deg(current_heading - base_heading)) > angle_tol_deg:
            break
        total += seg_m
        cursor += 1
    return float(total)


def load_path(path_file: Path) -> list[Point]:
    data = json.loads(path_file.read_text(encoding="utf-8"))
    points: list[Point] = []
    for item in data:
        if isinstance(item, dict):
            points.append((float(item["x"]), float(item["y"])))
        else:
            points.append((float(item[0]), float(item[1])))
    return points


def synthetic_cases() -> list[WindowCase]:
    return [
        WindowCase(
            name="正常直线段",
            points=[(0, 0), (20, 0), (40, 0), (60, 0), (80, 0)],
            window_size=5,
            center_index=2,
            source="synthetic",
            description="用于说明没有明显转角时，各项转角字段应接近 0。",
        ),
        WindowCase(
            name="单点急转",
            points=[(0, 0), (20, 0), (40, 0), (40, 20), (40, 40)],
            window_size=3,
            center_index=2,
            source="synthetic",
            description="3 点窗口能直接识别中心点处的突然转向。",
        ),
        WindowCase(
            name="短距离连续折线",
            points=[(0, 0), (15, 0), (22, 8), (30, -2), (38, 7), (52, 7)],
            window_size=5,
            center_index=2,
            source="synthetic",
            description="5 点窗口关注多个局部转角叠加，入口和出口方向变化可能不大，但中间折线很多。",
        ),
        WindowCase(
            name="方向逐步扭动",
            points=[(0, 0), (12, 0), (24, 3), (34, 10), (42, 20), (48, 32), (52, 45)],
            window_size=7,
            center_index=3,
            source="synthetic",
            description="7 点窗口用于识别单点不一定极端，但整体方向逐步变化的情况。",
        ),
        WindowCase(
            name="长跳干扰",
            points=[(0, 0), (20, 0), (40, 0), (120, 60), (140, 60), (160, 60)],
            window_size=5,
            center_index=2,
            source="synthetic",
            description="长跳不能简单解释为普通转角，max_segment_length_m 和 risk_reason 需要标出 long_jump_nearby。",
        ),
    ]


def choose_real_cases(points: Sequence[Point]) -> list[WindowCase]:
    if len(points) < 9:
        return []
    turns = [(idx, abs(turn_delta_deg(points, idx))) for idx in range(1, len(points) - 1)]
    sharp_idx = max(turns, key=lambda item: item[1])[0]

    zigzag_scores: list[tuple[int, float]] = []
    for idx in range(2, len(points) - 2):
        local_turns = [turn_delta_deg(points, j) for j in range(idx - 1, idx + 2)]
        signs = [1 if value > 0 else -1 if value < 0 else 0 for value in local_turns if abs(value) > 1e-6]
        alternating = any(a * b < 0 for a, b in zip(signs, signs[1:]))
        direction_change = abs(normalize_angle_deg(heading_deg(points[idx + 1], points[idx + 2]) - heading_deg(points[idx - 2], points[idx - 1])))
        score = sum(abs(value) for value in local_turns) - direction_change + (60.0 if alternating else 0.0)
        zigzag_scores.append((idx, score))
    zigzag_idx = max(zigzag_scores, key=lambda item: item[1])[0]

    direction_scores: list[tuple[int, float]] = []
    for idx in range(3, len(points) - 3):
        entry = heading_deg(points[idx - 3], points[idx - 2])
        exit_ = heading_deg(points[idx + 2], points[idx + 3])
        local_sum = sum(abs(turn_delta_deg(points, j)) for j in range(idx - 2, idx + 3))
        score = abs(normalize_angle_deg(exit_ - entry)) + 0.25 * local_sum
        direction_scores.append((idx, score))
    direction_idx = max(direction_scores, key=lambda item: item[1])[0]

    return [
        WindowCase("真实路径：单点急转候选", list(points), 3, sharp_idx, "real_path", "从真实路径中按最大 3 点转角自动截取。"),
        WindowCase("真实路径：短折线候选", list(points), 5, zigzag_idx, "real_path", "从真实路径中按 5 点转角累计和正负交替自动截取。"),
        WindowCase("真实路径：方向突变候选", list(points), 7, direction_idx, "real_path", "从真实路径中按 7 点入口出口方向变化自动截取。"),
    ]


def draw_cases(cases: Sequence[WindowCase], output_path: Path, *, resolution_m: float, long_jump_threshold_m: float) -> None:
    cols = 2
    rows = int(math.ceil(len(cases) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(12, 4.8 * rows), dpi=160)
    axes_array = np.atleast_1d(axes).reshape(rows, cols)
    for ax, case in zip(axes_array.ravel(), cases):
        metrics = window_metrics(
            case.points,
            center_index=case.center_index,
            window_size=case.window_size,
            resolution_m=resolution_m,
            straight_angle_tol_deg=20.0,
            long_jump_threshold_m=long_jump_threshold_m,
        )
        start = int(metrics["window_start_index"])
        end = int(metrics["window_end_index"])
        local = np.array(case.points[start : end + 1], dtype=float)
        context_start = max(0, start - 4)
        context_end = min(len(case.points) - 1, end + 4)
        context = np.array(case.points[context_start : context_end + 1], dtype=float)
        ax.plot(context[:, 0], context[:, 1], color="#b0b0b0", linewidth=1.2, linestyle="-")
        ax.plot(local[:, 0], local[:, 1], color="#0066cc", linewidth=2.2, marker="o", markersize=4)
        ax.scatter(
            [case.points[case.center_index][0]],
            [case.points[case.center_index][1]],
            color="#e60000",
            s=34,
            zorder=3,
        )
        ax.annotate(
            f"center={case.center_index}",
            xy=case.points[case.center_index],
            xytext=(8, 10),
            textcoords="offset points",
            fontsize=9,
            color="#e60000",
        )
        for idx in range(start, end + 1):
            ax.annotate(str(idx), xy=case.points[idx], xytext=(4, -12), textcoords="offset points", fontsize=8)
        ax.set_title(case.name, fontsize=12)
        ax.set_aspect("equal", adjustable="datalim")
        ax.grid(True, linestyle=":", linewidth=0.6)
        ax.invert_yaxis()
        lines = [
            f"size={metrics['window_size']}  turn={metrics['turn_angle_deg']}  sum={metrics['turn_angle_sum_deg']}",
            f"direction={metrics['direction_change_deg']}  win_len={metrics['window_length_m']}m",
            f"before={metrics['straight_length_before_m']}m  after={metrics['straight_length_after_m']}m",
            f"max_seg={metrics['max_segment_length_m']}m",
            f"reason={','.join(metrics['risk_reason'])}",
        ]
        ax.text(
            0.02,
            0.02,
            "\n".join(lines),
            transform=ax.transAxes,
            fontsize=9,
            va="bottom",
            bbox={"facecolor": "#f2f2f2", "edgecolor": "#555555", "linewidth": 0.8},
        )
    for ax in axes_array.ravel()[len(cases) :]:
        ax.axis("off")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def write_case_json(cases: Sequence[WindowCase], output_path: Path, *, resolution_m: float, long_jump_threshold_m: float) -> None:
    payload = []
    for case in cases:
        metrics = window_metrics(
            case.points,
            center_index=case.center_index,
            window_size=case.window_size,
            resolution_m=resolution_m,
            straight_angle_tol_deg=20.0,
            long_jump_threshold_m=long_jump_threshold_m,
        )
        payload.append(
            {
                "name": case.name,
                "source": case.source,
                "description": case.description,
                "metrics": metrics,
            }
        )
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path-pixels", type=Path, default=None, help="可选真实路径点 JSON；不提供时只生成示意场景。")
    parser.add_argument("--resolution-m", type=float, default=0.05, help="地图分辨率，单位 m/px。")
    parser.add_argument("--long-jump-threshold-m", type=float, default=3.0, help="长跳判断示例阈值，单位 m。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    doc_dir = Path(__file__).resolve().parents[1]
    assets_dir = doc_dir / "assets"
    cases = synthetic_cases()
    real_cases: list[WindowCase] = []
    if args.path_pixels is not None and args.path_pixels.is_file():
        real_cases = choose_real_cases(load_path(args.path_pixels))
    all_cases = cases + real_cases
    draw_cases(cases, assets_dir / "转角窗口字段_示意场景.png", resolution_m=args.resolution_m, long_jump_threshold_m=args.long_jump_threshold_m)
    if real_cases:
        draw_cases(
            real_cases,
            assets_dir / "转角窗口字段_真实路径窗口.png",
            resolution_m=args.resolution_m,
            long_jump_threshold_m=args.long_jump_threshold_m,
        )
    write_case_json(
        all_cases,
        assets_dir / "转角窗口字段计算案例.json",
        resolution_m=args.resolution_m,
        long_jump_threshold_m=args.long_jump_threshold_m,
    )
    print(assets_dir / "转角窗口字段_示意场景.png")
    if real_cases:
        print(assets_dir / "转角窗口字段_真实路径窗口.png")
    print(assets_dir / "转角窗口字段计算案例.json")


if __name__ == "__main__":
    main()
