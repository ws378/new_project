"""交汇节点几何中的 truncation 与 round 求解 helper。"""

from __future__ import annotations

from typing import Any

import numpy as np

from .. import geometry_core as geomcore


def solve_truncation_points(
    local_ctx: dict[str, Any],
    old_centers: list[tuple[int, int]],
    cut_min_px: float,
    cut_probe_px: float,
    cut_verify_px: float,
    stable_angle_deg: float,
    single_center_extra_push_px: float,
) -> list[geomcore.ExitTrace]:
    """按完整 `07_5` 逻辑为单个交汇节点求截断点。"""

    # 是否只有一个旧中心，决定了走 single-exit 还是 clustered-exit 分支。
    # 这是交汇 truncation 逻辑里最关键的分岔条件。
    if len(old_centers) == 1:
        # 单中心交汇按 residual component 提取 outward exit，这是研究算法里和
        # 多中心交汇最不同的一条分支，不能被简化成统一近邻规则。
        exits = geomcore.extract_single_center_exits(
            local_ctx=local_ctx,
            min_cut_px=cut_min_px,
            probe_px=cut_probe_px,
            verify_px=cut_verify_px,
            stable_angle_deg=stable_angle_deg,
            extra_push_px=single_center_extra_push_px,
        )
    else:
        # 多旧中心交汇沿用旧 `05` 的局部分支语义：先按旧中心附近 seed group 分组，
        # 再恢复 outward path，最后在每条 path 上做稳定方向截断。
        exits = geomcore.extract_clustered_exits(
            local_ctx=local_ctx,
            min_cut_px=cut_min_px,
            probe_px=cut_probe_px,
            verify_px=cut_verify_px,
            stable_angle_deg=stable_angle_deg,
        )
    # 无论哪条分支，最终都统一按 stable theta 排序。
    # 这样后续 round/support 求解就不必再关心来源分支。
    # 统一顺序也是后续扇区环顺序评估的前提。
    # 调试输出里看到的 exit 顺序也因此始终稳定。
    exits.sort(key=lambda item: float(item.stable_theta_deg))
    return exits


def evaluate_geometry_round(
    center_rc: tuple[float, float],
    exits: list[geomcore.ExitTrace],
    free_mask01: np.ndarray,
    ray_step_deg: float,
    ray_max_radius_px: int,
    include_truncation_debug: bool = True,
) -> tuple[Any | None, list[dict[str, Any]] | None, tuple[float, float] | None]:
    """执行一轮中心-支持联合求解。"""

    # 这层只是对 geometry_core.evaluate_round 的薄封装。
    # 对外暴露的是“best eval + 调试截断项 + polygon centroid”三元组。
    # 这样 node_geometry 主流程无需直接依赖 geometry_core 的返回细节。
    best_eval, truncation_items, polygon_centroid_rc = geomcore.evaluate_round(
        center_rc=center_rc,
        exits=exits,
        free_mask01=free_mask01,
        ray_step_deg=ray_step_deg,
        ray_max_radius_px=ray_max_radius_px,
        include_truncation_debug=include_truncation_debug,
    )
    # 没拿到 best_eval 时，三项结果都按空值返回，避免半空结构外泄。
    # 这样调用方只需要判断第一项是否为空。
    # 一旦 best_eval 存在，其余两项也保证与之对应。
    if best_eval is None:
        # 这里统一把三项都回空，避免调用方误把旧的 centroid/debug 残值当成当前轮结果。
        return None, None, None
    return best_eval, truncation_items, polygon_centroid_rc


def polygon_centroid_from_eval(best_eval: Any) -> tuple[float, float]:
    """从 candidate eval 里取 polygon centroid。"""

    # 只有 polygon 至少三点时才按真正 polygon 质心求中心。
    if len(best_eval.polygon_vertices_rc) >= 3:
        return geomcore.polygon_centroid_rc([tuple(map(float, p)) for p in best_eval.polygon_vertices_rc])
    # 否则退回 candidate center，自然兼容退化 polygon 场景。
    return tuple(map(float, best_eval.center_rc))


__all__ = (
    "solve_truncation_points",
    "evaluate_geometry_round",
    "polygon_centroid_from_eval",
)
