# Algorithms 子工程说明

本目录承载仓库内的覆盖规划算法集合，不承载 GUI、测试集运行产物或仓库级治理文档。

当前一级算法工程：

- `channel_topology_graph/`
  - aisle / shelf-like 拓扑覆盖算法
  - 自带算法级 `README.md`、`docs/`、`support/`、`baselines/`、`smoke/`
- `coverage_planning/`
  - 通用覆盖规划算法集合与路由层
  - 负责 formal contract、planner routing、room-like / mixed / guarded planner 组织
  - 自带算法级 `README.md` 与 `docs/`

文档边界：

- 算法集合这一层只维护算法总入口与一级边界说明
- 每个正式算法工程负责维护自己的 `README.md` 和 `docs/`
- 不要把某个算法的详细设计、流程方案、整改记录继续平铺到 `algorithms/` 根层

相关入口：

- `channel_topology_graph/README.md`
- `channel_topology_graph/docs/`
- `coverage_planning/README.md`
- `coverage_planning/docs/`
