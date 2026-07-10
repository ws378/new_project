"""对照当前实现与 channel_topology_graph 全链 baseline。"""

from __future__ import annotations

from datetime import datetime
from difflib import unified_diff
import json
import sys

from ._common import load_json, normalize_case_spec, write_json
from .collect_baseline import STAGE_FILES
from .normalize_coverage import normalize_coverage_result
from .normalize_geometry import normalize_geometry_result
from .normalize_junction import normalize_junction_result
from .normalize_topology import normalize_topology_result
from .pipeline_case import REPO_ROOT, run_fixed_case


def main() -> None:
    """运行当前代码，并与冻结 baseline 做结构化对照。"""

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
    compare_root = (
        REPO_ROOT
        / "algorithms"
        / "channel_topology_graph"
        / "compare"
        / "channel_topology_graph_refactor"
        / spec.case_name
        / datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    baseline_dir = compare_root / "baseline"
    actual_dir = compare_root / "actual"
    diff_dir = compare_root / "diff"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    actual_dir.mkdir(parents=True, exist_ok=True)
    diff_dir.mkdir(parents=True, exist_ok=True)

    actual_payloads = {
        "geometry_preparation": normalize_geometry_result(pipeline_result.geometry_preparation_result),
        "junction_rebuild": normalize_junction_result(pipeline_result.junction_rebuild_result),
        "topology_graph_build": normalize_topology_result(pipeline_result.topology_graph_build_result),
        "coverage_planning": normalize_coverage_result(pipeline_result.coverage_planning_result),
    }
    compare_summary: dict[str, object] = {
        "generated_at": datetime.now().isoformat(),
        "spec": normalize_case_spec(spec, resolved_pipeline_config=resolved_pipeline_config),
        "compare_root": str(compare_root.resolve()),
        "stage_results": {},
    }

    has_diff = False
    for stage_key, filename in STAGE_FILES.items():
        baseline_payload = load_json(baseline_root / "stages" / filename)
        actual_payload = actual_payloads[stage_key]
        write_json(baseline_dir / filename, baseline_payload)
        write_json(actual_dir / filename, actual_payload)
        baseline_text = json.dumps(baseline_payload, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
        actual_text = json.dumps(actual_payload, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
        diff_lines = list(
            unified_diff(
                baseline_text,
                actual_text,
                fromfile=f"baseline/{filename}",
                tofile=f"actual/{filename}",
                lineterm="",
            )
        )
        (diff_dir / f"{stage_key}.diff").write_text("\n".join(diff_lines), encoding="utf-8")
        matched = baseline_payload == actual_payload
        if not matched:
            has_diff = True
        compare_summary["stage_results"][stage_key] = {
            "file": filename,
            "matched": bool(matched),
            "diff_line_count": int(len(diff_lines)),
        }

    write_json(compare_root / "summary.json", compare_summary)
    print(str(compare_root.resolve()))
    if has_diff:
        sys.exit(1)


if __name__ == "__main__":
    main()
