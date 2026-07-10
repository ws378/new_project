# 路口内连接路径点与 FinalCoveragePath 方案

## 1. 文档定位

本文档描述 `build_final_coverage_path(...)` 这一层的正式职责、正式输入输出、route 展开方式、`A/B/C/D` 取点规则、三类连接构造、离散化、support width 和校验链。

本文档的约束是：

1. 语义说明可以更细
2. 普通连接的几何与真值规则必须贴当前已对齐方案
3. 路由结果 contract 若与旧代码不一致，以本文档作为本轮实现收口目标

## 2. 当前主线定位

当前正式主线已经稳定到：

1. `coverage_lane_info`
2. `sweeps`
3. `sweep_graph_info`
4. `sweep_cadence_info`
5. `final_coverage_path_info`

当前这一层只做：

- 沿 cadence route 逐段展开 sweep 段
- 对需要的 segment 构造 `junction_connection`
- 把 sweep 段和连接段拼成 route 级正式连续子链集

当前这一层不做：

- 不回头修改 cadence
- 不回头修改 sweep 铺设
- 不重建 sweep graph
- 不改写 node / edge 正式几何

## 3. 当前真实输入

当前 `build_final_coverage_path(...)` 的正式输入是：

1. `graph_info`
2. `geometry_result`
3. `coverage_lane_info`
4. `sweeps`
5. `sweep_graph_info`
6. `sweep_cadence_info`
7. `config`

### 3.1 各输入的用途

- `graph_info`
  - 提供正式 `edges / nodes`
- `geometry_result`
  - 提供：
    - `free_mask`
    - `resolution_m_per_px`
- `coverage_lane_info`
  - 提供 lane 级局部间距统计
- `sweeps`
  - 提供：
    - `sweep_id`
    - `source_edge_id`
    - `coverage_lane_id`
    - `path_rc`
- `sweep_graph_info`
  - 提供 transition 真值：
    - `transition_id`
    - `from_end_type`
    - `to_end_type`
    - `via_node_id`
- `sweep_cadence_info`
  - 提供 route 骨架真值：
    - `sweep_sequence`
    - `segments`
    - `start_end_type`
    - `end_end_type`
- `config`
  - 当前至少会读取：
    - `robot_width_m`
    - `coverage_width_m`
    - `resolution_m_per_px`

### 3.2 当前硬要求

- `robot_width_m` 当前必须显式为正
- 若 `robot_width_m <= 0`，函数直接失败

## 4. 当前真实输出

当前 `FinalCoveragePathInfo` 结构至少包含：

- `routes`
- `ordered_items`
- `junction_connections`
- `summary`

### 4.1 `routes`

每条 route 当前至少包含：

- `route_id`
- `ordered_items`
- `sweep_segments`
- `junction_connections`
- `path_subchains_rc`
- `path_length_px`
- `path_length_m`
- `coverage_support_info`
- `debug_info`

### 4.2 `ordered_items`

每项当前只可能是两类之一：

1. `sweep_segment`
2. `junction_connection`

### 4.3 `junction_connections`

每条路口连接当前至少包含：

- `connection_id`
- `route_id`
- `from_sweep_id`
- `to_sweep_id`
- `via_node_id`
- `connection_type`
- `point_a_rc`
- `point_b_rc`
- `point_c_rc`
- `point_d_rc`
- `theta_deg`
- `connection_class`
- `is_constructible`
- `failure_reason`
- `rule_geometry_rc`
- `junction_connection_points_rc`
- `path_points_rc`
- `coverage_support_width_m`
- `is_foldback`
- `debug_info`

## 5. 当前唯一真值语义

当前这一层只允许保留下面这套真值链：

### 5.1 连接端点真值

- 普通 `transition`
  - 优先信 `connection_units` 投影出来的 `transition.from_end_type`
  - 优先信 `connection_units` 投影出来的 `transition.to_end_type`
  - 只有旧口径缺 `connection_units` 时，才回退使用 `sweep_graph_info.transitions[*]`

- `foldback`
  - 才允许回退使用 `segment.entry_end_type`
  - 才允许回退使用 `segment.exit_end_type`

### 5.2 几何输入真值

- `A`
- `B`
- `C`
- `D`

### 5.3 输出真值

- `point_a_rc`
- `point_b_rc`
- `point_c_rc`
- `point_d_rc`
- `theta_deg`
- `connection_class`
- `rule_geometry_rc`
- `path_points_rc`

