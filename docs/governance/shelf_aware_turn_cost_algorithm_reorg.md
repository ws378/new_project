# ShelfAware TurnCost 算法重构治理

本文冻结 `shelf_aware_guarded` 与 `shelf_aware_turn_cost` 重构前的基线、领域模型、准入门禁和分批顺序。目标是先把事实源和边界定清楚，再做目录与代码重构；本文不是执行流水账。

## Step 0：现状基线冻结

当前正式运行入口：

- `algorithms/coverage_planning/modes.py`
  - `basic`、`shelf_aware`、`shelf_aware_turn_cost` 是 formal factory mode。
  - `auto` 是 router mode。
  - `channel_topology_graph` 是 adapter-only mode。
- `algorithms/coverage_planning/planner_factory.py`
  - `run_formal_planner_request(...)` 是显式 formal planner request 入口。
  - `shelf_aware` 和 `shelf_aware_turn_cost` 都创建 `ShelfAwareCoveragePlanner`。
- `algorithms/coverage_planning/profiles.py`
  - `shelf_aware_turn_cost` 当前 profile 为 `shelf_aware_turn_cost_repaired_grid_0_28`。
  - `profile_status` 为 `candidate_enhancement`，不是完整论文 turn-cost formal 算法。
  - default overrides：
    - `shelf_ctg_auxiliary_enable=True`
    - `shelf_node_generation_mode=turn_cost_repaired_grid`
    - `shelf_repaired_grid_max_offset_factor=0.28`
    - `isolated_jump_cleanup_enable=False`

floor3 area5 现状基线来自本机临时证据 `/tmp/maptools_floor3_area5_runtime/summary.json`。该路径是运行证据，不提交为长期资产；每次行为重构前应重新生成或确认等价证据。

| mode | 成功数 | planner 均值 | planner 范围 | total 均值 | 末次点数 | coverage_ratio | long_jump_count |
|---|---:|---:|---:|---:|---:|---:|---:|
| `basic` | 3/3 | `0.192s` | `0.185-0.206s` | `0.396s` | 1690 |  |  |
| `shelf_aware` | 3/3 | `18.867s` | `18.828-18.909s` | `19.037s` | 1663 | `0.9968527604` | 12 |
| `shelf_aware_turn_cost` | 3/3 | `17.113s` | `17.066-17.180s` | `17.271s` | 1320 | `0.9986251887` | 23 |

现有测试和验证入口：

- 单元/契约测试：
  - `tests/test_coverage_planner_modes.py`
  - `tests/test_planner_factory_modes.py`
  - `tests/test_shelf_aware_*`
  - `tests/test_coverage_repo_export_diagnostics.py`
- 批量候选验证脚本：
  - `algorithms/turn_cost_coverage_research/scripts/baseline/run_shelf_aware_all_areas.py`
  - `algorithms/turn_cost_coverage_research/scripts/baseline/run_shelf_aware_turn_cost_delivery_gate.py`
- 局部重构回归最小口径：
  - `floor3 area5` 同参数下 `shelf_aware` 与 `shelf_aware_turn_cost` 指标不漂移。
  - 相关 `tests/test_shelf_aware_*` 与 `tests/test_coverage_planner_modes.py` 通过。

## Step 1：领域模型冻结

### 核心对象

