"""Project-local persistence for coverage planner dialog parameters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ..views.coverage_dialog import coverage_dialog_config_from_values, merge_coverage_dialog_values

COVERAGE_PLANNER_PARAMS_SCHEMA_VERSION = 1
COVERAGE_PLANNER_PARAMS_FILENAME = "coverage_planner_params.json"


def coverage_planner_params_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / COVERAGE_PLANNER_PARAMS_FILENAME


def normalize_coverage_planner_params_payload(payload: Mapping[str, Any]) -> dict[str, object]:
    """Return validated dialog values from a persisted params payload."""

    schema_version = int(payload.get("schema_version", 0))
    if schema_version != COVERAGE_PLANNER_PARAMS_SCHEMA_VERSION:
        raise ValueError(f"unsupported coverage planner params schema_version={schema_version}")
    values = payload.get("coverage_dialog_values")
    if not isinstance(values, dict):
        raise ValueError("coverage_dialog_values must be an object")
    merged = merge_coverage_dialog_values(values)
    coverage_dialog_config_from_values(merged)
    return merged


def build_coverage_planner_params_payload(values: Mapping[str, object]) -> dict[str, object]:
    merged = merge_coverage_dialog_values(dict(values))
    coverage_dialog_config_from_values(merged)
    return {
        "schema_version": COVERAGE_PLANNER_PARAMS_SCHEMA_VERSION,
        "coverage_dialog_values": merged,
    }


def save_coverage_planner_params(project_dir: str | Path, values: Mapping[str, object]) -> Path:
    path = coverage_planner_params_path(project_dir)
    payload = build_coverage_planner_params_payload(values)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_coverage_planner_params(project_dir: str | Path) -> dict[str, object] | None:
    path = coverage_planner_params_path(project_dir)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("coverage planner params payload must be an object")
    return normalize_coverage_planner_params_payload(payload)
