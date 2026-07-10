from __future__ import annotations

import numpy as np

from algorithms.coverage_planning.planners.shelf_aware_guarded.artifacts.provenance_payloads import (
    FINAL_SEGMENT_EVIDENCE_LEVEL_FINAL_SEGMENT_SIDECAR,
    FINAL_SEGMENT_EVIDENCE_LEVEL_MATCHED_TRAVERSAL_EDGE,
    FINAL_SEGMENT_EVIDENCE_LEVEL_VALUES,
    FINAL_SEGMENT_SOURCE_MOVE_TRACE_ARTIFACT,
    FINAL_SEGMENT_SOURCE_PATH_ARTIFACT,
    FINAL_SEGMENT_SOURCE_POLICY_VALUES,
    FINAL_SEGMENT_SOURCE_POLICY_FINAL_PATH_GEOMETRY,
    FINAL_SEGMENT_SOURCE_POLICY_TRAVERSAL_MOVE_TRACE,
    final_segment_provenance_payload,
)


class _NoopJumpCleanupResult:
    def to_summary_dict(self, _resolution_m_per_px: float) -> dict[str, object]:
        return {"enabled": False}


def test_final_segment_provenance_registry_is_stable_and_unique() -> None:
    assert FINAL_SEGMENT_SOURCE_POLICY_VALUES == (
        "traversal_move_trace",
        "final_path_geometry",
    )
    assert len(FINAL_SEGMENT_SOURCE_POLICY_VALUES) == len(set(FINAL_SEGMENT_SOURCE_POLICY_VALUES))
    assert FINAL_SEGMENT_EVIDENCE_LEVEL_VALUES == (
        "matched_traversal_edge",
        "final_segment_sidecar",
    )
    assert len(FINAL_SEGMENT_EVIDENCE_LEVEL_VALUES) == len(set(FINAL_SEGMENT_EVIDENCE_LEVEL_VALUES))
    assert FINAL_SEGMENT_SOURCE_PATH_ARTIFACT == "path_pixels.json"
    assert FINAL_SEGMENT_SOURCE_MOVE_TRACE_ARTIFACT == "path_generation_provenance.json"


