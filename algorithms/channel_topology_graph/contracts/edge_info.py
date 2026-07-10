"""边正式对象契约。

这里定义的是 junction_rebuild 之后唯一允许进入主线的边对象。
边的身份稳定靠 `edge_id`，几何变化通过路径字段更新来表达。
"""

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict


class CoverageLaneWidthStats(TypedDict, total=False):
    """coverage lane 的局部宽度统计。"""

    # `sweep_spacing_px` 是 sweep 生成时使用的横向层距像素摘要，只用于几何层回看。
    sweep_spacing_px: int
    # `coverage_width_m` 是 sweep 横向层距米制摘要，外部比较和配置解释应优先使用它。
    coverage_width_m: float
    # `effective_min_clearance_px` 是有效自由空间最小清障像素估计，只用于 lane 几何诊断。
    effective_min_clearance_px: float
    # `positive_side_sweep_count` 是中心线正侧可生成的 sweep 层数。
    positive_side_sweep_count: int
    # `negative_side_sweep_count` 是中心线负侧可生成的 sweep 层数。
    negative_side_sweep_count: int
    # `target_sweep_count` 是当前 lane 期望生成的 sweep 总数。
    target_sweep_count: int
    # `robust_percentile` 是宽度统计采用的稳健分位数，用于解释为什么没有使用极端宽度。
    robust_percentile: float
    # `anchor_count` 是参与宽度统计的中心线 anchor 数量。
    anchor_count: int
    # `approx_usable_width_px` 是估计可用横向宽度的像素摘要，只保留给几何调试。
    approx_usable_width_px: float
    # `approx_usable_width_m` 是估计可用横向宽度的米制摘要，是对外报告应优先读取的宽度字段。
    approx_usable_width_m: float


class EdgeCoverageInfo(TypedDict, total=False):
    """CoveragePlanning 写回边对象的最小 coverage 投影。"""

    # `coverage_lane_id` 回指该 edge 对应的 coverage lane 主键。
    coverage_lane_id: int
    # `active` 表示该 edge 是否实际进入 coverage lane / sweep 生成。
    active: bool
    # `main_direction` 是该 edge 覆盖 lane 的主方向描述，用于调试横纵向判定。
    main_direction: str
    # `territory_pixels` 是该 edge 覆盖领地像素集合，坐标为运行尺度 row/col。
    territory_pixels: tuple[tuple[int, int], ...]
    # `effective_region_pixels` 是扣除不可用区域后的有效覆盖像素集合。
    effective_region_pixels: tuple[tuple[int, int], ...]
    # `sweep_ids` 是该 edge 派生出的正式 sweep id 集合。
    sweep_ids: tuple[int, ...]
    # `sweep_count` 是该 edge 派生出的 sweep 数量。
    sweep_count: int
    # `local_width_stats` 是该 edge/lane 的局部宽度统计摘要。
    local_width_stats: CoverageLaneWidthStats
    # `geometry_valid` 表示 lane 几何是否足以生成覆盖对象。
    geometry_valid: bool
    # `node_valid` 表示该 edge 端点节点关系是否满足 coverage 消费前提。
    node_valid: bool
    # `topology_valid` 表示该 edge 在拓扑层是否满足 coverage 消费前提。
    topology_valid: bool
    # `excluded_reason` 记录 edge 未进入 coverage 或被降级的原因。
    excluded_reason: str
    # `resolution_m_per_px` 记录生成该 coverage 投影时使用的米/像素分辨率。
    resolution_m_per_px: float


# `edge_type` 只表达最稳定的端点连接形态，避免把 coverage/final-path 连接细节塞进 edge 主体。
EdgeType = Literal["connected_both_ends", "dead_end_one_side", "dead_end_both_sides", "cycle"]


@dataclass(slots=True)
class EdgeInfo:
    """描述单条正式边的最小稳定信息。

    真实职责：
        承载边两端节点关系，以及边在节点 polygon 内外的分段几何。
        junction_rebuild 在同一 `edge_id` 上不断更新几何状态，topology_graph_build / coverage_planning 继续消费。

    Args:
        edge_id:
            边正式主键。单位：无。
            约束：在整条主线内必须唯一，且下游阶段不得重编号。
        src_node_id:
            边起点节点 id。单位：无。
            约束：必须能回指到正式 `node_id`。
        dst_node_id:
            边终点节点 id。单位：无。
            约束：必须能回指到正式 `node_id`。
        inner_path_rc:
            位于节点 polygon 内部的几何路径。单位：像素。
            作用：保留边如何从节点内部接出。
        outer_path_rc:
            位于节点 polygon 之外的主体几何路径。单位：像素。
            作用：后续用于洪水扩张、有效区域生成、sweep 与路径点提取。
        path_rc:
            完整边路径。单位：像素。
            作用：作为整条边的统一几何表达。
        length_px:
            边长度，运行尺度像素单位。
        length_m:
            边长度，米单位。
        edge_type:
            边端点连接类型。单位：无。
            作用：表达该边当前是双端连通、单端 dead_end、双端 dead_end 还是回环。
        coverage_info:
            CoveragePlanning 回填的边级 coverage 投影。
            约束：只能表达当前 edge 的 coverage 闭环摘要，
            不允许在这里塞入另一套独立 stage 结果树。
        debug_info:
            调试信息，仅用于追踪过程。
        validation_info:
            校验信息，用于记录几何与拓扑闭环结果。

    Returns:
        EdgeInfo:
            一个可被 junction_rebuild 写出、并被 topology_graph_build / coverage_planning 继续消费的正式边对象。
    """

    # `edge_id` 是正式边主键；下游阶段不得重编号或另建并列主键。
    edge_id: int
    # `src_node_id` 是边的 src 端节点 id，必须能回指到正式 node_info。
    src_node_id: int
    # `dst_node_id` 是边的 dst 端节点 id，允许在 cycle edge 中与 src_node_id 相同。
    dst_node_id: int
    # `inner_path_rc` 是位于节点 polygon 内部的路径段，坐标为运行尺度 row/col。
    inner_path_rc: tuple[tuple[float, float], ...] = ()
    # `outer_path_rc` 是节点 polygon 外部的边主体路径，coverage lane 通常围绕它生成。
    outer_path_rc: tuple[tuple[float, float], ...] = ()
    # `path_rc` 是完整边路径；正式消费者应优先读它，只有需要区分内外段时才读 inner/outer。
    path_rc: tuple[tuple[float, float], ...] = ()
    # `length_px` 是边完整路径长度的运行尺度像素摘要，仅用于几何调试和可视化报告。
    length_px: float = 0.0
    # `length_m` 是边完整路径长度的米制摘要，外部指标和阈值比较应优先使用它。
    length_m: float = 0.0
    # `edge_type` 是边端点连接形态，供 pure cycle / dead-end / normal link 分支统一消费。
    edge_type: EdgeType | None = None
    # `coverage_info` 是 coverage planning 回填的边级覆盖摘要；为空只表示该阶段尚未投影回来。
    coverage_info: EdgeCoverageInfo | None = None
    # `debug_info` 保存边重建和更新过程解释，不替代正式几何字段。
    debug_info: dict[str, Any] | None = field(default=None)
    # `validation_info` 记录边端点、路径、长度、coverage 投影等闭环校验结果。
    validation_info: dict[str, Any] | None = field(default=None)
