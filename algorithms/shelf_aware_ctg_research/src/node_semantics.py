from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from algorithms.shelf_aware_ctg_research.src.ctg_territory_extractor import extract_ctg_territory
from algorithms.shelf_aware_ctg_research.src.project_inputs import build_study_input
from algorithms.shelf_aware_ctg_research.src.territory_expansion import expand_dead_end_territories


@dataclass(frozen=True)
class NodeSemanticsConfig:
    # footprint_radius_factor：节点 footprint 半径相对覆盖宽度的比例。
    footprint_radius_factor: float = 0.5
    # small_local_free_ratio_threshold：局部 free 比例低于该值时认为覆盖收益偏低。
    small_local_free_ratio_threshold: float = 0.45
    # low_degree_threshold：非障碍邻居数小于等于该值时认为连接性弱。
    low_degree_threshold: int = 5
    # obstacle_neighbor_boundary_threshold：障碍邻居数过多时认为节点靠边敏感。
    obstacle_neighbor_boundary_threshold: int = 2
    # min_clearance_boundary_m：运行时按 coverage_width_m * 0.7 写入，不再使用固定 0.10m。
    min_clearance_boundary_m: float = 0.0
    # mixed_ratio_threshold：某类空间占比超过该阈值才算进入 mixed_space。
    mixed_ratio_threshold: float = 0.10


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_child_run(variant_dir: Path) -> Path:
    runs = sorted(path for path in variant_dir.glob("run_*") if path.is_dir())
    if not runs:
        raise ValueError(f"missing planner run directory: {variant_dir}")
    return runs[-1]


def load_baseline_nodes(area_dir: Path) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    # 只读取 shelf_aware_baseline 的真实 grid node，不重新生成或修改节点。
    run_dir = latest_child_run(area_dir / "shelf_aware_baseline")
    # metadata.json 提供分辨率、coverage_width_px 等规划尺度信息。
    metadata_path = run_dir / "metadata.json"
    nodes_path = run_dir / "node_debug_enriched.json"
    # 缺少 metadata 说明该 baseline run 不完整，不能继续做语义研究。
    if not metadata_path.is_file():
        raise ValueError(f"missing metadata: {metadata_path}")
    # node_debug_enriched.json 是本研究代码的节点事实源。
    if not nodes_path.is_file():
        raise ValueError(f"missing node_debug_enriched.json: {nodes_path}")
    # obstacle 节点不参与覆盖语义，只保留可通行 grid node。
    nodes = [node for node in load_json(nodes_path) if not bool(node.get("obstacle", True))]
    return run_dir, load_json(metadata_path), nodes


def build_semantic_maps(area_dir: Path, *, apply_boundary_smoothing: bool = True) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    # summary.json 记录 area 对应的原始 maptools project 和 area_id。
    summary = load_json(area_dir / "summary.json")
    project_dir = Path(summary["project_dir"])
    # area_id 用来重新构建 CTG 输入，保证 label map 与当前 area 对齐。
    area_id = int(summary["area_id"])
    study_input = build_study_input(project_dir, area_id, area_dir / "diagnostics" / "node_semantics_prepare_map")
    # 这里复用 CTG 前处理结果，只提取 free_mask、expanded territory、junction polygon。
    ctg = extract_ctg_territory(study_input, apply_boundary_smoothing=apply_boundary_smoothing)
    geometry_result = ctg["geometry_result"]
    # graph_info.nodes 内的 polygon_vertices_rc 是 junction_label 的唯一来源。
    graph_info = ctg["topology_result"].graph_info
    lane_info = tuple(ctg["coverage_lane_sweep_info"].coverage_lane_info)
    # expanded.labels 表示 edge territory 势力范围，不负责表达 junction。
    expanded = expand_dead_end_territories(geometry_result, graph_info, lane_info)
    free_mask = np.where(np.asarray(geometry_result.free_mask) > 0, 255, 0).astype(np.uint8)
    # territory_labels 中 label >= 0 表示 edge id，label < 0 只表示非 edge。
    territory_labels = np.asarray(expanded.labels, dtype=np.int32)
    junction_id_map = np.full(free_mask.shape, -1, dtype=np.int32)
    junction_records: list[dict[str, Any]] = []
    # 每个 junction polygon 单独 rasterize 成 junction_id，不偷用 territory_label < 0。
    for node in graph_info.nodes:
        polygon = tuple(getattr(node, "polygon_vertices_rc", None) or ())
        # 没有合法 polygon 的 node 不能作为 junction 面区域参与统计。
        if len(polygon) < 3:
            continue
        junction_id = int(getattr(node, "node_id", len(junction_records) + 1))
        # CTG polygon 是 row/col，这里转换为 OpenCV fillPoly 需要的 x/y。
        points_xy = np.array(
            [[int(round(float(col))), int(round(float(row)))] for row, col in polygon],
            dtype=np.int32,
        )
        # junction_id_map 的像素值就是 junction_label / junction_id。
        cv2.fillPoly(junction_id_map, [points_xy], junction_id)
        junction_records.append(
            {
                "junction_id": junction_id,
                "point_rc": list(getattr(node, "point_rc", ())),
                "degree": int(getattr(node, "degree", 0)),
                "incident_edge_ids": [int(edge_id) for edge_id in tuple(getattr(node, "incident_edge_ids", ()))],
                "polygon_vertex_count": int(len(polygon)),
            }
        )
    return free_mask, territory_labels, junction_id_map, {
        "project_dir": str(project_dir),
        "area_id": area_id,
        "resolution_m_per_px": float(summary["resolution_m_per_px"]),
        "free_shape": list(free_mask.shape),
        "junction_count": int(len(junction_records)),
        "junctions": junction_records,
    }


