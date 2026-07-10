# 下一步研究算法参考：全局语义、方向辅助与网格节点质量

本文记录当前阶段对后续研究方向的判断。重点不是继续组合新算法，而是明确 `shelf_aware_guarded` 当前缺什么、`territory / axis 辅助信息` 能提供什么、以及更值得优先优化的模块。

## 背景判断

当前更可靠的方向是：

```text
保留 shelf_aware_guarded 作为主体规划器
CTG / territory / axis 只提供全局语义、拓扑证据和方向辅助
不要让 axis 辅助信息 接管局部细节规划
```

原因：

- `shelf_aware_guarded` 对货架、墙边、局部边界细节表现更好。
- 直接使用 axis 辅助信息 替代 baseline local direction 后，部分区域路径变长或更不稳定。
- CTG 当前的 edge 粒度可能过碎，直接作为硬约束风险较大。
- 当前更明显的问题可能不在方向，而在覆盖网格节点质量和残留点处理。

## 1. expanded territory 应先作为全局语义输入

`shelf_aware_guarded` 当前缺少全局信息。它主要基于旋转后的局部网格、局部方向和能量搜索做决策，不知道：

- 当前点属于哪条通道/边；
- 当前点是否位于路口；
- 当前候选点是否仍在同一通道；
- fallback 是正常换区，还是跨很远跳转；
- 远处未覆盖点是重要区域，还是小凸起/边界噪声导致的低价值残留。

`territory / axis 辅助信息` 可以提供的第一类价值，不应该是直接提供 sweep 方向，而是提供全局语义 label。

建议抽象成：

```text
territory_label_map:
  -1 = junction / unknown / connector
   0..N = edge territory

territory_type_map:
  edge / junction / unknown / connector

edge metadata:
  edge_id
  edge_type
  incident_nodes
  approximate_axis
  territory_area
  territory_pixel_count
```

使用方式可以分阶段：

1. 先用于诊断：给 path 点染色，观察路径在哪些 edge 之间切换。
2. 再用于 fallback 判断：区分正常换通道和异常远跳。
3. 最后再考虑进入能量函数，作为轻量 soft prior。

注意：`territory_pixels` / expanded territory 是归属证据，不是绝对真值。不能直接把它等价为必须覆盖分区或强制顺序。

## 2. axis_map 和 local_direction_map 的关系

`axis_map / confidence_map` 和 `shelf_aware_guarded` 的 `local_direction_map / confidence` 本质上都表达：

```text
某个位置偏好的无向行走轴方向
```

但它们来源不同，适用边界也不同。

### baseline local_direction_map

来源：图像边界。

特点：

- 来自 Canny / Sobel / structure tensor。
- 对货架、墙边、局部边界方向敏感。
- 能反映局部细节。
- 受边界噪声影响。

适合回答：

```text
这个像素附近更适合沿哪个局部方向走？
```

### CTG axis_map

来源：CTG edge 的 `outer_path_rc` 和 expanded territory。

特点：

- 是通道级、拓扑级方向。
- 表达某条 edge / 通道的大致方向。
- 不理解局部货架边界细节。
- 依赖 CTG 图质量和 edge 粒度。
- 方向是 180 度无向语义，左右同义、上下同义。

适合回答：

```text
这个区域大致属于哪条通道？这条通道的大方向是什么？
```

### 不应平级替代

当前 axis 辅助信息 的问题之一是：传入 external axis 后，planner 会用它替代 baseline image-gradient local direction。这样会丢失 baseline 的局部细节优势。

后续更合理的融合思路：

```text
如果 axis confidence 高，且 local confidence 低：
  axis 可以补足方向

如果 axis 和 local 一致：
  提高方向 confidence

如果 axis 和 local 冲突：
  优先 local，降低 axis 权重

如果在 junction / unknown / connector：
  axis confidence = 0
```

也就是说，axis 应该帮助 local direction 不可靠的区域，而不是覆盖 local direction 已经做得好的区域。

## 3. 覆盖网格节点一次性生成带来的问题

当前 `shelf_aware_guarded` 的覆盖网格节点是在规划前一次性生成的：

```text
rotated_room_map
  -> build_nodes()
  -> 固定节点集合
  -> 搜索时只能访问这些节点
```

后续不会动态删除、合并、移动节点。

