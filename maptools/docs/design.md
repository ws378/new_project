# ROS2 地图编辑工具 - 技术设计方案

## 1. 整体架构

采用 **MVC + 命令模式** 架构：

```
┌─────────────────────────────────────────────────────────────────┐
│                           View Layer                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │ MenuBar  │ │ Toolbar  │ │ Sidebar  │ │   MapCanvas      │   │
│  └──────────┘ └──────────┘ └──────────┘ │ (Tkinter Canvas) │   │
│                                          └──────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Controller Layer                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐   │
│  │ ToolManager │ │ CommandMgr  │ │ CoordinateTransformer   │   │
│  │ (工具状态)   │ │ (撤销/重做) │ │ (像素↔世界坐标)         │   │
│  └─────────────┘ └─────────────┘ └─────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                          Model Layer                             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐   │
│  │  MapData    │ │ Annotations │ │     ProjectManager      │   │
│  │ (PGM+YAML)  │ │ (JSON向量)  │ │   (加载/保存/导出)       │   │
│  └─────────────┘ └─────────────┘ └─────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## 2. 模块划分

```
maptools/
├── main.py                 # 入口
├── app.py                  # 主应用类
│
├── models/                 # 数据模型
│   ├── __init__.py
│   ├── map_data.py         # 地图数据(PGM + YAML)
│   ├── annotations.py      # 向量标注数据
│   └── project.py          # 项目管理
│
├── views/                  # 视图组件
│   ├── __init__.py
│   ├── main_window.py      # 主窗口
│   ├── map_canvas.py       # 地图画布
│   ├── toolbar.py          # 工具栏
│   ├── sidebar.py          # 侧边栏(图层+属性)
│   └── dialogs.py          # 对话框
│
├── controllers/            # 控制器
│   ├── __init__.py
│   ├── tool_manager.py     # 工具状态管理
│   ├── command_manager.py  # 撤销/重做
│   └── commands/           # 具体命令
│       ├── __init__.py
│       ├── brush_cmd.py
│       ├── annotation_cmd.py
│       └── transform_cmd.py
│
├── tools/                  # 绘图工具
│   ├── __init__.py
│   ├── base_tool.py        # 工具基类
│   ├── pan_tool.py         # 平移工具
│   ├── brush_tool.py       # 画笔工具
│   ├── eraser_tool.py      # 橡皮擦
│   ├── polygon_tool.py     # 多边形(禁行区)
│   ├── pass_only_tool.py   # 多边形(仅通行区) - 新增
│   ├── line_tool.py        # 线段(虚拟墙)
│   ├── station_tool.py     # 基站标注
│   ├── measure_tool.py     # 测距工具
│   └── origin_tool.py      # 原点调整工具
│
├── utils/                  # 工具函数
│   ├── __init__.py
│   ├── coordinate.py       # 坐标转换
│   ├── image_utils.py      # 图像处理
│   └── export.py           # 导出功能
│
└── resources/              # 资源文件
    └── icons/              # 工具图标(可选)
```

## 3. 核心类设计

### 3.1 MapData - 地图数据模型

```python
@dataclass
class MapMetadata:
    image_path: str
    resolution: float           # 米/像素
    origin: Tuple[float, float, float]  # [x, y, yaw]
    negate: bool
    occupied_thresh: float
    free_thresh: float

class MapData:
    """管理地图栅格数据"""

    def __init__(self):
        self.metadata: MapMetadata = None
        self.base_image: np.ndarray = None      # 原始地图(只读)
        self.edit_layer: np.ndarray = None      # 编辑层(画笔/橡皮擦)
        self.image_size: Tuple[int, int] = (0, 0)

    def load(self, yaml_path: str) -> bool: ...
    def get_merged_image(self) -> np.ndarray: ...
    def apply_brush(self, x: int, y: int, radius: int, value: int): ...
    def rotate(self, angle_deg: float): ...
    def translate_origin(self, dx: float, dy: float): ...
