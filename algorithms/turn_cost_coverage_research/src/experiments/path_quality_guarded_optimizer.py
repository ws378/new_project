"""局部质量守卫的已有路径 turn-cost 后处理实验。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from algorithms.turn_cost_coverage_research.src.diagnostics.path_diagnostics import LocalQualityMetrics, diagnose_local_quality
from algorithms.turn_cost_coverage_research.src.experiments.path_post_optimizer import (
    PathMetrics,
    Point,
    local_turn_after,
    local_turn_before,
    path_length_px,
    path_metrics,
    segment_is_free,
)


@dataclass(frozen=True)
class QualityGuardedConfig:
    coverage_width_px: int
    max_coverage_drop_ratio: float = 0.001
    max_narrow_coverage_drop_ratio: float = 0.001
    max_shortcut_factor: float = 2.5
    long_jump_factor: float = 4.0
    min_score_improvement: float = 1.0
    length_weight: float = 0.05
    repeated_weight: float = 2500.0
    over_dense_weight: float = 5000.0
    max_quality_evaluations: int = 300


@dataclass(frozen=True)
class QualityGuardedResult:
    points: tuple[Point, ...]
    before_metrics: PathMetrics
    after_metrics: PathMetrics
    before_quality: LocalQualityMetrics
    after_quality: LocalQualityMetrics
    accepted_count: int
    rejected_by_collision_count: int
    rejected_by_global_guard_count: int
    rejected_by_local_quality_count: int
    rejected_by_score_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "before_metrics": self.before_metrics.to_dict(),
            "after_metrics": self.after_metrics.to_dict(),
            "before_quality": self.before_quality.to_dict(),
            "after_quality": self.after_quality.to_dict(),
            "accepted_count": int(self.accepted_count),
            "rejected_by_collision_count": int(self.rejected_by_collision_count),
            "rejected_by_global_guard_count": int(self.rejected_by_global_guard_count),
            "rejected_by_local_quality_count": int(self.rejected_by_local_quality_count),
            "rejected_by_score_count": int(self.rejected_by_score_count),
        }


def _score(metrics: PathMetrics, quality: LocalQualityMetrics, config: QualityGuardedConfig) -> float:
    return float(
        metrics.total_turn_angle_deg
        + metrics.length_px * float(config.length_weight)
        + quality.repeated_coverage_ratio * float(config.repeated_weight)
        + quality.over_dense_coverage_ratio * float(config.over_dense_weight)
    )


def _passes_global_guards(
    candidate: PathMetrics,
    baseline: PathMetrics,
    *,
    config: QualityGuardedConfig,
) -> bool:
    if baseline.coverage_ratio - candidate.coverage_ratio > float(config.max_coverage_drop_ratio):
        return False
    if candidate.long_jump_count > baseline.long_jump_count:
        return False
    if candidate.max_segment_px > baseline.max_segment_px + 1e-6:
        return False
    return True


def _segment_guard_values(points: Sequence[Point], *, long_jump_threshold_px: float) -> tuple[int, float]:
    lengths = [path_length_px((start, end)) for start, end in zip(points, points[1:])]
    long_jump_count = sum(1 for length in lengths if length > float(long_jump_threshold_px))
    return int(long_jump_count), float(max(lengths) if lengths else 0.0)


def _passes_local_quality_guards(
    candidate: LocalQualityMetrics,
    baseline: LocalQualityMetrics,
    *,
    config: QualityGuardedConfig,
) -> bool:
    if candidate.uncovered_component_count > baseline.uncovered_component_count:
        return False
    if candidate.largest_uncovered_component_area_px > baseline.largest_uncovered_component_area_px:
        return False
    if baseline.narrow_coverage_ratio - candidate.narrow_coverage_ratio > float(config.max_narrow_coverage_drop_ratio):
        return False
    if candidate.infeasible_segment_count > baseline.infeasible_segment_count:
        return False
    if candidate.max_infeasible_segment_length_px > baseline.max_infeasible_segment_length_px + 1e-6:
        return False
    return True


def quality_guarded_simplify_path(
    points: Sequence[Point],
    free_mask: np.ndarray,
    config: QualityGuardedConfig,
) -> QualityGuardedResult:
    current = list(points)
    before_metrics = path_metrics(
        current,
        free_mask,
        coverage_width_px=config.coverage_width_px,
        long_jump_factor=config.long_jump_factor,
    )
    before_quality = diagnose_local_quality(current, free_mask, coverage_width_px=config.coverage_width_px)
    long_jump_threshold_px = float(config.coverage_width_px) * float(config.long_jump_factor)
    baseline_long_jump_count, baseline_max_segment_px = _segment_guard_values(
        current,
        long_jump_threshold_px=long_jump_threshold_px,
    )
    accepted = 0
    rejected_collision = 0
    rejected_global = 0
    rejected_local = 0
    rejected_score = 0
    current_length = before_metrics.length_px
    current_turn = before_metrics.total_turn_angle_deg

    index = 1
    while index < len(current) - 1:
        prev_point = current[index - 1]
        point = current[index]
        next_point = current[index + 1]
        direct_len = path_length_px((prev_point, next_point))
        old_len = path_length_px((prev_point, point, next_point))
        if direct_len > old_len * float(config.max_shortcut_factor):
            rejected_score += 1
            index += 1
            continue
        if not segment_is_free(
            free_mask,
            prev_point,
            next_point,
            clearance_px=max(1, int(round(float(config.coverage_width_px) * 0.35))),
        ):
            rejected_collision += 1
            index += 1
            continue
        turn_before = local_turn_before(current, index)
        turn_after = local_turn_after(current, index)
        turn_improvement = turn_before - turn_after
        length_improvement = old_len - direct_len
        if turn_improvement <= 0.0 and length_improvement <= 0.0:
            rejected_score += 1
            index += 1
            continue
        candidate = current[:index] + current[index + 1 :]
        candidate_long_jump_count, candidate_max_segment_px = _segment_guard_values(
            candidate,
            long_jump_threshold_px=long_jump_threshold_px,
        )
        if candidate_long_jump_count > baseline_long_jump_count or candidate_max_segment_px > baseline_max_segment_px + 1e-6:
            rejected_global += 1
            index += 1
            continue
        candidate_length = current_length - old_len + direct_len
        candidate_turn = current_turn - turn_before + turn_after
        score_improvement = (
            current_turn
            + current_length * float(config.length_weight)
            - candidate_turn
            - candidate_length * float(config.length_weight)
        )
        if score_improvement < float(config.min_score_improvement) and turn_improvement <= 0.0:
            rejected_score += 1
            index += 1
            continue
        current = candidate
        current_length = candidate_length
        current_turn = candidate_turn
        accepted += 1
        index = max(1, index - 1)

    current_metrics = path_metrics(
        current,
        free_mask,
        coverage_width_px=config.coverage_width_px,
        long_jump_factor=config.long_jump_factor,
    )
    after_quality = diagnose_local_quality(current, free_mask, coverage_width_px=config.coverage_width_px)
    if not _passes_global_guards(current_metrics, before_metrics, config=config) or not _passes_local_quality_guards(after_quality, before_quality, config=config):
        rejected_local += 1
        current = list(points)
        current_metrics = before_metrics
        after_quality = before_quality
        accepted = 0

    return QualityGuardedResult(
        points=tuple(current),
        before_metrics=before_metrics,
        after_metrics=current_metrics,
        before_quality=before_quality,
        after_quality=after_quality,
        accepted_count=accepted,
        rejected_by_collision_count=rejected_collision,
        rejected_by_global_guard_count=rejected_global,
        rejected_by_local_quality_count=rejected_local,
        rejected_by_score_count=rejected_score,
    )