### 5.4 这套真值的正式含义

- `B`
  - 前 sweep 在本次连接上真正使用的退出端点
- `C`
  - 后 sweep 在本次连接上真正使用的进入端点
- `A`
  - `B` 在前 sweep 上的相邻点
- `D`
  - `C` 在后 sweep 上的相邻点

这里最关键的约束是：

- `A/B/C/D` 只从原始 `sweep.path_rc` 和 end type 真值里取
- 不能从 route 展开后的 sweep 方向、连接结果或任何锚点语义里反推

## 6. 当前必须删除的重复语义

以下语义不应再作为正式设计的一部分出现：

- `from_sweep_anchor_rc`
- `to_sweep_anchor_rc`
- `start_anchor_rc`
- `end_anchor_rc`
- 任意“节点入口锚点”
- 任意“先进入节点，再从入口锚点连到出口锚点”的二次语义

当前正式路径只应围绕：

- sweep 真实端点
- `A/B/C/D`
- 单条连接的 `path_points_rc`
- route 级的 `path_subchains_rc`

来表达。

## 7. 顶层主流程

当前主流程是：

1. 建立查找索引
2. 遍历 cadence 的 `routes`
3. 对每条 route 调 `_materialize_route(...)`
4. 按失败连接显式切分 route 子链
5. 全局分配 `connection_id`
6. 汇总扁平 `ordered_items / junction_connections`
7. 统计 summary

### 7.1 顶层详细伪代码

```python
def build_final_coverage_path(
    *,
    graph_info,
    geometry_result,
    coverage_lane_info,
    sweeps,
    sweep_graph_info,
    sweep_cadence_info,
    config=None,
):
    """
    输入:
        graph_info:
            正式 graph, 含 nodes / edges。
        geometry_result:
            第 1 步几何真值, 当前主要消费 free_mask 和分辨率。
        coverage_lane_info:
            lane 级统计真值。
        sweeps:
            全部正式 sweep。
        sweep_graph_info:
            transition 真值来源。
        sweep_cadence_info:
            route 骨架来源。
        config:
            当前 final path 参数。

    输出:
        FinalCoveragePathInfo
    """

    config = dict(config or {})
    robot_width_m = float(config.get("robot_width_m", 0.0))
    if robot_width_m <= 0.0:
        raise ValueError("FinalCoveragePath requires explicit positive robot_width_m")

    # 建立索引, 后续 route 展开与连接求解都直接用这些真值。
    sweep_by_id = {int(item["sweep_id"]): item for item in tuple(sweeps or ())}
    edge_by_id = {int(edge.edge_id): edge for edge in tuple(graph_info.edges)}
    node_by_id = {int(node.node_id): node for node in tuple(graph_info.nodes)}
    lane_by_id = {int(item["coverage_lane_id"]): item for item in tuple(coverage_lane_info or ())}
    connection_units = tuple((sweep_graph_info or {}).get("connection_units", ()))
    if connection_units:
        transition_by_id = {
            int(item["connection_unit_id"]): {
                "transition_id": int(item["connection_unit_id"]),
                "source_candidate_id": int(item["source_candidate_id"]),
                "via_node_id": int(item["source_node_id"]),
                "from_sweep_id": int(item["out_sweep_global_id"]),
                "to_sweep_id": int(item["in_sweep_global_id"]),
                "from_end_type": str(item["out_end_type"]),
                "to_end_type": str(item["in_end_type"]),
                "motion_type": str(item["motion_type"]),
                "mapping_type": str(item["mapping_type"]),
                "selection_level": str(item["selection_level"]),
                "risk_score": float(item["risk_score"]),
                "coverage_gain_score": float(item["coverage_gain_score"]),
                "total_score": float(item["total_score"]),
                "port_rank_gap": int(item.get("port_rank_gap", 0)),
                "endpoint_distance_px": float(item.get("endpoint_distance_px", 0.0)),
            }
            for item in connection_units
        }
    else:
        transition_by_id = {
            int(item["transition_id"]): dict(item)
            for item in tuple((sweep_graph_info or {}).get("transitions", ()))
        }

    path_routes = []
    for route in tuple((sweep_cadence_info or {}).get("routes", ())):
        materialized = _materialize_route(
            route=route,
            graph_info=graph_info,
            geometry_result=geometry_result,
            sweep_by_id=sweep_by_id,
            edge_by_id=edge_by_id,
            node_by_id=node_by_id,
            lane_by_id=lane_by_id,
            transition_by_id=transition_by_id,
            config=config,
        )
        path_routes.append(materialized)

    # connection_id 当前在所有 route 物化完成后统一分配。
    _assign_global_connection_ids(path_routes)

    all_connections = [
        item
        for route in path_routes
        for item in tuple(route.get("junction_connections", ()))
    ]
    route_order_items = [
        item
        for route in path_routes
        for item in tuple(route.get("ordered_items", ()))
    ]

    total_path_length_px = float(sum(float(item.get("path_length_px", 0.0)) for item in path_routes))
    total_path_length_m = float(total_path_length_px * float(geometry_result.resolution_m_per_px))

    return {
        "routes": tuple(path_routes),
        "ordered_items": tuple(route_order_items),
        "junction_connections": tuple(all_connections),
        "summary": {
            "route_count": int(len(path_routes)),
            "junction_connection_count": int(len(all_connections)),
            "foldback_connection_count": int(sum(1 for item in all_connections if bool(item.get("is_foldback", False)))),
            "path_point_count": int(
                sum(
                    len(tuple(subchain))
                    for route in path_routes
                    for subchain in tuple(route.get("path_subchains_rc", ()))
                )
            ),
            "path_length_px": float(total_path_length_px),
            "path_length_m": float(total_path_length_m),
        },
    }
```