```

### 3.2 Annotations - 向量标注

```python
@dataclass
class ForbiddenZone:
    id: str
    name: str
    polygon: List[Tuple[float, float]]  # 世界坐标

@dataclass
class PassOnlyZone:
    """仅通行区 - 机器人可通行但不执行清洁"""
    id: str
    name: str
    polygon: List[Tuple[float, float]]  # 世界坐标

@dataclass
class VirtualWall:
    id: str
    name: str
    start: Tuple[float, float]
    end: Tuple[float, float]

@dataclass
class Station:
    id: str
    name: str
    position: Tuple[float, float]
    orientation: float  # 弧度

class Annotations:
    """管理向量标注"""

    def __init__(self):
        self.forbidden_zones: List[ForbiddenZone] = []
        self.pass_only_zones: List[PassOnlyZone] = []  # 新增：仅通行区
        self.virtual_walls: List[VirtualWall] = []
        self.stations: List[Station] = []
        # 仅用于历史/调试记录，不参与显示与导出
        self.coordinate_transform = {"rotation_deg": 0, "origin_offset": [0, 0]}

    def add_forbidden_zone(self, polygon: List[Tuple]): ...
    def add_pass_only_zone(self, polygon: List[Tuple]): ...  # 新增
    def add_virtual_wall(self, start: Tuple, end: Tuple): ...
    def add_station(self, pos: Tuple, orientation: float): ...
    def remove_by_id(self, item_id: str): ...
    def apply_transform(self, rotation: float, offset: Tuple): ...
    def to_dict(self) -> dict: ...
    def from_dict(self, data: dict): ...
```

### 3.3 MapCanvas - 地图画布

```python
class MapCanvas(tk.Canvas):
    """地图显示和交互画布"""

    def __init__(self, parent, controller):
        self.controller = controller
        self.zoom_level: float = 1.0
        self.pan_offset: Tuple[int, int] = (0, 0)
        self.display_image: ImageTk.PhotoImage = None

        # 图层可见性
        self.layers_visible = {
            "base_map": True,
            "edit_layer": True,
            "forbidden_zones": True,
            "pass_only_zones": True,  # 新增：仅通行区
            "virtual_walls": True,
            "stations": True,
            "grid": False,
            "origin": True,
        }

    def set_map_data(self, map_data: MapData): ...
    def set_annotations(self, annotations: Annotations): ...
    def refresh(self): ...

    # 视图控制
    def zoom_in(self): ...
    def zoom_out(self): ...
    def zoom_to_fit(self): ...
    def pan(self, dx: int, dy: int): ...

    # 坐标转换(画布坐标 ↔ 世界坐标)
    def canvas_to_world(self, cx: int, cy: int) -> Tuple[float, float]: ...
    def world_to_canvas(self, wx: float, wy: float) -> Tuple[int, int]: ...

    # 绘制
    def _draw_map(self): ...
    def _draw_grid(self): ...
    def _draw_origin(self): ...
    def _draw_scale_bar(self): ...
    def _draw_annotations(self): ...
```

### 3.4 Tool 基类与工具管理

```python
class BaseTool(ABC):
    """工具基类"""

    name: str = "base"
    cursor: str = "arrow"

    def __init__(self, canvas: MapCanvas, controller):
        self.canvas = canvas
        self.controller = controller

    @abstractmethod
    def on_press(self, event): ...

    @abstractmethod
    def on_drag(self, event): ...

    @abstractmethod
    def on_release(self, event): ...

    def on_motion(self, event):
        """鼠标移动(非按下状态)"""
        pass

    def on_key(self, event):
        """键盘事件"""
        pass


class ToolManager:
    """工具状态管理"""

    def __init__(self, canvas: MapCanvas):
        self.canvas = canvas
        self.tools: Dict[str, BaseTool] = {}
        self.current_tool: BaseTool = None
        self.brush_size: int = 5
        self.brush_value: int = 0  # 0=障碍, 255=可通行

    def register_tool(self, tool: BaseTool): ...
    def switch_tool(self, name: str): ...
    def get_current_tool(self) -> BaseTool: ...
