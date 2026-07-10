from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.path_visualization import draw_coverage_path


# 这个脚本是研究版全局路径生成器，不修改正式 shelf_aware_guarded。
# 输入是一个已有 shelf_aware_ctg_research run，内部必须已经有 baseline 路径。
# 输出是每个 area 的 semantic_global_path_v1 诊断目录和 run 级汇总。
SEMANTIC_PATH_VERSION = "semantic_global_path_v1"

# cover_core / cover_soft 是仍然需要覆盖的节点角色。
# connector 主要承担通行和换区作用，也必须保留路径通过能力。
KEEP_ROLES = {"cover_core", "cover_soft", "connector"}

# residual_soft / noise_candidate 是低覆盖责任节点。
# 这些节点不是直接删除，而是只有在已被重叠覆盖时才跳过。
LOW_VALUE_ROLES = {"residual_soft", "noise_candidate"}

# OpenCV 颜色是 BGR 顺序，不是 RGB。
ROLE_COLORS = {
    "cover_core": (30, 170, 60),
    "cover_soft": (0, 210, 220),
    "connector": (220, 80, 30),
    "residual_soft": (0, 140, 255),
    "noise_candidate": (0, 0, 220),
    "unmatched": (120, 120, 120),
}


def parse_args() -> argparse.Namespace:
    # run-dir 指向已有 output/run_xxx，不在这里新跑 baseline planner。
    parser = argparse.ArgumentParser(description="Build a semantic global path from shelf_aware baseline path and node semantics.")
    # area 可重复传入，用来只测试一个或几个区域。
    parser.add_argument("--run-dir", required=True, help="Existing shelf_aware_ctg_research run directory.")
    # 不传 area 时默认处理 run 目录下所有 area_* 子目录。
    parser.add_argument("--area", action="append", default=None, help="Optional area folder name. Repeatable.")
    # actual-clean-width-m 表示实际机器人清扫宽度，用于判断低价值点是否已被重叠覆盖。
    parser.add_argument("--actual-clean-width-m", type=float, default=0.70, help="Actual cleaning width used for overlap absorption.")
    # max-bridge-gap-factor 控制跳过低价值点后允许产生的最大连接间距。
    parser.add_argument("--max-bridge-gap-factor", type=float, default=2.5, help="Max semantic segment gap as factor of coverage_width_px.")
    # match-radius-factor 控制路径点关联最近 grid node 的最大距离。
    parser.add_argument("--match-radius-factor", type=float, default=0.75, help="Path point to node match radius as factor of coverage_width_px.")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    # 所有诊断文件统一使用 utf-8 json。
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    # ensure_ascii=False 保留中文说明，方便直接阅读。
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def latest_child_run(variant_dir: Path) -> Path:
    # baseline 目录下可能有多次 run，这里取最新一次。
    runs = sorted(path for path in variant_dir.glob("run_*") if path.is_dir())
    # 如果没有 baseline run，这个 area 无法生成语义路径。
    if not runs:
        raise ValueError(f"missing baseline run directory: {variant_dir}")
    return runs[-1]


def select_area_dirs(run_dir: Path, selected: list[str] | None) -> list[Path]:
    # area 目录以 summary.json 作为识别条件，避免误处理其他诊断目录。
    area_dirs = sorted(path for path in run_dir.iterdir() if path.is_dir() and (path / "summary.json").is_file())
    # 如果用户指定 area，只处理这些名字。
    if selected:
        names = set(selected)
        area_dirs = [path for path in area_dirs if path.name in names]
    # 返回值顺序稳定，便于多次测试对比。
    return area_dirs


def point_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    # 路径长度和跳段长度都使用像素欧氏距离。
    return float(math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1])))


def path_length(points: list[tuple[float, float]]) -> float:
    # 路径总长度是连续点之间距离累加。
    return float(sum(point_distance(a, b) for a, b in zip(points, points[1:])))


