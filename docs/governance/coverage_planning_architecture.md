# 覆盖规划长期架构边界

## 目标边界

覆盖规划工程按以下职责分层：

- `maptools`
  - 地图编辑器产品层、工程会话、用户交互、覆盖规划参数对话框、结果展示和产品适配。
  - 不承载覆盖规划算法规则，不直接依赖旧算法中间对象。
- `algorithms/coverage_planning`
  - 正式覆盖规划算法域。
  - 承载统一 request/result/diagnostics/config contract、公共预处理、显式 planner factory、`auto` routing 和正式 planner。
- `algorithms/channel_topology_graph`
  - 独立一级算法主线。
  - 通过 `algorithms/coverage_planning/routing/adapters/channel_topology_graph_adapter.py` 接入覆盖规划统一 contract。
- `tools/coverage_planning`
  - 仓库级标准 case runner 和可视化工具入口。
  - 不依赖历史 `python_ws`。
- `coverage_dataset`
  - 测试集、case 生成、批量 geometry/full-pipeline runner、报告索引和 benchmark 资产管理。

## 正式调用链

覆盖规划正式输入由 `CoveragePlanningRequest` 承载：

```text
maptools / tools / dataset
  -> CoveragePlanningRequest(prepared_map, region_mask, starting_position_px, public_config, private_config)
  -> auto: route_coverage_plan(...)
  -> explicit basic/shelf_aware/shelf_aware_turn_cost: run_formal_planner_request(...)
  -> explicit channel_topology_graph: run_channel_topology_graph_adapter(...)
  -> CoveragePlanningResult(status, path, path_pixels, diagnostics)
```

`auto` 只负责选择一个目标算法，不允许先运行 CTG 的重型建模再用 CTG 中间结果反向决定是否选择 CTG。

## 算法入口

当前 UI 暴露的 planner mode 由 `algorithms/coverage_planning/modes.py` 统一定义：

- `auto`
- `basic`
- `shelf_aware`
- `shelf_aware_turn_cost`
- `channel_topology_graph`

其中：

- `basic`、`shelf_aware`、`shelf_aware_turn_cost` 是 formal factory 可直接运行的显式模式。
- `channel_topology_graph` 是 adapter-only 模式。
- `auto` 通过 routing 选择 `region_basic`、`shelf_aware` 或 `channel_topology_graph`。

## 公共输入与预处理

阶段2后的正式公共输入为：

- `prepared_map`
  - 总图尺度上的统一公共预处理结果。
- `region_mask`
  - 当前任务区域硬边界。
- `starting_position_px`
  - 起点像素坐标；不可通行时由公共入口吸附或返回失败。
- `map_resolution`、`map_origin_xy`
  - 像素与世界坐标转换真值。

公共预处理由 `algorithms/coverage_planning/preprocessing` 承担。显式算法和 `auto` 不应各自重复维护一套互相冲突的区域裁剪或形态学处理策略。

## 参数分层

正式公共配置为 `CoveragePlannerConfig`，位于 `algorithms/coverage_planning/contracts/config.py`，不属于任何单一 planner 实现。

长期分层：

- 正式输入真值：`prepared_map`、`region_mask`、`starting_position_px`、`map_resolution`、`map_origin_xy`。
- 通用可调参数：`coverage_width_m`、`robot_width_m`、`open_kernel_m`、`obstacle_expand_m`、`auto_rotate`。
- 算法专属参数：shelf-aware、turn-constraint、CTG 专属求解参数。
- 内部实现参数：调试开关、临时实验参数、尚未稳定的中间过程参数。

旧公共字段 `coverage_radius`、`grid_spacing_m`、`robot_radius`、`erode_radius`、`erode_radius_m` 不再支持。旧 CTG 宽度键 `sweep_max_spacing_m`、`robot_cleaning_width_m` 也不再作为正式输入键。

完整参数字段、GUI 控件映射和算法专属参数解释属于子工程职责，应维护在 `algorithms/coverage_planning/docs/` 或 `maptools/docs/`，根层只保存分层原则和跨模块约束。

## 工程驱动编辑器边界

`maptools` 的正式产品主链围绕工程会话：

- `New Project...`
- `Open Project...`
- `Save Project`
- `Save Project As...`

底图加载、区域恢复、路径恢复、电子围栏恢复和覆盖规划结果落盘都应附着在工程生命周期内。零散资源导入导出可以保留底层能力，但不应重新成为顶层长期主链。

## 历史入口退场

以下入口已经退出当前正式运行面：

- `python_ws` 工作区根目录。
- `python_ws/algorithms/channel_topology_coverage` 旧 CTC。
- `python_ws/algorithms/python_energy_functional` 早期原型。
- `maptools/algorithms/region_coverage_path` 旧覆盖规划包装。
- 顶层根目录历史样例/输出目录作为长期 fixture 或报告真值。

归档文档可以解释这些入口的历史来源，但不能指导当前运行。
