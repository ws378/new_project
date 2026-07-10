"""最终路径变换记录结构化工具。

每个最终路径步骤都应有一条可追溯记录：发生了什么、为何发生、是否可追踪到 artifact。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


FINAL_PATH_TRANSFORM_SIMPLIFY_ROTATED_PATH = "simplify_rotated_path"
FINAL_PATH_TRANSFORM_SEMANTIC_GLOBAL_PATH = "semantic_global_path"
FINAL_PATH_TRANSFORM_ISOLATED_JUMP_CLEANUP = "isolated_jump_cleanup"
FINAL_PATH_TRANSFORM_FINAL_PATH_GEOMETRY = "final_path_geometry"
FINAL_PATH_TRANSFORM_NAMES = (
  FINAL_PATH_TRANSFORM_SIMPLIFY_ROTATED_PATH,
  FINAL_PATH_TRANSFORM_SEMANTIC_GLOBAL_PATH,
  FINAL_PATH_TRANSFORM_ISOLATED_JUMP_CLEANUP,
  FINAL_PATH_TRANSFORM_FINAL_PATH_GEOMETRY,
)

FINAL_PATH_TRANSFORM_TYPE_LIGHTWEIGHT_SAFETY_GUARD = "lightweight_safety_guard"
FINAL_PATH_TRANSFORM_TYPE_SEMANTIC_PATH_EXPRESSION = "semantic_path_expression"
FINAL_PATH_TRANSFORM_TYPE_GEOMETRIC_FORMATTING = "geometric_formatting"
FINAL_PATH_TRANSFORM_TYPES = (
  FINAL_PATH_TRANSFORM_TYPE_LIGHTWEIGHT_SAFETY_GUARD,
  FINAL_PATH_TRANSFORM_TYPE_SEMANTIC_PATH_EXPRESSION,
  FINAL_PATH_TRANSFORM_TYPE_GEOMETRIC_FORMATTING,
)

FINAL_PATH_PROVENANCE_POLICY_PIPELINE_TRACE = "pipeline_trace"
FINAL_PATH_PROVENANCE_POLICY_SEMANTIC_PATH_ARTIFACT = "semantic_path_artifact"
FINAL_PATH_PROVENANCE_POLICY_ISOLATED_JUMP_CLEANUP_ARTIFACT = "isolated_jump_cleanup_artifact"
FINAL_PATH_PROVENANCE_POLICY_PATH_PIXELS_AND_SEGMENTS = "path_pixels_and_segments"
FINAL_PATH_PROVENANCE_POLICIES = (
  FINAL_PATH_PROVENANCE_POLICY_PIPELINE_TRACE,
  FINAL_PATH_PROVENANCE_POLICY_SEMANTIC_PATH_ARTIFACT,
  FINAL_PATH_PROVENANCE_POLICY_ISOLATED_JUMP_CLEANUP_ARTIFACT,
  FINAL_PATH_PROVENANCE_POLICY_PATH_PIXELS_AND_SEGMENTS,
)


@dataclass(frozen=True)
class FinalPathTransformRecord:
  """记录单次 final path 变换的可追溯信息，用于审计与复盘。

  该记录不用于控制流，仅作为阶段间一致性与可解释性输出。
  """
  name: str
  transform_type: str
  enabled: bool
  input_point_count: int
  output_point_count: int
  changes_path_points: bool
  allowed_in_formal: bool = True
  provenance_policy: str = FINAL_PATH_PROVENANCE_POLICY_PIPELINE_TRACE

  @property
  def point_count_delta(self) -> int:
    """输出点数与输入点数差值（输出 - 输入）。

    返回正数表示新增，负数表示减少。变更链路使用该值判断“本阶段是否扩展了几何点集”。
    """
    # 只在同一口径（点数）上比较，避免把点列结构变化与其他指标混淆。
    return int(self.output_point_count) - int(self.input_point_count)

  @property
  def added_point_count(self) -> int:
    """返回新增点数。

    Returns:
      int: 只对正向增量裁切后得到的新增数量。
    """
    return int(max(0, self.point_count_delta))

  @property
  def removed_point_count(self) -> int:
    """返回移除点数。

    Returns:
      int: 只对负向增量裁切后得到的移除数量。
    """
    return int(max(0, -self.point_count_delta))

  def to_payload(self) -> dict[str, object]:
    """导出审计 payload，避免直接序列化 dataclass 细节。"""
    return {
      "name": str(self.name),
      "transform_type": str(self.transform_type),
      "enabled": bool(self.enabled),
      "allowed_in_formal": bool(self.allowed_in_formal),
      "input_point_count": int(self.input_point_count),
      "output_point_count": int(self.output_point_count),
      "point_count_delta": self.point_count_delta,
      "added_point_count": self.added_point_count,
      "removed_point_count": self.removed_point_count,
      "changes_path_points": bool(self.changes_path_points),
      "provenance_policy": str(self.provenance_policy),
    }


def build_final_path_transform_record(
  *,
  name: str,
  transform_type: str,
  enabled: bool,
  input_point_count: int,
  output_point_count: int,
  changes_path_points: bool,
  allowed_in_formal: bool = True,
  provenance_policy: str = FINAL_PATH_PROVENANCE_POLICY_PIPELINE_TRACE,
) -> FinalPathTransformRecord:
  """统一构建可序列化的 transform record。"""
  # 固化同一 schema 的理由是，后续归因分析工具按字段匹配，而不是按实现细节匹配。
  return FinalPathTransformRecord(
    name=name,
    transform_type=transform_type,
    enabled=enabled,
    input_point_count=input_point_count,
    output_point_count=output_point_count,
    changes_path_points=changes_path_points,
    allowed_in_formal=allowed_in_formal,
    provenance_policy=provenance_policy,
  )


def final_path_transform_records_payload(
  records: Sequence[FinalPathTransformRecord],
) -> list[dict[str, object]]:
  """导出 transform record 列表为 json payload。"""
  # 链式记录用于证明 final path 的来源与变更链路，便于“为什么这个点变了”复盘。
  return [
    record.to_payload()
    for record in records
  ]
