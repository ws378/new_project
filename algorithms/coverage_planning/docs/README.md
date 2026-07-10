# Coverage Planning 文档说明

本目录只服务 `algorithms/coverage_planning` 算法工程。

当前工程职责：

- 定义覆盖规划 formal contract
- 组织 room-like / mixed / aisle-like 的 planner routing
- 承载通用区域覆盖 planner 与 shelf-aware guarded planner
- 通过 adapter 对接 `channel_topology_graph`

当前代码分层：

- `contracts/`
  - 正式请求、结果、适用性与诊断对象
- `planners/`
  - 具体 planner 实现
  - `region_basic/`：基础区域覆盖 planner
  - `shelf_aware_guarded/`：货架感知 guarded planner
- `routing/`
  - 适用性判断、planner 选择和 formal result 收口
- `planner_factory.py`
  - 面向调用方的稳定创建入口

文档边界：

- 本目录只维护 `coverage_planning` 算法工程自身的设计与结构说明
- `channel_topology_graph` 的阶段设计、对象契约和治理文档应留在 `algorithms/channel_topology_graph/docs/`
- GUI 交互、产品说明和使用流程应留在 `maptools/docs/`
- 测试集、case 组织和报告治理应留在 `coverage_dataset/docs/`

当前状态：

- 本算法工程已经是正式一级算法域
- 目前详细设计文档仍偏少，后续新增设计说明、对象契约和 routing 规则文档时，应优先落到本目录

当前文档：

- `01_模块边界说明.md`
  - 说明 `contracts / planners / routing / adapters / planner_factory` 的正式职责边界
