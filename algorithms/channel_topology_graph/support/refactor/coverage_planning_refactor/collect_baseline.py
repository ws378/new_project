"""采集 CoveragePlanning 局部重构 baseline。

说明：
    这里保留 `stage_a/b/c/d` 文件名，只因为 baseline 工件协议仍冻结在这套命名上。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json

from algorithms.channel_topology_graph.io import write_coverage_planning_result_json

from .normalize import (
    normalize_case_spec,
    normalize_stage_a,
    normalize_stage_b,
    normalize_stage_c,
    normalize_stage_d,
    write_json,
)
from .pipeline_case import REPO_ROOT, run_fixed_case


def main() -> None:
    """运行固定 case，并冻结四阶段基线。"""

    bundle = run_fixed_case()
    spec = bundle["spec"]
    resolved_geometry_config = bundle["resolved_geometry_config"]
    coverage_result = bundle["coverage_result"]
    baseline_root = (
        REPO_ROOT
        / "algorithms"
        / "channel_topology_graph"
        / "baselines"
        / "coverage_planning_refactor"
        / spec.case_name
    )
    baseline_root.mkdir(parents=True, exist_ok=True)

    metadata = {
        "generated_at": datetime.now().isoformat(),
        "spec": normalize_case_spec(spec, resolved_geometry_config=resolved_geometry_config),
        "baseline_policy": "current code, fixed case, fixed entry, fixed config",
    }
    write_json(baseline_root / "meta.json", metadata)

    raw_dir = baseline_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    result_json_path = write_coverage_planning_result_json(
        result=coverage_result,
        output_dir=raw_dir,
    )
    (raw_dir / "result_json_path.txt").write_text(str(result_json_path), encoding="utf-8")

    stages_dir = baseline_root / "stages"
    write_json(stages_dir / "stage_a_coverage_lanes_and_sweeps.json", normalize_stage_a(coverage_result))
    write_json(stages_dir / "stage_b_sweep_graph_layers.json", normalize_stage_b(coverage_result))
    write_json(stages_dir / "stage_c_sweep_cadence.json", normalize_stage_c(coverage_result))
    write_json(stages_dir / "stage_d_final_coverage_path.json", normalize_stage_d(coverage_result))

    summary = {
        "baseline_root": str(baseline_root.resolve()),
        "stage_files": [
            "stages/stage_a_coverage_lanes_and_sweeps.json",
            "stages/stage_b_sweep_graph_layers.json",
            "stages/stage_c_sweep_cadence.json",
            "stages/stage_d_final_coverage_path.json",
        ],
    }
    (baseline_root / "README.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(baseline_root.resolve()))


if __name__ == "__main__":
    main()
