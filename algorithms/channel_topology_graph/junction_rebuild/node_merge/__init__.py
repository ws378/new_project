"""交汇节点合并与对象失效逻辑正式入口。"""

from __future__ import annotations

from .apply import apply_node_merges
from .groups import derive_merge_groups
from .post_geometry import (
    derive_post_geometry_merge_candidates,
    derive_post_geometry_merge_groups,
    derive_post_split_geometry_anomalies,
    max_post_geometry_merge_iterations,
    validate_post_geometry_merge_result,
)

__all__ = (
    "derive_merge_groups",
    "apply_node_merges",
    "derive_post_geometry_merge_candidates",
    "derive_post_geometry_merge_groups",
    "derive_post_split_geometry_anomalies",
    "max_post_geometry_merge_iterations",
    "validate_post_geometry_merge_result",
)
