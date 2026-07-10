"""结果写出辅助函数。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..contracts import (
    CoveragePlanningResult,
    GeometryPreparationResult,
    JunctionRebuildResult,
    TopologyGraphBuildResult,
)
from .result_jsonable import to_jsonable as _to_jsonable


def normalize_output_dir(output_dir: str | Path) -> Path:
    """规整并创建输出目录。"""

    normalized = Path(output_dir)
    normalized.mkdir(parents=True, exist_ok=True)
    # 目录在这里统一创建，后续各写盘 helper 就只关心 payload，不再重复处理目录存在性。
    return normalized


def write_summary_payload(output_dir: str | Path, payload: dict[str, Any]) -> str:
    """把 summary payload 写到统一的 `summary.json`。"""

    output_path = normalize_output_dir(output_dir) / "summary.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(output_path.resolve())


def write_named_json_payload(output_dir: str | Path, filename: str, payload: dict[str, Any]) -> str:
    """把命名 payload 写到指定 json 文件。"""

    output_path = normalize_output_dir(output_dir) / filename
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(output_path.resolve())


def build_geometry_preparation_summary_payload(
    result: GeometryPreparationResult,
    extra_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """构造 geometry_preparation summary payload。"""

    return {
        "crop_box_px": list(result.crop_box_px),
        "gray_shape": list(result.gray.shape),
        "resolution_m_per_px": float(result.resolution_m_per_px),
        "region_pixel_count": int((result.region_mask > 0).sum()),
        "free_pixel_count": int((result.free_mask > 0).sum()),
        "obstacle_pixel_count": int((result.obstacle_mask > 0).sum()),
        "after_open_pixel_count": int((result.after_open_mask > 0).sum()),
        "skeleton_raw_pixel_count": int((result.skeleton_mask > 0).sum()),
        "skeleton_pruned_pixel_count": int((result.skeleton_pruned_mask > 0).sum()),
        "skeleton_pixels_rc_count": int(len(result.skeleton_pixels_rc)),
        "debug_info": _to_jsonable(result.debug_info),
        "validation_info": _to_jsonable(result.validation_info),
        "meta": _to_jsonable(result.meta),
        "extra_meta": _to_jsonable(extra_meta or {}),
    }


def build_topology_graph_summary_payload(
    result: TopologyGraphBuildResult,
    extra_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """构造 topology_graph_build summary payload。"""

    incident_port_info = result.incident_port_info or {}
    node_local_connection_hypothesis_info = result.node_local_connection_hypothesis_info or {}
    hypothesis_summary = dict(node_local_connection_hypothesis_info.get("summary", {}))
    # 这里故意只保留计数与摘要，不把 graph/candidate 全量结构直接塞进 summary。
    return {
        "graph_node_count": int(len(result.graph_info.nodes)),
        "graph_edge_count": int(len(result.graph_info.edges)),
        "incident_port_count": int(len(incident_port_info.get("items", ()))),
        "node_local_connection_hypothesis_count": int(len(node_local_connection_hypothesis_info.get("items", ()))),
        "forward_hypothesis_count": int(hypothesis_summary.get("forward_count", 0)),
        "foldback_hypothesis_count": int(hypothesis_summary.get("foldback_count", 0)),
        "debug_info": _to_jsonable(result.debug_info),
        "validation_info": _to_jsonable(result.validation_info),
        "meta": _to_jsonable(result.meta),
        "extra_meta": _to_jsonable(extra_meta or {}),
    }


def build_coverage_planning_result_payload(result: CoveragePlanningResult) -> dict[str, Any]:
    """构造 CoveragePlanning 完整结构化结果 payload。"""

    return {
        "graph_info": _to_jsonable(result.graph_info),
        "coverage_lane_sweep_info": _to_jsonable(result.coverage_lane_sweep_info),
        "sweep_graph_build_info": _to_jsonable(result.sweep_graph_build_info),
        "sweep_cadence_build_info": _to_jsonable(result.sweep_cadence_build_info),
        "final_coverage_path_build_info": _to_jsonable(result.final_coverage_path_build_info),
        "debug_info": _to_jsonable(result.debug_info),
        "validation_info": _to_jsonable(result.validation_info),
        "meta": _to_jsonable(result.meta),
    }


def write_geometry_preparation_summary(
    result: GeometryPreparationResult,
    output_dir: str | Path,
    extra_meta: dict[str, Any] | None = None,
) -> str:
    """写出 geometry_preparation 真实数据测试摘要。

    真实职责：
        把 geometry_preparation 结果里最关键的统计量和输入元信息导出成 json，
        方便人工核对真实数据测试是否符合预期。

    Args:
        result:
            geometry_preparation 正式结果。
        output_dir:
            输出目录。
        extra_meta:
            额外写入的输入或运行元信息。

    Returns:
        str:
            summary.json 的绝对路径字符串。
    """

    # 真实 case 摘要总是写到独立目录，避免不同轮次结果互相覆盖。
    # 这里优先导出“geometry_preparation 可人工核对的计数真值”，而不是整块数组。
    # debug/validation/meta 会走统一 jsonable 归一层，避免写盘时出现对象类型差异。
    # summary 层只暴露最小必要统计，不承担持久化完整对象的职责。
    # 因此这里的字段布局也尽量保持短平快，便于人工直接打开核对。
    # 大数组如果要看，应该通过可视化或完整对象文件查看，而不是 summary。
    payload = build_geometry_preparation_summary_payload(result, extra_meta)
    # summary.json 固定使用稳定缩进格式，方便后续 compare 和人工 diff。
    # 输出路径统一 resolve，便于过程记录直接复用绝对路径。
    # 写盘动作只发生一次，不做临时文件中转，减少 smoke 输出噪声。
    return write_summary_payload(output_dir, payload)


def write_junction_rebuild_summary(
    result: JunctionRebuildResult,
    output_dir: str | Path,
    extra_meta: dict[str, Any] | None = None,
) -> str:
    """写出 junction_rebuild 真实数据测试摘要。

    真实职责：
        把 junction_rebuild 输出的节点数、边数、polygon 与路径拆分等关键统计导出成 json，
        方便人工核对真实 case 上的重建结果是否合理。

    Args:
        result:
            junction_rebuild 正式结果。
        output_dir:
            输出目录。
        extra_meta:
            额外写入的运行元信息。

    Returns:
        str:
            summary.json 的绝对路径。
    """

    # junction_rebuild real-case 摘要既要看数量，也要看节点/边级局部几何概况。
    # 摘要里同时保留节点和边级条目，方便人工把“拓扑数量”与“几何细节”一起核对。
    # 这里不写完整 polygon/path，只写计数摘要，避免 smoke 文件过度膨胀。
    # 因而节点条目只保留 degree、incident 和 polygon 顶点数量等关键字段。
    # 边条目也只保留 path 长度和首尾节点，不把整条 path 原样落盘。
    # 这些字段足够回答“节点数对不对”“边切分是否合理”“局部几何是否空洞”。
    # 更细颗粒度的对象排查则交给完整结构文件和可视化产物。
    # 因此 summary 里的 node/edge 列表都是“轻量索引视图”，不是完整真值镜像。
    # 人工看这份 summary 时，重点不是逐点几何，而是规模和局部结构是否合理。
    # 这也让 junction_rebuild summary 能在真实 case 上保持可读，不会被长路径淹没。
    payload = {
        "node_count": len(result.node_info_list),
        "edge_count": len(result.edge_info_list),
        "junction_node_count": int(sum(1 for item in result.node_info_list if item.node_type == "junction")),
        "dead_end_node_count": int(sum(1 for item in result.node_info_list if item.node_type == "dead_end")),
        "polygon_node_count": int(sum(1 for item in result.node_info_list if item.polygon_vertices_rc)),
        "edge_outer_path_count": int(sum(1 for item in result.edge_info_list if item.outer_path_rc)),
        "edge_inner_path_count": int(sum(1 for item in result.edge_info_list if item.inner_path_rc)),
        "nodes": [
            {
                "node_id": int(item.node_id),
                "node_type": item.node_type,
                "point_rc": [float(item.point_rc[0]), float(item.point_rc[1])],
                "degree": int(item.degree),
                "unique_incident_edge_count": int(len(item.incident_edge_ids)),
                "incident_edge_ids": [int(edge_id) for edge_id in item.incident_edge_ids],
                "polygon_vertex_count": int(len(item.polygon_vertices_rc or ())),
            }
            for item in result.node_info_list
        ],
        "edges": [
            {
                "edge_id": int(item.edge_id),
                "src_node_id": int(item.src_node_id),
                "dst_node_id": int(item.dst_node_id),
                "path_point_count": int(len(item.path_rc)),
                "outer_path_point_count": int(len(item.outer_path_rc)),
                "inner_path_point_count": int(len(item.inner_path_rc)),
                "length_px": float(item.length_px),
                "length_m": float(item.length_m),
            }
            for item in result.edge_info_list
        ],
        "debug_info": _to_jsonable(result.debug_info),
        "validation_info": _to_jsonable(result.validation_info),
        "meta": _to_jsonable(result.meta),
        "extra_meta": _to_jsonable(extra_meta or {}),
    }
    # 写盘格式与 geometry_preparation 保持一致，便于统一工具读取。
    # junction_rebuild 和 geometry_preparation 共用同名 summary，是为了让 real-case 脚本按阶段目录读取。
    # 返回绝对路径后，调用方无需再自己拼接输出目录。
    # 这里也不做额外排序，因为正式结果本身已经在上游固定顺序。
    # 所以 summary diff 一旦变化，通常意味着上游正式对象真的发生了漂移。
    # 换言之，这个文件的变化应该被当成信号，而不是噪声。
    return write_summary_payload(output_dir, payload)


def write_topology_graph_build_summary(
    result: TopologyGraphBuildResult,
    output_dir: str | Path,
    extra_meta: dict[str, Any] | None = None,
) -> str:
    """写出 topology_graph_build 真实数据测试摘要。"""

    # topology_graph_build 摘要聚焦 graph/candidate/directed lane 三层的关键计数。
    # 这些计数足以帮助判断“建图成功但规则分类漂移”这类问题。
    # 这里不额外展开 candidate/lane 明细，避免 stage-3 smoke 输出被明细淹没。
    # 明细如果需要，优先通过 compare 支撑文件和中间可视化去看。
    # 因而这里的核心价值是提供稳定的“高信号计数面板”。
    payload = build_topology_graph_summary_payload(result, extra_meta)
    # 仍然沿用统一 summary.json 名称，便于 real-case 脚本固定读取。
    # 绝对路径返回约定与其它 stage 保持一致，方便过程记录工具直接收口。
    # 这里的输出层职责只到“稳定写 json”，不承担目录命名策略。
    return write_summary_payload(output_dir, payload)


def write_coverage_planning_summary(
    result: CoveragePlanningResult,
    output_dir: str | Path,
    extra_meta: dict[str, Any] | None = None,
) -> str:
    """写出 CoveragePlanning 真实数据测试摘要。"""

    # 四个 coverage planning 子域结果都允许为空，因此这里先统一抽摘要，避免 payload 组装阶段分叉。
    coverage_lane_sweep_info = result.coverage_lane_sweep_info
    sweep_graph_build_info = result.sweep_graph_build_info
    sweep_cadence_build_info = result.sweep_cadence_build_info
    final_coverage_path_build_info = result.final_coverage_path_build_info
    # 四层 summary 都先转普通 dict，后续 payload 读取就不再关心 dataclass/Mapping 差异。
    coverage_lane_sweep_summary = dict(coverage_lane_sweep_info.summary) if coverage_lane_sweep_info is not None else {}
    sweep_graph_summary = dict(sweep_graph_build_info.summary) if sweep_graph_build_info is not None else {}
    sweep_transition_candidate_summary = (
        dict(sweep_graph_build_info.sweep_transition_candidate_info.get("summary", {}))
        if sweep_graph_build_info is not None and sweep_graph_build_info.sweep_transition_candidate_info is not None
        else {}
    )
    sweep_cadence_summary = dict(sweep_cadence_build_info.summary) if sweep_cadence_build_info is not None else {}
    final_coverage_path_summary = dict(final_coverage_path_build_info.summary) if final_coverage_path_build_info is not None else {}
    # 覆盖统计来自 sweep cadence，终态合法性来自 final coverage path，这里显式拆开读取来源。
    # 这样一旦 coverage_ratio 和 final_path_valid 同时异常，就能立即定位落在哪层。
    # None 容错放在这里统一做，下游 payload 不再散落空值判断。
    coverage_stats = sweep_cadence_build_info.coverage_stats if sweep_cadence_build_info is not None else {}
    final_validation = (
        final_coverage_path_build_info.validation_info
        if final_coverage_path_build_info is not None and final_coverage_path_build_info.validation_info is not None
        else {}
    )
    # 摘要优先暴露人工最常看的四类指标：lane/sweep 数、cadence 覆盖率、最终路径长度、失败连接数。
    # 这些字段同时覆盖“几何规模”“求解规模”“终态合法性”三条人工判断主线。
    # 这里仍然不写完整 FinalCoveragePath 明细，那部分由完整结果 json 承担。
    # 四个 coverage planning 子域的关键规模指标都落到同一层，方便人工单文件横向比对。
    # 同时保留 graph 级计数，避免只看覆盖结果却忽略上游图规模漂移。
    # 这也是 CoveragePlanning summary 比较适合作为 baseline 首层比较入口的原因。
    # 真正深入到某条 route 或某个 sweep 时，再转去完整结果文件查看。
    payload = {
        "graph_node_count": int(len(result.graph_info.nodes)),
        "graph_edge_count": int(len(result.graph_info.edges)),
        "coverage_lane_unit_count": int(coverage_lane_sweep_summary.get("coverage_lane_count", 0)),
        "sweep_count": int(coverage_lane_sweep_summary.get("sweep_count", 0)),
        "sweep_group_count": int(sweep_graph_summary.get("sweep_group_count", 0)),
        "sweep_port_view_count": int(sweep_graph_summary.get("sweep_port_view_count", 0)),
        "sweep_transition_candidate_count": int(sweep_graph_summary.get("sweep_transition_candidate_count", 0)),
        "sweep_transition_strong_candidate_count": int(sweep_transition_candidate_summary.get("strong_candidate_count", 0)),
        "sweep_transition_weak_candidate_count": int(sweep_transition_candidate_summary.get("weak_candidate_count", 0)),
        "sweep_transition_fallback_candidate_count": int(sweep_transition_candidate_summary.get("fallback_candidate_count", 0)),
        "sweep_cadence_count": int(sweep_cadence_summary.get("sweep_cadence_count", 0)),
        "final_coverage_path_route_count": int(final_coverage_path_summary.get("route_count", 0)),
        "junction_connection_count": int(final_coverage_path_summary.get("junction_connection_count", 0)),
        "final_path_forward_connection_count": int(final_coverage_path_summary.get("forward_connection_count", 0)),
        "final_path_foldback_connection_count": int(final_coverage_path_summary.get("foldback_connection_count", 0)),
        "final_path_point_count": int(final_coverage_path_summary.get("path_point_count", 0)),
        "final_path_length_m": float(final_coverage_path_summary.get("path_length_m", 0.0)),
        "final_path_invalid_connection_count": int(final_validation.get("invalid_connection_count", 0)),
        "final_path_is_valid": bool(final_validation.get("is_valid", False)),
        "final_path_route_seam_break_count": int(final_validation.get("route_seam_break_count", 0)),
        "covered_sweep_count": int(coverage_stats.get("covered_sweep_count", 0)),
        "total_sweep_count": int(coverage_stats.get("total_sweep_count", 0)),
        "coverage_ratio": float(coverage_stats.get("coverage_ratio", 0.0)),
        "is_complete": bool(coverage_stats.get("is_complete", False)),
        "debug_info": _to_jsonable(result.debug_info),
        "validation_info": _to_jsonable(result.validation_info),
        "meta": _to_jsonable(result.meta),
        "extra_meta": _to_jsonable(extra_meta or {}),
    }
    # CoveragePlanning real-case 与 compare 都依赖稳定 json 格式，因此这里不做压缩写出。
    # 阶段摘要与完整结果拆成两个文件，是为了让人工 diff 时先看高信号摘要。
    # summary 负责“先发现异常”，完整结果负责“再定位异常”。
    # 这里固定 UTF-8 非 ASCII 保留策略，避免中文原因字段被转义后难读。
    # 同一目录下两类文件各司其职，避免把摘要和完整真值混成一个超大文件。
    return write_summary_payload(output_dir, payload)


def write_coverage_planning_result_json(
    result: CoveragePlanningResult,
    output_dir: str | Path,
) -> str:
    """写出 CoveragePlanning 完整结构化结果，供对象层核查。"""

    # 完整结果写出用于对象层排查，因此这里保留 graph 与四个 coverage planning 子域的正式对象。
    # 与 summary 不同，这里追求“可核查结构完整”，不是“摘要最短”。
    # 完整结果和 summary 并存，分别服务“快速核对”和“深度追查”两类场景。
    # 这里的 payload 结构基本贴结果对象树，方便后续 compare 逐层映射。
    payload = build_coverage_planning_result_payload(result)
    # 文件名固定为 `coverage_planning_result.json`，便于 baseline 工具直接定位。
    # 这里不沿用 summary.json，是为了避免 compare 工具混淆摘要和完整真值文件。
    # 单独命名也便于同目录下同时保留摘要和完整真值而不互相覆盖。
    return write_named_json_payload(output_dir, "coverage_planning_result.json", payload)
