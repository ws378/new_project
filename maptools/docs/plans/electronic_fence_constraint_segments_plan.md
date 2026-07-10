# 电子围栏升级为正式约束分段对象方案

## 1. 背景

当前 `maptools` 里和“电子围栏/约束”相关的能力是分裂的：

- `forbidden_zones`
  - 多边形，天然闭合
- `pass_only_zones`
  - 多边形，天然闭合
- `virtual_walls`
  - 线段，天然不闭合
- `reference_trajectory_world`
  - 只读显示层，不属于正式标注模型

这几套对象分别服务不同能力，但它们在用户认知上都容易被理解成“电子围栏”。当前主要问题是：

1. 无法把一条已有约束线切开、分段、单段编辑
2. 无法在同一套对象内表达“闭合段”和“非闭合段”
3. 无法把一段约束从“虚拟墙”升级成“禁止区”或“不规划覆盖”
4. 当前“载入电子围栏”实际上加载的是参考轨迹，不是正式约束对象
5. 导航约束和覆盖约束混在现有对象命名里，不利于长期演化

因此需要把“电子围栏”升级成一类正式、可分段、可切换语义的约束对象。

## 2. 目标

目标不是再加一个文件导入入口，而是新增一套正式约束模型，支持：

1. 切开一条已有约束
2. 按段编辑
3. 每段可闭合或不闭合
4. 每段可切换约束类型
5. 同一工程里同时承载导航约束和覆盖约束
6. 后续可稳定映射到导出和规划链

## 3. 术语

本方案统一使用以下术语：

- `constraint segment`
  - 约束分段对象，系统内部最小可编辑单位
- `closed segment`
  - 闭合段
- `open segment`
  - 非闭合段
- `constraint type`
  - 约束语义类型
- `planning coverage exclusion`
  - 不规划覆盖区，只影响 coverage，不必等价为导航禁行

说明：

- “电子围栏”保留为产品层用户词汇
- 代码和数据模型层尽量使用 `constraint` / `segment`，避免继续把“参考轨迹”“禁止区”“虚拟墙”混成一个概念

## 4. 数据模型方案

### 4.1 新的统一对象

建议新增统一对象：

```python
@dataclass
class ConstraintSegment:
    id: str
    name: str
    points: List[Tuple[float, float]]
    closed: bool
    constraint_type: str
    color: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
```

约束：

1. `points`
  - 世界坐标有序点列
2. `closed`
  - `True` 表示最后一个点和第一个点逻辑闭合
3. `constraint_type`
  - 不再由“对象类名”决定语义，而由正式字段决定
4. `metadata`
  - 只放辅助信息，不放正式业务真值

### 4.2 正式约束类型

第一版建议只定义这 4 类：

- `forbidden_zone`
  - 导航禁入区域
  - 必须闭合
- `virtual_wall`
  - 导航虚拟墙
  - 允许不闭合
- `no_coverage`
  - 不规划覆盖区域
  - 应闭合
- `pass_only`
  - 仅通行不清扫
  - 应闭合

约束：

1. `forbidden_zone`
  - `closed=True`
2. `virtual_wall`
  - `closed=False`
3. `no_coverage`
  - `closed=True`
4. `pass_only`
  - `closed=True`

如果用户把不符合规则的段切换到某类型，应触发约束检查：

- 线段切换为区域类类型时，要求先闭合
- 区域段切换为 `virtual_wall` 时，要求先拆开

### 4.3 和现有 `Annotations` 的关系

长期不建议继续把：

- `ForbiddenZone`
- `PassOnlyZone`
- `VirtualWall`

作为并列长期主模型。

建议演进为：

```python
class Annotations:
    self.constraint_segments: List[ConstraintSegment]
```

现有字段在迁移期可以保留，但它们应逐步降级成：

- 迁移输入
- 导出兼容层
- 旧工程恢复层

而不是长期正式主运行面。

## 5. UI 交互方案

### 5.1 顶层交互目标

UI 不再把：

- 禁止区
- 虚拟墙
- pass only
- 电子围栏

做成完全独立的绘制世界。

而是统一为：

- 新建约束段
- 编辑约束段
- 单段切换类型
- 单段切换闭合状态

### 5.2 工具层建议

建议新增一个统一工具组：

- `Constraint Segment Tool`

第一版至少支持：

1. 新建 open segment
2. 新建 closed segment
3. 选中某段
4. 拖点
5. 加点
6. 删点
7. 切开段
8. 合并段
9. 切换 `constraint_type`

### 5.3 选择与编辑行为

建议支持 3 层选择粒度：

1. 段级选择
  - 选中整段
2. 点级选择
  - 选中某个控制点
3. 边级选择
  - 选中两点间一段边，用于插点或切开

### 5.4 “切开”定义

“切开”应指：

