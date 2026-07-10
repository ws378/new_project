# ShelfAware+TurnCost 轻量候选基线

## 1. 用途

本目录是 `shelf_aware_turn_cost` 交付门禁使用的轻量候选基线 fixture。

它用于证明行为不变重构没有改变三项目 19 区域的最终路径点：

```text
algorithms/turn_cost_coverage_research/scripts/baseline/run_shelf_aware_turn_cost_delivery_gate.py
-> run_candidate_baseline_gate.py
-> build_effect_snapshot.py
```

## 2. 内容

本目录只保留：

- `summary.json`：三项目 19 区域的指标摘要；
- `areas/*/path_pixels.json`：每个区域最终 path pixels，用于 path identity 哈希对比。

`summary.json` 中包含两类指标：

- 硬门禁指标：`coverage_ratio`、`long_jump_count`、`infeasible_segment_count`；
- 非硬门禁只读指标：`narrow_coverage_ratio`、`turn_hotspot_count`、`lane_over_dense_count`、`lane_over_sparse_count`、`lane_spacing_issue_count`、`segment_crossing_count`。

非硬门禁只读指标只用于风险暴露和趋势观察，不参与 `comparison_status` 的 fail/warn 判定。2026-06-19 只回填了这些只读指标，`path_pixels.json` 内容不变。

交付门禁会同时记录：

- `baseline_summary_sha256`；
- `baseline_path_pixels_count`；
- `baseline_path_pixels_missing_count`；
- `baseline_path_pixels_bundle_sha256`。

其中 `baseline_path_pixels_count` 表示成功读取到哈希的 path 数；`baseline_path_pixels_bundle_sha256` 只在 `baseline_path_pixels_missing_count=0` 时有效，按 `case_key + final_path_pixels_sha256` 稳定排序后计算，用于证明提交中的 19 个 `path_pixels.json` 与 `summary.json` 属于同一份轻量基线资产。

本目录不保留：

- PNG 可视化；
- planner 全量 artifact；
- 大体积 output run；
- 人工诊断中间产物。

## 3. 来源

该 fixture 从本地候选基线输出抽取：

```text
algorithms/turn_cost_coverage_research/output/candidate_baselines/run_20260617_123210_721341_shelf_aware_turn_cost_all_areas
```

原始目录约 176MB，位于 ignored output 下，不适合作为版本库资产。当前目录约 848KB，可提交，用于让交付门禁不依赖本机历史 output。

## 4. 更新规则

只有在明确接受 `shelf_aware_turn_cost` 行为变化时，才允许更新本 fixture。

更新必须同时满足：

- 说明为什么允许 path identity 变化；
- 重新运行三项目 19 区域候选基线；
- 重新生成本目录；
- 运行 `algorithms/turn_cost_coverage_research/scripts/baseline/run_shelf_aware_turn_cost_delivery_gate.py`；
- 在提交说明中写明新旧基线差异、`baseline_summary_sha256`、`baseline_path_pixels_bundle_sha256` 和证据路径。
