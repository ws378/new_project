# 路径编辑工具整合方案 (Path Tools Integration Plan)

## 1. 现状分析

### 1.1 外部独立工具 ([path_tools/map_editor.py](file:///home/renzo/code/robot/tools/path_tools/map_editor.py)) — 完整功能清单

| 功能类别 | 具体功能 | 说明 |
|---------|---------|------|
| **交互模式** | Select | 单击选点，支持**拖拽移动**选中点（含批量） |
| | Polygon | 多边形框选（射线法），双击闭合 |
| | Add | 点击插入新点（追加或插入到选中点之后，继承 Room/Segment/Yaw） |
| | **Draw** | 手绘自由线段，松开后按 `interval` 等距重采样生成路径点 |
| | **Line** | 多次点击折线段，双击结束，按 `interval` 重采样 |
| | Measure | 两次点击测距，橡皮筋预览，Escape 取消 |
| **编辑操作** | Offset (dx/dy) | 批量世界坐标平移选中点 |
| | Delete | 删除选中点（含确认对话框） |
| | 单点属性编辑 | 右侧面板修改 X/Y/U/V/Yaw/Room/Segment，U/V 与 X/Y 智能同步 |
| | Ctrl+A 全选 | 全选所有路径点 |
| **数据计算** | Yaw 重算 | 保存时可选按相邻点连线重算 Yaw（Segment 分组，不跨段） |
| | 距离重算 | Acc_Dist、Room_Dist、Seg_Dist 基于 Room/Segment 边界重算 |
| | ID 重编号 | 任何编辑后自动重排序 |
| **渲染** | Segment 颜色 | 使用黄金比例 HSV 为每个 Segment 生成不同颜色 |
| | 选中高亮 | 光晕 (Halo) + 白色边框 + 放大半径 |
| | ID 标签阈值 | 缩放比例超过阈值时显示点 ID 编号 |
| | 视口裁剪 | 只渲染可见区域内的路径点和线段 |
| | 地图缓存 | 裁剪+缩放后的底图缓存避免重复渲染 |
| **性能** | SpatialGrid | 网格空间索引加速点击命中检测 |
| **文件操作** | Open Path | 加载 TSV 路径文件 |
| | Open Map | 加载新地图 YAML，可选保留现有点并重算 U/V |
| | New Path | 清空所有点，创建空路径 |
| | Save / Save As | 保存时自动备份 (.bak-timestamp)，可选重算 Yaw 和距离 |
| **其它** | Undo/Redo (50 级) | 基于 `deepcopy(points)` 的全量快照 |
| | Dirty 状态追踪 | 修改后标题栏/状态栏显示 [Modified] |
| | 窗口几何持久化 | 关闭时保存窗口大小位置到 `~/.config/` |
| | 快捷键体系 | s/p/a/d/l/m 切模式，Ctrl+S 保存，Delete 删除等 |
| | 状态栏 | 实时显示文件名、模式、缩放、选中数、鼠标世界坐标、测量距离 |

### 1.2 当前主工具 (`map-tools-beiguo`) 现有能力

