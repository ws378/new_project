# F 第一轮：overlap jump target pruning simulation

本文记录 `simulate_residual_pruning.py` 的第一轮结果。该脚本只做后处理模拟，不修改 baseline path artifact，不改正式 planner。

## 输入

```text
algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008
```

前置要求：每个 area 已存在：

```text
<area>/diagnostics/residual_candidate_rules/residual_candidate_rules.json
```

运行命令：

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 -m algorithms.shelf_aware_ctg_research.scripts.simulate_residual_pruning   --run-dir algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008
```

## 模拟方法

本轮只模拟两类候选：

```text
optional_by_overlap_high_confidence
optional_by_overlap_needs_review
```

做法：

1. 找到候选 jump target 对应的 path index。
2. 在模拟 path 中删除这些 target point。
3. 重新计算折线路径长度。
4. 在 target 附近用实际清扫半径估算局部 free pixel 是否仍被 simulated path 覆盖。
5. 输出 overlay 和 JSON。

这不是正式路径优化。它没有重新规划局部连接，也没有做完整 swept-area 覆盖验证。

## 输出

全局 summary：

```text
algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008/pruning_simulation_summary.json
```

每个 area 输出：

```text
<area>/diagnostics/pruning_simulation/pruning_simulation.json
<area>/diagnostics/pruning_simulation/01_overlap_pruning_simulation_overlay.png
```

## 全局结果

```text
candidate_count = 31
low_coverage_risk_candidate_count = 23
simulated_length_delta_m = -19.077
```

解释：

- 31 个 overlap 候选中，23 个在当前局部风险估计下覆盖风险较低。
- 直接删除 target point 的路径长度估计只减少约 19.08m。
- 这个数明显小于上一轮 `avoidable_jump_length_upper_bound_m = 132.932m`。

因此，jump 长度上界不能当真实收益。实际收益取决于删除 target 后如何重连前后路径，以及是否需要局部补扫。

## 重点区域

### beiguo_lanshan_0407_area_6

```text
candidate_count = 14
low_coverage_risk_candidate_count = 8
simulated_length_delta_m = -7.906
```

结论：

- area_6 有 overlap 候选，但不是全部低风险。
- 第一版 pruning 不能简单全删；需要按 coverage risk 分层。

### fourfloor_area_6

```text
candidate_count = 0
low_coverage_risk_candidate_count = 0
simulated_length_delta_m = 0.000
```

结论：

- 该区域继续作为反例保留。
- 唯一长 jump 没有进入 overlap pruning 候选，符合预期。

### fourfloor_area_7

```text
candidate_count = 2
low_coverage_risk_candidate_count = 1
simulated_length_delta_m = -0.243
```

结论：

- 虽然存在 overlap target，但简单删除点的路径长度收益很小。
- 该区域更可能需要局部路径重连或 snap/insert，而不是单点删除。

## 当前可信判断

1. overlap target 确实是一个可研究方向，但不能直接等价于删除节点。
2. 局部覆盖风险能筛掉一部分 overlap 候选。
3. 简单删除 path point 的收益有限，说明真正要做的是 fallback 前决策或局部重连，而不是事后粗删。
4. `fourfloor_area_6` 继续证明：长 jump 不一定是残留低价值点。

## 下一步

下一批不应直接进正式 planner。建议继续做研究版：

1. 对低风险 overlap candidate 做局部 reconnect simulation。
2. 对 near-overlap / snap_or_insert candidate 做吸附点搜索。
3. 输出 before/after 局部路径 context，而不是只看全局长度。
