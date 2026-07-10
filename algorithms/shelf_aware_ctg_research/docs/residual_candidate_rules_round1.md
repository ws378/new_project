# D/E 第一轮：jump target 局部 context 与 residual candidate 判据

本文记录 `classify_residual_jump_targets.py` 的第一轮结果。该脚本只读取上一轮 residual grid-node 诊断输出，不改 planner。

## 输入

```text
algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008
```

前置要求：每个 area 已存在：

```text
<area>/diagnostics/residual_grid_nodes/jump_target_diagnostics.json
```

运行命令：

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 -m algorithms.shelf_aware_ctg_research.scripts.classify_residual_jump_targets   --run-dir algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008
```

## 输出

全局 summary：

```text
algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008/residual_candidate_rules_summary.json
```

每个 area 输出：

```text
<area>/diagnostics/residual_candidate_rules/residual_candidate_rules.json
<area>/diagnostics/residual_candidate_rules/01_jump_target_context_sheet.png
```

其中 context sheet 只在该 area 有 jump target 时生成。本轮 12 个 area 中 8 个 area 有 jump target，因此生成 8 张 context sheet。

## 第一版分类

当前规则只做研究候选分类，不代表可以直接删点。

```text
optional_by_overlap_high_confidence
optional_by_overlap_needs_review
optional_by_near_overlap_needs_review
snap_or_insert_candidate
boundary_sensitive_review
required_or_topology_review
```

### optional_by_overlap_high_confidence

条件：

- jump target 在实际清扫半径内；
- 同时命中 boundary / low degree / small local free area / unknown label 中至少一类。

含义：优先进入后续 pruning simulation，但仍需覆盖损失检查。

### optional_by_overlap_needs_review

条件：

- jump target 在实际清扫半径内；
- 但没有额外低价值证据。

含义：可能可跳过，但需要局部 context 和覆盖损失确认。

### optional_by_near_overlap_needs_review

条件：

- jump target 稍超出实际清扫半径；
- 同时命中 boundary / low degree / small local free area。

含义：不应直接删，适合研究 snap 或 insert。

### snap_or_insert_candidate

条件：

- target node 低 degree 或局部 free area 小；
- 但不满足 overlap / near-overlap。

含义：更适合吸附或插入已有路径，而不是直接删除。

### boundary_sensitive_review

条件：

- target node 靠近障碍或边界敏感；
- 但没有 overlap、低 degree、小面积等更强证据。

含义：需要人工看局部 context。

### required_or_topology_review

条件：

- 当前诊断没有发现低价值证据。

含义：不能作为 pruning 目标；可能是真实拓扑连接或正常换区。

## 全量结果

本轮覆盖 12 个 area，69 个 jump target。

全局分类：

```text
optional_by_overlap_high_confidence = 21
optional_by_overlap_needs_review = 10
optional_by_near_overlap_needs_review = 7
snap_or_insert_candidate = 3
boundary_sensitive_review = 5
required_or_topology_review = 23
```

如果只把 overlap 两类作为“可能可跳过”的候选：

```text
candidate_count = 31
avoidable_jump_length_upper_bound_m = 132.932
```

注意：这是理论上界，不是实际路径长度收益。跳过某个 target 后可能需要重连路径，也可能造成覆盖损失。

## 重点区域

### beiguo_lanshan_0407_area_6

```text
optional_by_overlap_high_confidence = 8
optional_by_overlap_needs_review = 6
optional_by_near_overlap_needs_review = 5
boundary_sensitive_review = 1
required_or_topology_review = 11
avoidable_jump_length_upper_bound_m = 40.323
```

结论：

- 该区域确实有一批 overlap target，适合做第一版 pruning simulation。
- 但仍有 11 个 target 进入 topology review，说明不能用简单 overlap 规则处理全部远跳。

### fourfloor_area_6

```text
required_or_topology_review = 1
avoidable_jump_length_upper_bound_m = 0.0
```

结论：

- 该区域的唯一长 jump 不满足 overlap / boundary / low-degree / small-area 证据。
- 它应作为反例保留，防止 pruning 规则误伤真实连接。

### fourfloor_area_7

```text
optional_by_overlap_high_confidence = 2
optional_by_near_overlap_needs_review = 1
boundary_sensitive_review = 1
required_or_topology_review = 1
avoidable_jump_length_upper_bound_m = 21.997
```

结论：

- 该区域适合验证 overlap pruning 和 near-overlap snap/insert 的区别。
- 最大长跳中有 overlap 候选，但仍需要看局部 context 和覆盖损失。

## 当前可信判断

1. 31 个 overlap 候选是后续第一版 pruning simulation 的合理输入。
2. 23 个 required/topology review 不能直接动，说明简单“跳远就删”的思路不成立。
3. `fourfloor_area_6` 是必要反例，应进入后续验收集。
4. 下一步应做 simulation，而不是直接改 planner。

## 下一步

进入 F 的研究版 simulation：

1. 只对 `optional_by_overlap_high_confidence` 和 `optional_by_overlap_needs_review` 做跳过模拟。
2. 估算可减少的 jump 段长度上界。
3. 用实际清扫半径估算 target 附近覆盖损失。
4. 输出 before/after 伪路径图，但不改 baseline path artifact。
