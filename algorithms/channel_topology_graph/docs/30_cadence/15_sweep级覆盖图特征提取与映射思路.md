# sweep级覆盖图特征提取与映射思路

目标：在已经完成场景分类后，提炼能够直接驱动 `sweep -> sweep` 映射策略的关键特征，并给出稳定的解决思路。  
本文档重点回答：

- 为什么不能只按 sweep 索引映射
- 为什么要引入 `SweepGroup`
- 节点口空间排序到底是什么
- `straight / left_turn / right_turn / u_turn` 应如何进入映射逻辑
- 哪些风险和收益项应进入评分

本文档不直接给最终模块流程，正式整体方案请继续参考：

- [16_sweep级覆盖图与顺序规划方案.md](./16_sweep级覆盖图与顺序规划方案.md)

## 1. 问题重述

当前第 3 步已经有 accepted topology lane：

- `in_edge -> via_node -> out_edge`

它解决的是：

- edge 级通行许可

它没有解决的是：

- 哪条 `in_sweep` 应接哪条 `out_sweep`

因此，下一步的重点不是重新求 edge 许可，而是：

- 把 edge 级许可进一步细化成 sweep 级连接关系

## 2. 为什么不能只看 sweep 索引

### 2.1 生成顺序不等于几何顺序

若 sweep 索引只是“生成顺序”，则：

- 它未必稳定表达通道横向位置
- 更无法表达在某个节点口的实际空间排序

因此不能直接做：

- `in_sweep_idx -> out_sweep_idx`

### 2.2 不同路口转向下，映射规律不同

例如：

- `straight`
- `left_turn`
- `right_turn`
- `u_turn`

它们对应的 sweep 对齐规律天然不同。  
即使同样是三条 sweep 对三条 sweep：

- 直行可能更接近同序
- 转弯可能更接近偏移映射
- 某些非正交场景甚至既不是同序也不是反序

### 2.3 风险不允许简单按序一一连接

边缘 sweep 往往：

- 更靠近障碍
- 转弯更急
- 在节点口更危险

所以“每条 sweep 都要按索引一一对应”并不是合理目标。

## 3. 为什么要引入 SweepGroup

## 3.1 定义

`SweepGroup` 表示：

- 同一 `coverage lane` 内的一组有序 sweeps

它保留的不是单条 sweep 的几何，而是：

- 组内结构
- 组内顺序
- 中心/边缘语义
- 在节点口处的组内空间排序

### 3.2 作用

引入 `SweepGroup` 的目的不是多加一层对象，而是：

1. 保留同一通道内部的 sweep 组结构
2. 把 `sweep -> sweep` 映射问题先提升成 `group -> group` 结构问题
3. 避免退化成裸 sweep 两两暴力配对

### 3.3 对最终目标的正向收益

1. **压缩复杂度**
- 先组到组，再组内展开

2. **保留结构先验**
- 中心 sweep、边缘 sweep、相对顺序不会丢

3. **更利于定义映射模板**
- 同序
- 反序
- 中心对齐
- 边缘回避

4. **更利于后续 route**
- route 不只在 sweep 上运算，也可参考其组结构和风险

## 4. 应提取哪些关键特征

### 4.1 Group 级特征

每个 `SweepGroup` 至少应提取：

- `source_edge_id`
- `coverage_lane_id`
- `sweep_count`
- `center_sweep_index`
- `ordered_sweep_ids`
- `main_direction`

### 4.2 Group 内 sweep 特征

每条 sweep 至少应提取：

- 组内横向序位
- 相对中心位置
- 是否边缘 sweep
- 点链长度
- 风险等级

### 4.3 节点口空间特征

这是最关键的一层。

对每个 `SweepGroup` 在某个节点口，应建立：

- `SweepPortView`

它至少描述：

- 该组在节点口的开口截面
- 组内 sweeps 在节点口处的空间排序
- 每条 sweep 在该口处更偏左 / 更偏右 / 更偏中心

这里的“排序”不是生成顺序，而是：

- **节点口空间排序**

也就是：

- 当机器人从该组进入节点时，哪个 sweep 在空间上更靠一侧，哪个更靠中心

### 4.4 拓扑与转向特征

对每个 accepted `in_edge -> via_node -> out_edge`，应明确：

- `turn_type`
  - `straight`
  - `left_turn`
  - `right_turn`
  - `u_turn`
