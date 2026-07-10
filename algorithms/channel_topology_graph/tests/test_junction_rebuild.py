"""JunctionRebuild 测试。"""

from __future__ import annotations

import math
from collections import deque
from pathlib import Path

import numpy as np

from algorithms.channel_topology_graph.coverage_planning.coverage_lane_sweep.lane_regions import (
    derive_outer_path_owner_map,
    find_seed_points_in_mask,
)
from algorithms.channel_topology_graph.contracts import EdgeInfo, GraphInfo, NodeInfo
from algorithms.channel_topology_graph.junction_rebuild.geometry_core.common import (
    SectorModel,
)
from algorithms.channel_topology_graph.junction_rebuild.geometry_core.branch_support import (
    ray_first_hit,
    ray_first_hits,
)
from algorithms.channel_topology_graph.junction_rebuild.geometry_core.sector_refine import (
    refine_edge_endpoints_from_neighbors,
)
from algorithms.channel_topology_graph.junction_rebuild.initial_node_edge.node_builder import (
    derive_initial_nodes,
)
from algorithms.channel_topology_graph.junction_rebuild.initial_node_edge.node_candidates import (
    derive_initial_junction_candidates,
)
from algorithms.channel_topology_graph.junction_rebuild.initial_node_edge.pure_cycle import (
    chainify_cycle_residual,
    find_best_cycle_cut_and_paths,
)
from algorithms.channel_topology_graph.junction_rebuild.node_merge.apply import apply_node_merges
from algorithms.channel_topology_graph.junction_rebuild.node_merge.post_geometry import (
    derive_post_geometry_merge_candidates,
    derive_post_geometry_merge_groups,
    derive_post_split_geometry_anomalies,
)
from algorithms.channel_topology_graph.renderers.junction_renderers import (
    write_junction_rebuild_visualizations,
)
from algorithms.channel_topology_graph.stages.geometry_preparation import build_geometry_preparation
from algorithms.channel_topology_graph.stages.junction_rebuild import (
    build_junction_rebuild,
    build_post_geometry_merge_outputs,
)


def build_cross_map(height: int = 80, width: int = 80) -> np.ndarray:
    """构造一个十字通道测试图。"""

    raw = np.zeros((height, width), dtype=np.uint8)
    raw[10:70, 36:44] = 255
    raw[36:44, 10:70] = 255
    return raw


def build_double_junction_map(height: int = 100, width: int = 100) -> np.ndarray:
    """构造两个近距离交汇相连的测试图。"""

    raw = np.zeros((height, width), dtype=np.uint8)
    raw[18:82, 46:54] = 255
    raw[30:38, 16:54] = 255
    raw[62:70, 46:84] = 255
    raw[46:54, 46:54] = 255
    return raw


def build_ring_cycle_map(size: int = 80) -> np.ndarray:
    """构造一个无路口、无断头路的纯回环测试图。"""

    raw = np.zeros((size, size), dtype=np.uint8)
    raw[10:70, 10:70] = 255
    raw[22:58, 22:58] = 0
    return raw


def _reference_owner_map(graph_info: GraphInfo, constrained_free_mask: np.ndarray) -> np.ndarray:
    owner_map = np.full(constrained_free_mask.shape, -1, dtype=np.int32)
    queue: deque[tuple[int, int, int]] = deque()
    for edge in graph_info.edges:
        for row, col in find_seed_points_in_mask(edge.outer_path_rc, constrained_free_mask):
            if owner_map[row, col] >= 0:
                continue
            owner_map[row, col] = int(edge.edge_id)
            queue.append((int(row), int(col), int(edge.edge_id)))

    height, width = constrained_free_mask.shape
    while queue:
        row, col, edge_id = queue.popleft()
        for d_row in (-1, 0, 1):
            for d_col in (-1, 0, 1):
                if d_row == 0 and d_col == 0:
                    continue
                next_row = row + d_row
                next_col = col + d_col
                if next_row < 0 or next_row >= height or next_col < 0 or next_col >= width:
                    continue
                if constrained_free_mask[next_row, next_col] == 0 or owner_map[next_row, next_col] >= 0:
                    continue
                owner_map[next_row, next_col] = edge_id
                queue.append((next_row, next_col, edge_id))
    return owner_map


