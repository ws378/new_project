# F 第二轮：local reconnect / snap simulation

本文记录 `simulate_local_reconnect_snap.py` 的第一轮结果。该脚本仍然只做研究诊断，不修改 baseline，不改正式 planner。

## 输入

```text
algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008
```

前置要求：已生成：

```text
<area>/diagnostics/residual_candidate_rules/residual_candidate_rules.json
<area>/diagnostics/pruning_simulation/pruning_simulation.json
```

运行命令：

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 -m algorithms.shelf_aware_ctg_research.scripts.simulate_local_reconnect_snap   --run-dir algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008
```

## 评估内容

### reconnect

针对：

```text
optional_by_overlap_high_confidence
optional_by_overlap_needs_review
```

检查删除 target point 后，前一个 path point 和后一个 path point 的直连线是否完全落在 free mask 内，同时结合上一轮 local coverage risk。

输出 verdict：

```text
reconnect_ready
reconnect_blocked
coverage_risk_review
```

### snap

针对：

```text
optional_by_near_overlap_needs_review
snap_or_insert_candidate
```

查找 jump target 到跳转前已有 path segment 的最近投影点，判断距离是否在 snap 阈值内、target 到投影点连线是否 free。

输出 verdict：

```text
snap_ready
snap_connector_blocked
snap_too_far
```

## 输出

全局 summary：

```text
algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008/local_reconnect_snap_summary.json
```

每个 area 输出：

```text
<area>/diagnostics/local_reconnect_snap/local_reconnect_snap.json
<area>/diagnostics/local_reconnect_snap/01_reconnect_snap_overlay.png
```

## 全局结果

reconnect：

```text
coverage_risk_review = 3
reconnect_blocked = 27
reconnect_ready = 1
```

snap：

```text
snap_connector_blocked = 8
snap_ready = 1
snap_too_far = 1
```

## 重点区域

### beiguo_lanshan_0407_area_6

```text
reconnect candidates = 14
coverage_risk_review = 3
reconnect_blocked = 10
reconnect_ready = 1

snap candidates = 5
snap_connector_blocked = 4
snap_ready = 1
```

结论：

- area_6 中 overlap target 很多，但大多数不能通过简单前后点直连处理。
- 只有 1 个 reconnect_ready，说明简单 post-process pruning 不适合作为第一版优化主体。

### fourfloor_area_6

```text
reconnect candidates = 0
snap candidates = 0
```

结论：

- 该区域继续作为反例，说明它的长 jump 不属于当前 residual pruning 范围。

### fourfloor_area_7

```text
reconnect candidates = 2
reconnect_blocked = 2

snap candidates = 1
snap_connector_blocked = 1
```

结论：

- fourfloor_area_7 的 overlap target 也不能靠简单直连删除。
- 该区域更适合研究 fallback 前是否避免跳转，或局部绕行插入，而不是事后删点。

## 当前可信判断

1. 简单删除 overlap target 并直连前后路径，大多数情况下不可行。
2. overlap 证据仍有价值，但更适合进入 fallback 前决策：如果 target 已在实际清扫半径内，就不要把它作为 global fallback 目标。
3. near-overlap / snap 类目标也不能简单吸附，connector 经常被 obstacle/free 约束阻挡。
4. 下一版优化不应做纯后处理删点，应优先在 planner 的 fallback target 选择前增加 optional 判断，或在研究层重放 fallback 决策。

## 下一步

建议进入“fallback target 选择模拟”：

1. 读取 jump target 顺序。
2. 当 fallback 候选属于 low-risk overlap target 时，模拟跳过该候选，选择下一个未覆盖目标。
3. 估算 jump 数、长 jump 数和局部 coverage risk。
4. 只在研究脚本内做，不改正式 planner。
