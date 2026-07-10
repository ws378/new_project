# B/C/D 第一轮诊断结论：baseline 路径、网格节点质量与远跳

本文记录第一轮 B/C/D 诊断结果。该轮只分析 `shelf_aware_guarded` baseline 路径；axis / territory 只作为辅助图层，不再分析独立 axis 路径。

## 输入与脚本

基线 run：

```text
algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008
```

诊断脚本：

```bash
python3 -m algorithms.shelf_aware_ctg_research.scripts.diagnose_path_grid_jumps   --run-dir algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008
```

诊断输出汇总：

```text
algorithms/shelf_aware_ctg_research/output/run_20260505_185541_861008/path_grid_jump_diagnostics_summary.json
```

每个 area 输出：

```text
<area>/diagnostics/path_grid_jumps/00_territory_label_context.png
<area>/diagnostics/path_grid_jumps/area_diagnostics.json
<area>/diagnostics/path_grid_jumps/shelf_aware_baseline/01_path_by_territory.png
<area>/diagnostics/path_grid_jumps/shelf_aware_baseline/02_grid_node_quality.png
<area>/diagnostics/path_grid_jumps/shelf_aware_baseline/03_jump_overlay.png
<area>/diagnostics/path_grid_jumps/shelf_aware_baseline/diagnostics.json
```

## 诊断覆盖范围

1. **B：path + territory 全局诊断**
   - baseline 路径点按 expanded territory label 着色。
   - 统计路径中 territory label 切换次数。
   - 显示 label=-1 的 junction/unknown/connector 区。

2. **C：grid node 质量诊断**
   - 从 planner `energy_debug.csv` 读取所有可访问网格节点。
   - 统计节点是否靠近障碍、是否在 unknown label、是否 obstacle-neighbor 较多。
   - 输出 `02_grid_node_quality.png`。

3. **D：jump / 远跳诊断**
   - 读取 `path_jump_segments_pixels.json`。
   - 统计 jump 数量、长跳数量、最大跳转长度。
   - 判断 jump 目标是否落在实际清扫宽度 overlap 半径内。
   - 判断 jump 目标最近网格节点是否属于边界敏感节点。

默认实际清扫宽度假设：

```text
actual_clean_width_m = 0.70
nominal coverage_width_m = 0.55
```

## 全局数字：baseline

```text
shelf_aware_baseline:
  jump_count = 69
  long_jump_count_ge_2m = 50
  edge_switch_count = 1174
  jump_targets_within_overlap_radius = 31
  boundary_sensitive_jump_targets = 25
```

可见：

- baseline 远跳是真问题，不是个别区域偶然现象。
- 很多 jump 目标落在 overlap 半径内，说明存在“为了可能已被实际清扫宽度覆盖的点而跳转”的情况。
- 不少 jump 目标靠近边界敏感节点，说明远跳与网格节点质量/边界细节有关。

## 代表区域结论

### beiguo_lanshan_0407_area_6

CTG 图规模：

```text
nodes=76, edges=114
```

baseline 诊断结果：

```text
path_points=2922
edge_switch_count=675
jump_count=31
long_jump_count_ge_2m=22
max_jump_length_m=38.99
boundary_sensitive_node_ratio=0.286
jump_targets_within_overlap_radius=14
boundary_sensitive_jump_targets=9
```

可信结论：

- 该区域 CTG edge 很碎，path-by-territory 会产生大量 label 切换。
- 原始 edge label 只能作为诊断证据，不能直接作为强规划约束。
- 远跳目标中有相当一部分落在 overlap 半径内或边界敏感节点附近，支持“残留点/边界节点质量问题值得优先研究”。

### beiguo_lanshan_0407_area_4

CTG 图规模：

```text
nodes=10, edges=12
```

baseline 诊断结果：

```text
edge_switch_count=138
jump_count=8
long_jump_count_ge_2m=7
boundary_sensitive_node_ratio=0.424
jump_targets_within_overlap_radius=4
boundary_sensitive_jump_targets=4
```

可信结论：

- 网格节点中边界敏感比例较高。
- jump 目标与 overlap / 边界敏感区域有明显关联。

### fourfloor_area_7

CTG 图规模：

```text
nodes=6, edges=5
```

baseline 诊断结果：

```text
edge_switch_count=19
jump_count=5
long_jump_count_ge_2m=4
max_jump_length_m=18.25
boundary_sensitive_node_ratio=0.119
jump_targets_within_overlap_radius=2
boundary_sensitive_jump_targets=2
```

可信结论：

- 小型多分支区域也会出现长跳。
- 该问题不只来自 CTG 过碎，也与 fallback 和残留节点处理有关。

### fourfloor_area_2~5

诊断结果基本为：

```text
edge_switch_count=0
jump_count=0
```

可信结论：

- 这些区域适合作为“无复杂拓扑时不能破坏 baseline”的回归样例。
- 不适合作为 CTG 辅助能力的主分析样例。

## 目前可以相信的判断

1. **远跳是真问题。**
   - baseline 有 69 个 jump，其中 50 个超过 2m。

2. **部分 jump 目标可能不值得专门跳过去。**
   - baseline 有 31 个 jump 目标落在实际清扫 overlap 半径内。
   - 这支持后续研究“残留点可选化 / overlap 覆盖容忍”。

3. **边界敏感节点与 jump 有关联。**
   - baseline 有 25 个 jump target 靠近边界敏感节点。
   - 这支持后续研究 grid node refinement，而不是只调路径能量。

4. **CTG 原始 edge label 在复杂区域可能过碎。**
   - `beiguo_lanshan_0407_area_6` 有 76 nodes / 114 edges，baseline 路径 label 切换 600+ 次。
   - 原始 edge label 应先用于诊断，不宜直接强约束规划。

## 还不能下的结论

1. 不能直接说哪些具体 jump 可以删除。
2. 不能证明 grid node pruning 一定安全。
3. 不能证明 CTG label 应直接进 energy。
4. 还需要结合覆盖贡献、局部 free area、是否连接其他区域等判据。

## 下一步建议

下一步继续围绕 baseline 网格节点和残留点做模块级研究：

1. 对 jump target 附近生成局部 context 图，显示：
   - 最近 path segment；
   - 最近 grid node；
   - free/obstacle 形态；
   - territory label；
   - overlap 半径。

2. 对每个 grid node 估计 coverage contribution：
   - cell 内 free pixel 数；
   - 与已有路径覆盖圆盘/条带的重叠比例；
   - 是否位于边界毛刺或小凸起。

3. 形成节点分类，而不是直接删点：

```text
required
optional_by_overlap
optional_by_boundary
snap_candidate
insert_candidate
```

4. 先在诊断层模拟 optional node，不改 planner：
   - 如果跳过这些点，路径长度减少多少；
   - 估计覆盖损失多少；
   - 哪些区域最受益。
