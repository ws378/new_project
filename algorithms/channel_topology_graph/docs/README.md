# Channel Topology Graph 文档说明

本目录只服务 `channel_topology_graph` 算法工程。

目录分层：

- `00_core/`
  - 总体设计、术语、核心对象契约、模块边界、IO 与渲染说明
- `10_pipeline/`
  - 四阶段主流程方案：geometry preparation、junction rebuild、topology graph build、coverage planning
- `20_sweep/`
  - coverage lane、sweep 与 transition candidate 相关专题
- `30_cadence/`
  - sweep cadence、route 生成与规则分析
- `40_final_path/`
  - final coverage path 生成与 junction 连接点规则
- `50_archive/`
  - 已归档但仍需保留的历史专题
- `90_guide/`
  - 面向实现和治理的补充说明、职责图和改造清单

使用约束：

- 本目录维护 CTG 的正式设计说明、整改方案、实现说明和算法治理文档
- 不要把仓库级治理文档迁入这里
- 不要把测试集规则和报告治理文档迁入这里
- 若内容只服务 `coverage_dataset` 或 `maptools`，应放回对应子工程的 `docs/`
