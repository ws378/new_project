# renderers 渲染模块说明

## 1. 文档目的

本文档补齐 `algorithms/channel_topology_graph/renderers` 的正式职责说明，解决“主算法文档较完整，但 renderers 对正式源码公开面没有被同等级说明”的缺口。

本文档描述当前源码里已经存在的正式渲染结构、正式入口和职责边界，不把临时调试脚本、一次性 notebook 绘图或外部实验目录混入正式渲染面。

## 2. 模块范围

当前正式源码目录包括：

- `algorithms/channel_topology_graph/renderers/__init__.py`
- `algorithms/channel_topology_graph/renderers/coverage_renderers.py`
- `algorithms/channel_topology_graph/renderers/geometry_renderers.py`
- `algorithms/channel_topology_graph/renderers/junction_renderers.py`
- `algorithms/channel_topology_graph/renderers/coverage/`
- `algorithms/channel_topology_graph/renderers/junction/`

## 3. 正式结构分层

当前 `renderers` 包已经明确按三层结构组织：

1. 包级入口 `renderers/__init__.py`
   - 只暴露最常用的三类写盘入口。
2. 领域级入口 `coverage_renderers.py` / `geometry_renderers.py` / `junction_renderers.py`
   - 面向需要某一领域细粒度渲染能力的调用方。
3. 内部实现层 `coverage/` / `junction/`
   - 承载具体绘制原语、面板组合和分图写盘逻辑。

这个分层是当前正式结构，不应把内部子包再次直接暴露成外部主入口。

## 4. 包级正式公开面

`renderers/__init__.py` 当前正式导出：

- `write_coverage_planning_visualizations`
- `write_geometry_preparation_visualizations`
- `write_junction_rebuild_visualizations`

包级入口的边界很明确：

- 只做稳定导出。
- 不在包级入口新增跨领域聚合逻辑。
- 不把内部绘图 helper 直接抬升到包级公开面。

## 5. 三个领域级入口分别回答什么

## 5.1 `coverage_renderers.py`

真实职责：

- 对外稳定暴露 coverage 领域的写盘入口。
- 对外暴露 summary / sweep debug / cadence debug / final path debug 能力。
- 把具体绘图与状态组合继续下沉到 `renderers.coverage/` 子包。

当前正式导出分组是：

1. 写盘入口
   - `write_coverage_planning_visualizations`
2. summary
   - `render_coverage_lanes_summary`
   - `render_coverage_lane_territory_summary`
   - `render_coverage_lane_effective_region_summary`
   - `render_coverage_sweeps_summary`
3. sweep debug
   - `render_sweep_node_chain_debug`
   - `render_sweep_port_view_debug`
   - `render_sweep_transition_candidate_debug`
4. cadence debug
   - `render_sweep_cadence_debug`
   - `render_sweep_cadence_classification_inputs_debug`
   - `render_sweep_cadence_connection_rules_debug`
   - `render_sweep_cadence_connection_rule_focus_debug`
5. final debug
   - `render_final_coverage_path_debug`
   - `render_junction_connection_summary`
   - `write_junction_connection_detail_visualizations`
   - `render_junction_connection_detail_for_node`

## 5.2 `geometry_renderers.py`

真实职责：

- 对外稳定暴露 geometry 领域的 summary/detail 写盘入口。
- 由本文件直接承载 geometry_preparation 的渲染调度与主要绘图实现。

当前正式主入口是：

- `write_geometry_preparation_visualizations(...)`

这个入口当前受两个开关控制：

- `summary_viz`
- `detail_viz`

它的正式约束是：

- 两个开关都关时完全无副作用。
- 真正写图时才创建输出目录。
- summary 图和 detail 图职责分离。
- 返回值只汇报写盘结果路径，不返回图像数组本体。

## 5.3 `junction_renderers.py`

真实职责：

- 对外稳定暴露 junction 领域的 summary/detail/native-geometry 渲染能力。
- 具体绘图组合继续下沉到 `renderers.junction/` 子包。

当前正式导出是：

- `write_junction_rebuild_visualizations`
- `render_junction_rebuild_summary`
- `render_junction_rebuild_native_geometry`
- `write_junction_rebuild_details`

## 6. `renderers` 真正回答的问题

`renderers` 不是算法求解层，它回答的是“正式结果如何被人看见”。

当前三大领域分别回答：

1. `geometry`
   - geometry_preparation 的 region/free/open/skeleton/pruned-skeleton 是否合理。
2. `junction`
   - junction_rebuild 的节点、边、native geometry 与 detail 视图是否合理。
3. `coverage`
   - coverage lane/sweep、sweep graph 候选、cadence 规则输入与 final path 物化结果是否合理。

换句话说，`renderers` 是正式结果的人类检查面，而不是算法真值生成面。

## 7. 与其它目录的边界

与 `stages` 的边界：

- `stages` 负责生成正式结果对象。
- `renderers` 只读取正式结果对象生成图像，不反向改写真值。

与 `io` 的边界：

- `io` 负责 json/summary 写盘。
- `renderers` 负责图片和可视化写盘。
- 两者都属于输出层，但输出媒介不同。

与 `contracts` 的边界：

- `contracts` 定义正式结构。
- `renderers` 消费这些结构并把它们转成可视图。
- `renderers` 不应重新定义一套与 contract 脱节的解释层。

## 8. 当前治理约束

后续整改或扩展 `renderers` 时，至少要继续满足以下约束：

1. 包级入口只保留稳定导出，不承担跨领域聚合判断。
2. 领域级入口是正式公开面，内部子包不应被外部调用方直接当成主入口。
3. 渲染层只读取正式结果，不改写结果对象。
4. 渲染图的分层要和正式对象层次一致，避免另起一套语义。
5. 开关控制必须真实生效，关闭时不生成多余目录和空产物。

## 9. 结论

当前 `renderers` 已经不是零散绘图工具集合，而是这条算法主线的正式可视化输出层：

- 包级入口负责收口常用写盘面。
- 领域级入口负责对外暴露稳定渲染能力。
- 内部子包负责承载具体图像组合实现。

因此后续文档、审计和整改都必须把 `renderers` 视为正式模块，而不是附属调试目录。
