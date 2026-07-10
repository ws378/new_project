"""基础几何准备中的预处理公共入口。"""

from __future__ import annotations

from .conversions import kernel_px_from_meters
from .core import InputFrame, SpaceMasks, build_space_masks, clean_free_space, normalize_input

__all__ = (
    "InputFrame",
    "SpaceMasks",
    "normalize_input",
    "build_space_masks",
    "clean_free_space",
    "kernel_px_from_meters",
)