| 对象 | 当前主要代码 | 主身份 | 创建者 | 可修改者 | 生命周期 | 分层 |
|---|---|---|---|---|---|---|
| `PlannerConfig` | `./models.py` | 一次 planner run 的内部配置对象 | `ShelfAwareCoveragePlanner._build_planner_config(...)` | 创建后不应被运行态修改 | 单次规划 | 静态配置 |
| `CoverageCell` / `CellCandidate` | `grid_builder.py` | `cell_id = r{grid_row}_c{grid_col}` | `build_cell_candidates(...)` | graph build 阶段内部 | coverage graph 构建到 artifact 输出 | 静态模型 |
| `CoverageGraph` / `CoverageGraphView` | `coverage_graph.py` | `cell_id` 集合和邻接关系 | `build_coverage_graph(...)` | 创建后只读 | traversal 与 final path 阶段 | 静态模型 |
| legacy `Node` | `models.py`、`build_legacy_node_matrix(...)` | 派生自 `cell_id` | graph build adapter | 迁移期 adapter 内部 | 过渡期 traversal 兼容 | legacy adapter |
| `TraversalState` | `traversal_state.py` | 当前 run 的访问历史 | `TraversalState.from_start(...)` | traversal commit 阶段 | traversal loop | 运行态 |
| `TraversalCursor` | `traversal_cursor.py` | 当前 `cell_id` | traversal loop | traversal loop | 单步选择到下一步提交 | 运行态 |
| `TraversalCandidateRef` | `traversal_candidate_ref.py` | 候选 `cell_id` | candidate enumeration | 只读 | 单步选择 | 候选动作 |
| `CandidateScoreBreakdown` | `candidate_scoring.py` | 单候选评分结果 | candidate scoring | 只读 | 单次候选评分 | 诊断态/选择辅助 |
| `CandidatePhaseSelection` | `traversal_candidate_summary.py` | phase + selected `cell_id` | phase selector | 只读 | 单步选择到 commit | 运行态摘要 |
| `MoveTrace` | `traversal_move.py` | `move_id` / path index | move commit | 只追加 | traversal 输出到 artifact | 诊断态 |
| `FinalPath` | `final_path/realization.py` | path point sequence order | final path realization | final path 阶段 | result 输出 | 输出态 |
| `Artifact` | `artifacts/` | artifact schema + path | artifact writer | artifact writer | run 输出目录 | 诊断态/导出态 |

### 主身份规则

- 覆盖图节点的唯一主身份是 `cell_id`，当前格式由 `grid_row` 和 `grid_col` 派生。
- `grid_row/grid_col` 是 `cell_id` 的结构化来源，不是额外主身份。
- `planning_point_px`、`grid_center_px`、world pose 都是空间表达或输出表达，不是节点身份。
- traversal 的运行态访问记录必须以 `cell_id` 为准，不以 pixel point 或 legacy `Node` 对象地址为准。
- artifact 中的 node id、move id、path index 只能解释当前 run，不能反向成为下一次算法输入的事实源。

### 分层边界

静态模型：

- `PlannerConfig`
- `CoverageCellGrid`
- `CoverageGraphView`
- 方向场、CTG edge label、region mask
- node generation profile

运行态：

- `TraversalState`
- `TraversalCursor`
- history clearance index
- local residual / frontier 临时统计
- candidate phase selection

诊断态：

- candidate decision debug
- fallback debug trace
- move trace
- score components
- pipeline trace
- node debug enriched payload

输出态：

- `CoveragePlanningResult`
- `path_pixels`
- world path / poses
- final segment provenance
- artifact manifest

禁止规则：

- 静态模型不得读取运行态状态。
- 正式算法不得从 artifact/debug payload 反向读取事实。
- 产品入口参数不得直接承担 traversal 内部状态。
- legacy `Node` 只能作为迁移期 adapter；不能和 `CoverageGraphView` 同时成为主事实源。

## Step 2：Research Delivery Gate

当前状态：

- `shelf_aware`：formal baseline。
- `shelf_aware_turn_cost`：candidate enhancement。
- `turn_cost_repaired_grid`：candidate default 的节点生成策略。
- `algorithms/turn_cost_coverage_research/src`：research/diagnostics/experiments，默认不得进入 formal 入口。

准入矩阵：

| 维度 | 当前固定口径 |
|---|---|
| 固定输入集合 | 至少包含 `examples/maptools_projects/beiguoshangcheng_floor_3` `area_id=5`；正式 gate 继续使用三项目全区域矩阵。 |
| 参数来源 | 项目保存参数 `coverage_planner_params.json` 加 `shelf_aware_turn_cost` profile default overrides。 |
| 运行入口 | `run_formal_planner_request(request, "shelf_aware_turn_cost")`。 |
| 关键指标 | success、point_count、coverage_ratio、long_jump_count、length_px、planner_elapsed_s、diagnostics profile。 |
| 局部通过阈值 | 重构不改变算法行为时，floor3 area5 的点数、coverage_ratio、long_jump_count 应保持不漂移；若有预期变化，必须进入独立算法变更批次。 |
| 证据路径 | 临时运行证据写 `/tmp`；长期只提交摘要、baseline 或门禁结果，不提交大型运行目录。 |
| 回滚点 | 保持 `shelf_aware` formal baseline 可运行；`shelf_aware_turn_cost` profile 可通过 default overrides 定位。 |

