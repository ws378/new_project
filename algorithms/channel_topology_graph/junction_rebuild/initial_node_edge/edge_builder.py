"""初始正式边恢复逻辑。"""

from __future__ import annotations

from collections import deque
from typing import Any

import cv2
import numpy as np

from ...contracts import EdgeInfo, GeometryPreparationResult, NodeInfo
from ...contracts.node_degree import traversal_degree_for_node
from .edge_paths import dedupe_path, densify_line_rc, path_length_px

_RING_OFFSETS: tuple[tuple[int, int], ...] = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
    (1, 0),
    (1, -1),
    (0, -1),
)


def derive_initial_edges(
    geometry_result: GeometryPreparationResult,
    node_map: dict[int, NodeInfo],
    node_runtime: dict[int, dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> tuple[dict[int, EdgeInfo], dict[int, dict[str, Any]]]:
    """从初始节点出发切出第一版边。"""

    # 初始建边阶段只关注“节点区之外”的残余骨架主链。
    if config is None:
        config = {}

    # 先把 skeleton 压成 0/1 mask，并为每个节点画出本地 node zone。
    # 半径区分 junction / dead-end，是为了让节点区尺度更符合节点类型。
    skeleton01 = np.where(geometry_result.skeleton_pruned_mask > 0, 1, 0).astype(np.uint8)
    labels, zone_masks = build_node_zone_labels(
        shape_hw=skeleton01.shape,
        node_map=node_map,
        junction_radius_px=int(config.get("initial_junction_zone_radius_px", 2)),
        dead_end_radius_px=int(config.get("initial_dead_end_zone_radius_px", 1)),
    )
    dilated_zone_masks = {
        int(node_id): cv2.dilate(
            np.where(zone_mask > 0, 255, 0).astype(np.uint8),
            np.ones((3, 3), np.uint8),
            iterations=1,
        )
        for node_id, zone_mask in zone_masks.items()
    }
    # labels 用于快速查“某像素属于哪个节点区”，zone_masks 则保留逐节点掩码。
    # 两者分别服务于 component 触达判断和 contact 像素提取。

    # 节点区从骨架里扣掉后，剩余的连通分量才有资格成为正式边主体。
    residual01 = skeleton01.copy()
    residual01[labels > 0] = 0

    num_labels, component_labels = cv2.connectedComponents(
        np.where(residual01 > 0, 255, 0).astype(np.uint8),
        connectivity=8,
    )
    # 连通域标签给出的就是“去掉节点区后的残余骨架分段”。
    # 后续每个分段都独立判定是否能解释成边。

    edge_map: dict[int, EdgeInfo] = {}
    edge_runtime: dict[int, dict[str, Any]] = {}
    next_edge_id = 1
    component_pixels_by_id: dict[int, list[tuple[int, int]]] = {}
    component_rows, component_cols = np.where(component_labels > 0)
    for row, col in zip(component_rows.tolist(), component_cols.tolist()):
        component_pixels_by_id.setdefault(int(component_labels[row, col]), []).append((int(row), int(col)))
    # 下面逐个 residual component 做“能否成边”的判定与落盘。
    for comp_id in range(1, int(num_labels)):
        # 每个残余连通分量单独尝试解释成一条边。
        # 这里的 comp_id 只是 residual 上的局部标签，不会直接暴露成 edge_id。
        pixels_rc = component_pixels_by_id.get(int(comp_id), [])
        if not pixels_rc:
            continue
        # 空分量理论上不应出现，这里仍保守跳过。
        # 这样异常标签不会影响后续编号与 incident 关系。

        adjacent_node_ids = adjacent_node_ids_for_component_pixels(pixels_rc, labels)
        if len(adjacent_node_ids) != 2:
            # 这一版只把“明确连接两个节点”的残余分量收成正式边。
            # 其它情况保留在调试信息里，不在此处强行解释成主线边。
            continue
        # 只有恰好碰到两个节点区的分量，才满足“边连接两个节点”的基本定义。

        src_node_id, dst_node_id = adjacent_node_ids
        # contact 像素描述的是残余分量与两端节点区真正接触的位置。
        src_contacts = contact_pixels(pixels_rc, dilated_zone_masks[src_node_id])
        dst_contacts = contact_pixels(pixels_rc, dilated_zone_masks[dst_node_id])
        # 某侧没有 contact 时，说明这个分量无法稳定挂到对应节点。
        if not src_contacts or not dst_contacts:
            # 这种情况下即使 component 碰到了两个节点区，也不能证明存在可靠主干桥接。
            continue

        # 主体路径从 src/dst 接触像素之间恢复；两端 connector 再补回节点中心。
        # 这样最终 edge.path_rc 覆盖的是“节点中心到节点中心”的完整路径。
        core_path, src_contact_rc, dst_contact_rc = multi_source_shortest_path_pixels(
            pixels_rc,
            src_contacts,
            dst_contacts,
        )
        if not core_path:
            # shortest path 恢复失败时，不构造不可信边。
            continue

        src_node = node_map[src_node_id]
        dst_node = node_map[dst_node_id]
        # connector 只负责补上 node zone 内部缺失的短路径。
        src_connector = densify_line_rc(src_node.point_rc, src_contact_rc)
        dst_connector = densify_line_rc(dst_contact_rc, dst_node.point_rc)
        path_rc = dedupe_path(src_connector[:-1] + core_path + dst_connector[1:])
        length_px = path_length_px(path_rc)
        # 初始边先落成完整 path、outer core path 和最小调试信息。
        # 其中 outer_path_rc 只保留节点区之外的核心段，供后续重建参考。
        # 这里不急着判 edge_type，后续几何重建阶段再细化。
        # debug_info / edge_runtime 都保留原始 component 关联，方便排障回溯。
        # 这让基线比对时可以回溯到具体 residual 分量。
        edge_map[next_edge_id] = EdgeInfo(
            edge_id=next_edge_id,
            src_node_id=src_node_id,
            dst_node_id=dst_node_id,
            inner_path_rc=(),
            outer_path_rc=tuple((float(r), float(c)) for r, c in core_path),
            path_rc=tuple((float(r), float(c)) for r, c in path_rc),
            length_px=float(length_px),
            length_m=float(length_px * geometry_result.resolution_m_per_px),
            edge_type=None,
            debug_info={
                "initial_component_pixel_count": len(pixels_rc),
            },
            validation_info=None,
        )
        edge_runtime[next_edge_id] = {
            "active": True,
            "inactive_reason": None,
            "component_pixels_rc": tuple(pixels_rc),
            "adjacent_node_ids": tuple(adjacent_node_ids),
            "src_contact_rc": tuple(src_contact_rc),
            "dst_contact_rc": tuple(dst_contact_rc),
            "core_path_rc": tuple(core_path),
            "zone_component_id": int(comp_id),
        }
        next_edge_id += 1
        # edge_id 只在真正成功落边后递增，避免留下空洞编号。
        # 因而 edge_id 和 component label 没有直接对应关系。
        # 这也避免了无效分量把编号空间冲散。
        # 成功落边的 component 会在 runtime 中保留原始 comp_id 关联。

    # 建边结束后统一回填每个节点的 incident edge 集合。
    # 这样后续 node rebuild 可以直接复用初始 incident 关系。
    # derive_initial_edges 到这里结束，不额外做几何截断或边类型判定。
    # 因而它的职责边界非常明确：只生成第一版可用边。
    # 任何更细的几何修补都留给后续 junction rebuild 阶段。
    refresh_incident_edge_ids(node_map=node_map, edge_map=edge_map, edge_runtime=edge_runtime)
    return edge_map, edge_runtime


def build_node_zone_labels(
    shape_hw: tuple[int, int],
    node_map: dict[int, NodeInfo],
    junction_radius_px: int,
    dead_end_radius_px: int,
) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    """为初始节点建立节点区。"""

    # 节点区本质上是节点周围的一个小圆盘，用来把节点本体从残余骨架里扣掉。
    # 同时也为后续 contact 检测提供一个稳定、统一的节点占据定义。
    labels = np.zeros(shape_hw, dtype=np.int32)
    zone_masks: dict[int, np.ndarray] = {}
    for node in node_map.values():
        radius_px = junction_radius_px if node.node_type == "junction" else dead_end_radius_px
        mask = np.zeros(shape_hw, dtype=np.uint8)
        center_rc = (int(round(node.point_rc[0])), int(round(node.point_rc[1])))
        # OpenCV circle 用 `(x, y)`，因此 center 要写成 `(col, row)`。
        # 标签图和单节点 mask 同步生成，方便后续既能快速查标签，也能拿掩码做 contact。
        # 后写入的节点会覆盖先前标签，这是这里允许的简化。
        # 在当前节点密度下，这个简化足够稳定。
        cv2.circle(mask, (center_rc[1], center_rc[0]), int(max(1, radius_px)), 1, -1, cv2.LINE_AA)
        labels[mask > 0] = int(node.node_id)
        zone_masks[int(node.node_id)] = mask
    return labels, zone_masks


def adjacent_node_ids_for_component_pixels(
    component_pixels_rc: list[tuple[int, int]],
    node_zone_labels: np.ndarray,
) -> list[int]:
    """基于 component 像素的 3x3 邻域查找接触到的节点区。"""

    height, width = node_zone_labels.shape
    touched: set[int] = set()
    for row, col in component_pixels_rc:
        for d_row in (-1, 0, 1):
            next_row = row + d_row
            if next_row < 0 or next_row >= height:
                continue
            for d_col in (-1, 0, 1):
                next_col = col + d_col
                if next_col < 0 or next_col >= width:
                    continue
                node_id = int(node_zone_labels[next_row, next_col])
                if node_id != 0:
                    touched.add(node_id)
    return sorted(touched)


def contact_pixels(
    component_pixels_rc: list[tuple[int, int]],
    dilated_zone_mask01: np.ndarray,
) -> list[tuple[int, int]]:
    """找出残余骨架与节点区接触的像素。"""

    # component_pixels_rc 已经来自 np.argwhere(component01 > 0)，过滤后仍保持原 row-major 顺序。
    return [(row, col) for row, col in component_pixels_rc if dilated_zone_mask01[row, col] > 0]


def multi_source_shortest_path_pixels(
    component_pixels_rc: list[tuple[int, int]],
    src_points_rc: list[tuple[int, int]],
    dst_points_rc: list[tuple[int, int]],
) -> tuple[list[tuple[int, int]], tuple[int, int] | None, tuple[int, int] | None]:
    """在 component 像素集合里恢复一条 src-dst 最短路径。"""

    src_set = set(src_points_rc)
    dst_set = set(dst_points_rc)
    if not src_set or not dst_set:
        return [], None, None

    component_set = set(component_pixels_rc)
    queue: deque[tuple[int, int]] = deque()
    parent: dict[tuple[int, int], tuple[int, int] | None] = {}
    for src in src_set:
        if src not in component_set:
            continue
        queue.append(src)
        parent[src] = None

    meet: tuple[int, int] | None = None
    while queue:
        cur = queue.popleft()
        if cur in dst_set:
            meet = cur
            break
        for dr, dc in _RING_OFFSETS:
            nxt = (cur[0] + dr, cur[1] + dc)
            if nxt not in component_set:
                continue
            if nxt in parent:
                continue
            parent[nxt] = cur
            queue.append(nxt)

    if meet is None:
        return [], None, None

    path_rc: list[tuple[int, int]] = []
    cur = meet
    while cur is not None:
        path_rc.append(cur)
        cur = parent[cur]
    path_rc.reverse()
    return path_rc, path_rc[0], path_rc[-1]


def refresh_incident_edge_ids(
    node_map: dict[int, NodeInfo],
    edge_map: dict[int, EdgeInfo],
    edge_runtime: dict[int, dict[str, Any]],
) -> None:
    """刷新节点上的 incident 边集合。"""

    # 先收集所有 active edge 对两端节点的挂接关系。
    incident_map: dict[int, list[int]] = {int(node_id): [] for node_id in node_map}
    for edge_id, edge in edge_map.items():
        if not bool(edge_runtime.get(edge_id, {}).get("active", False)):
            continue
        incident_map[int(edge.src_node_id)].append(int(edge_id))
        incident_map[int(edge.dst_node_id)].append(int(edge_id))
        # 每条 active edge 会同时写入 src/dst 两侧。
        # inactive edge 不参与 degree 统计。

    edge_by_id = {int(edge.edge_id): edge for edge in edge_map.values()}
    for node_id, node in node_map.items():
        # incident id 顺序统一排序，保证后续输出稳定。
        # `incident_edge_ids` 继续记录唯一边 id；`degree` 则升级为可连接 traversal 端口数。
        # 这样 self-loop 节点不会再被错误压平成 degree=1。
        incident_ids = tuple(sorted(set(incident_map.get(int(node_id), []))))
        node.incident_edge_ids = incident_ids
        node.degree = traversal_degree_for_node(node, edge_by_id)


__all__ = (
    "derive_initial_edges",
    "build_node_zone_labels",
    "adjacent_node_ids_for_component",
    "contact_pixels",
    "multi_source_shortest_path",
    "refresh_incident_edge_ids",
)
