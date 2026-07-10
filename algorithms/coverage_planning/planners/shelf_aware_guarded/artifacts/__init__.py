"""artifacts 子模块对外入口。

这里只暴露写出产物的上下文与统一写出接口，避免上层直接绑定到 writer 内部实现，
保证写出层 API 与产物目录演进之间解耦。
"""

from __future__ import annotations

from .writer import PlannerArtifactContext, write_planner_artifacts

# 只暴露最小 API，避免上层绑定 writer 内部实现细节。
__all__ = (
  "PlannerArtifactContext",
  "write_planner_artifacts",
)
