"""使用真实 case 跑 geometry_preparation。

该脚本直接读取 `plan1_aisle_graph_prototype/inputs/case_01`，
把 geometry_preparation 结果、统计摘要和可视化一起落到带时间戳目录中。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.channel_topology_graph.io import (  # noqa: E402
    load_plan1_case_input,
    write_geometry_preparation_summary,
)
from algorithms.channel_topology_graph.renderers import (  # noqa: E402
    write_geometry_preparation_visualizations,
)
from algorithms.channel_topology_graph.stages.geometry_preparation import (  # noqa: E402
    build_geometry_preparation,
)


def main() -> None:
    """执行真实 case 的 geometry_preparation 测试。"""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(__file__).resolve().parents[2] / "test_outputs" / f"geometry_preparation_real_case_{timestamp}"
    output_root.mkdir(parents=True, exist_ok=True)

    case_dir = (
        REPO_ROOT
        / "tests"
        / "fixtures"
        / "coverage_cases"
        / "case_demo"
    )
    case_input = load_plan1_case_input(case_dir=case_dir)
    result = build_geometry_preparation(
        raw_map=case_input.raw_map,
        region_constraint=case_input.region_constraint,
        config={
            "crop_box_px": case_input.meta["crop_box_px"],
            "open_kernel_m": 0.3,
            "short_side_branch_m": 1.2,
        },
    )
    viz_info = write_geometry_preparation_visualizations(
        result=result,
        output_dir=output_root / "viz",
        summary_viz=True,
        detail_viz=True,
        render_scale=8,
    )
    summary_path = write_geometry_preparation_summary(
        result=result,
        output_dir=output_root,
        extra_meta=case_input.meta,
    )
    print(f"output_dir={output_root}")
    print(f"summary_json={summary_path}")
    print(f"gray_shape={result.gray.shape}")
    print(f"skeleton_pixels={len(result.skeleton_pixels_rc)}")
    print(f"viz={viz_info}")


if __name__ == "__main__":
    main()
