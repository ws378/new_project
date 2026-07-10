"""清理产物载荷构建。

这个文件只做最终清理结果摘要输出，避免在 writer 中夹杂具体清理规则。
"""

from __future__ import annotations

from typing import Any

from ..models import IsolatedJumpCleanupConfig


def isolated_jump_cleanup_payload(
  *,
  config: IsolatedJumpCleanupConfig,
  jump_cleanup_result: Any,
  map_resolution: float,
) -> dict[str, Any]:
  """组装 isolated_jump_cleanup 的元信息。

  返回值只作为 metadata 的一部分提交，约束是：
  - config 以参数化字典形式可追溯；
  - summary 必须与 map_resolution 对齐，以便复现清理长度/距离。
  """
  # 先归档配置快照再写指标，确保复现时既有参数又有口径。
  return {
    "config": config.to_dict(),
    "summary": jump_cleanup_result.to_summary_dict(map_resolution),
  }
