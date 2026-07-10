# coverage lane 与 sweep 生成模块方案

## 1. 文档定位

本文档只描述当前源码中第 4 步 `coverage_planning` 里“coverage lane 与 sweep 生成”这一段正式主线。

这里有三个硬要求：

1. stage 级对象名必须贴当前源码。
2. stage 级主流程必须贴当前真实装配链。
3. 本文只讨论 sweep 的生成，不讨论 sweep 的连接、cadence 和 final path。

也就是说，本文允许把职责、规则、字段和边界解释得更细，但不能把当前实现改写成另一套对象树，也不能把后续 `sweep_transition_candidate_info / sweep_cadence_build_info / final_coverage_path_build_info` 混进 sweep 生成主线。

本文是对下面三份文档中“仍然属于 sweep 生成”的内容做重新收口：

- `11_覆盖lane对象与契约方案.md`
- `12_sweep生成与连接方案.md`
- `13_横向sweep铺设方案.md`

但要特别说明：

- 本文只吸收其中和 sweep 生成直接相关的部分。
- 原 `12_sweep生成与连接方案.md` 里关于 sweep 连接的表述，不属于本文范围。
- 原 `12_sweep生成与连接方案.md` 中把 `sweep_graph_info` 写成“已退出当前正式主线”的表述，不符合当前源码真实状态，因此本文不沿用那种写法。

## 2. 当前入口函数

当前 sweep 生成这段在 stage 级上的正式入口是：

- `algorithms/channel_topology_graph/coverage_planning/coverage_lane_sweep/coverage_lane_sweep_build.py::build_coverage_lane_sweep_info(...)`

当前函数签名语义是：

```python
def build_coverage_lane_sweep_info(
    *,
    graph_info: GraphInfo,
    geometry_result: GeometryPreparationResult,
    config: dict[str, object] | None = None,
) -> CoverageLaneSweepBuildInfo:
    # 真实实现见下方详细伪代码。
    pass
```

### 2.1 输入

- `graph_info`
  - 第 4 步在本子模块里读取的正式图对象。
  - 当前至少直接消费：
    - `graph_info.edges[*].outer_path_rc`
    - `graph_info.edges[*].src_node_id / dst_node_id`
    - `graph_info.nodes[*].polygon_vertices_rc`
- `geometry_result`
  - 第 1 步输出的正式几何结果。
  - 当前至少直接消费：
    - `free_mask`
    - `resolution_m_per_px`
- `config`
  - 当前这段会直接消费：
    - `coverage_width_m`
    - `free_node_min_clearance_m`

### 2.2 输出

- `CoverageLaneSweepBuildInfo`

当前 `CoverageLaneSweepBuildInfo` 的正式字段包括：

- `coverage_lane_info`
- `sweeps`
- `summary`
- `validation_info`

要特别强调：

- 当前 sweep 生成这一段的 stage 级正式产物，只到 `CoverageLaneSweepBuildInfo` 为止。
- `sweep_transition_candidate_info`
- `sweep_graph_build_info`
- `sweep_cadence_build_info`
- `final_coverage_path_build_info`

都不属于本文讨论范围。

## 3. 当前源码真实主装配链

当前 sweep 生成这段在源码里的真实函数链是：

1. `build_coverage_lane_sweep_info(...)`
2. `build_coverage_lanes_and_sweeps(...)`
3. `resolve_lane_sweep_spacing_context(...)`
4. `prepare_coverage_lane_context(...)`
5. `build_all_single_coverage_lanes(...)`
6. `build_single_coverage_lane(...)`
7. `build_lane_sweep_specs(...)`
8. `build_sweep_item_from_layout(...)`
9. `freeze_lane_sweep_items(...)`
10. `build_coverage_lane_sweep_summary(...)`
11. `validate_coverage_lane_generation(...)`

如果把“边级 coverage 真值投影回图对象”也算 sweep 生成之后的紧邻动作，那么当前还会接：

12. `attach_edge_coverage_info(...)`

这里必须区分两层：

1. stage 级正式主链
   - `build_coverage_lane_sweep_info(...)`
2. 子域内部 helper 链
   - `build_coverage_lanes_and_sweeps(...)`
   - `build_single_coverage_lane(...)`
   - `build_lane_sweep_specs(...)`
   - `build_sweep_item_from_layout(...)`

后者当前确实存在，而且是 sweep 生成逻辑的真实承载者；但它们仍然属于子域内部 helper，不应被误写成 `coverage_planning` stage 的并列顶层对象。

## 4. 模块边界

### 4.1 负责

- 基于正式 `graph_info` 和 `geometry_result` 生成每条边的 `coverage_lane_info`
- 为每条 active coverage lane 生成正式 `sweeps`
- 把 `coverage_lane_info + sweeps` 收成 `coverage_lane_sweep_info`
- 为这一段生成最小必要的：
  - `summary`
  - `validation_info`
- 把 lane 级 coverage 真值投影回 `graph_info.edges[*].coverage_info`

### 4.2 不负责

- 不负责 sweep 间连接候选生成
- 不负责 `node_local_connection_hypothesis_info` 的读取和展开
- 不负责 `sweep_transition_candidate_info` 的评分和保留
- 不负责 `sweep_cadence_info` 的构造
- 不负责 `final_coverage_path_info` 的物化
- 不改写 topology 结构，不重建节点和边，不重新判定 topology 合法性

## 5. 这一段正式回答什么问题

当前 sweep 生成模块至少回答四个问题：