不得直接迁入 formal 的内容：

- `algorithms/turn_cost_coverage_research/src/guidance`
- `algorithms/turn_cost_coverage_research/src/official_replacements`
- `algorithms/turn_cost_coverage_research/src/experiments`
- archived scripts 和一次性实验输出
- 没有固定参数、指标、失败边界和回滚方式的 research 代码

## Step 3：Batch Refactor

重构按领域批次推进。每批先审查、再集中改、再验证；禁止边看边改跨领域文件。

| 批次 | 范围 | 目标 | 不处理内容 | 最小验证 |
|---|---|---|---|---|
| 1 | 入口 / profile / config | 固定 `shelf_aware` 与 `shelf_aware_turn_cost` 的入口、profile、默认参数和 diagnostics 契约 | 不搬 traversal 和 graph 代码 | `tests/test_coverage_planner_modes.py`、`tests/test_planner_factory_modes.py` |
| 2 | coverage graph / node generation | 将 `grid_builder`、`coverage_graph`、`node_generation`、legacy node adapter 分包 | 不改候选评分和 final path | `tests/test_shelf_aware_grid_builder.py`、`tests/test_shelf_aware_coverage_graph_stage.py`、floor3 area5 指标 |
| 3 | traversal / candidate / scoring | 收束 traversal loop、candidate enumeration、phase selector、score breakdown、state ownership | 不改 node generation profile | `tests/test_shelf_aware_traversal_*`、floor3 area5 指标 |
| 4 | final path / semantic / postprocess | 收束 simplify、semantic CTG、isolated jump cleanup、path geometry 输出 | 不改 traversal 选择策略 | `tests/test_shelf_aware_final_path_realization.py`、artifact summary 检查 |
| 5 | artifact / debug 隔离 | 明确 artifact 只读消费事实源，移除 debug 对算法模型的反向耦合 | 不新增算法策略 | `tests/test_shelf_aware_artifact_*`、manifest/sidecar contract 测试 |
| 6 | pipeline / geometry 结构收口 | 将阶段边界和房间几何工具下沉到正式包，清空顶层阶段散文件 | 不拆 `models.py`，不改算法策略 | `tests/test_shelf_aware_*.py`、旧路径引用扫描 |
| 7 | 删除历史包壳 | 删除 `energy_functional` 历史命名边界，将正式子包上移到 `shelf_aware_guarded/` | 不拆 `models.py`，不改算法策略 | `tests/test_shelf_aware_*.py`、planner factory/mode/UI 测试、旧路径引用扫描 |

每批提交说明必须包含：

- `影响范围`
- `验证情况`
- `证据路径`
- `关联跟踪`
- 已知风险和未处理缺口

### 当前批次进展

- 批 1 已收束顶层 coverage-planning contract re-export，外部调用可从 `algorithms.coverage_planning` 获取 `shelf_aware_turn_cost` profile metadata、default overrides 和 repaired-grid 参数常量。
- 批 2 已将 coverage graph / node generation 实现迁入 `graph_build/`：
  - `coverage_graph.py`
  - `grid_builder.py`
  - `grid_topology.py`
  - `node_alignment.py`
  - `node_filtering.py`
- 原 `{coverage_graph,grid_builder,grid_topology,node_alignment,node_filtering}.py` 顶层兼容壳已删除。新代码和测试必须使用 `shelf_aware_guarded.graph_build.*`。
- 批 2 没有改变 graph build 行为；floor3 area5 回归指标与 Step 0 冻结基线一致。
- 批 3 已将 traversal / candidate / scoring 实现迁入 `traversal_core/`：
  - `candidate_scoring.py`
  - `traversal.py`
  - `traversal_candidate_*.py`
  - `traversal_cursor.py`
  - `traversal_decision_debug.py`
  - `traversal_graph_access.py`
  - `traversal_history_clearance.py`
  - `traversal_move*.py`
  - `traversal_phase_*.py`
  - `traversal_reachability.py`
  - `traversal_roles.py`
  - `traversal_scoring_context.py`
  - `traversal_state.py`
  - `traversal_step_selection.py`