def footprint_slices(shape: tuple[int, int], point_xy: tuple[float, float], radius_px: int) -> tuple[slice, slice]:
    # point_xy 是原图坐标系下的 node center_pixel。
    x = int(round(float(point_xy[0])))
    y = int(round(float(point_xy[1])))
    # shape 是 free_mask 的高宽，footprint 不能越界。
    h, w = shape
    # 返回 row slice 与 col slice，后续所有像素统计都使用这个窗口。
    return slice(max(0, y - radius_px), min(h, y + radius_px + 1)), slice(max(0, x - radius_px), min(w, x + radius_px + 1))


def counter_to_dict(counter: Counter[int]) -> dict[str, int]:
    # JSON key 统一转成字符串，避免 int key 在不同工具中展示不一致。
    return {str(int(key)): int(value) for key, value in sorted(counter.items())}


def compute_space_stats(
    *,
    free_mask: np.ndarray,
    territory_labels: np.ndarray,
    junction_id_map: np.ndarray,
    center_xy: tuple[float, float],
    radius_px: int,
    mixed_ratio_threshold: float,
) -> dict[str, Any]:
    # footprint 是围绕 grid node 中心取出的局部像素窗口。
    rows, cols = footprint_slices(free_mask.shape, center_xy, radius_px)
    # free_patch 只保留可通行像素，障碍物像素不参与归属比例统计。
    free_patch = free_mask[rows, cols] > 0
    # window_pixel_count 是完整窗口像素数，包含障碍物和 free。
    window_pixel_count = int(free_patch.size)
    # free_count 是窗口内真正可覆盖/可通行的像素数。
    free_count = int(np.count_nonzero(free_patch))
    # 如果窗口里没有 free 像素，这个节点在空间语义上就是 empty。
    if free_count <= 0:
        return {
            "footprint_radius_px": int(radius_px),
            "footprint_window_pixel_count": window_pixel_count,
            "footprint_free_pixel_count": 0,
            "local_free_ratio": 0.0,
            "territory_pixel_counts": {},
            "junction_pixel_counts": {},
            "unknown_pixel_count": 0,
            "primary_space_type": "empty",
            "primary_territory_label": None,
            "primary_junction_id": None,
            "territory_ratio": 0.0,
            "junction_ratio": 0.0,
            "unknown_ratio": 0.0,
            "mixed_space": False,
            "mixed_space_types": [],
        }
    # territory_patch 是同一窗口内每个像素的 edge territory label。
    territory_patch = territory_labels[rows, cols]
    # junction_patch 是同一窗口内每个像素的 junction polygon id。
    junction_patch = junction_id_map[rows, cols]
    # territory_counter 只统计 free 像素上的有效 edge id，label < 0 不算 edge。
    territory_counter: Counter[int] = Counter(int(value) for value in territory_patch[free_patch] if int(value) >= 0)
    # junction_counter 只统计 free 像素上的有效 junction id，id < 0 不算 junction。
    junction_counter: Counter[int] = Counter(int(value) for value in junction_patch[free_patch] if int(value) >= 0)
    # territory_total 表示该 footprint 内落入所有 edge territory 的 free 像素数。
    territory_total = int(sum(territory_counter.values()))
    # junction_total 表示该 footprint 内落入所有 junction polygon 的 free 像素数。
    junction_total = int(sum(junction_counter.values()))
    # unknown 是 free 像素，但既不属于 edge territory，也不属于 junction polygon。
    unknown_mask = free_patch & (territory_patch < 0) & (junction_patch < 0)
    # unknown_count 后续用于判断节点是否主要处在未归属区域。
    unknown_count = int(np.count_nonzero(unknown_mask))
    # best_territory 是 footprint 内占比最高的 edge id 及其像素数。
    best_territory = territory_counter.most_common(1)[0] if territory_counter else (None, 0)
    # best_junction 是 footprint 内占比最高的 junction id 及其像素数。
    best_junction = junction_counter.most_common(1)[0] if junction_counter else (None, 0)
    # 三类空间竞争：edge、junction、unknown，谁的 free 像素最多谁是主空间。
    candidates = [("edge", best_territory[0], int(best_territory[1])), ("junction", best_junction[0], int(best_junction[1])), ("unknown", None, unknown_count)]
    # primary_type 是该节点空间语义的主标签，不是覆盖角色。
    primary_type, primary_id, primary_count = max(candidates, key=lambda item: item[2])
    # 如果三类都没有像素，兜底为 empty，避免把 0 像素误判为 unknown。
    if primary_count <= 0:
        primary_type, primary_id = "empty", None
    # territory_ratio 是最高占比 edge 的像素数 / free_count。
    territory_ratio = float(best_territory[1] / free_count) if best_territory[0] is not None else 0.0
    # junction_ratio 是最高占比 junction 的像素数 / free_count。
    junction_ratio = float(best_junction[1] / free_count) if best_junction[0] is not None else 0.0
    # unknown_ratio 是未归属 free 像素数 / free_count。
    unknown_ratio = float(unknown_count / free_count)
    # mixed_types 记录 footprint 是否同时显著覆盖多类空间。
    mixed_types = []
    # 只要 edge 总占比超过阈值，就认为 mixed 空间里包含 edge。
    if territory_total / free_count >= mixed_ratio_threshold:
        mixed_types.append("edge")
    # 只要 junction 总占比超过阈值，就认为 mixed 空间里包含 junction。
    if junction_total / free_count >= mixed_ratio_threshold:
        mixed_types.append("junction")
    # unknown 占比超过阈值时，说明节点有一部分落在未明确归属区域。
    if unknown_ratio >= mixed_ratio_threshold:
        mixed_types.append("unknown")
    # 返回值保留原始计数和比例，方便从 json 反查每个节点的判定原因。
    return {
        "footprint_radius_px": int(radius_px),
        "footprint_window_pixel_count": window_pixel_count,
        "footprint_free_pixel_count": free_count,
        "local_free_ratio": float(free_count / window_pixel_count) if window_pixel_count else 0.0,
        "territory_pixel_counts": counter_to_dict(territory_counter),
        "junction_pixel_counts": counter_to_dict(junction_counter),
        "unknown_pixel_count": unknown_count,
        "primary_space_type": primary_type,
        "primary_territory_label": int(primary_id) if primary_type == "edge" and primary_id is not None else None,
        "primary_junction_id": int(primary_id) if primary_type == "junction" and primary_id is not None else None,
        "territory_ratio": territory_ratio,
        "junction_ratio": junction_ratio,
        "unknown_ratio": unknown_ratio,
        "mixed_space": bool(len(mixed_types) >= 2),
        "mixed_space_types": mixed_types,
    }


