# ShelfAware 参数代码级说明

本文档按当前代码实现解释 `CoverageDialog` 中 ShelfAware 相关参数。说明基于代码调用链，不按 UI 文案字面解释。

## 入口和传递链路

UI 定义位置：

- `maptools/views/coverage_dialog.py`
- `CoverageDialog._build_widgets()`
- `CoverageDialog.get_config()`

公共配置对象：

- `algorithms/coverage_planning/contracts/config.py`
- `CoveragePlannerConfig`

ShelfAware 适配层：

- `algorithms/coverage_planning/planners/shelf_aware_guarded/shelf_aware_planner.py`
- `ShelfAwareCoveragePlanner._build_planner_config(...)`

内部规划配置：

- `algorithms/coverage_planning/planners/shelf_aware_guarded/energy_functional/models.py`
- `PlannerConfig`
- `StrategyConfig`
- `LocalDirectionConfig`
- `TurnConstraintConfig`

主流程：

- `energy_functional/energy_planner.py::plan_coverage_path(...)`
- `energy_functional/traversal.py::run_traversal_loop(...)`
- `energy_functional/candidate_scoring.py::evaluate_candidate_score_for_geometry(...)`

## ShelfAware 专属参数

### 启用局部方向图

UI 字段：

- `local_direction_enable`

公共配置：

- `CoveragePlannerConfig.local_direction_enable`

内部配置：

- `PlannerConfig.local_direction.enable`

代码使用点：

- `direction/field.py::resolve_local_direction_maps(...)`
- `candidate_scoring.py::compute_energy_breakdown_for_geometry(...)`

实际作用：

`resolve_local_direction_maps(...)` 总会解析出方向图和置信度图。候选评分时，只有 `local_direction.enable=True` 且方向图、置信度图都存在，才会在候选节点位置采样局部方向并加入方向惩罚。

关闭后，`compute_energy_breakdown_for_geometry(...)` 不使用方向图，而进入旧的水平移动偏好分支：

```python
horizontal_movement_ratio = abs(diff_x) / (abs(diff_x) + abs(diff_y) + 1e-6)
horizontal_reward = 8.0 - 1.5 * horizontal_movement_ratio
energy += horizontal_reward
```

因此这个开关不是控制是否生成方向图，而是控制候选评分是否使用方向图。

### 局部方向权重

UI 字段：

- `local_direction_energy_weight`

公共配置：

- `CoveragePlannerConfig.local_direction_energy_weight`

内部配置：

- `LocalDirectionConfig.energy_weight`

代码使用点：

- `candidate_scoring.py::compute_energy_breakdown_for_geometry(...)`

候选评分公式：

```python
direction_penalty = undirected_axis_penalty(travel_angle, local_preferred_angle)
energy += local_direction_cfg.energy_weight * local_confidence * direction_penalty
```

含义：

- `travel_angle` 是当前节点到候选节点的移动方向。
- `local_preferred_angle` 是候选节点位置从局部方向图采样得到的无向轴角。
- `undirected_axis_penalty(...)` 使用 `abs(sin(delta_angle))`，所以沿轴正反方向都低惩罚，横切方向高惩罚。
- `local_confidence` 是方向图置信度，低于 `LocalDirectionConfig.min_confidence` 时该项不生效。

该值越大，路径越不愿意偏离局部货架/通道主方向。

### 长跳惩罚权重

UI 字段：

- `fallback_jump_weight`

公共配置：

- `CoveragePlannerConfig.fallback_jump_weight`

内部配置：

- `StrategyConfig.fallback_jump_weight`

代码使用点：

- `candidate_scoring.py::compute_energy_breakdown_for_geometry(...)`
- 只在 `is_global_fallback=True` 时生效。

公式：

```python
translational = distance_px / coverage_width_px
dist_ratio = max(0.0, translational - 1.0)
energy += fallback_jump_weight * dist_ratio * dist_ratio
```

含义：

邻接候选不使用该项。只有当前节点没有可接受邻接候选，需要从所有未访问节点中选择全局 fallback 候选时，才会惩罚距离超过一个覆盖步长的候选。

该值越大，全局 fallback 越不愿意跳很远。

### 历史轨迹净空权重

UI 字段：

- `history_clearance_weight`

公共配置：

- `CoveragePlannerConfig.history_clearance_weight`

