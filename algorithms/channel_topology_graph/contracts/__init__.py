"""channel_topology_graph 正式对象契约导出。"""

from .node_info import NodeInfo
from .edge_info import CoverageLaneWidthStats, EdgeCoverageInfo, EdgeInfo, EdgeType
from .graph_info import GraphInfo
from .pipeline_stage_results import (
    GeometryPreparationResult,
    JunctionRebuildResult,
    TopologyGraphBuildResult,
    CoverageLaneSweepBuildInfo,
    SweepGraphBuildInfo,
    SweepCadenceBuildInfo,
    FinalCoveragePathBuildInfo,
    CoveragePlanningResult,
    PipelineRunResult,
)
from .coverage_lane_sweep_stage_results import (
    CoverageLaneInfoItem,
    CoverageLaneGenerationValidation,
    CoverageLaneSweepSummary,
    SweepInfo,
)
from .topology_port_hypothesis_stage_results import (
    IncidentPortInfo,
    IncidentPortItem,
    IncidentPortSummary,
    NodeLocalConnectionHypothesisInfo,
    NodeLocalConnectionHypothesisItem,
    NodeLocalConnectionHypothesisSummary,
)
from .sweep_graph_stage_results import (
    SweepGroupInfo,
    SweepGroupItem,
    SweepPortViewInfo,
    SweepPortViewItem,
    SweepTransitionCandidateInfo,
    SweepTransitionCandidateItem,
    SweepGraphBuildSummary,
    SweepGraphInfo,
    SweepGraphNode,
    SweepGraphSweep,
    SweepGraphValidation,
)
from .sweep_cadence_stage_results import (
    SweepCadenceBuildSummary,
    SweepCoverageStats,
    SweepCadenceInfo,
    SweepCadenceRoute,
    SweepCadenceSegment,
)
from .final_coverage_path_stage_results import (
    FinalCoveragePathConnection,
    FinalCoveragePathCoverageSupportInfo,
    FinalCoveragePathInfo,
    FinalCoveragePathOrderedItem,
    FinalCoveragePathRouteDebugInfo,
    FinalCoveragePathRoute,
    FinalCoveragePathSummary,
    FinalCoveragePathValidation,
)

__all__ = (
    # base graph objects
    # 这组对象定义 node/edge/graph 的正式真值边界，是所有 stage result 的基础依赖。
    "NodeInfo",
    "CoverageLaneWidthStats",
    "EdgeCoverageInfo",
    "EdgeInfo",
    "EdgeType",
    "GraphInfo",
    # pipeline stage results
    "GeometryPreparationResult",
    "JunctionRebuildResult",
    "TopologyGraphBuildResult",
    "CoveragePlanningResult",
    "PipelineRunResult",
    # coverage lane sweep stage
    # CoveragePlanning 第一个子域的正式 contract，从 coverage lane 到 sweep 原语都在这里收口。
    "CoverageLaneInfoItem",
    "CoverageLaneGenerationValidation",
    "CoverageLaneSweepBuildInfo",
    "CoverageLaneSweepSummary",
    "SweepInfo",
    # topology port / hypothesis stage
    "IncidentPortItem",
    "IncidentPortSummary",
    "IncidentPortInfo",
    "NodeLocalConnectionHypothesisItem",
    "NodeLocalConnectionHypothesisSummary",
    "NodeLocalConnectionHypothesisInfo",
    # sweep graph stage
    # SweepGraph 子域负责 sweep 静态图层与 transition candidate 真值，不再复刻旧 directed-lane 世界。
    "SweepGraphBuildInfo",
    "SweepGraphBuildSummary",
    "SweepGroupItem",
    "SweepGroupInfo",
    "SweepPortViewItem",
    "SweepPortViewInfo",
    "SweepTransitionCandidateItem",
    "SweepTransitionCandidateInfo",
    "SweepGraphNode",
    "SweepGraphSweep",
    "SweepGraphInfo",
    "SweepGraphValidation",
    # sweep cadence stage
    "SweepCadenceBuildInfo",
    "SweepCadenceBuildSummary",
    "SweepCoverageStats",
    "SweepCadenceSegment",
    "SweepCadenceRoute",
    "SweepCadenceInfo",
    # final coverage path stage
    # FinalCoveragePath 子域承载最终路径与路口连接真值，是 coverage planning 的最终正式输出层。
    "FinalCoveragePathBuildInfo",
    "FinalCoveragePathOrderedItem",
    "FinalCoveragePathConnection",
    "FinalCoveragePathCoverageSupportInfo",
    "FinalCoveragePathRouteDebugInfo",
    "FinalCoveragePathRoute",
    "FinalCoveragePathSummary",
    "FinalCoveragePathInfo",
    "FinalCoveragePathValidation",
)
