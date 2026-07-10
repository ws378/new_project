# Work Log

## [2026-02-27] 路径工具深度集成 (Path Tools Integration)

### 目标 (Objective)
将外部路径绘制工具 (`path_tools/map_editor.py`) 的全部核心功能无缝集成到当前地图编辑工具 (`map-tools-beiguo`) 中。支持完整的覆盖路径的节点级编辑、参数配置、撤销重做及存取。

### 完成的变更 (Completed Changes)

1. **数据与解析层 (Data & Parser Layer)**
   - 在 `maptools/models/coverage_path.py` 新增了 `CoveragePathNode` 和 `CoveragePathManager`。
   - 实现了一个简单的空间网格索引 `SpatialGrid` 用于优化点选检测 (Hit Test)。
   - 重构了路径的导入/导出和解析逻辑 (`PathParser`)，封装了偏航角 (Yaw) 和距离累加的独立重算算法。

2. **渲染层 (Rendering Layer)**
   - 彻底修改了 `MapCanvas` 中的路径渲染 (`_draw_coverage_paths_editable`)。
   - 实现了基于 Segment 的 HSV 固定段落着色。
   - 实现了动态高亮光环和选中点的独特渲染。
   - 添加基于屏幕坐标的视口剔除 (Viewport Culling) 及基于缩放级别的 ID 标签动态显示。

3. **交互工具层 (Interaction Tools)**
   - 在 `maptools/tools/path_tools.py` 内部创建了一整套针对路径的专用交互工具：
     - `PathSelectTool` (单选与拖拽)
     - `PathPolygonSelectTool` (多边形框选)
     - `PathAddTool` (点击增加独立点)
     - `PathDrawTool` (鼠标拖手绘生成平滑路径 + 自动重采样)
     - `PathLineTool` (多次点击画多段折线 + 自动重采样)

