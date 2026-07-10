# Shelf-Aware CTG 研究治理文档

本目录用于承载 `shelf_aware_ctg_research` 后续研究算法的开工前准备、阶段计划、验收入口和执行记录。

这里的目标不是继续做组合算法，也不是把 axis 独立规划结果作为对比对象，而是按“先诊断，再模块优化”的顺序推进：

1. 固定 `shelf_aware_guarded` baseline。
2. 用 CTG / expanded territory / edge axis 作为辅助图层和诊断证据。
3. 诊断 path、territory、jump、grid node 质量。
4. 形成 residual / optional / snap / insert 判据。
5. 在研究目录内验证 grid node optionalization / residual pruning。
6. 只有证据充分后，再决定 territory 或 axis 是否进入正式 planner。

## 文档结构

- `00_background/`：记录研究背景、当前资产、输入输出和已确认结论。
- `10_architecture/`：定义研究架构、模块边界、禁止事项和数据真值。
- `20_execution_plan/`：定义阶段计划、自主推进规则和弱门禁口径。
- `30_preflight/`：定义每批开工前必须检查的范围、目录、测试和 Git 边界。
- `40_execution_records/`：记录每个正式研究批次的目标、实施、验收和提交状态。

## 当前总口径

- 主体 planner：`shelf_aware_guarded` baseline。
- CTG / territory / axis：辅助信息，不独立形成全局路径。
- 当前优先级：B/C/D 诊断 > E 判据 > F 研究版 pruning > G territory/axis 接入评估。
- 当前禁止：不恢复独立 axis 路径比较，不直接做 CTG-guided 组合算法，不把原始 edge label 当强约束。
