"""Coverage lane sweep baseline helpers for tests only."""

from __future__ import annotations

from typing import TypedDict

import numpy as np

from algorithms.channel_topology_graph.coverage_planning.coverage_lane_sweep.lane_common import path_length_euclidean
from algorithms.channel_topology_graph.coverage_planning.coverage_lane_sweep.lane_sweep_geometry import build_uniform_offsets_in_interval
from algorithms.channel_topology_graph.coverage_planning.coverage_lane_sweep.lane_sweep_specs import (
    shrink_head_and_tail_to_avoid_segment_intersection,
)


class LaneSweepAnchorInfo(TypedDict, total=False):
    anchor_index: int
    anchor_rc: tuple[float, float]
    center_point_rc: tuple[float, float]
    normal_vec: tuple[float, float]
    offset_min_px: int
    offset_max_px: int


class LaneSweepLayoutDebug(TypedDict, total=False):
    anchors: list[dict[str, object]]
    mean_offsets_px: list[float]
    center_sweep_index: int


class LaneSweepSpec(TypedDict, total=False):
    path_rc: list[list[float]]
    anchor_points_rc: list[list[float]]
    offset_profile_px: list[float]
    side_label: str
    side_level: int
    path_length_px: float
    target_count: int
    anchor_count: int


def _build_profiles_from_anchor_layouts(
    anchor_infos: list[LaneSweepAnchorInfo],
    target_count: int,
    layout_debug: LaneSweepLayoutDebug,
) -> tuple[list[list[float]], list[list[tuple[float, float]]], list[list[tuple[float, float]]]]:
    """旧版 baseline：统一回填 offset 后直接按索引 regroup。"""

    offset_profiles: list[list[float]] = [[] for _ in range(target_count)]
    point_profiles: list[list[tuple[float, float]]] = [[] for _ in range(target_count)]
    anchor_profiles: list[list[tuple[float, float]]] = [[] for _ in range(target_count)]
    for anchor_info in anchor_infos:
        offsets = build_uniform_offsets_in_interval(
            offset_min_px=int(anchor_info["offset_min_px"]),
            offset_max_px=int(anchor_info["offset_max_px"]),
            count=target_count,
        )
        base_point_rc = tuple(anchor_info["center_point_rc"])
        normal_vec = tuple(anchor_info["normal_vec"])
        for sweep_index, offset_px in enumerate(offsets):
            point_rc = (
                float(base_point_rc[0]) + float(normal_vec[0]) * float(offset_px),
                float(base_point_rc[1]) + float(normal_vec[1]) * float(offset_px),
            )
            offset_profiles[sweep_index].append(float(offset_px))
            point_profiles[sweep_index].append(point_rc)
            anchor_profiles[sweep_index].append(tuple(anchor_info["anchor_rc"]))
        anchor_index = int(anchor_info["anchor_index"])
        layout_debug["anchors"][anchor_index]["final_offsets_px"] = [int(item) for item in offsets]
    return offset_profiles, point_profiles, anchor_profiles


def _resolve_center_sweep_index(
    offset_profiles: list[list[float]],
    layout_debug: LaneSweepLayoutDebug,
) -> int:
    """根据平均横向偏移确定中心 sweep。"""

    mean_offsets = [float(np.mean(profile)) if profile else 0.0 for profile in offset_profiles]
    center_index = int(min(range(len(mean_offsets)), key=lambda idx: abs(mean_offsets[idx])))
    layout_debug["mean_offsets_px"] = [float(item) for item in mean_offsets]
    layout_debug["center_sweep_index"] = int(center_index)
    return center_index


def _build_specs_from_profiles(
    point_profiles: list[list[tuple[float, float]]],
    anchor_profiles: list[list[tuple[float, float]]],
    offset_profiles: list[list[float]],
    center_index: int,
    target_count: int,
    anchor_count: int,
) -> list[LaneSweepSpec]:
    """把 regroup 后的 profiles 物化成 baseline spec 列表。"""

    sweep_specs: list[LaneSweepSpec] = []
    for sweep_index, path_points in enumerate(point_profiles):
        raw_path_tuple = tuple(path_points)
        raw_anchor_tuple = tuple(anchor_profiles[sweep_index])
        raw_offset_tuple = tuple(float(item) for item in offset_profiles[sweep_index])
        path_tuple, anchor_tuple, offset_tuple = shrink_head_and_tail_to_avoid_segment_intersection(
            path_points=raw_path_tuple,
            anchor_points=raw_anchor_tuple,
            offset_profile=raw_offset_tuple,
        )
        if len(path_tuple) < 2:
            continue
        path_length_px = path_length_euclidean(path_tuple)
        if path_length_px <= 1.0:
            continue
        if sweep_index == center_index:
            side_label = "center"
            side_level = 0
        elif sweep_index > center_index:
            side_label = "positive"
            side_level = int(sweep_index - center_index)
        else:
            side_label = "negative"
            side_level = int(center_index - sweep_index)
        sweep_specs.append(
            LaneSweepSpec(
                path_rc=[list(point) for point in path_tuple],
                anchor_points_rc=[list(point) for point in anchor_tuple],
                offset_profile_px=[float(item) for item in offset_tuple],
                side_label=side_label,
                side_level=int(side_level),
                path_length_px=float(path_length_px),
                target_count=int(target_count),
                anchor_count=int(anchor_count),
            )
        )
    return sweep_specs


def build_lane_sweep_specs_index_regroup_baseline(
    anchor_infos: list[LaneSweepAnchorInfo],
    target_count: int,
    layout_debug: LaneSweepLayoutDebug,
) -> list[LaneSweepSpec]:
    """测试专用旧版 baseline：统一回填 offset 后直接按索引 regroup。"""

    offset_profiles, point_profiles, anchor_profiles = _build_profiles_from_anchor_layouts(
        anchor_infos=anchor_infos,
        target_count=target_count,
        layout_debug=layout_debug,
    )
    center_index = _resolve_center_sweep_index(
        offset_profiles=offset_profiles,
        layout_debug=layout_debug,
    )
    return _build_specs_from_profiles(
        point_profiles=point_profiles,
        anchor_profiles=anchor_profiles,
        offset_profiles=offset_profiles,
        center_index=center_index,
        target_count=target_count,
        anchor_count=len(anchor_infos),
    )
