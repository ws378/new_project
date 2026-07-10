"""节点几何主流程里的配置、轮次执行与结果落盘 helper。"""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np

from ...contracts import GeometryPreparationResult, NodeInfo
from .debug import (
    sector_to_debug_dict as _sector_to_debug_dict,
    solve_dead_end_polygon as _solve_dead_end_polygon,
)
from .support import evaluate_geometry_round as _evaluate_geometry_round


def load_geometry_config(
    geometry_result: GeometryPreparationResult,
    config: dict[str, Any] | None,
) -> dict[str, float | int]:
    """读取节点几何阶段配置，并完成运行尺度换算。"""

    if config is None:
        config = {}
    # 这里所有长度门限都必须已经回到运行尺度，不允许再混入 8x 常量。
    # 统一在这里做一次配置收口，避免主流程里散落默认值。
    # 这样同一阶段所有节点都会共享完全一致的门限口径。
    recenter_threshold_m = float(config.get("recenter_threshold_m", 0.1))
    # 返回字典只保留本阶段真正消费的参数。
    # 下游 helper 不再自己读取 config，防止不同分支默认值漂移。
    # 配置收口后，主流程只做参数透传，不再关心默认值来源。
    return {
        "margin_px": int(config.get("junction_local_margin_px", 14)),
        "cut_min_px": float(config.get("cut_min_px", 22.0)),
        "cut_probe_px": float(config.get("cut_probe_px", 8.0)),
        "cut_verify_px": float(config.get("cut_verify_px", 24.0)),
        "stable_angle_deg": float(config.get("stable_angle_deg", 12.0)),
        "single_center_extra_push_px": float(config.get("single_center_extra_push_px", 15.0)),
        "recenter_threshold_px": float(recenter_threshold_m) / float(geometry_result.resolution_m_per_px),
        "ray_step_deg": float(config.get("ray_step_deg", 1.0)),
        # 旧研究主线这里是 420px@8x，对应运行尺度约 53px。
        "ray_max_radius_px": int(config.get("ray_max_radius_px", 53)),
        "dead_end_polygon_radius_px": float(config.get("dead_end_polygon_radius_px", 4.0)),
        "include_truncation_debug": bool(config.get("include_truncation_debug", True)),
    }


def run_geometry_rounds(
    node: NodeInfo,
    exits,
    free_mask01: np.ndarray,
    recenter_threshold_px: float,
    ray_step_deg: float,
    ray_max_radius_px: int,
    include_truncation_debug: bool = True,
) -> dict[str, Any] | None:
    """围绕 round1/round2 规则运行 support-polygon 求解。"""

    # round1 始终从当前节点中心出发，得到首轮 polygon 与 centroid。
    round1_eval, round1_truncation_items, polygon_centroid1 = _evaluate_geometry_round(
        center_rc=tuple(map(float, node.point_rc)),
        exits=exits,
        free_mask01=free_mask01,
        ray_step_deg=ray_step_deg,
        ray_max_radius_px=ray_max_radius_px,
        include_truncation_debug=include_truncation_debug,
    )
    # round1 一旦失败，说明当前中心下连基本 support polygon 都构不出来。
    # 这种失败应原样向上传递，不做启发式补救。
    if round1_eval is None or polygon_centroid1 is None:
        return None
    # polygon 顶点不足三点时，即使评估对象存在，也不能当作有效闭环边界。
    if len(round1_eval.polygon_vertices_rc) < 3:
        return None

    # centroid 与 round1 center 的距离决定是否需要 round2 recenter。
    # 这里比较的是 polygon 几何中心与评估中心的偏移，而不是某个 branch 的局部误差。
    dist_px = math.hypot(
        float(polygon_centroid1[0] - round1_eval.center_rc[0]),
        float(polygon_centroid1[1] - round1_eval.center_rc[1]),
    )
    use_round2 = dist_px > recenter_threshold_px
    round2_center_rc = polygon_centroid1 if use_round2 else tuple(map(float, round1_eval.center_rc))

    # round2 仅在需要 recenter 时重新围绕 centroid 再解一轮。
    # 若 round1 已经足够接近 polygon centroid，则第二轮没有必要再跑。
    # 这一步保持和研究脚本一致：round2 的唯一作用就是围绕 centroid 再评估一次。
    round2_eval, round2_truncation_items, polygon_centroid2 = _evaluate_geometry_round(
        center_rc=round2_center_rc,
        exits=exits,
        free_mask01=free_mask01,
        ray_step_deg=ray_step_deg,
        ray_max_radius_px=ray_max_radius_px,
        include_truncation_debug=include_truncation_debug,
    )
    # round2 失败时直接回落 round1，不再偷偷引入其它启发式 polygon。
    # 这样可以保证所有成功结果都仍然来自 support 主链。
    # 回落后仍然保留 round1 的截断明细，避免 debug 字段出现半空状态。
    if round2_eval is None or polygon_centroid2 is None:
        round2_eval = round1_eval
        round2_truncation_items = round1_truncation_items
        polygon_centroid2 = polygon_centroid1
        use_round2 = False
        # 回落 round1 的含义是“recenter 这件事失败了”，不是“整个节点几何失败了”。
    elif len(round2_eval.polygon_vertices_rc) < 3:
        return None

    # 返回值把两轮求解所需关键信息集中起来，供外层继续写 runtime/debug。
    # 这里保留 round1/round2 两轮信息，方便后续过程记录与基线解释。
    # 外层不需要再推导 round 关系，只消费这份结构化结果即可。
    # 因而这份结果同时承担“主流程接口”和“调试中间态缓存”两种职责。
    # round helper 到这里就结束，不再直接触碰 node/edge 对象本身。
    return {
        "round1_eval": round1_eval,
        "round1_truncation_items": round1_truncation_items,
        "polygon_centroid1": polygon_centroid1,
        "round1_center_to_polygon_dist_px": float(dist_px),
        "use_round2": bool(use_round2),
        "round2_eval": round2_eval,
        "round2_truncation_items": round2_truncation_items,
        "polygon_centroid2": polygon_centroid2,
    }