def _build_geometry(raw: np.ndarray):
    """统一构造 geometry_preparation 结果。"""

    return build_geometry_preparation(
        raw_map={"gray": raw, "resolution_m_per_px": 0.05},
        config={"open_kernel_px": 1, "short_side_branch_px": 6},
    )


def test_build_junction_rebuild_returns_node_and_edge_outputs() -> None:
    """JunctionRebuild 应输出合法的节点和边。"""

    geometry_result = _build_geometry(build_cross_map())
    result = build_junction_rebuild(
        geometry_preparation_result=geometry_result,
        config={
            "intersection_merge_geodesic_px": 12,
            "summary_viz": False,
            "detail_viz": False,
        },
    )

    assert len(result.node_info_list) >= 5
    assert len(result.edge_info_list) >= 4
    assert all(item.degree == len(item.incident_edge_ids) for item in result.node_info_list)
    assert all(item.path_rc for item in result.edge_info_list)
    assert all(item.edge_type is not None for item in result.edge_info_list)

    assert all(hasattr(item, "is_virtual") for item in result.node_info_list)
    assert all(item.is_virtual is False for item in result.node_info_list)
    assert all(item.virtual_reason is None for item in result.node_info_list)


def test_derive_initial_junction_candidates_returns_internal_view() -> None:
    """初始交汇候选应在正式建点前先被独立提取出来。"""

    geometry_result = _build_geometry(build_cross_map())
    candidates = derive_initial_junction_candidates(geometry_result)

    assert candidates
    assert "representative_point_rc" in candidates[0]
    assert "member_points_rc" in candidates[0]


def test_junction_nodes_carry_polygon_vertices() -> None:
    """交汇节点必须保留 polygon 顶点。"""

    geometry_result = _build_geometry(build_cross_map())
    result = build_junction_rebuild(
        geometry_preparation_result=geometry_result,
        config={"intersection_merge_geodesic_px": 12},
    )

    junctions = [item for item in result.node_info_list if item.node_type == "junction"]
    assert junctions
    assert all(item.polygon_vertices_rc for item in junctions)
    assert all((item.debug_info or {}).get("junction_geometry") is not None for item in junctions)


def test_junction_geometry_debug_contains_truncation_chain() -> None:
    """交汇节点调试信息里应保留完整几何链条。"""

    geometry_result = _build_geometry(build_cross_map())
    result = build_junction_rebuild(
        geometry_preparation_result=geometry_result,
        config={"intersection_merge_geodesic_px": 12},
    )

    junctions = [item for item in result.node_info_list if item.node_type == "junction"]
    assert junctions
    geometry_debug = (junctions[0].debug_info or {})["junction_geometry"]
    assert geometry_debug["truncation"]
    assert geometry_debug["support_sectors"]
    assert geometry_debug["polygon_source"] == "support"


def test_merge_reduces_close_junction_nodes() -> None:
    """近距离双交汇应在 junction rebuild 里合并。"""

    geometry_result = _build_geometry(build_double_junction_map())
    initial_node_map, _ = derive_initial_nodes(geometry_result)
    initial_junction_count = sum(1 for item in initial_node_map.values() if item.node_type == "junction")

    result = build_junction_rebuild(
        geometry_preparation_result=geometry_result,
        config={"intersection_merge_geodesic_px": 40},
    )
    merged_junction_count = sum(1 for item in result.node_info_list if item.node_type == "junction")

    assert initial_junction_count >= 2
    assert merged_junction_count < initial_junction_count


