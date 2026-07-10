# 20260617 shelfAware+TurnCost 候选基线

## 1. 结论

`shelf_aware_turn_cost` 已完成三项目 19 区域正式链路候选补证：

```text
19/19 成功
```

当前结论：

- 可以作为 `ShelfAware+TurnCost` UI 显式候选 mode 的候选基线证据。
- 不能升级为默认算法。
- 不能宣称全面优于 `shelf_aware`，因为长跳总数高于当前 shelfAware 基线。

## 2. 输入口径

运行入口：

```bash
algorithms/turn_cost_coverage_research/.venv/bin/python \
  algorithms/turn_cost_coverage_research/scripts/baseline/run_shelf_aware_all_areas.py \
  --planner-mode shelf_aware_turn_cost \
  --output-root algorithms/turn_cost_coverage_research/output/candidate_baselines
```

项目：

- `beiguo_lanshan_1770397756`
- `beiguoshangcheng_floor_3`
- `fourfloor_20250923_8`

区域数量：`19`

参数来源：

- 使用各项目当前保存参数；
- `planner_mode=shelf_aware_turn_cost`；
- mode defaults 强制：
  - `shelf_ctg_auxiliary_enable=True`
  - `shelf_node_generation_mode=turn_cost_repaired_grid`
  - `shelf_repaired_grid_max_offset_factor=0.28`
  - `isolated_jump_cleanup_enable=False`

## 3. 输出证据

候选基线输出：

```text
algorithms/turn_cost_coverage_research/output/candidate_baselines/run_20260617_123210_721341_shelf_aware_turn_cost_all_areas
```

summary：

```text
algorithms/turn_cost_coverage_research/output/candidate_baselines/run_20260617_123210_721341_shelf_aware_turn_cost_all_areas/summary.json
```

全部最终图：

```text
algorithms/turn_cost_coverage_research/output/candidate_baselines/run_20260617_123210_721341_shelf_aware_turn_cost_all_areas/全部最终shelf_aware_turn_cost_coverage
```

`final_segment_provenance.json` 数量：

```text
19
```

## 4. 指标摘要

| 指标 | `shelf_aware` 当前基线 | `shelf_aware_turn_cost` 候选基线 |
| --- | ---: | ---: |
| 区域成功数 | 19/19 | 19/19 |
| 覆盖率 min | 0.9905723171780789 | 0.9912209715785085 |
| 覆盖率 mean | 0.9965843781289876 | 0.9978171918561973 |
| 覆盖率 max | 1.0 | 1.0 |
| 长跳总数 | 133 | 191 |
| 不可行段总数 | 1841 | 1299 |

对比基线：

```text
algorithms/turn_cost_coverage_research/output/full_flow_tests/run_20260525_151418_596689_shelf_aware_all_areas/summary.json
```

## 5. 最差覆盖区域

| 项目 | 区域 | 覆盖率 | 长跳数 | 不可行段数 | 状态 |
| --- | ---: | ---: | ---: | ---: | --- |
| `beiguo_lanshan_1770397756` | 1 | 0.9912209715785085 | 16 | 184 | warn |
| `fourfloor_20250923_8` | 5 | 0.9941431670281996 | 0 | 2 | warn |
| `beiguo_lanshan_1770397756` | 6 | 0.9949750085440875 | 35 | 478 | warn |
| `beiguo_lanshan_1770397756` | 5 | 0.9952494596541787 | 8 | 84 | warn |
| `fourfloor_20250923_8` | 6 | 0.9969361015924209 | 4 | 29 | warn |

## 6. 判断

候选 mode 的价值：

- 覆盖率整体略高；
- 不可行段总数下降；
- 每个区域都有最终覆盖图；
- 每个区域都有 final segment provenance sidecar。

候选 mode 的风险：

- 长跳总数从 `133` 增加到 `191`；
- 质量守卫状态均可能继续给出 warning；
- 几何只读诊断已有同口径样例和全区域证据入口，但尚未成为硬门禁或默认 UI 风险提示；
- 尚未完成 UI 风险可见性展示的发布级验收。

因此当前定位保持为：

```text
UI-ready candidate mode
```

而不是：

```text
default planner
```

## 7. 行为守卫复跑证据

为确认重构没有改变 20260617 候选基线行为，追加一次三项目 19 区域重跑和路径身份对比。

重跑输出：

```text
algorithms/turn_cost_coverage_research/output/candidate_baselines/run_20260618_111631_507710_shelf_aware_turn_cost_all_areas
```

重跑结果：

```text
area_count=19
success_count=19
failed_count=0
```

覆盖区域：

```text
beiguo_lanshan_1770397756: area 1, 2, 3, 4, 5, 6
beiguoshangcheng_floor_3: area 3, 5, 6, 7, 8, 10, 16
fourfloor_20250923_8: area 2, 3, 4, 5, 6, 7
```

对比输出：

```text
algorithms/turn_cost_coverage_research/output/candidate_baselines/run_20260618_111631_507710_shelf_aware_turn_cost_all_areas/effect_snapshot_against_20260617_candidate_baseline/effect_comparison.json
```

对比结论：

```text
status=pass
case_count=19
fail_count=0
warn_count=0
path_identity_status=pass for all areas
```

说明：

- 对比启用 `--require-path-identity`，要求 `path_pixels.json` 内容哈希一致；
- `build_effect_snapshot.py` 对 formal baseline summary 中未直接记录 `final_path_pixels` 的区域，使用 `area_run_dir/path_pixels.json` 作为路径身份来源；
- 双方都缺失的扩展指标记为 `not_available`，不参与 warn；单边缺失仍保留 warn；
- 该回归守卫只证明重构未改变候选基线行为，不改变第 6 节对候选 mode 的定位。
