# CTG Baselines 目录说明

本目录承载 `channel_topology_graph` 工程内需要长期保留的基线样本与对照资产。

当前子目录：

- `channel_topology_graph_refactor/`
  - 主线结构调整相关的阶段基线
- `coverage_planning_refactor/`
  - coverage planning 子域重构相关基线

边界约束：

- 这里保存“需要长期跟踪的少量基线资产”
- 大批量运行结果、临时调试输出和人工审图图集应留在 `coverage_dataset/reports/`
- 若某个基线不再承担长期 compare 价值，应从这里清理或降级，不要把 `baselines/` 变成历史报告堆积区
