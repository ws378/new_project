"""使用真实 case 跑 junction_rebuild。"""

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
    write_junction_rebuild_summary,
)
from algorithms.channel_topology_graph.renderers import (  # noqa: E402
    write_geometry_preparation_visualizations,
    write_junction_rebuild_visualizations,
)
from algorithms.channel_topology_graph.stages.geometry_preparation import (  # noqa: E402
    build_geometry_preparation,
)
from algorithms.channel_topology_graph.stages.junction_rebuild import (  # noqa: E402
    build_junction_rebuild,
)


def main() -> None:
    """执行真实 case 的 geometry_preparation + junction_rebuild 联调。"""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(__file__).resolve().parents[2] / "test_outputs" / f"junction_rebuild_real_case_{timestamp}"
    output_root.mkdir(parents=True, exist_ok=True)

    case_dir = (
        REPO_ROOT
        / "tests"
        / "fixtures"
        / "coverage_cases"
        / "case_demo"
    )
    case_input = load_plan1_case_input(case_dir=case_dir)
    geometry_result = build_geometry_preparation(
        raw_map=case_input.raw_map,
        region_constraint=case_input.region_constraint,
        config={
            "crop_box_px": case_input.meta["crop_box_px"],
            "open_kernel_m": 0.3,
            "short_side_branch_m": 1.2,
        },
    )
    geometry_viz = write_geometry_preparation_visualizations(
        result=geometry_result,
        output_dir=output_root / "geometry_viz",
        summary_viz=True,
        detail_viz=True,
        render_scale=8,
    )
    geometry_summary_path = write_geometry_preparation_summary(
        result=geometry_result,
        output_dir=output_root / "geometry_summary",
        extra_meta=case_input.meta,
    )

    rebuild_result = build_junction_rebuild(
        geometry_preparation_result=geometry_result,
        config={
            "intersection_merge_geodesic_px": 20,
            "initial_junction_zone_radius_px": 2,
            "initial_dead_end_zone_radius_px": 1,
            "junction_polygon_radius_px": 10.0,
            "dead_end_polygon_radius_px": 4.0,
        },
    )
    junction_viz = write_junction_rebuild_visualizations(
        geometry_result=geometry_result,
        result=rebuild_result,
        output_dir=output_root / "junction_viz",
        summary_viz=True,
        detail_viz=True,
        render_scale=8,
    )
    rebuild_summary_path = write_junction_rebuild_summary(
        result=rebuild_result,
        output_dir=output_root / "junction_summary",
        extra_meta=case_input.meta,
    )

    print(f"output_dir={output_root}")
    print(f"geometry_summary_json={geometry_summary_path}")
    print(f"junction_summary_json={rebuild_summary_path}")
    print(f"geometry_viz={geometry_viz}")
    print(f"junction_viz={junction_viz}")
    print(f"node_count={len(rebuild_result.node_info_list)}")
    print(f"edge_count={len(rebuild_result.edge_info_list)}")


if __name__ == "__main__":
    main()
