"""geometry_preparation 可视化 smoke 运行。

该脚本用于快速验证 summary/detail 可视化能否在真实文件夹中落盘。
输出目录会自动带年月日时分秒时间戳。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    # 脚本直接运行时，显式把仓库根目录加入模块搜索路径，避免依赖外部环境变量。
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.channel_topology_graph.renderers import write_geometry_preparation_visualizations
from algorithms.channel_topology_graph.stages.geometry_preparation import build_geometry_preparation


def build_demo_map() -> np.ndarray:
    """构造一张包含主十字通道和短枝的示例图。"""

    raw = np.zeros((96, 96), dtype=np.uint8)
    raw[12:84, 45:51] = 255
    raw[45:51, 12:84] = 255
    raw[68:74, 68:78] = 255
    raw[18:24, 64:70] = 255
    return raw


def main() -> None:
    """执行一次带时间戳输出目录的可视化 smoke 运行。"""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(__file__).resolve().parents[2] / "test_outputs" / f"geometry_preparation_{timestamp}"
    output_root.mkdir(parents=True, exist_ok=True)

    raw = build_demo_map()
    result = build_geometry_preparation(
        raw_map={"gray": raw, "resolution_m_per_px": 0.05},
        config={
            "open_kernel_px": 1,
            "short_side_branch_px": 6,
        },
    )
    viz_info = write_geometry_preparation_visualizations(
        result=result,
        output_dir=output_root,
        summary_viz=True,
        detail_viz=True,
        render_scale=8,
    )
    print(f"output_dir={output_root}")
    print(f"skeleton_pixels={len(result.skeleton_pixels_rc)}")
    print(f"viz={viz_info}")


if __name__ == "__main__":
    main()
