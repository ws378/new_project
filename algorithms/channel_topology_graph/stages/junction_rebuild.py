"""JunctionRebuild stage 入口。"""

from __future__ import annotations

from typing import Any

from ..junction_rebuild import (
    apply_node_merges,
    build_initial_node_edge,
    compact_active_objects,
    derive_merge_groups,
    derive_post_geometry_merge_candidates,
    derive_post_geometry_merge_groups,
    derive_post_split_geometry_anomalies,
    max_post_geometry_merge_iterations,
    rebuild_edge_geometry,
    rebuild_node_geometry,
    validate_post_geometry_merge_result,
    validate_junction_rebuild_result,
)
from ..contracts import GeometryPreparationResult, JunctionRebuildResult


def build_initial_junction_runtime(
    geometry_preparation_result: GeometryPreparationResult,
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """建立 junction_rebuild 初始 node/edge runtime 结构。"""

    # 这里返回的是“可变对象 + runtime”组合，后续 merge/geometry 都会在其上原地演化。
    return build_initial_node_edge(
        geometry_result=geometry_preparation_result,
        config=config,
    )


def build_junction_merge_outputs(
    *,
    geometry_preparation_result: GeometryPreparationResult,
    node_map: dict[str, Any],
    node_runtime: dict[str, Any],
    edge_map: dict[str, Any],
    edge_runtime: dict[str, Any],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """完成 merge group 发现与对象级写回。"""

    # `derive_merge_groups` 只回答“哪些节点应该归并”，
    # 不直接改对象，避免规则判断和对象写回纠缠在一起。
    merge_groups, merge_debug = derive_merge_groups(
        geometry_result=geometry_preparation_result,
        node_map=node_map,
        node_runtime=node_runtime,
        config=config,
    )
    # 真正的 node/edge 重写集中放到 apply 阶段，便于定位是“规则命中”问题还是“写回执行”问题。
    merge_apply_debug = apply_node_merges(
        node_map=node_map,
        edge_map=edge_map,
        node_runtime=node_runtime,
        edge_runtime=edge_runtime,
        merge_groups=merge_groups,
    )
    return merge_groups, merge_debug, merge_apply_debug


def build_junction_geometry_outputs(
    *,
    geometry_preparation_result: GeometryPreparationResult,
    node_map: dict[str, Any],
    edge_map: dict[str, Any],
    node_runtime: dict[str, Any],
    edge_runtime: dict[str, Any],
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """完成节点几何和边几何重建。"""

    # 节点 polygon 先收稳，再切边的内外路径，这样 edge geometry 才能信任节点边界。
    node_geometry_debug = rebuild_node_geometry(
        geometry_result=geometry_preparation_result,
        node_map=node_map,
        edge_map=edge_map,
        node_runtime=node_runtime,
        edge_runtime=edge_runtime,
        config=config,
    )
    edge_geometry_debug = rebuild_edge_geometry(
        node_map=node_map,
        edge_map=edge_map,
        edge_runtime=edge_runtime,
        resolution_m_per_px=geometry_preparation_result.resolution_m_per_px,
    )
    return node_geometry_debug, edge_geometry_debug


def build_post_geometry_merge_outputs(
    *,
    geometry_preparation_result: GeometryPreparationResult,
    node_map: dict[int, Any],
    node_runtime: dict[int, Any],
    edge_map: dict[int, Any],
    edge_runtime: dict[int, Any],
    config: dict[str, Any],
    node_geometry_debug: dict[str, Any],
    edge_geometry_debug: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """在边几何切分后执行交汇内部短边二次合并。"""

    iterations: list[dict[str, Any]] = []
    max_iterations = max_post_geometry_merge_iterations(config)
    current_node_geometry_debug = node_geometry_debug
    current_edge_geometry_debug = edge_geometry_debug
    if max_iterations <= 0:
        return (
            {
                "max_iterations": int(max_iterations),
                "iterations": iterations,
                "stopped_reason": "disabled",
            },
            current_node_geometry_debug,
            current_edge_geometry_debug,
        )

    for iteration_index in range(max_iterations):
        # post-geometry merge 必须读取已经切分完成的 `outer_path_rc`。
        # 因此它不能放在初始 geodesic merge 前，也不能下放到 coverage 阶段。
        merge_candidates = derive_post_geometry_merge_candidates(
            node_map=node_map,
            edge_map=edge_map,
            node_runtime=node_runtime,
            edge_runtime=edge_runtime,
            resolution_m_per_px=geometry_preparation_result.resolution_m_per_px,
            config=config,
        )
        anomaly_findings = derive_post_split_geometry_anomalies(
            node_map=node_map,
            edge_map=edge_map,
            node_runtime=node_runtime,
            edge_runtime=edge_runtime,
            resolution_m_per_px=geometry_preparation_result.resolution_m_per_px,
            config=config,
        )
        if anomaly_findings and bool(config.get("post_geometry_merge_strict_anomaly_fail", False)):
            # strict 模式用于基线治理阶段；默认只记录 anomaly，不中断正常 pipeline。
            raise ValueError("post split geometry anomaly detected")

        merge_groups = derive_post_geometry_merge_groups(merge_candidates)
        anomaly_validation_info = {
            "valid": True,
            "warning_count": int(len(anomaly_findings)),
            "warnings": anomaly_findings,
            "strict_mode": bool(config.get("post_geometry_merge_strict_anomaly_fail", False)),
        }
        iteration_debug: dict[str, Any] = {
            "iteration_index": int(iteration_index),
            "candidate_count": int(len(merge_candidates) + len(anomaly_findings)),
            "merge_candidate_count": int(len(merge_candidates)),
            "anomaly_candidate_count": int(len(anomaly_findings)),
            "merge_candidates": merge_candidates,
            "anomaly_findings": anomaly_findings,
            "anomaly_validation_info": anomaly_validation_info,
            "merge_groups": merge_groups,
            "applied": False,
        }
        iterations.append(iteration_debug)
        if not merge_groups:
            # 没有可合并组时，本轮只把 anomaly/candidate 证据留在 debug。
            # 当前几何已经是最终几何，不需要再重复 rebuild。
            break

        # 二次合并仍复用统一节点合并执行器，但内部边失效原因必须标出 post-geometry 来源。
        # 这样后续排查能区分初始 geodesic merge 与 edge split 后短内部边 merge。
        merge_apply_debug = apply_node_merges(
            node_map=node_map,
            edge_map=edge_map,
            node_runtime=node_runtime,
            edge_runtime=edge_runtime,
            merge_groups=merge_groups,
            internal_inactive_reason="internal_after_post_geometry_merge",
        )
        current_node_geometry_debug, current_edge_geometry_debug = build_junction_geometry_outputs(
            geometry_preparation_result=geometry_preparation_result,
            node_map=node_map,
            edge_map=edge_map,
            node_runtime=node_runtime,
            edge_runtime=edge_runtime,
            config=config,
        )
        post_merge_validation = validate_post_geometry_merge_result(
            node_map=node_map,
            edge_map=edge_map,
            node_runtime=node_runtime,
            edge_runtime=edge_runtime,
            merge_candidates=merge_candidates,
        )
        if not bool(post_merge_validation["valid"]):
            raise ValueError("post geometry merge validation failed")
        iteration_debug["applied"] = True
        iteration_debug["merge_apply_debug"] = merge_apply_debug
        iteration_debug["validation_info"] = post_merge_validation
        iteration_debug["node_geometry_debug"] = current_node_geometry_debug
        iteration_debug["edge_geometry_debug"] = current_edge_geometry_debug
    else:
        # 跑满上限后先做一次只读探测，只有仍有可合并 A 类候选时才写 warning。
        remaining_merge_candidates = derive_post_geometry_merge_candidates(
            node_map=node_map,
            edge_map=edge_map,
            node_runtime=node_runtime,
            edge_runtime=edge_runtime,
            resolution_m_per_px=geometry_preparation_result.resolution_m_per_px,
            config=config,
        )
        if remaining_merge_candidates:
            iterations.append(
                {
                    "iteration_index": int(max_iterations),
                    "candidate_count": int(len(remaining_merge_candidates)),
                    "merge_candidate_count": int(len(remaining_merge_candidates)),
                    "anomaly_candidate_count": 0,
                    "merge_candidates": remaining_merge_candidates,
                    "anomaly_findings": [],
                    "merge_groups": derive_post_geometry_merge_groups(remaining_merge_candidates),
                    "applied": False,
                    "stopped_reason": "max_iterations_reached_with_remaining_merge_candidates",
                }
            )

    return (
        {
            "max_iterations": int(max_iterations),
            "iterations": iterations,
        },
        current_node_geometry_debug,
        current_edge_geometry_debug,
    )


def build_junction_rebuild(
    geometry_preparation_result: GeometryPreparationResult,
    config: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> JunctionRebuildResult:
    """在运行尺度几何世界上完成交汇重建。

    真实职责：
        junction_rebuild 必须先建立初始 `node_info / edge_info`，再做节点聚类合并、
        边重定向与失效、节点 polygon 写回、边内外路径切分，最后 compact 成
        只包含有效节点和有效边的正式输出。

    Args:
        geometry_preparation_result:
            geometry_preparation 正式输出。这里消费裁剪后灰度图、修剪后骨架与分辨率。
        config:
            junction_rebuild 阶段配置。支持合并门限、polygon 半径和可视化参数。
        context:
            运行时上下文。当前只保留接口，不把它当成正式算法输入。

    Returns:
        JunctionRebuildResult:
            junction_rebuild 正式输出。这里只包含 `node_info_list / edge_info_list`，
            仍然不建立 `graph_info`。

    副作用:
        当前函数不写文件、不修改全局状态；它只返回正式结果对象。
    """
    config, context = normalize_junction_rebuild_inputs(config, context)
    stage_outputs = build_junction_rebuild_stage_outputs(
        geometry_preparation_result=geometry_preparation_result,
        config=config,
    )
    return build_junction_rebuild_result(
        stage_outputs=stage_outputs,
        context=context,
    )


def normalize_junction_rebuild_inputs(
    config: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """规整 junction_rebuild 输入配置与上下文。"""

    # 入口统一补默认空字典，避免后续 helper 再判断 None。
    normalized_config = dict(config or {})
    # context 当前不参与正式求解，但保留为稳定 dict，便于结果 meta 和后续扩展使用。
    normalized_context = dict(context or {})
    # junction_rebuild 当前不消费 context 真值，但仍把它收成稳定 dict 以便 meta 记账。
    return normalized_config, normalized_context


def build_junction_rebuild_stage_outputs(
    *,
    geometry_preparation_result: GeometryPreparationResult,
    config: dict[str, Any],
) -> dict[str, Any]:
    """按 junction_rebuild 正式顺序构建子结果。"""

    # junction_rebuild 的第一件事是把骨架世界收成“可操作的初始节点和初始边”。
    # 这里只有初始 node/edge，还没有经过合并、polygon 和 compact。
    # 这一步拿到的是可变 runtime 结构，后续几何与 merge 都在其上演化。
    # 也正因为如此，junction_rebuild 内部允许出现 inactive 对象。
    node_map, node_runtime, edge_map, edge_runtime = build_initial_junction_runtime(
        geometry_preparation_result=geometry_preparation_result,
        config=config,
    )
    # 聚类/节点合并发生在初始 node/edge 建立之后，而不是之前。
    # 先做分组，再应用到 node/edge runtime，可把“发现规则”和“写回动作”分开。
    # merge_debug 保留“为什么会并到一起”，便于回看阈值是否过宽。
    # merge_apply_debug 则回答“这些分组最终怎样落到了对象层”。
    # 两层 debug 分开保留，避免“规则命中”和“对象改写”混成一团。
    merge_groups, merge_debug, merge_apply_debug = build_junction_merge_outputs(
        geometry_preparation_result=geometry_preparation_result,
        node_map=node_map,
        node_runtime=node_runtime,
        edge_map=edge_map,
        edge_runtime=edge_runtime,
        config=config,
    )
    # 节点合并收稳之后，再求节点 polygon；边几何切分严格依赖这些 polygon。
    # 这一步的顺序不能颠倒，否则边路径切分会基于旧节点边界。
    # node_geometry_debug 与 edge_geometry_debug 分开保留，便于判断问题落在哪层。
    # 节点几何先收口，边几何才能基于稳定 polygon 做切分。
    # 这里仍然只改 runtime，不提前生成 junction_rebuild 正式输出对象。
    node_geometry_debug, edge_geometry_debug = build_junction_geometry_outputs(
        geometry_preparation_result=geometry_preparation_result,
        node_map=node_map,
        edge_map=edge_map,
        node_runtime=node_runtime,
        edge_runtime=edge_runtime,
        config=config,
    )
    # 边几何切分完成后，才能判断两个 junction polygon 是否已经把中间通道段吃到极短。
    # 若命中 A 类内部短边，必须回到 junction_rebuild 的节点合并层收口，而不是让 coverage 阶段过滤。
    post_geometry_merge_debug, node_geometry_debug, edge_geometry_debug = build_post_geometry_merge_outputs(
        geometry_preparation_result=geometry_preparation_result,
        node_map=node_map,
        node_runtime=node_runtime,
        edge_map=edge_map,
        edge_runtime=edge_runtime,
        config=config,
        node_geometry_debug=node_geometry_debug,
        edge_geometry_debug=edge_geometry_debug,
    )
    # junction_rebuild 内部允许 inactive 对象存在，但对外必须 compact 成干净输出。
    # compact 后的对象才允许进入 topology_graph_build 建图，避免无效节点/边泄漏到主线。
    # compact_debug 记录了 runtime -> formal object 的收口过程。
    # 这一步也是 junction_rebuild “内部世界”和“正式输出世界”的硬边界。
    # 因此所有正式 node_id/edge_id 的稳定顺序也应在这里冻结。
    node_info_list, edge_info_list, compact_debug = compact_active_objects(
        node_map=node_map,
        edge_map=edge_map,
        node_runtime=node_runtime,
        edge_runtime=edge_runtime,
    )
    return {
        "node_info_list": node_info_list,
        "edge_info_list": edge_info_list,
        "merge_debug": merge_debug,
        "merge_apply_debug": merge_apply_debug,
        "post_geometry_merge_debug": post_geometry_merge_debug,
        "node_geometry_debug": node_geometry_debug,
        "edge_geometry_debug": edge_geometry_debug,
        "compact_debug": compact_debug,
    }


def build_junction_rebuild_result(
    *,
    stage_outputs: dict[str, Any],
    context: dict[str, Any],
) -> JunctionRebuildResult:
    """组装 junction_rebuild 正式结果。"""

    node_info_list = stage_outputs["node_info_list"]
    edge_info_list = stage_outputs["edge_info_list"]
    # 对外输出前做对象级闭环校验，确保 incident/path/degree 已经收稳。
    validation_info = validate_junction_rebuild_result(
        node_info_list=node_info_list,
        edge_info_list=edge_info_list,
    )
    validation_info["post_geometry_merge"] = build_post_geometry_merge_validation_info(
        stage_outputs["post_geometry_merge_debug"]
    )
    # debug_info 保留阶段内关键子步骤摘要，便于后续定位几何与 merge 问题。
    # meta 则只保留阶段名和上下文键，不把 context 本身复制进结果。
    return JunctionRebuildResult(
        node_info_list=node_info_list,
        edge_info_list=edge_info_list,
        debug_info={
            # merge_groups 保留规则命中证据，回答“为什么这些节点会被合并”。
            "merge_groups": stage_outputs["merge_debug"],
            # merge_groups_applied 保留对象级写回结果，回答“最终改动落到了哪些对象上”。
            "merge_groups_applied": stage_outputs["merge_apply_debug"].get("merge_groups_applied", []),
            # post_geometry_merge 记录 edge split 后内部短边合并与异常候选。
            "post_geometry_merge": stage_outputs["post_geometry_merge_debug"],
            "node_geometry": stage_outputs["node_geometry_debug"],
            "edge_geometry": stage_outputs["edge_geometry_debug"],
            "compact": stage_outputs["compact_debug"],
        },
        # validation_info 单独挂出，避免 debug 与正式校验语义混在一起。
        validation_info=validation_info,
        meta={
            "stage_name": "junction_rebuild",
            "context_keys": sorted(context.keys()),
        },
    )


def build_post_geometry_merge_validation_info(post_geometry_merge_debug: dict[str, Any]) -> dict[str, Any]:
    """把 post-geometry anomaly 归入机器可读 validation warning。"""

    warnings: list[dict[str, Any]] = []
    for iteration in post_geometry_merge_debug.get("iterations", []):
        for warning in iteration.get("anomaly_findings", []):
            warnings.append(dict(warning))
    return {
        "valid": True,
        "warning_count": int(len(warnings)),
        "warnings": warnings,
    }
