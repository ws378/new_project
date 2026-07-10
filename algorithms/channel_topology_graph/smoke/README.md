# CTG Smoke 目录说明

本目录承载 `channel_topology_graph` 的人工/轻量 smoke 入口。

当前子目录：

- `real_case/`
  - 基于真实 case 的阶段级 smoke 运行脚本
- `visual/`
  - 以可视化为主的轻量 smoke 入口

边界约束：

- `smoke/` 只放手动触发或轻量验证脚本
- 正式自动化测试应留在 `tests/`
- 批量 case 组织与报告治理应留在 `coverage_dataset/`
- smoke 运行产物属于生成物，不是源码真值