```

### 3.5 Command 模式 (撤销/重做)

```python
class Command(ABC):
    """命令基类"""

    @abstractmethod
    def execute(self): ...

    @abstractmethod
    def undo(self): ...


class BrushCommand(Command):
    """画笔命令 - 保存修改前的区域快照"""

    def __init__(self, map_data: MapData,
                 affected_pixels: List[Tuple[int, int]],
                 old_values: np.ndarray,
                 new_value: int):
        self.map_data = map_data
        self.affected_pixels = affected_pixels
        self.old_values = old_values
        self.new_value = new_value

    def execute(self): ...
    def undo(self): ...


class AddAnnotationCommand(Command):
    """添加标注命令"""

    def __init__(self, annotations: Annotations, item): ...
    def execute(self): ...
    def undo(self): ...


class CommandManager:
    """命令管理器"""

    def __init__(self, max_history: int = 50):
        self.undo_stack: List[Command] = []
        self.redo_stack: List[Command] = []
        self.max_history = max_history

    def execute(self, cmd: Command): ...
    def undo(self): ...
    def redo(self): ...
    def can_undo(self) -> bool: ...
    def can_redo(self) -> bool: ...
```

## 4. 关键交互流程

### 4.1 画笔绘制流程

```
用户按下鼠标 → BrushTool.on_press()
                    │
                    ▼
            记录起始位置，开始收集像素
                    │
用户拖动鼠标 → BrushTool.on_drag()
                    │
                    ▼
        计算路径上的像素点，收集旧值，写入新值
        实时更新 MapCanvas 显示
                    │
用户释放鼠标 → BrushTool.on_release()
                    │
                    ▼
        创建 BrushCommand，提交到 CommandManager
```

### 4.2 禁行区绘制流程

```
用户点击第一个点 → PolygonTool.on_press()
                        │
                        ▼
                    记录顶点，显示预览点
                        │
用户继续点击     → 添加更多顶点，绘制预览线段
                        │
用户双击/按Enter → 完成多边形
                        │
                        ▼
        创建 ForbiddenZone，提交 AddAnnotationCommand
        MapCanvas 刷新显示
```

### 4.3 坐标系调整流程

```
用户选择"调整原点"工具
        │
        ▼
用户点击新原点位置 → OriginTool.on_press()
        │
        ▼
计算原点偏移量 (dx, dy)
        │
        ▼
┌───────────────────────────────────┐
│  TransformCommand.execute():      │
│  1. 更新 MapData.metadata.origin  │
│  2. 更新 Annotations 中所有坐标    │
│  3. 刷新显示                       │
└───────────────────────────────────┘
```

### 4.4 地图旋转流程（烘焙到图像）

```
用户选择"旋转地图"工具
        │
        ▼
用户设定旋转角度 θ（逆时针为正）
        │
        ▼
