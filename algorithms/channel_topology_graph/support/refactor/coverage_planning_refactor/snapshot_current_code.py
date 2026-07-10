"""冻结当前 CoveragePlanning 正式代码快照。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

from .pipeline_case import REPO_ROOT


SNAPSHOT_FILES = (
    "algorithms/channel_topology_graph/stages/coverage_planning.py",
    "algorithms/channel_topology_graph/coverage_planning/__init__.py",
    "algorithms/channel_topology_graph/coverage_planning/coverage_lane_sweep/coverage_lane_sweep_build.py",
    "algorithms/channel_topology_graph/coverage_planning/sweep_graph/sweep_graph_build.py",
    "algorithms/channel_topology_graph/coverage_planning/sweep_cadence/sweep_cadence_build.py",
    "algorithms/channel_topology_graph/coverage_planning/final_coverage_path/final_path_connectors.py",
    "algorithms/channel_topology_graph/coverage_planning/final_coverage_path/final_path_core.py",
    "algorithms/channel_topology_graph/contracts/coverage_lane_sweep_stage_results.py",
    "algorithms/channel_topology_graph/contracts/sweep_graph_stage_results.py",
    "algorithms/channel_topology_graph/contracts/sweep_cadence_stage_results.py",
    "algorithms/channel_topology_graph/contracts/final_coverage_path_stage_results.py",
    "algorithms/channel_topology_graph/tests/test_coverage_planning.py",
)


def main() -> None:
    """把当前正式代码快照复制到迁移期只读目录。"""

    snapshot_name = datetime.now().strftime("coverage_planning_round_%Y%m%d_%H%M%S")
    output_root = (
        REPO_ROOT
        / "algorithms"
        / "channel_topology_graph"
        / "baseline_snapshots"
        / snapshot_name
        / "code_snapshot"
    )
    output_root.mkdir(parents=True, exist_ok=True)
    for relative_path in SNAPSHOT_FILES:
        source = REPO_ROOT / relative_path
        target = output_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    print(str(output_root.resolve()))


if __name__ == "__main__":
    main()
