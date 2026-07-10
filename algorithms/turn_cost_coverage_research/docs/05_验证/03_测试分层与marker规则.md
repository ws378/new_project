# 测试分层与 marker 规则

## 1. 目标

本文件定义 `turn_cost_coverage_research` 收敛期间的测试分层。目标是让正式入口、UI、导出、只读诊断、研究实验和论文参考复现分开执行，避免把 optional / research 测试失败误判为正式 UI 不可用。

本文定义 pytest marker 和自动标记规则，不用 marker 代替测试文件本身的断言和验收语义。

## 2. marker 列表

| marker | 中文说明 | 是否 formal 必跑 |
| --- | --- | --- |
| `formal_contract` | 正式覆盖规划契约、factory、router、preprocessing 和 planner 基础行为。 | 是 |
| `ui_contract` | UI 入口、参数显示隐藏和用户可见模式契约。 | UI 改动批必跑 |
| `export_contract` | 覆盖路径仓库导入导出和 diagnostics 导出契约。 | export/diagnostics 改动批必跑 |
| `adapter_contract` | 非 formal factory 的 adapter / routing 入口契约。 | routing 改动批必跑 |
| `shelf_grid` | ShelfAware 节点生成、路径后处理和 TurnCost repaired grid 相关契约。 | profile/node generation 改动批必跑 |
| `readonly_diagnostic` | 只读诊断、可视化诊断和资产索引，不改变路径。 | diagnostics 改动批必跑 |
| `research_experiment` | 研究性实验、后处理、候选重连和局部优化证据。 | 否 |
| `reference_reproduction` | 论文 official / 替代 solver / guidance / square8 等参考复现实验。 | 否 |
| `archived_evidence` | 历史归档证据测试。 | 否 |
| `optional_env` | 依赖可选环境、重型依赖或非 formal UI 验收必跑项。 | 否 |

## 3. 自动标记规则

自动标记规则位于：

```text
tests/conftest.py
```

规则按测试文件名添加 marker。这样可以避免在大量测试文件中重复写装饰器，也便于后续集中复核分层。

新增测试文件时应同步更新：

- `tests/conftest.py`
- 本文件的分层说明
- 必要时更新 `05_验证/01_shelfAwareTurnCost最终收敛验收清单.md` 或仓库级 `docs/governance/shelf_aware_turn_cost_algorithm_reorg.md`

## 4. 推荐命令

正式契约最小集合：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 algorithms/turn_cost_coverage_research/.venv/bin/python \
  -m pytest -q -m "formal_contract"
```

UI 改动批：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 algorithms/turn_cost_coverage_research/.venv/bin/python \
  -m pytest -q -m "ui_contract"
```

导出/诊断契约：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 algorithms/turn_cost_coverage_research/.venv/bin/python \
  -m pytest -q -m "export_contract or readonly_diagnostic"
```

排除 optional 环境的 turn-cost 研究测试：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 algorithms/turn_cost_coverage_research/.venv/bin/python \
  -m pytest -q -m "not optional_env" tests/test_turn_cost_*.py
```

## 5. 注意事项

- marker 只决定测试分层，不改变算法行为。
- `research_experiment` 失败不能直接说明 UI 正式路径失败。
- `reference_reproduction` 和 `optional_env` 失败需要先区分依赖缺失、许可证限制和算法回归。
- `readonly_diagnostic` 测试不得修改路径。
- 三项目 19 区域批量测试仍是阶段门禁，不用 marker 替代。

## 6. 效果守卫和快照工具

行为不变重构和候选增强行为变更必须使用同一套效果指标契约：

```text
algorithms/turn_cost_coverage_research/scripts/diagnostics/effect_metric_contract.py
```

不得在测试、脚本或文档中维护第二份硬门禁指标名单。

当前硬门禁指标：

| 指标 | 中文说明 | 要求 |
| --- | --- | --- |
| `coverage_ratio` | 路径 buffer 覆盖目标区域的比例。 | 不得下降超过 `coverage_epsilon`。 |
| `long_jump_count` | 相邻路径点距离超过阈值的长跳跃数量。 | 不得增加超过 `allow_count_increase`。 |
| `infeasible_segment_count` | 路径线段穿障或不可行数量。 | 不得增加超过 `allow_count_increase`。 |

当前只读风险指标：

| 指标 | 中文说明 | 口径 |
| --- | --- | --- |
| `narrow_coverage_ratio` | 窄通道区域覆盖比例。 | 暴露风险，不作为硬门禁。 |
| `turn_hotspot_count` | 局部急转热点数量。 | 暴露风险，不作为硬门禁。 |
| `lane_over_dense_count` | 局部 coverage lane 过密数量。 | 暴露线距风险，不作为硬门禁。 |
| `lane_over_sparse_count` | 局部 coverage lane 过疏数量。 | 暴露漏扫风险，不作为硬门禁。 |
| `lane_spacing_issue_count` | coverage lane 过密与过疏问题总数。 | 暴露线距均匀性风险，不作为硬门禁。 |
| `segment_crossing_count` | 路径线段交叉数量。 | 暴露局部重连和路口复杂度风险，不作为硬门禁。 |

效果快照工具：

```text
algorithms/turn_cost_coverage_research/scripts/diagnostics/build_effect_snapshot.py
```

使用边界：

- 行为不变批次应使用 `--require-path-identity`，要求同一区域 `final_path_pixels` 内容哈希一致；
- 行为改变批次不默认要求路径哈希一致，但必须显式设置 coverage、narrow coverage 和计数类风险阈值；
- 行为改变批次必须显式设置 runtime、candidate、geometry swept risk 阈值；没有这些阈值时不得进入正式行为改变阶段；
- `run_shelf_aware_turn_cost_delivery_gate.py --skip-pytest` 或 `--skip-effect-baseline` 只允许本地定位问题，不能作为正式收口证据；
- 正式收口证据必须是完整 delivery gate `status=pass`，并且三项目 19 区域 `path_identity_pass_count=19`、`comparison_fail_count=0`、`comparison_warn_count=0`。