def test_apply_node_merges_deactivates_duplicate_edges() -> None:
    """节点合并后若两条边变成同一对端点，后出现的边必须失效。"""

    node_map = {
        1: NodeInfo(node_id=1, point_rc=(10.0, 10.0), node_type="junction"),
        2: NodeInfo(node_id=2, point_rc=(10.0, 12.0), node_type="junction"),
        3: NodeInfo(node_id=3, point_rc=(20.0, 20.0), node_type="junction"),
    }
    edge_map = {
        1: EdgeInfo(edge_id=1, src_node_id=1, dst_node_id=3, path_rc=((10.0, 10.0), (20.0, 20.0))),
        2: EdgeInfo(edge_id=2, src_node_id=2, dst_node_id=3, path_rc=((10.0, 12.0), (20.0, 20.0))),
    }
    node_runtime = {
        1: {"active": True},
        2: {"active": True},
        3: {"active": True},
    }
    edge_runtime = {
        1: {"active": True, "inactive_reason": None},
        2: {"active": True, "inactive_reason": None},
    }

    debug = apply_node_merges(
        node_map=node_map,
        edge_map=edge_map,
        node_runtime=node_runtime,
        edge_runtime=edge_runtime,
        merge_groups=[[1, 2]],
    )

    assert node_runtime[2]["active"] is False
    assert edge_runtime[2]["active"] is False
    assert edge_runtime[2]["inactive_reason"] == "duplicate_after_node_merge"
    assert debug["duplicate_edge_ids_after_merge"] == [2]


def test_post_geometry_merge_candidates_merge_short_junction_edge() -> None:
    """edge split 后的交汇内部短边应回到节点合并层处理。"""

    node_map = {
        1: NodeInfo(node_id=1, point_rc=(10.0, 10.0), node_type="junction"),
        2: NodeInfo(node_id=2, point_rc=(10.0, 50.0), node_type="junction"),
    }
    edge_map = {
        10: EdgeInfo(
            edge_id=10,
            src_node_id=1,
            dst_node_id=2,
            outer_path_rc=((10.0, 20.0), (10.0, 24.0)),
            path_rc=((10.0, 10.0), (10.0, 50.0)),
            debug_info={
                "split_hits": {
                    "src_hit_index": 1,
                    "dst_hit_index": 5,
                    "src_hit_point_rc": [10.0, 20.0],
                    "dst_hit_point_rc": [10.0, 24.0],
                },
                "split_used_fallback": False,
            },
        ),
    }
    node_runtime = {1: {"active": True}, 2: {"active": True}}
    edge_runtime = {10: {"active": True}}

    candidates = derive_post_geometry_merge_candidates(
        node_map=node_map,
        edge_map=edge_map,
        node_runtime=node_runtime,
        edge_runtime=edge_runtime,
        resolution_m_per_px=0.05,
        config={
            "post_geometry_merge_outer_path_min_length_m": 0.5,
            "post_geometry_merge_full_path_max_merge_length_m": 3.0,
        },
    )

    assert len(candidates) == 1
    assert candidates[0]["action"] == "merge"
    assert candidates[0]["reason"] == "outer_path_too_short"
    assert derive_post_geometry_merge_groups(candidates) == [[1, 2]]


