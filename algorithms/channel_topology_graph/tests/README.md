# CTG Tests 目录说明

本目录保存 `channel_topology_graph` 算法工程的正式自动化测试。

当前测试范围：

- `geometry_preparation`
- `junction_rebuild`
- `topology_graph_build`
- `coverage_planning`
- junction rebuild integration

边界约束：

- `tests/` 负责正式自动化回归
- `smoke/` 负责人工触发或轻量 smoke 验证
- `support/` 负责诊断、扫描、审查和重构辅助工具
- 若测试需要外部 case 或批量结果，应优先从 `coverage_dataset/` 或仓库级 `tests/fixtures/` 引用，不把大体量运行结果直接沉到本目录
