"""方向场工具的统一导出入口。

本模块只负责暴露能力，不承担算法策略细节，便于调用端只依赖能力名称。
"""

from __future__ import annotations

from .field import (
  blend_axis_with_image_gradient,
  compute_local_direction_map,
  normalize_axis_angle_map,
  resolve_local_direction_maps,
  rotate_external_axis_direction_map,
  rotate_external_edge_label_map,
)
from .visualization import visualize_local_direction

# 外部只关心能力名称，不绑定内部文件结构，便于重构时不影响调用方。
__all__ = (
  "blend_axis_with_image_gradient",
  "compute_local_direction_map",
  "normalize_axis_angle_map",
  "resolve_local_direction_maps",
  "rotate_external_axis_direction_map",
  "rotate_external_edge_label_map",
  "visualize_local_direction",
)