- **已有框架**：`ToolManager`（工具注册/切换）、`CommandManager`（全局 Undo/Redo）、[MapCanvas](file:///home/renzo/code/robot/tools/map-tools-beiguo/maptools/views/map_canvas.py#7-781)（地图渲染/缩放/平移/标注绘制）、`Sidebar`（属性面板）。
- **已有路径能力**：覆盖路径生成（`CoveragePlanner`），导出 TSV（与 path_tools 格式兼容），画布上简单的路径连线显示。
- **缺失的路径编辑能力**：除了生成和导出外，**没有任何路径编辑功能**。

---

## 2. 原方案遗漏和缺陷分析

> [!IMPORTANT]
> 以下是对原方案的自审，列出所有遗漏和需要改进的点。

### 2.1 遗漏的功能

| 遗漏项 | 严重程度 | 说明 |
|--------|---------|------|
| **Draw 模式** (手绘路径) | ⚠️ 高 | 原方案完全没有提及。用户可以鼠标拖拽手绘自由曲线，松开后等距重采样生成路径点，这是路径绘制的核心功能之一。 |
| **Line 模式** (折线路径) | ⚠️ 高 | 原方案未提及。多次点击设定折线顶点，双击结束并重采样，与 Draw 平行的另一种路径创建方式。 |
| **点拖拽移动** | ⚠️ 高 | 原方案只提了 Offset（数值输入式偏移），但遗漏了 Select 模式下**直接鼠标拖拽移动选中点**的功能，这是最常用的交互方式。 |
| **New Path** 工作流 | 中 | 清空当前所有路径点重新开始的流程未涉及。 |
| **Open Path** / **Open Map** | 中 | 加载外部 TSV 路径文件、切换底图（含路径点 U/V 重算）的工作流未涉及。 |
| **Ctrl+A 全选** | 低 | 路径点全选快捷键。 |
| **resample_polyline** 算法 | ⚠️ 高 | Draw/Line 模式依赖的等距重采样算法未提及迁移。 |
| **_make_path_points** 生成函数 | 中 | 从世界坐标采样点生成完整 PathPoint（含自动 Yaw 计算）的函数。 |

### 2.2 架构设计缺陷

| 缺陷 | 说明 | 建议修正 |
|------|------|---------|
| **SpatialGrid 性能优化未提及** | 当路径点数量达到数千甚至上万时，每次点击都遍历所有点检索最近点会严重卡顿。外部工具已实现 [SpatialGrid](file:///home/renzo/code/robot/tools/path_tools/map_editor.py#89-117) 网格空间索引解决了此问题。 | 在模型层同步引入 SpatialGrid 用于快速点击检测。 |
| **Segment 颜色渲染未提及** | 外部工具用黄金比例 HSV 为不同 Segment 生成颜色，跨 Segment 连线用灰色标识。这对路径的可视化辨识非常重要。 | 渲染层需实现 segment-based coloring。 |
| **Undo/Redo 策略过度设计** | 原方案提出为每种操作创建独立的 Command 类（`AddPathNodeCommand`, `DeletePathNodeCommand` 等）。但外部工具用更简单的**全量快照**策略（`deepcopy(points)` 入栈），更简单且不易出错。考虑到路径编辑的频率和数据量，全量快照方案更实用。 | 建议路径编辑部分采用**快照式 Undo/Redo**，而非过度拆分的 Command 模式。可以作为 `CommandManager` 下的一个特殊 `PathSnapshotCommand` 实现。 |
| **Draw/Line 参数面板缺失** | Draw 和 Line 模式需要用户输入 Interval(m)、Room、Segment 参数，原方案的 Sidebar 设计中没有包含这些。 | 需要在工具栏或 Sidebar 中增加 Draw/Line 参数配置区。 |
| **Dirty 状态管理未提及** | 用户修改路径点后的未保存状态提示，这对防止数据丢失很重要。 | 需引入 dirty flag，在标题栏或状态栏展示未保存提示。 |
| **路径数据与 Annotations 的关系不清晰** | 原方案中提到将路径数据纳入 [Annotations](file:///home/renzo/code/robot/tools/map-tools-beiguo/maptools/models/annotations.py#54-242)，但路径点本质上是一种**独立的数据类型**（有自己的序列化格式 TSV），与标注（JSON）是完全不同的数据流。混合管理可能带来不必要的耦合。 | 建议路径数据作为**独立的数据管理模块** (`CoveragePathManager`)，与 Annotations 平行存在，而非嵌套其中。 |

### 2.3 实施步骤的问题

| 问题 | 说明 |
|------|------|
| **覆盖路径生成与路径编辑的衔接** | 原方案没有说清楚：用户生成覆盖路径后 → 路径数据如何从 `Pose2D` 列表转为可编辑的 `CoveragePathNode` → 用户编辑完成后如何保存。这个衔接逻辑是整合的关键。 |
| **TSV 导入/导出的兼容性** | 原方案没有明确提到需要支持**双向**的 TSV 文件操作：(1) 导出生成的路径 (2) 导入已有的 TSV 文件进行编辑。当前工具只能导出，需要新增导入功能。 |
| **路径编辑与标注编辑的模式切换** | 当前工具已有标注绘制工具（PolygonTool, LineTool 等），新增路径编辑工具后需要考虑两套工具如何在 ToolManager 中共存和切换。 |

---

## 3. 修订后的完整整合方案

### 3.1 数据模型层

1. 新增 `models/coverage_path.py`：
   - `CoveragePathNode` dataclass (对应外部的 [PathPoint](file:///home/renzo/code/robot/tools/path_tools/map_editor.py#69-82))
   - `CoveragePathManager` 类：管理路径点列表、选中状态集合、SpatialGrid 空间索引
   - [PathParser](file:///home/renzo/code/robot/tools/path_tools/map_editor.py#124-206) 类：TSV 文件读写、距离/Yaw 重算算法
   - [resample_polyline()](file:///home/renzo/code/robot/tools/path_tools/map_editor.py#292-317)、[_make_path_points()](file:///home/renzo/code/robot/tools/path_tools/map_editor.py#319-349) 等工具函数

### 3.2 渲染层 (MapCanvas 扩展)

1. 新增 `_draw_coverage_paths_editable()` 方法替代现有简单连线：
   - Segment 颜色渲染 (golden-ratio HSV)
   - 选中高亮 (Halo + 白色边框 + 放大半径)
   - ID 标签阈值显示
   - 视口裁剪优化

### 3.3 交互工具 (注册到 ToolManager)

| 新工具类 | 对应外部功能 | 说明 |
|---------|------------|------|
| `PathSelectTool` | Select 模式 | 单点选择 + **拖拽移动** |
| `PathPolygonSelectTool` | Polygon 模式 | 多边形框选路径点 |
| `PathAddTool` | Add 模式 | 点击添加/插入路径点 |
| `PathDrawTool` | Draw 模式 | 手绘拖拽路径 + 重采样 |
| `PathLineTool` | Line 模式 | 多点折线路径 + 重采样 |
| `PathMeasureTool` | Measure 模式 | (可复用主工具已有的测量能力或新增) |

### 3.4 UI 面板

1. **Sidebar 扩展**：进入路径编辑模式后显示路径编辑面板
   - 信息区：总点数、选中点数
   - 单点属性编辑：X/Y/U/V/Yaw/Room/Segment + "Update Selected" 按钮
   - Offset 操作：dx/dy 输入 + "Apply Offset" 按钮
   - "Delete Selected" 按钮
   - Draw/Line 参数：Interval(m)、Room、Segment
   - "Recompute Yaw" 开关
2. **菜单扩展**：
   - File > Import Path (TSV)...
   - File > New Path

### 3.5 Command 系统

- 采用 `PathSnapshotCommand` 模式：在 `CommandManager` 中新增一个对路径点列表做全量快照的 Command 类，而非为每种操作单独创建 Command。简单、可靠。

### 3.6 工作流衔接

```
生成路径 (CoveragePlanner) 
  → Pose2D 列表转为 CoveragePathNode 列表 
  → 存入 CoveragePathManager 
  → 自动进入可编辑状态（渲染 + 交互工具可用）
  → 用户编辑（选择/移动/增删/Draw/Line）
  → 保存为 TSV (可选重算 Yaw/距离)
```

```
导入外部 TSV → PathParser.load() 
  → CoveragePathNode 列表 
  → 同上的编辑流程
```

---

## 4. 建议实施阶段

| 阶段 | 内容 | 预计工作量 |
|------|------|-----------|
| **Phase 1** | 数据模型 + PathParser + 算法函数迁移 | 低 |
| **Phase 2** | 渲染升级（segment 颜色、选中高亮、ID 标签、视口裁剪） | 中 |
| **Phase 3** | PathSelectTool (含拖拽) + PathPolygonSelectTool | 中 |
| **Phase 4** | PathAddTool + PathDrawTool + PathLineTool | 中-高 |
| **Phase 5** | Sidebar 路径编辑面板 + Offset/Delete/单点编辑 | 中 |
| **Phase 6** | Undo/Redo (PathSnapshotCommand) + Dirty 状态 | 低 |
| **Phase 7** | TSV 导入/导出 + Yaw 重算 + 距离重算 | 低 |
| **Phase 8** | 快捷键、状态栏增强、测试验证 | 低 |
