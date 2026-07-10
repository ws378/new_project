# 覆盖规划治理索引

本目录承载覆盖规划相关的仓库级长期治理事实。这里不保存“第几批执行记录”，只保存后续维护者需要依赖的稳定口径。

## 文档入口

- `coverage_planning_architecture.md`
  - 覆盖规划、地图编辑器、CTG、dataset 和工具链的长期架构边界。
- `current_code_facts.md`
  - 当前代码入口、数据契约、参数事实、运行资产规则和已退场旧入口。
- `decisions_and_gaps.md`
  - 已稳定决策、仍存在的缺口和后续处理方向。
- `shelf_aware_turn_cost_algorithm_reorg.md`
  - `shelf_aware_guarded` 与 `shelf_aware_turn_cost` 重构前的基线、领域模型、candidate gate 和分批顺序。
- `doc_governance_rules.md`
  - 根层 docs 的长期治理规则、删除/吸收边界和新增文档准入。

## 当前结论

覆盖规划正式运行面已经从早期 `python_ws`、`maptools/algorithms/region_coverage_path` 和旧 `ctc` 入口迁出，收口到一级 `algorithms/coverage_planning`、一级 `algorithms/channel_topology_graph`、`maptools` 产品适配层、`tools/coverage_planning` 标准 case runner 与 `coverage_dataset` 测试集工程。

历史材料只保留在 `docs/archive/`，不得作为当前运行入口或参数真值。
