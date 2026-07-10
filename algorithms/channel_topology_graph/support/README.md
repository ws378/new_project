# CTG Support 目录说明

本目录承载 `channel_topology_graph` 算法工程的支撑性工具，不承载正式运行源码。

当前子目录：

- `comment_audit/`
  - 注释密度与注释覆盖检查工具
- `coverage_debug/`
  - coverage planning 相关诊断与可视化辅助工具
- `refactor/`
  - 重构期辅助脚本与快照/扫描类工具

边界约束：

- `support/` 放辅助诊断、审查、扫描、迁移类工具
- 正式 pipeline/stage/runtime 代码应留在算法主目录下的实现模块
- 只在重构期间有意义的脚本可以放在这里，但不能反向成为正式运行入口
