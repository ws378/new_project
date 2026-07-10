"""决策调试载荷构建。

用于输出候选点选择阶段的局部诊断信息，作为 fallback trace 的补充视图。
"""

from __future__ import annotations

from typing import Any

from .schema_registry import CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION


def candidate_decision_debug_payload(
  candidate_decision_debug_trace: list[dict[str, Any]],
) -> dict[str, Any]:
  """生成候选决策阶段的 artifact 负载。

  注意：这里的坐标语义保持沿用 path_index_before_selection（语义上位于
  simplify/semantic/jump-cleanup 之前），不能与 fallback_debug_trace 混淆。
  """
  # 独立文件保留 candidate 决策阶段粒度；
  # 与 fallback 合并会稀释候选前后状态差异，影响复盘。
  return {
    "schema_version": CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION,
    "coordinate_note": (
      "path_index_before_selection 对齐到 simplify/semantic/jump-cleanup 前的 "
      "raw fov_coverage_path；candidate 记录是阶段内局部候选诊断，不替代 "
      "fallback_debug_trace。"
    ),
    "event_count": int(len(candidate_decision_debug_trace)),
    "events": candidate_decision_debug_trace,
  }