1) 对图像执行像素旋转（以图像中心为旋转中心）
2) 计算新图像尺寸 (w', h')
3) 计算新 origin 并更新 map.yaml（yaw 归零）
4) 对所有标注坐标应用同样旋转
5) 刷新显示
```

> 说明：旋转烘焙到图像后，`origin[2]` 保持为 `0`，避免双重旋转。

## 5. 坐标系统设计

### 5.1 四种坐标系

| 坐标系 | 说明 | 原点 |
|--------|------|------|
| 屏幕坐标 | Tkinter事件坐标 | 窗口左上角 |
| 画布坐标 | Canvas滚动后坐标 | Canvas左上角 |
| 像素坐标 | PGM图像像素 | 图像左上角, Y向下 |
| 世界坐标 | ROS2世界坐标(米) | map.yaml.origin, Y向上 |

### 5.2 转换链

```python
class CoordinateTransformer:
    """坐标转换器"""

    def __init__(self, map_data: MapData, canvas: MapCanvas):
        self.map_data = map_data
        self.canvas = canvas

    def screen_to_canvas(self, sx, sy) -> Tuple[int, int]:
        """屏幕 → 画布"""
        return self.canvas.canvasx(sx), self.canvas.canvasy(sy)

    def canvas_to_pixel(self, cx, cy) -> Tuple[int, int]:
        """画布 → 像素 (考虑缩放和平移)"""
        zoom = self.canvas.zoom_level
        px = self.canvas.pan_offset[0]
        py = self.canvas.pan_offset[1]
        return int((cx - px) / zoom), int((cy - py) / zoom)

    def pixel_to_world(self, pixel_x, pixel_y) -> Tuple[float, float]:
        """像素 → 世界"""
        meta = self.map_data.metadata
        h = self.map_data.image_size[1]
        wx = meta.origin[0] + pixel_x * meta.resolution
        wy = meta.origin[1] + (h - pixel_y) * meta.resolution
        return wx, wy

    def world_to_pixel(self, wx, wy) -> Tuple[int, int]:
        """世界 → 像素"""
        meta = self.map_data.metadata
        h = self.map_data.image_size[1]
        px = int((wx - meta.origin[0]) / meta.resolution)
        py = int(h - (wy - meta.origin[1]) / meta.resolution)
        return px, py

    # 便捷方法
    def screen_to_world(self, sx, sy) -> Tuple[float, float]:
        cx, cy = self.screen_to_canvas(sx, sy)
        px, py = self.canvas_to_pixel(cx, cy)
        return self.pixel_to_world(px, py)
```

### 5.3 旋转后 origin 更新规则（烘焙旋转）

当图像像素被旋转时，需要同步更新 `map.yaml` 的 `origin`，以保证世界坐标不发生跳变。

定义：
- 原图像尺寸：`w, h`（像素）
- 新图像尺寸：`w', h'`（像素）
- 分辨率：`r`
- 原 `origin`: `(ox, oy, yaw)`，MVP 约束 `yaw = 0`
- 旋转角度：`θ`（逆时针）
- 旋转仿射矩阵：`A`，满足 `p_new = A * p_old`（像素坐标）

步骤：
1. 计算 `A`（围绕图像中心旋转并修正平移得到新图像的包围盒）。
2. 求 `A` 的逆 `A_inv`，得到新图像像素 `(0, 0)` 在旧图中的像素坐标：`p_old = A_inv * [0, 0, 1]`
3. 将 `p_old = (x_old, y_old)` 转为世界坐标（使用旧图）：`world_x = ox + x_old * r`，`world_y = oy + (h - y_old) * r`
4. 计算新 `origin`（使新图 `(0,0)` 对应同一世界点）：`ox' = world_x`，`oy' = world_y - h' * r`，`yaw' = 0`

所有标注坐标使用同样的旋转角 `θ` 进行旋转更新。

## 6. 导出功能设计

```python
class Exporter:
    """导出管理器"""

    def __init__(self, map_data: MapData, annotations: Annotations):
        self.map_data = map_data
        self.annotations = annotations

    def export(self, output_dir: str):
        """导出完整项目"""
        os.makedirs(output_dir, exist_ok=True)

        # 1. 导出主地图 (base + edit_layer 合并)
        self._export_main_map(output_dir)

        # 2. 导出禁行区栅格（内部/后续插件使用）
        self._export_forbidden_zones(output_dir)

        # 3. 导出仅通行区栅格（新增）
        self._export_pass_only_zones(output_dir)

        # 4. 导出虚拟墙栅格（内部/后续插件使用）
        self._export_virtual_walls(output_dir)

        # 5. 导出更新后的 YAML
        self._export_yaml(output_dir)

        # 6. 导出标注 JSON (供参考)
        self._export_annotations_json(output_dir)

    def _rasterize_polygon(self, polygon: List[Tuple],
                           image_shape: Tuple) -> np.ndarray:
        """将多边形栅格化为二值图像"""
        # 使用 OpenCV fillPoly
        ...

    def _rasterize_line(self, start: Tuple, end: Tuple,
                        thickness: int, image_shape: Tuple) -> np.ndarray:
        """将线段栅格化"""
        # 使用 OpenCV line
        ...
