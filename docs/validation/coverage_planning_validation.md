# 覆盖规划验证矩阵

## 通用只读检查

每轮文档或代码治理开始和结束建议执行：

```bash
git status --short
git diff --stat
```

文档治理还应执行：

```bash
find docs -type f | sort
rg -n "\\[[^\\]]+\\]\\(([^)]+)\\)" docs
```

## 文档类改动

适用范围：

- 根层 docs 结构调整。
- 覆盖规划治理文档更新。
- 归档说明吸收或删除。

最低检查：

```bash
git diff -- docs
find docs -type f | sort
find docs \( -path 'docs/refactor_*' -o -path '*/40_*' \) -print
```

通过标准：

- 根层索引能解释每个目录职责。
- 没有断链。
- 没有把历史入口写成当前运行入口。
- 过程记录中的稳定事实已吸收到治理、验证或归档文档。

## 覆盖规划 contract 或参数改动

最低检查：

```bash
python3 -m pytest tests/test_planner_factory_modes.py tests/test_channel_topology_graph_adapter.py -q
python3 -m pytest coverage_dataset/tests/test_generate_cases_from_template.py -q
```

重点观察：

- `CoveragePlanningRequest` 仍以 `prepared_map + region_mask` 为正式输入。
- `CoveragePlannerConfig` 继续拒收旧公共字段。
- CTG private config 继续拒收旧宽度键。
- `planning_config` 新生成 case 仍写入阶段2正式字段。

## GUI 覆盖规划入口改动

最低检查：

```bash
python3 -m pytest tests/test_main_window_flow.py tests/test_planner_factory_modes.py -q
```

重点观察：

- `auto`、`basic`、`shelf_aware`、`shelf_aware_turn_cost`、`channel_topology_graph` 仍与 mode registry 一致。
- 覆盖规划对话框默认值、参数分区和 diagnostics 展示不退回旧字段。
- `File` 顶层主链不恢复零散导入导出入口。

## 标准 case runner 与 dataset 改动

最低检查：

```bash
python3 -m pytest coverage_dataset/tests/test_generate_cases_from_template.py \
  coverage_dataset/tests/test_run_generated_cases_geometry.py \
  coverage_dataset/tests/test_run_generated_cases_full_pipeline.py -q
python3 -m pytest tests/test_channel_topology_graph_adapter.py -q
```

重点观察：

- `tools/coverage_planning/run_case.py` 只接受阶段2正式公共字段。
- generated case loader 返回 `CasePlanningConfig`。
- geometry/full-pipeline runner 输出包含正式 `planning_config` 摘要。

## 旧入口或资产删除

删除、归档或迁移旧入口前必须先做引用检查：

```bash
rg "python_ws|channel_topology_coverage|legacy_ctc|maptools.algorithms.region_coverage_path" algorithms maptools tools tests coverage_dataset
rg "coverage_radius|robot_radius|erode_radius|sweep_max_spacing_m|robot_cleaning_width_m" algorithms maptools tools tests coverage_dataset
```

通过标准：

- 当前源码、工具和测试不得继续依赖旧运行入口。
- 旧字段命中如属于拒绝式测试、历史 baseline 或归档说明，必须有明确语义。
- 下游导航、覆盖清扫或仿真链路受影响时，测试结论必须说明是否已验证下游链路。
