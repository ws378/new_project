import json

from algorithms.turn_cost_coverage_research.scripts.experiments.run_shelf_path_batch_candidate_reconnect import (
    TaggedPoint,
    _load_source_segment_by_original_index,
    _select_candidates,
    _source_segment_by_original_index,
    _write_batch_generation_provenance,
)
from algorithms.turn_cost_coverage_research.scripts.diagnostics.run_shelf_path_turn_cost_diagnostics import (
    _load_generation_provenance,
)


def test_batch_reconnect_writes_preserved_and_inserted_segment_provenance(tmp_path) -> None:
    summary = {
        "generation_segment_mapping": {
            "loaded": True,
            "segment_items": [
                {
                    "segment_index": 1,
                    "mapped": True,
                    "distance_px": 0.5,
                    "raw_path_index": 2,
                    "move_source": "normal_neighbor",
                    "edge_role": "coverage_lane",
                },
                {
                    "segment_index": 2,
                    "mapped": True,
                    "distance_px": 0.8,
                    "raw_path_index": 3,
                    "move_source": "global_fallback",
                    "edge_role": "fallback_transfer",
                },
            ],
        }
    }
    current = [
        TaggedPoint(point=(0.0, 0.0), original_index=0),
        TaggedPoint(
            point=(10.0, 0.0),
            original_index=1,
            reconnect_candidate_rank=4,
            reconnect_window_start_original_index=1,
            reconnect_window_end_original_index=2,
        ),
        TaggedPoint(
            point=(15.0, 5.0),
            original_index=None,
            reconnect_candidate_rank=4,
            reconnect_window_start_original_index=1,
            reconnect_window_end_original_index=2,
        ),
        TaggedPoint(
            point=(20.0, 0.0),
            original_index=2,
            reconnect_candidate_rank=4,
            reconnect_window_start_original_index=1,
            reconnect_window_end_original_index=2,
        ),
    ]
    out_path = tmp_path / "path_generation_provenance.json"

    output_summary = _write_batch_generation_provenance(
        path=out_path,
        current=current,
        source_by_original_segment=_source_segment_by_original_index(summary),
        source_diagnostics_run_dir=tmp_path / "diagnostics",
    )

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert output_summary["move_source_counts"]["normal_neighbor"] == 1
    assert output_summary["move_source_counts"]["turn_aware_reconnect"] == 2
    assert payload["items"][0]["source_kind"] == "preserved_original_segment"
    assert payload["items"][0]["edge_role"] == "coverage_lane"
    assert payload["items"][1]["source_kind"] == "inserted_bridge_segment"
    assert payload["items"][1]["edge_role"] == "local_reconnect_bridge"
    assert payload["items"][1]["reconnect_candidate_rank"] == 4
    assert payload["items"][1]["reconnect_window_start_original_index"] == 1
    assert payload["items"][1]["reconnect_window_end_original_index"] == 2
    assert payload["items"][2]["from_original_index"] is None


def test_diagnostics_prefers_derived_path_generation_provenance(tmp_path) -> None:
    input_run_dir = tmp_path / "raw"
    input_run_dir.mkdir()
    derived_dir = tmp_path / "derived"
    derived_dir.mkdir()
    (input_run_dir / "path_generation_provenance.json").write_text(
        json.dumps({"version": "raw", "items": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    derived_path = derived_dir / "batch_candidate_reconnect_path_pixels.json"
    derived_path.write_text("[]", encoding="utf-8")
    (derived_dir / "path_generation_provenance.json").write_text(
        json.dumps({"version": "derived", "items": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    payload = _load_generation_provenance(input_run_dir, path_pixels_path=derived_path)

    assert payload is not None
    assert payload["version"] == "derived"
    assert payload["_loaded_from"] == str(derived_dir / "path_generation_provenance.json")


def test_batch_reconnect_loads_full_segment_mapping_artifact(tmp_path) -> None:
    diagnostics_dir = tmp_path / "diagnostics"
    diagnostics_dir.mkdir()
    artifact = diagnostics_dir / "generation_segment_mapping.json"
    artifact.write_text(
        json.dumps(
            {
                "loaded": True,
                "segment_items": [
                    {
                        "segment_index": 3,
                        "mapped": True,
                        "move_source": "revisit_bridge",
                        "edge_role": "revisit_bridge",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    summary = {
        "generation_segment_mapping": {
            "loaded": True,
            "mapped_segment_count": 1,
        },
        "artifacts": {
            "generation_segment_mapping": str(artifact),
        },
    }

    mapping = _load_source_segment_by_original_index(diagnostics_dir, summary)

    assert mapping[3]["move_source"] == "revisit_bridge"


def test_batch_reconnect_source_policy_skips_lane_only_candidates() -> None:
    payload = {
        "top_candidates": [
            {
                "candidate_id": 1,
                "candidate_kind": "lane_uniformity_local_fix",
                "segment_type": "coverage_core",
                "metrics": {
                    "infeasible_segment_count": 0,
                    "high_risk_crossing_count": 0,
                },
                "generation_source": {
                    "high_risk_transfer_count": 0,
                },
            },
            {
                "candidate_id": 2,
                "candidate_kind": "fallback_reconnect",
                "segment_type": "fragment",
                "metrics": {
                    "infeasible_segment_count": 0,
                    "high_risk_crossing_count": 1,
                },
                "generation_source": {
                    "high_risk_transfer_count": 1,
                },
            },
        ]
    }

    selected, selection = _select_candidates(
        payload,
        source="top",
        source_policy="provenance_safe",
        action_labels=None,
        max_candidates=30,
    )

    assert [candidate["candidate_id"] for candidate in selected] == [2]
    assert selection["raw_candidate_count"] == 2
    assert selection["source_policy_candidate_count"] == 1
    assert selection["selected_candidate_kinds"] == {"fallback_reconnect": 1}
