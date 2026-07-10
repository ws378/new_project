"""带方向引导偏置的官方 atomic strips wrapper。"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .models import GuidanceField
from .vertex_guidance import query_vertex_direction


def axis_angle_distance_rad(a: float, b: float) -> float:
    """无向轴角距离，返回 [0, pi/2]。"""

    return abs(((float(a) - float(b) + 0.5 * math.pi) % math.pi) - 0.5 * math.pi)


class GuidedEquiangularRepetitionAtomicStrips:
    """官方 EquiangularRepetitionAtomicStrips 的本地软引导包装。

    与官方实现保持相同候选方向、目标项和 assignment，只在候选方向集合选择时增加
    guidance penalty。该类不修改 `third_party/paper_official` 源码。
    """

    def __init__(
        self,
        *,
        number_of_different_orientations: int,
        repetition_of_each_orientation: int,
        guidance_field: GuidanceField,
        guidance_weight_frac: float,
        guidance_weight_abs: float,
        min_confidence: float,
    ) -> None:
        self.k = int(number_of_different_orientations)
        self.r = int(repetition_of_each_orientation)
        self.guidance_field = guidance_field
        self.guidance_weight_frac = float(guidance_weight_frac)
        self.guidance_weight_abs = float(guidance_weight_abs)
        self.min_confidence = float(min_confidence)
        self.last_stats: dict[str, Any] = {}

    def _get_sample_orientations(self, instance: Any, v: Any) -> list[float]:
        from pcpptc.grid_solver.cycle_cover.atomic_strip_orientation.orientations import (
            NeighborOrientations,
            StepwiseOrientations,
        )

        stepwise_orientations = StepwiseOrientations(10)
        neighbor_orientations = NeighborOrientations(instance)
        return list(stepwise_orientations()) + list(neighbor_orientations(v))

    def _guidance_penalty(self, orientations: list[float], preferred_angle_rad: float, confidence: float, base_scale: float) -> float:
        angle_error = min(axis_angle_distance_rad(angle, preferred_angle_rad) for angle in orientations)
        normalized_error = angle_error / (0.5 * math.pi)
        return float(confidence) * (
            self.guidance_weight_abs * normalized_error
            + self.guidance_weight_frac * float(base_scale) * normalized_error
        )

    def __call__(self, instance: Any, fractional_solution: Any) -> dict[Any, list[Any]]:
        from pcpptc.grid_solver.cycle_cover.atomic_strip_orientation.assignment import (
            FixedRepetitionAtomicStripAssignment,
        )
        from pcpptc.grid_solver.cycle_cover.atomic_strip_orientation.orientation_list_objective import (
            OrientationListObjective,
        )
        from pcpptc.grid_solver.cycle_cover.atomic_strip_orientation.patterns import (
            EquiangularOrientationList,
        )

        print("Using guided static atomic strip selection strategy.")
        pattern = EquiangularOrientationList(self.k)
        obj = OrientationListObjective(instance, fractional_solution)
        assigner = FixedRepetitionAtomicStripAssignment(self.r, instance, fractional_solution)
        result = {}
        vertex_count = 0
        guided_vertex_count = 0
        changed_choice_count = 0
        total_base_score = 0.0
        total_guidance_penalty = 0.0
        status_counts: dict[str, int] = {}
        for v in instance.graph.nodes:
            vertex_count += 1
            orientations = self._get_sample_orientations(instance, v)
            candidates = [pattern(o) for o in orientations]
            base_scores = [float(obj(v, candidate)) for candidate in candidates]
            base_best_index = int(np.argmin(base_scores))
            best_index = base_best_index
            hint, status = query_vertex_direction(v, self.guidance_field, min_confidence=self.min_confidence)
            status_counts[status.status] = status_counts.get(status.status, 0) + 1
            if hint is not None:
                guided_vertex_count += 1
                positive_scores = [abs(score) for score in base_scores if np.isfinite(score)]
                base_scale = float(np.median(positive_scores)) if positive_scores else 1.0
                base_scale = max(base_scale, 1.0)
                guided_scores = [
                    score + self._guidance_penalty(candidate, hint.preferred_angle_rad, hint.confidence, base_scale)
                    for score, candidate in zip(base_scores, candidates)
                ]
                best_index = int(np.argmin(guided_scores))
                total_guidance_penalty += float(guided_scores[best_index] - base_scores[best_index])
            total_base_score += float(base_scores[best_index])
            if best_index != base_best_index:
                changed_choice_count += 1
            result[v] = list(assigner(v, candidates[best_index]))
        self.last_stats = {
            "vertex_count": int(vertex_count),
            "guided_vertex_count": int(guided_vertex_count),
            "guided_vertex_ratio": guided_vertex_count / vertex_count if vertex_count > 0 else 0.0,
            "changed_choice_count": int(changed_choice_count),
            "changed_choice_ratio": changed_choice_count / vertex_count if vertex_count > 0 else 0.0,
            "total_selected_base_score": float(total_base_score),
            "total_selected_guidance_penalty": float(total_guidance_penalty),
            "status_counts": status_counts,
            "guidance_weight_frac": float(self.guidance_weight_frac),
            "guidance_weight_abs": float(self.guidance_weight_abs),
            "min_confidence": float(self.min_confidence),
            "score_normalization": "per_vertex_median_abs_base_score_floor_1",
            "algorithm_impact": "soft_atomic_strip_orientation_bias",
            "official_difference": "候选方向集合评分增加方向偏置；候选生成、assignment、matching、cycle cover、PCST 仍走官方流程",
        }
        return result


class CorridorAxisAtomicStrips:
    """高置信 corridor 点锁定主轴方向的 atomic strips 实验。

    该类仍复用官方 assignment、matching、cycle cover 和 PCST，仅改变高置信
    guidance 命中点的候选方向集合。低置信或查询失败点回退到官方
    EquiangularRepetitionAtomicStrips 的逐点选择逻辑。
    """

    def __init__(
        self,
        *,
        number_of_different_orientations: int,
        repetition_of_each_orientation: int,
        guidance_field: GuidanceField,
        min_confidence: float,
        primary_orientation_count: int | None = None,
    ) -> None:
        self.k = int(number_of_different_orientations)
        self.r = int(repetition_of_each_orientation)
        self.guidance_field = guidance_field
        self.min_confidence = float(min_confidence)
        self.primary_orientation_count = self.k if primary_orientation_count is None else int(primary_orientation_count)
        if self.primary_orientation_count < 1 or self.primary_orientation_count > self.k:
            raise ValueError("primary_orientation_count must be in [1, number_of_different_orientations]")
        self.last_stats: dict[str, Any] = {}

    def _get_sample_orientations(self, instance: Any, v: Any) -> list[float]:
        from pcpptc.grid_solver.cycle_cover.atomic_strip_orientation.orientations import (
            NeighborOrientations,
            StepwiseOrientations,
        )

        stepwise_orientations = StepwiseOrientations(10)
        neighbor_orientations = NeighborOrientations(instance)
        return list(stepwise_orientations()) + list(neighbor_orientations(v))

    def __call__(self, instance: Any, fractional_solution: Any) -> dict[Any, list[Any]]:
        from pcpptc.grid_solver.cycle_cover.atomic_strip_orientation.assignment import (
            FixedRepetitionAtomicStripAssignment,
        )
        from pcpptc.grid_solver.cycle_cover.atomic_strip_orientation.orientation_list_objective import (
            OrientationListObjective,
        )
        from pcpptc.grid_solver.cycle_cover.atomic_strip_orientation.patterns import (
            EquiangularOrientationList,
        )

        print("Using corridor-axis atomic strip selection strategy.")
        pattern = EquiangularOrientationList(self.k)
        obj = OrientationListObjective(instance, fractional_solution)
        assigner = FixedRepetitionAtomicStripAssignment(self.r, instance, fractional_solution)
        result = {}
        vertex_count = 0
        locked_vertex_count = 0
        fallback_vertex_count = 0
        status_counts: dict[str, int] = {}
        for v in instance.graph.nodes:
            vertex_count += 1
            hint, status = query_vertex_direction(v, self.guidance_field, min_confidence=self.min_confidence)
            status_counts[status.status] = status_counts.get(status.status, 0) + 1
            if hint is not None:
                locked_vertex_count += 1
                primary_count = int(self.primary_orientation_count)
                locked_orientations = [float(hint.preferred_angle_rad)] * primary_count
                locked_orientations.extend([float(hint.preferred_angle_rad + 0.5 * math.pi)] * (self.k - primary_count))
                result[v] = list(assigner(v, locked_orientations))
                continue
            fallback_vertex_count += 1
            orientations = self._get_sample_orientations(instance, v)
            best_set = min((pattern(o) for o in orientations), key=lambda x: obj(v, x))
            result[v] = list(assigner(v, best_set))
        self.last_stats = {
            "vertex_count": int(vertex_count),
            "locked_vertex_count": int(locked_vertex_count),
            "locked_vertex_ratio": locked_vertex_count / vertex_count if vertex_count > 0 else 0.0,
            "fallback_vertex_count": int(fallback_vertex_count),
            "fallback_vertex_ratio": fallback_vertex_count / vertex_count if vertex_count > 0 else 0.0,
            "status_counts": status_counts,
            "min_confidence": float(self.min_confidence),
            "primary_orientation_count": int(self.primary_orientation_count),
            "secondary_orientation_count": int(self.k - self.primary_orientation_count),
            "locked_orientation_policy": "repeat_guidance_axis_primary_count_and_perpendicular_for_remaining_slots_preserve_strip_count",
            "algorithm_impact": "non_official_corridor_axis_atomic_strip_candidate_replacement",
            "official_difference": "高置信 guidance 命中点优先使用 corridor 主轴并可保留少量垂直方向；低置信点回退官方候选选择；后续 assignment/matching/cycle cover/PCST 仍走官方流程",
        }
        return result
