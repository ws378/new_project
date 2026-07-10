# MapTools Usability Quickstart

本文档对应 `maptools/docs/plans/2026-03-13-maptools-usability-task-breakdown.md` 的落地结果，聚焦“更容易用”的工作流。

## 1. 统一打开入口

在 `File` 菜单中，`Open Resource...` 是主入口，资源识别流程统一到 `_open_resource`：

- `Open Resource...`: 主入口；先选择资源文件（YAML），未选择文件时可继续选择项目目录，再自动分流
- 资源文件支持：地图 YAML、coverage repo YAML、工程文件 `*.mapproj`
- `Advanced -> Open Map/Open Project/Import Coverage Repo`: 兼容入口，不作为主流程
- `Import Coverage Repo YAML...`: 显式导入 coverage repo（带类型校验）

资源识别规则：

1. 目录（来自 Open Resource 的目录选择）-> 项目目录
2. `.mapproj` -> 工程文件（解析后定位到项目目录）
3. YAML 且包含 `image/resolution/origin` -> 地图 YAML
4. YAML 且包含 `map_id/paths` -> coverage repo YAML

## 2. 响应式工具栏与快捷键

工具栏支持宽度断点：

- `narrow`（宽度 < 1300）：仅 `primary` 分组常驻
- `medium`（1300-1799）：`primary + vector` 常驻
- `wide`（>= 1800）：`primary + vector + path` 全常驻

隐藏分组会折叠到 `More Tools` 菜单。  
工具按钮统一提供 Tooltip，包含快捷键提示。

常用快捷键：

- `V` Select
- `Space` Pan
- `B/L/E` Brush/Line/Eraser
- `O/F/P/W/S/A` Origin/Forbidden/PassOnly/Wall/Station/Area
- `1/2/3/4/5` Path tools

## 3. 会话状态区

工具栏下方新增会话状态条，实时显示：

- 当前地图文件名
- 当前项目目录名（若有）
- Dirty 状态（Undo 栈或路径编辑脏状态）
- 当前布局断点（narrow/medium/wide）
- 快捷键提示摘要

## 4. 错误文案格式统一

关键失败路径统一采用三段式提示：

- `问题`
- `影响`
- `建议`

覆盖场景包括：

- 打开/保存项目失败
- 导入/导出失败
- 覆盖路径生成失败
- 路径导入导出失败

## 5. Coverage Repo 导入导出反馈

### 导入后摘要

导入 coverage repo 后弹出摘要，包含：

- map id / map yaml
- rooms / nodes / segments / area labels

### 导出前预检

导出 coverage repo 前会先做预检：

- 是否已加载地图
- 是否已有区域标注
- 输出目录是否可写

预检通过后显示即将输出的文件清单，再由用户确认继续导出。
