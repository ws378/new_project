# GUI 交互级验收边界工程化与手工验收清单

## 1. 目标

本文定义 `ShelfAware+TurnCost` 进入 UI 后的 GUI 验收边界。

当前 GUI 手工验收边界不改变算法、profile、geometry gate、baseline 或正式 planner 行为，只回答两个问题：

1. 当前自动化测试已经证明了哪些 UI 链路；
2. 真实窗口点击、文件定位和人工观察还需要怎样验收。

## 2. 已自动化覆盖的内容

### 2.1 UI 参数与模式契约

已覆盖：

- UI mode 列表包含 `auto`、`basic`、`shelf_aware`、`shelf_aware_turn_cost`、`channel_topology_graph`；
- `shelf_aware_turn_cost` 使用同一个 `shelf_advanced` 参数组，不再保留重复的 `shelf_turn_cost_advanced` 双真值；
- `shelf_aware_turn_cost` 会隐藏由 profile 固定覆盖的 UI 参数，例如 CTG auxiliary 和 isolated jump cleanup；
- 参数保存/读取可以保留 `planner_mode=shelf_aware_turn_cost`。

测试：

```text
tests/test_main_window_flow.py::test_coverage_dialog_turn_cost_shelf_mode_exposes_shelf_groups
tests/test_main_window_flow.py::test_coverage_planner_params_round_trip_preserves_turn_cost_mode
```

### 2.2 真实 CoverageDialog widget smoke

已覆盖：

- 在有 Tk display 的环境中创建真实 `CoverageDialog` widget；
- 通过非 modal 测试子类避免阻塞；
- 验证 `shelf_aware_turn_cost` 模式下实际 widget 行显隐；
- 切换回 `shelf_aware` 后，验证原 shelfAware 参数行恢复；
- 调用 `apply()` 后，验证 `result_values` 和 `result_config` 保留 `shelf_aware_turn_cost`。

测试：

```text
tests/test_main_window_flow.py::test_coverage_dialog_real_widget_turn_cost_mode_visibility_and_apply
```

边界：

- 该测试是真实 widget smoke，不是真实鼠标点击；
- 没有可用 Tk display 时跳过；
- 不打开文件管理器，不验证窗口截图，不运行重算法。

### 2.3 UI 主流程函数级闭环

已覆盖：

- 对话框返回 `CoveragePlannerConfig(planner_mode="shelf_aware_turn_cost")`；
- `_generate_coverage_path_for_area()` 将 mode 传给 `run_formal_planner_request(request, planner_mode)`；
- `request.public_config.planner_mode` 保持 `shelf_aware_turn_cost`；
- `request.artifacts_output_root` 使用 `maptools_shelf_aware_turn_cost_runs`；
- 成功结果写入 `CoveragePathManager`；
- `_last_coverage_planning_diagnostics` 被保存；
- 状态栏能展示 `shelf aware turn cost` 摘要。

测试：

```text
tests/test_main_window_flow.py::test_generate_coverage_path_uses_turn_cost_mode_from_dialog
```

边界：

- 该测试 monkeypatch planner 返回值，不运行真实算法；
- 它证明 UI 调用链不丢 mode，不证明最终路径质量；
- 最终路径质量由 delivery gate 的 19 区域候选基线负责。

### 2.4 coverage repo 自动生成闭环

已覆盖：

- `export_coverage_repo(..., auto_generate_missing=True)` 在 explicit `shelf_aware_turn_cost` 下调用 formal planner；
- `planner_mode` 透传；
- `request.public_config.write_artifacts=true`；
- 导出的 `planner_diagnostics` 保留 profile、requested/applied diff 和 readable summary。

测试：

```text
tests/test_coverage_repo_export_diagnostics.py::test_export_coverage_repo_dispatches_explicit_shelf_aware_turn_cost
```

## 3. 仍未自动化的真实 GUI 交互

以下内容仍未自动化，不能写成已完成：

- 真实鼠标点击算法单选按钮；
- 真实点击“显示高级参数”；
- 真实点击“生成”按钮并等待完整规划；
- 真实查看 `Coverage Planner Diagnostics...` 窗口；
- 真实点击“复制路径”“定位选中产物”等按钮；
- 文件管理器或桌面环境是否成功打开对应目录；
- 多平台窗口布局、字体、缩放和焦点行为。

这些内容属于完整 GUI 交互级验收，不属于当前自动化单元测试已经证明的范围。

