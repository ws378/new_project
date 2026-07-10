from __future__ import annotations

"""FinalCoveragePath 的 TypedDict 契约。"""

from typing import Any, TypedDict


class FinalCoveragePathOrderedItem(TypedDict, total=False):
    # `item_type` 区分 sweep 段和 junction connection 段，保证 ordered_items 能串成统一序列。
    item_type: str
    # `route_id` 表示该 item 属于哪条 final path route。
    route_id: int
    # `item_index` 是 route 内最终路径 item 顺序。
    item_index: int
    # `sweep_id` 在 item_type 为 sweep 时有效，表示当前 item 对应哪条 sweep。
    sweep_id: int
    # `direction` 表示 sweep 在最终路径中实际走向，与 sweep 原始 path_rc 方向可能不同。
    direction: str
    # `connection_id` 在 item_type 为 junction_connection 时有效，回指具体连接对象。
    connection_id: int
    # `sweep_points_rc` 是 sweep item 的最终路径点串，坐标为运行尺度 row/col。
    sweep_points_rc: tuple[tuple[float, float], ...]
    # `junction_connection_points_rc` 是连接 item 的最终路径点串，坐标为运行尺度 row/col。
    junction_connection_points_rc: tuple[tuple[float, float], ...]
    # `debug_info` 保留 item 展开过程解释，不替代 points 主体真值。
    debug_info: dict[str, Any]


class FinalCoveragePathConnection(TypedDict, total=False):
    """单条 junction connection 在最终路径层的正式真值。"""

    # `item_type` 固定表达这是 junction connection item，便于和 sweep item 统一排列。
    item_type: str
    # `connection_id` 是 final path 层连接主键，被 ordered_items 回指。
    connection_id: int
    # `route_id` 表示该 connection 属于哪条 final route。
    route_id: int
    # `item_index` 是该 connection 在 route ordered_items 中的位置。
    item_index: int
    # `from_sweep_id` 是连接起点 sweep。
    from_sweep_id: int
    # `to_sweep_id` 是连接目标 sweep。
    to_sweep_id: int
    # `via_node_id` 表示连接依托的拓扑节点；组内横移可能没有强节点几何。
    via_node_id: int
    # `connection_type` 表示连接几何模板类型，供 renderer/debug 解释构造规则。
    connection_type: str
    # `connector_kind` 是 final path 层主连接语义，区分 forward / foldback 等最终落地类别。
    connector_kind: str
    # `point_a_rc` 是规则构型的第一个关键点，通常来自 from sweep 端点或其投影。
    point_a_rc: tuple[float, float]
    # `point_b_rc` 是规则构型的第二个关键点，用于描述连接进入路口/过渡区的几何。
    point_b_rc: tuple[float, float]
    # `point_c_rc` 是规则构型的第三个关键点，用于描述连接离开路口/过渡区的几何。
    point_c_rc: tuple[float, float]
    # `point_d_rc` 是规则构型的第四个关键点，通常接回 to sweep 端点或其投影。
    point_d_rc: tuple[float, float]
    # `theta_deg` 是连接局部几何模板的角度解释，用于调试连接形态。
    theta_deg: float
    # `connection_class` 表示前进连接、折返连接等更上层归类。
    connection_class: str
    # `is_constructible` 表示这条连接是否成功生成了可落地几何。
    is_constructible: bool
    # `failure_reason` 记录不可构造原因，成功构造时应为空或无实质错误。
    failure_reason: str
    # `rule_geometry_rc` 是规则层构造出的几何骨架，用于审查规则点是否合理。
    rule_geometry_rc: tuple[tuple[float, float], ...]
    # `path_points_rc` 是最终落地路径点串，是 renderer / compare 直接消费的连接几何。
    path_points_rc: tuple[tuple[float, float], ...]
    # `coverage_support_width_m` 是该 connection 可支撑的覆盖宽度米制估计，用于安全性校验。
    coverage_support_width_m: float
    # `is_foldback` 显式标记该连接是否属于折返类，便于 validation 单独检查。
    is_foldback: bool
    # `debug_info` 保存连接构造过程的补充信息，不替代 path_points_rc 主体真值。
    debug_info: dict[str, Any]


class FinalCoveragePathCoverageSupportInfo(TypedDict, total=False):
    # `junction_connection_count` 是当前 route 中参与支撑宽度统计的连接数量。
    junction_connection_count: int
    # `max_support_width_m` 是当前 route 内连接可支撑宽度的最大米制摘要。
    max_support_width_m: float