def test_final_segment_provenance_matches_representative_move_sources() -> None:
    pixel_points = [
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 10.0),
        (30.0, 10.0),
        (40.0, 20.0),
    ]
    pixel_poses = [(x, y, 0.0) for x, y in pixel_points]
    traversal_move_trace = [
        {
            "move_id": "move_000001",
            "path_index": 1,
            "move_source": "start",
            "edge_role": "start",
            "from_node_id": None,
            "to_node_id": "r0_c0",
            "from_point_rotated_px": None,
            "to_point_rotated_px": [0.0, 0.0],
            "selected_energy": 0.0,
            "distance_px": 0.0,
            "heading_rad": None,
            "turn_angle_deg": None,
            "phase_candidate_count": None,
            "phase_energy_evaluated_candidate_count": None,
            "phase_accepted_candidate_count": None,
            "phase_rejected_before_energy_count": None,
            "phase_candidate_rank": None,
        },
        {
            "move_id": "move_000002",
            "path_index": 2,
            "move_source": "normal_neighbor",
            "edge_role": "coverage_lane",
            "from_node_id": "r0_c0",
            "to_node_id": "r0_c1",
            "from_point_rotated_px": [0.0, 0.0],
            "to_point_rotated_px": [10.0, 0.0],
            "selected_energy": 1.0,
            "distance_px": 10.0,
            "heading_rad": 0.0,
            "turn_angle_deg": 0.0,
            "phase_candidate_count": 2,
            "phase_energy_evaluated_candidate_count": 2,
            "phase_accepted_candidate_count": 2,
            "phase_rejected_before_energy_count": 0,
            "phase_candidate_rank": 1,
        },
        {
            "move_id": "move_000003",
            "path_index": 3,
            "move_source": "revisit_bridge",
            "edge_role": "revisit_bridge",
            "from_node_id": "r0_c1",
            "to_node_id": "r1_c1",
            "from_point_rotated_px": [10.0, 0.0],
            "to_point_rotated_px": [10.0, 10.0],
            "selected_energy": 2.0,
            "distance_px": 10.0,
            "heading_rad": 1.5707963267948966,
            "turn_angle_deg": 90.0,
            "phase_candidate_count": 3,
            "phase_energy_evaluated_candidate_count": 2,
            "phase_accepted_candidate_count": 1,
            "phase_rejected_before_energy_count": 1,
            "phase_candidate_rank": 1,
        },
        {
            "move_id": "move_000004",
            "path_index": 4,
            "move_source": "global_fallback",
            "edge_role": "fallback_transfer",
            "from_node_id": "r1_c1",
            "to_node_id": "r1_c3",
            "from_point_rotated_px": [10.0, 10.0],
            "to_point_rotated_px": [30.0, 10.0],
            "selected_energy": 3.0,
            "distance_px": 20.0,
            "heading_rad": 0.0,
            "turn_angle_deg": 90.0,
            "phase_candidate_count": 4,
            "phase_energy_evaluated_candidate_count": 4,
            "phase_accepted_candidate_count": 2,
            "phase_rejected_before_energy_count": 0,
            "phase_candidate_rank": 1,
        },
    ]

    payload = final_segment_provenance_payload(
        pixel_points=pixel_points,
        pixel_poses=pixel_poses,
        traversal_move_trace=traversal_move_trace,
        inverse_rotation=np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32),
        map_resolution=0.05,
        semantic_path_payload=None,
        jump_cleanup_result=_NoopJumpCleanupResult(),
    )

    assert payload["source_summary"]["matched_traversal_segment_count"] == 3
    assert payload["source_summary"]["derived_final_geometry_segment_count"] == 1
    assert payload["source_path_artifact"] == FINAL_SEGMENT_SOURCE_PATH_ARTIFACT
    assert payload["source_move_trace_artifact"] == FINAL_SEGMENT_SOURCE_MOVE_TRACE_ARTIFACT
    assert payload["source_summary"]["move_source_counts"] == {
        "derived_final_path": 1,
        "global_fallback": 1,
        "normal_neighbor": 1,
        "revisit_bridge": 1,
    }
    assert payload["source_summary"]["edge_role_counts"] == {
        "coverage_lane": 1,
        "derived_final_segment": 1,
        "fallback_transfer": 1,
        "revisit_bridge": 1,
    }

    assert payload["items"][0]["generation_move"]["move_id"] == "move_000002"
    assert payload["items"][0]["source_policy"] == FINAL_SEGMENT_SOURCE_POLICY_TRAVERSAL_MOVE_TRACE
    assert payload["items"][0]["evidence_level"] == FINAL_SEGMENT_EVIDENCE_LEVEL_MATCHED_TRAVERSAL_EDGE
    assert payload["items"][0]["generation_move"]["move_source"] == "normal_neighbor"
    assert payload["items"][0]["generation_move"]["phase_candidate_count"] == 2
    assert payload["items"][1]["generation_move"]["move_id"] == "move_000003"
    assert payload["items"][1]["generation_move"]["edge_role"] == "revisit_bridge"
    assert payload["items"][1]["generation_move"]["phase_accepted_candidate_count"] == 1
    assert payload["items"][2]["generation_move"]["move_id"] == "move_000004"
    assert payload["items"][2]["generation_move"]["edge_role"] == "fallback_transfer"
    assert payload["items"][2]["generation_move"]["phase_energy_evaluated_candidate_count"] == 4
    assert payload["items"][3]["generation_move"] is None
    assert payload["items"][3]["source_policy"] == FINAL_SEGMENT_SOURCE_POLICY_FINAL_PATH_GEOMETRY
    assert payload["items"][3]["evidence_level"] == FINAL_SEGMENT_EVIDENCE_LEVEL_FINAL_SEGMENT_SIDECAR
    assert payload["items"][3]["move_source"] == "derived_final_path"
    assert payload["items"][3]["edge_role"] == "derived_final_segment"
