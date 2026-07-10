# Territory Node Semantics 研究方案

## 目标

本方案只讨论如何把 `territory / junction / node quality` 信息提供给 `shelf_aware_guarded`，暂不使用 `axis_map / confidence_map`。

核心目标不是做新 planner，也不是用 CTG 接管覆盖路径，而是为 `shelf_aware_guarded` 的每个 grid node 建立统一语义：

```text
空间归属 -> 覆盖责任 -> 连通价值 -> 搜索/回退/残留处理决策
```

这里的英文变量和中文含义：

- `grid node`：覆盖网格节点，`shelf_aware_guarded` 内部 `build_nodes()` 生成的覆盖候选点。
- `territory_label`：势力范围标签，表示 node footprint 主要属于哪条 CTG edge 的 expanded territory。
- `junction_label` / `junction_id`：路口标签，来自 junction polygon，不等价于 `territory_label < 0`。
- `unknown`：既不属于明确 edge territory，也不属于 junction polygon 的 free 像素区域。
- `footprint`：节点代表的局部覆盖窗口，用于统计这个节点周围 free 像素属于 edge、junction 还是 unknown。
- `coverage_obligation`：覆盖责任，0~1，表示这个节点对覆盖质量有多重要。
- `connectivity_value`：连通价值，0~1，表示这个节点对通行、换区、路口过渡、重复访问有多重要。
- `node_role`：节点角色，是 `coverage_obligation` 和 `connectivity_value` 的离散化结果。

## 不做什么

第一版明确不做：

```text
不使用 axis_map / confidence_map
不删除 grid node
不把 node 预置为 visited
不破坏 neighbors 邻接关系
不把 junction 简化为 territory_label < 0
不强制 edge 顺序
不做 corridor group
不做 snap / insert
不改正式 shelf_aware_guarded 搜索逻辑
```

之前 `required-only optionalization` 把 optional node 直接设成 visited，这个实现语义不正确，不能作为本方案依据。

## 1. 输入

每个 area 需要以下输入：

```text
1. free_mask
   CTG geometry preparation 后的可通行区域。

2. expanded territory label map
   expanded territory 的 edge 势力范围标签。
   label >= 0 表示 edge territory。
   label < 0 表示没有明确 edge 归属，但不自动等价为 junction。

3. junction polygon list
   来自 CTG graph nodes 的 polygon_vertices_rc。
   这些 polygon 才是 junction_label / junction_id 的来源。

4. shelf_aware baseline node debug
   来自 shelf_aware_baseline/run_*/node_debug_enriched.json。
   这是真正由 shelf_aware_guarded 生成的 grid nodes。
```

## 2. node footprint 空间归属统计

不能只用 node 中心点采样空间语义。一个 node 可能部分落在 edge territory，部分落在 junction，部分落在 unknown。正确做法是统计 footprint。

对每个 node：

```text
footprint = 以 node.center_pixel 为中心的局部窗口
窗口半径默认 = coverage_width_px * 0.5
```

统计时：

```text
排除 obstacle 像素
只统计 free_mask > 0 的像素
```

对 footprint 内每个 free 像素统计：

```text
territory_count_by_label[label] += 1   # label >= 0
junction_count_by_id[junction_id] += 1 # junction polygon 内
unknown_count += 1                     # 既非 territory，也非 junction
free_count += 1
```

然后计算比例：

```text
territory_ratio = max(territory_count_by_label) / free_count
junction_ratio = max(junction_count_by_id) / free_count
unknown_ratio = unknown_count / free_count
```

如果一个 node 同时落到 territory 和 junction：

```text
比较排除 obstacle 后的 free 像素点数
占比最高者作为 primary_space
同时保留所有比例和 mixed_space 标记
```

`primary_space` 中文含义是“主空间归属”。取值：

```text
edge      # 明确 edge territory
junction  # junction polygon
unknown   # 未明确归属的 free 区域
empty     # footprint 内没有 free 像素，理论上非 obstacle node 不应出现
```

## 3. 基础质量特征

这些特征只用于计算统一语义，不直接作为零散补丁塞进 energy。

### small_local_free

中文：局部可通行面积小。

定义：

```text
local_free_ratio = free_count / footprint_pixel_count
small_local_free = local_free_ratio <= threshold
```

默认阈值：

