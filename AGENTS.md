# 地图工具协作指南

## 沟通和文档

- 面向人的新增文档、提交说明、PR/MR 描述和测试结论默认使用中文。
- 技术标识保持原文，例如文件格式、算法名、参数名、坐标系、脚本命令和错误日志。

## 算法交付跟踪联动

- 算法交付跟踪入口：`/home/yuanyayun/code/algorithm/robot/algorithm-delivery-tracking`。
- 本仓库属于每日内部 Git 检查范围，默认只整理 yuanyayun 相关提交。
- 涉及地图编辑、路径编辑、转弯代价、覆盖路径、地图导入导出或交付地图处理的变化时，提交或 PR/MR 描述应补充：
  - `影响范围`：功能、脚本、输入输出格式、地图样例、算法参数。
  - `验证情况`：样例地图验证、静态检查、人工检查或尚未验证。
  - `证据路径`：测试记录、生成结果、截图外部路径或样例工程路径。
  - `关联跟踪`：对应算法交付跟踪仓库中的任务 ID 或风险 ID。

## 测试口径

- 地图工具输出影响导航、覆盖清扫或仿真验证时，需要说明下游链路是否已验证。

## 仿真验证（Route C — 轻量管线）

### 启动方式
- 从 GUI 菜单 `Tools → 启动仿真`：导出 map+path → 调用 `ros_nodes/launch_nav2_sim.py`
- 手动 `ros2 launch`：`ros2 launch /path/to/sim_demo.launch.py map_yaml:=... path_yaml:=...`

### 节点组成
| 节点 | 脚本 | 发布 |
|------|------|------|
| diff_drive_sim | `ros_nodes/diff_drive_sim.py` | `/odom`, `/tf`, `/actual_driven_path`, `/robot_footprint` Marker |
| simple_path_follower | `ros_nodes/simple_path_follower.py` | `/coverage_path` (Path), `/cmd_vel` |
| map_server | `nav2_map_server` | `/map` (需 lifecycle configure+activate) |
| rviz2 | `rviz2` | — |

### 数据流
1. `simple_path_follower` 读 YAML 路径点 → pure pursuit → `Twist` → `/cmd_vel`
2. `diff_drive_sim` 收 `/cmd_vel` → 运动学积分 → `/odom` + `/tf`
3. `simple_path_follower` 收 `/odom` → 计算到下一目标点的误差 → 继续发 `/cmd_vel`
4. RViz 显示 `/map`, `/coverage_path`, `/actual_driven_path`, `/robot_footprint`

### Route B 现状（已验证通过）
- **Bugs Found & Fixed**:
  1. **pkill -x 不匹配**（2026-07-14）：Linux `comm` 字段限制 15 字符，`controller_server` → `controller_serv`，`nav2_costmap_2d` → `nav2_costmap_2` → 改用 `pkill -f` + 路径模式
  2. **生命周期服务路径**（2026-07-14）：`nav2_costmap_2d` 的 lifecycle service 在 `/{node}/{instance}/change_state`（如 `/local_costmap/local_costmap/change_state`），不是 `/{node}/change_state`
  3. **ROS2 daemon 干扰**（2026-07-14）：`ros2 lifecycle set` 依赖 daemon，daemon 被杀后返回 `!rclpy.ok()` → cleanup 中加 `ros2 daemon stop/start`
- **已验证**：DWB 控制器接收 6m 分段路径，CMD 正常输出（v=0.53~0.80m/s, Speed=0.80m/s），Segments 持续 SUCCEEDED
- 截图、生成地图、大型样例工程和临时结果不直接提交，除非它们是明确需要版本管理的轻量测试夹具。

## 区域标签切割功能

### 操作流程
- 右键区域标签 → "切割区域" → 点击定义切割线（≥2 点）→ 双击完成
- C 键快捷键：鼠标在区域标签上时进入切割模式
- Esc 取消

### 算法
- 用 `split_polygon_by_line` 按切割线方向将区域分为左/右两部分
- 首尾点定义切割线方向，函数自动延长至穿过整个区域
- 左/右两侧各自成为新区域标签，原标签被删除（支持 undo/redo）
- 切割线预览以红色虚线延伸到画布边缘，便于观察切割效果
- 原方案（`subtract_polygon` 多边形减法 + 桥接孔洞）已废弃，改用无面积损失的线切割

### 相关文件
- `maptools/utils/geometry_utils.py`：`split_polygon_by_line`（Sutherland-Hodgman 半边平面裁剪）
- `maptools/controllers/commands/split_area_label_command.py`：`SplitAreaLabelCommand`
- `maptools/views/map_canvas.py`：`_enter_cut_mode` / `_redraw_cut_preview` / `_finalize_cut_polygon`
- `maptools/views/main_window.py`：`_do_split_area_label` / `_try_enter_cut_mode`
