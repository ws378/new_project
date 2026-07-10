from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .diagnostics import CoveragePlanningDiagnostics


class CoveragePlanningStatus(str, Enum):
    """Shared planner status values."""

    SUCCESS = "success"
    FAILURE = "failure"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class CoveragePose2D:
    """World-frame coverage path pose."""

    x: float
    y: float
    theta: float


@dataclass(frozen=True)
class CoveragePlanningResult:
    """Stable output contract for coverage-planning routing and adapters."""

    status: CoveragePlanningStatus
    path: tuple[CoveragePose2D, ...] = ()
    path_pixels: tuple[tuple[float, float], ...] = ()
    error_message: str = ""
    diagnostics: CoveragePlanningDiagnostics = field(default_factory=CoveragePlanningDiagnostics)

    @property
    def success(self) -> bool:
        return self.status == CoveragePlanningStatus.SUCCESS

    def to_summary_dict(self) -> dict[str, object]:
        """Return a stable formal-planning result summary for reports and artifacts."""

        return {
            "status": str(self.status.value),
            "success": bool(self.success),
            "error_message": str(self.error_message or ""),
            "path_point_count": int(len(self.path)),
            "path_pixel_point_count": int(len(self.path_pixels)),
            "diagnostics": self.diagnostics.to_summary_dict(),
        }
