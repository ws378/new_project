# 示例资产目录

## 职责

`examples/` 只保存可人工打开、可用于演示或手工复核的样例资产。

它不是算法实现目录，也不是测试运行输出目录。

## 当前子目录

- `maptools_projects/` - MapTools 工程样例，包含地图、图层、标注和历史 coverage repo 导出。

## 长期约束

- 新的正式算法实现必须放在顶层 `algorithms/`。
- 新的仓库级工具必须放在顶层 `tools/`。
- 自动化测试依赖的固定输入应放在 `tests/fixtures/`，不要放在 `examples/`。
- 运行产物不应提交到 `examples/`，需要复现实验结果时应进入专门 dataset 或 report 目录。