- 原 `{candidate_scoring,traversal,traversal_*}.py` 顶层兼容壳已删除。新代码和测试必须使用 `shelf_aware_guarded.traversal_core.*`。
- 批 3 没有改变 traversal 选择策略；`tests/test_shelf_aware_*.py` 已通过，floor3 area5 回归指标继续对齐 Step 0 冻结基线：
  - `shelf_aware`：证据 `/tmp/maptools_batch3_traversal_reorg_regression/run_20260622_114903_898813_shelf_aware_all_areas/summary.json`，`point_count=1663`，`coverage_ratio=0.9968527604054346`，`long_jump_count=12`，`length_px=23404.177442683475`。
  - `shelf_aware_turn_cost`：证据 `/tmp/maptools_batch3_traversal_reorg_regression/run_20260622_114945_990357_shelf_aware_turn_cost_all_areas/summary.json`，`point_count=1320`，`coverage_ratio=0.9986251886995903`，`long_jump_count=23`，`length_px=20303.044378566643`。
- 批 4 已将 final path / semantic / postprocess 实现迁入 `final_path/`：
  - `realization.py`
  - `transform_record.py`
  - `postprocess.py`
  - `jump_cleanup.py`
  - `node_semantics.py`
  - `semantic_path.py`
- 原 `{final_path_realization,final_path_transform_record,path_postprocess,path_jump_cleanup}.py` 和 `semantic_ctg/{node_semantics,semantic_path}.py` 兼容壳已删除，`semantic_ctg/` 空目录也已删除。新代码和测试必须使用 `shelf_aware_guarded.final_path.*`。
- 批 4 没有改变 traversal 选择策略、semantic path 策略或 isolated jump cleanup 策略；本批已通过 final path / semantic / postprocess 目标测试，floor3 area5 回归指标继续对齐 Step 0 冻结基线：
  - `shelf_aware`：证据 `/tmp/maptools_batch4_final_path_reorg_regression/run_20260622_115543_585208_shelf_aware_all_areas/summary.json`，`point_count=1663`，`coverage_ratio=0.9968527604054346`，`long_jump_count=12`，`length_px=23404.177442683475`。
  - `shelf_aware_turn_cost`：证据 `/tmp/maptools_batch4_final_path_reorg_regression/run_20260622_115626_708235_shelf_aware_turn_cost_all_areas/summary.json`，`point_count=1320`，`coverage_ratio=0.9986251886995903`，`long_jump_count=23`，`length_px=20303.044378566643`。
- 批 4 P2 边界债务：`final_path/postprocess.py` 仍包含 traversal 在线候选使用的 `violates_shape_constraints` 和 `point_distance`。当前为保持行为不漂移只做目录收束；后续若要进一步纯化，应单独把在线形状约束抽到 traversal 几何 helper，并跑 traversal 回归。
- 批 5 已收束 artifact / debug 与算法事实源边界：
  - `path_visualization.py` 实现迁入 `artifacts/path_visualization.py`；原顶层兼容壳已删除。
  - traversal 运行期 debug payload 构造迁入 `traversal_core/traversal_debug_payloads.py`；`traversal_core` 不再直接 import `shelf_aware_guarded.artifacts`。
  - `artifacts/__init__.py` 只公开 artifact orchestration 入口：`PlannerArtifactContext` 和 `write_planner_artifacts`。
  - `artifacts/node_debug.py` 只负责 JSON 写出和复用 traversal debug payload，不再同时承担运行期 selector helper 的主事实源。
- 批 5 没有新增算法策略；artifact/debug 仍只能消费 graph/traversal/final path 的快照与 payload，不能反向作为算法输入。floor3 area5 回归指标继续对齐 Step 0 冻结基线：
  - `shelf_aware`：证据 `/tmp/maptools_batch5_artifact_reorg_regression/run_20260622_120111_328042_shelf_aware_all_areas/summary.json`，`point_count=1663`，`coverage_ratio=0.9968527604054346`，`long_jump_count=12`，`length_px=23404.177442683475`。
  - `shelf_aware_turn_cost`：证据 `/tmp/maptools_batch5_artifact_reorg_regression/run_20260622_120154_264477_shelf_aware_turn_cost_all_areas/summary.json`，`point_count=1320`，`coverage_ratio=0.9986251886995903`，`long_jump_count=23`，`length_px=20303.044378566643`。
