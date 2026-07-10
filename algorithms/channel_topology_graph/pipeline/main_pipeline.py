"""主线内存编排器。

这个模块只负责阶段调用顺序和对象流转，不实现任何具体算法。
"""

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from ..geometry_preparation.boundary_smoothing import BoundarySmoothingResult, apply_majority_smoothing
from ..contracts import (
    CoveragePlanningResult,
    GeometryPreparationResult,
    JunctionRebuildResult,
    PipelineRunResult,
    TopologyGraphBuildResult,
)
from ..stages import (
    build_coverage_plan,
    build_geometry_preparation,
    build_junction_rebuild,
    build_topology_graph,
)

GeometryPreparationStage = Callable[..., GeometryPreparationResult]
JunctionRebuildStage = Callable[..., JunctionRebuildResult]
TopologyGraphBuildStage = Callable[..., TopologyGraphBuildResult]
CoveragePlanningStage = Callable[..., CoveragePlanningResult]


@dataclass(slots=True)
class PipelineInput:
    """主线外部输入封装。

    真实职责：
        把外部调用者提供的原始地图和区域约束收成统一入口对象，
        避免 pipeline 直接依赖散乱的位置参数。

    Args:
        raw_map:
            原始地图输入。具体类型由上层调用者决定。
        region_constraint:
            可选区域约束。为空时表示由 geometry_preparation 自行解释默认区域。
        meta:
            输入级元信息。仅用于追踪，不参与正式算法推理。
    """

    raw_map: Any
    region_constraint: Any | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PipelineConfig:
    """主线阶段化配置封装。

    真实职责：
        把 4 个正式阶段的配置拆开保存，保证 pipeline 只做编排，不理解算法细节。

    Args:
        geometry_preparation:
            geometry_preparation 配置。
        junction_rebuild:
            junction_rebuild 配置。
        topology_graph_build:
            topology_graph_build 配置。
        coverage_planning:
            coverage_planning 配置。
        runtime:
            运行时公共上下文配置。只承载跨阶段公共元信息，不承载正式对象。
    """

    # 按阶段拆配置，可以避免不同步骤之间的参数语义互相污染。
    geometry_preparation: dict[str, Any] = field(default_factory=dict)
    junction_rebuild: dict[str, Any] = field(default_factory=dict)
    topology_graph_build: dict[str, Any] = field(default_factory=dict)
    coverage_planning: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PipelineStages:
    """4 个正式阶段实现的依赖注入容器。

    真实职责：
        允许上层在不改 pipeline 编排逻辑的情况下，替换具体阶段实现，
        便于后续把占位 stage 渐进替换成正式算法实现。

    Args:
        geometry_preparation:
            geometry_preparation stage 实现。
        junction_rebuild:
            junction_rebuild stage 实现。
        topology_graph_build:
            topology_graph_build stage 实现。
        coverage_planning:
            coverage_planning stage 实现。
    """

    geometry_preparation: GeometryPreparationStage = build_geometry_preparation
    junction_rebuild: JunctionRebuildStage = build_junction_rebuild
    topology_graph_build: TopologyGraphBuildStage = build_topology_graph
    coverage_planning: CoveragePlanningStage = build_coverage_plan


def run_geometry_preparation_stage(
    *,
    pipeline_input: PipelineInput,
    config: PipelineConfig,
    stages: PipelineStages,
) -> GeometryPreparationResult:
    """运行 geometry_preparation，并默认执行边界多数投票平滑。"""

    # pipeline 不在这里解释原始地图语义，只负责把入口对象拆给正式 stage。
    geometry_config = dict(config.geometry_preparation)
    baseline_result = stages.geometry_preparation(
        raw_map=pipeline_input.raw_map,
        region_constraint=pipeline_input.region_constraint,
        config=geometry_config,
    )
    return apply_geometry_boundary_smoothing_if_enabled(
        baseline_result=baseline_result,
        geometry_config=geometry_config,
        stages=stages,
    )


