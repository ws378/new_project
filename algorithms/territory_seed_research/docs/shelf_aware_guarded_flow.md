# shelf_aware_guarded 流程与关键规则

本文只梳理当前代码已经实现的 `shelf_aware_guarded` 行为，不讨论新的组合策略。

## 入口

主入口是 `ShelfAwareCoveragePlanner.plan()`：

- 代码：`algorithms/coverage_planning/planners/shelf_aware_guarded/shelf_aware_planner.py`
- 内部规划入口：`planner.py::plan_coverage_path()`
- 输入核心数据：
  - `room_map`：局部区域 free mask，255 表示可通行/待覆盖区域。
  - `map_resolution`：米/像素。
  - `starting_position`：像素坐标 `(x, y)`。
  - `CoveragePlannerConfig`：覆盖宽度、转角约束、局部方向权重、fallback/revisit 参数等。

当前默认模式下，不需要 CTG，也不需要 axis prior。

## 总体流程

当前流程可以简化为：

```text
room_map
  -> 求整块区域主方向
  -> 按主方向旋转 room_map
  -> 在旋转图上按 coverage_width 建覆盖网格节点
  -> 计算局部方向图 local_direction_map/confidence
  -> 从起点最近网格节点开始
  -> 逐步选择最低能量候选节点
  -> 必要时 revisit / global fallback
  -> 简化路径点
  -> 反旋转回原图像素路径
  -> 输出 path_pixels / path_world / 可视化
```

## 主方向和旋转

代码位置：`./geometry/room_rotation.py`

规则：

1. 用 Canny 提取边界。
2. 用 HoughLinesP 识别线段。
3. 将线段方向按 `[0, pi]` 做 36 个 bin 统计。
4. 用线段长度作为权重。
5. 取权重最大的 bin 中心作为 `rotation_angle`。
6. 将整块区域旋转到该方向。

含义：

- 这是一个全局方向估计。
- 对矩形、货架、长通道通常有效。
- 对 L 形、回字形、十字形、多方向通道，单个全局主方向不一定能表达全部区域。
- 但后续还有 local direction，不是完全只依赖全局方向。

## 覆盖网格节点

代码位置：`graph_build/grid_builder.py`

规则：

1. `coverage_width_px = floor(coverage_width_m / resolution)`。
2. 在旋转后的 free mask bounding box 内按 `coverage_width_px` 采样网格。
3. 每个网格中心调用 `complete_cell_test()`：
   - 如果中心点本身是 free，则直接作为节点中心。
   - 如果中心点不是 free，但该 cell 内有 free 像素，则在 cell 内做 distance transform，选择离障碍更远且离原中心最近的点作为调整后的节点中心。
   - 如果 cell 内没有 free 像素，则该节点为 obstacle/visited。
4. 每个节点连接 8 邻域节点。

含义：

- 最终路径点本质上是网格节点访问序列，不是严格几何 sweep line。
- 节点会因局部障碍/边界被调整，所以路径点可能不是规则栅格。
- 网格粒度由覆盖宽度决定。

## baseline local direction

代码位置：`direction/field.py::compute_local_direction_map()`

规则：

1. 对旋转后的 `room_map` 做 Canny。
2. 对边界图做 Sobel 梯度。
3. 用 structure tensor：`j_xx, j_yy, j_xy`。
4. 高斯平滑窗口默认来自 `LocalDirectionConfig.window_size_px=41`，sigma 默认 `6.0`，并至少与覆盖宽度相关。
5. 得到边界方向 `edge_orientation`。
6. 行走方向取边界方向旋转 90 度：`travel_orientation = edge_orientation + pi/2`。
7. 方向是无向轴语义：模 `pi`。
8. confidence 来自 structure tensor coherence，并只在 free 区有效。

含义：

- baseline 对货架边界、墙边、局部细节敏感。
- 这是 `shelf_aware_guarded` 在货架场景表现较好的主要原因之一。
- 它受边界噪声影响，但比单个全局主方向更局部。

## 候选能量规则

代码位置：`traversal_core/candidate_scoring.py`

每一步从当前节点选择候选节点，能量主要包含：

1. **平移代价**
   - 距离越远代价越高。
   - 对邻域节点通常接近 1。

2. **转向代价**
   - 当前 travel angle 相对上一段 travel angle 的角度差。
   - 角度差越大代价越高。

3. **转角硬约束**
   - 如果 `turn_constraint_enable=True`，近距离大转角可能被禁止。
   - 默认参数来自 `CoveragePlannerConfig`。

4. **local direction 代价**
   - 在候选节点位置采样 `local_direction_map/confidence`。
   - 如果 confidence 超过阈值，则按行走方向和局部偏好轴的夹角加代价。
   - 使用无向轴 penalty：同向/反向都认为一致，垂直惩罚最大。

5. **local lateral 代价**
   - 在当前节点采样局部方向。
   - 鼓励沿当前局部方向继续走，减少横向偏离。

6. **revisit / fallback 相关代价**
   - revisit 候选会考虑 frontier 可达性和 revisit penalty。
   - global fallback 会额外加跳转距离代价和 heading 代价。
   - history clearance 会惩罚离已有路径太近的 fallback。

## revisit 与 global fallback

代码位置：`planner.py::plan_coverage_path()`

搜索顺序：

1. 优先找未访问的 8 邻域节点。
2. 如果找不到，并允许 `allow_revisit_bridge`，尝试走已访问但仍能通向未访问区域的邻居。
3. 如果仍找不到，则 global fallback：遍历所有未访问节点，选择能量最低者。

含义：

- revisit bridge 允许小范围重复通过，适合小路口/连接区。
- global fallback 保证覆盖能继续，但也可能造成大范围跳动。
- 当前 fallback 主要由几何距离和转角控制，不理解 CTG 拓扑距离。

## path_pixels 如何生成

代码位置：`planner.py`、`final_path/realization.py` 和 `final_path/postprocess.py`

规则：

1. 搜索得到 `fov_coverage_path`，这是旋转坐标系下的网格节点序列。
2. 调用 `simplify_point_path()` 做简单点列简化。
3. 将简化后的点反旋转回原图像素坐标。
4. `point_path_to_pose_path()` 根据相邻点方向生成 theta。
5. 转成 world path。
6. `ShelfAwareCoveragePlanner._to_path_pixels()` 再从 world path 还原 pixel path 返回。

后处理规则：

- `simplify_point_path()` 会删除短距离、大转角的局部折返点。
- `split_point_path()` 按大转角或长跳转拆 segment。
- `build_jump_segments()` 标记跳转段。

含义：

- 当前路径点不是严格的连续 sweep 线段，而是网格访问点。
- 路径点数量、短折线、局部抖动，与网格搜索和后处理都有关系。
- 后续如果做模块级优化，路径点后处理是相对独立的切入点。

## 当前优点

- 对货架、墙边、局部边界方向敏感。
- 不依赖 CTG，失败面较小。
- revisit/fallback 机制使覆盖完整性较强。
- 对简单通道、单连通区域表现稳定。

## 当前风险

- 全局主方向对 L 形、回字形、十字形不是充分表达。
- local direction 来自边界图，边界噪声会影响方向稳定性。
- global fallback 不理解拓扑，可能跨通道跳转。
- 路口没有显式语义，重复通过和掉头都只是能量搜索自然产生。
- path_pixels 是网格访问序列，几何形态未必最优。
