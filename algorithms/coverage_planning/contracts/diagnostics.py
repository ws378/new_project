from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any

from .applicability import ApplicabilityMetrics
from .config import CoveragePlannerConfig, coverage_planner_config_to_dict


KEY_ARTIFACT_DETAIL_ROWS: tuple[tuple[str, str], ...] = (
    ("artifact_manifest", "产物清单"),
    ("path_overlay", "路径总览图"),
    ("nodes_debug", "覆盖节点图"),
    ("path_pixels", "最终像素路径"),
    ("path_world", "最终世界坐标路径"),
    ("path_generation_provenance", "路径生成溯源"),
    ("final_segment_provenance", "最终线段溯源"),
    ("candidate_decision_debug", "候选决策调试"),
    ("pipeline_trace", "阶段流水记录"),
)


def _mapping(payload: Any) -> dict[str, Any]:
    return dict(payload) if isinstance(payload, Mapping) else {}


def build_compact_diagnostics_summary(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build a small UI/export summary from the stable diagnostics payload.

    The compact summary is a readability layer only. It must not replace the full
    diagnostics payload and must not reinterpret unavailable geometry diagnostics
    as a pass.
    """

    data = dict(payload or {})
    runtime = _mapping(data.get("runtime"))
    profile = _mapping(data.get("profile"))
    mode_default_overrides = _mapping(data.get("mode_default_overrides"))
    override_diff = _mapping(data.get("override_diff"))
    quality = _mapping(runtime.get("path_quality_summary"))
    geometry = _mapping(runtime.get("geometry_risk_summary"))
    geometry_count_metrics = _mapping(geometry.get("count_metrics"))
    geometry_ratio_metrics = _mapping(geometry.get("ratio_metrics"))
    provenance = _mapping(runtime.get("provenance_summary"))
    artifact_manifest = _mapping(provenance.get("artifact_manifest"))
    artifact_paths = _mapping(artifact_manifest.get("artifact_paths"))
    path_generation = _mapping(provenance.get("path_generation_provenance"))
    final_segment = _mapping(provenance.get("final_segment_provenance"))
    candidate_debug = _mapping(provenance.get("candidate_decision_debug"))

    quality_available = bool(quality.get("available", False))
    geometry_available = bool(geometry.get("available", False))
    return {
        "selected_planner": str(data.get("selected_planner", "") or ""),
        "scene_type": str(data.get("scene_type", "") or ""),
        "profile_id": str(profile.get("profile_id", "") or ""),
        "profile_version": int(profile.get("profile_version", 0) or 0),
        "profile_status": str(profile.get("profile_status", "") or ""),
        "profile_version_policy": str(profile.get("profile_version_policy", "") or ""),
        "mode_default_override_count": int(len(mode_default_overrides)),
        "mode_default_override_fields": [str(key) for key in sorted(mode_default_overrides)],
        "override_diff_count": int(len(override_diff)),
        "override_diff_fields": [str(key) for key in sorted(override_diff)],
        "path_quality": {
            "available": quality_available,
            "status": str(quality.get("status", "") or ("pass" if quality.get("passed") else "unavailable")),
            "coverage_ratio": quality.get("coverage_ratio"),
            "long_jump_count": quality.get("long_jump_count"),
            "infeasible_segment_count": quality.get("infeasible_segment_count"),
        },
        "geometry_risk": {
            "available": geometry_available,
            "status": str(geometry.get("status", "") or ("available" if geometry_available else "not_run")),
            "reason": str(geometry.get("reason", "") or ""),
            "body_swept_collision_count": geometry_count_metrics.get("body_swept_collision_count"),
            "turn_swept_collision_count": geometry_count_metrics.get("turn_swept_collision_count"),
            "cleaning_footprint_coverage_ratio": geometry_ratio_metrics.get("cleaning_footprint_coverage_ratio"),
            "summary_path": str(geometry.get("summary_path", "") or ""),
        },
        "provenance": {
            "available": bool(provenance.get("available", False)),
            "artifact_manifest_available": bool(artifact_manifest.get("available", False)),
            "artifact_manifest_path": str(artifact_manifest.get("path", "") or ""),
            "artifact_paths": {
                str(name): {
                    "path": str(_mapping(info).get("path", "") or ""),
                    "role": str(_mapping(info).get("role", "") or ""),
                    "schema_or_format": str(_mapping(info).get("schema_or_format", "") or ""),
                }
                for name, info in sorted(artifact_paths.items())
                if str(_mapping(info).get("path", "") or "")
            },
            "path_generation_available": bool(path_generation.get("available", False)),
            "final_segment_available": bool(final_segment.get("available", False)),
            "candidate_decision_available": bool(candidate_debug.get("available", False)),
            "move_trace_count": int(path_generation.get("move_trace_count", 0) or 0),
            "global_fallback_count": int(path_generation.get("global_fallback_count", 0) or 0),
            "revisit_bridge_count": int(path_generation.get("revisit_bridge_count", 0) or 0),
        },
    }


def _display_token(value: Any) -> str:
    return str(value or "").replace("_", " ").strip()


def _ratio_text(value: Any, digits: int = 3) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return ""


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return int(default)


def _add_readable_item(items: list[dict[str, Any]], key: str, label: str, value: str, **extra: Any) -> None:
    text = str(value or "").strip()
    if not text:
        return
    item = {
        "key": key,
        "label": label,
        "value": text,
    }
    item.update(extra)
    items.append(item)


def _value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (list, tuple)):
        return ", ".join(_value_text(item) for item in value)
    if isinstance(value, Mapping):
        parts = [f"{key}={_value_text(item)}" for key, item in sorted(value.items())]
        return "{%s}" % ", ".join(parts)
    return str(value)


def _add_detail_row(rows: list[dict[str, Any]], key: str, label: str, value: Any, **extra: Any) -> None:
    text = _value_text(value).strip()
    if not text:
        return
    row = {
        "key": key,
        "label": label,
        "value": text,
    }
    row.update(extra)
    rows.append(row)


def _append_section(sections: list[dict[str, Any]], key: str, label: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    sections.append(
        {
            "key": key,
            "label": label,
            "rows": rows,
        }
    )


def _build_readable_detail_sections(payload: Mapping[str, Any], compact: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build table-like UI/export details without changing planning decisions."""

    data = dict(payload or {})
    runtime = _mapping(data.get("runtime"))
    coverage_meta = _mapping(runtime.get("coverage_meta"))
    profile = _mapping(data.get("profile"))
    mode_default_overrides = _mapping(data.get("mode_default_overrides"))
    override_diff = _mapping(data.get("override_diff"))
    quality = _mapping(runtime.get("path_quality_summary"))
    geometry_raw = _mapping(runtime.get("geometry_risk_summary"))
    geometry = _mapping(compact.get("geometry_risk"))
    provenance_raw = _mapping(runtime.get("provenance_summary"))
    provenance = _mapping(compact.get("provenance"))
    ctg_auxiliary = _mapping(coverage_meta.get("shelf_ctg_auxiliary"))

    sections: list[dict[str, Any]] = []

    profile_rows: list[dict[str, Any]] = []
    _add_detail_row(profile_rows, "selected_planner", "规划器", data.get("selected_planner"))
    _add_detail_row(profile_rows, "scene_type", "场景类型", data.get("scene_type"))
    _add_detail_row(profile_rows, "artifacts_dir", "产物目录", data.get("artifacts_dir"))
    _add_detail_row(profile_rows, "planner_mode", "Profile 模式", profile.get("planner_mode"))
    _add_detail_row(profile_rows, "profile_id", "Profile ID", profile.get("profile_id") or compact.get("profile_id"))
    _add_detail_row(
        profile_rows,
        "profile_version",
        "Profile 版本",
        profile.get("profile_version") or compact.get("profile_version"),
    )
    _add_detail_row(profile_rows, "profile_status", "Profile 状态", profile.get("profile_status"))
    _add_detail_row(profile_rows, "profile_version_policy", "Profile 版本策略", profile.get("profile_version_policy"))
    _append_section(sections, "profile", "策略配置", profile_rows)

    default_rows: list[dict[str, Any]] = []
    for key in sorted(mode_default_overrides):
        _add_detail_row(default_rows, str(key), str(key), mode_default_overrides.get(key))
    _append_section(sections, "mode_default_overrides", "模式固定覆盖", default_rows)

    diff_rows: list[dict[str, Any]] = []
    for key in sorted(override_diff):
        diff = _mapping(override_diff.get(key))
        requested = diff.get("requested")
        applied = diff.get("applied")
        value = f"{_value_text(requested)} -> {_value_text(applied)}"
        _add_detail_row(
            diff_rows,
            str(key),
            str(key),
            value,
            requested=_value_text(requested),
            applied=_value_text(applied),
        )
    _append_section(sections, "override_diff", "请求/生效差异", diff_rows)

    ctg_rows: list[dict[str, Any]] = []
    if ctg_auxiliary:
        _add_detail_row(ctg_rows, "enabled", "CTG 辅助是否生效", ctg_auxiliary.get("enabled"))
        _add_detail_row(ctg_rows, "reason", "CTG 辅助状态原因", ctg_auxiliary.get("reason"))
        _add_detail_row(ctg_rows, "error_message", "CTG 辅助错误信息", ctg_auxiliary.get("error_message"))
    _append_section(sections, "ctg_auxiliary", "CTG 辅助", ctg_rows)

    quality_rows: list[dict[str, Any]] = []
    path_quality = _mapping(compact.get("path_quality"))
    if bool(path_quality.get("available", False)) or bool(quality.get("available", False)):
        _add_detail_row(quality_rows, "status", "质量状态", path_quality.get("status") or quality.get("status"))
        _add_detail_row(quality_rows, "passed", "是否通过", quality.get("passed"))
        _add_detail_row(
            quality_rows,
            "coverage_ratio",
            "覆盖率",
            path_quality.get("coverage_ratio", quality.get("coverage_ratio")),
        )
        _add_detail_row(
            quality_rows,
            "long_jump_count",
            "长跳跃数量",
            path_quality.get("long_jump_count", quality.get("long_jump_count")),
        )
        _add_detail_row(
            quality_rows,
            "infeasible_segment_count",
            "不可行线段数量",
            path_quality.get("infeasible_segment_count", quality.get("infeasible_segment_count")),
        )
    _append_section(sections, "path_quality", "路径质量", quality_rows)

    geometry_rows: list[dict[str, Any]] = []
    geometry_available = bool(geometry.get("available", False) or geometry_raw.get("available", False))
    _add_detail_row(geometry_rows, "available", "几何诊断是否可用", geometry_available)
    _add_detail_row(
        geometry_rows,
        "policy",
        "规划约束关系",
        "只读诊断，不作为正式规划硬约束",
    )
    _add_detail_row(geometry_rows, "status", "几何诊断状态", geometry.get("status") or geometry_raw.get("status"))
    _add_detail_row(geometry_rows, "reason", "状态原因", geometry.get("reason") or geometry_raw.get("reason"))
    _add_detail_row(
        geometry_rows,
        "body_swept_collision_count",
        "车体扫掠碰撞数量",
        geometry.get("body_swept_collision_count"),
    )
    _add_detail_row(
        geometry_rows,
        "turn_swept_collision_count",
        "转弯 yaw 扫掠碰撞数量",
        geometry.get("turn_swept_collision_count"),
    )
    _add_detail_row(
        geometry_rows,
        "cleaning_footprint_coverage_ratio",
        "真实清扫 footprint 覆盖率",
        geometry.get("cleaning_footprint_coverage_ratio"),
    )
    _add_detail_row(geometry_rows, "summary_path", "几何诊断摘要路径", geometry.get("summary_path"))
    _append_section(sections, "geometry_risk", "几何风险", geometry_rows)

    provenance_rows: list[dict[str, Any]] = []
    _add_detail_row(
        provenance_rows,
        "available",
        "路径溯源是否可用",
        provenance.get("available", provenance_raw.get("available")),
    )
    _add_detail_row(
        provenance_rows,
        "artifact_manifest_available",
        "产物清单是否可用",
        provenance.get("artifact_manifest_available"),
    )
    _add_detail_row(
        provenance_rows,
        "path_generation_available",
        "路径生成溯源是否可用",
        provenance.get("path_generation_available"),
    )
    _add_detail_row(
        provenance_rows,
        "final_segment_available",
        "最终线段溯源是否可用",
        provenance.get("final_segment_available"),
    )
    _add_detail_row(
        provenance_rows,
        "candidate_decision_available",
        "候选决策调试是否可用",
        provenance.get("candidate_decision_available"),
    )
    _add_detail_row(provenance_rows, "move_trace_count", "移动记录数量", provenance.get("move_trace_count"))
    _add_detail_row(provenance_rows, "global_fallback_count", "全局 fallback 数量", provenance.get("global_fallback_count"))
    _add_detail_row(provenance_rows, "revisit_bridge_count", "重复访问桥接数量", provenance.get("revisit_bridge_count"))
    _append_section(sections, "provenance", "路径溯源", provenance_rows)

    artifact_rows: list[dict[str, Any]] = []
    artifact_paths = _mapping(provenance.get("artifact_paths"))
    manifest_path = str(provenance.get("artifact_manifest_path", "") or "").strip()
    if manifest_path:
        _add_detail_row(
            artifact_rows,
            "artifact_manifest",
            "产物清单",
            manifest_path,
            artifact_name="artifact_manifest",
            artifact_kind="json",
            role="artifact_manifest",
        )
    for artifact_name, label in KEY_ARTIFACT_DETAIL_ROWS:
        if artifact_name == "artifact_manifest":
            continue
        info = _mapping(artifact_paths.get(artifact_name))
        path_text = str(info.get("path", "") or "").strip()
        if not path_text:
            continue
        _add_detail_row(
            artifact_rows,
            artifact_name,
            label,
            path_text,
            artifact_name=artifact_name,
            artifact_kind=str(info.get("schema_or_format", "") or ""),
            role=str(info.get("role", "") or ""),
        )
    _append_section(sections, "artifact_paths", "关键产物路径", artifact_rows)

    return sections


def build_readable_diagnostics_summary(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build a shared human-readable diagnostics layer for UI and export.

    This layer is derived from the full diagnostics payload. It is not a
    decision source and must not hide the raw `runtime`, `profile`, or config
    fields used for debugging and regression.
    """

    data = dict(payload or {})
    compact = _mapping(data.get("compact_summary"))
    if not compact:
        compact = build_compact_diagnostics_summary(data)
    runtime = _mapping(data.get("runtime"))
    quality = _mapping(runtime.get("path_quality_summary"))
    provenance = _mapping(compact.get("provenance"))
    geometry = _mapping(compact.get("geometry_risk"))
    items: list[dict[str, Any]] = []

    planner = _display_token(compact.get("selected_planner") or data.get("selected_planner"))
    _add_readable_item(items, "selected_planner", "规划器", planner)

    scene_type = _display_token(compact.get("scene_type") or data.get("scene_type"))
    _add_readable_item(items, "scene_type", "场景类型", scene_type)

    reasons = [_display_token(item) for item in data.get("reasons", ()) or () if _display_token(item)]
    if reasons:
        _add_readable_item(items, "reasons", "原因", "; ".join(reasons[:2]), values=reasons)

    warnings = [_display_token(item) for item in data.get("warnings", ()) or () if _display_token(item)]
    if warnings:
        _add_readable_item(items, "warnings", "警告", "; ".join(warnings[:1]), values=warnings)

    profile_id = _display_token(compact.get("profile_id"))
    if profile_id:
        profile_version = _int_value(compact.get("profile_version"))
        value = profile_id
        if profile_version:
            value = f"{value} v{profile_version}"
        _add_readable_item(items, "profile", "策略配置", value)

    mode_default_fields = [str(field) for field in compact.get("mode_default_override_fields", ()) or ()]
    if mode_default_fields:
        _add_readable_item(
            items,
            "mode_defaults",
            "模式固定覆盖",
            f"{len(mode_default_fields)} 项",
            fields=mode_default_fields,
        )

    override_diff_fields = [str(field) for field in compact.get("override_diff_fields", ()) or ()]
    if override_diff_fields:
        _add_readable_item(
            items,
            "applied_overrides",
            "实际生效覆盖",
            f"{len(override_diff_fields)} 项",
            fields=override_diff_fields,
        )

    path_quality = _mapping(compact.get("path_quality"))
    if bool(path_quality.get("available", False)) or bool(quality.get("available", False)):
        status = _display_token(path_quality.get("status") or quality.get("status"))
        quality_parts = [status or "available"]
        coverage_ratio = _ratio_text(path_quality.get("coverage_ratio", quality.get("coverage_ratio")))
        if coverage_ratio:
            quality_parts.append(f"覆盖率={coverage_ratio}")
        long_jump_count = path_quality.get("long_jump_count", quality.get("long_jump_count"))
        if long_jump_count is not None:
            quality_parts.append(f"长跳跃={_int_value(long_jump_count)}")
        infeasible_count = path_quality.get("infeasible_segment_count", quality.get("infeasible_segment_count"))
        if infeasible_count is not None:
            quality_parts.append(f"不可行段={_int_value(infeasible_count)}")
        _add_readable_item(items, "path_quality", "路径质量", " ".join(quality_parts))

    if bool(geometry.get("available", False)):
        geometry_parts = ["只读诊断"]
        body_collision = geometry.get("body_swept_collision_count")
        if body_collision is not None:
            geometry_parts.append(f"车体碰撞={_int_value(body_collision)}")
        turn_collision = geometry.get("turn_swept_collision_count")
        if turn_collision is not None:
            geometry_parts.append(f"转弯碰撞={_int_value(turn_collision)}")
        cleaning_ratio = _ratio_text(geometry.get("cleaning_footprint_coverage_ratio"))
        if cleaning_ratio:
            geometry_parts.append(f"清扫覆盖={cleaning_ratio}")
        _add_readable_item(
            items,
            "geometry_risk",
            "几何风险",
            " ".join(geometry_parts),
            summary_path=str(geometry.get("summary_path", "") or ""),
        )
    else:
        reason = _display_token(geometry.get("reason") or geometry.get("status") or "not_run")
        _add_readable_item(items, "geometry_risk", "几何风险", f"未作为硬约束运行：{reason}")

    if (
        bool(provenance.get("available", False))
        or bool(provenance.get("path_generation_available", False))
        or bool(provenance.get("artifact_manifest_available", False))
    ):
        provenance_parts = []
        move_count = _int_value(provenance.get("move_trace_count"))
        if move_count:
            provenance_parts.append(f"移动={move_count}")
        provenance_parts.append(f"fallback={_int_value(provenance.get('global_fallback_count'))}")
        provenance_parts.append(f"revisit={_int_value(provenance.get('revisit_bridge_count'))}")
        if bool(provenance.get("artifact_manifest_available", False)):
            provenance_parts.append("产物清单=有")
        _add_readable_item(items, "provenance", "路径溯源", " ".join(provenance_parts))

    status_line = " | ".join(f"{item['label']}={item['value']}" for item in items)
    return {
        "version": "coverage_planning_diagnostics_readable.v1",
        "items": items,
        "detail_sections": _build_readable_detail_sections(data, compact),
        "status_line": status_line,
    }


@dataclass(frozen=True)
class CoveragePlanningPipelineMeta:
    """Stable pipeline-level runtime metadata exposed by planner adapters."""

    pipeline_name: str = ""
    source: str = ""
    map_yaml_path: str = ""

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> "CoveragePlanningPipelineMeta":
        data = dict(payload or {})
        return cls(
            pipeline_name=str(data.get("pipeline_name", "")),
            source=str(data.get("source", "")),
            map_yaml_path=str(data.get("map_yaml_path", "")),
        )

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "pipeline_name": str(self.pipeline_name or ""),
            "source": str(self.source or ""),
            "map_yaml_path": str(self.map_yaml_path or ""),
        }


@dataclass(frozen=True)
class CoveragePlanningFinalPathSummary:
    """Stable final-path aggregate summary returned by heavy planners like CTG."""

    route_count: int = 0
    path_point_count: int = 0

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> "CoveragePlanningFinalPathSummary":
        data = dict(payload or {})
        return cls(
            route_count=int(data.get("route_count", 0) or 0),
            path_point_count=int(data.get("path_point_count", 0) or 0),
        )

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "route_count": int(self.route_count),
            "path_point_count": int(self.path_point_count),
        }


@dataclass(frozen=True)
class CoveragePlanningFinalPathValidation:
    """Stable final-path validation outcome exposed by heavy planners like CTG."""

    is_valid: bool = True

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> "CoveragePlanningFinalPathValidation":
        data = dict(payload or {})
        return cls(is_valid=bool(data.get("is_valid", True)))

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "is_valid": bool(self.is_valid),
        }


@dataclass(frozen=True)
class CoveragePlanningRuntimeDetails:
    """Typed runtime evidence shared by reports, export, and planner diagnostics."""

    pipeline_meta: CoveragePlanningPipelineMeta = field(default_factory=CoveragePlanningPipelineMeta)
    coverage_meta: dict[str, Any] = field(default_factory=dict)
    runtime_adjustments: dict[str, Any] = field(default_factory=dict)
    postprocess_stage_summary: dict[str, Any] = field(default_factory=dict)
    path_quality_summary: dict[str, Any] = field(default_factory=dict)
    provenance_summary: dict[str, Any] = field(default_factory=dict)
    geometry_risk_summary: dict[str, Any] = field(default_factory=dict)
    final_path_summary: CoveragePlanningFinalPathSummary = field(default_factory=CoveragePlanningFinalPathSummary)
    final_path_validation: CoveragePlanningFinalPathValidation = field(default_factory=CoveragePlanningFinalPathValidation)

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "pipeline_meta": self.pipeline_meta.to_summary_dict(),
            "coverage_meta": dict(self.coverage_meta or {}),
            "runtime_adjustments": dict(self.runtime_adjustments or {}),
            "postprocess_stage_summary": dict(self.postprocess_stage_summary or {}),
            "path_quality_summary": dict(self.path_quality_summary or {}),
            "provenance_summary": dict(self.provenance_summary or {}),
            "geometry_risk_summary": dict(self.geometry_risk_summary or {}),
            "final_path_summary": self.final_path_summary.to_summary_dict(),
            "final_path_validation": self.final_path_validation.to_summary_dict(),
        }


@dataclass(frozen=True)
class CoveragePlanningDiagnostics:
    """Structured diagnostics returned by routing and planner adapters."""

    selected_planner: str = ""
    scene_type: str = ""
    fallback_chain: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    metrics: ApplicabilityMetrics = field(default_factory=ApplicabilityMetrics)
    artifacts_dir: str = ""
    requested_public_config: CoveragePlannerConfig | None = None
    applied_public_config: CoveragePlannerConfig | None = None
    profile: dict[str, Any] = field(default_factory=dict)
    mode_default_overrides: dict[str, Any] = field(default_factory=dict)
    override_diff: dict[str, Any] = field(default_factory=dict)
    runtime: CoveragePlanningRuntimeDetails = field(default_factory=CoveragePlanningRuntimeDetails)

    def to_summary_dict(self) -> dict[str, Any]:
        """Return a stable diagnostics payload for GUI, reports, and export artifacts."""

        summary = {
            "selected_planner": str(self.selected_planner or ""),
            "scene_type": str(self.scene_type or ""),
            "fallback_chain": [str(item) for item in tuple(self.fallback_chain or ())],
            "reasons": [str(item) for item in tuple(self.reasons or ())],
            "warnings": [str(item) for item in tuple(self.warnings or ())],
            "metrics": {
                "skeleton_pixel_count": int(self.metrics.skeleton_pixel_count),
                "free_area_pixel_count": int(self.metrics.free_area_pixel_count),
                "skeleton_to_free_area_ratio": float(self.metrics.skeleton_to_free_area_ratio),
                "width_variation_score": float(self.metrics.width_variation_score),
                "junction_candidate_count": int(self.metrics.junction_candidate_count),
                "open_space_score": float(self.metrics.open_space_score),
                "mixed_scene_score": float(self.metrics.mixed_scene_score),
            },
            "artifacts_dir": str(self.artifacts_dir or ""),
            "runtime": self.runtime.to_summary_dict(),
        }
        if self.applied_public_config is not None:
            summary["applied_public_config"] = coverage_planner_config_to_dict(self.applied_public_config)
        if self.requested_public_config is not None:
            summary["requested_public_config"] = coverage_planner_config_to_dict(self.requested_public_config)
        if self.profile:
            summary["profile"] = dict(self.profile)
        if self.mode_default_overrides:
            summary["mode_default_overrides"] = dict(self.mode_default_overrides)
        if self.override_diff:
            summary["override_diff"] = dict(self.override_diff)
        summary["compact_summary"] = build_compact_diagnostics_summary(summary)
        summary["readable_summary"] = build_readable_diagnostics_summary(summary)
        return summary

    def to_compact_summary_dict(self) -> dict[str, Any]:
        """Return the shared compact summary used by UI and export readability."""

        return build_compact_diagnostics_summary(self.to_summary_dict())

    def to_readable_summary_dict(self) -> dict[str, Any]:
        """Return the shared human-readable summary used by UI and export."""

        return build_readable_diagnostics_summary(self.to_summary_dict())
