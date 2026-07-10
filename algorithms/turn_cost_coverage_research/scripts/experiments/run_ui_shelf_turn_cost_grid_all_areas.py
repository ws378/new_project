"""批量运行 UI shelfAware 原链路 + turn_cost 规则节点生成实验。"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PACKAGE_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from algorithms.coverage_planning.contracts import SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR

DEFAULT_PROJECT_NAMES = (
    "beiguo_lanshan_1770397756",
    "beiguoshangcheng_floor_3",
    "fourfloor_20250923_8",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PACKAGE_ROOT / "output", help="输出根目录。")
    parser.add_argument("--project-name", action="append", choices=DEFAULT_PROJECT_NAMES, help="只运行指定项目，可重复。")
    parser.add_argument("--area-id", action="append", type=int, help="只运行指定 area_id，可重复；会应用到所有选中项目。")
    parser.add_argument(
        "--node-generation-mode",
        choices=("turn_cost_regular_grid", "turn_cost_repaired_grid"),
        default="turn_cost_repaired_grid",
        help="透传单区域实验的节点生成模式。",
    )
    parser.add_argument(
        "--repaired-grid-max-offset-factor",
        type=float,
        default=SHELF_AWARE_TURN_COST_REPAIRED_GRID_MAX_OFFSET_FACTOR,
        help="透传受控补点最大偏移倍率。",
    )
    parser.add_argument("--batch-reconnect-passes", type=int, default=2, help="透传当前主线批量候选重连轮数。")
    parser.add_argument("--batch-reconnect-max-candidates", type=int, default=30, help="透传每轮候选数量。")
    parser.add_argument("--skip-downstream", action="store_true", help="只跑原始路径，不跑诊断和批量候选重连。")
    parser.add_argument("--run-raw-diagnostics", action="store_true", help="只对原始路径跑诊断，不执行批量重连。")
    return parser.parse_args()


def _load_area_ids(project_dir: Path, allowed_area_ids: set[int] | None) -> list[int]:
    payload = json.loads((project_dir / "areas.json").read_text(encoding="utf-8"))
    area_ids = sorted(int(item["area_id"]) for item in payload.get("areas", []))
    if allowed_area_ids is not None:
        area_ids = [area_id for area_id in area_ids if area_id in allowed_area_ids]
    return area_ids


def _read_summary(run_dir: Path | None) -> dict[str, Any]:
    if run_dir is None:
        return {}
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        return {}
    return json.loads(summary_path.read_text(encoding="utf-8"))


def _read_final_diagnostics(summary: dict[str, Any]) -> dict[str, Any]:
    diagnostics_dir = summary.get("downstream", {}).get("final_diagnostics_run_dir")
    if not diagnostics_dir:
        return {}
    path = Path(str(diagnostics_dir)) / "summary.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _last_existing_path_from_stdout(stdout: str) -> Path | None:
    for line in reversed([item.strip() for item in stdout.splitlines() if item.strip()]):
        candidate = Path(line).expanduser()
        if candidate.exists():
            return candidate.resolve()
    return None


def _run_raw_diagnostics(*, area_run_dir: Path, final_path_pixels: Path, output_root: Path) -> Path | None:
    if not area_run_dir.is_dir() or not final_path_pixels.is_file():
        return None
    script_path = PACKAGE_ROOT / "scripts" / "diagnostics" / "run_shelf_path_turn_cost_diagnostics.py"
    command = [
        sys.executable,
        str(script_path),
        "--input-run-dir",
        str(area_run_dir),
        "--path-pixels-path",
        str(final_path_pixels),
        "--output-root",
        str(output_root),
    ]
    completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
    if completed.returncode != 0:
        return None
    return _last_existing_path_from_stdout(completed.stdout)


def _run_one(
    *,
    args: argparse.Namespace,
    script_path: Path,
    run_dir: Path,
    project_name: str,
    area_id: int,
) -> dict[str, Any]:
    project_dir = REPO_ROOT / "examples" / "maptools_projects" / project_name
    command = [
        sys.executable,
        str(script_path),
        "--project-dir",
        str(project_dir),
        "--area-id",
        str(area_id),
        "--node-generation-mode",
        str(args.node_generation_mode),
        "--repaired-grid-max-offset-factor",
        str(float(args.repaired_grid_max_offset_factor)),
        "--batch-reconnect-passes",
        str(int(args.batch_reconnect_passes)),
        "--batch-reconnect-max-candidates",
        str(int(args.batch_reconnect_max_candidates)),
        "--output-root",
        str(run_dir / "areas"),
    ]
    if bool(args.skip_downstream) or bool(args.run_raw_diagnostics):
        command.append("--skip-downstream")
    completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
    area_run_dir = _last_existing_path_from_stdout(completed.stdout)
    summary = _read_summary(area_run_dir)
    final_path_pixels_text = str(summary.get("downstream", {}).get("final_path_pixels", summary.get("artifacts", {}).get("path_pixels", "")))
    final_path_pixels = Path(final_path_pixels_text) if final_path_pixels_text else None
    raw_diagnostics_run_dir = None
    if completed.returncode == 0 and bool(args.run_raw_diagnostics) and area_run_dir is not None and final_path_pixels is not None:
        raw_diagnostics_run_dir = _run_raw_diagnostics(
            area_run_dir=area_run_dir,
            final_path_pixels=final_path_pixels,
            output_root=run_dir / "raw_diagnostics",
        )
    final_diagnostics = _read_summary(raw_diagnostics_run_dir) if raw_diagnostics_run_dir is not None else _read_final_diagnostics(summary)
    diagnostics = final_diagnostics.get("diagnostics", {})
    local_quality = final_diagnostics.get("local_quality", {})
    lane_spacing = final_diagnostics.get("lane_spacing_quality", {})
    segment_crossing = final_diagnostics.get("segment_crossing_quality", {})
    experiment = summary.get("experiment", {})
    return {
        "project_name": project_name,
        "area_id": int(area_id),
        "returncode": int(completed.returncode),
        "area_run_dir": str(area_run_dir) if area_run_dir else "",
        "stderr": completed.stderr,
        "status": "success" if completed.returncode == 0 and summary.get("success", True) else "failed",
        "saved_project_params_used": experiment.get("saved_project_params_used"),
        "fallback_to_dialog_defaults": experiment.get("fallback_to_dialog_defaults"),
        "final_diagnostics_run_dir": str(raw_diagnostics_run_dir) if raw_diagnostics_run_dir else summary.get("downstream", {}).get("final_diagnostics_run_dir", ""),
        "final_path_pixels": str(final_path_pixels) if final_path_pixels is not None else "",
        "coverage_ratio": local_quality.get("coverage_ratio"),
        "narrow_coverage_ratio": local_quality.get("narrow_coverage_ratio"),
        "long_jump_count": diagnostics.get("long_jump_count"),
        "turn_hotspot_count": diagnostics.get("turn_hotspot_count"),
        "infeasible_segment_count": local_quality.get("infeasible_segment_count"),
        "lane_over_dense_count": lane_spacing.get("over_dense_count"),
        "lane_over_sparse_count": lane_spacing.get("over_sparse_count"),
        "lane_spacing_issue_count": int(lane_spacing.get("over_dense_count", 0) or 0) + int(lane_spacing.get("over_sparse_count", 0) or 0),
        "segment_crossing_count": segment_crossing.get("crossing_count"),
    }


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fieldnames = (
        "project_name",
        "area_id",
        "status",
        "returncode",
        "saved_project_params_used",
        "fallback_to_dialog_defaults",
        "coverage_ratio",
        "narrow_coverage_ratio",
        "long_jump_count",
        "turn_hotspot_count",
        "infeasible_segment_count",
        "lane_over_dense_count",
        "lane_over_sparse_count",
        "lane_spacing_issue_count",
        "segment_crossing_count",
        "area_run_dir",
        "final_diagnostics_run_dir",
        "final_path_pixels",
    )
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in fieldnames})


def main() -> None:
    args = parse_args()
    run_dir = Path(args.output_root).expanduser().resolve() / (
        "run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_ui_shelf_turn_cost_grid_all_areas"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    project_names = tuple(args.project_name) if args.project_name else DEFAULT_PROJECT_NAMES
    allowed_area_ids = set(int(value) for value in args.area_id) if args.area_id else None
    script_path = PACKAGE_ROOT / "scripts" / "experiments" / "run_ui_shelf_turn_cost_grid_experiment.py"
    records: list[dict[str, Any]] = []
    for project_name in project_names:
        project_dir = REPO_ROOT / "examples" / "maptools_projects" / project_name
        for area_id in _load_area_ids(project_dir, allowed_area_ids):
            records.append(_run_one(args=args, script_path=script_path, run_dir=run_dir, project_name=project_name, area_id=area_id))

    payload = {
        "runner": "run_ui_shelf_turn_cost_grid_all_areas",
        "case_group": "ui_shelf_aware_turn_cost_node_generation_batch",
        "node_generation_mode": str(args.node_generation_mode),
        "repaired_grid_max_offset_factor": float(args.repaired_grid_max_offset_factor),
        "batch_reconnect_passes": int(args.batch_reconnect_passes),
        "batch_reconnect_max_candidates": int(args.batch_reconnect_max_candidates),
        "skip_downstream": bool(args.skip_downstream),
        "run_raw_diagnostics": bool(args.run_raw_diagnostics),
        "project_names": list(project_names),
        "area_count": int(len(records)),
        "success_count": int(sum(1 for record in records if record.get("status") == "success")),
        "failed_count": int(sum(1 for record in records if record.get("status") != "success")),
        "areas": records,
        "artifacts": {
            "summary": str(run_dir / "summary.json"),
            "summary_csv": str(run_dir / "批量区域指标.csv"),
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(run_dir / "批量区域指标.csv", records)
    print(run_dir)
    if payload["failed_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
