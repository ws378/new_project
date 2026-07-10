# shelfAwareTurnCost 收敛验收清单

本文定义 `shelf_aware_turn_cost` 作为 UI 显式候选增强入口时必须满足的验收口径。它不保存历史批次日志、单次测试长表或 output run 时间线。

## 1. 当前定位

`shelf_aware_turn_cost` 当前只能定位为：

```text
UI-ready candidate mode
```

它不能被描述为：

- `shelf_aware` 的无风险替代；
- 默认 planner；
- 论文 official turn-cost planner；
- 研究脚本最终后处理结果；
- 几何安全硬约束已闭环的版本。

当前正式入口和能力边界见 `01_主题/01_算法入口与能力边界.md`。

## 2. 必须满足的验收域

| 验收域 | 必须满足的条件 | 主要证据入口 |
| --- | --- | --- |
| mode/profile | `shelf_aware_turn_cost` 是明确 mode/profile，强制默认值可追溯。 | `02_代码事实/01_正式代码入口与依赖边界.md`、`01_主题/02_shelfAwareTurnCost算法设计/02_输入输出与模式契约.md` |
| UI/export | UI 可显式选择；参数显隐、profile notice、diagnostics 详情和 coverage repo 导出不混淆 mode。 | `05_验证/04_GUI交互级验收边界与手工验收清单.md` |
| 主流程 | 主流程以 shelfAware 正式路径器为主体，turn-cost 价值只通过已设计的节点生成、候选决策和 provenance 融合。 | `01_主题/02_shelfAwareTurnCost算法设计/04_主流程与遍历决策.md` |
| 覆盖图/遍历状态 | 静态覆盖图、动态遍历状态和旧 `Node` shell 不形成双真值。 | `01_主题/02_shelfAwareTurnCost算法设计/03_覆盖图与节点生成模型.md` |
| final path/artifact | `CoveragePlanningResult` 是正式输出；diagnostics 和 artifact 只解释结果，不反向定义路径。 | `01_主题/02_shelfAwareTurnCost算法设计/05_路径实现与诊断产物.md` |
| 多区域效果 | 三项目 19 区域可复跑，关键指标不突破候选基线守卫。 | `05_验证/当前基线/20260617_shelfAwareTurnCost候选基线.md` |
| 研究资产边界 | experiments / archived / output 单 run 不被误接入 formal planner。 | `02_代码事实/02_研究代码与脚本生命周期.md`、`02_代码事实/03_output证据资产规则.md` |

## 3. 交付门禁

正式收口入口：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. \
algorithms/turn_cost_coverage_research/.venv/bin/python \
  algorithms/turn_cost_coverage_research/scripts/baseline/run_shelf_aware_turn_cost_delivery_gate.py
```

该门禁必须至少覆盖：

- forbidden runtime symbol 检查；
- formal contract tests；
- UI contract tests；
- export contract tests；
- coverage graph contract tests；
- traversal core tests；
- scoring contract tests；
- final path / provenance tests；
- 三项目 19 区域候选效果基线对比。

最新可信候选基线和 run 证据不写在本文正文，统一维护在：

```text
05_验证/当前基线/20260617_shelfAwareTurnCost候选基线.md
```

## 4. 指标守卫

指标守卫的唯一契约入口是：

```text
05_验证/03_测试分层与marker规则.md
```

本文只规定必须有指标守卫，不维护第二份硬门禁或只读指标名单。若新增、删除或调整指标阈值，必须修改 `03_测试分层与marker规则.md` 以及对应的 `effect_metric_contract.py`，再由本文引用。

诊断指标不能被忽略；它们用于缺口管理和下一轮算法研究，但当前不能在没有充分多区域证据时直接升级为硬约束。

## 5. 不能宣称完成的事项

以下事项仍未完成，不能因为当前 candidate mode 可用而误判为已闭环：

- `shelf_aware_turn_cost` 成为默认算法；
- geometry readonly diagnostics 在正式 planner 内自动运行或成为硬约束；
- 长期 `Node` shell 完全退出；
- lane family / topology source / coverage contribution 语义建模；
- 线距、交叉、窄通道、急转等诊断指标升级为硬门禁；
- output rejected / archived 研究证据完成代表性归档或压缩；
- official paper algorithm 的发布级复现包。

这些事项必须进入 `03_缺口/01_当前缺口总表.md` 或后续专项设计，不允许混在验收清单里变成历史状态堆积。

## 6. 禁止恢复

为了保持验收边界稳定，禁止恢复：

- `ShelfAware 原版` 和 `ShelfAware UI 稳定版` 两个并列 UI 选项；
- 根目录 `scripts/run_*.py` 兼容 wrapper；
- research experiments 直接 import 到 formal planner；
- batch reconnect、全路径节点吸附、删点、shortcut、lane 平移作为默认行为；
- 旧 `Node.visited` / `Node.visit_count` 作为算法动态状态来源；
- raw output run 反向定义算法、参数或验收阈值。

## 7. 验收失败处理

出现以下任一情况时，`shelf_aware_turn_cost` 不得继续扩大使用范围：

- delivery gate 失败；
- 三项目 19 区域候选基线无法复跑或 case 数不一致；
- path identity 守卫失败且没有明确设计变更说明；
- 覆盖率、长跳、不可信段等硬守卫退化；
- UI/export 显示的 mode、profile、参数生效值或 artifact 路径不可追溯；
- 研究脚本或 archived 脚本被误接入 formal planner。

处理顺序：

1. 先定位失败属于代码、测试、环境、基线还是文档口径；
2. 若是算法行为变化，必须和当前候选基线比较；
3. 若是文档口径错误，修本文或相关入口文档；
4. 若是长期未闭环事项，写入缺口表；
5. 不允许用单个 area 的最终 PNG 直接覆盖门禁结论。