## 8. route 是如何物化的

当前 `_materialize_route(...)` 的真实逻辑是：

1. 读取当前 route 的：
   - `sweep_sequence`
   - `segments`
2. 逐条 sweep 展开 `sweep_segment`
3. 对每个相邻 segment，按需要决定是否构造 `junction_connection`
4. 把 sweep 点链和连接点链按 seam 去重方式拼成当前连续子链
5. 若遇到失败连接，则在该处显式断开，后续重新开启下一条连续子链
6. 最后校验各连续子链内部的 ordered item seam

### 8.1 route 物化详细伪代码

```python
def _materialize_route(
    *,
    route,
    graph_info,
    geometry_result,
    sweep_by_id,
    edge_by_id,
    node_by_id,
    lane_by_id,
    transition_by_id,
    config,
):
    """
    输入:
        route:
            cadence route 真值。
        graph_info / geometry_result:
            正式图和几何世界。
        sweep_by_id / edge_by_id / node_by_id / lane_by_id / transition_by_id:
            final path 物化直接使用的查找索引。
        config:
            final path 配置。

    输出:
        FinalCoveragePathRoute
    """

    sweep_sequence = [int(item) for item in route.get("sweep_sequence", ())]
    segments = tuple(route.get("segments", ()))
    route_id = int(route["route_id"])

    if not sweep_sequence:
        return {
            "route_id": int(route_id),
            "ordered_items": tuple(),
            "sweep_segments": tuple(),
            "junction_connections": tuple(),
            "path_subchains_rc": tuple(),
            "path_length_px": 0.0,
            "path_length_m": 0.0,
            "coverage_support_info": {},
            "debug_info": {},
        }

    ordered_items = []
    sweep_segments = []
    junction_connections = []
    path_subchains = []
    current_subchain = []

    for index, sweep_id in enumerate(sweep_sequence):
        sweep = sweep_by_id[int(sweep_id)]
        segment = dict(segments[index]) if index < len(segments) else None

        # 先根据前后 relation truth 决定这一条 sweep 在当前 route 中的展开方向。
        # 注意:
        #   这一步只影响 route 内展示和拼接顺序,
        #   不影响 A/B/C/D 的正式取点真值。
        sweep_path, direction = _resolve_route_sweep_path_from_relation_truth(
            route=route,
            sweep_sequence=sweep_sequence,
            segments=segments,
            index=index,
            sweep=sweep,
            transition_by_id=transition_by_id,
        )

        if sweep_path:
            sweep_item = {
                "item_type": "sweep_segment",
                "route_id": int(route_id),
                "item_index": int(len(ordered_items) + 1),
                "sweep_id": int(sweep_id),
                "direction": str(direction),
                "sweep_points_rc": tuple(sweep_path),
            }
            ordered_items.append(sweep_item)
            sweep_segments.append(sweep_item)

            # 成功 sweep 段优先并入当前连续子链。
            # 若当前没有子链, 就开启一条新的连续子链。
            if not current_subchain:
                current_subchain = _append_path_points(current_subchain, sweep_path)
            elif _sqdist(current_subchain[-1], sweep_path[0]) <= 1e-6:
                current_subchain = _append_path_points(current_subchain, sweep_path)
            else:
                path_subchains.append(tuple(current_subchain))
                current_subchain = _append_path_points([], sweep_path)

        # 没有后续 segment, route 到此结束。
        if segment is None:
            break

        # 当前只有需要节点内连接时, 才会显式生成 junction_connection。
        if bool(segment.get("requires_junction_connection", False)) or str(segment.get("primitive_type")) == "foldback":
            next_sweep_id = int(segment["to_sweep_id"])
            next_sweep = sweep_by_id[next_sweep_id]
            next_path, _ = _resolve_route_sweep_path_from_relation_truth(
                route=route,
                sweep_sequence=sweep_sequence,
                segments=segments,
                index=index + 1,
                sweep=next_sweep,
                transition_by_id=transition_by_id,
            )

            connection = _build_junction_connection_for_segment(
                route_id=route_id,
                segment=segment,
                graph_info=graph_info,
                geometry_result=geometry_result,
                sweep_by_id=sweep_by_id,
                edge_by_id=edge_by_id,
                node_by_id=node_by_id,
                lane_by_id=lane_by_id,
                transition_by_id=transition_by_id,
                from_sweep_path=tuple(sweep_path),
                to_sweep_path=tuple(next_path),
                config=config,
            )
            connection["connection_id"] = -1
            connection["item_index"] = int(len(ordered_items) + 1)
            junction_connections.append(connection)
            ordered_items.append(connection)

            if bool(connection.get("is_constructible", True)):
                current_subchain = _append_path_points(current_subchain, tuple(connection.get("path_points_rc", ())))
            else:
                if current_subchain:
                    path_subchains.append(tuple(current_subchain))
                    current_subchain = []

    if current_subchain:
        path_subchains.append(tuple(current_subchain))

    # route 级 seam 校验只针对同一连续子链内部仍然相邻的可构造 item。
    _validate_ordered_item_seams_by_subchains(
        ordered_items=tuple(ordered_items),
        path_subchains_rc=tuple(tuple(subchain) for subchain in path_subchains),
    )

    path_length_px = float(sum(_polyline_length_px(tuple(subchain)) for subchain in path_subchains))
    return {
        "route_id": int(route_id),
        "ordered_items": tuple(ordered_items),
        "sweep_segments": tuple(sweep_segments),
        "junction_connections": tuple(junction_connections),
        "path_subchains_rc": tuple(tuple(subchain) for subchain in path_subchains),
        "path_length_px": float(path_length_px),
        "path_length_m": float(path_length_px * float(geometry_result.resolution_m_per_px)),
        "coverage_support_info": {
            "junction_connection_count": int(len(junction_connections)),
            "max_support_width_m": float(
                max((float(item.get("coverage_support_width_m", 0.0)) for item in junction_connections), default=0.0)
            ),
        },
        "debug_info": {
            "sweep_segment_count": int(len(sweep_segments)),
            "junction_connection_count": int(len(junction_connections)),
        },
    }
```