这会带来一个关键问题：

```text
小凸出 free 区 / 边界毛刺 / 很窄的局部凸起
  -> 生成一个孤立或半孤立网格点
  -> 该点覆盖价值低
  -> 但算法仍把它当作必须访问节点
  -> 可能为了它产生远跳、回头或绕行
```

这种问题不是单纯调能量函数能稳定解决的，因为候选空间本身已经包含了质量较差的节点。

后续更值得研究 `grid node refinement`：

- 删除覆盖收益很低的孤立节点；
- 将贴边小凸起节点吸附到附近主通道节点；
- 合并距离过近、覆盖区域高度重叠的节点；
- 对 degree 很低、area contribution 很小的节点标记为 optional；
- 对 junction / connector 区节点降低“必须覆盖”语义；
- 将 territory label 用于判断节点属于主通道、路口还是边界残留。

这类优化属于 `shelf_aware_guarded` 的模块级优化，比直接做 axis 融合更基础。

## 4. 远距离跳转连接少量未覆盖点的问题

当前算法经常会出现：

```text
大部分区域已经覆盖
剩余一个或少量未访问节点
global fallback 为了这些点产生长距离跳转
```

这类行为在指标上会增加路径长度，在实际机器人执行中也不自然。

问题根因：

- 当前所有可访问网格节点都被视为必须访问。
- 算法没有区分“高价值未覆盖区域”和“低价值残留点”。
- 实际机器人清扫宽度通常大于设置的覆盖宽度，路径之间有重叠余量。
- 少量边界残留点可能已经被实际清扫宽度覆盖，不值得专门跳过去。

后续可以引入 coverage tolerance：

```text
实际清扫宽度 > nominal coverage_width
允许一定覆盖冗余
距离已有路径足够近的小残留点可以认为已覆盖
```

可能处理方式分三类。

### A. 删除残留节点

如果未访问节点满足：

```text
距离已有路径 < 实际清扫半径或覆盖冗余阈值
自身代表的 free area 很小
不是关键连接点
不在重要通道中心
```

则可以认为它已经被覆盖，不再强制访问。

### B. 调整残留节点位置

如果残留节点来自小凸起或边界毛刺，可以把它吸附到附近更好连接的位置，例如：

- 同 cell 内更靠近主路径的位置；
- 同 territory 内更靠近主通道轴的位置；
- 距离障碍更安全的位置；
- 与邻居连接更自然的位置。

### C. 插入到已有路径

如果残留点附近已有路径经过，不应从当前路径尾部远跳过去。可以考虑：

```text
找到历史路径中距离残留点最近的 segment
在该 segment 附近插入一个局部小绕行
然后继续原路径
```

这比 global fallback 到路径尾部更自然。

## 5. 后续优先级建议

基于当前问题，后续研究优先级建议调整为：

```text
第一优先级：网格节点质量诊断
  识别低价值残留点、孤立点、小凸起点、边界毛刺点。

第二优先级：残留点处理
  删除 / 吸附 / 插入，而不是让 global fallback 远跳。

第三优先级：expanded territory 作为全局 label
  用于判断节点属于哪个通道、是否在路口、跳转是否合理。

第四优先级：axis/local direction 融合
  只在 local direction 不可靠时补充，不替代 baseline。
```

当前最值得做的模块不是 axis 融合，而是：

```text
覆盖网格节点生成与残留点处理
```

这是更独立、更容易验证、也更可能直接改善路径质量的模块级优化方向。

## 6. 建议的下一步诊断输出

在真正改算法前，建议先做诊断可视化，至少包括：

1. 网格节点图：标出节点 degree、是否 obstacle、是否 visited。
2. 节点按 territory label 着色。
3. 未访问节点 / 最后访问节点 / fallback 跳转段高亮。
4. 每个节点的局部 coverage contribution 估计。
5. 距离已有路径小于实际清扫半径的残留节点高亮。
6. 小凸起区域导致的节点单独标出。
7. path segment 与 jump segment 分开显示。

目标是先回答：

```text
远跳到底是为了哪些点？
这些点是否真的需要覆盖？
它们来自真实区域，还是边界/网格生成副作用？
能否通过删点、吸附或插入解决？
```

只有这些问题可视化清楚后，再决定是否进入算法实现。
