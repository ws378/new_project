#!/usr/bin/env python3
"""生成机器人几何与清扫 footprint 参考图。"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, Rectangle


def main() -> None:
    output_dir = Path(__file__).resolve().parents[1] / "assets"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "机器人几何与清扫footprint示意图.png"

    # 坐标约定：以后轴中心 O 为原点，x 向右，y 向前。
    # 下列尺寸仅用于生成参考图，不作为机器人标定值。
    body_left = -0.30
    body_right = 0.30
    body_rear = -0.20
    rear_axle_to_front_m = 0.60
    brush_radius = 0.14
    left_brush_center = (-0.15, 0.18)
    right_brush_center = (0.15, 0.18)
    squeegee_y = -0.20
    squeegee_left = body_left - 0.10
    squeegee_right = body_right + 0.10
    squeegee_arc_depth_m = 0.07
    safety_radius = ((max(abs(body_left), abs(body_right))) ** 2 + rear_axle_to_front_m**2) ** 0.5

    fig, ax = plt.subplots(figsize=(8, 8), dpi=160)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-0.85, 0.85)
    ax.set_ylim(-0.45, 0.85)
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.35)
    ax.axhline(0, color="#666666", linewidth=0.8)
    ax.axvline(0, color="#666666", linewidth=0.8)

    body = Rectangle(
        (body_left, body_rear),
        body_right - body_left,
        rear_axle_to_front_m - body_rear,
        facecolor="#d9e8f7",
        edgecolor="#2f80d1",
        linewidth=2.0,
        alpha=0.78,
    )
    ax.add_patch(body)

    ax.add_patch(
        Circle((0, 0), safety_radius, fill=False, edgecolor="#555555", linewidth=1.8)
    )
    ax.add_patch(
        Circle(left_brush_center, brush_radius, facecolor="#f4a6b8", edgecolor="#ff3b49", linewidth=1.8, alpha=0.75)
    )
    ax.add_patch(
        Circle(right_brush_center, brush_radius, facecolor="#f4a6b8", edgecolor="#ff3b49", linewidth=1.8, alpha=0.75)
    )
    # 刮水器按软覆盖边表达，允许横向超出刚性车体宽度；这里只表达覆盖范围，不表达硬碰撞。
    xs = np.linspace(squeegee_left, squeegee_right, 100)
    normalized = (xs - squeegee_left) / (squeegee_right - squeegee_left)
    ys = squeegee_y - squeegee_arc_depth_m * np.sin(np.pi * normalized)
    ax.plot(xs, ys, color="#ff3b49", linewidth=2.2)
    ax.plot([squeegee_left, squeegee_right], [squeegee_y, squeegee_y], "o", color="#ff3b49", markersize=4)

    ax.plot(0, 0, "o", color="#1d5fa7", markersize=5)
    ax.annotate("O: rear axle center / path ref", xy=(0, 0), xytext=(0.04, -0.08), color="#1d5fa7", fontsize=10)
    ax.plot(0, rear_axle_to_front_m, "o", color="#555555", markersize=5)
    ax.plot([0, 0], [0, rear_axle_to_front_m], color="#333333", linewidth=1.8)
    ax.annotate(
        "rear_axle_to_front_m",
        xy=(0, rear_axle_to_front_m * 0.55),
        xytext=(0.04, 0.34),
        fontsize=10,
    )

    labels = {
        "A": (body_left, rear_axle_to_front_m),
        "D": (body_right, rear_axle_to_front_m),
        "B": (body_left, body_rear),
        "C": (body_right, body_rear),
        "left brush": left_brush_center,
        "right brush": right_brush_center,
        "soft squeegee coverage": (0.0, squeegee_y - squeegee_arc_depth_m - 0.04),
    }
    for text, xy in labels.items():
        ax.annotate(text, xy=xy, xytext=(xy[0] + 0.02, xy[1] + 0.02), fontsize=10)

    ax.set_xlabel("robot local x / m")
    ax.set_ylabel("robot local y / m")
    ax.set_title("Body and cleaning footprints with rear-axle reference")
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    print(output_path)


if __name__ == "__main__":
    main()
