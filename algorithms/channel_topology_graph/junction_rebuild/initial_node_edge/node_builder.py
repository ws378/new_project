"""初始正式节点装配与闭环校验。"""

from __future__ import annotations

from typing import Any

import numpy as np

from ...contracts import EdgeInfo, GeometryPreparationResult, NodeInfo
from .edge_builder import derive_initial_edges
from .edge_paths import densify_line_rc, dedupe_path, path_length_px
from .pure_cycle import find_best_cycle_cut_and_paths
from .node_candidates import (
    derive_initial_dead_end_candidates,
    derive_initial_junction_candidates,
)


def build_pure_cycle_initial_node_edge(
    geometry_result: GeometryPreparationResult,
    config: dict[str, Any] | None = None,
) -> tuple[dict[int, NodeInfo], dict[int, dict[str, Any]], dict[int, EdgeInfo], dict[int, dict[str, Any]]]:
    """为无 junction / 无 dead_end 的纯回环骨架补一个虚拟节点和 self-loop edge。

    这里不再直接把整圈骨架强行排序，而是：

    1. 先在回环上选一个切口；
    2. 切口的 3x3 局部骨架作为 `inner_path` 候选；
    3. 其余残余主分量先做一轮链化 thinning，再追成开口主链；
    4. 用这条开口主链作为 `outer_path` 主体。

    这样更接近常规边“先得到主链，再补两端局部几何”的组织方式，
    也更适合真实图里常见的斜角簇与对角双通路。
    """

    skeleton01 = np.where(geometry_result.skeleton_pruned_mask > 0, 1, 0).astype(np.uint8)
    config = config or {}
    cut_pixel, inner_zone, outer_path = find_best_cycle_cut_and_paths(
        skeleton01,
        parallel_workers=int(config.get("pure_cycle_parallel_workers", 0)),
    )
    if cut_pixel is None or len(outer_path) < 2:
        return {}, {}, {}, {}

    node_point_rc = (float(cut_pixel[0]), float(cut_pixel[1]))
    polygon = (
        (float(cut_pixel[0] - 1), float(cut_pixel[1] - 1)),
        (float(cut_pixel[0] - 1), float(cut_pixel[1] + 1)),
        (float(cut_pixel[0] + 1), float(cut_pixel[1] + 1)),
        (float(cut_pixel[0] + 1), float(cut_pixel[1] - 1)),
    )
    node_map = {
        1: NodeInfo(
            node_id=1,
            point_rc=node_point_rc,
            node_type="junction",
            incident_edge_ids=(1,),
            degree=2,
            is_virtual=True,
            virtual_reason="pure_cycle_cut",
            polygon_vertices_rc=polygon,
            debug_info={"synthetic_reason": "pure_cycle_cut"},
            validation_info=None,
        )
    }
    node_runtime = {
        1: {
            "active": True,
            "merge_target_node_id": None,
            "initial_point_rc": (int(cut_pixel[0]), int(cut_pixel[1])),
            "initial_component_member_points_rc": tuple(tuple(map(int, p)) for p in np.argwhere(skeleton01 > 0)),
            "component_type": "pure_cycle_cut",
        }
    }

    outer_start_rc = tuple(map(float, outer_path[0]))
    outer_end_rc = tuple(map(float, outer_path[-1]))
    src_inner_path = densify_line_rc(node_point_rc, outer_start_rc)
    dst_inner_path = densify_line_rc(node_point_rc, outer_end_rc)
    inner_path = tuple(
        (float(point_rc[0]), float(point_rc[1]))
        for point_rc in dedupe_path(src_inner_path[:-1] + list(reversed(dst_inner_path)))
    )
    outer_path_rc = tuple((float(point_rc[0]), float(point_rc[1])) for point_rc in outer_path)
    path_rc = tuple(
        (float(point_rc[0]), float(point_rc[1]))
        for point_rc in dedupe_path(src_inner_path[:-1] + outer_path + list(reversed(dst_inner_path))[1:])
    )

    edge = EdgeInfo(
        edge_id=1,
        src_node_id=1,
        dst_node_id=1,
        inner_path_rc=inner_path,
        outer_path_rc=outer_path_rc,
        path_rc=path_rc,
        length_px=float(path_length_px([tuple(map(int, point_rc)) for point_rc in path_rc])),
        length_m=float(path_length_px([tuple(map(int, point_rc)) for point_rc in path_rc]) * geometry_result.resolution_m_per_px),
        edge_type="cycle",
        debug_info={
            "initial_component_pixel_count": int(np.count_nonzero(skeleton01)),
            "synthetic_reason": "pure_cycle_cut",
            "cut_inner_zone_rc": [[int(r), int(c)] for r, c in inner_zone],
            "src_inner_path_rc": [[float(r), float(c)] for r, c in src_inner_path],
            "dst_inner_path_rc": [[float(r), float(c)] for r, c in dst_inner_path],
        },
        validation_info=None,
    )
    edge_map = {1: edge}
    edge_runtime = {
        1: {
            "active": True,
            "inactive_reason": None,
            "component_pixels_rc": tuple(tuple(map(int, point_rc)) for point_rc in np.argwhere(skeleton01 > 0)),
            "adjacent_node_ids": (1, 1),
            "src_contact_rc": tuple(map(int, outer_path[0])),
            "dst_contact_rc": tuple(map(int, outer_path[-1])),
            "core_path_rc": tuple(tuple(map(int, point_rc)) for point_rc in outer_path),
            "zone_component_id": 1,
            "synthetic_reason": "pure_cycle_cut",
        }
    }
    return node_map, node_runtime, edge_map, edge_runtime


