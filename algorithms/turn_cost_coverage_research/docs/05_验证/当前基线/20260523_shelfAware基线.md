# 20260523 shelfAware 基线

## 1. 基线身份

本基线用于后续所有 `turn_cost_coverage_research` 重构和实验对照。

```text
基线名称：shelfAware 覆盖路径基线
planner_mode：shelf_aware
基线提交：a9581b1 批量测试UI稳定版覆盖路径
基线输出：output/run_20260523_161642_160632_shelf_aware_all_areas
```

## 2. 基线行为

`shelf_aware` 的行为边界：

- 使用正式 `ShelfAwareCoveragePlanner` 生成路径。
- 使用 UI 保存参数或 UI 默认参数。
- 质量守卫只读诊断，不修改路径。
- CTG auxiliary 失败时，记录 warning 并降级为不带 CTG 继续运行。
- 不使用 `turn_cost_coverage_research` 的后处理优化结果。

## 3. 批量测试范围

项目：

- `beiguo_lanshan_1770397756`
- `beiguoshangcheng_floor_3`
- `fourfloor_20250923_8`

区域数：`19`

输出：

- `summary.json`
- `shelfAware批量区域指标.csv`
- `全部最终shelf_aware_coverage/`

## 4. 汇总指标

| 指标 | 最小值 | 最大值 | 平均值 |
| --- | ---: | ---: | ---: |
| coverage_ratio | 0.9905723171780789 | 1.0 | 0.9965843781289876 |
| long_jump_count | 0 | 30 | 7.0 |
| infeasible_segment_count | 1 | 771 | 96.89473684210526 |
| total_turn_angle_deg | 419.7484006603189 | 56483.95311453724 | 13819.647557492686 |
| length_px | 227.29652504131224 | 32492.870057735476 | 10514.99636117514 |

## 5. Warning 统计

- `infeasible_segment_detected`：19 个区域。
- `long_jump_detected`：16 个区域。

## 6. CTG auxiliary 降级区域

| 项目 | 区域 | 降级原因 |
| --- | ---: | --- |
| beiguoshangcheng_floor_3 | 8 | edge 5 path too short |
| beiguoshangcheng_floor_3 | 16 | edge 6 path too short |

## 7. 优先人工复核区域

低覆盖率优先复核：

- `beiguoshangcheng_floor_3 area3`：`0.9905723171780789`
- `beiguoshangcheng_floor_3 area8`：`0.9911721757599894`
- `beiguo_lanshan_1770397756 area1`：`0.9919075994997425`
- `beiguoshangcheng_floor_3 area6`：`0.9923174692839994`
- `beiguo_lanshan_1770397756 area6`：`0.992988508202324`
- `fourfloor_20250923_8 area6`：`0.9933078008466035`

高不可行段优先复核：

- `beiguo_lanshan_1770397756 area6`：`771`
- `beiguo_lanshan_1770397756 area1`：`257`
- `beiguo_lanshan_1770397756 area4`：`141`
- `beiguoshangcheng_floor_3 area5`：`136`
- `beiguoshangcheng_floor_3 area7`：`127`

## 8. 基线结论

该基线是当前保守正式基线，可作为 `shelf_aware_turn_cost` 的对照基线。

但它不能被写成“已完全解决路径质量问题”：

- 所有区域仍有不可行段 warning。
- 大多数区域仍有长跳 warning。
- 后续若继续算法研究，必须与本基线对比，而不是与历史任意 run 对比。

## 9. 禁止事项

- 不得把历史 batch reconnect 输出作为新基线。
- 不得把 area5 局部最优结果宣传成全局稳定结果。
- 不得修改本基线输出目录后继续称为同一基线。
- 不得在未跑完 19 区域前宣布新版本优于本基线。

## 10. 重构后复核

2026-05-23 完成脚本入口分层重构后，使用 canonical baseline 入口重新跑完整 19 区域：

```text
入口：scripts/baseline/run_shelf_aware_all_areas.py
输出：output/baselines/run_20260523_170339_960022_shelf_aware_all_areas
```

复核结果：

- 区域数：`19`
- 成功：`19`
- 失败：`0`
- coverage_ratio 最小值：`0.9905723171780789`
- coverage_ratio 平均值：`0.9965843781289875`
- coverage_ratio 最大值：`1.0`

结论：

- 入口分层重构没有改变 UI stable 基线行为。
- 后续新基线输出统一放在 `output/baselines/` 下。
