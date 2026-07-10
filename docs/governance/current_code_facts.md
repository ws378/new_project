# 当前代码事实

本文记录仓库级覆盖规划运行面的当前事实。代码仍是最终事实源；本文用于给维护者定位入口和边界。

## 覆盖规划 contract

- `algorithms/coverage_planning/contracts/requests.py`
  - `CoveragePlanningRequest` 固定 `prepared_map`、`region_mask`、`starting_position_px`、`public_config`、`private_config` 和 artifact 根目录。
  - `region_mask` 必须与 `prepared_map` 同尺寸。
- `algorithms/coverage_planning/contracts/config.py`
  - `CoveragePlannerConfig` 是正式公共参数对象。
  - `CoveragePlannerPrivateConfig` 是 planner-private 参数对象。
  - `normalize_coverage_planner_config_dict(...)` 拒收旧公共字段。
  - `build_private_coverage_planner_config(...)` 拒收旧 CTG 宽度键。
- `algorithms/coverage_planning/contracts/results.py`
  - `CoveragePlanningResult` 固定 `status`、`path`、`path_pixels`、`error_message` 和 typed diagnostics。

## Planner 与 routing

- `algorithms/coverage_planning/planner_factory.py`
  - `create_coverage_planner(...)` 创建 formal factory planner。
  - `run_formal_planner_request(...)` 执行 `basic` / `shelf_aware` / `shelf_aware_turn_cost` 显式模式。
  - 运行前会用 `apply_region_constraint(...)` 把 `region_mask` 重新压到 `prepared_map` 上。
- `algorithms/coverage_planning/routing/coverage_router.py`
  - `route_coverage_plan(...)` 是 `auto` 入口。
  - routing 先做 applicability 分类，再调用目标 planner 或 CTG adapter。
- `algorithms/coverage_planning/routing/adapters/channel_topology_graph_adapter.py`
  - CTG adapter 消费 `CoveragePlanningRequest`，构造 CTG stage config，并在 GUI/tool artifact 根目录下写 CTG 分阶段产物。

## 地图编辑器接入

- `maptools/adapters/coverage_planning_adapter.py`
  - 只做产品层桥接，统一 re-export 正式 coverage-planning API。
- `maptools/views/coverage_dialog.py`
  - UI planner mode 与 `algorithms/coverage_planning/modes.py` 保持一致。
  - 默认 planner mode 为 `auto`。
  - 参数按通用区、shelf-aware 专属/高级区、CTG 专属/高级区、转角约束区组织。
- `maptools/views/main_window.py`
  - `File` 顶层主链为 `New Project...`、`Open Project...`、`Save Project`、`Save Project As...`、`Exit`。
  - 覆盖规划 diagnostics 面板位于 `View -> Coverage Planner Diagnostics...`。

## Dataset 与工具入口

- `tools/coverage_planning/run_case.py`
  - 标准 case runner 从 `region.json` 和 `planning_config.json` 构造正式 request。
  - `planning_config` 必须提供阶段2正式公共字段，例如 `coverage_width_m`、`robot_width_m`、`open_kernel_m`、`obstacle_expand_m`。
- `coverage_dataset/tools/generate_cases_from_template.py`
  - 新生成 case 默认写入 `schema_version: 2` 和阶段2正式公共字段。
- `algorithms/channel_topology_graph/io/case_loader.py`
  - `CasePlanningConfig` 是 generated/real case 的阶段2归一化配置对象。
  - legacy public key 和 legacy width key 会被拒收。
- `coverage_dataset/tools/run_generated_cases_geometry.py`
  - 批量运行 geometry 阶段并汇总 `planning_config` 与输入摘要。
- `coverage_dataset/tools/run_generated_cases_full_pipeline.py`
  - 批量运行 CTG full pipeline，并输出正式规划配置摘要。

## 运行资产规则

- `coverage_dataset/reports` 是报告与调试工件区，不是源码真值。
- 长期 benchmark 或人工证据必须先进入明确的 report index、baseline 或验证文档，再判断是否需要版本管理。
- 临时截图、生成地图、大型样例工程和运行输出默认不提交。
- `runtime_runs/` 是运行输出位置，不应被文档写成长期输入事实源。
