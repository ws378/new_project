"""产物 schema 与角色注册表。

通过固定 registry 管理 name、文件名、角色和 schema，避免 manifest 与实际产物脱钩。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


ARTIFACT_MANIFEST_SCHEMA_VERSION = "shelf_aware_guarded_artifact_manifest.v1"
ARTIFACT_MANIFEST_RESULT_CONTRACT = "CoveragePlanningResult"
ARTIFACT_ROLE_NOTE = "Artifacts are evidence; CoveragePlanningResult remains the formal output truth."

TRAVERSAL_MOVE_TRACE_VERSION = "shelf_aware_guarded_traversal_move_trace_v2"
FINAL_SEGMENT_PROVENANCE_VERSION = "shelf_aware_guarded_final_segment_provenance_v2"
CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION = "candidate_decision_debug.v2"
FINAL_PATH_TRANSFORM_RECORDS_SCHEMA_VERSION = "final_path_transform_records_v1"


@dataclass(frozen=True)
class ArtifactSchemaSpec:
  """单个产物的注册条目定义。

  该 dataclass 只表示“谁在写”与“写了什么”，不承载产物运行时内容。
  """
  artifact_name: str
  filename: str
  role: str
  schema_or_format: str
  # 注册表条目：每个产物的身份、角色和格式。


ARTIFACT_SCHEMA_REGISTRY: Mapping[str, ArtifactSchemaSpec] = {
  "rotated_room_map": ArtifactSchemaSpec(
    artifact_name="rotated_room_map",
    filename="rotated_room_map.png",
    role="rotated_map_visual_evidence",
    schema_or_format="png",
  ),
  "nodes_debug": ArtifactSchemaSpec(
    artifact_name="nodes_debug",
    filename="nodes_debug.png",
    role="coverage_graph_visual_evidence",
    schema_or_format="png",
  ),
  "path_overlay": ArtifactSchemaSpec(
    artifact_name="path_overlay",
    filename="path_overlay.png",
    role="path_visual_evidence",
    schema_or_format="png",
  ),
  "region_mask": ArtifactSchemaSpec(
    artifact_name="region_mask",
    filename="region_mask.png",
    role="region_mask_visual_evidence",
    schema_or_format="png",
  ),
  "region_overlay": ArtifactSchemaSpec(
    artifact_name="region_overlay",
    filename="region_overlay.png",
    role="region_overlay_visual_evidence",
    schema_or_format="png",
  ),
  "local_direction_debug": ArtifactSchemaSpec(
    artifact_name="local_direction_debug",
    filename="local_direction_debug.png",
    role="local_direction_visual_evidence",
    schema_or_format="png",
  ),
  "region": ArtifactSchemaSpec(
    artifact_name="region",
    filename="region.json",
    role="region_input_snapshot",
    schema_or_format="region_json_v1",
  ),
  "path_pixels_raw": ArtifactSchemaSpec(
    artifact_name="path_pixels_raw",
    filename="path_pixels_raw.json",
    role="raw_traversal_pixel_path_evidence",
    schema_or_format="path_pixels_raw_v1",
  ),
  "path_pixels_baseline_before_semantics": ArtifactSchemaSpec(
    artifact_name="path_pixels_baseline_before_semantics",
    filename="path_pixels_baseline_before_semantics.json",
    role="pre_semantic_final_path_pixel_evidence",
    schema_or_format="path_pixels_baseline_v1",
  ),
  "path_pixels": ArtifactSchemaSpec(
    artifact_name="path_pixels",
    filename="path_pixels.json",
    role="final_path_pixels_evidence",
    schema_or_format="path_pixels_v1",
  ),
  "path_segments_pixels": ArtifactSchemaSpec(
    artifact_name="path_segments_pixels",
    filename="path_segments_pixels.json",
    role="final_path_segment_pixel_evidence",
    schema_or_format="path_segments_pixels_v1",
  ),
  "path_jump_segments_pixels": ArtifactSchemaSpec(
    artifact_name="path_jump_segments_pixels",
    filename="path_jump_segments_pixels.json",
    role="jump_segment_pixel_evidence",
    schema_or_format="path_jump_segments_pixels_v1",
  ),
  "path_world": ArtifactSchemaSpec(
    artifact_name="path_world",
    filename="path_world.json",
    role="final_path_world_evidence",
    schema_or_format="path_world_v1",
  ),
  "metadata": ArtifactSchemaSpec(
    artifact_name="metadata",
    filename="metadata.json",
    role="compat_summary",
    schema_or_format="metadata_compat_v1",
  ),
  "fallback_debug_trace": ArtifactSchemaSpec(
    artifact_name="fallback_debug_trace",
    filename="fallback_debug_trace.json",
    role="legacy_fallback_debug_evidence",
    schema_or_format="fallback_debug_trace_v1",
  ),
  "candidate_decision_debug": ArtifactSchemaSpec(
    artifact_name="candidate_decision_debug",
    filename="candidate_decision_debug.json",
    role="artifact_only_candidate_decision_evidence",
    schema_or_format=CANDIDATE_DECISION_DEBUG_SCHEMA_VERSION,
  ),
  "path_generation_provenance": ArtifactSchemaSpec(
    artifact_name="path_generation_provenance",
    filename="path_generation_provenance.json",
    role="raw_traversal_move_trace",
    schema_or_format=TRAVERSAL_MOVE_TRACE_VERSION,
  ),
  "final_segment_provenance": ArtifactSchemaSpec(
    artifact_name="final_segment_provenance",
    filename="final_segment_provenance.json",
    role="final_path_segment_source_evidence",
    schema_or_format=FINAL_SEGMENT_PROVENANCE_VERSION,
  ),
  "pipeline_trace": ArtifactSchemaSpec(
    artifact_name="pipeline_trace",
    filename="pipeline_trace.json",
    role="pipeline_evidence",
    schema_or_format="pipeline_trace_v1",
  ),
  "node_debug_enriched": ArtifactSchemaSpec(
    artifact_name="node_debug_enriched",
    filename="node_debug_enriched.json",
    role="coverage_graph_node_debug_evidence",
    schema_or_format="node_debug_enriched_v1",
  ),
  "node_semantics": ArtifactSchemaSpec(
    artifact_name="node_semantics",
    filename="node_semantics.json",
    role="semantic_node_evidence",
    schema_or_format="node_semantics_v1",
  ),
  "semantic_global_path": ArtifactSchemaSpec(
    artifact_name="semantic_global_path",
    filename="semantic_global_path.json",
    role="semantic_path_evidence",
    schema_or_format="semantic_global_path_v1",
  ),
  "isolated_jump_cleanup": ArtifactSchemaSpec(
    artifact_name="isolated_jump_cleanup",
    filename="isolated_jump_cleanup.json",
    role="isolated_jump_cleanup_evidence",
    schema_or_format="isolated_jump_cleanup_v1",
  ),
  "node_obstacle_ratio_filter_debug": ArtifactSchemaSpec(
    artifact_name="node_obstacle_ratio_filter_debug",
    filename="node_obstacle_ratio_filter_debug.png",
    role="node_obstacle_ratio_filter_visual_evidence",
    schema_or_format="png",
  ),
  "energy_debug": ArtifactSchemaSpec(
    artifact_name="energy_debug",
    filename="energy_debug.csv",
    role="legacy_energy_debug_table",
    schema_or_format="csv",
  ),
  "final_path_transform_records": ArtifactSchemaSpec(
    artifact_name="final_path_transform_records",
    filename="metadata.json",
    role="final_path_transform_manifest_embedded_in_metadata",
    schema_or_format=FINAL_PATH_TRANSFORM_RECORDS_SCHEMA_VERSION,
  ),
}


def artifact_schema_spec(artifact_name: str) -> ArtifactSchemaSpec:
  """按产物名查询 registry 条目。

  失败时抛 KeyError 是为了在 manifest 生成早期即暴露拼写/版本漂移问题。
  """
  try:
    return ARTIFACT_SCHEMA_REGISTRY[artifact_name]
  except KeyError as exc:
    raise KeyError(f"unknown shelf-aware artifact schema: {artifact_name}") from exc