4. **UI 面板与编辑 (UI Panels & Editing)**
   - 在右侧边栏 `Sidebar` 嵌入了专属的 `PathPanel` (\`maptools/views/path_panel.py\`)。
   - 面板支持展示与精细调整选中点的所有内置属性 (坐标，贴图 U/V，Yaw，Room，Segment)。
   - 提供整个路径选中集合的等值坐标偏移量 (Offset X/Y) 施加。
   - 支持批量删除功能及显示实时的数量统计信息。

5. **命令系统与撤销 (Command System & Undo/Redo)**
   - 设计了 `PathSnapshotCommand` 以全量深拷贝形式记录整个图节点的快照，以兼容极细微的自由绘图位移捕捉并支持无缝 Undo/Redo，且挂接到 `MainWindow` 原有的撤销栈。
   - 在所有的单步/多步工具结束节点抛出快照。

6. **全局应用与 IO (Global App & IO)**
   - 在 `MainWindow` 的 `File` 菜单栏挂载 "New Path..." 与 "Import Path (TSV)..."。
   - "Save Coverage Paths..." 改版为会话级保存。不仅兼容原来的算法全量生成，并且针对当前图管理器内部持有的编辑中路径进行弹窗提示，允许用户选择“是否在保存时由系统底层全部重算 Yaw & Distances”再进行落盘。
   - 主窗口左上角标题会自适应根据 `CoveragePathManager.is_dirty` 显示带星号 "\*" 的未保持提醒并阻止手误清理路径。

## [2026-02-27] 向量标注的选择、编辑与删除功能

### 新增功能
- **新增选择工具 (`SelectTool`)**：位于左侧工具栏。允许用户从绘制模式切换到选择模式，点击画布上已绘制的标注进行操作。
- **选中状态可视化 (`MapCanvas`)**：支持对禁行区、只通区、虚拟墙、基站和区域标记进行命中检测（Hit Testing）。选中后标注会加粗高亮，并在此端点/顶点上渲染控制锚点把手。
- **对象编辑与变形**：
  - **整体移动**：在选择模式下按住对象内部任意位置拖拽，可平移整个标注。
  - **顶层编辑**：按住对象上的控制锚点拖拽，可修改多边形顶点坐标或调整线段/基站位置。
- **快捷键删除**：选中对象后，按下键盘 `Delete` 或 `Backspace` 键即可将标注彻底删除。
- **取消绘制**: 在使用多边形、区域标记、单向区、虚拟墙等所有矢量工具进行绘图到一半时，可随时按下 `Esc` 键清空当前鼠标跟随线迹并放弃当前绘制。
- **状态支持撤销/重做**：
  - 新增 `UpdateAnnotationCommand` 记录移动和顶点编辑前后的属性。
  - 新增 `DeleteAnnotationCommand` 记录被删除对象及原始集合，保证编辑和删除操作全面支持 `Ctrl+Z` (撤销) 和 `Ctrl+Y` (重做)。

## [2026-02-27] 覆盖路径起点手动设置功能

### 新增功能
- **右键菜单新选项**（`map_canvas.py`）：AreaLabel 右键菜单新增"设置起点并生成路径"选项。
- **临时取点模式**（`map_canvas.py`）：选择菜单项后进入取点模式（光标变十字，状态栏提示），用户在地图上点击选择起点，支持 Esc 取消。
- **起点参数传递**（`main_window.py`）：新增 `_on_generate_coverage_path_with_start` 桥接回调；重构 `_on_generate_coverage_path` 方法，新增可选 `start_world_xy` 参数，支持手动指定起点世界坐标（为 None 时沿用质心默认值）。
- **修复事件冲突**（`tool_manager.py`）：`ToolManager` 的 `<ButtonPress-1>` 绑定会覆盖 Canvas 的 `<Button-1>` 绑定，导致取点模式下点击无响应。改为在 `ToolManager._on_press` 中检查 `_pick_start_mode` 标志，若处于取点模式则优先委派给 Canvas 的 `_on_left_click` 处理。

## [2026-02-26 20:10] Bug 修复：Y 轴反转 + 路径保存逻辑

### 修复内容
1. **Y 轴反转** (`coverage_planner.py`): 像素→世界坐标转换缺少 Y 轴翻转。像素坐标 Y 向下，ROS 世界坐标 Y 向上，修正为 `wy = (map_h - py) * resolution + origin_y`。同时修正 theta 方向。
2. **路径保存改为累积** (`main_window.py`): 生成路径后不再立即弹出保存对话框，而是累积到 `_coverage_paths` 列表中。画布合并显示所有区域路径。
3. **菜单保存按钮** (`main_window.py`): File 菜单新增 "Save Coverage Paths..." 按钮，弹出文件对话框，一次性保存所有区域路径。
4. **多区域合并导出** (`coverage_export.py`): 新增 `export_all_coverage_paths()` 函数，所有区域写入同一 TSV 文件，通过 Room 列区分区域，ID 全局递增。

## [2026-02-26] 覆盖路径规划算法引入与 GUI 集成

### 1. 算法移植
- 分析并移植了 ROS `nav2_room_exploration` 插件中的 `EnergyFunctionalExplorator` 等核心 C++ 代码到 Python 独立模块中。
- 创建了 `maptools/algorithms/coverage_planner.py`，完整实现了：
  - 地图旋转对齐以优化主方向。
  - 栅格节点化及 8 邻域图生成。
  - 启发式能量评估和贪心下一节点选择。
  - A* 回退寻路机制（当前直接回退寻找曼哈顿距离最近空闲节点）。
  - 各类状态的反向旋转与世界坐标转换。
- 添加了完备的 Python 特性单元测试，包括测试数据定义和路径断言。

### 2. GUI 集成
- 新增 `maptools/views/coverage_dialog.py`，实现用户自定义生成参数（工作半径、腐蚀半径、等）。
- 新增 `maptools/utils/coverage_export.py`，实现按照 `path_tools` 兼容格式（11 列表头，带累加距离及世界到像素换算）导出生成的路径。
- 修改 `map_canvas.py` 增加：
  - 点击 AreaLabel 的右键触发菜单响应。
  - 射线发 point-in-polygon (`_hit_test_area_label`) 检测 AreaLabel。
  - Canvas 上彩色渐变的折线叠加及顶点小圆圈显示 `show_coverage_path`。
- 修改 `main_window.py`：
  - 组装回调 `_on_generate_coverage_path` 流程，通过 `cv2` 根据 AreaLabel 世界坐标生成局部感兴趣掩码（Mask）与地图位姿相交，并触发 `CoveragePlanner` 规划。
  - 最终显示通过文件保存对话框保存结果 `tsv`。