def test_post_geometry_merge_candidates_do_not_merge_long_split_anomaly() -> None:
    """长边被 polygon 吃掉外部段时应进入 anomaly debug，而不是直接合并。"""

    node_map = {
        1: NodeInfo(node_id=1, point_rc=(10.0, 10.0), node_type="junction"),
        2: NodeInfo(node_id=2, point_rc=(10.0, 200.0), node_type="junction"),
    }
    edge_map = {
        20: EdgeInfo(
            edge_id=20,
            src_node_id=1,
            dst_node_id=2,
            outer_path_rc=((10.0, 90.0), (10.0, 94.0)),
            path_rc=((10.0, 10.0), (10.0, 200.0)),
            debug_info={
                "split_hits": {
                    "src_hit_index": 1,
                    "dst_hit_index": 5,
                    "src_hit_point_rc": [10.0, 90.0],
                    "dst_hit_point_rc": [10.0, 94.0],
                },
                "split_used_fallback": False,
            },
        ),
    }
    node_runtime = {1: {"active": True}, 2: {"active": True}}
    edge_runtime = {20: {"active": True}}

    candidates = derive_post_split_geometry_anomalies(
        node_map=node_map,
        edge_map=edge_map,
        node_runtime=node_runtime,
        edge_runtime=edge_runtime,
        resolution_m_per_px=0.05,
        config={
            "post_geometry_merge_outer_path_min_length_m": 0.5,
            "post_geometry_merge_full_path_max_merge_length_m": 3.0,
        },
    )

    assert len(candidates) == 1
    assert candidates[0]["action"] == "debug_anomaly"
    assert candidates[0]["reason"] == "long_edge_with_tiny_outer_path"
    assert derive_post_geometry_merge_groups(candidates) == []


def test_post_geometry_merge_candidates_reject_unreliable_split_hits() -> None:
    """短 outer path 若来自 fallback split，不允许直接驱动节点合并。"""

    node_map = {
        1: NodeInfo(node_id=1, point_rc=(10.0, 10.0), node_type="junction"),
        2: NodeInfo(node_id=2, point_rc=(10.0, 50.0), node_type="junction"),
    }
    edge_map = {
        30: EdgeInfo(
            edge_id=30,
            src_node_id=1,
            dst_node_id=2,
            outer_path_rc=((10.0, 20.0), (10.0, 24.0)),
            path_rc=((10.0, 10.0), (10.0, 50.0)),
            debug_info={
                "split_hits": {
                    "src_hit_index": None,
                    "dst_hit_index": 5,
                    "src_hit_point_rc": None,
                    "dst_hit_point_rc": [10.0, 24.0],
                },
                "split_used_fallback": True,
            },
        ),
    }
    node_runtime = {1: {"active": True}, 2: {"active": True}}
    edge_runtime = {30: {"active": True}}

    merge_candidates = derive_post_geometry_merge_candidates(
        node_map=node_map,
        edge_map=edge_map,
        node_runtime=node_runtime,
        edge_runtime=edge_runtime,
        resolution_m_per_px=0.05,
        config={
            "post_geometry_merge_outer_path_min_length_m": 0.5,
            "post_geometry_merge_full_path_max_merge_length_m": 3.0,
        },
    )
    anomalies = derive_post_split_geometry_anomalies(
        node_map=node_map,
        edge_map=edge_map,
        node_runtime=node_runtime,
        edge_runtime=edge_runtime,
        resolution_m_per_px=0.05,
        config={
            "post_geometry_merge_outer_path_min_length_m": 0.5,
            "post_geometry_merge_full_path_max_merge_length_m": 3.0,
        },
    )

    assert merge_candidates == []
    assert len(anomalies) == 1
    assert anomalies[0]["reason"] == "unreliable_split_hits_for_short_outer_path"