def load_path_points(path: Path) -> list[dict[str, Any]]:
    # path_pixels.json 中每个点包含 index/x/y。
    payload = load_json(path)
    # 这里保留原始 index，便于追溯到 baseline 路径点。
    return [
        {
            "index": int(item.get("index", idx)),
            "x": float(item["x"]),
            "y": float(item["y"]),
        }
        for idx, item in enumerate(payload, start=1)
    ]


def point_xy(point: dict[str, Any]) -> tuple[float, float]:
    # 统一把 json point 转成 x/y tuple。
    return float(point["x"]), float(point["y"])


def load_baseline_overlay_base(baseline_run: Path) -> np.ndarray:
    # 正确底图必须使用 baseline planner 自己生成的 path_overlay.png。
    # path_pixels.json 的坐标系和这个图一致，不能拿 area/01_prepared_map.png。
    overlay_path = baseline_run / "path_overlay.png"
    # 这张图已经是正式 shelf_aware_guarded 路径可视化采用的底图。
    image = cv2.imread(str(overlay_path), cv2.IMREAD_COLOR)
    # 缺图说明 baseline run 不完整，不能继续画 semantic 路线。
    if image is None:
        raise ValueError(f"missing baseline path overlay: {overlay_path}")
    # 返回副本，避免后续绘制修改 OpenCV 读入缓存对象。
    return image.copy()


def int_path_points(points: list[dict[str, Any]]) -> list[tuple[int, int]]:
    # draw_coverage_path 接收 OpenCV xy 整数点。
    return [(int(round(float(point["x"]))), int(round(float(point["y"])))) for point in points]


def split_semantic_segments(points: list[dict[str, Any]], jumps: list[dict[str, Any]]) -> list[list[tuple[int, int]]]:
    # semantic 路径需要按 jump 断开，否则普通 sweep 段会把远跳画成实线。
    if not points:
        return []
    # jump 的 end_global_index 是新段开始点。
    break_indices = {int(jump["end_global_index"]) for jump in jumps}
    # segments 保存非 jump 的连续子链。
    segments: list[list[tuple[int, int]]] = []
    # current 是当前连续子链。
    current: list[tuple[int, int]] = []
    # 遍历 global path 点，遇到 jump end 就先断开。
    for point in points:
        index = int(point["global_index"])
        # index 在 break_indices 中，说明上一点到当前点是 jump，不属于普通段。
        if index in break_indices and current:
            segments.append(current)
            current = []
        # 当前点加入新的或已有的普通段。
        current.append((int(round(float(point["x"]))), int(round(float(point["y"])))) )
    # 最后一段不要遗漏。
    if current:
        segments.append(current)
    return segments