1. 每条正式 `edge` 是否能形成一条 active `coverage_lane`
2. 这条 lane 的 territory / effective_region / local_width_stats 是什么
3. 这条 lane 内应该铺多少条 sweeps，以及它们的横向偏移结构是什么
4. 每条正式 `sweep` 的路径、侧别、长度和布局参数是什么

因此，这一段的正式主线对象只有两层：

1. `coverage_lane_info`
2. `sweeps`

而 stage 级收口对象是：

- `CoverageLaneSweepBuildInfo`

## 6. 当前核心输入依赖

当前 sweep 生成至少依赖这些输入：

- `edge.outer_path_rc`
- `edge.src_node_id / dst_node_id`
- `src_node.polygon_vertices_rc`
- `dst_node.polygon_vertices_rc`
- `free_mask`
- `resolution_m_per_px`
- `territory_pixels`
- `allowed_domain_mask`
- `obstacle_distance_px`
- `sampling_step_px`
- `normal_search_px`
- `effective_min_clearance_px`

这里要特别强调两个几何对象的区别：

1. `territory_pixels`
   - 更偏每条 edge 的全局归属区域
2. `effective_region_pixels`
   - 更偏当前 lane 的局部工作域表达

当前 sweep 布局时真正直接控制横向法向搜索可进入哪里的，是：

- `allowed_domain_mask`

而不是简单“只要 free 就行”。

## 7. 当前 coverage lane 正式对象语义

当前单条 `coverage_lane_info` 的关键字段包括：

- `coverage_lane_id`
- `source_edge_id`
- `main_direction`
- `territory_pixels`
- `effective_region_pixels`
- `sweep_ids`
- `sweep_count`
- `local_width_stats`
- `geometry_valid`
- `node_valid`
- `topology_valid`
- `active`
- `excluded_reason`
- `resolution_m_per_px`
- `debug_info`

这些字段里最重要的几条语义是：

- `active == False`
  - 说明这条 edge 没能形成正式可铺设 lane
- `excluded_reason`
  - 当前必须显式解释失败原因，而不是只靠空 sweep 列表侧推
- `sweep_ids`
  - 必须能回指当前轮生成的正式 `sweeps`
- `local_width_stats`
  - 当前承载的是布局层的摘要，不是局部每像素宽度场真值

## 8. 当前 sweep 正式对象语义

当前单条 `SweepInfo` 的关键字段包括：

- `sweep_id`
- `coverage_lane_id`
- `source_edge_id`
- `side_label`
- `side_level`
- `path_rc`
- `anchor_points_rc`
- `offset_profile_px`
- `sampling_step_px`
- `normal_search_px`
- `effective_min_clearance_px`
- `path_count`
- `path_length_px`
- `path_length_m`
- `active`

当前 sweep 对象表达的是：

- 一条已经完成布局求解并正式物化出来的 sweep 路径
- 它保留了 anchor 级偏移 profile，方便后续 debug / render / 下游阶段读取
- 但它不负责表达 sweep 之间如何连接

## 9. 当前真实处理顺序

当前 sweep 生成的真实流程可以收成下面 6 步：

1. 先解析 spacing / clearance / search 半径等几何主导参数
2. 再准备多条 lane 共用的底图、距离场、节点 polygon 与 territory 索引
3. 再逐条 edge 建单 lane 壳对象并做可铺设性判断
4. 对每条可铺设 lane 的主轴做横向布局求解，生成 `sweep_specs`
5. 再把 `sweep_specs` 物化成正式 `SweepInfo`
6. 最后冻结、汇总并校验成 `CoverageLaneSweepBuildInfo`

## 10. stage 级详细伪代码

### 10.1 `build_coverage_lane_sweep_info(...)`

```python
def build_coverage_lane_sweep_info(graph_info, geometry_result, config=None):
    # 这是 sweep 生成这段的 stage 级正式入口。
    # 它只负责把 lane+sweep 子域的正式真值收口成一个 build-info，
    # 不负责连接、不负责 cadence、不负责 final path。

    # 第一步：调用子域 builder，一次性生成 coverage_lane_info 和 sweeps。
    # 这一步是真正的 sweep 生成主体逻辑入口。
    coverage_lane_info, sweeps = build_coverage_lanes_and_sweeps(
        graph_info=graph_info,
        geometry_result=geometry_result,
        config=config,
    )

    # 第二步：把 builder 产出的可变 list 冻结成 stage 正式只读序列。
    # 这样上游 build-info 一旦生成，就不会被后续阶段静默改写。
    coverage_lane_items, sweep_items = freeze_lane_sweep_items(
        coverage_lane_info,
        sweeps,
    )

    # 第三步：生成最小 summary。
    # 这里只统计 lane/sweep 的最核心数量，不在这里展开复杂 debug。
    summary = build_coverage_lane_sweep_summary(
        coverage_lane_items,
        sweep_items,
    )

    # 第四步：生成这一段自己的 validation。
    # 校验重点是 lane->sweep 引用闭环，以及每条 sweep 至少形成一条有效线段。
    validation_info = validate_coverage_lane_generation(
        coverage_lane_items,
        sweep_items,
    )

    # 第五步：封装成 stage 级正式结果对象。
    # 从这里往后，下游如果要看 sweep 生成结果，正式入口就是它。
    return CoverageLaneSweepBuildInfo(
        coverage_lane_info=coverage_lane_items,
        sweeps=sweep_items,
        summary=summary,
        validation_info=validation_info,
    )
```