def test_post_geometry_merge_stage_applies_merge_and_rebuilds_geometry(monkeypatch) -> None:
    """stage 接入层必须完成合并、内部边失效、几何重建和 validation。"""

    class GeometryStub:
        resolution_m_per_px = 0.05

    node_map = {
        1: NodeInfo(node_id=1, point_rc=(10.0, 10.0), node_type="junction"),
        2: NodeInfo(node_id=2, point_rc=(10.0, 50.0), node_type="junction"),
    }
    edge_map = {
        10: EdgeInfo(
            edge_id=10,
            src_node_id=1,
            dst_node_id=2,
            outer_path_rc=((10.0, 20.0), (10.0, 24.0)),
            path_rc=((10.0, 10.0), (10.0, 50.0)),
            debug_info={
                "split_hits": {
                    "src_hit_index": 1,
                    "dst_hit_index": 5,
                    "src_hit_point_rc": [10.0, 20.0],
                    "dst_hit_point_rc": [10.0, 24.0],
                },
                "split_used_fallback": False,
            },
        ),
    }
    node_runtime = {1: {"active": True}, 2: {"active": True}}
    edge_runtime = {10: {"active": True}}
    rebuild_calls: list[int] = []

    def fake_rebuild_geometry(**kwargs):
        rebuild_calls.append(1)
        return {"fake_node_rebuild_count": len(rebuild_calls)}, {"fake_edge_rebuild_count": len(rebuild_calls)}

    monkeypatch.setattr(
        "algorithms.channel_topology_graph.stages.junction_rebuild.build_junction_geometry_outputs",
        fake_rebuild_geometry,
    )

    debug, node_debug, edge_debug = build_post_geometry_merge_outputs(
        geometry_preparation_result=GeometryStub(),
        node_map=node_map,
        node_runtime=node_runtime,
        edge_map=edge_map,
        edge_runtime=edge_runtime,
        config={"max_post_geometry_merge_iterations": 2},
        node_geometry_debug={},
        edge_geometry_debug={},
    )

    assert node_runtime[2]["active"] is False
    assert edge_runtime[10]["active"] is False
    assert edge_runtime[10]["inactive_reason"] == "internal_after_post_geometry_merge"
    assert debug["iterations"][0]["applied"] is True
    assert debug["iterations"][0]["validation_info"]["valid"] is True
    assert node_debug == {"fake_node_rebuild_count": 1}
    assert edge_debug == {"fake_edge_rebuild_count": 1}


def test_refine_edge_endpoints_snaps_free_space_endpoint_back_to_hit_points() -> None:
    """edge-like 端点若被裁到自由区，必须吸附回最近命中点。

    真实职责：
        这个测试锁住 `node_37` 暴露出的同类问题：拟合端点可能在几何上看似合理，
        但如果已经落入自由区，就不能直接作为 polygon 顶点继续往下传。
    """

    free_mask = np.zeros((32, 32), dtype=np.uint8)
    free_mask[10:23, 10:23] = 255

    prev_sector = SectorModel(
        sector_index=0,
        start_theta_deg=0.0,
        end_theta_deg=90.0,
        width_deg=90.0,
        center_theta_deg=45.0,
        hit_points_rc=[(8, 8)],
        hit_distances_px=[1.0],
        hit_angles_deg=[45.0],
        min_hit_distance_px=1.0,
        mean_hit_distance_px=1.0,
        std_hit_distance_px=0.0,
        min_relpos=0.5,
        linearity=0.0,
        span_px=0.0,
        thickness_px=0.0,
        relative_span=0.0,
        focus_score=1.0,
        interior_score=1.0,
        edge_score=0.0,
        corner_score=1.0,
        chosen_type="corner-like",
        representative_point_rc=(8, 8),
        edge_endpoints_rc=[],
    )
    edge_sector = SectorModel(
        sector_index=1,
        start_theta_deg=90.0,
        end_theta_deg=180.0,
        width_deg=90.0,
        center_theta_deg=135.0,
        hit_points_rc=[(9, 8), (9, 24), (9, 26)],
        hit_distances_px=[1.0, 1.0, 1.0],
        hit_angles_deg=[100.0, 130.0, 150.0],
        min_hit_distance_px=1.0,
        mean_hit_distance_px=1.0,
        std_hit_distance_px=0.0,
        min_relpos=0.5,
        linearity=1.0,
        span_px=18.0,
        thickness_px=0.0,
        relative_span=1.0,
        focus_score=0.0,
        interior_score=0.0,
        edge_score=1.0,
        corner_score=0.0,
        chosen_type="edge-like",
        representative_point_rc=None,
        edge_endpoints_rc=[(9, 8), (9, 26)],
    )
    next_sector = SectorModel(
        sector_index=2,
        start_theta_deg=180.0,
        end_theta_deg=270.0,
        width_deg=90.0,
        center_theta_deg=225.0,
        hit_points_rc=[(8, 26)],
        hit_distances_px=[1.0],
        hit_angles_deg=[225.0],
        min_hit_distance_px=1.0,
        mean_hit_distance_px=1.0,
        std_hit_distance_px=0.0,
        min_relpos=0.5,
        linearity=0.0,
        span_px=0.0,
        thickness_px=0.0,
        relative_span=0.0,
        focus_score=1.0,
        interior_score=1.0,
        edge_score=0.0,
        corner_score=1.0,
        chosen_type="corner-like",
        representative_point_rc=(8, 26),
        edge_endpoints_rc=[],
    )

    refined = refine_edge_endpoints_from_neighbors(
        sectors=[prev_sector, edge_sector, next_sector],
        free_mask=free_mask,
    )

    assert refined[1].chosen_type == "edge-like"
    assert refined[1].edge_endpoints_rc
    assert all(free_mask[r, c] == 0 for r, c in refined[1].edge_endpoints_rc)
    assert refined[1].edge_endpoints_rc[1] in edge_sector.hit_points_rc