## 9. 当前 sweep 方向是如何决定的

当前 `_resolve_route_sweep_path_from_relation_truth(...)` 会根据：

- 前一个 segment 的目标进入端
- 下一个 segment 的源退出端
- route 自身的 `start_end_type / end_end_type`

来决定 sweep 当前应按：

- `src -> dst`
  还是
- `dst -> src`

输出 route 内的 `sweep_points_rc`。

这里必须明确：

- 这一步只服务于 route 展开和 seam 拼接
- 不服务于 `A/B/C/D` 真值判断

## 10. `A/B/C/D` 的正式取点规则

当前 `_build_junction_connection_for_segment(...)` 中，`A/B/C/D` 的正式取点规则是源码硬真值。

### 10.1 当前先定 end type

当前先求：

- `from_end_type = _segment_source_exit_end(...)`
- `to_end_type = _segment_target_entry_end(...)`

其中：

- 普通 `transition`
  - 只从 `transition_by_id` 读取正式 `from_end_type / to_end_type`
- `foldback`
  - 才允许回退使用 `segment.entry_end_type / exit_end_type`

### 10.2 当前再从原始 `sweep.path_rc` 上取点

当前正式取点伪代码是：

```python
def _pick_from_endpoint_pair(path_rc, from_end_type):
    """
    输入:
        path_rc:
            前 sweep 原始 path_rc。
        from_end_type:
            当前连接实际离开的端类型。

    输出:
        (A, B)
            A 是 B 的相邻点。
            B 是真正离开端点。
    """
    if len(path_rc) < 2:
        raise ValueError("source sweep path requires at least 2 points")
    if from_end_type == "src":
        return path_rc[1], path_rc[0]
    if from_end_type == "dst":
        return path_rc[-2], path_rc[-1]
    raise ValueError(f"invalid from_end_type: {from_end_type}")


def _pick_to_endpoint_pair(path_rc, to_end_type):
    """
    输入:
        path_rc:
            后 sweep 原始 path_rc。
        to_end_type:
            当前连接实际进入的端类型。

    输出:
        (C, D)
            C 是真正进入端点。
            D 是 C 的相邻点。
    """
    if len(path_rc) < 2:
        raise ValueError("target sweep path requires at least 2 points")
    if to_end_type == "src":
        return path_rc[0], path_rc[1]
    if to_end_type == "dst":
        return path_rc[-1], path_rc[-2]
    raise ValueError(f"invalid to_end_type: {to_end_type}")
```

