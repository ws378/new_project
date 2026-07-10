"""研究运行产物与 summary 写入工具。"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2


CASE_STATUSES = {"success", "failure", "partial", "skipped"}
ROOT_SUMMARY_CONTRACT_VERSION = "turn_cost_coverage_research.root.v1"
STAGE_STATUSES = {
    "success",
    "failure",
    "skipped_not_implemented",
    "skipped_dependency_missing",
    "skipped_not_applicable",
}
OFFICIAL_CASE_GROUPS = {"paper_official_algorithm_steps", "maptools_official_algorithm_steps"}


@dataclass(frozen=True)
class ArtifactRecord:
    name: str
    stage: str
    path: str
    required: bool
    status: str
    bytes: int
    readable: bool
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "stage": self.stage,
            "path": self.path,
            "required": self.required,
            "status": self.status,
            "bytes": self.bytes,
            "readable": self.readable,
            "note": self.note,
        }


@dataclass
class RunSummary:
    case_id: str
    case_group: str
    status: str = "success"
    failure_stage: str = ""
    failure_reason: str = ""
    failure_detail: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    dependencies: dict[str, Any] = field(default_factory=dict)
    stage_status: dict[str, str] = field(default_factory=dict)
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    runtime_by_stage_s: dict[str, float] = field(default_factory=dict)
    third_party_usage: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        if self.status not in CASE_STATUSES:
            raise ValueError(f"unknown case status: {self.status}")
        invalid_stage_statuses = {
            stage: status
            for stage, status in self.stage_status.items()
            if status not in STAGE_STATUSES
        }
        if invalid_stage_statuses:
            raise ValueError(f"unknown stage statuses: {invalid_stage_statuses}")
        return {
            "case_id": self.case_id,
            "case_group": self.case_group,
            "status": self.status,
            "failure_stage": self.failure_stage,
            "failure_reason": self.failure_reason,
            "failure_detail": self.failure_detail,
            "input": dict(self.input),
            "dependencies": dict(self.dependencies),
            "stage_status": dict(self.stage_status),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "metrics": dict(self.metrics),
            "runtime_by_stage_s": dict(self.runtime_by_stage_s),
            "third_party_usage": list(self.third_party_usage),
        }


def default_dependencies(
    mesh_backend: str = "pcpptc_official_hex_delaunay",
    solver_backend: str = "pcpptc_official_gurobi_or_highs_blossom_pcst",
) -> dict[str, Any]:
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.replace("\n", " "),
        "mesh_backend": mesh_backend,
        "solver_backend": solver_backend,
        "optional_missing": [],
    }


def ensure_run_dir(path: str | Path) -> Path:
    run_dir = Path(path)
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def is_readable_artifact(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg"}:
        return cv2.imread(str(path), cv2.IMREAD_UNCHANGED) is not None
    if suffix == ".json":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
    return True


def inspect_artifact(
    run_dir: str | Path,
    relative_path: str,
    *,
    stage: str,
    required: bool,
    status: str = "success",
    note: str = "",
) -> ArtifactRecord:
    if status not in STAGE_STATUSES:
        raise ValueError(f"unknown artifact status: {status}")
    root = Path(run_dir)
    path = root / relative_path
    exists = path.is_file()
    size = int(path.stat().st_size) if exists else 0
    readable = is_readable_artifact(path)
    effective_status = status
    if required and (not exists or size <= 0 or not readable):
        effective_status = "failure"
    return ArtifactRecord(
        name=Path(relative_path).name,
        stage=stage,
        path=relative_path,
        required=bool(required),
        status=effective_status,
        bytes=size,
        readable=readable,
        note=note,
    )


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_summary_contract(summary: RunSummary) -> list[str]:
    errors: list[str] = []
    if not summary.case_id:
        errors.append("case_id is empty")
    if not summary.case_group:
        errors.append("case_group is empty")
    if summary.status not in CASE_STATUSES:
        errors.append(f"unknown case status: {summary.status}")
    if not summary.dependencies:
        errors.append("dependencies is empty")
    if not summary.stage_status:
        errors.append("stage_status is empty")
    for stage, status in summary.stage_status.items():
        if status not in STAGE_STATUSES:
            errors.append(f"stage {stage} has unknown status: {status}")

    failed_required_artifacts = [
        artifact.path
        for artifact in summary.artifacts
        if artifact.required and (artifact.status != "success" or artifact.bytes <= 0 or not artifact.readable)
    ]
    if failed_required_artifacts:
        errors.append("required artifacts failed: " + ", ".join(failed_required_artifacts))
    if summary.status == "success" and failed_required_artifacts:
        errors.append("successful case contains failed required artifacts")
    if summary.status == "success" and not summary.metrics:
        errors.append("successful case has empty metrics")
    if summary.status == "success":
        if summary.case_group in OFFICIAL_CASE_GROUPS:
            errors.extend(_validate_official_summary(summary))
    if summary.status in {"failure", "partial"} and not summary.failure_reason:
        errors.append(f"{summary.status} case has empty failure_reason")
    return errors


def _validate_official_summary(summary: RunSummary) -> list[str]:
    errors: list[str] = []
    for field_name in ("source_commit", "parameter_profile", "stop_after", "fractional_solver_backend", "result_scope"):
        if not summary.input.get(field_name):
            errors.append(f"official summary input missing {field_name}")
    if not summary.dependencies.get("official_dependency_versions"):
        errors.append("official summary dependencies missing official_dependency_versions")
    if not summary.third_party_usage:
        errors.append("official summary missing third_party_usage")
    for usage in summary.third_party_usage:
        if not usage.get("commit_or_version"):
            errors.append("official third_party_usage missing commit_or_version")
    result_scope = summary.input.get("result_scope", {})
    if isinstance(result_scope, dict) and result_scope.get("is_full_algorithm_run"):
        if "cycle_count_before_connection" not in summary.metrics:
            errors.append("official full run missing cycle_count_before_connection")
        if summary.metrics.get("connected_tour_feasible") is not True:
            errors.append("official full run missing connected_tour_feasible=true")
        for metric_name in (
            "tour_waypoint_count",
            "tour_length_m",
            "tour_feasible_area_coverage_ratio",
            "tour_valuable_area_value_coverage_ratio",
            "tour_missed_value",
        ):
            if metric_name not in summary.metrics:
                errors.append(f"official full run missing {metric_name}")
    if summary.input.get("fractional_solver_backend") == "highs" and summary.stage_status.get("fractional") == "success":
        for metric_name in (
            "non_official_solver_replacement",
            "fractional_objective_value",
            "highs_variable_count",
            "highs_constraint_count",
            "highs_status",
        ):
            if metric_name not in summary.metrics:
                errors.append(f"official highs run missing {metric_name}")
    if summary.input.get("parameter_profile") == "maptools_existing_preprocessing":
        adapter_metadata = summary.input.get("adapter_metadata")
        if not isinstance(adapter_metadata, dict):
            errors.append("maptools official run missing input.adapter_metadata")
        else:
            if adapter_metadata.get("adapter") != "maptools_existing_preprocessing_to_official_polygon_instance":
                errors.append("maptools official run has unexpected adapter")
            if "geometry_preparation" not in str(adapter_metadata.get("adapter_scope", "")):
                errors.append("maptools official run adapter_scope does not mention geometry_preparation")
        for field_name in ("maptools_project", "area_id", "instance_source"):
            if field_name not in summary.input:
                errors.append(f"maptools official run input missing {field_name}")
    return errors


def write_summary(run_dir: str | Path, summary: RunSummary) -> Path:
    contract_errors = validate_summary_contract(summary)
    if contract_errors and summary.status == "success":
        raise ValueError("summary contract violation: " + "; ".join(contract_errors))
    target = Path(run_dir) / "summary.json"
    write_json(target, summary.to_dict())
    return target


def validate_root_summary_contract(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("summary_contract_version") != ROOT_SUMMARY_CONTRACT_VERSION:
        errors.append("root summary has unknown summary_contract_version")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        errors.append("root summary cases must be a list")
        return errors
    try:
        case_count = int(payload.get("case_count"))
    except (TypeError, ValueError):
        errors.append("root summary case_count is not an integer")
        case_count = -1
    try:
        success_count = int(payload.get("success_count"))
    except (TypeError, ValueError):
        errors.append("root summary success_count is not an integer")
        success_count = -1
    if case_count != len(cases):
        errors.append("root summary case_count does not match cases length")
    actual_success_count = sum(1 for item in cases if isinstance(item, dict) and item.get("status") == "success")
    if success_count != actual_success_count:
        errors.append("root summary success_count does not match cases")
    if not payload.get("case_group"):
        errors.append("root summary case_group is empty")
    if not payload.get("runner"):
        errors.append("root summary runner is empty")
    return errors


def write_root_summary(run_dir: str | Path, payload: dict[str, Any]) -> Path:
    root_payload = {
        "summary_contract_version": ROOT_SUMMARY_CONTRACT_VERSION,
        **payload,
    }
    contract_errors = validate_root_summary_contract(root_payload)
    if contract_errors:
        raise ValueError("root summary contract violation: " + "; ".join(contract_errors))
    target = Path(run_dir) / "summary.json"
    write_json(target, root_payload)
    return target
