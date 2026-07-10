from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import (
    CoveragePlannerConfig,
    CoveragePlannerPrivateConfig,
)


@dataclass(frozen=True)
class CoveragePlanningRequest:
    """Stable input contract for coverage-planning routing and adapters."""

    prepared_map: np.ndarray
    map_resolution: float
    starting_position_px: tuple[int, int]
    map_origin_xy: tuple[float, float] = (0.0, 0.0)
    region_mask: np.ndarray | None = None
    region_polygon_px: tuple[tuple[int, int], ...] = ()
    map_yaml_path: Path | None = None
    public_config: CoveragePlannerConfig | None = None
    public_config_source_keys: tuple[str, ...] = ()
    private_config: CoveragePlannerPrivateConfig | None = None
    artifacts_output_root: Path | None = None

    def __post_init__(self) -> None:
        prepared_map = np.asarray(self.prepared_map)
        if prepared_map.ndim != 2:
            raise ValueError("prepared_map must be a 2D array")
        if self.region_mask is not None:
            region_mask = np.asarray(self.region_mask)
            if region_mask.shape != prepared_map.shape:
                raise ValueError("region_mask must have the same shape as prepared_map")
        if self.public_config is None:
            object.__setattr__(self, "public_config", CoveragePlannerConfig())
        elif self.public_config_source_keys:
            object.__setattr__(
                self,
                "public_config_source_keys",
                tuple(sorted(set(self.public_config_source_keys))),
            )
        if self.private_config is None:
            object.__setattr__(self, "private_config", CoveragePlannerPrivateConfig())