### 10.3 关键约束

- `B` 必须是前 sweep 的真实退出端点
- `C` 必须是后 sweep 的真实进入端点
- `A/B/C/D` 不能从 route 展开后的 path 首尾去猜
- `from_sweep_path / to_sweep_path` 当前只用于连接采样步长参考，不是端点真值来源

## 11. 当前节点局部可行域

当前 `_build_node_local_feasible_region(...)` 的真实职责是：

1. 读取 `node.polygon_vertices_rc`
2. 读取 incident edge 的 `inner_path_rc`
3. 用 polygon 和 corridor 先圈一个局部 bbox seed
4. 最终只保留 bbox 内的 `free_mask` 作为普通连接的内部可行性硬约束

### 11.1 当前输出字段

- `node_id`
- `polygon_rc`
- `mask`
- `clearance_dist_px`
- `resolution_m_per_px`
- `r0`
- `c0`
- `r1`
- `c1`
- `center_local_rc`

### 11.2 当前明确保留的约束

当前普通连接内部可行性只硬性依赖：

- 局部 bbox 内的 `free_mask`

当前文档不应再把下面两项写成普通连接的硬限制：

- `polygon` 外不可行
- `corridor` 外不可行

因为当前源码已经把它们收缩成：

- 局部 bbox 的取值辅助

而不是最终的普通连接内部掩码。

## 12. 三类正式连接规则

普通 `transition` 当前由 `_solve_node_local_transition_connection(...)` 处理。

### 12.1 主分类角

当前真实做法是：

- `from_tangent = normalize(B - A)`
- `to_tangent = normalize(D - C)`
- `theta_deg = abs(angle(B - A, D - C))`

也就是：

- 先把有符号角归一到 `[-180°, 180°]`
- 再取绝对值

### 12.2 分类边界

当前正式分类边界是：

1. `theta < 45°`
   - `direct`
2. `45° <= theta <= 120°`
   - `single_bend`
3. `theta > 120°`
   - `smooth_curve`

## 13. 当前普通连接构造逻辑

### 13.1 `direct`

当前调用：

- `_build_direct_connector(point_b, point_c, local_region)`

真实含义：

- 直接尝试 `B -> C`

### 13.2 `single_bend`

当前调用：

- `_build_single_bend_connector_from_tangent_intersection(...)`

真实逻辑：

1. 用 `B` 侧切向和 `C` 侧切向求直线交点
2. 若交点不存在，则失败
3. 若交点存在，先吸附到 local mask
4. 再尝试 polyline：
   - `B -> X -> C`

### 13.3 `smooth_curve`

当前调用：

- `_build_smooth_connector(...)`

真实逻辑：

1. 端点固定为 `B` 和 `C`
2. 切向固定为 `B-A` 与 `D-C`
3. 依次尝试 handle 比例：
   - `0.20`
   - `0.30`
   - `0.40`
4. 对每档比例采样 cubic bezier
5. 全段都在 local region 内则成功

### 13.4 当前不允许自动降级

当前实现是一类一试：

1. 先按 `theta` 判唯一目标类
2. 只尝试这一类
3. 成功则返回
4. 失败则显式标记为不可构造

