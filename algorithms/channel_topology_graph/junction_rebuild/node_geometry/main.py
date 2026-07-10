"""交汇几何重建核心逻辑。

这里不再使用保守 polygon 启发式，而是直接贴现有 `07_5` 研究算法主线：
1. 基于旧中心集合和修剪后骨架提取 outward exits；
2. 在每条 exit 上按稳定方向规则求截断点；
3. 用截断点构造 branches，再做 sector/support 求解；
4. 先跑 round1，再按 polygon centroid 决定是否跑 round2；
5. 把最终 polygon 写回 `node_info`，并把截断点结果登记到边运行时状态。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ...contracts import EdgeInfo, GeometryPreparationResult, NodeInfo
from .. import geometry_core as geomcore
from .debug import initial_point_rc as _initial_point_rc
from .edge_mapping import (
    match_exits_to_incident_edges as _match_exits_to_incident_edges,
    write_endpoint_truncation_runtime as _write_endpoint_truncation_runtime,
)
from .support import solve_truncation_points
from .workflow import (
    apply_dead_end_geometry as _apply_dead_end_geometry,
    apply_junction_geometry_result as _apply_junction_geometry_result,
    build_geometry_debug_payload as _build_geometry_debug_payload,
    load_geometry_config as _load_geometry_config,
    run_geometry_rounds as _run_geometry_rounds,
)


def merged_old_centers(node: NodeInfo, node_runtime: dict[int, dict[str, Any]]) -> list[tuple[int, int]]:
    """从 merge lineage 恢复当前节点对应的旧中心集合。"""

    # merged_member_node_ids 定义了这个 junction 由哪些旧节点合并而来。
    merged_member_node_ids = tuple(
        int(node_id)
        for node_id in node_runtime.get(int(node.node_id), {}).get("merged_member_node_ids", (int(node.node_id),))
    )
    # 旧中心统一从 runtime 初始记录恢复，不读取已经被更新过的 node.point_rc。
    return [_initial_point_rc(node_runtime, int(member_id)) for member_id in merged_member_node_ids]


def rebuild_node_geometry(
    geometry_result: GeometryPreparationResult,
    node_map: dict[int, NodeInfo],
    edge_map: dict[int, EdgeInfo],
    node_runtime: dict[int, dict[str, Any]],
    edge_runtime: dict[int, dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """为有效节点解算正式中心、polygon 与截断点。

    真实职责：
        junction_rebuild 节点几何不是“看 incident edges 画个保守 polygon”，而是沿用
        已确认的 `07_5` 交汇几何主链。对每个有效交汇节点，都要真正完成：
        1. outward exits 提取；
        2. 截断点求解；
        3. support/sector 评估；
        4. round1/round2 中心更新；
        5. polygon 写回；
        6. 截断信息登记到边运行时状态。

    Args:
        geometry_result:
            geometry_preparation 正式输出。这里直接消费自由空间掩膜和修剪后骨架像素。
        node_map:
            节点对象表。函数会原地更新节点中心与 polygon。
        edge_map:
            边对象表。这里用于读取当前 incident edge 的方向语义。
        node_runtime:
            节点运行时状态。这里读取 merge lineage，并写入节点几何调试信息。
        edge_runtime:
            边运行时状态。这里会把每个节点端的截断点结果写回，供后续边切分使用。
        config:
            junction_rebuild 阶段配置。所有长度门限都已经缩回运行尺度，不允许再混入 8x。

    Returns:
        dict[str, Any]:
            节点几何阶段摘要，便于 junction_rebuild 整体调试和统计。
    """

    params = _load_geometry_config(geometry_result, config)
    free_mask01 = np.where(np.asarray(geometry_result.free_mask) > 0, 1, 0).astype(np.uint8)
    skeleton_points_global = {tuple(map(int, point_rc)) for point_rc in geometry_result.skeleton_pixels_rc}
    # free_mask 与 skeleton 都在这里统一转成阶段内可直接消费的格式。
    # 这样循环内部不再重复做 numpy/set 转换。
    # 这也让阶段内所有节点共享同一份骨架真值视图。
    # 同时，后续 geometry_core 子链也不需要再关心输入格式适配。

    polygon_node_count = 0
    truncation_node_count = 0
    round2_node_count = 0
    for node_id, node in node_map.items():
        # inactive 节点已经退出正式求解链，不再重复处理几何。
        if not bool(node_runtime.get(node_id, {}).get("active", False)):
            continue

        if node.node_type != "junction":
            # dead_end 只写最小占据区，不进入交汇主链。
            _apply_dead_end_geometry(node, float(params["dead_end_polygon_radius_px"]))
            continue

        # junction 节点必须完整跑一遍 exits -> truncation -> support -> polygon 主链。
        # 这里不再保留历史上的保守 polygon 旁路。
        # 任何失败都应该以显式 failed 状态暴露，而不是悄悄降级。
        # 因而每个有效 junction 都会在这里触发一次完整节点级求解。
        geometry_debug = solve_junction_node_geometry(
            geometry_result=geometry_result,
            node=node,
            edge_map=edge_map,
            node_runtime=node_runtime,
            edge_runtime=edge_runtime,
            skeleton_points_global=skeleton_points_global,
            free_mask01=free_mask01,
            margin_px=int(params["margin_px"]),
            cut_min_px=float(params["cut_min_px"]),
            cut_probe_px=float(params["cut_probe_px"]),
            cut_verify_px=float(params["cut_verify_px"]),
            stable_angle_deg=float(params["stable_angle_deg"]),
            single_center_extra_push_px=float(params["single_center_extra_push_px"]),
            recenter_threshold_px=float(params["recenter_threshold_px"]),
            ray_step_deg=float(params["ray_step_deg"]),
            ray_max_radius_px=int(params["ray_max_radius_px"]),
            include_truncation_debug=bool(params["include_truncation_debug"]),
        )
        if geometry_debug is None:
            # 如果完整几何求解失败，不能偷偷退回启发式 polygon。
            # 这种情况应直接暴露成调试信息，后续由测试或真实数据核查。
            node_runtime[node_id]["junction_geometry_status"] = "failed"
            continue

        # 成功结果统一通过 workflow helper 写回节点与 runtime。
        # 计数器只统计真正完成正式落盘的 junction 节点。
        # 节点对象和 runtime 状态会在这一刻一起切到“已完成”。
        _apply_junction_geometry_result(node, node_runtime, node_id, geometry_debug)
        polygon_node_count += 1
        truncation_node_count += 1
        if bool(geometry_debug["round2_applied"]):
            # round2 是否发生直接从调试结果读取，不再额外推断。
            round2_node_count += 1

    # 阶段摘要只输出节点级统计，不混入每节点的细节调试信息。
    # 更细的解释统一留在各节点的 `debug_info["junction_geometry"]`。
    # 这样阶段摘要适合做总览，而不是承担过程解释。
    return {
        "polygon_node_count": polygon_node_count,
        "truncation_node_count": truncation_node_count,
        "round2_node_count": round2_node_count,
        "active_node_count": int(sum(1 for item in node_runtime.values() if bool(item.get("active", False)))),
    }


def solve_junction_node_geometry(
    geometry_result: GeometryPreparationResult,
    node: NodeInfo,
    edge_map: dict[int, EdgeInfo],
    node_runtime: dict[int, dict[str, Any]],
    edge_runtime: dict[int, dict[str, Any]],
    skeleton_points_global: set[tuple[int, int]],
    free_mask01: np.ndarray,
    margin_px: int,
    cut_min_px: float,
    cut_probe_px: float,
    cut_verify_px: float,
    stable_angle_deg: float,
    single_center_extra_push_px: float,
    recenter_threshold_px: float,
    ray_step_deg: float,
    ray_max_radius_px: int,
    include_truncation_debug: bool = True,
) -> dict[str, Any] | None:
    """为单个交汇节点运行完整 `07_5` 节点几何链。

    真实职责：
        这个函数把“研究脚本里的多段逻辑”收成一个节点级步骤，但算法本意不变：
        先从旧中心集合恢复 exits，再解截断点、support、polygon，最后把结果映射到
        当前 `node_info / edge_info` 体系中。
    """

    old_centers = merged_old_centers(node, node_runtime)
    local_ctx = geomcore.build_local_context(
        old_points_global=[tuple(map(int, point_rc)) for point_rc in old_centers],
        new_center_global=(int(round(node.point_rc[0])), int(round(node.point_rc[1]))),
        skeleton_points_global=skeleton_points_global,
        shape_hw=geometry_result.gray.shape[:2],
        margin_px=margin_px,
    )
    # local_ctx 是 geometry_core 子模块共享的局部世界描述。
    # 旧中心、新中心和窗口内骨架都在这里统一收口。
    # 这样 clustered/single-exit/support 子链拿到的是完全一致的局部口径。
    # 局部窗口一旦确定，后续节点级求解就都围绕这份上下文展开。

    # 先从局部上下文里恢复 outward exits，这是后续所有求解的基础真值。
    exits = solve_truncation_points(
        local_ctx=local_ctx,
        old_centers=old_centers,
        cut_min_px=cut_min_px,
        cut_probe_px=cut_probe_px,
        cut_verify_px=cut_verify_px,
        stable_angle_deg=stable_angle_deg,
        single_center_extra_push_px=single_center_extra_push_px,
    )
    # 少于 3 条 outward exits 时，无法围出稳定的 junction polygon。
    if len(exits) < 3:
        # 这里失败表示几何证据不足，而不是某个后处理 helper 报错。
        return None
    # 这里的失败意味着几何证据不足，而不是某个后处理步骤出错。

    # 两轮 support-polygon 求解统一委托给 workflow helper，主文件只保留装配关系。
    # 这样 node_geometry/main.py 只负责“串联哪些步骤”，不再展开 round 细节。
    # round1/round2 的回落与调试字段组织全部在 workflow 文件内完成。
    # 主文件因此更专注于节点级流程边界，而不是局部算子细节。
    round_result = _run_geometry_rounds(
        node=node,
        exits=exits,
        free_mask01=free_mask01,
        recenter_threshold_px=recenter_threshold_px,
        ray_step_deg=ray_step_deg,
        ray_max_radius_px=ray_max_radius_px,
        include_truncation_debug=include_truncation_debug,
    )
    if round_result is None:
        # round 失败后不再尝试启发式补边界，避免把非主线语义重新带回正式输出。
        return None
    # 能走到这里说明当前节点已经拿到了有效 polygon 与最终中心。

    # edge mapping 负责把几何 exit 顺序重新对齐到正式 incident edge。
    # 这一步把 research 里的几何出口顺序翻译回当前 edge_id 空间。
    # 这是把几何求解结果接回现有图结构合同的关键桥接步骤。
    edge_mapping = _match_exits_to_incident_edges(
        node=node,
        edge_map=edge_map,
        edge_runtime=edge_runtime,
        exits=exits,
    )
    # 截断点运行时结果必须和最终 node center 一起写回，供后续边切分复用。
    # 后续 edge_geometry 阶段不会重新推导这些节点端截断点。
    # 这也是 node_geometry 与 edge_geometry 之间最关键的显式契约。
    # 若这里不写回，后续边切分就会退化成缺少节点端几何约束的状态。
    _write_endpoint_truncation_runtime(
        node=node,
        final_node_center_rc=round_result["polygon_centroid2"],
        exits=exits,
        edge_mapping=edge_mapping,
        edge_map=edge_map,
        edge_runtime=edge_runtime,
    )

    # 返回调试载荷而不是直接回传对象，保持与现有 debug_info 序列化口径一致。
    # 这也是节点对象与运行时对象之间唯一共享的解释性结果。
    # 因而上层既可以把它写入 node.debug_info，也可以拿去做 detail 可视化。
    return _build_geometry_debug_payload(old_centers, round_result, edge_mapping)
