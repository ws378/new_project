"""交汇节点几何中的 edge-exit 映射与端点回写。"""

from __future__ import annotations

import math
from typing import Any

from ...contracts import EdgeInfo, NodeInfo
from .. import geometry_core as geomcore


def match_exits_to_incident_edges(
    node: NodeInfo,
    edge_map: dict[int, EdgeInfo],
    edge_runtime: dict[int, dict[str, Any]],
    exits: list[geomcore.ExitTrace],
) -> dict[int, int]:
    """把几何 exits 一一映射到当前 incident edges。"""

    # 先把仍处于 active 状态的 incident edges 抽出来，并估计各自方向角。
    active_edge_items: list[tuple[int, float]] = []
    for edge_id in node.incident_edge_ids:
        if not bool(edge_runtime.get(int(edge_id), {}).get("active", False)):
            continue
        theta_deg = incident_edge_theta_deg(node, edge_map[int(edge_id)])
        active_edge_items.append((int(edge_id), float(theta_deg)))
    # 任一侧为空都无法建立映射，直接返回空结果。
    if not active_edge_items or not exits:
        return {}

    active_edge_items.sort(key=lambda item: float(item[1]))
    exit_items = [(int(index), float(exit_trace.stable_theta_deg)) for index, exit_trace in enumerate(exits)]
    # 从这里开始，两侧数据都统一成“id + theta”的轻量表示。
    if len(active_edge_items) == len(exit_items):
        # 两边数量一致时，按环形顺序做旋转对齐，避免简单最近邻在 0/360 度附近错配。
        # 旋转匹配等价于固定环顺序，只允许整体起点平移。
        # 这正符合交汇几何里“边和出口按环顺序一一对应”的假设。
        # 因而这里不会打乱环顺序，只寻找最佳对齐偏移量。
        best_cost = float("inf")
        best_mapping: dict[int, int] = {}
        for shift in range(len(exit_items)):
            # 每个 shift 都代表一次“出口起点相对边起点的环形偏移”。
            cost = 0.0
            mapping: dict[int, int] = {}
            for edge_item, exit_item in zip(active_edge_items, exit_items[shift:] + exit_items[:shift]):
                # cost 使用最小夹角和，表示这次整体对齐的方向偏差。
                cost += angle_diff_deg(edge_item[1], exit_item[1])
                mapping[int(edge_item[0])] = int(exit_item[0])
            # 保留总代价最小的那次旋转。
            # mapping 内部始终是 edge_id -> exit_index 的简单字典。
            if cost < best_cost:
                best_cost = cost
                best_mapping = mapping
        # 最终输出的 best_mapping 会被直接用于端点回写。
        return best_mapping

    # 数量不一致时退回贪心最近邻。这里宁可少匹配，也不应把一条边错误映射到两个 exit。
    # 这个降级不会强造一一对应，只消费还能稳定对应的出口。
    unused_exit_ids = {int(index) for index, _theta in exit_items}
    mapping: dict[int, int] = {}
    for edge_id, edge_theta_deg in active_edge_items:
        best_exit_id = None
        best_delta = float("inf")
        for exit_index, exit_theta_deg in exit_items:
            if int(exit_index) not in unused_exit_ids:
                continue
            # 只在未消费出口里寻找当前 edge 的最近方向。
            delta = angle_diff_deg(edge_theta_deg, exit_theta_deg)
            if delta < best_delta:
                best_delta = delta
                best_exit_id = int(exit_index)
        if best_exit_id is None:
            # 某些 edge 可能因为出口不足而留空，这里允许这种不完全映射。
            continue
        # 一旦消费某个 exit，就不再允许被其它 edge 复用。
        # 这样可以避免两条 incident edge 被错误压到同一个出口上。
        mapping[int(edge_id)] = int(best_exit_id)
        unused_exit_ids.remove(int(best_exit_id))
        # 贪心策略不会回看已选结果，优先保证实现简单和输出稳定。
        # 它的目标是给数量不一致场景提供一个可解释的最小映射。
    return mapping


def incident_edge_theta_deg(node: NodeInfo, edge: EdgeInfo) -> float:
    """估计边在节点端的稳定方向角。"""

    path_rc = [tuple(map(float, p)) for p in edge.path_rc]
    # 路径太短时无法稳定估角，退回 0 度占位。
    if len(path_rc) < 2:
        return 0.0
    if int(edge.src_node_id) == int(node.node_id):
        # src 端按正向离开路径采样。
        sample_rc = sample_along_path(path_rc, forward=True)
    else:
        # dst 端则反向采样，保持“从当前节点向外”。
        sample_rc = sample_along_path(path_rc, forward=False)
    # 最终方向始终由节点中心指向离开节点的小样本点。
    # 这样得到的 theta 可以直接和 exit 的 stable theta 比较。
    # 包角之后就不会受到 `atan2` 负角输出的影响。
    return float(
        geomcore.wrap_deg(
            math.degrees(math.atan2(float(sample_rc[0] - node.point_rc[0]), float(sample_rc[1] - node.point_rc[1])))
        )
    )