def test_summary_viz_only_writes_summary_artifacts(tmp_path: Path) -> None:
    """只开 summary 时不应生成 details 目录。"""

    geometry_result = _build_geometry(build_cross_map())
    output_dir = tmp_path / "summary_only"
    result = build_junction_rebuild(
        geometry_preparation_result=geometry_result,
        config={
        },
    )

    viz = write_junction_rebuild_visualizations(
        geometry_result=geometry_result,
        result=result,
        output_dir=output_dir,
        summary_viz=True,
        detail_viz=False,
        render_scale=4,
    )
    assert viz["summary_panel_path"] is not None
    assert viz["detail_dir"] is None
    assert (output_dir / "junction_rebuild_summary.png").exists()
    assert not (output_dir / "details").exists()


def test_detail_viz_writes_detail_panels(tmp_path: Path) -> None:
    """打开 detail 时应写出节点细节图。"""

    geometry_result = _build_geometry(build_cross_map())
    output_dir = tmp_path / "detail"
    result = build_junction_rebuild(
        geometry_preparation_result=geometry_result,
        config={
        },
    )

    viz = write_junction_rebuild_visualizations(
        geometry_result=geometry_result,
        result=result,
        output_dir=output_dir,
        summary_viz=False,
        detail_viz=True,
        render_scale=4,
    )
    assert viz["summary_panel_path"] is None
    assert viz["detail_dir"] is not None
    detail_dir = Path(viz["detail_dir"])
    assert detail_dir.exists()
    assert any(detail_dir.glob("node_*.png")) or any(detail_dir.glob("merge_group_*.png"))


def test_pure_cycle_map_produces_virtual_cycle_node_and_edge() -> None:
    """纯回环场景必须保留 pure_cycle_cut 虚拟节点与 self-loop edge。"""

    geometry_result = _build_geometry(build_ring_cycle_map())
    result = build_junction_rebuild(
        geometry_preparation_result=geometry_result,
        config={"intersection_merge_geodesic_px": 12, "summary_viz": False, "detail_viz": False},
    )

    assert len(result.node_info_list) == 1
    assert len(result.edge_info_list) == 1
    node = result.node_info_list[0]
    edge = result.edge_info_list[0]
    assert node.is_virtual is True
    assert node.virtual_reason == "pure_cycle_cut"
    assert node.incident_edge_ids == (1,)
    assert node.degree == 2
    assert edge.src_node_id == edge.dst_node_id == int(node.node_id)
    assert edge.edge_type == "cycle"
    assert len(edge.path_rc) >= 2
    assert len(edge.inner_path_rc) >= 2

    component_pixels = {
        tuple(map(int, point))
        for point in np.argwhere(geometry_result.skeleton_pruned_mask > 0)
    }
    outer_pixels = {
        (int(round(point[0])), int(round(point[1])))
        for point in edge.outer_path_rc
    }
    inner_pixels = {
        (int(round(point[0])), int(round(point[1])))
        for point in edge.inner_path_rc
    }
    path_pixels = {
        (int(round(point[0])), int(round(point[1])))
        for point in edge.path_rc
    }
    cut_inner_zone = {tuple(item) for item in edge.debug_info["cut_inner_zone_rc"]}
    residual01 = np.where(geometry_result.skeleton_pruned_mask > 0, 1, 0).astype(np.uint8)
    for point_rc in cut_inner_zone:
        residual01[point_rc] = 0
    normalized_residual = chainify_cycle_residual(residual01)
    normalized_residual_pixels = {
        tuple(map(int, point_rc))
        for point_rc in np.argwhere(normalized_residual > 0)
    }
    assert outer_pixels
    assert inner_pixels
    assert outer_pixels.issubset(component_pixels)
    assert normalized_residual_pixels.issubset(outer_pixels)
    assert path_pixels.issuperset(outer_pixels)


