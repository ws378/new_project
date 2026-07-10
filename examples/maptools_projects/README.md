# MapTools 工程样例

## 职责

本目录保存人工可打开的 MapTools 工程样例。

这些工程用于手工查看地图编辑、标注、图层导出、coverage repo 导入等产品层能力。

## 目录说明

- `beiguo_lanshan_1770397756/` - 北国蓝山地图工程。
- `beiguoshangcheng_floor_3/` - 北国商城三层地图工程。
- `fourfloor_20250923_8/` - 四层楼房间型地图工程。

## 边界

- 这里不是算法 benchmark 真值目录。
- 这里不是自动化测试 fixture 的唯一来源。
- 若某个样例需要被测试长期引用，应复制或迁移到 `tests/fixtures/` 并在测试中使用明确路径。