内部配置：

- `StrategyConfig.history_clearance_weight`

代码使用点：

- `traversal_history_clearance.py::build_history_clearance_index(...)`
- `candidate_scoring.py::history_clearance_penalty(...)`
- `traversal.py::run_traversal_loop(...)`

生效范围：

只在全局 fallback 候选评分中生效。普通邻接移动不使用该项。

历史点索引：

`HistoryClearanceIndex` 用网格桶缓存历史路径点，默认跳过最近 `12` 个路径点，避免把局部连续移动误判为贴近历史。

惩罚公式：

```python
clearance_limit = coverage_width_px * history_clearance_radius_factor
energy += history_clearance_weight * (clearance_limit - clearance) / coverage_width_px
```

其中：

- `clearance` 是 fallback 候选到历史路径点的最近距离。
- `history_clearance_radius_factor` 当前 UI 没有直接暴露，`StrategyConfig` 默认是 `2.0`。
- `coverage_width_px` 用于归一化距离尺度。

该值越大，全局 fallback 越不愿意落在历史路径附近。

## 高级参数

### 自动旋转对齐

UI 字段：

- `auto_rotate`

公共配置：

- `CoveragePlannerConfig.auto_rotate`

主要使用：

该参数不属于 ShelfAware 内部 `PlannerConfig`，而是在外层覆盖规划适配/预处理阶段决定是否对区域做主方向旋转。进入 `shelf_aware` 的能量规划器时，`energy_planner.py` 接收到的已经是旋转后的 `rotated_room_map`。

代码影响：

- 影响房间图进入 ShelfAware 前的坐标系。
- 不直接参与 `candidate_scoring.py` 的能量评分。
- 不等同于 `shelf_row_endpoint_alignment_enable`。

### 启用行段首尾对齐

UI 字段：

- `shelf_row_endpoint_alignment_enable`

公共配置：

- `CoveragePlannerConfig.shelf_row_endpoint_alignment_enable`

内部配置：

- `PlannerConfig.row_endpoint_alignment_enable`

代码使用点：

- `energy_planner.py::plan_coverage_path(...)`
- `grid_builder.py::build_nodes(...)`
- `grid_builder.py::align_grid_segments_to_free_endpoints(...)`

执行位置：

节点构建后、邻接关系建立前。

当前行为：

- 先按行对连续非障碍节点做左右端点对齐。
- 再按列对连续非障碍节点做上下端点对齐。
- 只修改 `Node.planning_point_px`。
- 不修改 `Node.grid_center_px`。
- 不修改节点数量。
- 不直接删除节点。

重要边界：

连续段分组只按 `node.obstacle` 断段，不再用上下/左右 block 签名断段。

### 启用转角约束

UI 字段：

- `turn_constraint_enable`

公共配置：

- `CoveragePlannerConfig.turn_constraint_enable`

内部配置：

- `TurnConstraintConfig.enable_prohibit`

代码使用点：

- `candidate_scoring.py::compute_energy_breakdown_for_geometry(...)`
- `candidate_scoring.py::evaluate_candidate_score_for_geometry(...)`

当前代码中的生效范围：

`compute_energy_breakdown_for_geometry(...)` 里有如下条件：

```python
if turn_constraint.enable_prohibit and not is_global_fallback:
    ...
```

所以转角硬约束只对邻接移动和 revisit bridge 这类 `is_global_fallback=False` 的候选生效。全局 fallback 候选不会进入该硬约束分支。

违反约束时，`compute_energy_breakdown_for_geometry(...)` 返回 `CandidateScoreBreakdown(total_energy=turn_constraint.prohibit_energy, accepted=false, rejected_reasons=("turn_constraint",))`。

随后 `evaluate_candidate_score_for_geometry(...)` 会把硬拒绝候选标记为 `accepted=false`，并记录 `rejected_reasons=("turn_constraint",)`。

### 近邻判定距离

UI 字段：

- `turn_constraint_near_dist_m`

公共配置：

- `CoveragePlannerConfig.turn_constraint_near_dist_m`

内部配置：

- `TurnConstraintConfig.near_dist_m`

代码使用点：

- `candidate_scoring.py::compute_energy_breakdown_for_geometry(...)`

逻辑：

