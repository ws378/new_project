"""区域 mask、配置和可视化相关入口。"""

from __future__ import annotations

from .io import load_config_file, load_region_file, region_matches_map, save_config_file, save_region_file
from .masks import Point, polygon_to_mask
from .visualization import save_region_visualizations

# 区域相关能力按配置/几何/可视化聚合，调用方不需要关注子模块拆分方式。
__all__ = (
  "Point",
  "load_config_file",
  "load_region_file",
  "polygon_to_mask",
  "region_matches_map",
  "save_config_file",
  "save_region_file",
  "save_region_visualizations",
)