### 10.2 `build_coverage_lanes_and_sweeps(...)`

```python
def build_coverage_lanes_and_sweeps(graph_info, geometry_result, config=None):
    # 这是 lane+sweep 子域的总 builder。
    # 它把“多 lane 共用准备”和“逐 edge 单 lane 求解”这两层统一串起来。

    # 第一步：把 coverage_width_m、free_node_min_clearance_m 等参数
    # 统一换算成运行像素尺度下的 spacing/search/clearance 口径。
    coverage_width_m, sweep_spacing_px, effective_min_clearance_px, normal_search_px = (
        resolve_lane_sweep_spacing_context(
            geometry_result=geometry_result,
            config=config,
        )
    )

    # 第二步：准备多条 lane 共用的几何上下文。
    # 这里会生成：
    # 1. free_mask
    # 2. obstacle_distance_px
    # 3. constrained_free_mask
    # 4. nodes_by_id
    # 5. territory_pixels_by_edge_id
    free_mask, obstacle_distance_px, constrained_free_mask, nodes_by_id, territory_pixels_by_edge_id = (
        prepare_coverage_lane_context(
            graph_info=graph_info,
            geometry_result=geometry_result,
        )
    )

    # 第三步：逐条 edge 求单 lane 结果，并顺带生成这条 lane 的 sweeps。
    # 这里会维持全局递增的 coverage_lane_id 和 sweep_id。
    coverage_lane_items, sweep_items = build_all_single_coverage_lanes(
        graph_info=graph_info,
        nodes_by_id=nodes_by_id,
        free_mask=free_mask,
        constrained_free_mask=constrained_free_mask,
        territory_pixels_by_edge_id=territory_pixels_by_edge_id,
        obstacle_distance_px=obstacle_distance_px,
        sweep_spacing_px=sweep_spacing_px,
        coverage_width_m=coverage_width_m,
        normal_search_px=normal_search_px,
        effective_min_clearance_px=effective_min_clearance_px,
        resolution_m_per_px=geometry_result.resolution_m_per_px,
    )

    # 第四步：直接返回两份真值。
    # 上层 build-info 再负责冻结、汇总和校验。
    return coverage_lane_items, sweep_items
```

### 10.3 `resolve_lane_sweep_spacing_context(...)`

```python
def resolve_lane_sweep_spacing_context(geometry_result, config):
    # 这一步专门负责把米制参数转成运行尺度像素参数。
    # 它不碰 lane，不碰 edge，只做全局统一换算。

    config = dict(config or {})
    resolution_m_per_px = float(geometry_result.resolution_m_per_px)
    if resolution_m_per_px <= 0.0:
        raise ValueError("resolution_m_per_px must be positive")

    coverage_width_m = float(config.get("coverage_width_m", 0.55))
    if coverage_width_m <= 0.0:
        raise ValueError("coverage_width_m must be positive")

    free_node_min_clearance_m = float(config.get("free_node_min_clearance_m", 0.0))
    if free_node_min_clearance_m < 0.0:
        raise ValueError("free_node_min_clearance_m must be non-negative")

    # sweep_spacing_px：主轴采样节拍，也是横向条数统计时的最大间距口径。
    sweep_spacing_px = max(2, round(coverage_width_m / resolution_m_per_px))

    # required_clearance_m：当前口径不是简单用 free_node_min_clearance_m，
    # 而是至少取 0.5 * coverage_width_m，确保 sweep 本身有最基本通行余度。
    required_clearance_m = max(
        free_node_min_clearance_m,
        0.5 * coverage_width_m,
    )
    effective_min_clearance_px = required_clearance_m / resolution_m_per_px

    # normal_search_px：沿法向找中心合法点时的局部搜索半径。
    normal_search_px = max(1, round(0.5 * coverage_width_m / resolution_m_per_px))

    return (
        coverage_width_m,
        sweep_spacing_px,
        effective_min_clearance_px,
        normal_search_px,
    )
```

## 11. 多 lane 共用上下文伪代码

### 11.1 `prepare_coverage_lane_context(...)`

```python
def prepare_coverage_lane_context(graph_info, geometry_result):
    # 这一步负责生成所有 edge 共享的底图与索引，避免每条 lane 重复做重活。

    # 第一步：把 free_mask 统一标准化成 0/255 二值图，供 OpenCV 和后续 helper 稳定消费。
    free_mask = as_binary_mask(geometry_result.free_mask)

    # 第二步：在自由区上生成 obstacle_distance_px。
    # 后续无论找中心合法点，还是判断横向 offset 是否可用，都要依赖它。
    obstacle_distance_px = cv2.distanceTransform(free_mask, cv2.DIST_L2, 3)

    # 第三步：把全部 node polygon 合成一张全局节点掩膜。
    # 当前它主要服务于 territory/effective_region 这层几何表达。
    node_polygon_mask = build_node_polygon_mask(free_mask.shape, graph_info.nodes)

    # 第四步：先把节点 polygon 区从自由区里扣掉，形成 constrained_free_mask。
    # 当前 territory 和 effective_region 先在这个“去掉节点区”的自由世界里定义。
    constrained_free_mask = where(node_polygon_mask > 0, 0, free_mask)

    # 第五步：把 nodes 建成 id 索引，供单 lane 阶段快速回查 src/dst node。
    nodes_by_id = {node.node_id: node for node in graph_info.nodes}

    # 第六步：以所有 edge.outer_path_rc 为多源种子，在 constrained_free_mask 上统一扩张 territory。
    # 最终每个自由像素只会归属给一条 edge 主轴。
    territory_pixels_by_edge_id = derive_outer_path_territory_pixels(
        graph_info=graph_info,
        constrained_free_mask=constrained_free_mask,
    )

    return (
        free_mask,
        obstacle_distance_px,
        constrained_free_mask,
        nodes_by_id,
        territory_pixels_by_edge_id,
    )
```