- `turn_angle`
- `via_node_type`

## 5. 映射策略应如何思考

## 5.1 不是全排列

不能做：

- 所有 `in_sweeps × out_sweeps`

原因：

- 组合爆炸
- 大部分组合没有结构意义

### 5.2 先 edge-pair，再 group-pair

映射流程应先受 accepted topology lane 约束：

1. 只考虑已许可的 `in_edge -> out_edge`
2. 再把两端的 `SweepGroup` 取出来
3. 只在该 group-pair 内做 sweep 映射

### 5.3 几何候选主导跨 group 映射

跨 group 的正确候选生成顺序是：

1. 先按 accepted topology lane 锁定允许连接的 group-pair。
2. 在该 group-pair 内受控展开 `from_group sweeps x to_group sweeps`。
3. 对每个 pair 读取 from sweep 的退出端 `A/B` 和 to sweep 的进入端 `C/D`。
4. 用 `distance(B, C)` 作为端点接近度。
5. 用 `angle(B - A, D - C)` 作为 sweep 级转角。
6. 用 `turn_type / motion_type` 只表达期望运动类型，再由 sweep 级转角校验是否匹配。
7. 用 top-k、局部可行域和障碍约束控制候选数量。

这里的核心约束是：

- 跨 group 的左 / 中 / 右对应关系来自 sweep 端点几何和局部连接空间。
- 跨 group 输出可供 cadence 选择的多候选集合。
- 跨 group 候选是否合理，由 sweep 端点几何和局部可行性主导。
- 当前没有建立跨 group rank frame 对齐，因此跨 group 的 `rank_gap` 不能解释真实左 / 中 / 右对应关系。
- `mean_offset_m / side_level` 只在 sweep 自己的 group / coverage lane 内有角色意义，不能主导跨 group pair 选择。

同 group 则不同：

- 同 group sweeps 共享同一中心参考线、同一偏移生成规则和同一 port view 排序。
- 同 group 的 `rank_gap` 可以作为横移范围和横移风险的重要依据。
- 同 group 的 `mean_offset_m / side_level` 可以作为覆盖角色和起点选择的辅助依据。
- 即便在同 group 内，最终连接仍要结合端点距离、端点方向和局部可行性。

#### `straight`
- 期望 sweep 端点方向接近顺接。
- 不能因为 group rank 相同就直接认为是直行合理候选。

#### `left_turn / right_turn`
- 期望 sweep 端点方向符合对应转向。
- 不能用中心对齐模板替代真实转角判断。

#### `u_turn / foldback`
- 不能默认开放给全部 sweeps。
- 必须由 same-sweep 或端点方向接近回折的几何证据支撑。
- 或后续作为单独原语处理。

## 6. 风险与收益项

## 6.1 风险项

映射评分至少应考虑：

1. 边缘 sweep 风险
2. 小转弯半径风险
3. 节点口近障碍风险
4. 点链长度过短风险

## 6.2 收益项

除了可通行性，还应考虑：

1. 路口区覆盖收益
2. 减少未覆盖残区收益
3. 更利于后续 route 平滑推进的收益

## 6.3 特别注意：通道内切换 vs 借路口掉头

有些情况下：

- 在通道内直接切换到邻近 sweep

并不是最优。

更优的方式可能是：

- 先沿当前 sweep 进入路口
- 借路口完成掉头或换向
- 再进入目标 sweep

因此后续 route 层应允许：

1. 通道内切换原语
2. 借路口掉头/换向原语

并用统一代价比较。

## 7. 从特征到策略的整体思路

更合理的路线是：

1. 提取 `SweepGroup` 及其组内结构
2. 提取节点口空间排序 `SweepPortView`
3. 对每个 accepted topology lane 判定 `turn_type`
4. 在 topology 许可的 group-pair 内展开跨 group 多候选
5. 用 sweep 端点距离、sweep 级转角和局部可行性过滤候选
6. 按风险与收益评分，保留稳定候选

## 8. 本文结论

真正的核心不是：

- sweep 索引本身

而是：

- 节点口空间排序
- 转向类型
- `SweepGroup` 组结构
- 风险与覆盖收益

所以后续正式方案必须建立在：

- `SweepGroup`
- `SweepPortView`
- `turn_type`
- sweep 端点几何
- 局部可行性

这些层次之上，不能退化成简单的索引映射。