当前没有：

- `direct -> single_bend -> smooth_curve`
- `single_bend -> direct -> smooth_curve`
- `smooth_curve` 失败后再回退到其它类别

之类的跨类 fallback。

## 14. 当前 `foldback` 逻辑

`foldback` 不走普通三类连接分支，而是：

- `_solve_node_local_foldback_connection(...)`

### 14.1 当前真实逻辑

1. 先 `_select_foldback_pivot(...)`
2. 基于 pivot 构造几组模板 polyline
3. 找到第一条完全可行的 polyline 就返回
4. 若所有模板都失败，则抛异常

### 14.2 当前边界

- `foldback` 是否允许，属于 cadence 层真值
- final path 层只负责把已选中的 `foldback` 物化出来

## 15. 连接求解详细伪代码

```python
def _build_junction_connection_for_segment(
    *,
    route_id,
    segment,
    graph_info,
    geometry_result,
    sweep_by_id,
    edge_by_id,
    node_by_id,
    lane_by_id,
    transition_by_id,
    from_sweep_path,
    to_sweep_path,
    config,
):
    """
    输入:
        segment:
            cadence route 中的单条 segment 真值。
        from_sweep_path / to_sweep_path:
            route 方向下的 sweep 点链。
            当前只用于采样步长参考, 不用于端点真值判定。

    输出:
        FinalCoveragePathConnection
    """

    from_sweep = sweep_by_id[int(segment["from_sweep_id"])]
    to_sweep = sweep_by_id[int(segment["to_sweep_id"])]
    primitive_type = str(segment.get("primitive_type", "transition"))

    # 第一层真值:
    # 先拿正式 end_type 和 via_node_id。
    from_end_type = _segment_source_exit_end(segment, transition_by_id)
    to_end_type = _segment_target_entry_end(segment, transition_by_id)
    via_node_id = _segment_via_node_id(segment, transition_by_id, edge_by_id, from_sweep)
    via_node = node_by_id.get(int(via_node_id))
    if via_node is None:
        raise ValueError("junction connection requires valid via_node_id")

    # 第二层真值:
    # 从原始 sweep.path_rc 上直接取 A/B/C/D。
    point_a, point_b = _pick_from_endpoint_pair(_to_path_tuple(from_sweep.get("path_rc", ())), from_end_type)
    point_c, point_d = _pick_to_endpoint_pair(_to_path_tuple(to_sweep.get("path_rc", ())), to_end_type)

    # 构造节点局部可行域。
    local_region = _build_node_local_feasible_region(
        node=via_node,
        geometry_result=geometry_result,
        edge_by_id=edge_by_id,
        config=config,
    )

    # route 展开后的 sweep path 只给采样步长参考。
    sampling_from_path = tuple(from_sweep_path) if len(from_sweep_path) >= 2 else _to_path_tuple(from_sweep.get("path_rc", ()))
    sampling_to_path = tuple(to_sweep_path) if len(to_sweep_path) >= 2 else _to_path_tuple(to_sweep.get("path_rc", ()))

    # 先按规则类别求几何骨架。
    connection_solution = _solve_node_local_connection(
        point_a=point_a,
        point_b=point_b,
        point_c=point_c,
        point_d=point_d,
        local_region=local_region,
        segment=segment,
    )
    if not bool(connection_solution.get("is_constructible", True)):
        return _make_failed_junction_connection(
            route_id=route_id,
            from_sweep_id=int(from_sweep["sweep_id"]),
            to_sweep_id=int(to_sweep["sweep_id"]),
            via_node_id=int(via_node_id),
            connection_type="foldback" if primitive_type == "foldback" else "transition",
            point_a=point_a,
            point_b=point_b,
            point_c=point_c,
            point_d=point_d,
            theta_deg=float(connection_solution["theta_deg"]),
            connection_class=str(connection_solution["connection_class"]),
            failure_reason=str(connection_solution.get("failure_reason", "connector is not constructible")),
            rule_geometry_rc=tuple(connection_solution.get("rule_geometry_rc", ())),
            is_foldback=bool(primitive_type == "foldback"),
            local_region=local_region,
            from_end_type=str(from_end_type),
            to_end_type=str(to_end_type),
        )

    node_local_path = tuple(connection_solution["node_local_path_rc"])

    # 再按相邻 sweep 的真实点距风格做离散。
    sampling_step_px = _derive_connection_sampling_step_px(
        from_sweep_path=sampling_from_path,
        to_sweep_path=sampling_to_path,
    )
    sampled_path = _sample_connection_path_like_sweep(
        geometric_path=node_local_path,
        sampling_step_px=sampling_step_px,
    )

    # 再补 coverage support width 和合法性校验。
    coverage_support_width_m = _derive_connector_coverage_support_width(
        from_sweep=from_sweep,
        to_sweep=to_sweep,
        lane_by_id=lane_by_id,
        geometry_result=geometry_result,
        local_region=local_region,
        node_local_path_points_rc=node_local_path,
        point_b=point_b,
        point_c=point_c,
        config=config,
    )
    _validate_junction_connection(
        path_points_rc=sampled_path,
        coverage_support_width_m=coverage_support_width_m,
        local_region=local_region,
        segment=segment,
        point_b=point_b,
        point_c=point_c,
    )

    return {
        "item_type": "junction_connection",
        "connection_id": -1,
        "route_id": int(route_id),
        "from_sweep_id": int(from_sweep["sweep_id"]),
        "to_sweep_id": int(to_sweep["sweep_id"]),
        "via_node_id": int(via_node_id),
        "connection_type": "foldback" if primitive_type == "foldback" else "transition",
        "point_a_rc": tuple(map(float, point_a)),
        "point_b_rc": tuple(map(float, point_b)),
        "point_c_rc": tuple(map(float, point_c)),
        "point_d_rc": tuple(map(float, point_d)),
        "theta_deg": float(connection_solution["theta_deg"]),
        "connection_class": str(connection_solution["connection_class"]),
        "is_constructible": True,
        "failure_reason": "",
        "rule_geometry_rc": tuple(connection_solution["rule_geometry_rc"]),
        "junction_connection_points_rc": tuple(sampled_path),
        "path_points_rc": tuple(sampled_path),
        "coverage_support_width_m": float(coverage_support_width_m),
        "is_foldback": bool(primitive_type == "foldback"),
        "debug_info": {
            "from_end_type": str(from_end_type),
            "to_end_type": str(to_end_type),
            "local_bbox": [int(local_region["r0"]), int(local_region["c0"]), int(local_region["r1"]), int(local_region["c1"])],
        },
    }
```