def geometry_boundary_smoothing_config(geometry_config: dict[str, Any]) -> dict[str, Any]:
    """从 geometry_preparation 配置读取正式边界平滑参数。"""

    smoothing_cfg = dict(geometry_config.get("boundary_smoothing", {}) or {})
    enabled = bool(smoothing_cfg.get("enable", geometry_config.get("boundary_smoothing_enable", True)))
    return {
        "enable": enabled,
        "majority_radius_m": float(smoothing_cfg.get("majority_radius_m", geometry_config.get("boundary_smoothing_majority_radius_m", 0.25))),
        "boundary_band_m": float(smoothing_cfg.get("boundary_band_m", geometry_config.get("boundary_smoothing_band_m", 0.35))),
        "obstacle_threshold": float(smoothing_cfg.get("obstacle_threshold", geometry_config.get("boundary_smoothing_obstacle_threshold", 0.5))),
    }


def geometry_config_for_boundary_smoothed_rerun(geometry_config: dict[str, Any]) -> dict[str, Any]:
    """构造平滑后第二次 geometry_preparation 的配置。"""

    rerun_config = dict(geometry_config)
    rerun_config["input_is_prepared_map"] = True
    rerun_config["crop_pad_px"] = 0
    rerun_config["boundary_smoothing_enable"] = False
    nested = dict(rerun_config.get("boundary_smoothing", {}) or {})
    nested["enable"] = False
    rerun_config["boundary_smoothing"] = nested
    return rerun_config


def attach_boundary_smoothing_debug(
    result: GeometryPreparationResult,
    *,
    smoothing: BoundarySmoothingResult | None,
    enabled: bool,
    source: str,
) -> GeometryPreparationResult:
    """把 boundary smoothing 摘要写入 geometry_preparation 正式结果。"""

    debug_info = dict(result.debug_info or {})
    meta = dict(result.meta or {})
    if smoothing is None:
        debug_info["boundary_smoothing"] = {
            "enabled": bool(enabled),
            "applied": False,
            "source": source,
        }
        meta["boundary_smoothing"] = debug_info["boundary_smoothing"]
    else:
        payload = dict(smoothing.debug_info)
        payload["attempted"] = True
        payload["applied"] = bool(payload.get("accepted", False) and int(payload.get("updated_pixel_count", 0)) > 0)
        payload["source"] = source
        debug_info["boundary_smoothing"] = payload
        meta["boundary_smoothing"] = payload
    result.debug_info = debug_info
    result.meta = meta
    return result


def apply_geometry_boundary_smoothing_if_enabled(
    *,
    baseline_result: GeometryPreparationResult,
    geometry_config: dict[str, Any],
    stages: PipelineStages,
) -> GeometryPreparationResult:
    """在 geometry_preparation 后执行边界平滑，并用平滑 mask 重新建立几何结果。"""

    smoothing_config = geometry_boundary_smoothing_config(geometry_config)
    if not smoothing_config["enable"]:
        return attach_boundary_smoothing_debug(
            baseline_result,
            smoothing=None,
            enabled=False,
            source="disabled",
        )

    smoothing = apply_majority_smoothing(
        free_mask=baseline_result.free_mask,
        region_mask=baseline_result.region_mask,
        resolution_m_per_px=float(baseline_result.resolution_m_per_px),
        majority_radius_m=float(smoothing_config["majority_radius_m"]),
        boundary_band_m=float(smoothing_config["boundary_band_m"]),
        obstacle_threshold=float(smoothing_config["obstacle_threshold"]),
    )
    if int(smoothing.debug_info.get("updated_pixel_count", 0)) <= 0:
        return attach_boundary_smoothing_debug(
            baseline_result,
            smoothing=smoothing,
            enabled=True,
            source="baseline_geometry_result_no_delta",
        )

    rerun_config = geometry_config_for_boundary_smoothed_rerun(geometry_config)
    smoothed_result = stages.geometry_preparation(
        raw_map=np.asarray(smoothing.smoothed_free_mask),
        region_constraint=np.asarray(baseline_result.region_mask),
        config=rerun_config,
    )
    return attach_boundary_smoothing_debug(
        smoothed_result,
        smoothing=smoothing,
        enabled=True,
        source="boundary_smoothed_geometry_rerun",
    )