- 在某个段的某个边或点处打断
- 把一个 `ConstraintSegment` 分成两个新的 `ConstraintSegment`

规则：

1. `open segment`
  - 可在内部任意边切开
2. `closed segment`
  - 切开后默认变成 `open segment`
  - 因为闭合环被打断

### 5.5 “闭合/不闭合”切换

应显式暴露为段属性，不隐式推断。

规则：

1. `open -> closed`
  - 要求点数至少 3
2. `closed -> open`
  - 允许，通常用于从区域退化回边界线

### 5.6 类型切换

应允许单段切换类型，但要有校验：

- 切到 `virtual_wall`
  - 段必须为 `open`
- 切到 `forbidden_zone` / `no_coverage` / `pass_only`
  - 段必须为 `closed`

### 5.7 当前“载入电子围栏”的处理

当前 `load_electronic_fence(...)` 实际加载的是：

- `trajectory_from_tf.jsonl`
- 或 `summary.json`

并把结果放进：

- `reference_trajectory_world`

它是参考叠加层，不是正式约束对象。

因此第一版不建议把这条链直接并入正式 `constraint_segments`。

建议：

1. 保留它作为参考轨迹层
2. 明确更名或文案纠偏
  - 例如从“载入电子围栏”改成“载入参考轨迹”
3. 如果后续确有需要，再增加“参考轨迹转约束段”的显式转换动作

## 6. 导出映射方案

### 6.1 总原则

不要让一种约束类型同时隐式映射到多个导出语义。

映射应明确：

- 导航约束导出到导航层
- 覆盖约束导出到 coverage 层

### 6.2 第一版导出映射

建议映射如下：

- `forbidden_zone`
  - 导出到 `map_forbidden.*`
- `virtual_wall`
  - 导出到 `map_virtual_wall.*`
- `pass_only`
  - 导出到 `map_pass_only.*`
- `no_coverage`
  - 不进入 Nav2 forbidden / virtual wall 图层
  - 只进入 coverage planning 的区域裁决逻辑

### 6.3 重要语义边界

`no_coverage` 不应等价于：

- 导航禁行
- 虚拟墙

原因：

1. 它表达的是“不要扫”
2. 不一定表达“机器人绝对不能过”

这点必须在模型和导出层都写死。

### 6.4 Save/Open Project

工程应保存统一约束对象，而不是分别保存三类旧对象。

长期建议：

- 工程真值里保存 `constraint_segments`
- 打开工程时恢复 `constraint_segments`
- 渲染层按 `constraint_type` 决定显示风格
- 导出层按 `constraint_type` 决定落盘映射

## 7. 渐进迁移方案

### 阶段 A：新增统一模型，不改旧导出

目标：

1. 新增 `ConstraintSegment`
2. 工程文件开始支持保存和恢复 `constraint_segments`
3. UI 支持新建、编辑、切开、闭合、改类型

此阶段仍允许旧导出逻辑继续消费旧对象或兼容转换结果。

### 阶段 B：旧对象转兼容层

目标：

1. `ForbiddenZone` / `PassOnlyZone` / `VirtualWall` 不再作为主编辑对象
2. 它们只作为：
  - 旧工程恢复输入
  - 旧格式迁移输入
  - 导出兼容映射层

### 阶段 C：导出改成统一模型驱动

目标：

1. `export.py`
  - 直接从 `constraint_segments` 生成：
    - forbidden
    - virtual wall
    - pass only
2. coverage 相关逻辑从统一模型读取 `no_coverage`

### 阶段 D：清理旧主运行面

目标：

1. 删除旧编辑器对：
  - `forbidden_zones`
  - `pass_only_zones`
  - `virtual_walls`
   的直接编辑依赖
2. 只保留迁移读取能力

## 8. 非目标

本方案当前不包含：

1. 基于轨迹自动分段
2. 复杂布尔运算型区域编辑
3. 多层级约束优先级系统
4. 电子围栏和 coverage 路由策略的联动设计

## 9. 验收口径

第一阶段落地后，至少应满足：

1. 用户可以创建 open / closed 两类约束段
2. 用户可以把一段切开成两段
3. 用户可以对单段改类型
4. `virtual_wall` 只能是 open
5. `forbidden_zone` / `no_coverage` / `pass_only` 只能是 closed
6. 工程保存和打开能恢复统一约束对象
7. 导出仍能生成当前已有的 forbidden / virtual wall / pass only 结果
8. `no_coverage` 能进入覆盖规划语义，但不污染 Nav2 禁行语义

## 10. 一句话结论

长期应该把“电子围栏”从当前分裂的多边形、线段和参考轨迹概念，升级为一类统一的正式约束分段对象：

- 可切开
- 可分段
- 可闭合或不闭合
- 可切换为禁止区、虚拟墙、仅通行、不规划覆盖

并以统一模型驱动后续工程保存、编辑和导出。