def clamp01(value: float) -> float:
    # coverage_obligation 和 connectivity_value 都约束在 0~1。
    return float(max(0.0, min(1.0, value)))


def compute_semantics(node: dict[str, Any], space: dict[str, Any], *, config: NodeSemanticsConfig, resolution: float) -> dict[str, Any]:
    # degree 是 shelf_aware_baseline 里该 grid node 的非障碍邻居数。
    degree = int(node.get("non_obstacle_neighbor_count", 0))
    # obstacle_neighbors 表示该节点周围有多少邻居方向被障碍物阻断。
    obstacle_neighbors = int(node.get("obstacle_neighbor_count", 0))
    # min_distance_m 是 node 到最近障碍物的距离，来自 baseline 节点诊断。
    min_distance_m = float(node.get("min_distance_m", 0.0))
    # 边界距离阈值同时考虑 coverage_width_m * 0.7 和 1.5 个像素，避免阈值过小。
    clearance_threshold_m = max(float(config.min_clearance_boundary_m), float(resolution) * 1.5)
    # small_local_free 表示 footprint 内 free 比例偏低，通常是边界毛刺或小凸出区域。
    small_local_free = float(space["local_free_ratio"]) <= float(config.small_local_free_ratio_threshold)
    # low_degree 表示这个节点的拓扑连接选择少，容易成为死角或残留点。
    low_degree = degree <= int(config.low_degree_threshold)
    # boundary 通过“离障碍近”或“障碍邻居多”判断，当前只是质量标签，不直接改空间归属。
    boundary = min_distance_m <= clearance_threshold_m or obstacle_neighbors >= int(config.obstacle_neighbor_boundary_threshold)
    # primary 是 compute_space_stats 给出的主空间类型：edge / junction / unknown / empty。
    primary = str(space["primary_space_type"])
    # edge territory 当前被认为覆盖责任最高，这是部分可疑点成为 cover_core 的直接原因。
    if primary == "edge":
        base_obligation = 1.0
    # junction 不作为独立强覆盖区域，覆盖责任低于 edge。
    elif primary == "junction":
        base_obligation = 0.55
    # unknown 是 free 但未明确归属区域，先给较低覆盖责任。
    elif primary == "unknown":
        base_obligation = 0.45
    # empty 没有覆盖责任。
    else:
        base_obligation = 0.0
    # quality_factor 是覆盖责任的折减系数，当前只做轻量降权。
    quality_factor = 1.0
    # 局部 free 比例过低时，说明这个点覆盖收益偏低，所以覆盖责任乘 0.55。
    if small_local_free:
        quality_factor *= 0.60
    if boundary:
        quality_factor *= 0.60
    if low_degree:
        quality_factor *= 0.60
    # # 贴边且 local free 小时，再额外降权；单独 boundary 当前不会降权。
    # if boundary and small_local_free and primary != "junction":
    #     quality_factor *= 0.70
    # # 连接性弱且 local free 小时，再额外降权；单独 low_degree 当前不会降权。
    # if low_degree and small_local_free:
    #     quality_factor *= 0.75
    # coverage_obligation 是最终覆盖责任分数，越高越应该作为主覆盖节点。
    coverage_obligation = clamp01(base_obligation * quality_factor)

    # connectivity_value 表示节点作为过渡/连接/重复访问节点的价值。
    if primary == "junction":
        connectivity_value = 0.90
    # edge 节点主要用于覆盖，默认连通价值中等。
    elif primary == "edge":
        connectivity_value = 0.40
    # unknown 节点没有明确空间语义，默认连通价值略低。
    elif primary == "unknown":
        connectivity_value = 0.35
    # empty 不参与连通。
    else:
        connectivity_value = 0.0
    # mixed_types 用于识别节点 footprint 是否跨了 edge/junction/unknown。
    mixed_types = set(space.get("mixed_space_types", []))
    # 只要节点同时碰到 junction 和其他空间，就提高它的连接价值。
    if "junction" in mixed_types and len(mixed_types) >= 2:
        connectivity_value = max(connectivity_value, 0.75)
    # 同一个 footprint 里碰到多个 edge territory，说明它可能是换边过渡点。
    if len(space.get("territory_pixel_counts", {})) >= 2:
        connectivity_value = max(connectivity_value, 0.70)
    # 低 degree 的非 junction 节点连接价值要降，避免把死角当过渡点。
    if low_degree and primary != "junction":
        connectivity_value *= 0.70
    # degree 很高时，说明邻接选择多，轻微提高连接价值。
    if degree >= 5:
        connectivity_value += 0.10
    # 连通价值同样约束到 0~1。
    connectivity_value = clamp01(connectivity_value)

    # role 是把覆盖责任和连通价值统一后的节点角色标签。
    if connectivity_value >= 0.75:
        role = "connector"
    # cover_core 的现有条件很简单：coverage_obligation >= 0.75。
    elif coverage_obligation >= 0.75:
        role = "cover_core"
    # cover_soft 是有覆盖意义但不应该强行主导远跳的节点。
    elif coverage_obligation >= 0.55:
        role = "cover_soft"
    # residual_soft 是低责任残留候选，后续需要 residual policy 处理。
    elif coverage_obligation >= 0.20:
        role = "residual_soft"
    # noise_candidate 是覆盖责任和连通价值都低的候选节点。
    else:
        role = "noise_candidate"
    # quality_features 和两个分数都会写入 json，便于逐节点复核。
    return {
        "small_local_free": bool(small_local_free),
        "low_degree": bool(low_degree),
        "boundary": bool(boundary),
        "degree": int(degree),
        "obstacle_neighbor_count": int(obstacle_neighbors),
        "min_distance_m": float(min_distance_m),
        "clearance_threshold_m": float(clearance_threshold_m),
        "coverage_obligation": coverage_obligation,
        "connectivity_value": connectivity_value,
        "node_role": role,
    }