def build_initial_node_edge(
    geometry_result: GeometryPreparationResult,
    config: dict[str, Any] | None = None,
) -> tuple[dict[int, NodeInfo], dict[int, dict[str, Any]], dict[int, EdgeInfo], dict[int, dict[str, Any]]]:
    """建立 junction_rebuild 第一版正式节点与正式边。"""

    # 先产出初始节点，再基于这些节点去切第一版正式边。
    node_map, node_runtime = derive_initial_nodes(geometry_result)
    if not node_map:
        # 没有任何初始节点时，唯一合理解释通常是 pure cycle，需要走专门的虚拟节点/回环边补建逻辑。
        node_map, node_runtime, edge_map, edge_runtime = build_pure_cycle_initial_node_edge(geometry_result, config=config)
    else:
        edge_map, edge_runtime = derive_initial_edges(
            geometry_result=geometry_result,
            node_map=node_map,
            node_runtime=node_runtime,
            config=config,
        )
    # 初始 node/edge 出来后立即做一轮闭环校验，避免脏数据流入后续阶段。
    # 这样失败会尽早暴露在步骤 2，而不是拖到后续复杂几何阶段。
    # 这也让 build_initial_node_edge 保持一个完整的小闭环。
    # 因而调用方可以把它视为“初始拓扑装配”的单入口。
    validate_initial_node_edge(node_map=node_map, edge_map=edge_map)
    return node_map, node_runtime, edge_map, edge_runtime


