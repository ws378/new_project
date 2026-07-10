"""货架感知 guarded 覆盖规划器。"""

from .models import LocalDirectionConfig, PlannerConfig, StrategyConfig, TurnConstraintConfig
from .planner import plan_coverage_path
from .shelf_aware_planner import ShelfAwareCoveragePlanner

# 对外 API 统一聚合，避免调用方直接依赖内部细分模块路径。
__all__ = [
  "ShelfAwareCoveragePlanner",
  "plan_coverage_path",
  "LocalDirectionConfig",
  "PlannerConfig",
  "StrategyConfig",
  "TurnConstraintConfig",
]