def build_node_semantics_from_maps(
    area_dir: Path,
    *,
    free_mask: np.ndarray,
    territory_labels: np.ndarray,
    junction_id_map: np.ndarray,
    label_info: dict[str, Any],
    config: NodeSemanticsConfig | None = None,
) -> dict[str, Any]:
    # config 为空时使用当前研究版默认参数，不从正式 planner 读隐含参数。
    config = config or NodeSemanticsConfig()
    # baseline run 提供 grid node；本模块只做打标签，不重新生成 grid node。
    run_dir, metadata, nodes = load_baseline_nodes(area_dir)
    # resolution 是米/像素，用于把清扫宽度和边界距离统一到像素尺度。
    resolution = float(metadata["map_resolution"])
    # coverage_width_px 优先读 baseline 记录值，缺失时才由 coverage_width_m 推回。
    coverage_width_px = int(metadata.get("coverage_width_px") or max(1, round(float(metadata.get("coverage_width_m", 0.55)) / resolution)))
    # coverage_width_m 优先读 baseline 记录值，缺失时由像素宽度乘分辨率得到。
    coverage_width_m = float(metadata.get("coverage_width_m") or float(coverage_width_px) * resolution)
    # min_clearance_boundary_m 按用户要求设为 coverage_width_m 的 0.7 倍。
    min_clearance_boundary_m = float(coverage_width_m) * 0.7
    # config 是 frozen dataclass，所以用 replace 生成带动态边界阈值的新配置。
    effective_config = replace(config, min_clearance_boundary_m=min_clearance_boundary_m)
    # footprint 半径默认是覆盖宽度的一半，用来近似该节点实际覆盖影响范围。
    footprint_radius_px = max(1, int(round(float(coverage_width_px) * float(effective_config.footprint_radius_factor))))
    # records 是最终 node_semantics.json 里的 nodes 列表。
    records = []
    # 每个 baseline grid node 都独立计算空间归属和覆盖角色。
    for node in nodes:
        # center_pixel 是 x/y 坐标，和 OpenCV 绘图坐标保持一致。
        center = tuple(float(value) for value in node["center_pixel"])
        # space 保存该节点 footprint 内 edge/junction/unknown 的像素统计。
        space = compute_space_stats(
            free_mask=free_mask,
            territory_labels=territory_labels,
            junction_id_map=junction_id_map,
            center_xy=center,
            radius_px=footprint_radius_px,
            mixed_ratio_threshold=float(effective_config.mixed_ratio_threshold),
        )
        # semantics 把空间统计和 baseline 节点质量特征合成为 role。
        semantics = compute_semantics(node, space, config=effective_config, resolution=resolution)
        # 每个字段都显式写入，避免后续分析时再回查多个来源文件。
        records.append(
            {
                "node_id": str(node.get("node_id")),
                "grid_row": int(node.get("grid_row", -1)),
                "grid_col": int(node.get("grid_col", -1)),
                "center_pixel": [float(center[0]), float(center[1])],
                "visited_in_baseline": bool(node.get("visited", False)),
                "space": space,
                "quality_features": {
                    "small_local_free": semantics["small_local_free"],
                    "low_degree": semantics["low_degree"],
                    "boundary": semantics["boundary"],
                    "degree": semantics["degree"],
                    "obstacle_neighbor_count": semantics["obstacle_neighbor_count"],
                    "min_distance_m": semantics["min_distance_m"],
                    "clearance_threshold_m": semantics["clearance_threshold_m"],
                },
                "coverage_obligation": semantics["coverage_obligation"],
                "connectivity_value": semantics["connectivity_value"],
                "node_role": semantics["node_role"],
            }
        )
    # payload 是一个 area 的完整语义结果，json 和可视化都从这里生成。
    return {
        "area_dir": str(area_dir),
        "planner_run_dir": str(run_dir),
        "label_info": label_info,
        "resolution_m_per_px": resolution,
        "coverage_width_px": int(coverage_width_px),
        "coverage_width_m": float(coverage_width_m),
        "config": {
            "footprint_radius_factor": effective_config.footprint_radius_factor,
            "footprint_radius_px": int(footprint_radius_px),
            "small_local_free_ratio_threshold": effective_config.small_local_free_ratio_threshold,
            "low_degree_threshold": effective_config.low_degree_threshold,
            "obstacle_neighbor_boundary_threshold": effective_config.obstacle_neighbor_boundary_threshold,
            "min_clearance_boundary_m": effective_config.min_clearance_boundary_m,
            "min_clearance_boundary_rule": "coverage_width_m * 0.7",
            "mixed_ratio_threshold": effective_config.mixed_ratio_threshold,
        },
        "summary": summarize_records(records),
        "legend": legend_payload(),
        "nodes": records,
    }