class FinalCoveragePathRouteDebugInfo(TypedDict, total=False):
    # `sweep_segment_count` 是该 route 中 sweep item 数量。
    sweep_segment_count: int
    # `junction_connection_count` 是该 route 中 junction connection item 数量。
    junction_connection_count: int
    # `path_subchain_count` 是该 route 被切成的可连续绘制子链数量。
    path_subchain_count: int


class FinalCoveragePathRoute(TypedDict, total=False):
    # `route_id` 是 final path route 主键，继承 cadence route 的 route_id。
    route_id: int
    # `ordered_items` 是 route 内统一顺序主序列，供写盘/渲染/compare 直接消费。
    ordered_items: tuple[FinalCoveragePathOrderedItem, ...]
    # `sweep_segments` 是按 sweep 类型拆出的视图，便于单独统计 sweep 几何。
    sweep_segments: tuple[FinalCoveragePathOrderedItem, ...]
    # `junction_connections` 是按 connection 类型拆出的视图，便于校验和渲染连接几何。
    junction_connections: tuple[FinalCoveragePathConnection, ...]
    # `path_subchains_rc` 表示 route 已按可连续绘制的子链切好，避免上层重新切分。
    path_subchains_rc: tuple[tuple[tuple[float, float], ...], ...]
    # `path_length_px` 是 route 总路径长度的像素统计，只作为报告/调试摘要。
    path_length_px: float
    # `path_length_m` 是 route 总路径长度的米制统计，外部比较应优先使用该字段。
    path_length_m: float
    # `coverage_support_info` 是 route 级覆盖支撑宽度摘要，不复制每条连接完整几何。
    coverage_support_info: FinalCoveragePathCoverageSupportInfo
    # `debug_info` 是 route 级展开摘要，用于检查 item/connection/subchain 数量是否一致。
    debug_info: FinalCoveragePathRouteDebugInfo


class FinalCoveragePathSummary(TypedDict, total=False):
    # `route_count` 是最终输出路径 route 数量。
    route_count: int
    # `junction_connection_count` 是最终路径中连接段总数。
    junction_connection_count: int
    # `forward_connection_count` 是 forward 类连接数量。
    forward_connection_count: int
    # `foldback_connection_count` 是 foldback 类连接数量。
    foldback_connection_count: int
    # `path_point_count` 是所有 route/subchain 路径点总数。
    path_point_count: int
    # `path_length_px` 是最终路径总长度像素摘要，只作为报告/调试量纲保留。
    path_length_px: float
    # `path_length_m` 是最终路径总长度米制摘要，外部对比和指标应优先读取该字段。
    path_length_m: float


class FinalCoveragePathInfo(TypedDict, total=False):
    """final coverage path 层的正式真值容器。"""

    # `routes` 是最终路径层的正式主输出。
    routes: tuple[FinalCoveragePathRoute, ...]
    # `ordered_items` 是跨 route 拉平后的最终顺序视图，供 compare 和写盘层快速消费。
    ordered_items: tuple[FinalCoveragePathOrderedItem, ...]
    # `junction_connections` 是跨 route 拉平后的连接集合，供连接校验和可视化快速消费。
    junction_connections: tuple[FinalCoveragePathConnection, ...]
    # `summary` 是 final path 层规模、长度和连接类别摘要，不替代 routes 主体。
    summary: FinalCoveragePathSummary


class FinalCoveragePathValidation(TypedDict, total=False):
    # `is_valid` 表示最终路径是否通过连接、端点、支撑宽度和折返规则校验。
    is_valid: bool
    # `invalid_connection_count` 是不可构造或语义非法的 connection 数量。
    invalid_connection_count: int
    # `invalid_path_endpoint_count` 是 route seam 或路径端点对接异常数量。
    invalid_path_endpoint_count: int
    # `invalid_support_width_count` 是连接支撑宽度不满足要求的数量。
    invalid_support_width_count: int
    # `invalid_foldback_count` 是折返类连接违反折返规则的数量。
    invalid_foldback_count: int
    # `invalid_rule_truth_count` 是规则几何真值不闭环或缺关键点的数量。
    invalid_rule_truth_count: int
    # `duplicate_connection_ids` 记录重复出现的 connection_id，正常应为空。
    duplicate_connection_ids: list[int]
    # `route_seam_break_count` 是 route ordered_items 之间出现断缝的数量。
    route_seam_break_count: int


__all__ = (
    "FinalCoveragePathOrderedItem",
    "FinalCoveragePathConnection",
    "FinalCoveragePathCoverageSupportInfo",
    "FinalCoveragePathRouteDebugInfo",
    "FinalCoveragePathRoute",
    "FinalCoveragePathSummary",
    "FinalCoveragePathInfo",
    "FinalCoveragePathValidation",
)
