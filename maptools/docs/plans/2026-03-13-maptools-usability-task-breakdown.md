# MapTools Usability Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不改变核心业务能力的前提下，显著提升 maptools 的跨分辨率可用性、流程清晰度和错误可恢复性。  
**Architecture:** 采用“UI骨架先行 + 流程收敛 + 错误治理”三段式改造。优先改动入口与容器布局，避免先动算法层；依赖治理通过惰性加载与分级提示实现，不引入新进程。  
**Tech Stack:** Python 3, Tkinter, existing maptools MVC structure, pytest.

## Delivery Slice
- Iteration A（P0-1）: 响应式工具区
- Iteration B（P0-2）: 统一打开向导 + 会话状态区
- Iteration C（P0-3）: 错误与依赖治理 + 导入导出摘要

## Work Breakdown Table
| ID | Task | Owner | Files (Primary) | Est. | Dependencies | Verification |
|---|---|---|---|---|---|---|
| A1 | 盘点现有按钮并定义“常驻/折叠”清单 | PM+FE | `maptools/views/layout_components.py` | 0.5d | 无 | 评审通过 |
| A2 | 工具栏分组容器改造（支持折叠） | FE | `maptools/views/layout_components.py` | 1.0d | A1 | UI手工验证 |
| A3 | 增加断点策略（宽/中/窄屏） | FE | `maptools/views/layout_components.py` | 1.0d | A2 | 3分辨率截图比对 |
| A4 | Tooltip 与快捷键提示统一 | FE | `maptools/views/toolbar.py`(如有), `maptools/views/main_window.py` | 0.5d | A2 | 手工验证 |
| B1 | 统一“打开资源”入口与识别策略 | FE+BE | `maptools/views/main_window.py` | 1.0d | A2 | 导入三类型资源验证 |
| B2 | 会话状态区（当前地图/项目/脏状态） | FE | `maptools/views/main_window.py` | 0.5d | B1 | 状态变更验证 |
| B3 | 导入后摘要卡片（区域/路径/标签） | FE+BE | `maptools/views/main_window.py`, `maptools/utils/coverage_repo_import.py` | 0.5d | B1 | 导入后数据一致 |
| C1 | 可选依赖分级提示（不阻断启动） | BE | `algorithms/coverage_planning/planner_factory.py`, `maptools/views/main_window.py` | 0.5d | 无 | 缺依赖启动验证 |
| C2 | 错误文案标准化（问题/影响/建议） | FE+BE | `maptools/views/main_window.py` | 0.5d | C1 | 失败路径回归 |
| C3 | 导出前预检与输出清单提示 | BE+FE | `maptools/utils/coverage_repo_export.py`, `maptools/views/main_window.py` | 1.0d | B2 | 导出回归 |
| T1 | 增加回归测试（导入识别、依赖缺失兜底） | QA+BE | `tests/test_coverage_repo_import.py`, 新增 `tests/test_main_window_flow.py` | 1.0d | B1,C1 | pytest通过 |
| D1 | 用户文档更新（快速上手） | PM+QA | `README.md`, `docs/` | 0.5d | 全部 | 文档评审 |

## Execution Steps (Bite-Sized)
### Task 1: Baseline & Guardrails
**Files:**
- Modify: `maptools/views/main_window.py`
- Test: `tests/test_main_window_flow.py` (new)

1. 写失败测试：资源识别入口在三类输入下分流正确。  
2. 运行测试确认失败。  
3. 最小实现：抽出 `_open_resource()` 与类型识别分发。  
4. 运行测试确认通过。  
5. 提交：`feat: unify resource open entry`。

### Task 2: Responsive Toolbar
**Files:**
- Modify: `maptools/views/layout_components.py`
- Modify: `maptools/views/main_window.py`

1. 写可视断言清单（常驻按钮可见）。  
2. 实现分组容器与折叠菜单。  
3. 在窗口 resize 事件上应用断点策略。  
4. 手工验证三种分辨率。  
5. 提交：`feat: responsive grouped toolbar`。

### Task 3: Error UX & Optional Dependency
**Files:**
- Modify: `algorithms/coverage_planning/planner_factory.py`
- Modify: `maptools/views/main_window.py`
- Test: `tests/test_main_window_flow.py`

1. 写失败测试：缺失可选依赖时，basic 模式可继续。  
2. 实现分级提示与统一错误文案。  
3. 验证手工场景：选择 shelf_aware 时给 actionable message。  
4. 运行相关测试。  
5. 提交：`fix: degrade gracefully when optional planner dependency missing`。

### Task 4: Import/Export Feedback
**Files:**
- Modify: `maptools/views/main_window.py`
- Modify: `maptools/utils/coverage_repo_import.py`
- Modify: `maptools/utils/coverage_repo_export.py`

1. 增加导入结果摘要结构体到 UI 展示。  
2. 增加导出前预检与输出清单。  
3. 回归导入/导出现有流程。  
4. 提交：`feat: import-export summary and preflight checks`。

## Test Matrix
- 分辨率：1366x768 / 1920x1080 / 2560x1440
- 资源类型：map yaml / coverage repo yaml / project dir
- 算法依赖：可选 planner 依赖可用 / 不可用
- 关键操作：Open -> Edit -> Export 全链路

## Risk & Mitigation
- 风险：Tkinter 布局改动影响现有组件绑定。
- 缓解：先做容器级改造，控件 ID/命令回调不改名；每步加回归。
- 风险：错误文案改造遗漏分支。
- 缓解：统一错误处理辅助函数，逐步替换。
