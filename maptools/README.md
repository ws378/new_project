# ROS2 地图编辑工具

用于编辑 ROS2 地图（PGM + YAML）的轻量级 GUI 工具，支持栅格修正、禁行区/仅通行区/虚拟墙/基站标注，并可调整原点与旋转地图，导出可供 Nav2 使用的地图与图层。

## 适用场景

适合快速修正建图结果、标注机器人禁行区域、设置虚拟墙与基站位置，并输出 Nav2 静态地图与辅助图层。

## 主要功能

- 加载 ROS2 标准地图（YAML + PGM）
- 画笔/橡皮擦修正栅格地图
- 原点设置与地图旋转
- 禁行区、仅通行区、虚拟墙、基站标注
- 撤销/重做
- 导出 Nav2 地图与标注图层

## 安装

必须使用隔离的 Python 环境运行本项目：只能使用 conda 或 venv，不能直接使用系统全局 Python 环境。

首次拉取工程后，如果还没有环境，推荐从仓库根目录执行：

```bash
./setup_env.sh
```

脚本会提示选择 conda 或 venv，并安装 `requirements.txt` 中的运行依赖。

也可以手动安装。

### conda

```bash
conda create -n maptools python=3.10 -y
conda activate maptools
python -m pip install -r requirements.txt
```

### venv

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果启动时报 Tkinter 相关错误，请先安装系统 Tk 组件，再重试。常见修复：

```bash
# macOS Homebrew Python 3.10
brew install python-tk@3.10
./setup_env.sh venv

# Ubuntu / Debian
sudo apt install python3-tk
./setup_env.sh venv
```

## 启动

```bash
./run_maptools.sh
```

## 快速上手

1. 启动应用。
2. 通过主入口 `File -> Open Resource...` 打开资源：
   - 先选资源文件（YAML），系统自动识别地图 YAML（`map.yaml`）或 coverage repo YAML（`coverage_path_master.yaml`）
   - 也支持选择工程文件 `*.mapproj` 直接打开项目
   - 若未选择文件，可继续选择项目目录并加载 `project.json`
   - 旧入口位于 `File -> Advanced`，用于兼容原流程
3. 在工具栏选择工具进行编辑或标注（支持快捷键，鼠标悬停按钮可见 Tooltip）。
4. `File -> Save Project...` 保存项目，便于后续继续编辑。
5. `File -> Export for Nav2...` 导出可用于 Nav2 的地图与图层。
6. `File -> Export Coverage Repo...` 导出覆盖路径仓库（导出前会显示预检和输出清单）。

可用于手工打开的样例工程位于 `examples/maptools_projects/`。自动化测试使用的固定输入位于 `tests/fixtures/`，不要再从根目录 `sample/` 或 `output_base/` 读取。

## 可用性增强（2026-03）

- 响应式工具栏断点：
  - 窄屏（<1300）：仅常用工具常驻，其余折叠到 `More Tools`
  - 中屏（1300-1799）：常用+向量工具常驻，路径工具折叠
  - 宽屏（>=1800）：全部工具常驻
- 会话状态区：
  - 实时显示当前地图、项目目录、脏状态、当前布局断点与快捷键提示
- 覆盖路径算法可选依赖降级：
  - 选择 `shelf_aware` 但缺少依赖时，会提示并自动回退 `basic`，不阻断流程
- 导入摘要与导出清单：
  - 导入 coverage repo 后显示 map/rooms/nodes/segments/labels 摘要
  - 导出 coverage repo 前执行预检并展示即将生成的文件清单

详细流程说明见 `maptools/docs/maptools_usability_quickstart.md`。

## 常用操作

- 缩放：鼠标滚轮。
- 平移：中键拖拽；或选择 `Pan` 工具后左键拖拽。
- 禁行区/仅通行区：左键逐点绘制，多边形双击完成。
- 虚拟墙：左键按下拖拽形成线段，松开完成。
- 基站：左键按下拖拽确定方向，松开完成。
- 原点：选择 `Set Origin` 后单击地图设置新原点，完成后自动切回平移工具。
- 撤销/重做：`Ctrl+Z` / `Ctrl+Y`。
- 工具快捷键：`V/Space/B/L/E/O/F/P/W/S/A/1/2/3/4/5`（详见会话状态区 `Shortcuts`）

## 项目保存格式

`File -> Save Project...` 会在选择的目录下生成：

- `project.json`：项目信息（包含项目内地图 YAML 路径）
- `<project_name>.mapproj`：工程入口文件（推荐后续通过该文件打开）
- `edit_layer.npy`：栅格编辑层
- `annotations.json`：向量标注数据

## 导出内容

`File -> Export for Nav2...` 会在选择的目录下生成：

- `map.pgm` + `map.yaml`：合并编辑层后的主地图
- `map_forbidden.pgm` + `map_forbidden.yaml`：禁行区图层
- `map_virtual_wall.pgm` + `map_virtual_wall.yaml`：虚拟墙图层
- `map_pass_only.pgm` + `map_pass_only.yaml`：仅通行区图层
- `annotations.json`：原始标注数据

所有导出 YAML 共享同一份分辨率与原点参数，适合直接供 Nav2 使用。`map_forbidden.yaml` 会固定导出 `free_thresh: 0.0`，使禁行区掩码的白色背景在 Nav2 中保持 unknown，避免 KeepoutFilter 将主地图 unknown 区域误清成 free。

## 常见问题

1. 地图打不开或显示空白
请确认 YAML 中的 `image` 路径指向有效的 PGM 文件，并确保 YAML 与 PGM 在同一目录或路径正确。

2. 坐标/方向不对
请检查 `resolution` 与 `origin` 是否正确，必要时使用 `Set Origin` 或 `Rotate Map...` 进行修正。

3. 图层不显示
请确认右侧 `Layers` 中对应图层已勾选。
