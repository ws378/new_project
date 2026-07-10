# 覆盖路径优化治理说明

## 目标

覆盖路径性能优化必须先保持算法语义稳定，再讨论耗时下降。任何优化都不能通过跳过正式算法、减少覆盖结果、吞掉错误或改变默认规划语义来换取耗时。

## 语义基线

正式优化对比使用：

```bash
python3 tools/coverage_semantic_baseline_check.py --compare /tmp/beiguo_lanshan_current_baseline.json
```

稳定比较字段包括区域 id、区域名、成功状态、错误信息、路径点数量、路径长度、路径 hash、edge label hash、junction label hash、图节点数量和图边数量。耗时只作为性能观察，不参与语义相等判断。

## 起点语义

GUI 触发覆盖路径时，区域质心不一定落在可通行空间内。正式链路允许把起点吸附到所选区域内最近可通行像素，避免同一个区域因默认质心位置不可达而直接失败。

约束：

- 吸附只能发生在本轮所选区域的可通行空间内。
- 吸附不能跨出 region mask。
- 吸附后的 planning mask 外围仍按不可通行处理，避免区域边界被当成开放自由空间。

## CTG 私有运行参数

`CoveragePlannerPrivateConfig` 提供两个 CTG 私有运行控制项：

- `ctg_include_truncation_debug`：显式控制 junction 截断调试信息是否生成。未设置时沿用 `write_artifacts`，设置后不再被 artifact 开关隐式绑死。
- `ctg_pure_cycle_parallel_workers`：控制 pure-cycle 切口候选评估进程数。默认由正式 adapter 配置，设为 `0` 或 `1` 时走顺序评估。

这些参数是运行控制，不是算法语义参数。开启或关闭并行后，pure-cycle 切口、inner/outer path 和最终覆盖语义必须一致。

## 辅助链路约束

`shelf_ctg_auxiliary_build_sweeps` 默认关闭。关闭时辅助链路只构造正式规划需要的 edge/junction label map，不全量物化无效 sweep；开启时才恢复 sweep 级调试构造。

owner map 的单 seed 连通分量快路径只允许跳过无竞争 BFS，不允许改变多 edge seed 分量内的归属规则。相关逻辑必须有白盒测试覆盖。

## ShelfAware 孤立跳变治理

`shelf_aware` 的最终路径允许启用孤立跳变治理。该逻辑只处理最终路径序列中的异常小片段，不回写 sweep、CTG 或底层节点访问状态。

识别条件：

- 片段前后都是超过 `isolated_jump_distance_m` 的长跳。
- 片段点数不超过 `isolated_jump_max_points`。
- 片段内部路径长度不超过 `isolated_jump_max_length_m`。

处理顺序：

- 若片段靠近主路径其它位置，并且回插后的总代价满足 `isolated_jump_reinsert_improvement_ratio`，则插回更合适的位置。
- 若回插不合适，则把片段作为 inactive fragment 从最终路径中移除。
- 打开 artifacts 时，处理结果写入 `isolated_jump_cleanup.json`，并在 `metadata.json` 中记录摘要。

## 验收要求

每轮性能优化后至少执行：

```bash
python3 -m pytest -q \
  tests/test_coverage_preprocessing.py \
  tests/test_maptools_coverage_planning_adapter.py \
  tests/test_coverage_router.py \
  tests/test_channel_topology_graph_adapter.py \
  tests/test_coverage_semantic_baseline_tool.py \
  algorithms/channel_topology_graph/tests/test_junction_rebuild.py \
  algorithms/channel_topology_graph/tests/test_junction_rebuild_integration.py
```

若改动触及真实地图行为，还必须重新生成或比较 beiguo_lanshan 语义基线。