## 16. 当前连接段离散化逻辑

当前连接几何骨架构造成功后，不直接把几何线当最终路径，而是继续做两步：

1. `_derive_connection_sampling_step_px(...)`
2. `_sample_connection_path_like_sweep(...)`

### 16.1 采样步长来源

当前 `_derive_connection_sampling_step_px(...)` 的真实逻辑是：

1. 读取前后 sweep 路径的相邻点距
2. 收集所有正点距
3. 取中位数
4. 四舍五入成采样步长

也就是说，当前“与 sweep 风格一致”的正式含义是：

- 连接段采样步长来自相邻 sweep 真实点距的中位数

### 16.2 采样输出约束

当前 `_sample_connection_path_like_sweep(...)` 会：

1. 均匀重采样
2. 强制首点等于几何路径首点
3. 强制尾点等于几何路径尾点
4. 去掉相邻重复点

这对应当前的三条正式约束：

1. 首尾完整
   - 首点就是 `B`
   - 尾点就是 `C`
2. 整体均匀
   - 采样节拍与相邻 sweep 的真实点距风格一致
3. seam 不重复
   - route 拼接时不会重复插入相邻重合点

## 17. 当前 support width 的真实来源

当前 `_derive_connector_coverage_support_width(...)` 会取下面几类上界的最小值：

1. `robot_width_m`
2. `from_lane.local_width_stats.coverage_width_m`
3. `to_lane.local_width_stats.coverage_width_m`
4. 路径沿线 clearance 上界
5. 路径端点附近 clearance 上界
6. 把 band 放进 local region 后真正还能落下的最大宽度

### 17.1 当前函数输入字段

- `from_sweep`
- `to_sweep`
- `lane_by_id`
- `geometry_result`
- `local_region`
- `node_local_path_points_rc`
- `point_b`
- `point_c`
- `config`

### 17.2 当前函数边界

当前它表达的是：

- “连接段在当前节点局部自由区里，能支撑多宽的覆盖带”

它不是：

- 重新生成 coverage polygon

## 18. 当前连接合法性校验

当前 `_validate_junction_connection(...)` 至少检查：