def semantic_jump_pairs(jumps: list[dict[str, Any]]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    # draw_coverage_path 的 jump_segments 是 ((x0,y0),(x1,y1)) 结构。
    pairs = []
    # 每个 jump 都来自 semantic path 的连续点距离阈值判断。
    for jump in jumps:
        start = tuple(int(round(float(value))) for value in jump["start_xy"])
        end = tuple(int(round(float(value))) for value in jump["end_xy"])
        pairs.append((start, end))
    return pairs

def load_semantic_nodes(area_dir: Path) -> list[dict[str, Any]]:
    # node_semantics.json 是节点角色和质量标签的唯一来源。
    path = area_dir / "diagnostics" / "node_semantics" / "node_semantics.json"
    # 没有 node_semantics 时必须先跑 build_node_semantics.py。
    if not path.is_file():
        raise ValueError(f"missing node semantics: {path}")
    payload = load_json(path)
    # 每个 node 保留中心点、角色、空间归属和两个分数。
    return list(payload.get("nodes", []))


def nearest_semantic_node(point: tuple[float, float], nodes: list[dict[str, Any]], max_distance_px: float) -> tuple[dict[str, Any] | None, float]:
    # 当前数据量不大，直接线性找最近节点，避免引入额外依赖。
    if not nodes:
        return None, float("inf")
    # path point 是原图 x/y，node center_pixel 也是原图 x/y。
    px, py = float(point[0]), float(point[1])
    # min 会返回距离 path point 最近的语义节点。
    best = min(nodes, key=lambda node: math.hypot(px - float(node["center_pixel"][0]), py - float(node["center_pixel"][1])))
    # 计算最近距离，用于判断是否真的匹配上。
    dist = math.hypot(px - float(best["center_pixel"][0]), py - float(best["center_pixel"][1]))
    # 超过匹配半径时视为 unmatched，避免把路径点错误吸到远处节点。
    if dist > float(max_distance_px):
        return None, float(dist)
    return best, float(dist)


def annotate_path_points(path_points: list[dict[str, Any]], nodes: list[dict[str, Any]], match_radius_px: float) -> list[dict[str, Any]]:
    # annotated 是 baseline 路径点加上最近语义节点后的结果。
    annotated = []
    # 每个路径点独立匹配一个 node_role。
    for order, point in enumerate(path_points, start=1):
        node, distance_px = nearest_semantic_node(point_xy(point), nodes, match_radius_px)
        # 没匹配到节点时，用 unmatched 角色保守保留。
        if node is None:
            role = "unmatched"
            node_id = None
            coverage_obligation = None
            connectivity_value = None
            space = {}
            quality = {}
        else:
            role = str(node.get("node_role", "unmatched"))
            node_id = str(node.get("node_id"))
            coverage_obligation = float(node.get("coverage_obligation", 0.0))
            connectivity_value = float(node.get("connectivity_value", 0.0))
            space = dict(node.get("space", {}))
            quality = dict(node.get("quality_features", {}))
        # 写入完整追踪信息，便于解释每个路径点为什么被保留或跳过。
        annotated.append(
            {
                "semantic_index": int(order),
                "baseline_index": int(point["index"]),
                "x": float(point["x"]),
                "y": float(point["y"]),
                "node_id": node_id,
                "node_match_distance_px": float(distance_px),
                "node_role": role,
                "coverage_obligation": coverage_obligation,
                "connectivity_value": connectivity_value,
                "primary_space_type": space.get("primary_space_type"),
                "primary_territory_label": space.get("primary_territory_label"),
                "primary_junction_id": space.get("primary_junction_id"),
                "quality_features": quality,
            }
        )
    return annotated


def min_distance_to_kept_path(point: dict[str, Any], kept_points: list[dict[str, Any]]) -> float:
    # 如果当前还没有保留点，不能认为它被已有路径覆盖。
    if not kept_points:
        return float("inf")
    # 这里用到已保留 path point 的中心距离，作为重叠覆盖近似。
    xy = point_xy(point)
    return float(min(point_distance(xy, point_xy(item)) for item in kept_points))


def choose_semantic_path(annotated: list[dict[str, Any]], *, overlap_radius_px: float, max_bridge_gap_px: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # selected_flags 表示每个 baseline 路径点是否进入语义全局路径。
    selected_flags = [False] * len(annotated)
    # decisions 记录每个点的保留/跳过原因。
    decisions: list[dict[str, Any]] = []
    # kept_points 是已经进入路径的点，用于判断后续低价值点是否被覆盖。
    kept_points: list[dict[str, Any]] = []
    # 第一遍按 role 和 overlap 做语义选择。
    for idx, point in enumerate(annotated):
        role = str(point["node_role"])
        # 起点和终点必须保留，避免路径首尾漂移。
        must_keep_endpoint = idx == 0 or idx == len(annotated) - 1
        # cover_core / cover_soft / connector / unmatched 先保守保留。
        must_keep_by_role = role in KEEP_ROLES or role == "unmatched"
        # low value 点只有在足够靠近已保留路径时才跳过。
        low_value = role in LOW_VALUE_ROLES
        # 计算当前点到已保留路径的距离，用于 overlap 判定。
        distance_to_kept = min_distance_to_kept_path(point, kept_points)
        # 默认先保留，后面根据低价值和重叠条件改成跳过。
        keep = True
        reason = "keep_by_role"
        # 起终点优先级最高。
        if must_keep_endpoint:
            keep = True
            reason = "keep_endpoint"
        # 主覆盖和连接点保持 baseline 顺序。
        elif must_keep_by_role:
            keep = True
            reason = "keep_required_or_connector"
        # 低价值点如果在实际清扫半径内，认为已被前面路径重叠覆盖。
        elif low_value and distance_to_kept <= overlap_radius_px:
            keep = False
            reason = "skip_low_value_by_overlap"
        # 低价值点如果离已保留路径很远，仍保留，避免产生覆盖空洞。
        elif low_value:
            keep = True
            reason = "keep_low_value_far_from_path"
        # 未知角色保守保留。
        else:
            keep = True
            reason = "keep_unknown_role"
        # 根据本轮决策更新路径集合。
        selected_flags[idx] = bool(keep)
        if keep:
            kept_points.append(point)
        # 每个点都记录决策，方便后续复盘。
        decisions.append(
            {
                "semantic_index": int(point["semantic_index"]),
                "baseline_index": int(point["baseline_index"]),
                "node_role": role,
                "decision": reason,
                "selected": bool(keep),
                "distance_to_kept_path_px": float(distance_to_kept) if math.isfinite(distance_to_kept) else None,
                "x": float(point["x"]),
                "y": float(point["y"]),
            }
        )
    # 第二遍保护路径连续性：如果跳过后相邻保留点距离过大，就恢复中间低价值点。
    selected_indices = [idx for idx, flag in enumerate(selected_flags) if flag]
    # restored 记录因为连续性被恢复的点。
    restored: set[int] = set()
    # 检查每一对相邻保留点。
    for left, right in zip(selected_indices, selected_indices[1:]):
        # 两个保留点在原 baseline 中本来就相邻，则不需要恢复。
        if right <= left + 1:
            continue
        # 如果直连距离不大，允许跳过中间低价值点。
        gap = point_distance(point_xy(annotated[left]), point_xy(annotated[right]))
        if gap <= max_bridge_gap_px:
            continue
        # 如果直连距离过大，恢复中间所有被跳过点，保持路径可解释连续。
        for idx in range(left + 1, right):
            if not selected_flags[idx]:
                selected_flags[idx] = True
                restored.add(idx)
    # 把 restored 信息写回 decisions。
    for idx in restored:
        decisions[idx]["selected"] = True
        decisions[idx]["decision"] = "restore_bridge_continuity"
    # semantic_path 是最终全局路径，顺序仍沿用 baseline。
    semantic_path = [dict(point) for idx, point in enumerate(annotated) if selected_flags[idx]]
    # 给最终路径重新编号，避免 baseline index 跳号影响下游读取。
    for order, point in enumerate(semantic_path, start=1):
        point["global_index"] = int(order)
    return semantic_path, decisions


def compute_jump_segments(points: list[dict[str, Any]], threshold_px: float) -> list[dict[str, Any]]:
    # jump_segments 用于评价语义路径是否产生新的远跳。
    jumps = []
    # 连续点距离超过阈值就记作 jump。
    for idx, (prev, curr) in enumerate(zip(points, points[1:]), start=2):
        length_px = point_distance(point_xy(prev), point_xy(curr))
        if length_px < threshold_px:
            continue
        # 保存 jump 的起止点和长度。
        jumps.append(
            {
                "start_global_index": int(idx - 1),
                "end_global_index": int(idx),
                "start_baseline_index": int(prev["baseline_index"]),
                "end_baseline_index": int(curr["baseline_index"]),
                "start_xy": [float(prev["x"]), float(prev["y"])],
                "end_xy": [float(curr["x"]), float(curr["y"])],
                "length_px": float(length_px),
            }
        )
    return jumps



def draw_legend(image: np.ndarray, items: list[tuple[str, tuple[int, int, int]]]) -> None:
    # 图例放在左上角，全部使用 ASCII，避免中文乱码。
    x0, y0 = 10, 22
    # 每个图例项一行，和其它诊断图保持简单一致。
    for idx, (label, color) in enumerate(items):
        y = y0 + idx * 18
        cv2.circle(image, (x0, y - 4), 5, color, -1)
        cv2.putText(image, label, (x0 + 14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (20, 20, 20), 1, cv2.LINE_AA)

def draw_path_overlay(base: np.ndarray, semantic: list[dict[str, Any]], jumps: list[dict[str, Any]], output_path: Path) -> None:
    # 01 图直接复用 baseline path_overlay.png 作为底图。
    image = base.copy()
    # semantic path 使用正式 draw_coverage_path 绘制，避免坐标系和跳段画法漂移。
    draw_coverage_path(
        image,
        int_path_points(semantic),
        split_semantic_segments(semantic, jumps),
        semantic_jump_pairs(jumps),
        sweep_color=(0, 170, 0),
        jump_color=(0, 0, 255),
        sweep_thickness=2,
        jump_thickness=2,
        label_every=10,
    )
    # 输出尺寸应与 baseline path_overlay.png 一致。
    cv2.imwrite(str(output_path), image)


def draw_path_by_role(base: np.ndarray, semantic: list[dict[str, Any]], output_path: Path) -> None:
    # 02 图仍使用 baseline overlay 底图，但路径按 node_role 上色。
    image = base.copy()
    # 相邻 semantic 点之间按后一节点的 role 着色。
    for prev, curr in zip(semantic, semantic[1:]):
        role = str(curr.get("node_role", "unmatched"))
        color = ROLE_COLORS.get(role, ROLE_COLORS["unmatched"])
        p0 = (int(round(float(prev["x"]))), int(round(float(prev["y"]))))
        p1 = (int(round(float(curr["x"]))), int(round(float(curr["y"]))))
        cv2.line(image, p0, p1, color, 2, cv2.LINE_AA)
    # 保留稀疏点，帮助观察路径采样顺序。
    for idx, point in enumerate(semantic):
        if idx % 25 == 0:
            cv2.circle(image, (int(round(point["x"])), int(round(point["y"]))), 2, (0, 0, 0), -1)
    # 图例只用 ASCII，避免中文乱码。
    draw_legend(image, [(role, color) for role, color in ROLE_COLORS.items()])
    cv2.imwrite(str(output_path), image)


def draw_skipped_points(base: np.ndarray, semantic: list[dict[str, Any]], decisions: list[dict[str, Any]], output_path: Path) -> None:
    # 03 图在同一 baseline overlay 上标出被跳过和恢复的点。
    image = base.copy()
    # 先画 semantic path 的灰色中心线作为上下文。
    for prev, curr in zip(semantic, semantic[1:]):
        p0 = (int(round(float(prev["x"]))), int(round(float(prev["y"]))))
        p1 = (int(round(float(curr["x"]))), int(round(float(curr["y"]))))
        cv2.line(image, p0, p1, (80, 80, 80), 1, cv2.LINE_AA)
    # skip 用红点，restore 用黄点。
    for item in decisions:
        point = (int(round(float(item["x"]))), int(round(float(item["y"]))))
        if item["decision"] == "skip_low_value_by_overlap":
            cv2.circle(image, point, 3, (0, 0, 255), -1)
        elif item["decision"] == "restore_bridge_continuity":
            cv2.circle(image, point, 3, (0, 220, 255), -1)
    # 图例说明红黄灰三类元素。
    draw_legend(image, [("skipped", (0, 0, 255)), ("restored", (0, 220, 255)), ("path", (80, 80, 80))])
    cv2.imwrite(str(output_path), image)


def semantic_path_payload(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # global_path.json 只保留路径消费和分析真正需要的字段。
    payload = []
    # 每个点保留 global_index 和 baseline_index，方便回溯。
    for point in points:
        payload.append(
            {
                "index": int(point["global_index"]),
                "baseline_index": int(point["baseline_index"]),
                "x": float(point["x"]),
                "y": float(point["y"]),
                "node_id": point.get("node_id"),
                "node_role": point.get("node_role"),
                "coverage_obligation": point.get("coverage_obligation"),
                "connectivity_value": point.get("connectivity_value"),
                "primary_space_type": point.get("primary_space_type"),
                "primary_territory_label": point.get("primary_territory_label"),
                "primary_junction_id": point.get("primary_junction_id"),
            }
        )
    return payload


def process_area(area_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    # baseline run 提供原始 shelf_aware_guarded 全局路径。
    baseline_run = latest_child_run(area_dir / "shelf_aware_baseline")
    # metadata 里有分辨率、覆盖宽度和简化阈值。
    metadata = load_json(baseline_run / "metadata.json")
    # coverage_width_px 用于匹配半径和 bridge gap 阈值。
    coverage_width_px = int(metadata.get("coverage_width_px") or 1)
    # resolution 用于把像素路径长度换算成米。
    resolution = float(metadata["map_resolution"])
    # actual_clean_width_m 的一半是重叠覆盖半径。
    overlap_radius_px = float(args.actual_clean_width_m) * 0.5 / resolution
    # 路径点到节点的匹配半径，不匹配时保守视作 unmatched。
    match_radius_px = max(1.0, float(coverage_width_px) * float(args.match_radius_factor))
    # 跳过低价值点后允许的最大连接间距。
    max_bridge_gap_px = max(1.0, float(coverage_width_px) * float(args.max_bridge_gap_factor))
    # jump 阈值沿用 baseline postprocess 里的 split_jump_dist_factor 语义。
    jump_threshold_px = float(coverage_width_px) * float(metadata.get("strategy", {}).get("postprocess", {}).get("split_jump_dist_factor", 10.0))
    # 读取 baseline 路径和语义节点。
    baseline_path = load_path_points(baseline_run / "path_pixels.json")
    semantic_nodes = load_semantic_nodes(area_dir)
    # 每个路径点都绑定最近 node_role。
    annotated = annotate_path_points(baseline_path, semantic_nodes, match_radius_px)
    # 根据语义和 overlap 选择最终全局路径。
    semantic_path, decisions = choose_semantic_path(
        annotated,
        overlap_radius_px=overlap_radius_px,
        max_bridge_gap_px=max_bridge_gap_px,
    )
    # 计算 baseline 和 semantic 的跳段。
    baseline_jumps = compute_jump_segments(annotated, jump_threshold_px)
    semantic_jumps = compute_jump_segments(semantic_path, jump_threshold_px)
    # 输出目录每个 area 独立，避免覆盖其他诊断结果。
    output_dir = area_dir / "diagnostics" / SEMANTIC_PATH_VERSION
    output_dir.mkdir(parents=True, exist_ok=True)
    # 写出主要 json 结果。
    write_json(output_dir / "global_path.json", semantic_path_payload(semantic_path))
    write_json(output_dir / "global_path_decisions.json", decisions)
    write_json(output_dir / "jump_segments.json", semantic_jumps)
    # 绘制三张核心可视化，底图复用 baseline planner 的 path_overlay.png。
    base = load_baseline_overlay_base(baseline_run)
    # 01 叠加 semantic path，02 按角色着色，03 标出 skip/restore。
    draw_path_overlay(base, semantic_path, semantic_jumps, output_dir / "01_global_path_overlay.png")
    draw_path_by_role(base, semantic_path, output_dir / "02_path_by_node_role.png")
    draw_skipped_points(base, semantic_path, decisions, output_dir / "03_skipped_low_value_points.png")
    # 统计每类决策和每类角色数量。
    decision_counts = Counter(str(item["decision"]) for item in decisions)
    role_counts = Counter(str(item.get("node_role", "unmatched")) for item in semantic_path)
    # 路径长度换算成米，方便和 baseline 对比。
    baseline_length_m = path_length([point_xy(item) for item in annotated]) * resolution
    semantic_length_m = path_length([point_xy(item) for item in semantic_path]) * resolution
    # area_summary 是该 area 的可读结论。
    area_summary = {
        "area": area_dir.name,
        "success": True,
        "version": SEMANTIC_PATH_VERSION,
        "baseline_run_dir": str(baseline_run),
        "output_dir": str(output_dir),
        "coverage_width_px": int(coverage_width_px),
        "resolution_m_per_px": float(resolution),
        "actual_clean_width_m": float(args.actual_clean_width_m),
        "overlap_radius_px": float(overlap_radius_px),
        "match_radius_px": float(match_radius_px),
        "max_bridge_gap_px": float(max_bridge_gap_px),
        "jump_threshold_px": float(jump_threshold_px),
        "baseline_overlay_shape_hw": [int(base.shape[0]), int(base.shape[1])],
        "baseline_path_point_count": int(len(annotated)),
        "semantic_path_point_count": int(len(semantic_path)),
        "removed_path_point_count": int(len(annotated) - len(semantic_path)),
        "baseline_path_length_m": float(baseline_length_m),
        "semantic_path_length_m": float(semantic_length_m),
        "length_delta_m": float(semantic_length_m - baseline_length_m),
        "baseline_jump_count": int(len(baseline_jumps)),
        "semantic_jump_count": int(len(semantic_jumps)),
        "jump_delta": int(len(semantic_jumps) - len(baseline_jumps)),
        "decision_counts": dict(sorted(decision_counts.items())),
        "semantic_path_role_counts": dict(sorted(role_counts.items())),
        "artifacts": {
            "global_path": str(output_dir / "global_path.json"),
            "decisions": str(output_dir / "global_path_decisions.json"),
            "jump_segments": str(output_dir / "jump_segments.json"),
            "global_path_overlay": str(output_dir / "01_global_path_overlay.png"),
            "path_by_node_role": str(output_dir / "02_path_by_node_role.png"),
            "skipped_low_value_points": str(output_dir / "03_skipped_low_value_points.png"),
        },
    }
    # area_summary 单独落盘，便于只看某个 area。
    write_json(output_dir / "summary.json", area_summary)
    return area_summary


def main() -> None:
    # 解析命令行参数。
    args = parse_args()
    # run_dir 必须是已有研究 run，不在这里自动创建。
    run_dir = Path(args.run_dir).expanduser().resolve()
    # 不存在就直接失败，避免输出到错误位置。
    if not run_dir.is_dir():
        raise ValueError(f"run directory does not exist: {run_dir}")
    # 选择需要处理的 area。
    area_dirs = select_area_dirs(run_dir, args.area)
    # 逐个 area 生成语义全局路径。
    area_summaries = [process_area(area_dir, args) for area_dir in area_dirs]
    # 汇总跨 area 的关键指标。
    aggregate = {
        "baseline_path_point_count": int(sum(item["baseline_path_point_count"] for item in area_summaries)),
        "semantic_path_point_count": int(sum(item["semantic_path_point_count"] for item in area_summaries)),
        "removed_path_point_count": int(sum(item["removed_path_point_count"] for item in area_summaries)),
        "baseline_jump_count": int(sum(item["baseline_jump_count"] for item in area_summaries)),
        "semantic_jump_count": int(sum(item["semantic_jump_count"] for item in area_summaries)),
        "length_delta_m": float(sum(item["length_delta_m"] for item in area_summaries)),
    }
    # run_summary 是本轮测试的总结果。
    run_summary = {
        "run_dir": str(run_dir),
        "version": SEMANTIC_PATH_VERSION,
        "area_count": int(len(area_summaries)),
        "actual_clean_width_m": float(args.actual_clean_width_m),
        "aggregate": aggregate,
        "areas": area_summaries,
    }
    # 汇总写到 run 根目录。
    target = run_dir / "semantic_global_path_summary.json"
    write_json(target, run_summary)
    # 打印路径，方便命令行确认脚本完成。
    print(target)


if __name__ == "__main__":
    main()
