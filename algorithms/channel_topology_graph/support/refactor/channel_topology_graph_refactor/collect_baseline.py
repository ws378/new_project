"""采集 channel_topology_graph 全链重构 baseline。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json

from ._common import normalize_case_spec, write_json
from .normalize_coverage import normalize_coverage_result
from .normalize_geometry import normalize_geometry_result
from .normalize_junction import normalize_junction_result
from .normalize_topology import normalize_topology_result
from .pipeline_case import REPO_ROOT, run_fixed_case


STAGE_FILES = {
    "geometry_preparation": "geometry_preparation.json",
    "junction_rebuild": "junction_rebuild.json",
    "topology_graph_build": "topology_graph_build.json",
    "coverage_planning": "coverage_planning.json",
}


def main() -> None:
    """运行固定 case，并冻结全链 4 步 baseline。"""

    bundle = run_fixed_case()
    spec = bundle["spec"]
    resolved_pipeline_config = bundle["resolved_pipeline_config"]
    pipeline_result = bundle["pipeline_result"]
    baseline_root = (
        REPO_ROOT
        / "algorithms"
        / "channel_topology_graph"
        / "baselines"
        / "channel_topology_graph_refactor"
        / spec.case_name
    )
    baseline_root.mkdir(parents=True, exist_ok=True)

    metadata = {
        "generated_at": datetime.now().isoformat(),
        "spec": normalize_case_spec(spec, resolved_pipeline_config=resolved_pipeline_config),
        "baseline_policy": "current code, fixed case, fixed pipeline entry, fixed config",
    }
    write_json(baseline_root / "meta.json", metadata)

    stages_dir = baseline_root / "stages"
    write_json(
        stages_dir / STAGE_FILES["geometry_preparation"],
        normalize_geometry_result(pipeline_result.geometry_preparation_result),
    )
    write_json(
        stages_dir / STAGE_FILES["junction_rebuild"],
        normalize_junction_result(pipeline_result.junction_rebuild_result),
    )
    write_json(
        stages_dir / STAGE_FILES["topology_graph_build"],
        normalize_topology_result(pipeline_result.topology_graph_build_result),
    )
    write_json(
        stages_dir / STAGE_FILES["coverage_planning"],
        normalize_coverage_result(pipeline_result.coverage_planning_result),
    )

    summary = {
        "baseline_root": str(baseline_root.resolve()),
        "stage_files": [f"stages/{filename}" for filename in STAGE_FILES.values()],
    }
    (baseline_root / "README.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(str(baseline_root.resolve()))


if __name__ == "__main__":
    main()