### 11.2 `derive_outer_path_territory_pixels(...)`

```python
def derive_outer_path_territory_pixels(graph_info, constrained_free_mask):
    # territory 的真实语义是“每条 outer_path 的全局归属地盘”，
    # 不是最终 sweep 工作域，也不是 sweep 中心线本身。

    # 第一步：初始化多源 BFS 需要的 owner_map / distance_map / queue。
    territory_pixels_by_edge_id, owner_map, distance_map, queue = (
        collect_outer_path_seed_context(
            graph_info,
            constrained_free_mask,
        )
    )

    # 第二步：把每条 outer_path 在约束自由区中的可落 seed 写入队列。
    # 每个 seed 都带着自己的 owner_edge_id 和距离 0。
    seed_outer_path_territory_sources(
        graph_info=graph_info,
        constrained_free_mask=constrained_free_mask,
        owner_map=owner_map,
        distance_map=distance_map,
        queue=queue,
    )

    # 第三步：执行多源 BFS 扩张。
    # 每个自由像素最终会归属给最近的 outer_path owner；
    # 等距冲突不抢占，保证边界稳定。
    expand_outer_path_territory(
        constrained_free_mask=constrained_free_mask,
        owner_map=owner_map,
        distance_map=distance_map,
        queue=queue,
    )

    # 第四步：按 owner_map 回收每条 edge 的 territory 像素集合。
    return collect_territory_pixels_by_owner(
        territory_pixels_by_edge_id=territory_pixels_by_edge_id,
        owner_map=owner_map,
    )
```

## 12. 逐 edge 单 lane 构造伪代码

### 12.1 `build_all_single_coverage_lanes(...)`

```python
def build_all_single_coverage_lanes(...):
    # 这一层负责遍历 graph_info.edges，把每条边都尝试解释成一条 coverage lane。

    coverage_lane_items = []
    sweep_items = []
    next_sweep_id = 1

    for edge in graph_info.edges:
        # coverage_lane_id 在这里按 edge 处理顺序单调递增。
        coverage_lane_id = len(coverage_lane_items) + 1

        # 当前单 lane helper 会同时返回：
        # 1. 单条 lane truth
        # 2. 这条 lane 的 sweep 列表
        # 3. 更新后的 next_sweep_id
        lane_item, edge_sweeps, next_sweep_id = build_single_coverage_lane(
            coverage_lane_id=coverage_lane_id,
            edge=edge,
            nodes_by_id=nodes_by_id,
            free_mask=free_mask,
            constrained_free_mask=constrained_free_mask,
            territory_pixels=territory_pixels_by_edge_id.get(edge.edge_id, ()),
            obstacle_distance_px=obstacle_distance_px,
            sweep_spacing_px=sweep_spacing_px,
            coverage_width_m=coverage_width_m,
            normal_search_px=normal_search_px,
            effective_min_clearance_px=effective_min_clearance_px,
            resolution_m_per_px=resolution_m_per_px,
            next_sweep_id=next_sweep_id,
        )

        # 无论这条 lane 成功还是失败，lane_item 都要进正式输出，保证结果口径稳定。
        coverage_lane_items.append(lane_item)

        # 只有 active lane 才会贡献正式 sweeps。
        sweep_items.extend(edge_sweeps)

    return coverage_lane_items, sweep_items
```

### 12.2 `build_single_coverage_lane(...)`

