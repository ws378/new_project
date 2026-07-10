# shelfAwareTurnCost 闭环验收看板

本文只定义 `shelf_aware_turn_cost` 是否可以作为候选增强方案继续保留和演进的验收口径。它不是执行记录，不记录当前 WIP，不保存历史批次命令，也不维护 run 路径长表。

算法边界看 `01_主题/02_shelfAwareTurnCost算法设计/README.md`；具体验收命令和 marker 分层看 `05_验证/03_测试分层与marker规则.md`；最终交付门禁看 `05_验证/01_shelfAwareTurnCost最终收敛验收清单.md`；当前重构治理证据看仓库级 `docs/governance/shelf_aware_turn_cost_algorithm_reorg.md`。

## 1. 闭环分组

| 闭环 | 目标 | 关闭判据 | 证据入口 |
| --- | --- | --- | --- |
| A. mode/profile/参数契约 | `shelf_aware_turn_cost` 是明确 mode/profile，不是参数隐式叠加。 | formal factory、UI/router、profile version、requested/applied 参数均可追溯。 | `01_主题/02_shelfAwareTurnCost算法设计/02_输入输出与模式契约.md`、`05_验证/03_测试分层与marker规则.md` |
| B. 主流程阶段化 | 主流程是自然阶段流水线，不是散落补丁集合。 | stage input/result 清晰，主编排只负责编排和错误传播。 | `01_主题/02_shelfAwareTurnCost算法设计/04_主流程与遍历决策.md` |
| C. 覆盖图与动态状态分离 | 静态覆盖图、动态遍历状态、旧 `Node` shell 不再混成双真值。 | 静态事实来自 coverage graph；访问状态来自 traversal state；旧 `Node` 不承担动态 mirror。 | `01_主题/02_shelfAwareTurnCost算法设计/03_覆盖图与节点生成模型.md` |
| D. turn-cost 价值融合 | turn-cost 价值自然进入节点生成、候选评分、转角代价和 provenance。 | 规则覆盖图、转角代价、方向引导和来源追溯已进入主流程；线距稳定性作为验收守卫或后续缺口维护。 | `01_主题/02_shelfAwareTurnCost算法设计/01_算法定位与边界.md`、`01_主题/02_shelfAwareTurnCost算法设计/04_主流程与遍历决策.md` |
| E. diagnostics / artifact 主从关系 | 诊断和 artifact 解释路径，但不成为第二套路径真值。 | `CoveragePlanningResult` 是正式输出；diagnostics 是摘要；artifact 是证据。 | `01_主题/02_shelfAwareTurnCost算法设计/05_路径实现与诊断产物.md` |
| F. 测试、基线、资产治理 | 候选增强方案可复跑、可比较、可退回。 | 固定测试集、候选基线、output 资产规则和 deletion gate 一致。 | `05_验证/01_shelfAwareTurnCost最终收敛验收清单.md`、`02_代码事实/03_output证据资产规则.md` |

## 2. 不可关闭条件

出现以下任一情况时，对应闭环不得标记为完成：

- `shelf_aware` 和 `shelf_aware_turn_cost` 的 mode 身份混淆；
- profile 只能从零散 if/else 或 UI 默认参数推断；
- 主流程依赖 connector、fallback、postprocess 扩张出的补丁分支；
- 静态覆盖图和动态遍历状态存在双重真值；
- 旧 `Node.visited` / `Node.visit_count` 继续作为算法动态状态来源；
- candidate、fallback、revisit、final segment 没有统一 provenance；
- diagnostics、artifact、result 之间字段互相复制，无法判断主从；
- 只用单一区域或最终 PNG 证明行为正确；
- 结构重构后核心指标退化且没有解释或回滚；
- 为了旧实验脚本保留非必要正式兼容分支。

## 3. 必须覆盖的测试层级

| 层级 | 必须覆盖的内容 |
| --- | --- |
| 单元测试 | stage input/result、graph access、traversal state、candidate ref、move commit、artifact schema。 |
| 契约测试 | formal factory mode、profile 解析、UI/router adapter 边界、diagnostics summary。 |
| 行为守卫 | 轻量冒烟可覆盖 `beiguoshangcheng_floor_3 area5`，但正式行为守卫必须回到三项目 19 区域候选基线。 |
| 批量基线 | 三项目全区域固定用例可重跑，并与当前候选基线比较。 |
| 几何只读诊断 | 车体扫掠风险、转弯 yaw 风险、真实清扫覆盖与 buffer 覆盖差异可读。 |
| 资产治理 | output manifest、删除候选、轻量基线和证据路径可追溯。 |

## 4. 指标守卫

指标守卫、硬门禁与只读风险字段只由 `05_验证/03_测试分层与marker规则.md` 和 `effect_metric_contract.py` 维护。本文只要求每个闭环在验收时回到该统一契约，不能在看板中维护第二份指标名单。

当前基线数值和 run 证据只在 `05_验证/当前基线/` 维护。

## 5. 更新规则

- 本文只在验收口径变化时更新。
- 当前推进文档只记录恢复工作所需的阻塞、后续判断口径和有效上下文；不保存批次流水、临时失败长表或子 agent 原始审查全文。
- 架构取舍写入 `04_开发/决策记录/01_文档与算法治理决策记录.md`。
- 测试命令和 marker 写入 `05_验证/03_测试分层与marker规则.md`。
- output run 路径不进入本文正文；需要保留时写入当前基线或 output 资产索引。

## 6. 当前使用方式

阅读者判断一轮改动是否可接受时，按下面顺序使用本文：

1. 找到改动影响的闭环分组；
2. 对照不可关闭条件；
3. 执行对应测试层级；
4. 和当前基线比较关键指标；
5. 若存在未关闭风险，写入 `03_缺口/01_当前缺口总表.md` 或当前推进文档。
