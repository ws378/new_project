# Git 提交与回滚策略

## 1. 提交边界

可以自主提交以下批次：

- governance / preflight 文档闭合。
- 诊断脚本 + 文档 + 验收结果闭合。
- 研究版优化脚本 + 对比结果 + 执行记录闭合。

禁止混提交：

- 用户已有 maptools project 改动。
- output run 大图。
- 与当前研究无关的正式 planner 修改。
- CTG 本体修复和 shelf-aware 研究脚本。

## 2. 提交前检查

```bash
git status --short
git diff --stat
git diff --cached --stat
git diff --cached --name-status
```

必须确认暂存文件只属于当前批次。

## 3. 提交说明

使用中文提交说明。推荐格式：

```text
<动词><研究对象><批次目标>
```

示例：

```text
补齐 shelf aware CTG 研究开工准备文档
新增残留网格节点诊断
记录 baseline-only 远跳诊断结论
```

## 4. 回滚原则

不使用：

```bash
git reset --hard
git checkout -- .
```

如果需要撤销，优先：

- 针对本批文件反向修改。
- 新提交修正。
- 仅在确认不影响用户改动时 `git revert <commit>`。

## 5. output 处理

`output/` 默认由 `.gitignore` 忽略。

清理旧 output 只允许清理本研究目录内的 run 输出，例如：

```bash
rm -rf algorithms/shelf_aware_ctg_research/output/run_*
```

不得清理用户指定保留的 run。