```python
def build_single_coverage_lane(...):
    # 这是 sweep 生成这段最关键的单 edge helper。
    # 它负责：
    # 1. 建 lane 壳对象
    # 2. 做失败前置判断
    # 3. 生成 allowed_domain / effective_region
    # 4. 解 sweep layout
    # 5. 把 layout 物化成正式 sweeps
    # 6. 回填成功 lane 的正式真值

    outer_path = to_path_tuple(edge.outer_path_rc)
    lane_item = initialize_lane_item(
        coverage_lane_id=coverage_lane_id,
        edge=edge,
        outer_path=outer_path,
        resolution_m_per_px=resolution_m_per_px,
    )

    # 第一步：outer_path 至少得是一条最小主轴。
    # 单点 outer_path 无法恢复切向、法向和横向宽度，直接失败。
    if len(outer_path) < 2:
        lane_item["excluded_reason"] = "outer_path_too_short"
        return lane_item, [], next_sweep_id

    # 第二步：两端正式节点必须存在。
    # 否则连 endpoint polygon 都没法恢复，allowed_domain 也无法构造。
    src_node = nodes_by_id.get(edge.src_node_id)
    dst_node = nodes_by_id.get(edge.dst_node_id)
    if src_node is None or dst_node is None:
        lane_item["excluded_reason"] = "missing_endpoint_node"
        return lane_item, [], next_sweep_id

    # 第三步：当前轮不在这里裁剪 outer_path，trimmed_outer_path 先等于 outer_path。
    # 这个变量保留在这里，是为了以后若要恢复主轴裁剪，入口固定在单 lane 层。
    trimmed_outer_path = tuple(outer_path)

    # 第四步：准备单 lane 的局部 mask 视图。
    # 这里会生成：
    # 1. allowed_domain_mask
    # 2. effective_region_pixels
    # 3. lane_free_mask
    allowed_domain_mask, effective_region_pixels, lane_free_mask = prepare_single_lane_masks(
        constrained_free_mask=constrained_free_mask,
        outer_path=outer_path,
        territory_pixels=territory_pixels,
        free_mask=free_mask,
        src_node=src_node,
        dst_node=dst_node,
    )

    # 第五步：在这条 lane 的主轴上做 sweep 布局求解。
    # 这一层只决定“能铺几条、每条 offset 是多少、每条路径点链是什么”，
    # 还没有生成正式 SweepInfo。
    sweep_specs, layout_debug = build_lane_sweep_specs(
        axis_path=trimmed_outer_path,
        free_mask=free_mask,
        allowed_domain_mask=allowed_domain_mask,
        obstacle_distance_px=obstacle_distance_px,
        sampling_step_px=sweep_spacing_px,
        normal_search_px=normal_search_px,
        effective_min_clearance_px=effective_min_clearance_px,
        robust_quantile=0.6,
    )

    # 第六步：布局失败时，lane 保留失败状态和完整 debug，但不生成 sweeps。
    if sweep_specs is None:
        lane_item["excluded_reason"] = "sweep_layout_invalid"
        lane_item["debug_info"] = build_failed_lane_debug_info(
            territory_pixels=territory_pixels,
            effective_region_pixels=effective_region_pixels,
            sweep_spacing_px=sweep_spacing_px,
            normal_search_px=normal_search_px,
            effective_min_clearance_px=effective_min_clearance_px,
            layout_debug=layout_debug,
        )
        return lane_item, [], next_sweep_id

    # 第七步：把 layout spec 列表物化成正式 sweeps。
    # 从这里开始，条数和 offset 结构都已经确定，不再允许物化阶段反向改布局。
    sweep_items, next_sweep_id, center_sweep_id, positive_count, negative_count = (
        materialize_lane_sweeps(
            coverage_lane_id=coverage_lane_id,
            edge=edge,
            resolution_m_per_px=resolution_m_per_px,
            sweep_spacing_px=sweep_spacing_px,
            normal_search_px=normal_search_px,
            effective_min_clearance_px=effective_min_clearance_px,
            sweep_specs=sweep_specs,
            next_sweep_id=next_sweep_id,
        )
    )

    # 第八步：把成功求解后的真值回填到 lane_item。
    # 从这一刻起，这条 lane 才正式被标记成 active。
    finalize_successful_lane_item(
        lane_item=lane_item,
        territory_pixels=territory_pixels,
        effective_region_pixels=effective_region_pixels,
        sweep_items=sweep_items,
        sweep_spacing_px=sweep_spacing_px,
        coverage_width_m=coverage_width_m,
        normal_search_px=normal_search_px,
        effective_min_clearance_px=effective_min_clearance_px,
        center_sweep_id=center_sweep_id,
        trimmed_outer_path=trimmed_outer_path,
        layout_debug=layout_debug,
        sweep_specs=sweep_specs,
        positive_count=positive_count,
        negative_count=negative_count,
    )

    return lane_item, sweep_items, next_sweep_id
```

### 12.3 `prepare_single_lane_masks(...)`

```python
def prepare_single_lane_masks(...):
    # 这一层负责把单 lane 的工作域几何准备好。

    # 第一步：先只构造当前 edge 两端节点 polygon 的 block mask。
    # 这一步不是处理所有节点，而是只切断当前 lane 两端的口部区域。
    polygon_block_mask = build_endpoint_polygon_block_mask(
        constrained_free_mask.shape,
        src_node,
        dst_node,
    )

    # 第二步：从 constrained_free_mask 里扣掉两端 polygon 区，形成 lane_free_mask。
    # 当前 effective_region 是在这个“扣掉本 lane 两端口部”的自由区里定义的。
    lane_free_mask = where(polygon_block_mask > 0, 0, constrained_free_mask)

    # 第三步：从 outer_path 的可落 seed 出发，在 lane_free_mask 上 flood-fill，
    # 只保留与主轴连通的局部自由区，得到 effective_region_mask。
    effective_region_mask = derive_effective_region_mask(
        outer_path,
        lane_free_mask,
    )
    effective_region_pixels = mask_to_points(effective_region_mask)

    # 第四步：构造 allowed_domain_mask。
    # 当前真实语义不是“所有 free 都能进去”，而是：
    # own_territory ∪ own_endpoint_polygons
    allowed_domain_mask = build_allowed_domain_mask(
        shape=free_mask.shape,
        territory_pixels=territory_pixels,
        src_node=src_node,
        dst_node=dst_node,
    )

    return allowed_domain_mask, effective_region_pixels, lane_free_mask
```

## 13. 横向 sweep 布局伪代码

### 13.1 `build_lane_sweep_specs(...)`

