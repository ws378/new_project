"""产物清单构建与落盘入口。

该模块生成 artifact manifest 的条目与整体 payload。
每个产物在清单中都保留 role 与 schema 信息，未生成产物会显式标记缺失原因。
清单只用于索引和复核，不承载路径语义真值。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .paths import PlannerArtifactPaths
from .schema_registry import (
  ARTIFACT_MANIFEST_RESULT_CONTRACT,
  ARTIFACT_MANIFEST_SCHEMA_VERSION,
  ARTIFACT_ROLE_NOTE,
  artifact_schema_spec,
)


def artifact_manifest_entry(
  path: Path,
  *,
  role: str,
  schema_or_format: str,
  available: bool = True,
  optional_reason: str = "",
) -> dict[str, Any]:
  """构造单个 manifest 条目。

  Args:
    path: 产物完整路径。
    role: 该产物在复核链路中的职责角色。
    schema_or_format: 产物约定的 schema 或文件格式。
    available: False 时仍保留条目以便消费者知道缺失原因。
    optional_reason: 可选的不可用原因，用于静态诊断和人工比对。
  """
  return {
    "path": str(path),
    "role": str(role),
    "schema_or_format": str(schema_or_format),
    "available": bool(available),
    "optional_reason": str(optional_reason),
  }


def artifact_manifest_payload(artifacts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
  """构造 manifest 主体 payload。

  返回结构保留固定字段，便于下游用 schema_version 进行兼容校验。
  """
  return {
    "schema_version": ARTIFACT_MANIFEST_SCHEMA_VERSION,
    "result_contract": ARTIFACT_MANIFEST_RESULT_CONTRACT,
    "artifact_role_note": ARTIFACT_ROLE_NOTE,
    "artifacts": {str(name): dict(entry) for name, entry in artifacts.items()},
  }


def write_artifact_manifest(path: Path, artifacts: Mapping[str, Mapping[str, Any]]) -> None:
  """将 manifest 写入 json 文件。

  统一缩进和编码，降低人工 diff 噪声，保证文本层可重复比对。
  """
  with path.open("w", encoding="utf-8") as handle:
    json.dump(artifact_manifest_payload(artifacts), handle, ensure_ascii=True, indent=2)


def _registry_entry(
  artifact_name: str,
  path: Path,
  *,
  available: bool = True,
  optional_reason: str = "",
) -> dict[str, Any]:
  """按 registry 名称查找 schema 元信息并生成 manifest 条目。"""
  spec = artifact_schema_spec(artifact_name)
  return artifact_manifest_entry(
    path,
    role=spec.role,
    schema_or_format=spec.schema_or_format,
    available=available,
    optional_reason=optional_reason,
  )


def planner_artifact_manifest_entries(
  *,
  paths: PlannerArtifactPaths,
  region_mask_available: bool,
  node_obstacle_ratio_filter_enabled: bool,
  debug_csv_enabled: bool,
  node_semantics_available: bool,
  semantic_path_available: bool,
) -> dict[str, dict[str, Any]]:
  """构造 planner 输出产物清单条目，按阶段开关标注可用性。

  Args:
    paths: 运行时产物路径集合。
    region_mask_available: 区域掩码相关产物是否有效。
    node_obstacle_ratio_filter_enabled: 障碍占比过滤是否启用。
    debug_csv_enabled: 调试 CSV 是否开启。
    node_semantics_available: 节点语义增强是否可用。
    semantic_path_available: 语义路径输出是否可用。

  Returns:
    Dict[str, dict[str, Any]]: 可被 manifest payload 直接消费的条目字典。

  Notes:
    使用开关控制可用性，避免将“文件不存在”误解释为“逻辑不可达”；
    对缺失项保留说明，便于归档系统与人工复核同时识别原因。
  """
  return {
    "rotated_room_map": _registry_entry("rotated_room_map", paths.rotated_map),
    "nodes_debug": _registry_entry("nodes_debug", paths.nodes_debug),
    "path_overlay": _registry_entry("path_overlay", paths.path_overlay),
    "region_mask": _registry_entry(
      "region_mask",
      paths.region_mask,
      available=region_mask_available,
      optional_reason="" if region_mask_available else "region_mask_not_provided",
    ),
    "region_overlay": _registry_entry(
      "region_overlay",
      paths.region_overlay,
      available=region_mask_available,
      optional_reason="" if region_mask_available else "region_mask_not_provided",
    ),
    "local_direction_debug": _registry_entry("local_direction_debug", paths.local_direction_debug),
    "region": _registry_entry(
      "region",
      paths.region_json,
      available=region_mask_available,
      optional_reason="" if region_mask_available else "region_mask_not_provided",
    ),
    "path_pixels_raw": _registry_entry("path_pixels_raw", paths.path_pixels_raw),
    "path_pixels_baseline_before_semantics": _registry_entry(
      "path_pixels_baseline_before_semantics",
      paths.path_pixels_baseline_before_semantics,
    ),
    "path_pixels": _registry_entry("path_pixels", paths.path_pixels),
    "path_segments_pixels": _registry_entry("path_segments_pixels", paths.path_segments_pixels),
    "path_jump_segments_pixels": _registry_entry(
      "path_jump_segments_pixels",
      paths.path_jump_segments_pixels,
    ),
    "path_world": _registry_entry("path_world", paths.path_world),
    "metadata": _registry_entry("metadata", paths.metadata),
    "fallback_debug_trace": _registry_entry("fallback_debug_trace", paths.fallback_debug_trace),
    "candidate_decision_debug": _registry_entry(
      "candidate_decision_debug",
      paths.candidate_decision_debug,
    ),
    "path_generation_provenance": _registry_entry(
      "path_generation_provenance",
      paths.path_generation_provenance,
    ),
    "final_segment_provenance": _registry_entry(
      "final_segment_provenance",
      paths.final_segment_provenance,
    ),
    "pipeline_trace": _registry_entry("pipeline_trace", paths.pipeline_trace),
    "node_debug_enriched": _registry_entry("node_debug_enriched", paths.node_debug_enriched),
    "node_semantics": _registry_entry(
      "node_semantics",
      paths.node_semantics,
      available=node_semantics_available,
      optional_reason="" if node_semantics_available else "semantic_path_disabled_or_unavailable",
    ),
    "semantic_global_path": _registry_entry(
      "semantic_global_path",
      paths.semantic_global_path,
      available=semantic_path_available,
      optional_reason="" if semantic_path_available else "semantic_path_disabled_or_unavailable",
    ),
    "isolated_jump_cleanup": _registry_entry("isolated_jump_cleanup", paths.isolated_jump_cleanup),
    "node_obstacle_ratio_filter_debug": _registry_entry(
      "node_obstacle_ratio_filter_debug",
      paths.node_obstacle_ratio_filter_debug,
      available=node_obstacle_ratio_filter_enabled,
      optional_reason="" if node_obstacle_ratio_filter_enabled else "node_obstacle_ratio_filter_disabled",
    ),
    "energy_debug": _registry_entry(
      "energy_debug",
      paths.energy_debug,
      available=debug_csv_enabled,
      optional_reason="" if debug_csv_enabled else "debug_csv_disabled",
    ),
    "final_path_transform_records": _registry_entry("final_path_transform_records", paths.metadata),
  }
