"""ShelfAware+TurnCost 候选基线效果指标契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MetricDirection = Literal["higher_is_better", "lower_is_better"]
MetricGateScope = Literal["gated", "not_gated_readonly"]
MetricValueType = Literal["ratio", "count"]

EFFECT_METRIC_CONTRACT_VERSION = "effect_metric_contract_v1"


@dataclass(frozen=True)
class EffectMetricDefinition:
    name: str
    direction: MetricDirection
    gate_scope: MetricGateScope
    value_type: MetricValueType
    description_zh: str

    @property
    def is_gated(self) -> bool:
        return self.gate_scope == "gated"


EFFECT_METRIC_DEFINITIONS: tuple[EffectMetricDefinition, ...] = (
    EffectMetricDefinition(
        name="coverage_ratio",
        direction="higher_is_better",
        gate_scope="gated",
        value_type="ratio",
        description_zh="路径 buffer 覆盖目标区域的比例，是当前行为不变重构的硬门禁指标。",
    ),
    EffectMetricDefinition(
        name="narrow_coverage_ratio",
        direction="higher_is_better",
        gate_scope="not_gated_readonly",
        value_type="ratio",
        description_zh="窄通道区域的覆盖比例，只读暴露风险，暂不作为硬门禁。",
    ),
    EffectMetricDefinition(
        name="long_jump_count",
        direction="lower_is_better",
        gate_scope="gated",
        value_type="count",
        description_zh="相邻路径点距离超过阈值的长跳跃数量，是当前行为不变重构的硬门禁指标。",
    ),
    EffectMetricDefinition(
        name="turn_hotspot_count",
        direction="lower_is_better",
        gate_scope="not_gated_readonly",
        value_type="count",
        description_zh="局部急转热点数量，只读暴露风险，暂不作为硬门禁。",
    ),
    EffectMetricDefinition(
        name="infeasible_segment_count",
        direction="lower_is_better",
        gate_scope="gated",
        value_type="count",
        description_zh="路径线段穿障或不可行数量，是当前行为不变重构的硬门禁指标。",
    ),
    EffectMetricDefinition(
        name="lane_over_dense_count",
        direction="lower_is_better",
        gate_scope="not_gated_readonly",
        value_type="count",
        description_zh="局部 coverage lane 过密数量，只读暴露线距风险，暂不作为硬门禁。",
    ),
    EffectMetricDefinition(
        name="lane_over_sparse_count",
        direction="lower_is_better",
        gate_scope="not_gated_readonly",
        value_type="count",
        description_zh="局部 coverage lane 过疏数量，只读暴露漏扫风险，暂不作为硬门禁。",
    ),
    EffectMetricDefinition(
        name="lane_spacing_issue_count",
        direction="lower_is_better",
        gate_scope="not_gated_readonly",
        value_type="count",
        description_zh="coverage lane 过密与过疏问题总数，只读暴露线距均匀性风险，暂不作为硬门禁。",
    ),
    EffectMetricDefinition(
        name="segment_crossing_count",
        direction="lower_is_better",
        gate_scope="not_gated_readonly",
        value_type="count",
        description_zh="路径线段交叉数量，只读暴露局部重连和路口复杂度风险，暂不作为硬门禁。",
    ),
)


def effect_metric_names() -> tuple[str, ...]:
    return tuple(metric.name for metric in EFFECT_METRIC_DEFINITIONS)


def gated_effect_metric_names() -> tuple[str, ...]:
    return tuple(metric.name for metric in EFFECT_METRIC_DEFINITIONS if metric.is_gated)


def not_gated_effect_metric_names() -> tuple[str, ...]:
    return tuple(metric.name for metric in EFFECT_METRIC_DEFINITIONS if not metric.is_gated)


def higher_is_better_effect_metric_names() -> tuple[str, ...]:
    return tuple(metric.name for metric in EFFECT_METRIC_DEFINITIONS if metric.direction == "higher_is_better")


def lower_is_better_effect_metric_names() -> tuple[str, ...]:
    return tuple(metric.name for metric in EFFECT_METRIC_DEFINITIONS if metric.direction == "lower_is_better")


def effect_metric_contract_payload() -> dict[str, object]:
    return {
        "schema_version": EFFECT_METRIC_CONTRACT_VERSION,
        "gated_metrics": list(gated_effect_metric_names()),
        "not_gated_metrics": list(not_gated_effect_metric_names()),
        "metrics": [
            {
                "name": metric.name,
                "direction": metric.direction,
                "gate_scope": metric.gate_scope,
                "value_type": metric.value_type,
                "description_zh": metric.description_zh,
            }
            for metric in EFFECT_METRIC_DEFINITIONS
        ],
    }