```

## 7. UI 交互细节

### 7.1 快捷键设计

| 快捷键 | 功能 |
|--------|------|
| Space + 拖动 | 平移地图 (任何工具下) |
| 滚轮 | 缩放 |
| Ctrl + 滚轮 | 快速缩放 |
| Ctrl + 0 | 适应窗口 |
| Ctrl + Z | 撤销 |
| Ctrl + Y | 重做 |
| B | 画笔工具 |
| E | 橡皮擦 |
| P | 禁行区(Polygon) |
| O | 仅通行区(PassOnly) |
| L | 虚拟墙(Line) |
| S | 基站(Station) |
| M | 测距(Measure) |
| [ | 减小笔刷 |
| ] | 增大笔刷 |
| Delete | 删除选中标注 |
| Escape | 取消当前操作 |

### 7.2 鼠标行为

| 操作 | 行为 |
|------|------|
| 左键点击 | 工具主操作 |
| 左键拖动 | 连续绘制/选择框 |
| 右键点击 | 上下文菜单/取消 |
| 中键拖动 | 平移地图 |
| 滚轮 | 以鼠标位置为中心缩放 |

### 7.3 状态栏信息

```
坐标: X: 12.35m  Y: 8.72m (px: 562, 345)  |  缩放: 150%  |  工具: 画笔  |  笔刷: 5px
```

## 8. 性能考虑

### 8.1 大地图优化

- **延迟渲染**: 只渲染可视区域
- **图像缓存**: 缓存不同缩放级别的地图图像
- **增量更新**: 画笔只更新受影响区域，而非全图重绘

### 8.2 撤销栈优化

- **画笔命令合并**: 连续的画笔操作可合并为单个命令
- **栈深度限制**: 最多保留50步历史
- **大操作警告**: 旋转/大面积修改时提示用户

## 9. 待讨论问题

### Q1: 地图旋转实现方式（已决）

采用方案A：旋转图像并将旋转烘焙到 PGM 中，同时更新 `map.yaml` 的 `origin`（`origin[2]` 归零）与所有标注坐标。

- 优点: 导出的 PGM 可直接用于 nav2 静态地图
- 代价: 会引入插值误差，图像尺寸可能变化（通过 `origin` 更新保持世界坐标一致）

### Q2: 编辑层存储格式

**方案A: 独立 edit_layer.pgm**
- 255 = 未修改(透明)
- 0 = 绘制为障碍
- 254 = 绘制为可通行

**方案B: 差分记录**
- 只记录修改的像素坐标和值

建议: 方案A更简单，易于调试

### Q3: 标注选择与编辑

- 点击已有标注是否进入编辑模式？
- 是否支持拖动移动标注？
- 是否支持编辑多边形顶点？

建议: MVP 先只支持删除，后续版本支持编辑

### Q4: 项目文件格式

**方案A: 目录结构**
```
project/
├── map.yaml
├── map_base.pgm
├── map_edited.pgm
└── annotations.json
```

**方案B: 单文件 (.mapproj)**
- ZIP格式打包所有文件

建议: 方案A更简单透明

## 10. 开发计划建议

### Phase 1: 基础框架 (核心可用)
1. 主窗口框架 + 菜单栏
2. MapCanvas 基础显示
3. 地图加载 (PGM + YAML)
4. 缩放/平移
5. 坐标显示

### Phase 2: 栅格编辑
1. 画笔/橡皮擦工具
2. 命令管理器 (撤销/重做)
3. 保存编辑层

### Phase 3: 向量标注
1. 禁行区多边形
2. 虚拟墙线段
3. 基站标注
4. 标注可见性控制

### Phase 4: 视觉辅助
1. 网格叠加
2. 原点显示
3. 比例尺
4. 测距工具

### Phase 5: 坐标系调整
1. 原点平移
2. 地图旋转
3. 标注同步变换

### Phase 6: 导出与完善
1. 多图层PGM导出
2. 项目保存/加载
3. UI优化