```python
def build_lane_sweep_specs(
    axis_path,
    free_mask,
    allowed_domain_mask,
    obstacle_distance_px,
    sampling_step_px,
    normal_search_px,
    effective_min_clearance_px,
    robust_quantile=0.9,
):
    # 这是 sweep 生成里最核心的布局求解器。
    # 它不直接返回 SweepInfo，而是先返回 lane 级布局规格 sweep_specs。

    # 第一步：沿主轴按 spacing 节拍采样锚点。
    sampled_anchors = sample_path_by_spacing(axis_path, sampling_step_px)

    # 第二步：初始化完整 layout_debug。
    # 即使失败，也要把失败现场完整保留下来。
    layout_debug = initialize_layout_debug(
        sampled_anchors=sampled_anchors,
        sampling_step_px=sampling_step_px,
        normal_search_px=normal_search_px,
        effective_min_clearance_px=effective_min_clearance_px,
        robust_quantile=robust_quantile,
    )

    # 第三步：锚点少于 2 个时，无法恢复稳定切向，也无法构成 sweep 组。
    if len(sampled_anchors) < 2:
        return None, layout_debug

    # 第四步：逐锚点收集横向布局观测。
    # 对每个锚点，当前真实流程是：
    # 1. 估计局部切向
    # 2. 求法向
    # 3. 沿法向找一个满足 clearance 的中心合法点
    # 4. 以这个点为基准，在 allowed_domain_mask 里求主连续 offset 区间
    # 5. 基于区间宽度，先算这个锚点自己的 local_sweep_count
    anchor_infos, local_counts = collect_lane_anchor_layouts(
        sampled_anchors=sampled_anchors,
        free_mask=free_mask,
        allowed_domain_mask=allowed_domain_mask,
        obstacle_distance_px=obstacle_distance_px,
        normal_search_px=normal_search_px,
        effective_min_clearance_px=effective_min_clearance_px,
        sampling_step_px=sampling_step_px,
        layout_debug=layout_debug,
    )
    if anchor_infos is None or local_counts is None:
        return None, layout_debug

    # 第五步：把所有锚点的 local_sweep_count 收成全 lane 的统一目标条数。
    # 当前不是取最大值，也不是取最小值，而是取稳健分位数。
    target_count = solve_robust_target_sweep_count(local_counts, robust_quantile)
    if target_count <= 0:
        layout_debug["failed_reason"] = "target_count_invalid"
        return None, layout_debug

    layout_debug["local_sweep_counts_raw"] = local_counts
    layout_debug["local_sweep_counts_sorted"] = sorted(local_counts)
    layout_debug["target_sweep_count"] = target_count

    # 第六步：对每个锚点，不再沿用自己的 local_count，
    # 而是统一按 target_count 在自己的 offset_run 内重新均匀回填 offsets。
    # 这里的关键语义是：
    # 1. 先承认每个 anchor 的局部带宽并不完全一致；
    # 2. 再用统一 target_count 把整条 lane 的 sweep 条数锁定下来；
    # 3. 最后让每个 anchor 只负责提供“这一条 sweep 在我这里应该落在哪个 offset”。
    # 然后按 sweep 索引 regroup 成多条 sweep profile。
    offset_profiles, point_profiles, anchor_profiles = build_profiles_from_anchor_layouts(
        anchor_infos=anchor_infos,
        target_count=target_count,
        layout_debug=layout_debug,
    )

    # 第七步：根据各条 sweep 的平均 offset，确定哪一条是 center sweep。
    center_index = resolve_center_sweep_index(
        offset_profiles=offset_profiles,
        layout_debug=layout_debug,
    )

    # 第八步：把 regroup 后的 profile 物化成 lane 级 spec 列表。
    # 这一步仍然不是正式 SweepInfo，而是布局规格对象。
    sweep_specs = build_lane_sweep_specs_from_profiles(
        point_profiles=point_profiles,
        anchor_profiles=anchor_profiles,
        offset_profiles=offset_profiles,
        center_index=center_index,
        target_count=target_count,
        anchor_count=len(anchor_infos),
    )

    layout_debug["final_sweep_count_generated"] = len(sweep_specs)

    # 第九步：如果最后没有任何有效 spec，就整体视为布局失败。
    return (sweep_specs or None), layout_debug
```

### 13.2 `collect_lane_anchor_layouts(...)`

```python
def collect_lane_anchor_layouts(...):
    # 这一层负责把“单个 anchor 的局部横向几何真值”全部收出来。

    max_search_px = max(free_mask.shape)
    anchor_infos = []
    local_counts = []

    for idx, anchor_rc in enumerate(sampled_anchors):
        # 第一步：根据主轴采样点序列估计这个 anchor 的局部切向。
        tangent = estimate_local_tangent(sampled_anchors, idx)

        # 第二步：从切向构造法向。
        # 当前 sweep 铺设的横向搜索都在这个法向坐标系下进行。
        normal = normal_from_tangent(tangent, side_sign=1)

        # 第三步：先沿法向在 anchor 附近找一个满足 clearance 的中心合法点。
        # 如果连中心点都找不到，说明这个锚点无法作为稳定布局基准。
        center_point = search_legal_point_along_normal(
            anchor_rc=anchor_rc,
            normal_vec=normal,
            free_mask=free_mask,
            obstacle_distance_px=obstacle_distance_px,
            effective_min_clearance_px=effective_min_clearance_px,
            normal_search_px=normal_search_px,
        )
        if center_point is None:
            layout_debug["failed_anchor_index"] = idx
            layout_debug["failed_reason"] = "center_point_invalid"
            return None, None

        # 第四步：以中心合法点为基准，在 allowed_domain_mask 内求主连续 offset 区间。
        # 这个区间才是本 anchor 真正允许铺 sweep 的横向带宽。
        offset_run = solve_primary_offset_run(
            base_point_rc=center_point,
            normal_vec=normal,
            allowed_domain_mask=allowed_domain_mask,
            free_mask=free_mask,
            obstacle_distance_px=obstacle_distance_px,
            effective_min_clearance_px=effective_min_clearance_px,
            max_search_px=max_search_px,
        )
        if offset_run is None:
            layout_debug["failed_anchor_index"] = idx
            layout_debug["failed_reason"] = "offset_run_invalid"
            return None, None

        offset_min, offset_max = offset_run

        # 第五步：先按本 anchor 自己的区间宽度，估计一个 local_sweep_count。
        # 这一步只是局部观测，不是整条 lane 的最终条数。
        local_count = count_uniform_sweeps_for_interval(
            offset_min_px=offset_min,
            offset_max_px=offset_max,
            max_spacing_px=sampling_step_px,
        )

        # 第六步：把 anchor 级观测收成结构化 anchor_info，供后面统一回填使用。
        anchor_infos.append(
            LaneSweepAnchorInfo(
                anchor_index=idx,
                anchor_rc=anchor_rc,
                center_point_rc=center_point,
                normal_vec=normal,
                offset_min_px=offset_min,
                offset_max_px=offset_max,
                local_sweep_count=local_count,
            )
        )
        local_counts.append(local_count)

        # 第七步：同步把这一轮原始观测写入 layout_debug。
        append_layout_anchor_debug(...)

    return anchor_infos, local_counts
```

