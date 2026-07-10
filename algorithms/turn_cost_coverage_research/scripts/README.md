# 研究脚本入口说明

## 推荐入口

shelfAware 基线：

```bash
algorithms/turn_cost_coverage_research/.venv/bin/python \
  algorithms/turn_cost_coverage_research/scripts/baseline/run_shelf_aware_all_areas.py
```

ShelfAware+TurnCost 候选基线门禁：

```bash
algorithms/turn_cost_coverage_research/.venv/bin/python \
  algorithms/turn_cost_coverage_research/scripts/baseline/run_candidate_baseline_gate.py
```

ShelfAware+TurnCost 正式交付门禁：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. \
algorithms/turn_cost_coverage_research/.venv/bin/python \
  algorithms/turn_cost_coverage_research/scripts/baseline/run_shelf_aware_turn_cost_delivery_gate.py
```

该入口用于收敛验收，不用于调参实验。它串联检查：

- 已禁止恢复的候选引用旧壳符号；
- UI / factory / profile / formal planner mode 契约测试；
- coverage graph / graph access 契约测试；
- traversal core 关键测试；
- scoring / candidate evaluation 契约测试；
- final path realization / transform record / final provenance / artifact 输出关键测试；
- 三项目全区域 `shelf_aware_turn_cost` 候选效果基线。

默认 `--baseline-summary` 指向本地固定证据资产：

```text
algorithms/turn_cost_coverage_research/baselines/shelf_aware_turn_cost_20260617/summary.json
```

该文件是可提交轻量 fixture，只保留三项目 19 区域的 `summary.json` 和 `path_pixels.json`。该文件缺失、被替换或 case 数不是 19 时，正式 delivery gate 必须失败。

`run_candidate_baseline_gate.py` 可以单独用于局部预检；只有显式传 `--expected-baseline-case-count 0` 时才允许不检查 19 区域 case 数。最终收口证据必须使用 `run_shelf_aware_turn_cost_delivery_gate.py`。

## 目录语义

- `baseline/`：当前可进入 UI 的 shelfAware 基线入口。
- `diagnostics/`：只读诊断入口，不修改路径。
- `experiments/`：研究实验入口，可生成改写路径，但不得直接作为 UI 主线。
- `archived/`：已否定或不再推荐的历史入口，只用于历史实验重放。

## 旧入口

根目录下不再保留 `scripts/run_*.py` 兼容 wrapper。新代码、新文档和后续自主推进只使用分层目录下的 canonical 入口。
