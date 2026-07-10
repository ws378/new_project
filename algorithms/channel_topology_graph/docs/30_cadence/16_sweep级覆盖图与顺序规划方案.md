# sweep 级覆盖图与顺序规划方案

## 1. 文档定位

本文档描述当前源码里 sweep 级静态对象与顺序规划之间的关系。

这里采用已经对齐后的正式口径：

- `sweeps` 继续保留
- `sweep_transition_candidate_info` 继续保留
- `sweep_graph_info` 不再作为长期正式主线对象继续保留

## 2. 当前顺序规划之前的长期正式对象

当前真正进入顺序规划之前，长期应保留的 sweep 级对象是：

1. `sweeps`
2. `sweep_transition_candidate_info`

其中：

- `sweeps` 提供 sweep 几何与身份真值
- `sweep_transition_candidate_info` 提供 sweep-to-sweep 转移候选真值

## 3. `sweep_graph_info` 的定位变化

过去文档里常把：

- `sweep_graph_info`

写成 cadence 直接消费的 sweep 图真值。

现在对齐后的口径是：

- 如果代码里仍存在 `sweep_graph_info`，它只是迁移期或实现期的中间壳
- 它不再作为长期正式主线对象继续保留
- 它承接的功能应拆回：
  - `coverage_lane_sweep_info.sweeps`
  - `graph_info.nodes`
  - 规范化后的 sweep transition 真值视图

## 4. 顺序规划实际依赖什么

当前 `build_sweep_cadence(...)` 长期应理解为依赖：

- sweep 主表
- 节点语义主表
- sweep transition 真值视图

更具体地说，就是：

- `coverage_lane_sweep_info.sweeps`
- `graph_info.nodes`
- 从 `sweep_transition_candidate_info` 继续规范化得到的 transition truth

而不是把一个叫 `sweep_graph_info` 的中间壳继续当成正式抽象层。

## 5. 总结

当前 sweep 级覆盖图与顺序规划关系应写成：

- `sweeps`
  -> `sweep_transition_candidate_info`
  -> `sweep_cadence_info`

如果中间仍有 `sweep_graph_info` 一类实现层对象，只视为兼容或适配层，不再写成长期正式主线。