def build_node_semantics(area_dir: Path, *, apply_boundary_smoothing: bool = True, config: NodeSemanticsConfig | None = None) -> dict[str, Any]:
    # 对外入口：先构建 label map，再把 label map 采样到 baseline grid node 上。
    free_mask, territory_labels, junction_id_map, label_info = build_semantic_maps(area_dir, apply_boundary_smoothing=apply_boundary_smoothing)
    # 后续逻辑只依赖显式传入的三张 map，便于单元测试或替换输入。
    return build_node_semantics_from_maps(
        area_dir,
        free_mask=free_mask,
        territory_labels=territory_labels,
        junction_id_map=junction_id_map,
        label_info=label_info,
        config=config,
    )


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    # role_counts 统计 cover_core/connector 等最终角色数量。
    role_counts = Counter(str(item["node_role"]) for item in records)
    # space_counts 统计 edge/junction/unknown 等空间主标签数量。
    space_counts = Counter(str(item["space"]["primary_space_type"]) for item in records)
    # quality_counts 只统计布尔质量标签为 True 的次数。
    quality_counts = Counter()
    # quality_features 里既有 bool，也有 degree/min_distance 等数值。
    for item in records:
        for key, value in item["quality_features"].items():
            # 只有 small_local_free/low_degree/boundary 这种 bool 标签进入计数。
            if isinstance(value, bool) and value:
                quality_counts[key] += 1
    # obligations 用于给出覆盖责任均值，帮助快速比较不同 area。
    obligations = [float(item["coverage_obligation"]) for item in records]
    # connectivity 用于给出连通价值均值，帮助判断 connector 是否过多。
    connectivity = [float(item["connectivity_value"]) for item in records]
    # summary 只放汇总指标，逐节点原因仍然看 nodes 明细。
    return {
        "node_count": int(len(records)),
        "node_role_counts": dict(sorted(role_counts.items())),
        "primary_space_counts": dict(sorted(space_counts.items())),
        "quality_feature_counts": dict(sorted(quality_counts.items())),
        "coverage_obligation_mean": float(sum(obligations) / len(obligations)) if obligations else 0.0,
        "connectivity_value_mean": float(sum(connectivity) / len(connectivity)) if connectivity else 0.0,
        "mixed_space_count": int(sum(1 for item in records if bool(item["space"].get("mixed_space")))),
    }


