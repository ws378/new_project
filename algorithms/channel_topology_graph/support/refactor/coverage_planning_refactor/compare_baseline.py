"""对照当前实现与冻结 baseline。

说明：
    这里保留 `stage_a/b/c/d` 命名，只因为 compare 工件协议仍冻结在这套键名上。
    它不代表当前正式源码仍以 Stage A/B/C/D 作为业务命名。
"""

from __future__ import annotations

from datetime import datetime
from difflib import unified_diff
from pathlib import Path
import json
import sys

from .normalize import (
    load_json,
    normalize_case_spec,
    normalize_stage_a,
    normalize_stage_b,
    normalize_stage_c,
    normalize_stage_d,
    write_json,
)
from .pipeline_case import REPO_ROOT, run_fixed_case


STAGE_FILES = {
    "stage_a": "stage_a_coverage_lanes_and_sweeps.json",
    "stage_b": "stage_b_sweep_graph_layers.json",
    "stage_c": "stage_c_sweep_cadence.json",
    "stage_d": "stage_d_final_coverage_path.json",
}


def main() -> None:
    """运行当前代码，并与冻结 baseline 做结构化对照。"""

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
    compare_root = (
        REPO_ROOT
        / "algorithms"
        / "channel_topology_graph"
        / "compare"
        / "coverage_planning_refactor"
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
        "stage_a": normalize_stage_a(coverage_result),
        "stage_b": normalize_stage_b(coverage_result),
        "stage_c": normalize_stage_c(coverage_result),
        "stage_d": normalize_stage_d(coverage_result),
    }
    compare_summary: dict[str, object] = {
        "generated_at": datetime.now().isoformat(),
        "spec": normalize_case_spec(spec, resolved_geometry_config=resolved_geometry_config),
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