```python
dist_m = hypot(diff_x, diff_y) * map_resolution
if dist_m <= near_dist_m:
    use near_max_turn_deg
else:
    use neighbor_max_turn_deg
```

它是转角约束的分段阈值。小于等于该距离时使用更严格的近邻转角上限。

### 近邻最大转角

UI 字段：

- `turn_constraint_near_max_turn_deg`

公共配置：

- `CoveragePlannerConfig.turn_constraint_near_max_turn_deg`

内部配置：

- `TurnConstraintConfig.near_max_turn_deg`

代码使用点：

- `candidate_scoring.py::compute_energy_breakdown_for_geometry(...)`

逻辑：

当候选移动距离 `dist_m <= near_dist_m` 时，如果当前移动方向相对上一段方向的角度变化超过该值，候选直接被过滤。

### 邻接最大转角

UI 字段：

- `turn_constraint_neighbor_max_turn_deg`

公共配置：

- `CoveragePlannerConfig.turn_constraint_neighbor_max_turn_deg`

内部配置：

- `TurnConstraintConfig.neighbor_max_turn_deg`

代码使用点：

- `candidate_scoring.py::compute_energy_breakdown_for_geometry(...)`

逻辑：

当候选移动距离 `dist_m > near_dist_m` 且不是全局 fallback 时，使用该角度作为最大允许转角。

当前代码中，`is_global_fallback=True` 不进入转角硬约束分支，所以该参数主要控制普通邻接候选。

### 回退最大转角

UI 字段：

- `turn_constraint_fallback_max_turn_deg`

公共配置：

- `CoveragePlannerConfig.turn_constraint_fallback_max_turn_deg`

内部配置：

- `TurnConstraintConfig.fallback_max_turn_deg`

代码现状：

`compute_energy_breakdown_for_geometry(...)` 中保留了 fallback 转角放宽公式，但外层条件是：

```python
if turn_constraint.enable_prohibit and not is_global_fallback:
```

因此当前正式路径下，全局 fallback 候选不会使用 `fallback_max_turn_deg` 做硬过滤。

这意味着该参数在当前 ShelfAware 正式评分链路中基本没有实际效果，属于保留字段/历史公式残留。

### 回退放宽距离

UI 字段：

- `turn_constraint_fallback_relax_dist_m`

公共配置：

- `CoveragePlannerConfig.turn_constraint_fallback_relax_dist_m`

内部配置：

- `TurnConstraintConfig.fallback_relax_dist_m`

代码现状：

和 `fallback_max_turn_deg` 一样，当前 fallback 硬转角分支不会被执行，因此该值在当前 ShelfAware 正式路径中基本没有实际效果。

### 横切惩罚权重

UI 字段：

- `local_lateral_weight`

公共配置：

- `CoveragePlannerConfig.local_lateral_weight`

内部配置：

- `StrategyConfig.local_lateral_weight`

代码使用点：

- `candidate_scoring.py::compute_energy_breakdown_for_geometry(...)`

公式：

```python
lateral_ratio = undirected_axis_penalty(travel_angle, current_preferred_angle)
energy += local_lateral_weight * current_confidence * lateral_ratio
```

区别于 `local_direction_energy_weight`：

- `local_direction_energy_weight` 在候选节点位置采样方向场。
- `local_lateral_weight` 在当前位置采样方向场。

它约束的是“从当前通道/货架边离开”的移动。

### 长跳切段阈值倍率

UI 字段：

- `split_jump_dist_factor`

公共配置：

- `CoveragePlannerConfig.split_jump_dist_factor`

内部配置：

- `StrategyConfig.split_jump_dist_factor`

代码使用点：

- `path_postprocess.py::split_point_path(...)`
- `path_postprocess.py::build_jump_segments(...)`
- `path_postprocess.py::build_segment_index_groups(...)`
- `path_postprocess.py::build_jump_segment_indices(...)`

作用：

该参数不影响节点遍历时选点。它在路径生成后用于把最终点序列拆成普通覆盖 segment 和 jump segment。

典型逻辑是：相邻点距离超过 `coverage_width_px * split_jump_dist_factor` 时，认为是长跳连接。

### 启用重复回接

UI 字段：

- `allow_revisit_bridge`

公共配置：

- `CoveragePlannerConfig.allow_revisit_bridge`

内部配置：

