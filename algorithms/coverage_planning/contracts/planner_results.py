from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Pose2D:
    """Legacy planner pose in world coordinates."""

    x: float
    y: float
    theta: float


@dataclass
class CoverageResult:
    """Legacy planner execution result kept outside planner implementation files.

    ``runtime_metadata`` is an adapter handoff for diagnostics evidence. It must
    not be treated as the formal path output truth.
    """

    success: bool
    error_code: int
    error_message: str
    path: list[Pose2D]
    path_pixels: list[tuple[float, float]]
    artifacts_dir: str = ""
    runtime_metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def success_result(
        path: list[Pose2D],
        path_pixels: list[tuple[float, float]],
        artifacts_dir: str = "",
        runtime_metadata: dict[str, Any] | None = None,
    ) -> "CoverageResult":
        return CoverageResult(True, 0, "", path, path_pixels, artifacts_dir, dict(runtime_metadata or {}))

    @staticmethod
    def failure_result(
        error_code: int,
        error_message: str,
        artifacts_dir: str = "",
        runtime_metadata: dict[str, Any] | None = None,
    ) -> "CoverageResult":
        return CoverageResult(False, error_code, error_message, [], [], artifacts_dir, dict(runtime_metadata or {}))
