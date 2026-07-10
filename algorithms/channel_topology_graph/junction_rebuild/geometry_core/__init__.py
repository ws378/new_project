"""交汇几何核心公共入口。"""

from __future__ import annotations

from .branch_support import (
    build_branches_from_cut_points,
    ray_first_hit,
    ray_first_hits,
    truncate_using_cut_points,
)
from .clustered_exit import (
    extract_clustered_exits,
    identify_local_branches,
    seed_groups_around_old,
)
from .common import (
    BranchDirection,
    CandidateEval,
    ExitTrace,
    SectorModel,
    OFFSETS8,
    RING8,
    angle_ccw_delta_deg,
    build_local_context,
    clamp01,
    graph_distances,
    neighbors8,
    path_from_prev,
    to_global,
    to_local,
    wrap_deg,
)
from .evaluation import (
    evaluate_center_candidate,
    evaluate_round,
    polygon_area,
    support_polygon_vertices,
)
from .math import angle_diff_deg, cumulative_lengths, index_at_distance, polygon_centroid_rc
from .path_cuts import (
    component_path_from_entry,
    dedupe_points,
    exit_from_branch_path,
    stable_heading_deg,
)
from .sector_fit import fit_sector_model
from .sector_line import pca_linearity, project_point_to_line
from .sector_refine import refine_edge_endpoints_from_neighbors
from .single_exit import extract_single_center_exits
from ..initial_node_edge.edge_paths import densify_line_rc as densify_line_rc_int

__all__ = (
    # common data / helpers
    "BranchDirection",
    "CandidateEval",
    "ExitTrace",
    "SectorModel",
    "OFFSETS8",
    "RING8",
    "angle_ccw_delta_deg",
    "angle_diff_deg",
    "build_branches_from_cut_points",
    "build_local_context",
    "clamp01",
    # path / geometry utilities
    "component_path_from_entry",
    "cumulative_lengths",
    "dedupe_points",
    "densify_line_rc_int",
    "evaluate_center_candidate",
    "evaluate_round",
    "exit_from_branch_path",
    "extract_clustered_exits",
    "extract_single_center_exits",
    "fit_sector_model",
    "graph_distances",
    "identify_local_branches",
    "index_at_distance",
    "neighbors8",
    "path_from_prev",
    "pca_linearity",
    "polygon_area",
    "polygon_centroid_rc",
    "project_point_to_line",
    "ray_first_hit",
    "ray_first_hits",
    "refine_edge_endpoints_from_neighbors",
    "seed_groups_around_old",
    "stable_heading_deg",
    "support_polygon_vertices",
    "to_global",
    "to_local",
    "truncate_using_cut_points",
    "wrap_deg",
)
