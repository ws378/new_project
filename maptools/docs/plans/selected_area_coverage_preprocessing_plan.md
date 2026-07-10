# 所选区域覆盖预处理与阻塞层参数化方案

## 目标

覆盖路径生成只针对当前所选区域内的有效自由空间。预处理输入必须先被区域真值约束，区域外和区域边界外在本轮规划中都视为不可用，不能让算法看到整图自由空间。

## 正式公式

```text
selected_area_free_mask =
    region_mask
    AND map_free
    AND NOT block_mask(coverage_blocking_policy)
```

- `region_mask`：当前 AreaLabel 的多边形栅格化结果，是硬边界。
- `map_free`：底图/编辑层中真实自由空间，未知区和障碍物默认不是自由。
- `block_mask`：由覆盖阻塞策略决定的业务排除层。

## 阻塞策略

默认覆盖阻塞策略：

```text
block_forbidden_zone = true
block_virtual_wall = true
block_no_coverage = true
block_pass_only = false
```

含义：

- `forbidden_zone`：禁止区，不参与覆盖规划。
- `virtual_wall`：虚拟墙，作为本轮局部障碍线。
- `no_coverage`：不规划覆盖区，从可覆盖自由空间中扣除。
- `pass_only`：只通行语义，不默认扣除覆盖自由空间。

## 预处理顺序

1. 从地图和编辑层生成 `map_free`。
2. 按 `coverage_blocking_policy` 扣除业务阻塞层，得到 `total_free_map`。
3. 根据当前所选区域生成 `region_mask`。
4. 在进入形态学预处理前执行：`raw_map = total_free_map AND region_mask`。
5. 对这个区域内 raw_map 执行开运算、障碍物膨胀和小自由岛清理。
6. request 中仍保留 `region_mask` 和 `region_polygon_px`，作为下游二次校验与 artifact 记录。

## 验收用例

- `preprocess_total_map(region_mask=...)` 后区域外必须为障碍。
- 区域边界外不能因为整图自由空间而参与形态学连通。
- `block_no_coverage=false` 时 no_coverage 不扣除自由空间。
- 默认策略下 no_coverage 和派生 no_coverage 均扣除自由空间。
- `block_pass_only=false` 时 pass_only 不扣除自由空间。
- GUI 生成覆盖路径时，传入 planner 的 `prepared_map` 已经是区域内预处理结果。
- coverage repo 自动补路径时使用同一预处理顺序。
