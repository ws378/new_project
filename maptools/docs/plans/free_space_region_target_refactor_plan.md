# 自由连通区处置目标重构方案

## 背景问题

当前 GUI 中“自由连通区 -> 禁止区 / 不规划覆盖区 / 恢复自由区 / 生成多边形”的主链仍然以 `component_id` 为主要入口，并在不同阶段混用当前自由区分析结果、派生约束区域、bbox、metadata key 等信息重新推导目标区域。这个设计在以下场景中容易产生漂移：

- 同一个 `component_id` 在重新分析后指向了另一个连通区。
- 已经被设置为 `forbidden_zone` 或 `no_coverage` 的区域不再属于当前自由区分析结果，只能从派生区域恢复身份。
- 一个旧 `component_id` 同时对应多个历史派生区域时，继续按 `component_id` 回退会误操作。
- 菜单打开时命中的是 A 区域，但菜单动作执行时又重新解析，可能作用到 B 区域。

这类问题不能继续靠局部 fallback 修补。长期方案是把“右键命中的区域”冻结成稳定目标对象，菜单动作只消费这个目标对象，不再在执行时重新猜测。

## 重构目标

### 1. 单一目标模型

新增 `FreeSpaceRegionTarget`，作为所有自由区处置动作的唯一输入。目标对象在右键命中或批量分析阶段一次性构造，包含：

- `source`：`free_component` 或 `derived_region`
- `semantic`：当前语义，`free` / `forbidden_zone` / `no_coverage`
- `component_id`：仅作为显示和追踪字段，不作为唯一身份
- `component_key`：稳定身份，由 `bbox + mask digest` 形成
- `bbox_px`：局部 bbox
- `mask`：目标区域局部二值掩膜
- `area_m2`：面积
- `repair_radius_m`：本轮分析参数

### 2. 菜单动作冻结目标

右键菜单打开时立即解析 `FreeSpaceRegionTarget`。菜单中的所有命令闭包只保存这个 target，不保存裸 `component_id`。

执行动作时禁止再通过当前 `free_space_components_result` 重新猜测区域。只有从自由组件主动发起时，才允许先从当前分析结果构造 target。

### 3. 匹配只认稳定 key

删除“多个派生区域时按 `component_id` 猜一个”的路径。删除恢复自由区时按多边形中心点落在哪个 label 的兜底删除逻辑。恢复、覆盖、切换语义都只移除 `metadata.component_key == target.component_key` 的正式派生/多边形对象。

这会让行为更严格：没有稳定 key 的旧对象不会被误删。长期不为历史临时数据扩大兼容分支。

### 4. 数据写入保持单真值

语义处置仍写入 `annotations.derived_constraint_regions`，显式生成多边形才写入 `annotations.constraint_segments`。两者都必须带 `metadata.source=free_space_component` 和 `metadata.component_key`。

## 实施计划

### 批次 1：文档和目标模型

- 新增自由区目标模型与 helper。
- 把 component key 计算、派生区域解码、自由组件提取统一收敛到 helper。
- MainWindow 保留少量旧方法作为测试和内部调用包装，但内部动作转向 target。

### 批次 2：主链重构

- `_show_free_space_component_menu` 先解析 target，菜单闭包只传 target。
- `_apply_free_space_component_constraint` 改为 wrapper，核心动作改为 `_apply_free_space_region_target_constraint`。
- `_restore_free_space_component` 改为 wrapper，核心动作改为 `_restore_free_space_region_target`。
- `_generate_free_space_component_polygon_constraint` 改为 wrapper，核心动作改为 `_generate_free_space_region_target_polygon_constraint`。
- 批量小区域转 no_coverage 使用 target 构造，不再直接拼装派生区域。

### 批次 3：测试闭环

- 保留已有自由区全量测试。
- 新增 target 构造单测。
- 新增菜单冻结目标测试：菜单打开后，即使当前自由区分析结果变化，动作仍作用于原 target。
- 新增语义切换矩阵测试：`free -> forbidden_zone -> no_coverage -> free -> forbidden_zone` 等路径只改变同一个 component_key。
- 新增显式多边形测试：从派生区域生成多边形使用 target mask，不受当前 label 变化影响。

## 测试用例

| 用例 | 预期 |
| --- | --- |
| 从自由组件构造 target | key 包含 bbox 和 mask digest，面积来自当前 stat |
| 从派生区域构造 target | key、bbox、mask、语义来自派生区域，不依赖当前分析结果 |
| free -> forbidden_zone | 生成一个红色语义派生区，key 稳定 |
| forbidden_zone -> no_coverage | 删除同 key 的 forbidden，生成同 key 的 no_coverage |
| no_coverage -> free | 删除同 key 派生区，恢复为自由色显示 |
| 连续点击同一语义 | 不重复生成多个同 key 区域 |
| 多个同 component_id 历史区域 | wrapper 无 target 时拒绝猜测，不误改 |
| 菜单打开后 result relabel | 菜单动作仍作用菜单打开时的 target |
| 显式生成多边形 | 写入 constraint_segments，metadata.component_key 与 target 一致 |
| 批量小区域转 no_coverage | 只新增未存在 key，重复执行幂等 |

## 验收标准

- `tests/test_main_window_flow.py`、`tests/test_free_space_components.py`、`tests/test_constraint_segments.py` 全部通过。
- 工程相关测试不回归。
- 右键日志只展示当前目标的 before/after，不再打印全量区域列表。
- 代码中自由区处置核心动作以 `FreeSpaceRegionTarget` 为入口，`component_id` 只作为兼容 wrapper 和 UI 展示字段。