```text
threshold = 0.35
```

含义：可能是边界毛刺、小凸起、窄局部区域或低覆盖收益区域。

### low_degree

中文：低连接度。

定义：

```text
degree = 非 obstacle neighbor 数量
low_degree = degree <= threshold
```

默认阈值：

```text
threshold = 3
```

注意：`low_degree` 不一定低价值。真实 dead-end 末端也可能 low_degree，所以必须结合 territory / junction / footprint 解释。

### boundary

中文：边界敏感节点。

定义：

```text
boundary = min_distance_m <= clearance_threshold_m
        or obstacle_neighbor_count >= threshold
```

默认：

```text
clearance_threshold_m = max(resolution * 1.5, 0.10)
obstacle_neighbor_count threshold = 5
```

注意：沿墙覆盖本身需要 boundary node，不能只因为 boundary 就降低覆盖责任。只有 boundary 同时伴随 small_local_free / low_degree / unknown 等特征时，才更像低价值残留。

## 4. 统一语义：coverage_obligation 和 connectivity_value

搜索阶段不要到处写：

```text
if boundary
if low_degree
if junction
```

而是先统一计算两个核心量。

## 4.1 coverage_obligation 覆盖责任

`coverage_obligation` 表示这个 node 对最终覆盖质量有多重要。

取值：

```text
0.0 = 不应单独为了它补扫
0.5 = 尽量覆盖，但允许被覆盖冗余抵消
1.0 = 主覆盖区域，原则上必须覆盖
```

计算结构：

```text
coverage_obligation = base_by_space * quality_factor
```

第一版不把路径 overlap 放进预计算，因为 overlap 依赖规划过程，应在 residual 阶段再计算。

### base_by_space

```text
primary_space = edge:
  base_by_space = 1.00

primary_space = junction:
  base_by_space = 0.55

primary_space = unknown:
  base_by_space = 0.45

primary_space = empty:
  base_by_space = 0.00
```

解释：

- edge territory 是主要覆盖区域，覆盖责任高。
- junction polygon 是连接/掉头/过渡区域，也要清扫，但不应该像通道核心一样强制 sweep。
- unknown 不是无效区域，但归属不清，覆盖责任低于明确 edge。

### quality_factor

第一版建议规则：

```text
quality_factor = 1.0

if small_local_free:
  quality_factor *= 0.55

if boundary and small_local_free:
  quality_factor *= 0.70

if low_degree and small_local_free:
  quality_factor *= 0.75

if primary_space == junction:
  boundary 不再额外降低
```

为什么不单独因为 boundary 降低？

```text
沿墙节点可能是正常覆盖必须点。
单独 boundary 不足以说明它低价值。
```

## 4.2 connectivity_value 连通价值

`connectivity_value` 表示 node 对路径连通、换区、重复通过、路口过渡的价值。

取值：

```text
0.0 = 连通价值低
1.0 = 很适合作为连接/过渡/重复访问节点
```

第一版规则：

```text
primary_space = junction:
  connectivity_value = 0.90

mixed_space 且包含 junction:
  connectivity_value = max(connectivity_value, 0.75)

mixed_space 且包含多个 edge territory:
  connectivity_value = max(connectivity_value, 0.70)

primary_space = edge:
  connectivity_value = 0.40

primary_space = unknown:
  connectivity_value = 0.35

low_degree and not junction:
  connectivity_value *= 0.70

degree >= 5:
  connectivity_value += 0.10，上限 1.0
```

这里体现一个重要判断：

```text
junction 节点 coverage_obligation 可以不高，connectivity_value 应该高。
```

所以 junction 节点可以重复访问、可以作为过渡，但不要求像通道核心一样被完整 sweep。

## 5. node_role 节点角色

`node_role` 是 `coverage_obligation` 和 `connectivity_value` 的离散化表达，用于后续搜索和可视化。

第一版角色：

```text
cover_core
cover_soft
connector
residual_soft
noise_candidate
```

### cover_core 主覆盖节点

条件：

```text
coverage_obligation >= 0.75
```

含义：主覆盖区域节点，通常属于明确 edge territory。

### cover_soft 软覆盖节点

条件：

```text
0.45 <= coverage_obligation < 0.75
connectivity_value < 0.75
```

含义：应该尽量覆盖，但不应该为了它产生很大代价。

