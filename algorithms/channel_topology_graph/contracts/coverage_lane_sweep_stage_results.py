from __future__ import annotations

"""Coverage lane 与 sweep 的 TypedDict 契约。"""

from typing import Any, TypedDict

from .edge_info import CoverageLaneWidthStats


class CoverageLaneInfoItem(TypedDict, total=False):
    """单条 coverage lane 的正式最小真值。"""

    # `coverage_lane_id` 是 coverage lane 层稳定主键，后续 sweep group 通过它把 sweeps 回收到同一 lane。
    coverage_lane_id: int
    # `source_edge_id` 表示这条 coverage lane 来源于哪条正式 graph edge，是 coverage 结果回挂 edge 的唯一依据。
    source_edge_id: int
    # `main_direction` 给出 lane 主方向标签，供 sweep 分组、端口排序和最终连接解释使用。
    main_direction: str
    # `territory_pixels` 是 edge 扩张得到的 lane 领地像素集合，只表达 lane 可管理范围，不等于最终可采样区域。
    territory_pixels: tuple[list[int], ...] | tuple[tuple[int, int], ...]
    # `effective_region_pixels` 是真正允许 sweep 取样的有效区域像素集合，已经扣除节点边界和几何约束。
    effective_region_pixels: tuple[list[int], ...] | tuple[tuple[int, int], ...]
    # `sweep_ids` 指向这条 lane 下生成的正式 sweep 集合，后续不再从像素区域反推 sweep 从属关系。
    sweep_ids: tuple[int, ...]
    # `sweep_count` 是本 lane 实际生成并挂接的 sweep 数量，用于快速校验 lane 是否有覆盖原语。
    sweep_count: int
    # `local_width_stats` 提供 lane 宽度与建议 sweep 数的局部统计摘要，不替代 sweeps 主体真值。
    local_width_stats: CoverageLaneWidthStats
    # `geometry_valid` 表示 lane 的几何区域和主体路径是否满足生成 sweep 的基本前提。
    geometry_valid: bool
    # `node_valid` 表示 lane 与两端节点/端口边界的局部约束是否通过检查。
    node_valid: bool
    # `topology_valid` 表示 lane 仍能回指到正式 edge/node 拓扑关系，没有变成孤立覆盖片段。
    topology_valid: bool
    # `active` 表示该 lane 是否进入后续 sweep 主线；False 时仍保留排除证据但不参与 graph/cadence。
    active: bool
    # `excluded_reason` 记录 inactive lane 的排除原因，active lane 应保持为空字符串或无实质原因。
    excluded_reason: str
    # `resolution_m_per_px` 是本 lane 所在运行尺度的分辨率，供宽度摘要和调试结果做物理单位解释。
    resolution_m_per_px: float
    # `debug_info` 只保留 lane 构造过程的解释性信息，不允许下游把它当正式几何真值消费。
    debug_info: dict[str, Any]


class CoverageLaneSweepSummary(TypedDict, total=False):
    # `coverage_lane_count` 是本阶段输出的 lane 总数，包含 active 和 inactive lane。
    coverage_lane_count: int
    # `active_coverage_lane_count` 是真正进入后续 sweep graph 主线的 lane 数量。
    active_coverage_lane_count: int
    # `sweep_count` 是本阶段生成的 sweep 总数，通常只统计正式输出集合中的 sweep item。
    sweep_count: int
    # `active_sweep_count` 是允许进入 sweep graph / cadence 的 sweep 数量。
    active_sweep_count: int


class CoverageLaneGenerationValidation(TypedDict, total=False):
    # `valid` 表示 coverage lane 与 sweep 的引用闭环是否满足下游消费前提。
    valid: bool
    # `error_count` 是 validation 发现的结构错误数量，不包括普通调试提示。
    error_count: int
    # `errors` 保存具体错误描述，用于定位缺 sweep、短 path、引用缺失等问题。
    errors: list[str]
    # `coverage_lane_count` 是校验时看到的 lane 总数，便于和 summary 交叉核对。
    coverage_lane_count: int
    # `active_coverage_lane_count` 是校验时仍被认为 active 的 lane 数量。
    active_coverage_lane_count: int
    # `sweep_count` 是校验时看到的 sweep item 数量。
    sweep_count: int


class SweepInfo(TypedDict, total=False):
    """单条 sweep 的正式最小真值。"""

    # `sweep_id` 是 sweep 层稳定主键，后续 group、candidate、cadence、final path 都通过它回指 sweep。
    sweep_id: int
    # `coverage_lane_id` 表示这条 sweep 隶属于哪条 coverage lane，是 lane 内排序和分组的主依据。
    coverage_lane_id: int
    # `source_edge_id` 表示 sweep 最终来源于哪条正式 edge，供 same-edge 判断和 coverage 回溯使用。
    source_edge_id: int
    # `resolution_m_per_px` 是 sweep 几何折线所在运行尺度的分辨率，供局部距离换算成米制候选代价。
    resolution_m_per_px: float
    # `side_label` 描述 sweep 位于 lane 中心线哪一侧，主要用于调试和解释横向布局。
    side_label: str
    # `side_level` 描述 sweep 离 lane 中心参考线的离散层级，cadence 会用它判断中心/边缘优先级。
    side_level: int
    # `mean_offset_m` 是 sweep 相对中心参考线的平均横向偏移，正式消费层只允许读取米制。
    mean_offset_m: float
    # `path_rc` 是 sweep 最终走向的主几何折线，坐标仍采用运行尺度 row/col 像素坐标。
    path_rc: tuple[tuple[float, float], ...] | list[list[float]]
    # `anchor_points_rc` 保留 sweep 采样时的锚点集合，便于回看偏移回填和局部失真问题。
    anchor_points_rc: tuple[tuple[float, float], ...] | list[list[float]]
    # `offset_profile_m` 是沿主连续段采样得到的米制偏移剖面，用于解释 sweep 横向偏移是否平滑。
    offset_profile_m: tuple[float, ...] | list[float]
    # `sampling_step_m` 是该 sweep 生成时主轴采样间距的米制表达，不允许下游直接依赖像素步长。
    sampling_step_m: float
    # `normal_search_m` 是生成该 sweep 时沿法向搜索合法点的米制半径，主要用于调试布局稳定性。
    normal_search_m: float
    # `effective_min_clearance_m` 是生成 sweep 时要求的最小净空米制约束，来源于机器人宽度/配置。
    effective_min_clearance_m: float
    # `path_count` 表示这条 sweep 是否由多个子折线拼成；理想情况下通常应为 1。
    path_count: int
    # `path_length_m` 是 sweep 主折线长度的米制结果，供 cadence 起点选择和统计使用。
    path_length_m: float
    # `active` 表示这条 sweep 是否进入后续 graph/cadence 主线；False 时只能作为排查证据保留。
    active: bool


__all__ = (
    "CoverageLaneInfoItem",
    "CoverageLaneSweepSummary",
    "CoverageLaneGenerationValidation",
    "SweepInfo",
)