def run_junction_rebuild_stage(
    *,
    geometry_preparation_result: GeometryPreparationResult,
    config: PipelineConfig,
    stages: PipelineStages,
    runtime_context: dict[str, Any],
) -> JunctionRebuildResult:
    """运行 junction_rebuild。"""

    # junction_rebuild 的正式输入是 geometry_preparation_result。
    # runtime_context 在这里只作为辅助元信息，不允许反客为主。
    return stages.junction_rebuild(
        geometry_preparation_result=geometry_preparation_result,
        config=config.junction_rebuild,
        context=runtime_context,
    )


def run_topology_graph_build_stage(
    *,
    junction_rebuild_result: JunctionRebuildResult,
    config: PipelineConfig,
    stages: PipelineStages,
    runtime_context: dict[str, Any],
) -> TopologyGraphBuildResult:
    """运行 topology_graph_build。"""

    # topology_graph_build 只能接 compact 后的 node/edge 结果，不能跨阶段回读更早的内部对象。
    return stages.topology_graph_build(
        junction_rebuild_result=junction_rebuild_result,
        config=config.topology_graph_build,
        context=runtime_context,
    )


def run_coverage_planning_stage(
    *,
    topology_graph_build_result: TopologyGraphBuildResult,
    config: PipelineConfig,
    stages: PipelineStages,
    runtime_context: dict[str, Any],
) -> CoveragePlanningResult:
    """运行 coverage_planning。"""

    # coverage_planning 以 topology_graph_build_result 为主输入。
    # geometry_preparation_result 仅通过 runtime_context 作为补充正式引用进入。
    return stages.coverage_planning(
        topology_graph_build_result=topology_graph_build_result,
        config=config.coverage_planning,
        context=runtime_context,
    )


def run_channel_topology_graph_pipeline(
    pipeline_input: PipelineInput,
    config: PipelineConfig | None = None,
    stages: PipelineStages | None = None,
) -> PipelineRunResult:
    """按正式主线顺序运行整条流程。

    真实职责：
        统一完成 geometry_preparation -> junction_rebuild -> topology_graph_build -> coverage_planning 的内存对象串联，
        明确各阶段输入输出边界，并把阶段结果汇总成单次运行结果。

    Args:
        pipeline_input:
            外部输入封装，至少提供原始地图和可选区域约束。
        config:
            阶段化配置封装。为空时使用默认空配置。
        stages:
            阶段实现集合。为空时使用当前包内默认 stage 入口。

    Returns:
        PipelineRunResult:
            一次完整主线运行的阶段结果封装。

    副作用:
        本函数不写文件、不修改全局状态。它只负责编排阶段调用和组装返回值。
    """

    # 先把入口可选参数收成稳定对象，后续编排就不用再处理 None 分支。
    normalized_config, normalized_stages = normalize_pipeline_runtime_inputs(
        config=config,
        stages=stages,
    )
    # runtime_context 在 stage 开始前一次性建好，保证四个阶段看到的是同一份跨阶段元信息。
    runtime_context = build_pipeline_runtime_context(normalized_config)
    stage_results = run_pipeline_stages(
        pipeline_input=pipeline_input,
        config=normalized_config,
        stages=normalized_stages,
        runtime_context=runtime_context,
    )
    return build_pipeline_run_result(
        stage_results=stage_results,
        runtime_context=runtime_context,
        pipeline_input=pipeline_input,
    )


def normalize_pipeline_runtime_inputs(
    *,
    config: PipelineConfig | None,
    stages: PipelineStages | None,
) -> tuple[PipelineConfig, PipelineStages]:
    """规整 pipeline 入口配置和阶段实现容器。"""

    # pipeline 允许上层不显式传配置与实现，因此入口先补默认对象。
    normalized_config = config if config is not None else PipelineConfig()
    normalized_stages = stages if stages is not None else PipelineStages()
    return normalized_config, normalized_stages