### connector 连接节点

条件：

```text
connectivity_value >= 0.75
```

含义：通道切换、路口、过渡节点。它可以重复访问，可以作为路径桥接，不应该被当作孤立补扫目标。

### residual_soft 低责任残留节点

条件：

```text
0.20 <= coverage_obligation < 0.45
connectivity_value < 0.75
```

含义：覆盖责任低，可能是边界残留、小凸起或低收益节点。正常经过可顺手覆盖，但不应主动吸引远跳。

### noise_candidate 噪声候选节点

条件：

```text
coverage_obligation < 0.20
connectivity_value < 0.75
```

含义：非常低覆盖责任、低连通价值节点。第一版不删除，只记录为最弱补扫目标。

## 6. 后续搜索阶段如何统一使用

第一版研究代码只计算语义和可视化，不直接改 planner。后续真正接入 `shelf_aware_guarded` 时，所有阶段都围绕两个量：

```text
coverage_obligation
connectivity_value
```

### normal_search 正常搜索

中文：普通邻居推进阶段。

目标：

```text
优先推进 coverage_obligation 高的区域
允许 connectivity_value 高的节点作为过渡和重复访问
避免低 obligation 节点主动吸引路径
```

候选 energy 应该统一表达为：

```text
E_total = E_original
        - coverage_obligation_reward
        - connectivity_bridge_reward
        + territory_transition_cost
```

含义：

- `coverage_obligation_reward`：访问高覆盖责任节点有收益。
- `connectivity_bridge_reward`：connector 节点可降低重复访问或过渡代价。
- `territory_transition_cost`：空间转移代价，鼓励同 territory 连续，避免无意义跨区。

### fallback_search 全局回退

中文：当前局部无可用推进点时，选择远处未访问目标。

目标不应该再是“任意未访问 node”，而应该是：

```text
剩余覆盖责任高、拓扑切换合理、不是孤立低价值残留的目标
```

目标价值：

```text
target_value = coverage_obligation
             + nearby_unvisited_obligation_sum
             + connectivity_context
```

规则：

```text
低 coverage_obligation 的孤立节点不能单独触发远跳。
connector 只作为过渡，不作为孤立补扫目标。
junction 节点可重复访问，但不要求独立 sweep 式覆盖。
```

### residual_policy 残留处理

中文：搜索后期或 fallback 很远时，对剩余节点做最终判断。

触发条件可以是：

```text
剩余未访问节点数量少
或剩余总 coverage_obligation 低
或下一次 fallback 距离很远
```

处理顺序：

```text
1. coverage_obligation 高 -> 必须处理
2. connectivity_value 高 -> 保留为 connector，不作为孤立补扫目标
3. coverage_obligation 低 -> 判断 overlap / merge / insert / fallback
```

第一版只建议先实现：

```text
covered_by_overlap
```

暂不做 snap / insert。

`covered_by_overlap` 中文含义：节点虽然没有被路径中心访问，但距离已有路径小于实际清扫半径，因此可认为已被清扫覆盖。

条件：

```text
distance_to_existing_path <= actual_clean_radius
coverage_obligation 低
connectivity_value 低
```

## 7. 第一版落地边界

第一版研究代码只做：

```text
1. footprint 统计 territory / junction / unknown
2. 计算 small_local_free / low_degree / boundary
3. 计算 coverage_obligation / connectivity_value
4. 计算 node_role
5. 输出 JSON 和可视化
```

不改正式 planner，不输出路径，不生成新的覆盖轨迹。

输出建议：

```text
node_semantics/node_semantics.json
node_semantics/01_node_space_label_map.png
node_semantics/02_node_role_map.png
node_semantics/03_coverage_obligation_heatmap.png
node_semantics/04_connectivity_value_heatmap.png
```

## 8. 验收标准

第一版可信的最低验收：

```text
1. 每个非 obstacle grid node 都有 node_semantics 记录。
2. junction_label 只来自 junction polygon，不来自 territory_label < 0。
3. mixed territory / junction / unknown 的节点有像素比例记录。
4. coverage_obligation 和 connectivity_value 都有明确中文语义和计算规则。
5. node_role 可视化能解释：主通道、路口、边界残留、低价值节点分别在哪里。
6. 不修改正式 shelf_aware_guarded 搜索行为。
```
