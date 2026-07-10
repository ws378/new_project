# F 第四轮：fallback debug artifact 与 trace optionalization

> 2026-05-06 更新：本文件属于历史诊断记录，不再作为后续实现方向。后续主线改为 `territory_node_semantics_design.md` 中定义的“空间归属 -> 覆盖责任 -> 连通价值 -> 节点角色”。不得继续沿用“规划前把 optional node 设为 visited”或“简单跳过 fallback target”的语义。


本文记录两件事：

1. `shelf_aware_guarded` debug artifact 增强。
2. 基于 `fallback_debug_trace.json` 的 optional fallback target 对齐分析。

本轮只增加 debug 输出，不改变 planner 选择逻辑。

## Debug artifact 增强

新增/增强输出：

```text
fallback_debug_trace.json
node_debug_enriched.json
energy_debug.csv 追加 node_id / grid row-col / adjusted flag 等字段
```

### fallback_debug_trace.json

每次 global fallback 触发时记录：

```text
step
path_index_before_selection
current_node
local_residual_count
unvisited_node_count_before_selection
unvisited_node_ids_before_selection
candidate_count
candidates[]  # 含 node_id / grid row-col / center / energy
selected_node_id
selected_energy
```

### node_debug_enriched.json

每个 grid node 记录：

```text
node_id
grid_row / grid_col
center_rotated
grid_center_rotated
adjusted_from_grid_center
center_pixel
center_world
neighbor_ids
min_distance_m
obstacle_neighbor_count
non_obstacle_neighbor_count
```

### energy_debug.csv

保留原有 `x/y/status/obstacle_neighbor_count/min_distance_m`，追加：

```text
node_id
grid_row / grid_col
center_rotated_x / center_rotated_y
grid_center_rotated_x / grid_center_rotated_y
adjusted_from_grid_center
non_obstacle_neighbor_count
```

## 验证 run

新 run：

```text
algorithms/shelf_aware_ctg_research/output/run_20260506_102054_774428
```

验证结果：

```text
area_count = 12
fallback_debug_trace.json = 12
node_debug_enriched.json = 12
energy_debug.csv = 12
```

与旧 run 对比，重点区域 path 点数和长度未变化：

```text
beiguo_lanshan_0407_area_1: old 1370 / 784.187m, new 1370 / 784.187m
beiguo_lanshan_0407_area_6: old 2922 / 1713.161m, new 2922 / 1713.161m
fourfloor_area_6: old 395 / 234.023m, new 395 / 234.023m
fourfloor_area_7: old 322 / 209.070m, new 322 / 209.070m
```

说明本轮 debug 增强没有改变这些代表区域的路径结果。

## fallback trace optionalization 分析

脚本：

```text
algorithms/shelf_aware_ctg_research/scripts/analyze_fallback_trace_optionalization.py
```

运行命令：

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 -m algorithms.shelf_aware_ctg_research.scripts.analyze_fallback_trace_optionalization   --run-dir algorithms/shelf_aware_ctg_research/output/run_20260506_102054_774428
```

输出：

```text
algorithms/shelf_aware_ctg_research/output/run_20260506_102054_774428/fallback_trace_optionalization_summary.json
<area>/diagnostics/fallback_trace_optionalization/fallback_trace_optionalization.json
```

## 全局结果

```text
fallback_event_count = 221
optional_node_count = 31
selected_optional_fallback_event_count = 31
selected_optional_with_replacement_count = 31
```

解释：

- 31 个 optional overlap node 全部确实是 global fallback 选中的 target。
- 这些目标不是后处理误判出来的，而是 planner fallback 阶段真实选择过的节点。

## 重点区域

### beiguo_lanshan_0407_area_6

```text
fallback_event_count = 108
optional_node_count = 14
selected_optional_fallback_event_count = 14
selected_optional_with_replacement_count = 14
replacement_energy_delta_mean = 91.714
replacement_distance_delta_m_mean = 0.714
```

### fourfloor_area_6

```text
fallback_event_count = 7
optional_node_count = 0
selected_optional_fallback_event_count = 0
```

继续作为反例。

### fourfloor_area_7

```text
fallback_event_count = 11
optional_node_count = 2
selected_optional_fallback_event_count = 2
selected_optional_with_replacement_count = 2
replacement_energy_delta_mean = 158.509
replacement_distance_delta_m_mean = 0.269
```

## 当前可信判断

1. optional overlap targets 是真实 fallback 目标，不是后处理噪声。
2. 但直接跳过这些目标会选到 energy 明显更高的替代候选。
3. 所以优化不能只是“发现 optional 就跳过”。需要改 fallback target 的评价语义，例如：
   - optional target 不计入必须覆盖；
   - 或给 optional target 一个单独的 already-covered 判断；
   - 或在 grid node 生成阶段就标记 optional，避免其进入必须访问集合。
4. 事后 pruning 不是主线，fallback 前 optionalization / grid node optionalization 才是主线。

## 下一步

下一批建议进入研究版实现设计：

- 在 debug artifact 基础上定义 `optional_node_mask`。
- 研究版 replay：从 fallback trace 中模拟“optional node 不作为 unvisited target”。
- 如果 replay 仍需要高 energy 替代候选，则说明要更早处理：grid node 生成阶段 optionalization。
