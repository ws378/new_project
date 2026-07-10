"""基础几何准备纯算法入口。

本包当前采用“包根正式入口 + 局部子包”结构：

1. `preprocessing/`
   - 承载输入归一化、空间 mask 构造、裁剪等预处理能力。
2. `pruning/`
   - 承载骨架短枝裁剪相关能力。
3. `skeleton.py`
   - 保持骨架构造这一块的单文件正式实现。

约束：
    包根 `__init__.py` 只负责暴露本子系统的正式入口，不承担跨阶段聚合逻辑。
    当前不为了与其他子系统表面同形，而强行改成 `stage_*` 目录结构。
    后续若继续重构，只允许在不改变对外导出语义的前提下细化内部职责边界。
"""

from .boundary_smoothing import BoundarySmoothingResult, apply_majority_smoothing
from .preprocessing import InputFrame, SpaceMasks, build_space_masks, clean_free_space, normalize_input
from .pruning import prune_short_side_branches
from .skeleton import SkeletonView, build_skeleton

__all__ = (
    "BoundarySmoothingResult",
    "apply_majority_smoothing",
    "InputFrame",
    "SpaceMasks",
    "SkeletonView",
    "normalize_input",
    "build_space_masks",
    "clean_free_space",
    "build_skeleton",
    "prune_short_side_branches",
)
