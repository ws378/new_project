"""Formal coverage planner implementations live under this package."""

from .region_basic import CoveragePlanner
from .shelf_aware_guarded import ShelfAwareCoveragePlanner

__all__ = [
    "CoveragePlanner",
    "ShelfAwareCoveragePlanner",
]
