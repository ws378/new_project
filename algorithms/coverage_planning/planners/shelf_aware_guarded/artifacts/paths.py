"""覆盖规划产物路径集合。

集中管理输出目录与文件名，writer 与其它模块通过 dataclass 字段消费，
避免散落字符串路径导致维护口径漂移。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PlannerArtifactPaths:
  """planner 覆盖产物文件路径集合。

  用途：为 writer 与 manifest 提供单一来源的产物路径，避免不同阶段重复拼接文件名。
  输入：`output_dir` 目录。
  输出：固定字段名的可消费路径集合。

  约束：
  - 字段名表示语义，不承载运行时状态。
  - 路径一律是确定性文件名，便于复盘和外部对账。
  """

  output_dir: Path
  rotated_map: Path
  nodes_debug: Path
  path_overlay: Path
  region_mask: Path
  region_overlay: Path
  local_direction_debug: Path
  region_json: Path
  path_pixels_raw: Path
  path_pixels_baseline_before_semantics: Path
  path_pixels: Path
  path_segments_pixels: Path
  path_jump_segments_pixels: Path
  path_world: Path
  metadata: Path
  fallback_debug_trace: Path
  candidate_decision_debug: Path
  path_generation_provenance: Path
  final_segment_provenance: Path
  pipeline_trace: Path
  artifact_manifest: Path
  node_debug_enriched: Path
  node_semantics: Path
  semantic_global_path: Path
  isolated_jump_cleanup: Path
  node_obstacle_ratio_filter_debug: Path
  energy_debug: Path
  # 每个字段都是 artifact 的固定输出目标文件。

  @classmethod
  def from_output_dir(cls, output_dir: Path) -> "PlannerArtifactPaths":
    """基于 output_dir 生成全量产物路径。

    固定文件名是兼容约束；上游不得在这里拼接文件名，避免出现同名分裂。
    """
    return cls(
      output_dir=output_dir,
      rotated_map=output_dir / "rotated_room_map.png",
      nodes_debug=output_dir / "nodes_debug.png",
      path_overlay=output_dir / "path_overlay.png",
      region_mask=output_dir / "region_mask.png",
      region_overlay=output_dir / "region_overlay.png",
      local_direction_debug=output_dir / "local_direction_debug.png",
      region_json=output_dir / "region.json",
      path_pixels_raw=output_dir / "path_pixels_raw.json",
      path_pixels_baseline_before_semantics=output_dir / "path_pixels_baseline_before_semantics.json",
      path_pixels=output_dir / "path_pixels.json",
      path_segments_pixels=output_dir / "path_segments_pixels.json",
      path_jump_segments_pixels=output_dir / "path_jump_segments_pixels.json",
      path_world=output_dir / "path_world.json",
      metadata=output_dir / "metadata.json",
      fallback_debug_trace=output_dir / "fallback_debug_trace.json",
      candidate_decision_debug=output_dir / "candidate_decision_debug.json",
      path_generation_provenance=output_dir / "path_generation_provenance.json",
      final_segment_provenance=output_dir / "final_segment_provenance.json",
      pipeline_trace=output_dir / "pipeline_trace.json",
      artifact_manifest=output_dir / "artifact_manifest.json",
      node_debug_enriched=output_dir / "node_debug_enriched.json",
      node_semantics=output_dir / "node_semantics.json",
      semantic_global_path=output_dir / "semantic_global_path.json",
      isolated_jump_cleanup=output_dir / "isolated_jump_cleanup.json",
      node_obstacle_ratio_filter_debug=output_dir / "node_obstacle_ratio_filter_debug.png",
      energy_debug=output_dir / "energy_debug.csv",
    )
