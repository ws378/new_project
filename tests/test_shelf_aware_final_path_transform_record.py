from __future__ import annotations

from algorithms.coverage_planning.planners.shelf_aware_guarded.final_path.transform_record import (
    FINAL_PATH_PROVENANCE_POLICIES,
    FINAL_PATH_PROVENANCE_POLICY_PIPELINE_TRACE,
    FINAL_PATH_PROVENANCE_POLICY_SEMANTIC_PATH_ARTIFACT,
    FINAL_PATH_TRANSFORM_NAMES,
    FINAL_PATH_TRANSFORM_SEMANTIC_GLOBAL_PATH,
    FINAL_PATH_TRANSFORM_SIMPLIFY_ROTATED_PATH,
    FINAL_PATH_TRANSFORM_TYPE_LIGHTWEIGHT_SAFETY_GUARD,
    FINAL_PATH_TRANSFORM_TYPE_SEMANTIC_PATH_EXPRESSION,
    FINAL_PATH_TRANSFORM_TYPES,
    FinalPathTransformRecord,
    build_final_path_transform_record,
    final_path_transform_records_payload,
)


def test_final_path_transform_registry_is_stable_and_unique() -> None:
    assert FINAL_PATH_TRANSFORM_NAMES == (
        "simplify_rotated_path",
        "semantic_global_path",
        "isolated_jump_cleanup",
        "final_path_geometry",
    )
    assert len(FINAL_PATH_TRANSFORM_NAMES) == len(set(FINAL_PATH_TRANSFORM_NAMES))
    assert FINAL_PATH_TRANSFORM_TYPES == (
        "lightweight_safety_guard",
        "semantic_path_expression",
        "geometric_formatting",
    )
    assert len(FINAL_PATH_TRANSFORM_TYPES) == len(set(FINAL_PATH_TRANSFORM_TYPES))
    assert FINAL_PATH_PROVENANCE_POLICIES == (
        "pipeline_trace",
        "semantic_path_artifact",
        "isolated_jump_cleanup_artifact",
        "path_pixels_and_segments",
    )
    assert len(FINAL_PATH_PROVENANCE_POLICIES) == len(set(FINAL_PATH_PROVENANCE_POLICIES))


def test_final_path_transform_record_payload_preserves_existing_schema() -> None:
    payload = FinalPathTransformRecord(
        name=FINAL_PATH_TRANSFORM_SIMPLIFY_ROTATED_PATH,
        transform_type=FINAL_PATH_TRANSFORM_TYPE_LIGHTWEIGHT_SAFETY_GUARD,
        enabled=True,
        input_point_count=10,
        output_point_count=7,
        changes_path_points=True,
        allowed_in_formal=True,
        provenance_policy=FINAL_PATH_PROVENANCE_POLICY_PIPELINE_TRACE,
    ).to_payload()

    assert payload == {
        "name": "simplify_rotated_path",
        "transform_type": "lightweight_safety_guard",
        "enabled": True,
        "allowed_in_formal": True,
        "input_point_count": 10,
        "output_point_count": 7,
        "point_count_delta": -3,
        "added_point_count": 0,
        "removed_point_count": 3,
        "changes_path_points": True,
        "provenance_policy": "pipeline_trace",
    }


def test_build_final_path_transform_record_reports_added_points() -> None:
    record = build_final_path_transform_record(
        name=FINAL_PATH_TRANSFORM_SEMANTIC_GLOBAL_PATH,
        transform_type=FINAL_PATH_TRANSFORM_TYPE_SEMANTIC_PATH_EXPRESSION,
        enabled=True,
        input_point_count=4,
        output_point_count=6,
        changes_path_points=True,
        allowed_in_formal=False,
        provenance_policy=FINAL_PATH_PROVENANCE_POLICY_SEMANTIC_PATH_ARTIFACT,
    )
    payload = record.to_payload()

    assert payload["point_count_delta"] == 2
    assert payload["added_point_count"] == 2
    assert payload["removed_point_count"] == 0
    assert payload["allowed_in_formal"] is False
    assert payload["provenance_policy"] == FINAL_PATH_PROVENANCE_POLICY_SEMANTIC_PATH_ARTIFACT


def test_final_path_transform_records_payload_is_artifact_boundary() -> None:
    record = FinalPathTransformRecord(
        name=FINAL_PATH_TRANSFORM_SIMPLIFY_ROTATED_PATH,
        transform_type=FINAL_PATH_TRANSFORM_TYPE_LIGHTWEIGHT_SAFETY_GUARD,
        enabled=False,
        input_point_count=3,
        output_point_count=3,
        changes_path_points=False,
    )

    assert final_path_transform_records_payload((record,)) == [record.to_payload()]
