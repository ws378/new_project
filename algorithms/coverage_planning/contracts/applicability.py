from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ApplicabilityMetrics:
    """Scene-level signals used before selecting a coverage planner."""

    skeleton_pixel_count: int = 0
    free_area_pixel_count: int = 0
    skeleton_to_free_area_ratio: float = 0.0
    width_variation_score: float = 0.0
    junction_candidate_count: int = 0
    open_space_score: float = 0.0
    mixed_scene_score: float = 0.0


@dataclass(frozen=True)
class ApplicabilityResult:
    """Planner selection recommendation with reasons and warnings."""

    scene_type: str
    recommended_planner: str
    fallback_chain: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    metrics: ApplicabilityMetrics = field(default_factory=ApplicabilityMetrics)

