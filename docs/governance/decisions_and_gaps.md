# 决策与缺口

## 已稳定决策

### 覆盖规划正式域

覆盖规划正式域归属 `algorithms/coverage_planning`。`maptools` 只做产品适配，旧 `maptools/algorithms/region_coverage_path` 不再作为覆盖规划实现根目录。

影响范围：

- GUI 调用、标准 case runner、dataset runner 都应通过正式 contract 进入算法域。
- 新 planner、routing 或 diagnostics 变更应优先落在 `algorithms/coverage_planning`。

### CTG 独立一级算法主线

`algorithms/channel_topology_graph` 是独立一级算法，不作为 `coverage_planning/planners` 子目录。覆盖规划域通过 adapter 调用 CTG，并把 CTG 输出转换为 `CoveragePlanningResult`。

影响范围：

- CTG 内部 stage、baseline、support、renderers 继续归 CTG 子工程维护。
- 产品层不得直接消费 CTG 内部 stage 对象。

### 阶段2字段收口

公共参数使用宽度语义：

- `coverage_width_m`
- `robot_width_m`
- `open_kernel_m`
- `obstacle_expand_m`

旧字段和旧 CTG 宽度键不再作为正式输入。历史 baseline、拒绝式测试或归档说明中可以出现旧字段，但必须带历史或拒收语义。

### 工程会话主链

地图编辑器长期主链围绕 project 生命周期。`File` 顶层不再恢复成零散 map/path/repo 导入导出集合。

## 已确认但未完全闭合的缺口

### Routing 可靠性验证

状态：未作为长期完成事实记录。

影响范围：

- `auto` 已有正式入口，但跨 room-like、aisle-like、mixed 真实 case 的选择可靠性仍需要持续验证。
- 显式 planner 入口在 routing 可靠性稳定前继续保留。
- CTG 适用性细则、场景分类阈值和具体 case 解释属于 `algorithms/coverage_planning/routing` 与 `algorithms/channel_topology_graph` 子工程文档职责，根层只记录验证缺口和产品入口边界。

建议验证：

- 使用 `coverage_dataset` 中代表性 business maps 和 IPA maps 建立 routing 选择基线。
- 记录 `selected_planner`、`scene_type`、`reasons`、`warnings`、路径覆盖质量与失败原因。

### Diagnostics 产品化展示

状态：已有 diagnostics contract 和 GUI 摘要/面板入口，但 runtime details 仍有继续产品化空间。

影响范围：

- 当前 diagnostics 已可落到结果摘要和 artifact。
- 更完整的用户可读诊断面板、过滤和导出仍可继续增强。

### Dataset/report 资产分级

状态：报告区已与源码真值区分，但历史报告仍需要按 benchmark、evidence、scratch 继续治理。

影响范围：

- `coverage_dataset/reports` 不能直接被当作长期基线。
- 需要保留的报告必须进入 `report_index` 或明确 baseline。

### Maptools 文档同步

状态：根层治理已收敛，但 `maptools/docs` 中仍可能保留早期 `Open Resource...`、零散入口或旧 quickstart 表述。

影响范围：

- 本次只治理根层 `docs/`。
- 子工程文档后续应按同样规则把已过时流程吸收到当前设计或使用说明。