1. `path_points_rc` 至少 2 点
2. `coverage_support_width_m > 0`
3. 首点等于 `point_b`
4. 尾点等于 `point_c`
5. 采样点全部在 local feasible region 内
6. support band 不离开 local region
7. `foldback` 时，路径不能偏离中心过远

也就是说，当前连接段不是“几何构造成功就算完事”，而是还会做一轮正式物理约束检查。

## 19. 当前失败处理逻辑

当前单条 `junction_connection` 失败时，不会直接丢掉这条关系，而是返回：

- `_make_failed_junction_connection(...)`

### 19.1 失败对象保留的真值

失败对象仍会保留：

- `from_sweep_id`
- `to_sweep_id`
- `via_node_id`
- `point_a_rc`
- `point_b_rc`
- `point_c_rc`
- `point_d_rc`
- `theta_deg`
- `connection_class`
- `failure_reason`
- `rule_geometry_rc`

### 19.2 失败对象的正式标记

- `is_constructible = False`
- `path_points_rc = ()`
- `coverage_support_width_m = 0.0`

### 19.3 route 级行为

当前某条连接失败后：

- route 不会因此整体中断
- 当前连续子链会在失败处显式结束
- 后续 segment 仍会继续被物化，并在后面重新开启新的连续子链

## 20. 当前 seam 逻辑

当前 seam 逻辑分两层：

### 20.1 `_append_path_points(...)`

职责：

- 把点链拼到 route 总点链时做 seam 去重

### 20.2 `_validate_ordered_item_seams(...)`

职责：

- 检查相邻 ordered item 的 seam 是否真的闭环

这意味着当前 route 不是“粗暴拼一下”，而是有明确 seam contract 的。

同时要注意：

- seam contract 不再要求整条 route 单链连续
- 它只要求同一条 `path_subchains_rc` 内部连续
- 失败连接处允许显式断开

## 21. stage 级 final path 校验

当前 `validate_final_coverage_path(...)` 至少检查：

1. `connection_id` 是否重复
2. 可构造连接的首尾点是否真的是 `B/C`
3. support width 是否有效
4. `foldback` 标记和 `connection_type` 是否一致
5. `point_a/b/c/d / connection_class / rule_geometry_rc` 是否完整
6. 失败连接是否给了 `failure_reason`
7. route seam 是否断裂

### 21.1 当前返回的关键摘要字段

- `route_count`
- `junction_connection_count`
- `foldback_connection_count`
- `duplicate_connection_ids`
- `invalid_path_endpoint_count`
- `invalid_support_width_count`
- `invalid_foldback_count`
- `invalid_rule_truth_count`
- `failed_connection_count`
- `route_seam_break_count`
- `invalid_connection_count`
- `is_valid`

## 22. 审图时应按什么顺序看

### 22.1 先看 cadence 真值

- `sweep_sequence`
- `segments`
- `start_end_type`
- `end_end_type`

### 22.2 再看四点输入

- `point_a_rc`
- `point_b_rc`
- `point_c_rc`
- `point_d_rc`

### 22.3 再看分类真值

- `theta_deg`
- `connection_class`
- `rule_geometry_rc`

### 22.4 最后看最终离散结果

- `path_points_rc`
- route `ordered_items`
- route `path_subchains_rc`

## 23. 总结

当前 FinalCoveragePath 的真实主线不是：

- cadence `ordered_items`
  -> 某种抽象 connection unit 结果

而是：

- cadence `sweep_sequence + segments + start_end_type + end_end_type`
  -> `_materialize_route(...)`
  -> `sweep_segment + junction_connection`
  -> route seam 拼接

普通连接当前也不是抽象模板，而是这条明确的源码链：

1. 普通 `transition` 优先从 `sweep_graph_info.connection_units[*]` 投影出的 `transition.from_end_type / to_end_type`，旧口径才回退到 `sweep_graph_info.transitions[*]`，再结合原始 `sweep.path_rc` 直接取 `A/B/C/D`
2. 用 `angle(B-A, D-C)` 做唯一分类
3. 只按这一类求几何骨架
4. 用相邻 sweep 真实点距中位数做离散采样
5. 再做 support width 和 local feasible region 校验
6. route 级结果用 `path_subchains_rc` 显式表达失败连接处的断开

后续若继续细化文档，也必须以这套真实实现为基线，不能再发明另一套锚点语义或 route 物化流程。
