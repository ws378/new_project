"""交汇重建纯算法入口。"""

from .compact import compact_active_objects, validate_junction_rebuild_result
from .edge_geometry import rebuild_edge_geometry
from .initial_node_edge import (
    build_initial_node_edge,
    derive_initial_dead_end_candidates,
    derive_initial_edges,
    derive_initial_junction_candidates,
    derive_initial_nodes,
    validate_initial_node_edge,
)
from .node_geometry import rebuild_node_geometry
from .node_merge import (
    apply_node_merges,
    derive_merge_groups,
    derive_post_geometry_merge_candidates,
    derive_post_geometry_merge_groups,
    derive_post_split_geometry_anomalies,
    max_post_geometry_merge_iterations,
    validate_post_geometry_merge_result,
)

__all__ = (
    # initial node/edge build
    "build_initial_node_edge",
    "derive_initial_nodes",
    "derive_initial_junction_candidates",
    "derive_initial_dead_end_candidates",
    "derive_initial_edges",
    "validate_initial_node_edge",
    # node merge
    "derive_merge_groups",
    "apply_node_merges",
    "derive_post_geometry_merge_candidates",
    "derive_post_geometry_merge_groups",
    "derive_post_split_geometry_anomalies",
    "max_post_geometry_merge_iterations",
    "validate_post_geometry_merge_result",
    # geometry rebuild
    "rebuild_node_geometry",
    "rebuild_edge_geometry",
    # compact / validation
    "compact_active_objects",
    "validate_junction_rebuild_result",
)
