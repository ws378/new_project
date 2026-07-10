from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConstraintVisualStyle:
    outline: str
    fill: str
    stipple: str
    overlay_rgba: tuple[int, int, int, int]


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    if len(color) != 6:
        raise ValueError(f"Unsupported hex color: {color!r}")
    return tuple(int(color[idx : idx + 2], 16) for idx in (0, 2, 4))


def constraint_base_color(constraint_type: str) -> str:
    return {
        "forbidden_zone": "#ff4d4f",
        "pass_only": "#FFD700",
        "virtual_wall": "#1e6cff",
        "no_coverage": "#ff7a45",
        "electronic_fence": "#00c2ff",
    }.get(constraint_type, "#bfbfbf")


def constraint_visual_style(constraint_type: str) -> ConstraintVisualStyle:
    base = constraint_base_color(constraint_type)
    rgb = _hex_to_rgb(base)
    if constraint_type in {"forbidden_zone", "no_coverage"}:
        return ConstraintVisualStyle(
            outline=base,
            fill=base,
            stipple="gray25",
            overlay_rgba=(rgb[0], rgb[1], rgb[2], 96),
        )
    if constraint_type == "pass_only":
        return ConstraintVisualStyle(
            outline=base,
            fill=base,
            stipple="gray25",
            overlay_rgba=(rgb[0], rgb[1], rgb[2], 96),
        )
    if constraint_type in {"virtual_wall", "electronic_fence"}:
        return ConstraintVisualStyle(
            outline=base,
            fill="",
            stipple="",
            overlay_rgba=(rgb[0], rgb[1], rgb[2], 112),
        )
    return ConstraintVisualStyle(
        outline=base,
        fill="",
        stipple="",
        overlay_rgba=(rgb[0], rgb[1], rgb[2], 96),
    )
