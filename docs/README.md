# 仓库级文档索引

根层 `docs/` 只承载仓库级长期文档，不保存执行流水账，也不替各子工程维护产品说明。

## 目录职责

- `governance/`
  - 覆盖规划工程长期治理事实：架构边界、当前代码入口、稳定决策、未闭合缺口和文档治理规则。
- `validation/`
  - 仓库级覆盖规划验证矩阵、提交前检查口径和下游链路说明。
- `operations/`
  - 跨机器协作、远程访问等可重复执行的操作流程。
- `archive/`
  - 已退出当前运行面的历史材料。归档文档只能解释历史来源，不能作为当前运行入口。

## 子工程文档入口

- `maptools/README.md`
  - 地图编辑器子工程入口。
- `maptools/docs/`
  - 地图编辑器需求、设计、使用说明和专题计划。
- `algorithms/README.md`
  - 算法集合子工程入口。
- `algorithms/coverage_planning/docs/`
  - `coverage_planning` 正式覆盖规划算法域文档。
- `algorithms/channel_topology_graph/docs/`
  - `channel_topology_graph` 算法工程文档。
- `coverage_dataset/README.md`
  - 测试集子工程入口。
- `coverage_dataset/docs/`
  - 测试集工程文档。

## 新增文档规则

- 新文档必须先归属到仓库级、一级子工程或算法/数据子工程，不能直接平铺到根层。
- 长期文档只记录稳定事实、设计、代码入口、验证口径、决策和已确认缺口。
- 执行过程、临时计划、弱门禁聊天记录、阶段性恢复卡不得进入长期文档；其中的稳定结论应吸收到 `governance/` 或对应子工程文档后删除原记录。
