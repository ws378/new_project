# CoveragePlanning 调试脚本

## 目的
这里放的是 **可复用** 的 CoveragePlanning 调试脚本，不是一次性临时脚本。

当前这批脚本主要服务于：
- 审查每条 `coverage lane` 的横向 `sweep` 铺设
- 导出每个采样锚点的局部可铺 `sweep` 数
- 导出排序结果、稳健分位数结果、最终统一回填 offsets
- 审查 `SweepGraph -> SweepCadence` 的对象级问题分类

## 当前脚本
### `run_sweep_layout_diagnostics_real_case.py`
真实 case 运行脚本。会完整跑：
- `geometry_preparation`
- `junction_rebuild`
- `topology_graph_build`
- `coverage_planning`

然后导出：
- `sweep_layout_diagnostics.json`
- `sweep_layout_diagnostics.md`

### `run_sweep_cadence_diagnostics_real_case.py`
真实 case 运行脚本。会完整跑：
- `geometry_preparation`
- `junction_rebuild`
- `topology_graph_build`
- `coverage_planning`

然后导出：
- `sweep_cadence_diagnostics.json`
- `sweep_cadence_diagnostics.md`

## 导出内容说明
### 通道级
每条 `coverage lane` 会导出：
- `coverage_lane_id`
- `source_edge_id`
- `anchor_count`
- `sampling_step_px`
- `normal_search_px`
- `effective_min_clearance_px`
- `local_sweep_counts_raw`
- `local_sweep_counts_sorted`
- `robust_quantile`
- `target_sweep_count`
- `final_sweep_count_generated`
- `center_sweep_index`
- `mean_offsets_px`

### 锚点级
每个采样锚点会导出：
- `anchor_index`
- `anchor_rc`
- `center_point_rc`
- `normal_vec`
- `offset_min_px`
- `offset_max_px`
- `interval_width_px`
- `local_sweep_count`
- `final_offsets_px`

## 适用场景
这批脚本主要用于回答下面这些问题：
- 某条通道为什么只铺出 1 条 / 2 条 / 3 条 `sweep`
- 局部过窄锚点是否把全 lane 的 `sweep` 数拉低了
- 90 分位（或后续调整的稳健分位数）是否合理
- 统一条数回填后，各锚点的 offsets 是否仍保持首尾完整、均匀铺设
- 哪些 sweep 双端都有连接
- 哪些 sweep 只有一端连接
- 哪些 sweep 两端都没连接
- 问题是来自 graph 缺 transition，还是 cadence 没吃到

## 结果目录
脚本输出到：
- `algorithms/channel_topology_graph/test_outputs/sweep_layout_diagnostics_<timestamp>/`

## 后续扩展
后面如果继续补：
- `territory` 诊断
- `effective_region` 诊断
- polygon 内连接段诊断
- `SweepCadence` 问题分型诊断