- 批 6 已收束 pipeline / geometry 顶层散文件：
  - 阶段文件迁入 `pipeline/`：`input_validation.py`、`room_rotation.py`、`direction_field.py`、`coverage_graph.py`、`start_cell.py`、`graph_traversal.py`、`output_assembly.py`、`artifact_write.py`。
  - pipeline 契约迁入 `pipeline/trace.py` 和 `pipeline/summaries.py`。
  - 房间旋转与像素点变换工具迁入 `geometry/room_rotation.py`。
  - 原顶层阶段文件和 `room_rotator.py` 不保留兼容壳；正式代码和测试必须直接使用新路径。
- 批 6 不拆 `models.py`，不改变 coverage graph、traversal、final path 或 artifact 行为；`models.py` 后续按 config/domain/artifact contract 单独成批拆分。
- 批 7 已删除 `energy_functional/` 历史包壳：
  - `planner.py` 成为 `shelf_aware_guarded` 下正式主编排入口，导出 `plan_coverage_path(...)`。
  - `models.py`、`pipeline/`、`graph_build/`、`traversal_core/`、`final_path/`、`direction/`、`region/`、`artifacts/`、`geometry/` 全部位于 `shelf_aware_guarded/` 直接子级。
  - `shelf_aware_guarded/__init__.py` 作为正式聚合入口导出 `ShelfAwareCoveragePlanner`、`plan_coverage_path` 和必要配置类。
  - 不保留 `energy_functional` 兼容包或 re-export。
- 批 7 不拆 `models.py`，不改变算法策略；本批仅删除失效历史命名边界。

## Step 4：长期文档治理

文档治理在领域模型和重构批次稳定后执行，不作为第一步。本轮已在七个代码批次和 floor3 area5 回归闭合后执行。

保留类型：

- 当前算法入口与 profile 边界
- 领域模型冻结结论
- `shelf_aware_turn_cost` candidate gate
- 验收矩阵和基线摘要
- 已知缺口
- 稳定决策记录

删除或吸收类型：

- 执行流水账
- 临时推进计划
- 重复实验复盘
- 已被正式设计吸收的过程记录
- 大型运行输出索引
- 没有维护入口的截图或临时资产说明

治理后长期入口应能回答：

- 当前正式代码入口在哪里。
- `shelf_aware_turn_cost` 为什么只是 candidate enhancement。
- coverage graph、traversal、candidate、final path、artifact 各自的事实源是什么。
- 后续重构每批怎么验证不漂移。

本轮处理结果：

- `algorithms/turn_cost_coverage_research/docs/04_开发/当前推进/` 已删除；当前推进、批次约束和上下文恢复结论已由本文、主题文档、代码事实和验证入口吸收。
- `algorithms/turn_cost_coverage_research/docs/04_开发/codex技能草案/` 已删除；正式 skill 来源在用户的 Codex skills 目录，不在项目长期 docs 中复制。
- `algorithms/turn_cost_coverage_research/docs/04_开发/文档治理/` 已删除；长期治理规则收敛到仓库级 `docs/governance/`，研究 docs 不再保存删除吸收流水账。
- `algorithms/turn_cost_coverage_research/docs/04_开发/` 仅保留长期治理决策记录。
- 已扫描并修正 active docs 中对被删除路径的引用；旧过程材料需要追溯时使用 git 历史，不作为当前真值。
- 已删除 `energy_functional` 历史包壳、顶层非必要兼容壳和 `semantic_ctg` 旧壳；正式代码、研究脚本和测试已切到 `shelf_aware_guarded/{graph_build,traversal_core,final_path,artifacts,pipeline,geometry,direction,region}` 新路径。

## 未闭合缺口

- final path postprocess helper 中仍混有 traversal 在线形状约束函数，领域纯化删除条件未完成。
- legacy `Node` adapter 仍在 graph build 与 traversal 之间存在，删除条件未完成。
- `models.py` 仍同时承载 `Node`、配置对象和 artifact 返回对象，尚未按 config/domain/artifact contract 拆分。
- pipeline trace 当前有阶段摘要，但缺少稳定的 per-stage timing contract。
- `turn_cost_coverage_research/docs` 仍包含当前推进、文档治理、技能草案等开发态内容；需在代码边界稳定后用长期文档治理吸收或删除。
