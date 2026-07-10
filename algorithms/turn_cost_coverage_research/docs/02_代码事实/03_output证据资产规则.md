# output 证据资产规则

`algorithms/turn_cost_coverage_research/output/` 是本地证据资产目录，不是算法入口，也不是默认版本库资产。本文只保存长期规则，不保存单次扫描摘要。

## 1. 资产类别

| 类别 | 中文说明 | 默认处置 |
| --- | --- | --- |
| `baseline` | 正式基线或轻量 fixture 的来源证据。 | 保留，或抽取轻量 fixture 后归档原始大目录。 |
| `candidate_mode_evidence` | `shelf_aware_turn_cost` 候选增强入口证据。 | 保留当前候选基线和门禁证据。 |
| `diagnostic` | 只读诊断、几何诊断、人工标注对齐输出。 | 保留代表性证据，重复 run 可归档或删除。 |
| `rejected_evidence` | 已否定路线的关键失败证据。 | 只保留能解释拒绝原因的最小代表证据。 |
| `archived_reference` | 历史参考或外部复现证据。 | 保留索引或外部归档。 |
| `duplicate` | 已被更好证据替代的重复输出。 | 复核后删除。 |
| `interrupted` | 中断、不完整或无法复现的 run。 | 无唯一证据时删除。 |
| `unknown` | 无法判断用途的资产。 | 先补分类，不能直接保留或删除。 |

## 2. manifest 工具

只读扫描入口：

```bash
algorithms/turn_cost_coverage_research/.venv/bin/python \
  algorithms/turn_cost_coverage_research/scripts/diagnostics/build_output_asset_manifest.py
```

需要生成本地 manifest 时显式传入：

```bash
algorithms/turn_cost_coverage_research/.venv/bin/python \
  algorithms/turn_cost_coverage_research/scripts/diagnostics/build_output_asset_manifest.py \
  --write-local
```

本地输出位于 ignored output 目录：

```text
algorithms/turn_cost_coverage_research/output/output_asset_manifest.local.json
algorithms/turn_cost_coverage_research/output/output_delete_candidates.local.md
```

这些文件不提交。若需要提交长期结论，应写入本文、当前基线或验证文档，而不是提交自动生成摘要。

## 3. manifest 字段语义

字段 schema 以 `scripts/diagnostics/build_output_asset_manifest.py` 为唯一实现真值。本文只解释长期维护时需要理解的字段，不定义第二套 schema。

长期维护只依赖这些字段：

| 字段 | 中文说明 |
| --- | --- |
| `relative_path` | 相对 output 根目录的资产路径。 |
| `asset_type` | 资产类型，通常是目录或文件。 |
| `status` | 资产类别初判，不能单独作为删除依据。 |
| `recommended_action` | 工具建议动作，必须人工复核。 |
| `size_bytes` / `file_count` | 体积和文件数量，用于判断归档价值。 |
| `key_files` | 命中的 summary、metadata、comparison 等关键文件。 |
| `doc_reference_count` / `doc_reference_files` | 当前 docs 中引用该资产的数量和来源。 |
| `classification_reason` | 工具给出的分类原因。 |

时间戳、扫描总数、候选数量等只属于单次运行结果，不写入长期文档。

## 4. 删除门槛

output 删除必须同时满足：

- manifest 已记录路径、大小、关键文件和初判状态；`mtime` 只作为辅助排查字段，不作为长期语义字段；
- 没有被当前 docs、reference、当前基线、测试夹具、canonical 脚本输入依赖、人工标注或决策记录引用；
- 历史执行记录、流水记录和过期看板不单独构成保留依据；
- 不是正式 baseline、候选 mode 证据、诊断证据或失败路线唯一证据；
- 有等价替代证据，或确认是重复、失败、中断、临时产物；
- 删除动作单独提交；
- 提交说明写清 `影响范围`、`验证情况`、`证据路径`、`关联跟踪`。

## 5. 代表性证据原则

失败路线和研究路线不按“越多越安全”保留。长期只保留：

- 能说明为什么拒绝该路线的代表图、summary 或对比表；
- 能复现当前基线或候选基线的最小证据；
- 人工标注或文档明确引用的证据；
- 仍被测试、canonical 脚本输入依赖或 baseline fixture 依赖的输入。

其余大体积重复 run 应外部归档或删除。

## 6. `candidate_baselines` 内部规则

`output/candidate_baselines` 是一个顶层 output 资产。内部 run 清理必须额外遵守：

- 反向引用扫描只覆盖 `docs`、`baselines`、`scripts` 和 `tests`，避免 ignored output 内部自引用污染判断；
- 命中 run 目录名或完整相对路径均视为被引用，必须保留；
- 轻量 baseline fixture 的源基线、最新通过 delivery gate 的 candidate run、被当前基线、验证入口、决策记录或人工标注引用的 run 必须保留；
- 只删除未引用、已被更新通过证据替代的大体积重复 candidate run；
- 删除后必须刷新本地 manifest，并运行 `tests/test_turn_cost_output_asset_manifest.py`。

## 7. 禁止事项

- 不把 output 中某个单 run 反向定义算法；
- 不把自动删除候选表当作删除许可；
- 不提交 `.local.json`、`.local.md` 或全量大图目录；
- 不用历史执行记录为重复 output 续命；
- 不在同一提交里同时大规模删除 output、修改算法行为和改写验证口径。
