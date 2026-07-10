# Coverage Repo 测试夹具

## 职责

本目录保存 `maptools.utils.coverage_repo_import` 等模块的固定 coverage repo 输入。

## 当前夹具

- `output_base/` - 历史 coverage repo 导入测试使用的 MapTools 导出结构。

## 边界

- `output_base/` 是测试 fixture，不是根目录运行输出。
- 测试读取该目录时必须使用 `tests/fixtures/coverage_repos/output_base` 显式路径。
- coverage repo 导入逻辑不能再通过根目录 `sample/` 兜底寻找地图。
