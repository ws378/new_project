# B/C 加强诊断：残留网格节点与 jump target 归因

本文记录 `diagnose_residual_grid_nodes.py` 的第一轮结果。该脚本只分析 `shelf_aware_guarded` baseline 输出，不修改 planner，不生成独立 axis 路径。

## 输入

baseline run：

```text
algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008
```

运行命令：

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 -m algorithms.shelf_aware_ctg_research.scripts.diagnose_residual_grid_nodes   --run-dir algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008
```

## 输出

全局 summary：

```text
algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008/residual_grid_node_diagnostics_summary.json
```

每个 area 输出：

```text
<area>/diagnostics/residual_grid_nodes/01_path_territory_jumps.png
<area>/diagnostics/residual_grid_nodes/02_nodes_debug_enriched.png
<area>/diagnostics/residual_grid_nodes/03_jump_target_context.png
<area>/diagnostics/residual_grid_nodes/grid_node_metrics.json
<area>/diagnostics/residual_grid_nodes/jump_target_diagnostics.json
```

其中：

- `01_path_territory_jumps.png`：territory label 背景 + baseline path + edge switch 点 + jump segment。
- `02_nodes_debug_enriched.png`：grid node 按诊断分类着色。
- `03_jump_target_context.png`：jump segment、jump target、实际清扫半径和 target node 分类。
- `grid_node_metrics.json`：每个 node 的 estimated degree、local free ratio、贴边/unknown/jump-target 分类。
- `jump_target_diagnostics.json`：每个 jump target 的长度、到已有路径距离、nearest node 指标和分类。

## 已实现指标

### estimated_degree

由 `energy_debug.csv` 导出的非 obstacle node 在原图像素空间内估算，邻域半径为：

```text
1.55 * coverage_width_px
```

该值是诊断近似，用于识别孤立/半孤立节点，不等价于 planner 内部旋转网格的真实邻接表。

### local_free_ratio

在原图中，以 node 为中心，取约半个 coverage width 半径的方形窗口，统计 free pixel 比例。

该值用于识别局部 free 面积较小的节点。它不是 `complete_cell_test()` 的精确 cell 面积，因为当前 artifact 没有导出旋转网格 cell 信息。

### jump overlap

只对 jump target 使用“跳转发生前已有路径”距离判断：

```text
end_distance_to_prior_path_m <= actual_clean_width_m / 2
```

不能对所有已访问 node 使用完整 path 距离，否则 baseline 最终访问过的节点都会被误判为 overlap。

### center adjustment

当前不能精确判断 node 是否来自 `complete_cell_test()` 的中心调整。

原因：`energy_debug.csv` 只导出最终 node 坐标，没有导出原始 cell center、旋转网格 row/col、adjusted 标记或 cell free area。后续如果要精确分析，需要在研究版或 planner debug artifact 中补字段。

## 全量结果

本轮覆盖 12 个 area。

输出检查：

```text
diagnostics/residual_grid_nodes directories = 12
PNG files = 36
JSON files = 24
```

全局统计：

```text
node_count = 7318
jump_count = 69
long_jump_count_ge_2m = 50
jump_targets_within_overlap_radius = 31
```

节点分类累计：

```text
candidate_by_boundary_sensitive = 1424
candidate_by_low_degree = 195
candidate_by_overlap = 31
candidate_by_small_local_free_area = 67
candidate_by_unknown_or_junction_label = 1273
candidate_near_overlap_margin = 11
jump_target = 69
required_like = 4666
```

注意：这些分类是诊断候选，不代表可以直接删除。

## 重点区域

### beiguo_lanshan_0407_area_6

```text
node_count = 2689
jump_count = 31
long_jump_count_ge_2m = 22
jump_targets_within_overlap_radius = 14
```

jump target 分类：

```text
candidate_by_boundary_sensitive = 9
candidate_by_low_degree = 5
candidate_by_overlap = 14
candidate_by_small_local_free_area = 1
candidate_by_unknown_or_junction_label = 4
candidate_near_overlap_margin = 8
jump_target = 31
```

初步结论：

- 31 个 jump target 中，14 个在实际清扫半径内，另有 8 个在近邻 margin 内。
- 这支持后续研究“fallback 前是否可跳过 overlap target”。
- 同时有 9 个 target 边界敏感、5 个低 degree，说明部分远跳可能与边界/节点质量有关。
- 但仍有部分 target 只被标为 jump target，不能简单剪掉。

### fourfloor_area_6

```text
node_count = 386
jump_count = 1
long_jump_count_ge_2m = 1
jump_targets_within_overlap_radius = 0
```

jump target 分类：

```text
jump_target = 1
```

初步结论：

- 该 jump 不能由 overlap 或边界敏感直接解释。
- 它更可能是正常跨区或路径连接行为，需要看 path geometry，而不是作为 pruning 的第一类目标。

### fourfloor_area_7

```text
node_count = 310
jump_count = 5
long_jump_count_ge_2m = 4
jump_targets_within_overlap_radius = 2
```

jump target 分类：

```text
candidate_by_boundary_sensitive = 4
candidate_by_overlap = 2
candidate_near_overlap_margin = 1
jump_target = 5
```

初步结论：

- 5 个 jump target 中 2 个落在实际清扫半径内，1 个接近半径边界。
- 4 个 target 边界敏感，说明该小型多分支区域的远跳与边界节点质量有关。
- 这里适合作为后续 optional-by-overlap 和 boundary-sensitive 规则的重点样例。

## 当前可信判断

1. overlap jump target 是真实存在的，且不是少数：69 个 jump target 中 31 个满足 overlap。
2. 仅靠 overlap 不够，仍需要结合 boundary、degree、local free area、territory label 判断。
3. `beiguo_lanshan_0407_area_6` 适合分析 CTG label 过碎和 jump target 分布。
4. `fourfloor_area_7` 适合分析小区域多分支、边界敏感和 overlap target。
5. `fourfloor_area_6` 提醒我们不能把所有长 jump 都当成低价值残留点。

## 下一步

进入 D/E：

1. 对 jump target 生成更局部的裁剪 context 图，方便人工确认具体几何形态。
2. 定义 `required / optional_by_overlap / optional_by_boundary / snap_candidate / insert_candidate` 的第一版判据。
3. 先做 simulation，不改 planner：如果跳过 overlap target，估算路径长度减少和覆盖损失。
