# shelf_aware_guarded 与 axis prior 对比分析

本文记录当前研究阶段的实际结论和后续边界。重点不是提出新算法，而是说明：baseline 为什么强、axis prior 为什么不稳定、CTG 现在适合提供什么证据。

## 对比对象

当前研究 runner 中有三个变体：

1. `baseline`
   - 原始 `shelf_aware_guarded`。
   - 使用全局主方向旋转 + image-gradient local direction。

2. `axis_prior`
   - 将 CTG territory direction grid 转成 `axis_map/confidence_map`。
   - 传入 `ShelfAwareCoveragePlanner.plan()`。
   - 在 planner 内部替代 baseline 的 image-gradient local direction。

3. `ctg_guided`
   - 保守研究变体。
   - 当前不使用 axis map 接管方向。
   - 只传入 edge label map，给 same-edge / edge-switch 一个很轻的能量项。
   - 该变体只是接口骨架，不代表最终组合方案。

## 已有测试结果概览

主要输出目录：

```text
algorithms/territory_seed_research/output/run_20260505_174408_692387
```

关键结果：

```text
beiguo_lanshan_0407_area_1: baseline=1370 axis=1334 ctg=1351 ctg_len_delta=-15.702
beiguo_lanshan_0407_area_2: baseline=328  axis=340  ctg=328  ctg_len_delta=0.000
beiguo_lanshan_0407_area_3: baseline=460  axis=470  ctg=460  ctg_len_delta=0.000
beiguo_lanshan_0407_area_4: baseline=1293 axis=1307 ctg=1242 ctg_len_delta=-15.041
beiguo_lanshan_0407_area_5: baseline=646  axis=630  ctg=648  ctg_len_delta=-2.495
beiguo_lanshan_0407_area_6: baseline=2922 axis=2986 ctg=2963 ctg_len_delta=18.451

fourfloor_area_2: baseline=46 axis=46  ctg=46  ctg_len_delta=0.000
fourfloor_area_3: baseline=42 axis=42  ctg=42  ctg_len_delta=0.000
fourfloor_area_4: baseline=33 axis=33  ctg=33  ctg_len_delta=0.000
fourfloor_area_5: baseline=69 axis=69  ctg=69  ctg_len_delta=0.000
fourfloor_area_6: baseline=395 axis=400 ctg=395 ctg_len_delta=0.000
fourfloor_area_7: baseline=322 axis=345 ctg=321 ctg_len_delta=-0.253
```

注意：点数和路径长度不是唯一评价标准，只能作为初步信号。真正判断仍要看路径可视化。

## 图结构差异

同一轮测试中，CTG 图规模差异很大：

```text
fourfloor_area_2~6: 大多 nodes=2 edges=1
fourfloor_area_7: nodes=6 edges=5

beiguo_lanshan_0407_area_1: nodes=36 edges=57
beiguo_lanshan_0407_area_6: nodes=76 edges=114
```

这说明：

- fourfloor 多数区域 CTG 退化成单 edge，CTG-guided 很难带来可见变化。
- beiguo_lanshan_0407_area_1/6 的 CTG 很碎，直接使用原始 edge label 容易把全局覆盖问题拆成很多局部碎边问题。

因此，不能简单说“CTG 引导有效/无效”。必须先看 CTG 的粒度是否适合作为 planner 约束。

## baseline 表现好的原因

1. **保留局部边界信息**
   - baseline 的 local direction 来自边界梯度和 structure tensor。
   - 对货架、墙边、局部通道边界更敏感。

2. **全局旋转 + 局部方向结合**
   - 全局主方向提供基本规整性。
   - local direction 处理局部细节。

3. **revisit / fallback 保证覆盖继续**
   - 小路口可以自然重复通过。
   - 遇到局部死路后可以跳到未访问区域。

4. **没有被 CTG 碎边过度约束**
   - 在 CTG 过碎时，baseline 反而更稳。

## axis_prior 不稳定的原因

1. **替代了 baseline local direction**
   - axis prior 传入 external axis 后，planner 使用 `external_axis` 作为 local direction source。
   - 这会丢掉 baseline 的 image-gradient 细节优势。

2. **axis 是通道级，不是像素级**
   - axis 来自 edge outer path。
   - 它回答“这条通道大致方向是什么”，不回答“这个像素附近怎么绕边界”。

3. **junction 没有唯一方向**
   - 路口区可能需要重复通过、掉头或作为 connector。
   - 对路口硬给 axis 会制造错误偏好。

4. **CTG edge 可能过碎或受边界噪声影响**
   - 边界凹凸会影响 skeleton 和 edge 切分。
   - 如果 edge 粒度不稳定，axis 也会不稳定。

5. **axis 是 180 度无向语义**
   - 水平表示左右同义，垂直表示上下同义。
   - 真正走向必须依赖上一段路径 heading。

## 当前 CTG-guided 研究变体的实际含义

当前 `ctg_guided` 只做了非常薄的一层：

```text
baseline local direction
+ edge label same-edge reward
+ edge switch penalty
+ fallback edge switch extra penalty
```

它没有实现：

- CTG graph-distance jump penalty。
- edge residual leave penalty。
- axis/local direction 一致性增强和冲突降权。
- junction 分类。
- corridor group 合并。
- 路径点后处理优化。

所以它只能说明接口可以接入，不能说明完整 CTG-guided 策略成立。

## 当前更可靠的结论

1. `shelf_aware_guarded` 应该继续作为主体规划器。
2. axis prior 不应该直接替代 baseline local direction。
3. CTG/axis 更适合提供拓扑证据，而不是细节规划。
4. 原始 CTG edge label 是否可用，取决于图粒度；图太碎时需要先考虑 corridor group 或只用于诊断。
5. 路口区应从普通覆盖区语义降级，更像 connector/transition zone。
6. 下一步若继续研究，应先做全局诊断可视化，而不是继续加能量项。

## 建议的后续模块级切入点

这些是更适合逐个模块优化的方向：

1. **路径点后处理**
   - 连续同向点合并。
   - 同一 segment 内平滑。
   - jump segment 与 sweep segment 分开标识。
   - 掉头点保留，不被误删。

2. **全局诊断可视化**
   - path 点按 CTG edge label 着色。
   - 标出 edge switch 序列。
   - 标出 global fallback 跳转位置。
   - 标出路径穿越 junction polygon 的位置。

3. **CTG 粒度诊断**
   - 统计 edge 长度、degree、territory 面积。
   - 识别过碎 edge。
   - 判断是否需要 corridor group，而不是直接用原始 edge。

4. **axis 与 baseline direction 对齐诊断**
   - 可视化 baseline local direction 与 CTG axis 的夹角。
   - 一致区、冲突区、低 confidence 区分开显示。
   - 先诊断，再决定是否融合。

## 推荐阅读顺序

1. `shelf_aware_guarded_flow.md`
2. `axis_prior_flow.md`
3. 本文档

读完后，再看具体区域的 `13_shelf_aware_ctg_guided_comparison.png`，避免只从指标判断路径好坏。
