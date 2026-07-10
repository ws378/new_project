# F 第三轮：fallback optionalization feasibility

> 2026-05-06 更新：本文件属于历史诊断记录，不再作为后续实现方向。后续主线改为 `territory_node_semantics_design.md` 中定义的“空间归属 -> 覆盖责任 -> 连通价值 -> 节点角色”。不得继续沿用“规划前把 optional node 设为 visited”或“简单跳过 fallback target”的语义。


本文记录 `analyze_fallback_optionalization_feasibility.py` 的结果。该脚本不重放 planner，只审计现有 artifacts 是否足以支持 fallback target optionalization 研究。

## 输入

```text
algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008
```

运行命令：

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 -m algorithms.shelf_aware_ctg_research.scripts.analyze_fallback_optionalization_feasibility   --run-dir algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008
```

## 输出

全局 summary：

```text
algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008/fallback_optionalization_feasibility_summary.json
```

每个 area 输出：

```text
<area>/diagnostics/fallback_optionalization_feasibility/fallback_optionalization_feasibility.json
```

## 结论

现有 artifacts 不能精确重放 fallback target 选择。

缺失字段：

```text
per_step_selected_node
per_step_is_global_fallback
per_step_candidate_energy_list
per_step_unvisited_node_set_before_selection
node_grid_row_col_or_stable_node_id
complete_cell_original_center_and_adjusted_flag
```

原因：当前输出包含最终 path、jump segments、最终 grid-node CSV 和后处理诊断，但没有每一步 fallback 发生时的候选列表、energy、未访问集合和稳定 node id。

## proxy 结果

全局 proxy：

```text
jump_target_count = 69
optional_overlap_candidate_count = 31
review_candidate_count = 38
optional_reconnect_ready_count = 1
optional_reconnect_blocked_count = 27
optional_coverage_review_count = 3
optional_jump_length_upper_bound_m = 132.932
reconnect_ready_jump_length_upper_bound_m = 1.051
```

解释：

- 31 个 overlap candidate 只是 fallback optionalization 的潜在输入。
- 经过 local reconnect 检查后，只有 1 个 candidate 具备低风险后处理删除条件。
- 因此，不应继续把 post-process pruning 当主线。
- 如果要真正减少远跳，应在 fallback target 选择时判断 optional，而不是事后直连。

## 重点区域

### beiguo_lanshan_0407_area_6

```text
jump_target_count = 31
optional_overlap_candidate_count = 14
review_candidate_count = 17
optional_reconnect_ready_count = 1
optional_reconnect_blocked_count = 10
optional_coverage_review_count = 3
optional_jump_length_upper_bound_m = 40.323
reconnect_ready_jump_length_upper_bound_m = 1.051
```

### fourfloor_area_6

```text
jump_target_count = 1
optional_overlap_candidate_count = 0
review_candidate_count = 1
```

该区域继续作为反例。

### fourfloor_area_7

```text
jump_target_count = 5
optional_overlap_candidate_count = 2
review_candidate_count = 3
optional_reconnect_ready_count = 0
optional_reconnect_blocked_count = 2
optional_jump_length_upper_bound_m = 21.997
reconnect_ready_jump_length_upper_bound_m = 0.000
```

## 下一步判断

当前研究已经能说明：

1. 远跳与 overlap / boundary / low-value target 有关联。
2. 简单后处理 pruning 不可靠。
3. fallback optionalization 需要 planner-side debug 或研究版 planner replay。

下一批如果继续推进，应先做“研究版 debug artifact 增强”设计，而不是直接改正式算法：

- 给每一步 selected node 加 stable id。
- 记录是否 global fallback。
- 记录 fallback 候选节点列表、energy、optional 判定字段。
- 记录每个 node 的 grid row/col、原始 cell center、adjusted center、cell free area。

这些字段具备后，才能可信地做 fallback target optionalization simulation。