### 13.3 `build_profiles_from_anchor_layouts(...)`

```python
def build_profiles_from_anchor_layouts(anchor_infos, target_count, layout_debug):
    # 这一步把“每个 anchor 的局部观测”重新收成“整条 lane 的 sweep profiles”。

    offset_profiles = [[] for _ in range(target_count)]
    point_profiles = [[] for _ in range(target_count)]
    anchor_profiles = [[] for _ in range(target_count)]

    for anchor_info in anchor_infos:
        # 第一步：在当前 anchor 自己的 [offset_min, offset_max] 区间里，
        # 按 target_count 重新均匀回填 offsets。
        offsets = build_uniform_offsets_in_interval(
            offset_min_px=anchor_info.offset_min_px,
            offset_max_px=anchor_info.offset_max_px,
            count=target_count,
        )

        base_point_rc = anchor_info.center_point_rc
        normal_vec = anchor_info.normal_vec

        # 第二步：把每个 offset 投影回图像坐标，得到该 anchor 上每条 sweep 的实际点位。
        for sweep_index, offset_px in enumerate(offsets):
            point_rc = point_at_normal_offset(base_point_rc, normal_vec, offset_px)
            offset_profiles[sweep_index].append(offset_px)
            point_profiles[sweep_index].append(point_rc)
            anchor_profiles[sweep_index].append(anchor_info.anchor_rc)

        # 第三步：把最终 offsets 也写入 debug，便于和原 local_count 观测对照。
        layout_debug["anchors"][anchor_info.anchor_index]["final_offsets_px"] = offsets

    return offset_profiles, point_profiles, anchor_profiles
```

### 13.4 `build_lane_sweep_specs_from_profiles(...)`

```python
def build_lane_sweep_specs_from_profiles(...):
    # 这一层把 regroup 后的 profiles 物化成 lane 级 sweep spec 列表。

    sweep_specs = []
    for sweep_index, path_points in enumerate(point_profiles):
        path_tuple = tuple(path_points)

        # 第一步：太短或退化的 path 不进入正式 spec。
        if len(path_tuple) < 2:
            continue
        path_length_px = path_length_euclidean(path_tuple)
        if path_length_px <= 1.0:
            continue

        # 第二步：根据 center_index 给每条 sweep 标注中心/正侧/负侧语义。
        if sweep_index == center_index:
            side_label = "center"
            side_level = 0
        elif sweep_index > center_index:
            side_label = "positive"
            side_level = sweep_index - center_index
        else:
            side_label = "negative"
            side_level = center_index - sweep_index

        # 第三步：形成正式 spec。
        # 这里已经带上 path、anchor_points、offset_profile、target_count、anchor_count 等布局真值。
        sweep_specs.append(
            LaneSweepSpec(
                path_rc=path_tuple,
                anchor_points_rc=anchor_profiles[sweep_index],
                offset_profile_px=offset_profiles[sweep_index],
                side_label=side_label,
                side_level=side_level,
                path_length_px=path_length_px,
                target_count=target_count,
                anchor_count=anchor_count,
            )
        )

    return sweep_specs
```

## 14. 正式 sweep 物化伪代码

### 14.1 `materialize_lane_sweeps(...)`

```python
def materialize_lane_sweeps(...):
    # 这一层只负责把 layout spec 列表变成正式 SweepInfo 列表。
    # 它不再参与布局决策。
    # 也就是说，到了这里，sweep 的条数、侧别、横向 offset 结构都已经定死，
    # 这里只做 contract 物化，不允许再偷偷改布局结果。

    sweep_items = []
    positive_count = 0
    negative_count = 0
    center_sweep_id = None
    current_sweep_id = next_sweep_id

    for spec in sweep_specs:
        # 第一步：给当前 spec 分配一个全局唯一的 sweep_id。
        sweep_item = build_sweep_item_from_layout(
            coverage_lane_id=coverage_lane_id,
            sweep_id=current_sweep_id,
            edge=edge,
            resolution_m_per_px=resolution_m_per_px,
            sampling_step_px=sweep_spacing_px,
            normal_search_px=normal_search_px,
            effective_min_clearance_px=effective_min_clearance_px,
            spec=spec,
        )
        sweep_items.append(sweep_item)

        # 第二步：按 side_label 统计中心/正侧/负侧数量。
        if spec.side_label == "center":
            center_sweep_id = current_sweep_id
        elif spec.side_label == "positive":
            positive_count += 1
        else:
            negative_count += 1

        current_sweep_id += 1

    return sweep_items, current_sweep_id, center_sweep_id, positive_count, negative_count
```