- `StrategyConfig.allow_revisit_bridge`

代码使用点：

- `traversal.py::run_traversal_loop(...)`

生效位置：

当没有未访问邻接节点可选时，如果该参数为 true，规划器会允许选择已访问但访问次数未超限的邻接节点作为桥接点。

桥接候选还必须满足：

- `candidate.visit_count < max_revisit_count`
- 从该候选出发在 `revisit_frontier_depth` 内能到达未访问节点

当前 UI 只暴露开关，没有暴露 `max_revisit_count/revisit_penalty/revisit_frontier_depth/revisit_frontier_weight`。

## 与图中参数相关但不在截图内的新增节点过滤参数

### 节点障碍比例过滤开关

公共配置：

- `CoveragePlannerConfig.shelf_node_obstacle_ratio_filter_enable`

内部配置：

- `PlannerConfig.node_obstacle_ratio_filter_enable`

代码使用点：

- `grid_builder.py::build_nodes(...)`
- `grid_builder.py::filter_nodes_by_obstacle_ratio(...)`

当前 UI 截图中未展示该字段，但暂存代码已经加入正式配置。

### 节点障碍比例阈值

公共配置：

- `CoveragePlannerConfig.shelf_node_obstacle_ratio_threshold`

内部配置：

- `PlannerConfig.node_obstacle_ratio_threshold`

代码使用点：

- `grid_builder.py::filter_nodes_by_obstacle_ratio(...)`

逻辑：

在 row/column endpoint alignment 后，以 `planning_point_px` 为中心，按机器人宽度方窗统计障碍比例。

如果：

```python
obstacle_ratio > node_obstacle_ratio_threshold
```

则该节点被置为：

```python
node.obstacle = True
node.visited = True
node.obstacle_ratio_filtered = True
```

该节点后续不会参与遍历。

## 参数之间的实际关系

### 影响候选评分的参数

直接进入 `candidate_scoring.py::compute_energy_breakdown_for_geometry(...)` 或 `evaluate_candidate_score_for_geometry(...)`：

- `local_direction_enable`
- `local_direction_energy_weight`
- `fallback_jump_weight`
- `history_clearance_weight`
- `local_lateral_weight`
- `turn_constraint_enable`
- `turn_constraint_near_dist_m`
- `turn_constraint_near_max_turn_deg`
- `turn_constraint_neighbor_max_turn_deg`

### 影响节点构建的参数

进入 `grid_builder.py`：

- `coverage_width_m`
- `robot_width_m`
- `shelf_row_endpoint_alignment_enable`
- `shelf_node_obstacle_ratio_filter_enable`
- `shelf_node_obstacle_ratio_threshold`

### 影响方向图生成的参数

进入 `direction/field.py`：

- `local_direction_enable` 不控制方向图是否生成，只控制评分是否使用。
- `local_direction_energy_weight` 不参与方向图生成，只参与评分。
- 内部 `LocalDirectionConfig.window_size_px/smooth_sigma/min_confidence` 当前 UI 未暴露。

### 影响后处理的参数

不改变遍历选点，只改变最终路径分段或清理：

- `split_jump_dist_factor`
- `isolated_jump_cleanup_enable`
- `isolated_jump_distance_m`
- `isolated_jump_max_points`
- `isolated_jump_max_length_m`
- `isolated_jump_reinsert_max_distance_m`
- `isolated_jump_reinsert_improvement_ratio`

## 当前代码中的注意事项

1. `turn_constraint_fallback_max_turn_deg` 和 `turn_constraint_fallback_relax_dist_m` 在当前 ShelfAware 正式 fallback 路径中基本不生效，因为硬转角约束外层排除了 `is_global_fallback=True`。

2. `local_direction_enable=False` 时不是“没有方向成本”，而是进入旧的水平移动偏好分支，能量仍会被附加一项 `horizontal_reward`。

3. `history_clearance_weight` 只影响全局 fallback，不影响普通邻接移动。

4. `fallback_jump_weight` 只影响全局 fallback，不影响普通邻接移动。

5. `shelf_row_endpoint_alignment_enable` 只调整 `planning_point_px`，不改变 `grid_center_px`、节点数量和邻接构建规则。

6. `split_jump_dist_factor` 是后处理分段阈值，不是遍历时的长跳惩罚权重。
