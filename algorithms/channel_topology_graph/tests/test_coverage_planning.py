"""CoveragePlanning 测试。"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from algorithms.channel_topology_graph.coverage_planning import build_sweep_cadence
from algorithms.channel_topology_graph.coverage_planning.coverage_lane_sweep.lane_path_sampling import (
    sample_path_by_spacing,
)
from algorithms.channel_topology_graph.coverage_planning.coverage_lane_sweep.lane_sweep_specs import (
    build_lane_sweep_specs,
    collect_lane_anchor_layouts,
    initialize_layout_debug,
    segments_intersect,
    shrink_head_and_tail_to_avoid_segment_intersection,
)
from .coverage_lane_sweep_baseline import (
    build_lane_sweep_specs_index_regroup_baseline,
)
from algorithms.channel_topology_graph.coverage_planning.coverage_lane_sweep.lane_sweep_geometry import (
    build_uniform_offsets_in_interval,
    solve_robust_target_sweep_count,
)
from algorithms.channel_topology_graph.coverage_planning.sweep_graph.sweep_transition_candidates import (
    build_sweep_transition_candidates,
)
from algorithms.channel_topology_graph.coverage_planning.sweep_graph.sweep_graph_build import (
    resolve_sweep_transition_candidates,
)
from algorithms.channel_topology_graph.coverage_planning.sweep_graph.sweep_transition_candidates import (
    choose_lane_pairs,
)
from algorithms.channel_topology_graph.coverage_planning.sweep_cadence.cadence_types import (
    cadence_motion_priority,
    covered_connector_step_cost,
    route_transition_ids,
    transition_target_role_priority,
)
from algorithms.channel_topology_graph.contracts import EdgeInfo, GeometryPreparationResult, NodeInfo
from algorithms.channel_topology_graph.contracts import (
    CoverageLaneSweepBuildInfo,
    CoveragePlanningResult,
    GraphInfo,
)
from algorithms.channel_topology_graph.coverage_planning.final_coverage_path.final_path_core import (
    resolve_route_sweep_path_from_relation_truth,
)
from algorithms.channel_topology_graph.coverage_planning.final_coverage_path.final_path_connectors import (
    solve_node_local_transition_connection,
    solve_node_local_foldback_connection,
)
from algorithms.channel_topology_graph.coverage_planning.final_coverage_path.final_path_connectors import (
    validate_junction_connection,
)
from algorithms.channel_topology_graph.coverage_planning.final_coverage_path.final_path_connectors import (
    derive_connection_sampling_step_px,
    sample_connection_path_like_sweep,
)
from algorithms.channel_topology_graph.coverage_planning.final_coverage_path.final_path_core import (
    append_route_points_to_subchains,
    break_route_subchain,
)
from algorithms.channel_topology_graph.coverage_planning.final_coverage_path.final_path_core import (
    build_final_coverage_path_summary,
)
from algorithms.channel_topology_graph.coverage_planning.final_coverage_path.final_path_core import (
    collect_final_connection_truths,
)
from algorithms.channel_topology_graph.stages.coverage_planning import build_coverage_plan
from algorithms.channel_topology_graph.stages.geometry_preparation import build_geometry_preparation
from algorithms.channel_topology_graph.stages.junction_rebuild import build_junction_rebuild
from algorithms.channel_topology_graph.stages.topology_graph_build import build_topology_graph
from algorithms.channel_topology_graph.renderers.coverage_renderers import (
    render_sweep_node_snap_overlay,
)


def build_cross_map(height: int = 80, width: int = 80) -> np.ndarray:
    """构造一个十字通道测试图。"""

    raw = np.zeros((height, width), dtype=np.uint8)
    raw[10:70, 36:44] = 255
    raw[36:44, 10:70] = 255
    return raw


def _build_geometry(raw: np.ndarray):
    """统一构造 geometry_preparation 结果。"""

    return build_geometry_preparation(
        raw_map={"gray": raw, "resolution_m_per_px": 0.05},
        config={"open_kernel_px": 1, "short_side_branch_px": 6},
    )


def _build_topology_result(raw: np.ndarray):
    """统一构造 topology_graph_build 结果。"""

    geometry_result = _build_geometry(raw)
    junction_result = build_junction_rebuild(
        geometry_preparation_result=geometry_result,
        config={
            "intersection_merge_geodesic_px": 12,
            "summary_viz": False,
            "detail_viz": False,
        },
    )
    return geometry_result, build_topology_graph(junction_result)


def _coverage_config() -> dict[str, float]:
    """给窄通道测试图提供一组可成立的 sweep 参数。"""

    return {
        "coverage_width_m": 0.20,
        "free_node_min_clearance_m": 0.05,
        "robot_width_m": 0.20,
    }


def _simple_local_region(size: int = 21) -> dict[str, object]:
    mask = np.ones((size, size), dtype=np.uint8) * 255
    clearance = np.ones((size, size), dtype=np.float32) * 5.0
    center = (float(size // 2), float(size // 2))
    return {
        "mask": mask,
        "clearance_dist_px": clearance,
        "resolution_m_per_px": 0.05,
        "r0": 0,
        "c0": 0,
        "r1": size,
        "c1": size,
        "center_local_rc": center,
    }



def test_build_node_local_feasible_region_expands_bbox_with_connector_endpoints() -> None:
    """局部裁窗不能只跟着 polygon/corridor，必须把真实连接端点也纳入。"""

    from algorithms.channel_topology_graph.coverage_planning.final_coverage_path.final_path_connectors import (
        build_node_local_feasible_region,
    )

    free_mask = np.zeros((40, 120), dtype=np.uint8)
    free_mask[10:30, 20:101] = 255
    geometry_result = GeometryPreparationResult(
        gray=np.copy(free_mask),
        region_mask=np.copy(free_mask),
        free_mask=np.copy(free_mask),
        obstacle_mask=np.where(free_mask > 0, 0, 255).astype(np.uint8),
        after_open_mask=np.copy(free_mask),
        skeleton_mask=np.copy(free_mask),
        skeleton_pruned_mask=np.copy(free_mask),
        skeleton_pixels_rc=tuple(),
        crop_box_px=(0, 0, 120, 40),
        resolution_m_per_px=0.05,
    )
    node = NodeInfo(
        node_id=1,
        point_rc=(20.0, 30.0),
        node_type='junction',
        incident_edge_ids=(1,),
        degree=1,
        polygon_vertices_rc=((18.0, 28.0), (18.0, 32.0), (22.0, 32.0), (22.0, 28.0)),
    )
    edge = EdgeInfo(
        edge_id=1,
        src_node_id=1,
        dst_node_id=2,
        inner_path_rc=((20.0, 30.0), (20.0, 36.0)),
        outer_path_rc=((20.0, 36.0), (20.0, 44.0)),
        path_rc=((20.0, 30.0), (20.0, 36.0), (20.0, 44.0)),
        edge_type='connected_both_ends',
    )

    local_region = build_node_local_feasible_region(
        node=node,
        geometry_result=geometry_result,
        edge_by_id={1: edge},
        config={'robot_width_m': 0.4},
        extra_seed_points_rc=((20.0, 90.0),),
    )

    assert int(local_region['c1']) >= 91
    assert int(local_region['c0']) <= 30



def test_sample_connection_path_like_sweep_preserves_degenerate_seam_pair() -> None:
    """当 connector 首尾 seam 本来重合时，采样后也必须保留两端位。"""

    geometric_path = ((10.0, 20.0), (10.1, 20.1), (10.0, 20.0))
    sampled = sample_connection_path_like_sweep(
        geometric_path=geometric_path,
        sampling_step_px=5,
    )

    assert len(sampled) == 2
    assert tuple(sampled[0]) == tuple(geometric_path[0])
    assert tuple(sampled[-1]) == tuple(geometric_path[-1])



def test_validate_junction_connection_accepts_degenerate_shared_seam() -> None:
    """共享同一 seam 点的退化 direct connector 不应被 validation 误判失败。"""

    local_region = _simple_local_region()
    point = (10.0, 10.0)
    validate_junction_connection(
        path_points_rc=(point, point),
        coverage_support_width_m=0.1,
        local_region=local_region,
        segment={'primitive_type': 'transition'},
        point_b=point,
        point_c=point,
    )

def _make_sweep_graph_build_info(sweeps: tuple[dict, ...], candidates: tuple[dict, ...]):
    """给 cadence/final-path 单测快速构造最小 sweep_graph_build_info 壳。"""

    return SimpleNamespace(
        sweep_graph_info={
            "nodes": tuple(),
            "sweeps": tuple(sweeps),
            "summary": {"sweep_count": int(len(sweeps))},
        },
        sweep_transition_candidate_info={
            "items": tuple(candidates),
            "summary": {"candidate_count": int(len(candidates))},
        },
    )





def test_cross_group_transition_does_not_use_target_sweep_role_priority() -> None:
    """跨 group pair 未建立共享 rank frame 时，目标 sweep 角色不能进入连接器主成本。"""

    sweep_by_id = {
        1: {"sweep_id": 1, "coverage_lane_id": 10, "side_level": 0, "mean_offset_m": 0.0},
        2: {"sweep_id": 2, "coverage_lane_id": 20, "side_level": 1, "mean_offset_m": 0.3},
        3: {"sweep_id": 3, "coverage_lane_id": 10, "side_level": 1, "mean_offset_m": 0.3},
    }
    cross_group_transition = {
        "from_sweep_id": 1,
        "to_sweep_id": 2,
        "motion_type": "straight",
        "risk_score": 6.0,
    }
    same_lane_transition = {
        "from_sweep_id": 1,
        "to_sweep_id": 3,
        "motion_type": "straight",
        "risk_score": 6.0,
    }

    assert transition_target_role_priority(cross_group_transition, sweep_by_id) == 0.0
    assert transition_target_role_priority(same_lane_transition, sweep_by_id) == pytest.approx(1.6)
    assert covered_connector_step_cost(
        transition=cross_group_transition,
        sweep_by_id=sweep_by_id,
        previous_motion_type="straight",
    ) == pytest.approx(6.0)
    assert covered_connector_step_cost(
        transition=same_lane_transition,
        sweep_by_id=sweep_by_id,
        previous_motion_type="straight",
    ) == pytest.approx(6.8)


def _polyline_max_segment_length(path_rc: tuple[tuple[float, float], ...]) -> float:
    if len(path_rc) < 2:
        return 0.0
    return max(
        float(((path_rc[idx][0] - path_rc[idx - 1][0]) ** 2 + (path_rc[idx][1] - path_rc[idx - 1][1]) ** 2) ** 0.5)
        for idx in range(1, len(path_rc))
    )


def _polyline_max_turn_angle_deg(path_rc: tuple[tuple[float, float], ...]) -> float:
    if len(path_rc) < 3:
        return 0.0
    values: list[float] = []
    for idx in range(1, len(path_rc) - 1):
        point_a = path_rc[idx - 1]
        point_b = path_rc[idx]
        point_c = path_rc[idx + 1]
        vec_ab = (float(point_b[0] - point_a[0]), float(point_b[1] - point_a[1]))
        vec_bc = (float(point_c[0] - point_b[0]), float(point_c[1] - point_b[1]))
        norm_ab = float((vec_ab[0] * vec_ab[0] + vec_ab[1] * vec_ab[1]) ** 0.5)
        norm_bc = float((vec_bc[0] * vec_bc[0] + vec_bc[1] * vec_bc[1]) ** 0.5)
        if norm_ab <= 1e-6 or norm_bc <= 1e-6:
            continue
        cos_theta = max(-1.0, min(1.0, (vec_ab[0] * vec_bc[0] + vec_ab[1] * vec_bc[1]) / (norm_ab * norm_bc)))
        values.append(float(np.degrees(np.arccos(cos_theta))))
    return max(values) if values else 0.0


def test_shrink_head_and_tail_to_avoid_segment_intersection_shrinks_both_ends() -> None:
    """首段与尾段相交时，应通过首尾双端回缩解除冲突，而不是直接删点。"""

    raw_path = (
        (0.0, 0.0),
        (0.0, 10.0),
        (4.0, 9.0),
        (6.0, 8.0),
        (8.0, 7.0),
        (-2.0, 5.0),
    )
    raw_anchor = raw_path
    raw_offset = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    assert segments_intersect(raw_path[0], raw_path[1], raw_path[-2], raw_path[-1]) is True

    trimmed_path, trimmed_anchor, trimmed_offset = shrink_head_and_tail_to_avoid_segment_intersection(
        path_points=raw_path,
        anchor_points=raw_anchor,
        offset_profile=raw_offset,
    )

    assert len(trimmed_path) == len(raw_path)
    assert len(trimmed_path) == len(trimmed_anchor) == len(trimmed_offset)
    assert tuple(trimmed_path[0]) != tuple(raw_path[0])
    assert tuple(trimmed_path[-1]) != tuple(raw_path[-1])
    assert segments_intersect(trimmed_path[0], trimmed_path[1], trimmed_path[-2], trimmed_path[-1]) is False


def test_experimental_sweep_layout_reduces_outer_sweep_distortion_on_zigzag_axis() -> None:
    """实验版布局应比旧版 index-regroup 更能压住外侧 sweep 的大跳和回折。"""

    height = 120
    width = 220
    free_mask = np.zeros((height, width), dtype=np.uint8)
    free_mask[30:90, 10:210] = 255
    allowed_domain_mask = np.copy(free_mask)
    obstacle_distance_px = np.ones((height, width), dtype=np.float32) * 100.0

    axis_path = tuple(
        (
            float(60 + (8 if (idx % 2 == 0) else -8)),
            float(20 + idx * 10),
        )
        for idx in range(18)
    )
    sampling_step_px = 10
    normal_search_px = 2
    effective_min_clearance_px = 1.0
    robust_quantile = 0.6

    sampled_anchors = sample_path_by_spacing(axis_path, sampling_step_px)
    baseline_debug = initialize_layout_debug(
        sampled_anchors=sampled_anchors,
        sampling_step_px=sampling_step_px,
        normal_search_px=normal_search_px,
        effective_min_clearance_px=effective_min_clearance_px,
        robust_quantile=robust_quantile,
    )
    anchor_infos, local_counts = collect_lane_anchor_layouts(
        sampled_anchors=sampled_anchors,
        free_mask=free_mask,
        allowed_domain_mask=allowed_domain_mask,
        obstacle_distance_px=obstacle_distance_px,
        normal_search_px=normal_search_px,
        effective_min_clearance_px=effective_min_clearance_px,
        sampling_step_px=sampling_step_px,
        layout_debug=baseline_debug,
    )

    assert anchor_infos is not None
    assert local_counts is not None
    target_count = solve_robust_target_sweep_count(local_counts, robust_quantile)
    baseline_specs = build_lane_sweep_specs_index_regroup_baseline(
        anchor_infos=anchor_infos,
        target_count=target_count,
        layout_debug=baseline_debug,
    )

    experimental_specs, _ = build_lane_sweep_specs(
        axis_path=axis_path,
        free_mask=free_mask,
        allowed_domain_mask=allowed_domain_mask,
        obstacle_distance_px=obstacle_distance_px,
        sampling_step_px=sampling_step_px,
        normal_search_px=normal_search_px,
        effective_min_clearance_px=effective_min_clearance_px,
        robust_quantile=robust_quantile,
    )
    assert experimental_specs is not None

    baseline_outer = next(spec for spec in baseline_specs if str(spec['side_label']) == 'negative' and int(spec['side_level']) == 1)
    experimental_outer = next(spec for spec in experimental_specs if str(spec['side_label']) == 'negative' and int(spec['side_level']) == 1)

    baseline_path = tuple(tuple(map(float, point)) for point in baseline_outer['path_rc'])
    experimental_path = tuple(tuple(map(float, point)) for point in experimental_outer['path_rc'])

    assert _polyline_max_segment_length(experimental_path) < _polyline_max_segment_length(baseline_path)
    assert _polyline_max_turn_angle_deg(experimental_path) < _polyline_max_turn_angle_deg(baseline_path)

def test_build_coverage_plan_generates_coverage_lane_unit_per_edge() -> None:
    """每条正式边都必须先派生一个 coverage lane 单元。"""

    geometry_result, topology_result = _build_topology_result(build_cross_map())
    result = build_coverage_plan(
        topology_result,
        config=_coverage_config(),
        context={"geometry_preparation_result": geometry_result},
    )

    assert result.coverage_lane_sweep_info is not None
    assert len(result.coverage_lane_sweep_info.coverage_lane_info) == len(result.graph_info.edges)


def test_build_coverage_plan_generates_sweeps_for_active_coverage_lanes() -> None:
    """每个有效 coverage lane 都必须至少生成一条 sweep。"""

    geometry_result, topology_result = _build_topology_result(build_cross_map())
    result = build_coverage_plan(
        topology_result,
        config=_coverage_config(),
        context={"geometry_preparation_result": geometry_result},
    )

    assert result.coverage_lane_sweep_info is not None
    active_lane_items = [item for item in result.coverage_lane_sweep_info.coverage_lane_info if bool(item.get("active", True))]
    active_sweeps = [item for item in result.coverage_lane_sweep_info.sweeps if bool(item.get("active", True))]
    assert active_lane_items
    assert active_sweeps
    assert all(int(item["sweep_count"]) >= 1 for item in active_lane_items)
    assert all(len(item.get("territory_pixels", ())) > 0 for item in active_lane_items)
    assert all(float((item.get("local_width_stats") or {}).get("coverage_width_m", 0.0)) > 0.0 for item in active_lane_items)
    assert all("approx_usable_width_m" in (item.get("local_width_stats") or {}) for item in active_lane_items)
    assert all("offset_profile_m" in item and len(item.get("offset_profile_m", ())) >= 2 for item in active_sweeps)


def test_build_coverage_plan_projects_edge_coverage_info() -> None:
    """CoveragePlanning 结果图对象必须把 coverage lane 真值投影回 edge。"""

    geometry_result, topology_result = _build_topology_result(build_cross_map())
    result = build_coverage_plan(
        topology_result,
        config=_coverage_config(),
        context={"geometry_preparation_result": geometry_result},
    )

    lane_by_edge_id = {
        int(item["source_edge_id"]): item
        for item in result.coverage_lane_sweep_info.coverage_lane_info
    }
    assert result.graph_info.meta.get("coverage_projection_attached") is True
    for edge in result.graph_info.edges:
        coverage_info = edge.coverage_info
        lane_item = lane_by_edge_id[int(edge.edge_id)]
        assert coverage_info is not None
        assert int(coverage_info["coverage_lane_id"]) == int(lane_item["coverage_lane_id"])
        assert tuple(tuple(int(v) for v in point) for point in coverage_info["territory_pixels"]) == tuple(
            tuple(int(v) for v in point) for point in lane_item["territory_pixels"]
        )
        assert tuple(tuple(int(v) for v in point) for point in coverage_info["effective_region_pixels"]) == tuple(
            tuple(int(v) for v in point) for point in lane_item["effective_region_pixels"]
        )
        assert dict(coverage_info["local_width_stats"]) == dict(lane_item["local_width_stats"])
        assert tuple(int(item) for item in coverage_info["sweep_ids"]) == tuple(int(item) for item in lane_item["sweep_ids"])
        assert int(coverage_info["sweep_count"]) == int(lane_item["sweep_count"])
        assert bool(coverage_info["active"]) == bool(lane_item.get("active", True))


def test_build_coverage_plan_covers_all_sweeps() -> None:
    """当前正式主线的 cadence 必须覆盖所有 sweep。"""

    geometry_result, topology_result = _build_topology_result(build_cross_map())
    result = build_coverage_plan(
        topology_result,
        config=_coverage_config(),
        context={"geometry_preparation_result": geometry_result},
    )

    assert result.sweep_graph_build_info is not None
    assert result.sweep_cadence_build_info is not None
    stats = result.sweep_cadence_build_info.coverage_stats
    assert stats["is_complete"] is True
    assert stats["covered_sweep_count"] == stats["total_sweep_count"]
    cadence_sweep_ids = {int(sweep_id) for route in result.sweep_cadence_build_info.sweep_cadence_info["routes"] for sweep_id in route["sweep_sequence"]}
    graph_sweep_ids = {
        int(item["sweep_id"]) for item in result.sweep_graph_build_info.sweep_graph_info["sweeps"]
    }
    assert cadence_sweep_ids == graph_sweep_ids


def test_build_coverage_plan_maps_keep_topology_lanes_to_sweep_transitions() -> None:
    """accepted topology lane 应映射到 sweep 层 transition。"""

    geometry_result, topology_result = _build_topology_result(build_cross_map())
    result = build_coverage_plan(
        topology_result,
        config=_coverage_config(),
        context={"geometry_preparation_result": geometry_result},
    )

    assert result.sweep_graph_build_info is not None
    assert len(result.sweep_graph_build_info.sweep_transition_candidate_info["items"]) > 0


def test_build_coverage_plan_builds_sweep_groups_and_cadence() -> None:
    """CoveragePlanning 应先建立 sweep 组、sweep 级 transition 和 cadence。"""

    geometry_result, topology_result = _build_topology_result(build_cross_map())
    result = build_coverage_plan(
        topology_result,
        config=_coverage_config(),
        context={"geometry_preparation_result": geometry_result},
    )

    assert result.sweep_graph_build_info is not None
    assert result.sweep_cadence_build_info is not None
    assert len(result.sweep_graph_build_info.sweep_group_info["groups"]) > 0
    assert len(result.sweep_graph_build_info.sweep_port_view_info["items"]) > 0
    assert len(result.sweep_graph_build_info.sweep_transition_candidate_info["items"]) > 0
    selection_levels = {
        str(item["selection_level"]) for item in result.sweep_graph_build_info.sweep_transition_candidate_info["items"]
    }
    assert "strong_keep" in selection_levels
    candidate_end_types = {
        (str(item["from_end_type"]), str(item["to_end_type"]))
        for item in result.sweep_graph_build_info.sweep_transition_candidate_info["items"]
    }
    assert candidate_end_types
    assert all(
        from_end_type in {"src", "dst"} and to_end_type in {"src", "dst"}
        for from_end_type, to_end_type in candidate_end_types
    )
    assert len(result.sweep_graph_build_info.sweep_transition_candidate_info["items"]) > 0
    sweep_ids = {int(item["sweep_id"]) for item in result.sweep_graph_build_info.sweep_graph_info["sweeps"]}
    route_sweep_ids = {int(sweep_id) for route in result.sweep_cadence_build_info.sweep_cadence_info["routes"] for sweep_id in route["sweep_sequence"]}
    assert sweep_ids == route_sweep_ids


def test_build_coverage_plan_exposes_candidate_graph_skeleton() -> None:
    """阶段 B 只保留 sweep 静态骨架与正式 candidate 真值。"""

    geometry_result, topology_result = _build_topology_result(build_cross_map())
    result = build_coverage_plan(
        topology_result,
        config=_coverage_config(),
        context={"geometry_preparation_result": geometry_result},
    )

    assert result.sweep_graph_build_info is not None
    sweep_graph_info = result.sweep_graph_build_info.sweep_graph_info
    graph_sweeps = tuple(sweep_graph_info.get("sweeps", ()))
    candidate_items = tuple(result.sweep_graph_build_info.sweep_transition_candidate_info.get("items", ()))
    sweep_ids = {int(item["sweep_id"]) for item in graph_sweeps}

    assert candidate_items
    assert result.validation_info["sweep_graph"]["candidate_count"] == len(candidate_items)

    for sweep in graph_sweeps:
        assert int(sweep["sweep_global_id"]) == int(sweep["sweep_id"])
        assert int(sweep["sweep_local_id"]) >= 1

    for item in candidate_items:
        assert int(item["from_sweep_id"]) in sweep_ids
        assert int(item["to_sweep_id"]) in sweep_ids
        assert str(item["from_end_type"]) in {"src", "dst"}
        assert str(item["to_end_type"]) in {"src", "dst"}


def test_build_coverage_plan_builds_final_coverage_path() -> None:
    """CoveragePlanning 应继续把 SweepCadence 物化为 FinalCoveragePath。"""

    geometry_result, topology_result = _build_topology_result(build_cross_map())
    result = build_coverage_plan(
        topology_result,
        config=_coverage_config(),
        context={"geometry_preparation_result": geometry_result},
    )

    assert result.final_coverage_path_build_info is not None
    final_info = result.final_coverage_path_build_info.final_coverage_path_info
    assert final_info is not None
    assert len(final_info["routes"]) == len(result.sweep_cadence_build_info.sweep_cadence_info["routes"])
    assert len(final_info["ordered_items"]) > 0
    assert all("path_subchains_rc" in route for route in final_info["routes"])
    assert all("path_points_rc" not in route for route in final_info["routes"])
    assert all(int((route.get("coverage_support_info") or {}).get("junction_connection_count", -1)) >= 0 for route in final_info["routes"])
    assert all("path_subchain_count" in (route.get("debug_info") or {}) for route in final_info["routes"])
    assert result.validation_info["final_coverage_path"]["is_valid"] is True
    assert result.validation_info["final_coverage_path"]["route_seam_break_count"] == 0


def test_final_coverage_path_junction_connections_have_path_and_support_width() -> None:
    """路口内连接应输出路径点和覆盖支撑宽度。"""

    geometry_result, topology_result = _build_topology_result(build_cross_map())
    result = build_coverage_plan(
        topology_result,
        config=_coverage_config(),
        context={"geometry_preparation_result": geometry_result},
    )

    connections = tuple(result.final_coverage_path_build_info.final_coverage_path_info.get("junction_connections", ()))
    assert connections
    assert all(len(tuple(item.get("junction_connection_points_rc", ()))) >= 2 for item in connections)
    assert all(float(item.get("coverage_support_width_m", 0.0)) > 0.0 for item in connections)
    assert len({int(item["connection_id"]) for item in connections}) == len(connections)
    assert all(tuple(item.get("path_points_rc", ())) == tuple(item.get("junction_connection_points_rc", ())) for item in connections)
    assert all(tuple(item.get("junction_connection_points_rc", ()))[0] == tuple(item.get("point_b_rc", ())) for item in connections)
    assert all(tuple(item.get("junction_connection_points_rc", ()))[-1] == tuple(item.get("point_c_rc", ())) for item in connections)
    assert all(tuple(item.get("point_a_rc", ())) for item in connections)
    assert all(tuple(item.get("point_b_rc", ())) for item in connections)
    assert all(tuple(item.get("point_c_rc", ())) for item in connections)
    assert all(tuple(item.get("point_d_rc", ())) for item in connections)
    assert all(str(item.get("connection_class", "")) in {"direct", "single_bend", "smooth_curve", "foldback"} for item in connections)
    assert all(tuple(item.get("rule_geometry_rc", ())) for item in connections)


def test_final_coverage_path_sweep_segments_reuse_full_original_sweep_paths() -> None:
    """FinalCoveragePath 不允许重建或裁切 sweep 内部点链，只允许正反向引用原始 sweep.path_rc。"""

    geometry_result, topology_result = _build_topology_result(build_cross_map())
    result = build_coverage_plan(
        topology_result,
        config=_coverage_config(),
        context={"geometry_preparation_result": geometry_result},
    )

    sweep_by_id = {
        int(item["sweep_id"]): tuple(tuple(point) for point in tuple(item.get("path_rc", ())))
        for item in tuple(result.coverage_lane_sweep_info.sweeps)
    }
    ordered_items = tuple(result.final_coverage_path_build_info.final_coverage_path_info.get("ordered_items", ()))
    sweep_items = [item for item in ordered_items if str(item.get("item_type", "")) == "sweep_segment"]
    assert sweep_items
    for item in sweep_items:
        sweep_id = int(item["sweep_id"])
        original = sweep_by_id[sweep_id]
        used = tuple(item.get("sweep_points_rc", ()))
        assert used == original or used == tuple(reversed(original))


def test_final_path_transition_connector_uses_direct_when_tangent_is_aligned() -> None:
    """切向已足够顺时，应直接直连。"""

    local_region = _simple_local_region()
    solution = solve_node_local_transition_connection(
        point_a=(1.0, 2.0),
        point_b=(2.0, 2.0),
        point_c=(18.0, 14.0),
        point_d=(19.0, 14.0),
        local_region=local_region,
    )

    path = tuple(solution["node_local_path_rc"])
    assert solution["connection_class"] == "direct"
    assert path[0] == (2.0, 2.0)
    assert path[-1] == (18.0, 14.0)
    assert len(path) == 2


def test_final_path_transition_connector_uses_single_bend_when_angle_is_midrange() -> None:
    """中等夹角时，应优先生成单折线。"""

    local_region = _simple_local_region()
    solution = solve_node_local_transition_connection(
        point_a=(3.0, 4.0),
        point_b=(4.0, 4.0),
        point_c=(16.0, 16.0),
        point_d=(16.0, 15.0),
        local_region=local_region,
    )

    path = tuple(solution["node_local_path_rc"])
    assert solution["connection_class"] == "single_bend"
    assert path[0] == (4.0, 4.0)
    assert path[-1] == (16.0, 16.0)
    assert len(path) == 3


def test_final_path_transition_connector_uses_smooth_curve_when_angle_is_large() -> None:
    """大夹角时，应生成平滑曲线而不是折线。"""

    local_region = _simple_local_region()
    solution = solve_node_local_transition_connection(
        point_a=(3.0, 6.0),
        point_b=(4.0, 6.0),
        point_c=(16.0, 14.0),
        point_d=(15.0, 14.0),
        local_region=local_region,
    )

    path = tuple(solution["node_local_path_rc"])
    assert solution["connection_class"] == "smooth_curve"
    assert path[0] == (4.0, 6.0)
    assert path[-1] == (16.0, 14.0)
    assert len(path) > 3


def test_final_path_transition_connector_marks_failure_without_cross_class_fallback() -> None:
    """目标连接类不可行时，应显式失败，不允许自动降级到其他类。"""

    mask = np.zeros((40, 90), dtype=np.uint8)
    point_a = (15.0, 69.0)
    point_b = (12.0, 61.0)
    point_c = (17.0, 12.0)
    point_d = (18.0, 20.0)
    for row in range(8, 25):
        for col in range(10, 80):
            numerator = abs((point_c[1] - point_b[1]) * (row - point_b[0]) - (point_c[0] - point_b[0]) * (col - point_b[1]))
            if numerator / 50.0 < 2.2:
                mask[row, col] = 255
    for center in (point_b, point_c):
        for row in range(int(center[0]) - 2, int(center[0]) + 3):
            for col in range(int(center[1]) - 2, int(center[1]) + 3):
                if 0 <= row < mask.shape[0] and 0 <= col < mask.shape[1]:
                    mask[row, col] = 255
    local_region = {
        "mask": mask,
        "clearance_dist_px": np.ones_like(mask, dtype=np.float32) * 5.0,
        "r0": 0,
        "c0": 0,
        "r1": int(mask.shape[0]),
        "c1": int(mask.shape[1]),
        "center_local_rc": (float(mask.shape[0] // 2), float(mask.shape[1] // 2)),
        "resolution_m_per_px": 1.0,
    }
    solution = solve_node_local_transition_connection(
        point_a=point_a,
        point_b=point_b,
        point_c=point_c,
        point_d=point_d,
        local_region=local_region,
    )

    assert solution["theta_deg"] > 120.0
    assert solution["connection_class"] == "smooth_curve"
    assert solution["is_constructible"] is False
    assert tuple(solution["rule_geometry_rc"]) == ()
    assert tuple(solution["node_local_path_rc"]) == ()


def test_connection_sampling_step_uses_real_sweep_point_spacing() -> None:
    step = derive_connection_sampling_step_px(
        from_sweep_path=((0.0, 0.0), (0.0, 3.0), (0.0, 6.0)),
        to_sweep_path=((1.0, 0.0), (1.0, 5.0), (1.0, 10.0)),
    )

    assert step == 4


def test_final_path_uturn_connector_uses_structured_template() -> None:
    """空旷节点区内 foldback 应优先走节点内模板。"""

    local_region = _simple_local_region()
    path = solve_node_local_foldback_connection(
        point_b=(4.0, 6.0),
        point_c=(4.0, 14.0),
        local_region=local_region,
    )

    assert path[0] == (4.0, 6.0)
    assert path[-1] == (4.0, 14.0)
    assert len(path) >= 3


def test_route_path_subchains_break_at_failed_connection() -> None:
    """route 正式路径应在失败连接处断开，并在后续 sweep 处开启新子链。"""

    path_subchains = []
    current_subchain = []

    path_subchains, current_subchain = append_route_points_to_subchains(
        path_subchains=path_subchains,
        current_subchain=current_subchain,
        points_rc=((0.0, 0.0), (0.0, 1.0), (0.0, 2.0)),
    )
    path_subchains, current_subchain = append_route_points_to_subchains(
        path_subchains=path_subchains,
        current_subchain=current_subchain,
        points_rc=((0.0, 2.0), (1.0, 2.0)),
    )
    path_subchains, current_subchain = break_route_subchain(
        path_subchains=path_subchains,
        current_subchain=current_subchain,
    )
    path_subchains, current_subchain = append_route_points_to_subchains(
        path_subchains=path_subchains,
        current_subchain=current_subchain,
        points_rc=((3.0, 4.0), (3.0, 5.0)),
    )
    path_subchains, current_subchain = break_route_subchain(
        path_subchains=path_subchains,
        current_subchain=current_subchain,
    )

    assert path_subchains == [
        ((0.0, 0.0), (0.0, 1.0), (0.0, 2.0), (1.0, 2.0)),
        ((3.0, 4.0), (3.0, 5.0)),
    ]
    assert current_subchain == []


def test_sample_path_by_spacing_adapts_to_uniform_positions() -> None:
    """采样应围绕参考步长自适应均匀分布，并仍通过插值得到内部点。"""

    path_rc = (
        (0.0, 0.0),
        (0.0, 3.0),
        (0.0, 6.0),
        (0.0, 9.0),
        (0.0, 12.0),
    )
    sampled = sample_path_by_spacing(path_rc, spacing_px=5)

    assert sampled[0] == (0.0, 0.0)
    assert sampled[-1] == (0.0, 12.0)
    # 参考步长是 5，但整段 12px 更适合均分成 4px 一段，因此内部采样点应落在 4/8。
    assert sampled[1] == (0.0, 4.0)
    assert sampled[2] == (0.0, 8.0)
    # 仍然必须通过插值得到，而不是退回到原始折线已有的 3/6/9 点。
    assert sampled[1] not in path_rc[1:-1]
    assert sampled[2] not in path_rc[1:-1]


def test_lateral_sweep_count_uses_robust_quantile_and_uniform_offsets() -> None:
    """横向 sweep 数应先取稳健分位数，再在局部区间里统一回填 offsets。"""

    target_count = solve_robust_target_sweep_count([2, 2, 2, 3, 3], quantile=0.9)
    assert target_count == 3

    offsets = build_uniform_offsets_in_interval(offset_min_px=-6, offset_max_px=6, count=3)
    assert offsets == (-6, 0, 6)


def test_center_aligned_pairs_prefers_middle_when_counts_differ() -> None:
    """跨 group pair 应按端点几何选近邻，不再按 rank 中心对齐硬配。"""

    context = {
        'from_end_type': 'dst',
        'to_end_type': 'src',
        'from_port': {
            'ordered_port_sweep_ids': (11, 12),
            'port_rank_by_sweep_id': {11: 0, 12: 1},
        },
        'to_port': {
            'ordered_port_sweep_ids': (21, 22, 23, 24),
            'port_rank_by_sweep_id': {21: 0, 22: 1, 23: 2, 24: 3},
        },
    }
    sweeps_by_id = {
        11: {'sweep_id': 11, 'path_rc': ((0.0, 0.0), (0.0, 1.0)), 'resolution_m_per_px': 1.0},
        12: {'sweep_id': 12, 'path_rc': ((10.0, 0.0), (10.0, 1.0)), 'resolution_m_per_px': 1.0},
        21: {'sweep_id': 21, 'path_rc': ((20.0, 1.0), (20.0, 2.0)), 'resolution_m_per_px': 1.0},
        22: {'sweep_id': 22, 'path_rc': ((0.0, 1.1), (0.0, 2.0)), 'resolution_m_per_px': 1.0},
        23: {'sweep_id': 23, 'path_rc': ((10.0, 1.1), (10.0, 2.0)), 'resolution_m_per_px': 1.0},
        24: {'sweep_id': 24, 'path_rc': ((30.0, 1.0), (30.0, 2.0)), 'resolution_m_per_px': 1.0},
    }

    pairs, mapping_type = choose_lane_pairs(
        context=context,
        sweeps_by_id=sweeps_by_id,
        motion_type='straight',
        max_targets_per_sweep=1,
    )

    assert mapping_type == 'endpoint_geometry'
    assert pairs == [(11, 22), (12, 23)]


def test_candidate_pipeline_no_longer_keeps_fallback_layer() -> None:
    """正式候选现在直接输出单层 items，不再补一层 fallback 保底。"""

    candidate_info = {
        "items": (
            {"candidate_id": 1, "selection_level": "strong_keep"},
            {"candidate_id": 2, "selection_level": "strong_keep"},
        ),
        "summary": {
            "candidate_count": 2,
            "strong_candidate_count": 2,
            "weak_candidate_count": 0,
            "fallback_candidate_count": 0,
        },
    }

    assert tuple(item["candidate_id"] for item in candidate_info["items"]) == (1, 2)
    assert int(candidate_info["summary"]["weak_candidate_count"]) == 0
    assert int(candidate_info["summary"]["fallback_candidate_count"]) == 0


def test_sweep_cadence_inserts_repeat_before_same_end_follow_up() -> None:
    """dead-end-like sweep 遇到同端后继时，应先插入 foldback 翻端再继续。"""

    sweep_graph_info = {
        "sweeps": (
            {"sweep_id": 1, "path_length_m": 10.0},
            {"sweep_id": 2, "path_length_m": 10.0},
            {"sweep_id": 3, "path_length_m": 10.0},
        ),
        "transitions": (
            {
                "transition_id": 1,
                "from_sweep_id": 1,
                "to_sweep_id": 2,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 1,
            },
            {
                "transition_id": 2,
                "from_sweep_id": 2,
                "to_sweep_id": 3,
                "from_end_type": "src",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 2,
            },
        ),
    }

    cadence = build_sweep_cadence(_make_sweep_graph_build_info(tuple(sweep_graph_info["sweeps"]), tuple(sweep_graph_info["transitions"])))
    routes = tuple(cadence["routes"])
    assert len(routes) == 1
    assert routes[0]["sweep_sequence"] == [1, 2, 2, 3]
    assert route_transition_ids(routes[0]) == (1, 2)
    assert routes[0]["sweep_count"] == 4
    assert routes[0]["transition_count"] == 2
    assert routes[0]["segments"][1]["primitive_type"] == "foldback"
    assert routes[0]["segments"][1]["entry_end_type"] == "dst"
    assert routes[0]["segments"][1]["exit_end_type"] == "src"


def test_sweep_cadence_can_repeat_sweep_to_flip_exit_end() -> None:
    """dead-end-like sweep 翻端继续时，应走受控 foldback。"""

    sweep_graph_info = {
        "sweeps": (
            {"sweep_id": 1, "path_length_m": 10.0},
            {"sweep_id": 2, "path_length_m": 10.0},
            {"sweep_id": 3, "path_length_m": 10.0},
        ),
        "transitions": (
            {
                "transition_id": 1,
                "from_sweep_id": 1,
                "to_sweep_id": 2,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 1,
            },
            {
                "transition_id": 2,
                "from_sweep_id": 2,
                "to_sweep_id": 3,
                "from_end_type": "src",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 2,
            },
        ),
    }

    cadence = build_sweep_cadence(_make_sweep_graph_build_info(tuple(sweep_graph_info["sweeps"]), tuple(sweep_graph_info["transitions"])))
    routes = tuple(cadence["routes"])
    assert len(routes) == 1
    assert routes[0]["sweep_sequence"] == [1, 2, 2, 3]
    assert route_transition_ids(routes[0]) == (1, 2)
    assert routes[0]["sweep_count"] == 4
    assert routes[0]["transition_count"] == 2
    assert routes[0]["segments"][1]["primitive_type"] == "foldback"
    assert routes[0]["segments"][1]["from_sweep_id"] == 2
    assert routes[0]["segments"][1]["to_sweep_id"] == 2


def test_greedy_sweep_cadence_counts_repeat_coverage_via_transition() -> None:
    """再次经过已覆盖 sweep 仍应是 transition，只在结果层标记 repeat coverage。"""

    sweep_graph_info = {
        "sweeps": (
            {"sweep_id": 1, "path_length_m": 10.0},
            {"sweep_id": 2, "path_length_m": 10.0},
            {"sweep_id": 3, "path_length_m": 10.0},
        ),
        "transitions": (
            {
                "transition_id": 1,
                "from_sweep_id": 1,
                "to_sweep_id": 2,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 1,
            },
            {
                "transition_id": 2,
                "from_sweep_id": 2,
                "to_sweep_id": 1,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 2,
            },
            {
                "transition_id": 3,
                "from_sweep_id": 1,
                "to_sweep_id": 3,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 3,
            },
        ),
    }

    cadence = build_sweep_cadence(_make_sweep_graph_build_info(tuple(sweep_graph_info["sweeps"]), tuple(sweep_graph_info["transitions"])))
    routes = tuple(cadence["routes"])
    assert len(routes) == 1
    assert routes[0]["sweep_sequence"] == [1, 2, 1, 3]
    assert routes[0]["segments"][1]["primitive_type"] == "transition"
    assert routes[0]["segments"][1]["is_repeat_coverage_transition"] is True
    assert sum(1 for item in routes[0]["segments"] if item.get("is_repeat_coverage_transition")) == 1


def test_greedy_sweep_cadence_uses_controlled_foldback_on_dead_end_like_sweep() -> None:
    """dead-end-like sweep 翻端继续时，greedy 主线应使用 foldback，而不是 repeat_sweep。"""

    sweep_graph_info = {
        "sweeps": (
            {"sweep_id": 1, "path_length_m": 10.0, "coverage_lane_id": 10, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
            {"sweep_id": 2, "path_length_m": 10.0, "coverage_lane_id": 20, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
            {"sweep_id": 3, "path_length_m": 10.0, "coverage_lane_id": 30, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
        ),
        "transitions": (
            {
                "transition_id": 1,
                "from_sweep_id": 1,
                "to_sweep_id": 2,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 1,
            },
            {
                "transition_id": 2,
                "from_sweep_id": 2,
                "to_sweep_id": 3,
                "from_end_type": "src",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 2,
            },
        ),
    }

    cadence = build_sweep_cadence(_make_sweep_graph_build_info(tuple(sweep_graph_info["sweeps"]), tuple(sweep_graph_info["transitions"])))
    routes = tuple(cadence["routes"])
    assert len(routes) == 1
    assert routes[0]["sweep_sequence"] == [1, 2, 2, 3]
    assert routes[0]["segments"][1]["primitive_type"] == "foldback"


def test_greedy_cadence_integrates_singleton_between_two_routes() -> None:
    """异常 singleton route 若两侧都有兼容 transition，应优先被并入中间。"""

    sweep_graph_info = {
        "sweeps": (
            {"sweep_id": 1, "path_length_m": 10.0, "coverage_lane_id": 10, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
            {"sweep_id": 2, "path_length_m": 10.0, "coverage_lane_id": 20, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
            {"sweep_id": 3, "path_length_m": 10.0, "coverage_lane_id": 30, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
            {"sweep_id": 4, "path_length_m": 10.0, "coverage_lane_id": 40, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
        ),
        "transitions": (
            {
                "transition_id": 10,
                "from_sweep_id": 1,
                "to_sweep_id": 2,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 1,
            },
            {
                "transition_id": 20,
                "from_sweep_id": 2,
                "to_sweep_id": 3,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 2,
            },
            {
                "transition_id": 30,
                "from_sweep_id": 3,
                "to_sweep_id": 4,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 3,
            },
        ),
    }

    cadence = build_sweep_cadence(_make_sweep_graph_build_info(tuple(sweep_graph_info["sweeps"]), tuple(sweep_graph_info["transitions"])))
    routes = tuple(cadence["routes"])
    assert len(routes) == 1
    assert routes[0]["sweep_sequence"] == [1, 2, 3, 4]


def test_greedy_cadence_attaches_singleton_to_route_end() -> None:
    """异常 singleton route 若只能单侧并入，应允许并入现有 route 端点。"""

    sweep_graph_info = {
        "sweeps": (
            {"sweep_id": 1, "path_length_m": 10.0, "coverage_lane_id": 10, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
            {"sweep_id": 2, "path_length_m": 10.0, "coverage_lane_id": 20, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
            {"sweep_id": 3, "path_length_m": 10.0, "coverage_lane_id": 30, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
        ),
        "transitions": (
            {
                "transition_id": 10,
                "from_sweep_id": 1,
                "to_sweep_id": 2,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 1,
            },
            {
                "transition_id": 20,
                "from_sweep_id": 2,
                "to_sweep_id": 3,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 2,
            },
        ),
    }

    cadence = build_sweep_cadence(_make_sweep_graph_build_info(tuple(sweep_graph_info["sweeps"]), tuple(sweep_graph_info["transitions"])))
    routes = tuple(cadence["routes"])
    assert len(routes) == 1
    assert routes[0]["sweep_sequence"] == [1, 2, 3]


def test_greedy_cadence_inserts_singleton_into_route_slot() -> None:
    """异常 singleton route 若可替换已有局部连接，应允许插入到 route 中间。"""

    sweep_graph_info = {
        "sweeps": (
            {"sweep_id": 1, "path_length_m": 10.0, "coverage_lane_id": 10, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
            {"sweep_id": 2, "path_length_m": 10.0, "coverage_lane_id": 20, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
            {"sweep_id": 3, "path_length_m": 10.0, "coverage_lane_id": 30, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
            {"sweep_id": 4, "path_length_m": 10.0, "coverage_lane_id": 40, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
        ),
        "transitions": (
            {
                "transition_id": 10,
                "from_sweep_id": 1,
                "to_sweep_id": 2,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 1,
            },
            {
                "transition_id": 20,
                "from_sweep_id": 2,
                "to_sweep_id": 4,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 1.0,
                "coverage_gain_score": 0.0,
                "total_score": 1.0,
                "via_node_id": 2,
            },
            {
                "transition_id": 30,
                "from_sweep_id": 2,
                "to_sweep_id": 3,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 3,
            },
            {
                "transition_id": 40,
                "from_sweep_id": 3,
                "to_sweep_id": 4,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 4,
            },
        ),
    }

    cadence = build_sweep_cadence(_make_sweep_graph_build_info(tuple(sweep_graph_info["sweeps"]), tuple(sweep_graph_info["transitions"])))
    routes = tuple(cadence["routes"])
    assert len(routes) == 1
    assert routes[0]["sweep_sequence"] == [1, 2, 3, 4]


def test_sweep_cadence_prefers_straight_before_turn() -> None:
    """同级候选下，cadence 应先选 straight，再看风险等次级指标。"""

    sweep_graph_info = {
        "sweeps": (
            {"sweep_id": 1, "path_length_m": 10.0},
            {"sweep_id": 2, "path_length_m": 10.0},
            {"sweep_id": 3, "path_length_m": 10.0},
        ),
        "transitions": (
            {
                "transition_id": 1,
                "from_sweep_id": 1,
                "to_sweep_id": 2,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "left_turn",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 1,
            },
            {
                "transition_id": 2,
                "from_sweep_id": 1,
                "to_sweep_id": 3,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 10.0,
                "coverage_gain_score": 0.0,
                "total_score": 10.0,
                "via_node_id": 2,
            },
        ),
    }

    cadence = build_sweep_cadence(_make_sweep_graph_build_info(tuple(sweep_graph_info["sweeps"]), tuple(sweep_graph_info["transitions"])))
    routes = tuple(cadence["routes"])
    assert len(routes) == 2
    assert routes[0]["sweep_sequence"] == [1, 3]
    assert route_transition_ids(routes[0]) == (2,)
    assert routes[0]["segments"][0]["motion_type"] == "straight"


def test_greedy_cadence_prefers_continuous_group_with_short_lookahead() -> None:
    """同级候选下，greedy 应优先选更连续且后续还能延续的通道。"""

    sweep_graph_info = {
        "sweeps": (
            {"sweep_id": 1, "path_length_m": 10.0, "coverage_lane_id": 10, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
            {"sweep_id": 2, "path_length_m": 10.0, "coverage_lane_id": 10, "side_level": 0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
            {"sweep_id": 3, "path_length_m": 10.0, "coverage_lane_id": 20, "side_level": 2, "mean_offset_m": 10.0, "resolution_m_per_px": 0.05},
            {"sweep_id": 4, "path_length_m": 10.0, "coverage_lane_id": 10, "side_level": 1, "mean_offset_m": 5.0, "resolution_m_per_px": 0.05},
        ),
        "transitions": (
            {
                "transition_id": 1,
                "from_sweep_id": 1,
                "to_sweep_id": 3,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 1,
            },
            {
                "transition_id": 2,
                "from_sweep_id": 1,
                "to_sweep_id": 4,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 2,
            },
            {
                "transition_id": 3,
                "from_sweep_id": 4,
                "to_sweep_id": 2,
                "from_end_type": "dst",
                "to_end_type": "src",
                "selection_level": "strong_keep",
                "motion_type": "straight",
                "risk_score": 0.0,
                "coverage_gain_score": 0.0,
                "total_score": 0.0,
                "via_node_id": 3,
            },
        ),
    }

    cadence = build_sweep_cadence(_make_sweep_graph_build_info(tuple(sweep_graph_info["sweeps"]), tuple(sweep_graph_info["transitions"])))
    routes = tuple(cadence["routes"])
    assert routes[0]["sweep_sequence"][:3] == [1, 4, 2]


def test_cadence_motion_priority_prefers_same_turn_side_continuity() -> None:
    """已有左/右转上下文时，应优先保持同侧连续转向。"""

    assert cadence_motion_priority("left_turn", "left_turn") < cadence_motion_priority("right_turn", "left_turn")
    assert cadence_motion_priority("right_turn", "right_turn") < cadence_motion_priority("left_turn", "right_turn")


def test_collect_final_connection_truths_reads_algorithm_fields() -> None:
    result = SimpleNamespace(
        coverage_lane_sweep_info=SimpleNamespace(
            sweeps=(
                {"sweep_id": 1, "path_rc": ((0.0, 0.0), (0.0, 1.0), (0.0, 2.0))},
                {"sweep_id": 2, "path_rc": ((1.0, 2.0), (1.0, 1.0), (1.0, 0.0))},
            ),
        ),
        final_coverage_path_build_info=SimpleNamespace(
            final_coverage_path_info={
                "junction_connections": (
                    {
                        "connection_id": 10,
                        "route_id": 1,
                        "from_sweep_id": 1,
                        "to_sweep_id": 2,
                        "point_a_rc": (0.0, 1.0),
                        "point_b_rc": (0.0, 0.0),
                        "point_c_rc": (1.0, 0.0),
                        "point_d_rc": (1.0, 1.0),
                        "theta_deg": 0.0,
                        "connection_class": "direct",
                        "rule_geometry_rc": ((0.0, 0.0), (1.0, 0.0)),
                    },
                )
            },
        ),
    )

    items = collect_final_connection_truths(
        sweeps=result.coverage_lane_sweep_info.sweeps,
        final_coverage_path_info=result.final_coverage_path_build_info.final_coverage_path_info,
    )
    assert len(items) == 1
    item = items[0]
    assert item["point_a_rc"] == (0.0, 1.0)
    assert item["point_b_rc"] == (0.0, 0.0)
    assert item["point_c_rc"] == (1.0, 0.0)
    assert item["point_d_rc"] == (1.0, 1.0)


def test_resolve_route_sweep_path_uses_neighbor_relation_truth_not_propagated_state() -> None:
    route = {
        "route_id": 1,
        "start_end_type": "dst",
        "end_end_type": "dst",
    }
    sweep_sequence = [19, 11]
    segments = (
        {
            "from_sweep_id": 19,
            "to_sweep_id": 11,
            "transition_id": 48,
            "entry_end_type": "src",
            "exit_end_type": "dst",
        },
    )
    transition_by_id = {
        48: {
            "transition_id": 48,
            "from_end_type": "src",
            "to_end_type": "src",
        }
    }
    sweep_19 = {"sweep_id": 19, "path_rc": ((43.0, 90.0), (43.0, 100.0), (43.0, 110.0))}
    sweep_11 = {"sweep_id": 11, "path_rc": ((42.0, 110.0), (42.0, 120.0), (42.0, 130.0))}

    path_19, direction_19 = resolve_route_sweep_path_from_relation_truth(
        route=route,
        sweep_sequence=sweep_sequence,
        segments=segments,
        index=0,
        sweep=sweep_19,
        transition_by_id=transition_by_id,
    )
    path_11, direction_11 = resolve_route_sweep_path_from_relation_truth(
        route=route,
        sweep_sequence=sweep_sequence,
        segments=segments,
        index=1,
        sweep=sweep_11,
        transition_by_id=transition_by_id,
    )

    assert direction_19 == "reverse"
    assert path_19[0] == (43.0, 110.0)
    assert path_19[-1] == (43.0, 90.0)

    assert direction_11 == "forward"
    assert path_11[0] == (42.0, 110.0)
    assert path_11[-1] == (42.0, 130.0)


def test_resolve_route_sweep_path_skips_same_end_connector_only_occurrence() -> None:
    route = {
        "route_id": 1,
        "start_end_type": "dst",
        "end_end_type": "src",
        "sweep_sequence": (128, 130, 134),
        "segments": (
            {
                "from_sweep_id": 128,
                "to_sweep_id": 130,
                "primitive_type": "transition",
                "transition_id": 803,
                "entry_end_type": "src",
                "exit_end_type": "src",
            },
            {
                "from_sweep_id": 130,
                "to_sweep_id": 134,
                "primitive_type": "transition",
                "transition_id": 809,
                "entry_end_type": "src",
                "exit_end_type": "dst",
            },
        ),
    }
    sweep_sequence = [128, 130, 134]
    segments = tuple(route["segments"])
    transition_by_id = {
        803: {
            "transition_id": 803,
            "from_end_type": "src",
            "to_end_type": "src",
        },
        809: {
            "transition_id": 809,
            "from_end_type": "src",
            "to_end_type": "dst",
        },
    }
    sweep_130 = {"sweep_id": 130, "path_rc": ((10.0, 10.0), (10.0, 20.0), (10.0, 30.0))}

    path_130, direction_130 = resolve_route_sweep_path_from_relation_truth(
        route=route,
        sweep_sequence=sweep_sequence,
        segments=segments,
        index=1,
        sweep=sweep_130,
        transition_by_id=transition_by_id,
    )

    assert direction_130 == "connector_only"
    assert path_130 == ()


def test_dead_end_return_hypothesis_generates_formal_sweep_transition_candidates() -> None:
    """same-edge dead-end hypothesis 必须被展开成正式 foldback sweep transition 候选。"""

    sweep_group_info = {
        "groups": (
            {
                "group_id": 1,
                "coverage_lane_id": 11,
                "source_edge_id": 101,
                "edge_type": "dead_end_one_side",
                "src_node_id": 1,
                "dst_node_id": 2,
                "ordered_sweep_ids": [1001, 1002],
                "center_sweep_id": 1001,
                "center_sweep_index": 0,
                "sweep_count": 2,
                "main_direction": [1.0, 0.0],
            },
        ),
        "group_by_edge_id": {
            101: {
                "group_id": 1,
                "coverage_lane_id": 11,
                "source_edge_id": 101,
                "edge_type": "dead_end_one_side",
                "src_node_id": 1,
                "dst_node_id": 2,
                "ordered_sweep_ids": [1001, 1002],
                "center_sweep_id": 1001,
                "center_sweep_index": 0,
                "sweep_count": 2,
                "main_direction": [1.0, 0.0],
            },
        },
    }
    sweep_port_view_info = {
        "items": (
            {
                "group_id": 1,
                "coverage_lane_id": 11,
                "node_id": 1,
                "port_side": "src",
                "ordered_port_sweep_ids": [1001, 1002],
                "port_rank_by_sweep_id": {1001: 0, 1002: 1},
                "center_port_rank": 0,
            },
        ),
        "lookup": {
            (1, 1): {
                "group_id": 1,
                "coverage_lane_id": 11,
                "node_id": 1,
                "port_side": "src",
                "ordered_port_sweep_ids": [1001, 1002],
                "port_rank_by_sweep_id": {1001: 0, 1002: 1},
                "center_port_rank": 0,
            },
        },
    }
    sweeps = (
        {"sweep_id": 1001, "coverage_lane_id": 11, "source_edge_id": 101, "path_rc": ((0.0, 0.0), (10.0, 0.0)), "resolution_m_per_px": 0.05, "active": True},
        {"sweep_id": 1002, "coverage_lane_id": 11, "source_edge_id": 101, "path_rc": ((0.0, 1.0), (10.0, 1.0)), "resolution_m_per_px": 0.05, "active": True},
    )
    hypothesis_info = {
        "items": (
            {
                "hypothesis_id": 501,
                "via_node_id": 1,
                "in_port_id": 1,
                "out_port_id": 1,
                "in_edge_id": 101,
                "in_end_type": "src",
                "out_edge_id": 101,
                "out_end_type": "src",
                "connection_kind": "dead_end_return",
                "base_confidence": 1.0,
                "reason_tags": ("synthetic:dead_end_single_port",),
            },
        ),
    }

    result = build_sweep_transition_candidates(
        sweep_group_info=sweep_group_info,
        sweep_port_view_info=sweep_port_view_info,
        sweeps=sweeps,
        node_local_connection_hypothesis_info=hypothesis_info,
    )

    assert result["items"]
    dead_end_items = [item for item in result["items"] if str(item.get("connection_kind")) == "foldback"]
    lateral_items = [item for item in result["items"] if str(item.get("candidate_source")) == "group_internal"]
    assert dead_end_items
    assert lateral_items
    assert all(str(item.get("connection_kind")) == "foldback" for item in dead_end_items)
    assert all(str(item.get("connection_kind")) == "foldback" for item in dead_end_items)
    assert all(str(item.get("selection_level")) == "strong_keep" for item in dead_end_items)


def test_cadence_transition_segment_preserves_formal_transition_action_type() -> None:
    """cadence route segment 必须显式保留 formal foldback 语义。"""

    sweep_graph_info = {
        "nodes": ({"node_id": 1, "node_type": "dead_end", "point_rc": [0.0, 0.0]},),
        "sweeps": (
            {"sweep_id": 1001, "sweep_global_id": 1001, "sweep_local_id": 1, "coverage_lane_id": 11, "source_edge_id": 101, "path_rc": ((0.0, 0.0), (10.0, 0.0)), "path_length_m": 1.0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05, "src_connection_unit_ids": (1,), "dst_connection_unit_ids": ()},
            {"sweep_id": 1002, "sweep_global_id": 1002, "sweep_local_id": 2, "coverage_lane_id": 11, "source_edge_id": 101, "path_rc": ((0.0, 1.0), (10.0, 1.0)), "path_length_m": 1.0, "mean_offset_m": 1.0, "resolution_m_per_px": 0.05, "src_connection_unit_ids": (), "dst_connection_unit_ids": ()},
        ),
        "transitions": (
            {
                "transition_id": 1,
                "source_candidate_id": 1,
                "via_node_id": 1,
                "from_sweep_id": 1001,
                "to_sweep_id": 1002,
                "from_end_type": "src",
                "to_end_type": "src",
                "motion_type": "foldback",
                "connection_kind": "foldback",
                                "mapping_type": "reverse_order",
                "selection_level": "strong_keep",
                "risk_score": 0.0,
                "coverage_gain_score": 1.0,
                "total_score": 0.0,
                "confidence_score": 1.0,
                "rank_gap": 0,
                "endpoint_distance_m": 1.0,
            },
        ),
    }

    cadence_info = build_sweep_cadence(_make_sweep_graph_build_info(tuple(sweep_graph_info["sweeps"]), tuple(sweep_graph_info["transitions"])), config={})
    segments = tuple(cadence_info["routes"][0]["segments"])
    assert segments
    transition_segments = [item for item in segments if str(item["primitive_type"]) == "transition"]
    assert transition_segments
    assert all(str(item.get("connection_kind")) == "foldback" for item in transition_segments)
    assert all(str(item.get("connection_kind")) == "foldback" for item in transition_segments)


def test_cycle_through_hypothesis_generates_formal_sweep_transition_candidates() -> None:
    """pure cycle cut 的 cycle_through hypothesis 必须能展开成正式 sweep candidates。"""

    sweep_group_info = {
        "group_by_edge_id": {
            7: {"group_id": 17, "source_edge_id": 7, "sweep_ids": (101, 102, 103)},
        }
    }
    sweep_port_view_info = {
        "lookup": {
            (17, 5): {
                "ordered_port_sweep_ids": (101, 102, 103),
                "port_rank_by_sweep_id": {101: 0, 102: 1, 103: 2},
            }
        }
    }
    sweeps = (
        {"sweep_id": 101, "source_edge_id": 7, "path_rc": ((0.0, 0.0), (0.0, 1.0)), "path_length_m": 1.0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05},
        {"sweep_id": 102, "source_edge_id": 7, "path_rc": ((1.0, 0.0), (1.0, 1.0)), "path_length_m": 1.0, "mean_offset_m": 1.0, "resolution_m_per_px": 0.05},
        {"sweep_id": 103, "source_edge_id": 7, "path_rc": ((2.0, 0.0), (2.0, 1.0)), "path_length_m": 1.0, "mean_offset_m": 2.0, "resolution_m_per_px": 0.05},
    )
    hypothesis_info = {
        "items": (
            {
                "hypothesis_id": 9,
                "via_node_id": 5,
                "in_edge_id": 7,
                "in_end_type": "src",
                "out_edge_id": 7,
                "out_end_type": "dst",
                "connection_kind": "cycle_through",
                "base_confidence": 1.0,
            },
        )
    }

    candidate_info = build_sweep_transition_candidates(
        sweep_group_info=sweep_group_info,
        sweep_port_view_info=sweep_port_view_info,
        sweeps=sweeps,
        node_local_connection_hypothesis_info=hypothesis_info,
    )

    cycle_items = [
        item
        for item in candidate_info["items"]
        if str(item.get("connection_kind")) == "forward"
        and str(item.get("candidate_source")) == "node_projected"
        and str(item.get("source_trace_label")) == "cycle_through"
    ]
    assert cycle_items
    assert all(str(item.get("connection_kind")) == "forward" for item in cycle_items)
    strong_cycle_items = [item for item in cycle_items if str(item.get("selection_level")) == "strong_keep"]
    assert strong_cycle_items
    assert all(str(item.get("mapping_type")) == "endpoint_geometry" for item in strong_cycle_items)
    assert all("rank_gap" in item for item in strong_cycle_items)


@pytest.mark.parametrize(
    "edge_type",
    ("connected_both_ends", "dead_end_one_side", "dead_end_both_sides", "cycle"),
)
def test_group_internal_lateral_candidates_cover_all_supported_edge_types(edge_type: str) -> None:
    """四类 edge_type 都必须能在组内相邻 sweep 之间生成 same-side lateral candidates。"""

    sweep_group_info = {
        "groups": (
            {
                "group_id": 17,
                "coverage_lane_id": 7,
                "source_edge_id": 70,
                "edge_type": edge_type,
                "src_node_id": 5,
                "dst_node_id": 6,
                "ordered_sweep_ids": [101, 102, 103],
                "center_sweep_id": 102,
                "center_sweep_index": 1,
                "sweep_count": 3,
                "main_direction": [1.0, 0.0],
            },
        ),
        "group_by_edge_id": {
            70: {
                "group_id": 17,
                "coverage_lane_id": 7,
                "source_edge_id": 70,
                "edge_type": edge_type,
                "src_node_id": 5,
                "dst_node_id": 6,
                "ordered_sweep_ids": [101, 102, 103],
                "center_sweep_id": 102,
                "center_sweep_index": 1,
                "sweep_count": 3,
                "main_direction": [1.0, 0.0],
            },
        },
    }
    sweep_port_view_info = {
        "items": (
            {
                "group_id": 17,
                "coverage_lane_id": 7,
                "node_id": 5,
                "port_side": "src",
                "ordered_port_sweep_ids": [101, 102, 103],
                "port_rank_by_sweep_id": {101: 0, 102: 1, 103: 2},
                "center_port_rank": 1,
            },
            {
                "group_id": 17,
                "coverage_lane_id": 7,
                "node_id": 6,
                "port_side": "dst",
                "ordered_port_sweep_ids": [101, 102, 103],
                "port_rank_by_sweep_id": {101: 0, 102: 1, 103: 2},
                "center_port_rank": 1,
            },
        ),
        "lookup": {
            (17, 5, "src"): {
                "group_id": 17,
                "coverage_lane_id": 7,
                "node_id": 5,
                "port_side": "src",
                "ordered_port_sweep_ids": [101, 102, 103],
                "port_rank_by_sweep_id": {101: 0, 102: 1, 103: 2},
                "center_port_rank": 1,
            },
            (17, 6, "dst"): {
                "group_id": 17,
                "coverage_lane_id": 7,
                "node_id": 6,
                "port_side": "dst",
                "ordered_port_sweep_ids": [101, 102, 103],
                "port_rank_by_sweep_id": {101: 0, 102: 1, 103: 2},
                "center_port_rank": 1,
            },
        },
    }
    sweeps = (
        {"sweep_id": 101, "coverage_lane_id": 7, "source_edge_id": 70, "path_rc": ((0.0, 0.0), (10.0, 0.0)), "path_length_m": 1.0, "mean_offset_m": -1.0, "resolution_m_per_px": 0.05, "active": True},
        {"sweep_id": 102, "coverage_lane_id": 7, "source_edge_id": 70, "path_rc": ((0.0, 1.0), (10.0, 1.0)), "path_length_m": 1.0, "mean_offset_m": 0.0, "resolution_m_per_px": 0.05, "active": True},
        {"sweep_id": 103, "coverage_lane_id": 7, "source_edge_id": 70, "path_rc": ((0.0, 2.0), (10.0, 2.0)), "path_length_m": 1.0, "mean_offset_m": 1.0, "resolution_m_per_px": 0.05, "active": True},
    )

    candidate_info = build_sweep_transition_candidates(
        sweep_group_info=sweep_group_info,
        sweep_port_view_info=sweep_port_view_info,
        sweeps=sweeps,
        node_local_connection_hypothesis_info={"items": ()},
    )

    lateral_items = [item for item in candidate_info["items"] if str(item.get("candidate_source")) == "group_internal"]
    assert len(lateral_items) == 12
    assert all(str(item.get("connection_kind")) == "forward" for item in lateral_items)
    assert all(str(item.get("from_end_type")) == str(item.get("to_end_type")) for item in lateral_items)
    assert {str(item.get("from_end_type")) for item in lateral_items} == {"src", "dst"}
    assert all(int(item.get("rank_gap", -1)) in {1, 2} for item in lateral_items)
    assert all(str(item.get("selection_level")) == "strong_keep" for item in lateral_items)


def test_final_coverage_path_summary_counts_connector_kinds() -> None:
    """FinalCoveragePath summary 必须显式统计 forward / foldback 两类 connector_kind。"""

    summary = build_final_coverage_path_summary(
        path_routes=(
            {"path_length_px": 10.0},
            {"path_length_px": 5.0},
        ),
        all_connections=(
            {"connector_kind": "forward", "is_foldback": False},
            {"connector_kind": "forward", "is_foldback": False},
            {"connector_kind": "foldback", "is_foldback": True},
            {"connector_kind": "foldback", "is_foldback": True},
        ),
        resolution_m_per_px=0.05,
    )

    assert summary["junction_connection_count"] == 4
    assert summary["forward_connection_count"] == 2
    assert summary["foldback_connection_count"] == 2
    assert True
    assert True
    assert True
    assert summary["path_length_m"] == 0.75


def test_resolve_sweep_transition_candidates_reads_candidate_items() -> None:
    """统一 helper 只读取正式 candidate items。"""

    sweep_graph_build_info = _make_sweep_graph_build_info(
        tuple(),
        (
            {
                "candidate_id": 7,
                "source_hypothesis_id": 5,
                "candidate_source": "node_projected",
                "via_node_id": 3,
                "from_sweep_id": 101,
                "to_sweep_id": 102,
                "from_end_type": "src",
                "to_end_type": "dst",
                "connection_kind": "forward",
                "motion_type": "straight",
                "mapping_type": "aligned",
                "selection_level": "strong_keep",
                "risk_score": 0.1,
                "coverage_gain_score": 0.8,
                "total_score": 0.9,
                "confidence_score": 0.7,
                "rank_gap": 1,
                "endpoint_distance_m": 2.0,
                "trace_tags": ("node_projected",),
                "source_trace_label": "node_projected",
            },
        ),
    )

    transitions = resolve_sweep_transition_candidates(sweep_graph_build_info)
    assert len(transitions) == 1
    assert transitions[0]["candidate_id"] == 7
    assert transitions[0]["from_sweep_id"] == 101
    assert transitions[0]["to_sweep_id"] == 102
    assert transitions[0]["mapping_type"] == "aligned"


def test_render_sweep_node_snap_overlay_smoke() -> None:
    """sweep node snap overlay 至少应能稳定渲染成功/失败 anchor 图层。"""

    gray = np.zeros((40, 60), dtype=np.uint8)
    geometry_result = GeometryPreparationResult(
        gray=gray,
        region_mask=np.ones_like(gray, dtype=np.uint8) * 255,
        free_mask=np.ones_like(gray, dtype=np.uint8) * 255,
        obstacle_mask=np.zeros_like(gray, dtype=np.uint8),
        after_open_mask=np.ones_like(gray, dtype=np.uint8) * 255,
        skeleton_mask=np.zeros_like(gray, dtype=np.uint8),
        skeleton_pruned_mask=np.zeros_like(gray, dtype=np.uint8),
        skeleton_pixels_rc=tuple(),
        crop_box_px=(0, 0, 60, 40),
        resolution_m_per_px=0.05,
    )
    edge = EdgeInfo(
        edge_id=1,
        src_node_id=1,
        dst_node_id=2,
        outer_path_rc=((10.0, 10.0), (10.0, 40.0)),
        inner_path_rc=tuple(),
        path_rc=((10.0, 10.0), (10.0, 40.0)),
        edge_type="connected_both_ends",
    )
    edge.coverage_info = {"coverage_lane_id": 1}
    lane_item = {
        "coverage_lane_id": 1,
        "source_edge_id": 1,
        "debug_info": {
            "sampling_step_px": 6,
            "sweep_layout_debug": {
                "normal_search_px": 4,
                "center_reference_path_rc": [[12.0, 12.0], [12.0, 38.0]],
                "anchors": (
                    {
                        "anchor_index": 0,
                        "anchor_rc": [10.0, 12.0],
                        "center_point_rc": [12.0, 12.0],
                        "offset_min_px": -2,
                        "offset_max_px": 2,
                    },
                    {
                        "anchor_index": 1,
                        "anchor_rc": [10.0, 18.0],
                        "center_point_rc": [12.0, 18.0],
                        "offset_min_px": -2,
                        "offset_max_px": 2,
                    },
                ),
                "failed_anchor_index": 2,
                "failed_reason": "center_point_invalid",
            },
        },
    }
    result = CoveragePlanningResult(
        graph_info=GraphInfo(nodes=tuple(), edges=(edge,)),
        coverage_lane_sweep_info=CoverageLaneSweepBuildInfo(
            coverage_lane_info=(lane_item,),
            sweeps=tuple(),
            summary={},
            validation_info={},
        ),
    )

    image = render_sweep_node_snap_overlay(geometry_result, result, render_scale=4)

    assert image.shape == (160, 240, 3)
    assert int(np.count_nonzero(image)) > 0
