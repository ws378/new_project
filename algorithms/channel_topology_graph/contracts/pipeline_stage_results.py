from __future__ import annotations

"""主线核心阶段结果 dataclass 契约。"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .edge_info import EdgeInfo
from .graph_info import GraphInfo
from .node_info import NodeInfo

if TYPE_CHECKING:
    from .coverage_lane_sweep_stage_results import (
        CoverageLaneGenerationValidation,
        CoverageLaneInfoItem,
        CoverageLaneSweepSummary,
        SweepInfo,
    )
    from .topology_port_hypothesis_stage_results import (
        IncidentPortInfo,
        NodeLocalConnectionHypothesisInfo,
    )
    from .sweep_graph_stage_results import (
        SweepGraphBuildSummary,
        SweepGraphInfo,
        SweepGraphValidation,
        SweepGroupInfo,
        SweepPortViewInfo,
        SweepTransitionCandidateInfo,
    )
    from .sweep_cadence_stage_results import (
        SweepCadenceBuildSummary,
        SweepCadenceInfo,
        SweepCoverageStats,
    )
    from .final_coverage_path_stage_results import (
        FinalCoveragePathInfo,
        FinalCoveragePathSummary,
        FinalCoveragePathValidation,
    )


@dataclass(slots=True)
class GeometryPreparationResult:
    """geometry_preparation 结果。

    真实职责：
        承载运行尺度下的灰度图、自由空间、障碍、骨架以及分辨率信息，
        作为 junction_rebuild 唯一允许读取的正式几何输入。
    """

    # `gray` 是运行尺度灰度图，是所有二值 mask 和渲染底图的共同像素基准。
    gray: Any
    # `region_mask` 是本轮裁剪/标注区域掩膜，后续 free/obstacle/skeleton 都必须受它约束。
    region_mask: Any
    # `free_mask` 是区域内可通行自由空间掩膜，是 skeleton 提取和 lane 扩张的基础。
    free_mask: Any
    # `obstacle_mask` 是区域内障碍空间掩膜，用于检查连接和 sweep 是否越界碰撞。
    obstacle_mask: Any
    # `after_open_mask` 是形态学清理后的自由空间掩膜，是 skeleton_mask 的直接来源。
    after_open_mask: Any
    # `skeleton_mask` 是从清理后自由空间提取的原始骨架。
    skeleton_mask: Any
    # `skeleton_pruned_mask` 是短枝修剪后的正式骨架，junction_rebuild 应优先消费它。
    skeleton_pruned_mask: Any
    # `skeleton_pixels_rc` 是正式骨架像素点列表，坐标为运行尺度 `(row, col)`。
    skeleton_pixels_rc: tuple[tuple[int, int], ...]
    # `crop_box_px` 是原图裁剪框 `(x, y, w, h)`，用于把局部坐标回投到原图坐标。
    crop_box_px: tuple[int, int, int, int]
    # `resolution_m_per_px` 是运行尺度米/像素分辨率，所有物理距离换算必须从这里来。
    resolution_m_per_px: float
    # `debug_info` 只保存几何准备过程解释，不能替代上述正式几何字段。
    debug_info: dict[str, Any] | None = field(default=None)
    # `validation_info` 记录 mask / skeleton 的一致性校验结果，供阶段失败定位。
    validation_info: dict[str, Any] | None = field(default=None)
    # `meta` 保存配置摘要、运行尺度等编排信息，不定义新的算法真值。
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class JunctionRebuildResult:
    """junction_rebuild 结果。

    真实职责：
        在基础几何世界上先建立并更新 `node_info / edge_info`，
        然后在正式输出前 compact，只把有效节点和有效边交给 topology_graph_build。
    """

    # `node_info_list` 是 compact 后的正式节点集合，是 topology_graph_build 建图的节点真值。
    node_info_list: tuple[NodeInfo, ...]
    # `edge_info_list` 是 compact 后的正式边集合，是 topology_graph_build 建图的边真值。
    edge_info_list: tuple[EdgeInfo, ...]
    # `debug_info` 保存节点合并、边更新、虚拟节点补建等过程解释。
    debug_info: dict[str, Any] | None = field(default=None)
    # `validation_info` 记录 node/edge 闭环校验结果，例如端点引用、路径有效性和 degree 一致性。
    validation_info: dict[str, Any] | None = field(default=None)
    # `meta` 保存阶段级统计和配置摘要，不定义新的 node/edge 真值。
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TopologyGraphBuildResult:
    """topology_graph_build 结果。

    真实职责：
        第一次正式建立 `graph_info`，并在其上继续派生 incident port 与
        node-local connection hypothesis 这组正式 topology 主线对象。
    """

    # `graph_info` 是 topology_graph_build 第一次建立的正式图对象，聚合正式 node/edge。
    graph_info: GraphInfo
    # `incident_port_info` 把 edge 的 src/dst 端展开成可连接 port，是 node-local hypothesis 的输入。
    incident_port_info: "IncidentPortInfo" | None = None
    # `node_local_connection_hypothesis_info` 是拓扑层局部连接假设，不直接代表最终 sweep 节拍。
    node_local_connection_hypothesis_info: "NodeLocalConnectionHypothesisInfo" | None = None
    # `debug_info` 保存端口展开、局部连接枚举和排序解释。
    debug_info: dict[str, Any] | None = field(default=None)
    # `validation_info` 记录 graph/port/hypothesis 的结构闭环校验结果。
    validation_info: dict[str, Any] | None = field(default=None)
    # `meta` 保存 topology stage 的配置、统计和派生索引摘要。
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CoverageLaneSweepBuildInfo:
    """CoveragePlanning 的 coverage lane 与 sweep 正式结果。

    真实职责：
        收口 `coverage_lane_info + sweeps` 这一组上游覆盖原语，
        让主装配层和后续阶段不再从多个局部变量散读这两份真值。
    """

    # `coverage_lane_info` 给出 lane 级正式覆盖真值，是 edge coverage 摘要和 sweep group 的直接来源。
    coverage_lane_info: tuple["CoverageLaneInfoItem", ...]
    # `sweeps` 是 coverage planning 后续三个子域共同消费的最小扫掠原语集合。
    sweeps: tuple["SweepInfo", ...]
    # `summary` 只保留 lane/sweep 规模摘要，不替代 coverage_lane_info 和 sweeps 主体。
    summary: "CoverageLaneSweepSummary" = field(default_factory=dict)
    # `validation_info` 回答 coverage lane / sweep 生成是否满足下游消费前提。
    validation_info: "CoverageLaneGenerationValidation" | None = field(default=None)


@dataclass(slots=True)
class SweepGraphBuildInfo:
    """CoveragePlanning 的 sweep 图层正式结果。

    真实职责：
        把 sweep 静态组、节点口视图、正式 transition candidate 和 `sweep_graph_info`
        收到同一个 sweep 图层对象里，避免主装配继续把这些图层散挂在局部变量上。
    """

    # `sweep_group_info` 把同一 coverage lane 上的一组 sweeps 收成静态分组真值。
    sweep_group_info: "SweepGroupInfo"
    # `sweep_port_view_info` 给出每个节点端口看到的 sweep 排列视图。
    sweep_port_view_info: "SweepPortViewInfo"
    # `sweep_transition_candidate_info` 承载正式 transition 候选真值，供 cadence 继续裁决。
    sweep_transition_candidate_info: "SweepTransitionCandidateInfo"
    # `sweep_graph_info` 保留 sweep 静态骨架层，不再混入正式 transition 真值。
    sweep_graph_info: "SweepGraphInfo"
    # `summary` 是 sweep group / port view / candidate / sweep 静态骨架的阶段级规模摘要。
    summary: "SweepGraphBuildSummary" = field(default_factory=dict)
    # `validation_info` 记录 sweep graph 输入 cadence 前的结构校验结果。
    validation_info: "SweepGraphValidation" | None = field(default=None)


@dataclass(slots=True)
class SweepCadenceBuildInfo:
    """CoveragePlanning 的 SweepCadence 正式结果。

    真实职责：
        承载 `sweep_cadence_info` 与 route 级覆盖统计，
        作为 final path 的唯一节拍来源。
    """

    # `sweep_cadence_info` 是 route/segment 级正式求解结果。
    sweep_cadence_info: "SweepCadenceInfo"
    # `coverage_stats` 提供“覆盖是否完整”的阶段级裁决摘要。
    coverage_stats: "SweepCoverageStats"
    # `summary` 是 cadence route 数量、覆盖数量和完成度摘要。
    summary: "SweepCadenceBuildSummary" = field(default_factory=dict)
    # `validation_info` 保存比 coverage_stats 更细的节拍约束和异常信息。
    validation_info: dict[str, Any] | None = field(default=None)


@dataclass(slots=True)
class FinalCoveragePathBuildInfo:
    """CoveragePlanning 的 FinalCoveragePath 正式结果。

    真实职责：
        承载 `final_coverage_path_info` 及其 stage-level validation，
        让最终路径不再作为零散字段挂在 stage 装配层。
    """

    # `final_coverage_path_info` 是最终落地给 compare / renderer / 写盘层消费的路径真值主对象。
    final_coverage_path_info: "FinalCoveragePathInfo"
    # `summary` 只回答规模与长度摘要，不替代 route/connection 主体。
    summary: "FinalCoveragePathSummary" = field(default_factory=dict)
    # `validation_info` 负责回答最终路径是否存在断缝、非法连接、支撑宽度异常等问题。
    validation_info: "FinalCoveragePathValidation" | None = field(default=None)


@dataclass(slots=True)
class CoveragePlanningResult:
    """CoveragePlanning 结果。

    真实职责：
        在不回写 `node_info / edge_info / graph_info` 的前提下，
        基于 topology_graph_build 的正式图和 lane 派生结果生成当前正式主线的：
        `coverage_lane_info + sweeps + SweepGraph + SweepCadence + FinalCoveragePath`。
    """

    # `graph_info` 是 coverage planning 读取的同一个正式拓扑图，不在本阶段重建图对象。
    graph_info: GraphInfo
    # `coverage_lane_sweep_info` 是 coverage lane 与 sweep 生成结果，后续 sweep graph 从这里起步。
    coverage_lane_sweep_info: CoverageLaneSweepBuildInfo | None = None
    # `sweep_graph_build_info` 是 sweep 分组、端口视图、transition candidate 和静态 sweep 骨架结果。
    sweep_graph_build_info: SweepGraphBuildInfo | None = None
    # `sweep_cadence_build_info` 是基于 transition candidate 生成的 route/segment 节拍结果。
    sweep_cadence_build_info: SweepCadenceBuildInfo | None = None
    # `final_coverage_path_build_info` 是基于 cadence route 物化出的最终路径结果。
    final_coverage_path_build_info: FinalCoveragePathBuildInfo | None = None
    # `debug_info` 保存 coverage planning stage 级调试摘要，不替代四个 build-info 主体。
    debug_info: dict[str, Any] | None = field(default=None)
    # `validation_info` 汇总 coverage planning stage 级校验结果。
    validation_info: dict[str, Any] | None = field(default=None)
    # `meta` 保存运行配置、统计和写盘辅助信息，不定义新的 coverage 真值。
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PipelineRunResult:
    """主线一次完整内存运行结果。

    真实职责：
        把四个正式阶段的输出打包成一次完整运行结果，便于上层调用、
        调试归档或后续执行结果校验。
    """

    # `geometry_preparation_result` 是本次运行第 1 阶段几何准备结果。
    geometry_preparation_result: GeometryPreparationResult
    # `junction_rebuild_result` 是本次运行第 2 阶段节点/边重建结果。
    junction_rebuild_result: JunctionRebuildResult
    # `topology_graph_build_result` 是本次运行第 3 阶段 graph/port/hypothesis 构建结果。
    topology_graph_build_result: TopologyGraphBuildResult
    # `coverage_planning_result` 是本次运行第 4 阶段覆盖规划完整结果。
    coverage_planning_result: CoveragePlanningResult
    # `meta` 只承载编排级附加信息，不定义新的正式算法真值。
    meta: dict[str, Any] = field(default_factory=dict)


__all__ = (
    "GeometryPreparationResult",
    "JunctionRebuildResult",
    "TopologyGraphBuildResult",
    "CoverageLaneSweepBuildInfo",
    "SweepGraphBuildInfo",
    "SweepCadenceBuildInfo",
    "FinalCoveragePathBuildInfo",
    "CoveragePlanningResult",
    "PipelineRunResult",
)