def derive_initial_nodes(
    geometry_result: GeometryPreparationResult,
) -> tuple[dict[int, NodeInfo], dict[int, dict[str, Any]]]:
    """从修剪后骨架直接提取一版初始节点。"""

    # 交汇候选和断头路候选分两条规则独立提取，最后统一装配成 NodeInfo。
    initial_junction_candidates = derive_initial_junction_candidates(geometry_result)
    dead_end_items = derive_initial_dead_end_candidates(geometry_result)

    node_map: dict[int, NodeInfo] = {}
    node_runtime: dict[int, dict[str, Any]] = {}
    next_node_id = 1

    for component in initial_junction_candidates:
        # 每个 component 都已经压成“代表点 + 成员点集”的轻量结构。
        # junction 候选先整体装配，保持 node_id 连续。
        # representative 会同时写进 NodeInfo.point_rc 和 runtime.initial_point_rc。
        # 这样静态对象和 runtime 真值从一开始就共享同一代表点。
        # debug_info 则继续保留完整成员像素，供后续排查。
        representative = tuple(map(int, component["representative_point_rc"]))
        node_map[next_node_id] = NodeInfo(
            node_id=next_node_id,
            point_rc=(float(representative[0]), float(representative[1])),
            node_type="junction",
            incident_edge_ids=(),
            degree=0,
            polygon_vertices_rc=None,
            debug_info={
                "initial_component_member_points_rc": component["member_points_rc"],
            },
            validation_info=None,
        )
        node_runtime[next_node_id] = {
            "active": True,
            "merge_target_node_id": None,
            "initial_point_rc": (int(representative[0]), int(representative[1])),
            "initial_component_member_points_rc": tuple(tuple(map(int, p)) for p in component["member_points_rc"]),
            "component_type": "junction",
        }
        # junction 节点先不给 incident，等建边阶段统一回填。
        # runtime 同时保留 component 成员点，方便后续 merge/debug。
        # 到这里 node_id 才算真正占用。
        # 因而 next_node_id 的递增严格跟随成功装配的节点数。
        # 这也意味着候选列表顺序会直接影响 node_id 分配顺序。
        next_node_id += 1

    for component in dead_end_items:
        # 断头路节点的装配口径与 junction 基本一致，只是 node_type 不同。
        # dead_end 紧跟在 junction 之后编号，不单独开辟编号空间。
        # 这样所有初始节点都处在一个统一 id 空间里。
        # 统一编号空间能减少后续 merge/apply 阶段的分支处理。
        # 同时也让调试时更容易按 node_id 回溯整条链路。
        representative = tuple(map(int, component["representative_point_rc"]))
        node_map[next_node_id] = NodeInfo(
            node_id=next_node_id,
            point_rc=(float(representative[0]), float(representative[1])),
            node_type="dead_end",
            incident_edge_ids=(),
            degree=0,
            polygon_vertices_rc=None,
            debug_info={
                "initial_component_member_points_rc": component["member_points_rc"],
            },
            validation_info=None,
        )
        node_runtime[next_node_id] = {
            "active": True,
            "merge_target_node_id": None,
            "initial_point_rc": (int(representative[0]), int(representative[1])),
            "initial_component_member_points_rc": tuple(tuple(map(int, p)) for p in component["member_points_rc"]),
            "component_type": "dead_end",
        }
        # dead_end 也沿用同一 runtime schema，便于统一消费。
        # 两类节点只在 component_type/node_type 上做区分。
        # 这样运行时统计可以只看 schema，不必再分两套结构。
        # 死路节点是否会被后续合并，则由后续阶段单独决定。
        next_node_id += 1

    # 返回结果只表达“初始节点真值”，不在这里做任何合并或几何重建。
    # 因而 node_map/node_runtime 仍然是最原始的初始阶段状态。
    # 后续 merge/rebuild 都会在这个基础上继续演化。
    # 这一步的目标只是稳定、可验证地落下一版节点。
    # 输出顺序和编号也因此应保持稳定，不做额外重排。
    return node_map, node_runtime


def validate_initial_node_edge(
    node_map: dict[int, NodeInfo],
    edge_map: dict[int, EdgeInfo],
) -> None:
    """校验初始节点/边闭环。"""

    # 初始阶段至少要有节点和边，否则后续重建链路没有意义。
    if not node_map:
        raise ValueError("initial node map must not be empty")
    if not edge_map:
        raise ValueError("initial edge map must not be empty")

    # 先把 node_id 收成集合，后续做 O(1) 端点存在性检查。
    node_ids = {int(node_id) for node_id in node_map}
    for edge in edge_map.values():
        # 每条边的两端节点 id 都必须能在 node_map 中找到。
        # 这是最基本的拓扑闭环约束。
        if int(edge.src_node_id) not in node_ids:
            raise ValueError("initial edge src_node_id does not exist")
        if int(edge.dst_node_id) not in node_ids:
            raise ValueError("initial edge dst_node_id does not exist")
        # path 至少要有两个点，才能表达最小边几何。
        # 单点 path 无法区分方向，也无法参与后续截断。
        if len(edge.path_rc) < 2:
            raise ValueError("initial edge path_rc must contain at least 2 points")
    # 所有检查通过后不返回值，表示闭环校验成功。
    # 这样失败一定以异常形式暴露，而不会静默吞掉。
    # 通过这一关后，初始 node/edge 至少满足最基本的拓扑与几何约束。
    # 后续阶段可以在此基础上继续做更强约束检查。
    # 这一层不做修复，只做严格失败。
    # 因而 validate 更像断言，而不是纠错流程。


__all__ = (
    "build_initial_node_edge",
    "derive_initial_nodes",
    "validate_initial_node_edge",
)