def build_pipeline_runtime_context(config: PipelineConfig) -> dict[str, Any]:
    """构造跨阶段共享的 runtime_context。"""

    # `runtime_context` 只承载跨阶段共享的元信息。
    # 正式算法输入输出仍然必须通过 stage result 对象传递。
    runtime_context = dict(config.runtime)
    runtime_context.setdefault("pipeline_name", "channel_topology_graph")
    # runtime_context 只保留跨阶段共享元信息，正式结果对象仍必须显式穿过 stage 边界。
    return runtime_context


def run_pipeline_stages(
    *,
    pipeline_input: PipelineInput,
    config: PipelineConfig,
    stages: PipelineStages,
    runtime_context: dict[str, Any],
) -> dict[str, Any]:
    """按固定顺序运行四个正式 stage。"""

    # 先得到统一的运行尺度几何世界。
    # 这里仍然只传原始输入，不把后续阶段结果提前注入。
    geometry_preparation_result = run_geometry_preparation_stage(
        pipeline_input=pipeline_input,
        config=config,
        stages=stages,
    )
    # coverage_planning 需要读取 geometry_preparation 的 free_mask 做 coverage 有效区判定，
    # 但正式阶段输入边界仍保持不变，这里通过 runtime_context 只传对象引用。
    runtime_context["geometry_preparation_result"] = geometry_preparation_result

    # 在几何世界上建立并更新节点、边，但这里仍不建图。
    # junction_rebuild 只消费 geometry_preparation 正式结果与 runtime 元信息，不跨边界读取别的对象。
    junction_rebuild_result = run_junction_rebuild_stage(
        geometry_preparation_result=geometry_preparation_result,
        config=config,
        stages=stages,
        runtime_context=runtime_context,
    )

    # 第一次正式建立 graph_info，并派生图层候选与 lane 结果。
    # 直到这里才允许主线出现 `graph_info`，这是 junction_rebuild / topology_graph_build 边界的核心约束。
    topology_graph_build_result = run_topology_graph_build_stage(
        junction_rebuild_result=junction_rebuild_result,
        config=config,
        stages=stages,
        runtime_context=runtime_context,
    )

    # coverage_planning 只消费正式图对象和其派生结果，不再回写 node/edge。
    # 覆盖规划可以读 runtime_context，但正式算法输入仍以 stage result 为主。
    coverage_planning_result = run_coverage_planning_stage(
        topology_graph_build_result=topology_graph_build_result,
        config=config,
        stages=stages,
        runtime_context=runtime_context,
    )
    return {
        "geometry_preparation_result": geometry_preparation_result,
        "junction_rebuild_result": junction_rebuild_result,
        "topology_graph_build_result": topology_graph_build_result,
        "coverage_planning_result": coverage_planning_result,
    }


def build_pipeline_run_result(
    *,
    stage_results: dict[str, Any],
    runtime_context: dict[str, Any],
    pipeline_input: PipelineInput,
) -> PipelineRunResult:
    """组装总流水线的最终结果对象。"""

    # 最终把四步结果统一打包，便于上层调用和阶段级校验。
    # meta 只记录本次编排级元信息，不重复拷贝四阶段大对象。
    # 这样 PipelineRunResult 仍然清楚地区分“正式阶段结果”和“编排级附加信息”。
    return PipelineRunResult(
        geometry_preparation_result=stage_results["geometry_preparation_result"],
        junction_rebuild_result=stage_results["junction_rebuild_result"],
        topology_graph_build_result=stage_results["topology_graph_build_result"],
        coverage_planning_result=stage_results["coverage_planning_result"],
        meta={
            # pipeline_name 用于标识是哪条正式主线产出的结果，方便多 pipeline 共存时归档。
            "pipeline_name": runtime_context["pipeline_name"],
            # input_meta 只回放入口追踪信息，不把 raw_map / region_constraint 本体塞进 meta。
            "input_meta": dict(pipeline_input.meta),
        },
    )