def sample_along_path(
    path_rc: list[tuple[float, float]],
    forward: bool,
    min_distance_px: float = 3.0,
) -> tuple[float, float]:
    """沿路径离开端点一小段，取方向样本点。"""

    # 样本点不取紧贴端点的第一个点，而是至少离开一个最小距离。
    if forward:
        start_rc = path_rc[0]
        iterable = path_rc[1:]
    else:
        start_rc = path_rc[-1]
        iterable = reversed(path_rc[:-1])
    for point_rc in iterable:
        # 一旦离端点足够远，就把该点作为稳定方向样本。
        # 这个阈值可以抑制端点附近轻微折线对方向估计的干扰。
        if math.hypot(float(point_rc[0] - start_rc[0]), float(point_rc[1] - start_rc[1])) >= min_distance_px:
            return point_rc
    # 整条路径都太短时，就退回第二个点或倒数第二个点。
    # 这样即使极短边也能产出方向，不会中断映射流程。
    return path_rc[1] if forward else path_rc[-2]


def write_endpoint_truncation_runtime(
    node: NodeInfo,
    final_node_center_rc: tuple[float, float],
    exits: list[geomcore.ExitTrace],
    edge_mapping: dict[int, int],
    edge_map: dict[int, EdgeInfo],
    edge_runtime: dict[int, dict[str, Any]],
) -> None:
    """把节点端的截断点结果登记到边运行时状态。"""

    # edge_mapping 指明“哪条边对应哪个 exit”，这里把对应截断信息写回 runtime。
    for edge_id, exit_index in edge_mapping.items():
        exit_trace = exits[int(exit_index)]
        edge = edge_map[int(edge_id)]
        oriented_path_rc = orient_edge_path_from_node(node.node_id, edge)
        # 正式回写点仍然锚到现有边路径上的离散点，避免写入悬空浮点端点。
        cut_index = nearest_path_index(oriented_path_rc, exit_trace.cut_point_rc)
        cut_point_rc = tuple(map(float, oriented_path_rc[cut_index]))
        # endpoint_geometry 按 node_id 分槽存储，允许两端各写各的截断信息。
        # 这样 src 端和 dst 端的几何修正可以互不覆盖。
        endpoint_geometry = edge_runtime[int(edge_id)].setdefault("endpoint_geometry", {})
        # 以下字段同时保留“评估 cut point”和“真正回写到边上的离散 cut point”。
        # 这能帮助后续排查“评估点与离散吸附点不一致”的情况。
        # 写入结构也与两端 endpoint_geometry 的其余字段口径保持一致。
        endpoint_geometry[int(node.node_id)] = {
            "node_id": int(node.node_id),
            "truncation_point_rc": (float(cut_point_rc[0]), float(cut_point_rc[1])),
            "cut_index_from_node": int(cut_index),
            "evaluation_cut_point_rc": tuple(map(float, exit_trace.cut_point_rc)),
            "evaluation_theta_deg": float(exit_trace.stable_theta_deg),
            # 这里用 polygon centroid 做正式节点中心，保证和你前面确认过的主线一致。
            # inner connector 始终是“centroid -> cut point”的离散连接线。
            # 该连接线只服务于边重建和调试，不改 exit 自身评估结果。
            # connector 坐标也统一转为 float，和 edge.path_rc 口径一致。
            "inner_connector_path_rc": tuple(
                (float(r), float(c))
                for r, c in geomcore.densify_line_rc_int(
                    (int(round(float(final_node_center_rc[0]))), int(round(float(final_node_center_rc[1])))),
                    (int(round(float(cut_point_rc[0]))), int(round(float(cut_point_rc[1])))),
                )
            ),
        }
        # 回写完成后，该边即可在后续 edge geometry 阶段按该端截断。
        # 这里不直接改 edge.path_rc，本阶段只写 runtime 真值。


def orient_edge_path_from_node(node_id: int, edge: EdgeInfo) -> list[tuple[float, float]]:
    """把边路径统一成“从当前节点向外”的方向。"""

    path_rc = [tuple(map(float, p)) for p in edge.path_rc]
    # src 侧直接沿原方向，dst 侧则反转后再返回。
    # 非 incident edge 被传进来时直接抛错，避免静默写错端点。
    # 调用方因此必须先确保 edge 确实属于该 node。
    if int(edge.src_node_id) == int(node_id):
        return path_rc
    if int(edge.dst_node_id) == int(node_id):
        return list(reversed(path_rc))
    raise ValueError(f"edge {edge.edge_id} is not incident to node {node_id}")


def nearest_path_index(path_rc: list[tuple[float, float]], point_rc: tuple[int, int] | tuple[float, float]) -> int:
    """在路径上找距离目标点最近的位置。"""

    # 空路径时退回 0，由调用方决定如何兜底。
    if not path_rc:
        return 0
    # 这里用平方距离排序即可，不必额外开方。
    # 并列时使用原索引作为次级键，保证结果稳定。
    # 因而返回结果始终是现有离散点索引，而不是插值点。
    # 这个 helper 的角色只是“离散吸附”，不做曲线投影。
    return min(
        range(len(path_rc)),
        key=lambda index: (
            (float(path_rc[index][0]) - float(point_rc[0])) ** 2
            + (float(path_rc[index][1]) - float(point_rc[1])) ** 2,
            index,
        ),
    )


def angle_diff_deg(a_deg: float, b_deg: float) -> float:
    """计算两个方向角的最小夹角。"""

    # 方向差总被包到 [0, 180]，便于直接拿来做匹配代价。
    delta = abs((float(a_deg) - float(b_deg)) % 360.0)
    return min(delta, 360.0 - delta)


__all__ = (
    "match_exits_to_incident_edges",
    "incident_edge_theta_deg",
    "sample_along_path",
    "write_endpoint_truncation_runtime",
    "orient_edge_path_from_node",
    "nearest_path_index",
    "angle_diff_deg",
)
