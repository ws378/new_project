"""流水线阶段轻量追踪结构。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PipelineStageRecord:
  """流水线每阶段的最小追踪记录，关注“做了什么”和“是否产生路径副作用”。
  """

  stage_name: str
  status: str = "completed"
  mutates_path: bool = False
  input_point_count: int | None = None
  output_point_count: int | None = None
  summary: dict[str, Any] = field(default_factory=dict)

  def to_dict(self) -> dict[str, Any]:
    """把阶段记录序列化为可持久化的纯字典。

    Returns:
        dict[str, Any]: stage 字段的可 JSON 导出版本。
    """

    return asdict(self)


def pipeline_trace_payload(records: list[PipelineStageRecord]) -> dict[str, Any]:
  """返回写入 planner artifacts 的版本化流水线追踪 payload。"""

  return {
    # payload 里保留版本，支持跨版本读取器兼容旧/新字段。
    "version": "shelf_aware_guarded_pipeline_trace_v1",
    # stage_count 提供快速完整性门限，避免下游仅依赖具体字段名盲目枚举。
    "stage_count": len(records),
    "path_mutating_stage_count": sum(1 for record in records if record.mutates_path),
    "stages": [record.to_dict() for record in records],
  }