def role_color(role: str) -> tuple[int, int, int]:
    # OpenCV 使用 BGR 顺序，不是 RGB。
    return {
        # cover_core 用绿色，表示当前规则认为它是主覆盖节点。
        "cover_core": (30, 170, 60),
        # cover_soft 用青色，表示有覆盖价值但责任较弱。
        "cover_soft": (0, 210, 220),
        # connector 用蓝橙色，表示更偏通行/过渡。
        "connector": (220, 80, 30),
        # residual_soft 用橙色，表示后续 residual policy 处理对象。
        "residual_soft": (0, 140, 255),
        # noise_candidate 用红色，表示低价值候选。
        "noise_candidate": (0, 0, 220),
    }.get(role, (120, 120, 120))


def space_color(space: str) -> tuple[int, int, int]:
    # 空间图只表达 footprint 主空间类型，不表达最终覆盖角色。
    return {
        # edge 表示主要落在 expanded territory 的某条边势力范围内。
        "edge": (40, 180, 80),
        # junction 表示主要落在 junction polygon 内。
        "junction": (220, 80, 220),
        # unknown 表示 free 但没有明确 edge/junction 归属。
        "unknown": (150, 150, 150),
        # empty 表示 footprint 内没有 free 像素。
        "empty": (40, 40, 40),
    }.get(space, (120, 120, 120))


