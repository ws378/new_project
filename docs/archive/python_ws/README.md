# python_ws 历史归档

本文档只解释原 `python_ws` 工作区的历史来源。当前仓库不再保留 `python_ws` 作为正式工作区根目录，也不再通过 `python_ws` 运行覆盖规划。

## 当前替代入口

- 覆盖规划正式算法域：`algorithms/coverage_planning`
- 通道拓扑图算法主线：`algorithms/channel_topology_graph`
- 标准 case runner：`tools/coverage_planning/run_case.py`
- 标准轻量 fixture：`tests/fixtures/coverage_cases/case_demo`
- 测试集与批量运行：`coverage_dataset`

运行标准 case：

```bash
python3 tools/coverage_planning/run_case.py \
  --case-dir tests/fixtures/coverage_cases/case_demo \
  --algorithm basic
```

可视化 runner 输出：

```bash
python3 tools/coverage_planning/viewer.py <run_dir>/global_path.json
```

## 历史迁移事实

原 `python_ws` 阶段曾包含：

- `python_ws/algorithms/channel_topology_coverage`
  - 旧 CTC 实现，曾作为早期 map-tools 覆盖规划入口。
- `python_ws/algorithms/python_energy_functional`
  - 早期能量函数和货架感知原型。
- `python_ws/cases/case_demo`
  - 早期标准 case。
- `python_ws/tools`
  - 早期 runner 和 viewer。

当前状态：

- 旧 CTC 和 `legacy_ctc` 入口已经删除。
- `python_energy_functional` 原型已经删除。
- 标准 case 已迁到 `tests/fixtures/coverage_cases/case_demo`。
- 标准 runner/viewer 已迁到 `tools/coverage_planning`。
- map-tools 覆盖规划入口通过 `algorithms.coverage_planning` 的 contracts、planner factory、routing 和 adapters 接入。

## 历史 case 格式吸收结果

早期 case 设计中的长期有效部分已经吸收为当前标准：

- `map.yaml` 提供地图。
- `region.json` 提供区域像素多边形和起点像素。
- `planning_config.json` 提供阶段2正式公共参数。
- runner 输出写入 `runs/` 或指定运行目录，属于运行工件，默认不提交。

## 禁止恢复

- 不得恢复 `python_ws` 作为当前运行根目录。
- 不得恢复 `python_ws/algorithms` 作为算法 import 根目录。
- 不得把旧 `ctc` 写成当前 planner mode。
- 不得把 `coverage_radius`、`robot_radius`、`erode_radius`、`sweep_max_spacing_m`、`robot_cleaning_width_m` 写成当前正式输入字段。
