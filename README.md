# map-tools-beiguo

本仓库当前包含 3 个主子工程：地图编辑器、算法集合、测试集工程。根层 `README.md` 只提供仓库级入口，不替子工程维护它们各自的产品/模块说明。

## 子工程入口

- `maptools/`
  - 地图编辑器子工程
  - 入口文档：`maptools/README.md`
  - 详细文档：`maptools/docs/`
- `algorithms/`
  - 覆盖规划算法集合
  - 入口文档：`algorithms/README.md`
  - 正式算法工程：
    - `algorithms/channel_topology_graph/`
    - `algorithms/coverage_planning/`
- `coverage_dataset/`
  - 测试集、样例、跑批与报告治理子工程
  - 入口文档：`coverage_dataset/README.md`
  - 详细文档：`coverage_dataset/docs/`

## 仓库级支持域

- `tools/`
  - 仓库级工具目录
  - 入口文档：`tools/README.md`
  - 当前覆盖规划工具入口：`tools/coverage_planning/README.md`
- `examples/`
  - 示例项目与示例输入
  - 入口文档：`examples/README.md`
- `tests/fixtures/`
  - 仓库级固定测试输入与夹具
  - 入口文档：`tests/fixtures/README.md`

## 文档分层

- `docs/`
  - 仓库级治理、重构执行和历史归档
- `maptools/docs/`
  - 地图编辑器需求、设计、使用说明与专题计划
- `algorithms/channel_topology_graph/docs/`
  - `channel_topology_graph` 算法工程文档
- `algorithms/coverage_planning/docs/`
  - `coverage_planning` 算法工程文档
- `coverage_dataset/docs/`
  - 测试集工程规则、报告治理、裁剪与标注工作流

约束：

- 不要再把某个子工程自己的需求、设计、quickstart、专题计划平铺回根层 `docs/`
- 每一层只维护自己那一层的文档职责

## 快速启动

本工程必须使用隔离的 Python 环境运行：只能使用 conda 环境或 venv 虚拟环境，不能直接使用系统全局 Python 环境安装依赖或启动入口。

首次拉取工程后，如果本机还没有可用环境，先执行安装脚本并按提示选择 conda 或 venv：

```bash
./setup_env.sh
```

安装完成后通过运行脚本启动地图编辑器：

```bash
./run_maptools.sh
```

运行脚本会优先使用仓库本地 `.venv`，否则尝试使用 conda `maptools` 环境；如果两者都不存在，会提示先执行 `./setup_env.sh`。

也可以显式指定环境类型：

```bash
./setup_env.sh conda
./run_maptools.sh --conda

./setup_env.sh venv
./run_maptools.sh --venv
```

如果你要手动执行，仍然必须先进入 conda 或 venv 环境：

### conda 环境

```bash
conda create -n maptools python=3.10 -y
conda activate maptools
python -m pip install -r requirements.txt
python -m maptools.main
```

### venv 环境

如果不使用 conda，也可以用 Python 3.10 自带的 venv：

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m maptools.main
```

如果启动时报 `No module named '_tkinter'`，说明当前 Python 运行时没有 Tk 支持，不是 pip 依赖缺失。macOS Homebrew Python 3.10 可先执行：

```bash
brew install python-tk@3.10
./setup_env.sh venv
```

地图编辑器的详细使用说明见 `maptools/README.md` 和 `maptools/docs/maptools_usability_quickstart.md`。