### 14.2 `build_sweep_item_from_layout(...)`

```python
def build_sweep_item_from_layout(...):
    # 这一层把单条 lane_sweep_spec 变成正式 SweepInfo。
    # 当前只做 contract 口径整理，不重算布局。

    path_tuple = to_path_tuple(spec["path_rc"])
    path_length_px = float(spec["path_length_px"])
    offset_profile = tuple(float(item) for item in spec["offset_profile_px"])

    return {
        # 正式身份字段。
        "sweep_id": int(sweep_id),
        "coverage_lane_id": int(coverage_lane_id),
        "source_edge_id": int(edge.edge_id),

        # 侧别语义字段。
        "side_label": str(spec["side_label"]),
        "side_level": int(spec["side_level"]),

        # 正式几何字段。
        # path_rc 是这条 sweep 真正会被后续阶段继续消费的点链。
        "path_rc": [list(point) for point in path_tuple],
        "anchor_points_rc": [list(point) for point in spec["anchor_points_rc"]],
        "offset_profile_px": [float(item) for item in offset_profile],

        # 生成参数口径字段。
        "sampling_step_px": int(sampling_step_px),
        "normal_search_px": int(normal_search_px),
        "effective_min_clearance_px": float(effective_min_clearance_px),

        # 摘要字段。
        "path_count": int(len(path_tuple)),
        "path_length_px": float(path_length_px),
        "path_length_m": float(path_length_px * resolution_m_per_px),

        # 当前物化出来的 sweep 默认就是 active。
        "active": True,
    }
```

## 15. 关键规则

### 15.1 真实主轴是 `edge.outer_path_rc`

当前 lane 和 sweep 生成的主轴几何来自：

- `edge.outer_path_rc`

不是：

- `edge.path_rc`
- `inner_path_rc`
- 其他临时中心链

### 15.2 sweep 横向允许域不是“只要 free 就行”

当前 `allowed_domain_mask` 的真实语义是：

- `own_territory ∪ own_endpoint_polygons`

因此 sweep 横向搜索不允许轻易串入别的通道。

### 15.3 `effective_region_mask` 当前是工作域表达，不是 sweep 中心点硬约束

当前它会生成并写入 `coverage_lane_info`，但 sweep 布局的直接横向搜索仍以：

- `allowed_domain_mask`
- `free_mask`
- `obstacle_distance_px`

为主。

### 15.4 当前横向铺设不是“先中心一条，再向两侧固定复制”

当前真实逻辑是：

1. 主轴采样锚点
2. 每锚点求横向主连续段
3. 每锚点先算局部条数
4. 取稳健分位数统一条数
5. 每锚点按统一条数回填 offsets
6. regroup 成 sweep specs

### 15.5 当前全 lane 目标条数不是取最大值，也不是取最小值

当前用的是：

- `solve_robust_target_sweep_count(local_counts, robust_quantile)`

当前源码调用口径是：

- `robust_quantile = 0.6`

文档不能把这层改写成别的条数策略。

### 15.6 lane 失败必须显式标 reason

当前失败口径至少包括：

- `outer_path_too_short`
- `missing_endpoint_node`
- `sweep_layout_invalid`

失败 lane 仍然必须写正式 `lane_item`，而不是直接丢掉这条 edge。

## 16. 校验重点

当前这一段至少要校验：

1. `coverage_lane_info[*].source_edge_id` 能回指正式 `graph_info.edges`
2. `coverage_lane_info[*].sweep_ids` 能回指当前轮生成的 `sweeps`
3. `active == False` 时必须给出 `excluded_reason`
4. `active == True` 时 `sweep_count` 必须为正
5. 每条 `sweep.path_rc` 至少包含两个点

对应当前源码中的 stage-level validation 入口是：

- `validate_coverage_lane_generation(...)`

## 17. 与后续模块的边界

这一步完成之后，正式输出停在：

- `CoverageLaneSweepBuildInfo`

以及一个带 coverage 投影的新 `graph_info`。

后续如果要继续做：

- `sweep_transition_candidate_info`
- `sweep_graph_build_info`
- `sweep_cadence_build_info`
- `final_coverage_path_build_info`

那已经属于 sweep 连接与覆盖节拍阶段，不属于本文范围。

这条边界必须明确，不允许再把 sweep 连接、cadence 和 final path 混回 sweep 生成文档。

## 18. 总结

当前 sweep 生成这段的正式主线应收敛为：

1. `build_coverage_lane_sweep_info(...)` 是 stage 级正式入口
2. `build_coverage_lanes_and_sweeps(...)` 是子域总 builder
3. 单 edge 的真实 sweep 生成主 helper 是 `build_single_coverage_lane(...)`
4. 横向布局求解的核心 helper 是 `build_lane_sweep_specs(...)`
5. 正式 sweep 物化的核心 helper 是 `build_sweep_item_from_layout(...)`
6. 当前正式输出只到 `CoverageLaneSweepBuildInfo`，不包含 sweep 连接和 cadence

换句话说，本文只回答：

- 一条 edge 如何变成一条 coverage lane
- 一条 coverage lane 如何变成一组正式 sweeps

而不回答：

- 这些 sweeps 后续如何连接、如何排序、如何组成最终路径