def test_pure_cycle_parallel_cut_selection_matches_sequential() -> None:
    """pure-cycle 进程并行只能改变耗时，不能改变切口和路径语义。"""

    geometry_result = _build_geometry(build_ring_cycle_map(size=120))
    skeleton01 = np.where(geometry_result.skeleton_pruned_mask > 0, 1, 0).astype(np.uint8)

    sequential = find_best_cycle_cut_and_paths(skeleton01, max_candidate_count=24, parallel_workers=0)
    parallel = find_best_cycle_cut_and_paths(skeleton01, max_candidate_count=24, parallel_workers=2)

    assert parallel == sequential


def test_ray_first_hits_matches_scalar_reference() -> None:
    """批量射线命中必须等价于标量参考实现。"""

    free_mask = np.zeros((31, 35), dtype=np.uint8)
    free_mask[3:28, 4:31] = 255
    free_mask[8:12, 17:21] = 0
    center_rc = (15, 16)

    vectorized = ray_first_hits(free_mask, center_rc, ray_step_deg=15.0, max_radius_px=20)
    reference = []
    for theta_deg in np.arange(0.0, 360.0, 15.0):
        hit_rc, hit_dist = ray_first_hit(
            free_mask,
            center_rc,
            math.radians(float(theta_deg)),
            max_radius_px=20,
        )
        reference.append((float(theta_deg), hit_rc, hit_dist))

    assert vectorized == reference


def test_outer_path_owner_map_matches_reference_bfs_for_multi_seed_component() -> None:
    """owner_map 快路径必须保持旧多源 BFS 的归属语义。"""

    free_mask = np.zeros((14, 18), dtype=np.uint8)
    free_mask[2:12, 2:16] = 255
    free_mask[6, 8] = 0
    graph_info = GraphInfo(
        nodes=(),
        edges=(
            EdgeInfo(edge_id=10, src_node_id=1, dst_node_id=2, outer_path_rc=((3.0, 3.0),)),
            EdgeInfo(edge_id=20, src_node_id=3, dst_node_id=4, outer_path_rc=((10.0, 14.0),)),
        ),
    )

    actual = derive_outer_path_owner_map(graph_info, free_mask)
    expected = _reference_owner_map(graph_info, free_mask)

    assert np.array_equal(actual, expected)


def test_outer_path_owner_map_assigns_single_seed_component_without_bfs_competition() -> None:
    """单 edge seed 连通分量应整体归属该 edge，避免无意义逐像素 BFS。"""

    free_mask = np.zeros((12, 12), dtype=np.uint8)
    free_mask[2:10, 2:10] = 255
    graph_info = GraphInfo(
        nodes=(),
        edges=(
            EdgeInfo(edge_id=7, src_node_id=1, dst_node_id=2, outer_path_rc=((4.0, 4.0),)),
        ),
    )

    actual = derive_outer_path_owner_map(graph_info, free_mask)

    assert np.all(actual[free_mask > 0] == 7)
    assert np.all(actual[free_mask == 0] == -1)