def append_legend_panel(image: np.ndarray, items: list[tuple[str, tuple[int, int, int], str]]) -> np.ndarray:
    # 图例使用右侧 panel，避免直接盖住地图内容。
    if not items:
        return image
    # panel_width 保持较窄，图中只放英文短标签。
    panel_width = 190
    # row_height 控制每个图例项的垂直间距。
    row_height = 24
    # panel 背景用浅灰，和地图底图区分。
    panel = np.full((image.shape[0], panel_width, 3), 245, dtype=np.uint8)
    # 左边界线用于区分地图和图例区域。
    cv2.line(panel, (0, 0), (0, panel.shape[0] - 1), (180, 180, 180), 1)
    # OpenCV 默认字体不支持中文，所以图上只写 ASCII。
    cv2.putText(panel, "Legend", (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 1, cv2.LINE_AA)
    # y 是当前图例项的绘制基线。
    y = 50
    # items 中包含短标签、颜色和英文辅助说明。
    for short_label, color, detail in items:
        # panel 高度不够时停止绘制，避免文字写出边界。
        if y + 18 >= panel.shape[0]:
            break
        # 圆点颜色和地图节点颜色保持一致。
        cv2.circle(panel, (18, y - 5), 5, color, -1)
        # short_label 是图上可读的最短类别名。
        cv2.putText(panel, short_label, (34, y), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (20, 20, 20), 1, cv2.LINE_AA)
        # detail 是英文补充说明，中文完整说明写入 json。
        if detail:
            cv2.putText(panel, detail, (34, y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (80, 80, 80), 1, cv2.LINE_AA)
            y += row_height + 10
        else:
            y += row_height
    # 返回拼接后的地图 + 图例整图。
    return np.hstack([image, panel])


def legend_payload() -> dict[str, dict[str, str]]:
    # 中文图例放在 json 里，避免 OpenCV 中文乱码和遮挡地图。
    return {
        "space_label_map": {
            "edge": "主通道 / edge territory 势力范围",
            "junction": "路口 polygon 区域，来源是 junction polygon，不是 territory_label < 0",
            "unknown": "未明确归属的 free 区域",
            "mixed": "节点 footprint 同时覆盖多类空间，图中用白色外圈表示",
        },
        "node_role_map": {
            "cover_core": "主覆盖节点，coverage_obligation 覆盖责任高",
            "cover_soft": "软覆盖节点，尽量覆盖但不应主导远跳",
            "connector": "连通节点，通常用于路口、换区或重复访问",
            "residual_soft": "低责任残留节点，后续 residual policy 判断是否补扫",
            "noise_candidate": "噪声候选节点，覆盖责任和连通价值都很低",
        },
        "heatmaps": {
            "coverage_obligation": "覆盖责任热力图，值越高越偏主覆盖",
            "connectivity_value": "连通价值热力图，值越高越适合作为过渡/重复访问节点",
        },
    }


def base_image(free_mask: np.ndarray) -> np.ndarray:
    # free_mask 是单通道图，先转成 BGR 才能画彩色节点。
    image = cv2.cvtColor(free_mask, cv2.COLOR_GRAY2BGR)
    # free 区域显示为浅灰，障碍物保持黑色。
    image[free_mask > 0] = (242, 242, 242)
    # 返回未放大的基础底图。
    return image


def scaled_base_image(free_mask: np.ndarray, scale: int) -> np.ndarray:
    # 先生成原尺寸底图，再做最近邻放大，避免底图被插值模糊。
    image = base_image(free_mask)
    # 最近邻放大 8 倍后，地图像素块边界仍然清楚。
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)


def scaled_point(point: list[float] | tuple[float, float], scale: int) -> tuple[int, int]:
    # point 是原图 x/y 坐标，绘制到放大图时需要同步乘 scale。
    return int(round(float(point[0]) * scale)), int(round(float(point[1]) * scale))


def draw_node_index(image: np.ndarray, index: int, point: tuple[int, int]) -> None:
    # index 是图上显示的 1-based 序号，方便和用户口头指出的点对应。
    cv2.putText(
        image,
        str(index),
        # 文字放在点右上方，不做描边，避免遮挡节点颜色。
        (point[0] + 4, point[1] - 4),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.32,
        (0, 0, 0),
        1,
        cv2.LINE_AA,
    )


def draw_space_label_map(free_mask: np.ndarray, records: list[dict[str, Any]], output_path: Path) -> None:
    # 当前按用户要求固定放大 8 倍，输出仍覆盖原文件名。
    scale = 8
    # 底图放大，节点点半径不随比例增大，避免点遮挡大片区域。
    image = scaled_base_image(free_mask, scale)
    # records 顺序和 node_semantics.json 一致，图上序号从 1 开始。
    for index, item in enumerate(records, start=1):
        # 节点坐标从原图坐标转换到放大图坐标。
        point = scaled_point(item["center_pixel"], scale)
        # 颜色由 primary_space_type 决定，和 role 无关。
        color = space_color(str(item["space"]["primary_space_type"]))
        cv2.circle(image, point, 2, color, -1)
        # mixed_space 用白圈提示该节点 footprint 覆盖多类空间。
        if bool(item["space"].get("mixed_space")):
            cv2.circle(image, point, 4, (255, 255, 255), 1)
        # 每个点都标序号，便于精确讨论某个节点。
        draw_node_index(image, index, point)
    # 右侧图例只显示短英文，中文解释见 json legend。
    image = append_legend_panel(
        image,
        [
            ("edge", space_color("edge"), "territory"),
            ("junction", space_color("junction"), "polygon"),
            ("unknown", space_color("unknown"), "free area"),
            ("mixed", (255, 255, 255), "white ring"),
        ],
    )
    # 覆盖写回 01_node_space_label_map.png，不保留旧图。
    cv2.imwrite(str(output_path), image)


def draw_role_map(free_mask: np.ndarray, records: list[dict[str, Any]], output_path: Path) -> None:
    # role 图也固定放大 8 倍，和 space 图保持一致。
    scale = 8
    # 底图仍然只表达 free/obstacle，不额外叠加 territory 面。
    image = scaled_base_image(free_mask, scale)
    # 每个节点按最终 node_role 着色。
    for index, item in enumerate(records, start=1):
        # 坐标乘 scale 后才能和放大底图对齐。
        point = scaled_point(item["center_pixel"], scale)
        # role_color 只看 node_role，不看具体 edge id 或 junction id。
        cv2.circle(image, point, 2, role_color(str(item["node_role"])), -1)
        # 标序号，便于和 node_semantics.json 的 nodes 顺序对应。
        draw_node_index(image, index, point)
    # 右侧图例解释 role 的英文短名。
    image = append_legend_panel(
        image,
        [
            ("cover_core", role_color("cover_core"), "main cover"),
            ("cover_soft", role_color("cover_soft"), "soft cover"),
            ("connector", role_color("connector"), "transition"),
            ("residual", role_color("residual_soft"), "low obligation"),
            ("noise", role_color("noise_candidate"), "candidate"),
        ],
    )
    # 覆盖写回 02_node_role_map.png，不保留旧图。
    cv2.imwrite(str(output_path), image)


def draw_value_heatmap(free_mask: np.ndarray, records: list[dict[str, Any]], key: str, output_path: Path) -> None:
    # values 是原图尺寸的稀疏分数图，每个节点中心写入一个分数。
    values = np.zeros(free_mask.shape, dtype=np.float32)
    # key 通常是 coverage_obligation 或 connectivity_value。
    for item in records:
        x, y = (int(round(float(v))) for v in item["center_pixel"])
        # 只写入图像范围内的节点，避免异常坐标导致越界。
        if 0 <= y < values.shape[0] and 0 <= x < values.shape[1]:
            values[y, x] = max(values[y, x], float(item[key]))
    # 高斯模糊只是为了可视化成热力图，不参与算法判定。
    values = cv2.GaussianBlur(values, (0, 0), sigmaX=3.0, sigmaY=3.0)
    # 归一化到 0~1，便于不同 area 的图视觉范围一致。
    if float(values.max()) > 0.0:
        values = values / float(values.max())
    # TURBO 色表只用于观察分数分布。
    heat = cv2.applyColorMap((values * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    # 热力图叠在 free/obstacle 底图上。
    image = base_image(free_mask)
    # 只在有非零分数的位置附近叠色，避免整张图染色。
    mask = values > 0.01
    image[mask] = cv2.addWeighted(image, 0.35, heat, 0.65, 0.0)[mask]
    # 热力图仍然输出原尺寸，后续如需要可再统一放大。
    cv2.imwrite(str(output_path), image)


def write_node_semantics_outputs(payload: dict[str, Any], free_mask: np.ndarray, output_dir: Path) -> dict[str, str]:
    # 输出目录由 build_node_semantics.py 传入，通常是 diagnostics/node_semantics。
    output_dir.mkdir(parents=True, exist_ok=True)
    # records 是所有节点明细，绘图和 json 共用同一份数据。
    records = list(payload["nodes"])
    # json 是最重要的可复核结果，图只是辅助定位。
    json_path = output_dir / "node_semantics.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # 01 图表达空间归属：edge / junction / unknown / mixed。
    draw_space_label_map(free_mask, records, output_dir / "01_node_space_label_map.png")
    # 02 图表达覆盖角色：cover_core / connector / residual 等。
    draw_role_map(free_mask, records, output_dir / "02_node_role_map.png")
    # 03 图表达 coverage_obligation，即覆盖责任强弱。
    draw_value_heatmap(free_mask, records, "coverage_obligation", output_dir / "03_coverage_obligation_heatmap.png")
    # 04 图表达 connectivity_value，即作为过渡点的价值强弱。
    draw_value_heatmap(free_mask, records, "connectivity_value", output_dir / "04_connectivity_value_heatmap.png")
    # 返回路径字典，供脚本汇总或日志输出使用。
    return {
        "node_semantics": str(json_path),
        "node_space_label_map": str(output_dir / "01_node_space_label_map.png"),
        "node_role_map": str(output_dir / "02_node_role_map.png"),
        "coverage_obligation_heatmap": str(output_dir / "03_coverage_obligation_heatmap.png"),
        "connectivity_value_heatmap": str(output_dir / "04_connectivity_value_heatmap.png"),
    }