def build_geometry_debug_payload(
    old_centers: list[tuple[int, int]],
    round_result: dict[str, Any],
    edge_mapping: dict[int, int],
    sector_debug_encoder: Callable[[Any], dict[str, Any]] = _sector_to_debug_dict,
) -> dict[str, Any]:
    """把节点几何主链结果整理成调试载荷。"""

    round1_eval = round_result["round1_eval"]
    round2_eval = round_result["round2_eval"]
    polygon_centroid1 = round_result["polygon_centroid1"]
    polygon_centroid2 = round_result["polygon_centroid2"]
    # 调试载荷既保留 round1/round2 关键信息，也保留最终 support sector 明细。
    # 这里统一转成 list/float/dict，确保 debug_info 可以稳定序列化。
    # `edge_mapping` 也在这里一起写入，避免调试时跨 runtime/debug 两处拼信息。
    # 返回值口径直接对齐现有 node.debug_info 结构，不引入二次适配层。
    # 这样过程记录文档也可以直接消费这份字典，不必再做字段转译。
    # 一旦 debug 结构要扩展，也只需要在这里集中调整。
    # 这也是节点几何过程记录唯一的结构化真值出口。
    # 上层若要落 JSON 或渲染 detail 图，都可以直接复用这份字典。
    return {
        "old_centers_rc": [list(map(int, point_rc)) for point_rc in old_centers],
        "round1_center_rc": [float(round1_eval.center_rc[0]), float(round1_eval.center_rc[1])],
        "round1_polygon_centroid_rc": [float(polygon_centroid1[0]), float(polygon_centroid1[1])],
        "round1_center_to_polygon_dist_px": float(round_result["round1_center_to_polygon_dist_px"]),
        "round2_applied": bool(round_result["use_round2"]),
        "evaluation_center_rc": [float(round2_eval.center_rc[0]), float(round2_eval.center_rc[1])],
        "final_node_center_rc": [float(polygon_centroid2[0]), float(polygon_centroid2[1])],
        "polygon_vertices_rc": [list(map(float, point_rc)) for point_rc in round2_eval.polygon_vertices_rc],
        "support_sectors": [sector_debug_encoder(sector) for sector in round2_eval.sectors],
        "truncation": round_result["round2_truncation_items"],
        "edge_mapping": {str(edge_id): int(exit_index) for edge_id, exit_index in edge_mapping.items()},
        "polygon_source": "support",
    }


def apply_dead_end_geometry(node: NodeInfo, dead_end_polygon_radius_px: float) -> None:
    """为 dead_end 节点写入最小占据 polygon。"""

    # 断头路节点不走交汇 polygon 主链，但仍需要一个最小节点占据区。
    # 这个占据区只服务边分段和后续区域约束，不代表交汇结构。
    node.polygon_vertices_rc = tuple(_solve_dead_end_polygon(node.point_rc, dead_end_polygon_radius_px))


def apply_junction_geometry_result(
    node: NodeInfo,
    node_runtime: dict[int, dict[str, Any]],
    node_id: int,
    geometry_debug: dict[str, Any],
) -> None:
    """把成功求解出的中心与 polygon 正式写回节点。"""

    # 节点中心最终使用 polygon centroid，而不是 round 求值时的 evaluation center。
    node.point_rc = tuple(map(float, geometry_debug["final_node_center_rc"]))
    # polygon 顶点统一转成浮点 rc，保持和合同字段口径一致。
    node.polygon_vertices_rc = tuple(tuple(map(float, point_rc)) for point_rc in geometry_debug["polygon_vertices_rc"])
    # debug_info 保留整条节点几何主链结果，方便基线比对和失败定位。
    node.debug_info = {
        **(node.debug_info or {}),
        "junction_geometry": geometry_debug,
    }
    # 状态写回 runtime，供阶段摘要和失败排查统一读取。
    # 正式 node 对象与 runtime 状态因此会在这一刻同步切到“已完成”。
    node_runtime[node_id]["junction_geometry_status"] = "ok"


__all__ = (
    "load_geometry_config",
    "run_geometry_rounds",
    "build_geometry_debug_payload",
    "apply_dead_end_geometry",
    "apply_junction_geometry_result",
)