## 4. 手工验收清单

手工验收只使用当前正式 UI，不运行研究脚本。

### 4.1 前置条件

- 当前分支已包含 `shelf_aware_turn_cost`；
- 使用工程 UI 打开以下项目之一：

```text
examples/maptools_projects/beiguoshangcheng_floor_3
examples/maptools_projects/beiguo_lanshan_1770397756
examples/maptools_projects/fourfloor_20250923_8
```

- 可以先用 `beiguoshangcheng_floor_3 area 5` 做一次冒烟，因为它暴露过路径形态和诊断可读性问题。
- 冒烟通过不代表 GUI 验收通过；正式手工验收至少应覆盖三个项目中各一个区域，并在需要发布前补齐固定三项目 19 区域的正式门禁。

### 4.2 参数面板验收

操作：

1. 进入覆盖路径生成；
2. 打开“覆盖路径参数”窗口；
3. 选择 `ShelfAware+TurnCost`；
4. 打开“显示高级参数”。

预期：

- 算法选择中存在 `shelfAware` 和 `ShelfAware+TurnCost`；
- `shelfAware` 不再出现所谓“原版/稳定版”的双入口；
- `ShelfAware+TurnCost` 的说明中显示 profile 固定覆盖；
- `ShelfAware+TurnCost` 不展示被固定覆盖的 CTG auxiliary 和 isolated jump cleanup 控件；
- `shelfAware` 模式下仍可展示 shelfAware 自身高级参数；
- 参数文字不重叠，窗口可读。

### 4.3 规划链路验收

操作：

1. 在当前区域选择 `ShelfAware+TurnCost`；
2. 点击生成；
3. 等待路径生成完成。

预期：

- 状态栏显示 `Planner: 规划器=shelf aware turn cost` 或等价摘要；
- 当前区域生成路径点；
- 没有自动降级成 `basic` 或 `shelf_aware`；
- 项目目录下出现 `maptools_shelf_aware_turn_cost_runs` 产物目录；
- 产物目录内至少包含 planner artifact manifest、路径图或路径 JSON。

### 4.4 诊断窗口验收

操作：

1. 生成路径后打开 `Coverage Planner Diagnostics...`；
2. 查看详情内容；
3. 如果存在 artifact 路径，尝试复制路径或定位选中产物。

预期：

- 能看到 profile id：`shelf_aware_turn_cost_repaired_grid_0_28`；
- 能看到 mode default overrides；
- 能看到 requested/applied diff；
- 能看到路径质量摘要；
- geometry risk 明确标记为只读诊断或未作为硬约束运行；
- artifact 路径可读，复制内容是绝对路径或明确可定位路径；
- 失败时有明确 warning，不静默吞掉。

### 4.5 手工记录格式

建议每次手工验收记录以下内容：

```text
验收时间：
分支/提交：
项目：
区域：
选择模式：
参数来源：默认 / 项目保存参数 / 手动修改
生成结果：成功 / 失败
状态栏摘要：
artifact 目录：
诊断窗口是否可打开：
复制/定位 artifact 是否可用：
截图路径：
问题记录：
结论：通过 / 需修复
```

## 5. 正式自动化命令

UI 契约：

```text
python3 -m pytest -q tests/test_main_window_flow.py
```

导出契约：

```text
python3 -m pytest -q tests/test_coverage_repo_export_diagnostics.py tests/test_coverage_repo_export_planner_modes.py
```

研究 venv 交付门禁：

```text
algorithms/turn_cost_coverage_research/.venv/bin/python \
  algorithms/turn_cost_coverage_research/scripts/baseline/run_shelf_aware_turn_cost_delivery_gate.py
```

注意：

- 交付门禁以研究 venv 为准；
- 系统 Python 可能因为 CTG/几何依赖差异导致效果基线漂移；
- 门禁脚本内部已固定 pytest 子进程 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，避免 ROS pytest 插件污染。

## 6. 本清单禁止事项

- 不把真实 widget smoke 写成完整 GUI e2e；
- 不用截图人工感觉替代 19 区域 candidate baseline；
- 不把 geometry readonly diagnostics 升级为硬约束；
- 不新增 UI mode；
- 不恢复旧 ShelfAware 原版入口；
- 不把研究后处理接入 `ShelfAware+TurnCost`；
- 不为了通过 GUI 验收修改算法结果。
