from algorithms.coverage_planning.contracts import (
    build_readable_diagnostics_summary,
    CoveragePlanningDiagnostics,
    CoveragePlanningRuntimeDetails,
)


def test_readable_diagnostics_summary_is_derived_from_compact_and_runtime_payload():
    diagnostics = CoveragePlanningDiagnostics(
        selected_planner="shelf_aware_turn_cost",
        scene_type="explicit",
        profile={
            "planner_mode": "shelf_aware_turn_cost",
            "profile_id": "shelf_aware_turn_cost_repaired_grid_0_28",
            "profile_version": 2,
        },
        mode_default_overrides={
            "shelf_node_generation_mode": "turn_cost_repaired_grid",
            "shelf_repaired_grid_max_offset_factor": 0.28,
        },
        override_diff={
            "shelf_node_generation_mode": {
                "requested": "shelf_cell_adjusted",
                "applied": "turn_cost_repaired_grid",
            }
        },
        runtime=CoveragePlanningRuntimeDetails(
            coverage_meta={
                "shelf_ctg_auxiliary": {
                    "enabled": False,
                    "reason": "auxiliary_failed_continued_without_ctg",
                    "error_message": "edge 6 path too short",
                }
            },
            path_quality_summary={
                "available": True,
                "status": "pass",
                "coverage_ratio": 0.99851,
                "long_jump_count": 0,
                "infeasible_segment_count": 0,
            },
            provenance_summary={
                "available": True,
                "artifact_manifest": {"available": True},
                "path_generation_provenance": {
                    "available": True,
                    "move_trace_count": 42,
                    "global_fallback_count": 1,
                    "revisit_bridge_count": 2,
                },
            },
            geometry_risk_summary={
                "available": True,
                "status": "read_only_diagnostic_available",
                "summary_path": "/tmp/geometry/summary.json",
                "count_metrics": {
                    "body_swept_collision_count": 3,
                    "turn_swept_collision_count": 5,
                },
                "ratio_metrics": {
                    "cleaning_footprint_coverage_ratio": 0.9874,
                },
            },
        ),
    )

    summary = diagnostics.to_summary_dict()

    readable = summary["readable_summary"]
    assert readable["version"] == "coverage_planning_diagnostics_readable.v1"
    assert readable["status_line"].startswith("规划器=shelf aware turn cost")
    assert "策略配置=shelf aware turn cost repaired grid 0 28 v2" in readable["status_line"]
    assert "路径质量=pass 覆盖率=0.999 长跳跃=0 不可行段=0" in readable["status_line"]
    assert "几何风险=只读诊断 车体碰撞=3 转弯碰撞=5 清扫覆盖=0.987" in readable["status_line"]
    assert "路径溯源=移动=42 fallback=1 revisit=2 产物清单=有" in readable["status_line"]
    assert any(item["key"] == "mode_defaults" and item["fields"] for item in readable["items"])
    assert any(item["key"] == "applied_overrides" and item["fields"] for item in readable["items"])

    sections = {section["key"]: section for section in readable["detail_sections"]}
    assert sections["profile"]["label"] == "策略配置"
    profile_rows = {row["key"]: row for row in sections["profile"]["rows"]}
    assert profile_rows["profile_id"]["value"] == "shelf_aware_turn_cost_repaired_grid_0_28"
    assert profile_rows["profile_version"]["value"] == "2"

    default_rows = {row["key"]: row for row in sections["mode_default_overrides"]["rows"]}
    assert default_rows["shelf_node_generation_mode"]["value"] == "turn_cost_repaired_grid"
    assert default_rows["shelf_repaired_grid_max_offset_factor"]["value"] == "0.28"

    diff_rows = {row["key"]: row for row in sections["override_diff"]["rows"]}
    assert diff_rows["shelf_node_generation_mode"]["requested"] == "shelf_cell_adjusted"
    assert diff_rows["shelf_node_generation_mode"]["applied"] == "turn_cost_repaired_grid"
    assert diff_rows["shelf_node_generation_mode"]["value"] == "shelf_cell_adjusted -> turn_cost_repaired_grid"

    ctg_rows = {row["key"]: row for row in sections["ctg_auxiliary"]["rows"]}
    assert ctg_rows["enabled"]["value"] == "false"
    assert ctg_rows["reason"]["value"] == "auxiliary_failed_continued_without_ctg"
    assert ctg_rows["error_message"]["value"] == "edge 6 path too short"

    geometry_rows = {row["key"]: row for row in sections["geometry_risk"]["rows"]}
    assert geometry_rows["policy"]["value"] == "只读诊断，不作为正式规划硬约束"
    assert geometry_rows["body_swept_collision_count"]["value"] == "3"
    assert geometry_rows["turn_swept_collision_count"]["value"] == "5"
    assert geometry_rows["summary_path"]["value"] == "/tmp/geometry/summary.json"

    provenance_rows = {row["key"]: row for row in sections["provenance"]["rows"]}
    assert provenance_rows["artifact_manifest_available"]["value"] == "true"
    assert provenance_rows["path_generation_available"]["value"] == "true"
    assert provenance_rows["move_trace_count"]["value"] == "42"


def test_readable_diagnostics_summary_keeps_unavailable_geometry_explicit():
    payload = {
        "selected_planner": "shelf_aware_turn_cost",
        "scene_type": "explicit",
        "runtime": {
            "geometry_risk_summary": {
                "available": False,
                "status": "not_run",
                "reason": "readonly_geometry_diagnostic_not_run_in_formal_planner",
            }
        },
    }

    readable = build_readable_diagnostics_summary(payload)

    assert "几何风险=未作为硬约束运行：readonly geometry diagnostic not run in formal planner" in readable["status_line"]
    sections = {section["key"]: section for section in readable["detail_sections"]}
    geometry_rows = {row["key"]: row for row in sections["geometry_risk"]["rows"]}
    assert geometry_rows["available"]["value"] == "false"
    assert geometry_rows["policy"]["value"] == "只读诊断，不作为正式规划硬约束"
    assert geometry_rows["reason"]["value"] == "readonly_geometry_diagnostic_not_run_in_formal_planner"


def test_readable_diagnostics_summary_keeps_ctg_auxiliary_enabled_state():
    payload = {
        "selected_planner": "shelf_aware_turn_cost",
        "scene_type": "explicit",
        "runtime": {
            "coverage_meta": {
                "shelf_ctg_auxiliary": {
                    "enabled": True,
                    "reason": "auxiliary_maps_available",
                }
            }
        },
    }

    readable = build_readable_diagnostics_summary(payload)

    sections = {section["key"]: section for section in readable["detail_sections"]}
    ctg_rows = {row["key"]: row for row in sections["ctg_auxiliary"]["rows"]}
    assert ctg_rows["enabled"]["value"] == "true"
    assert ctg_rows["reason"]["value"] == "auxiliary_maps_available"
    assert "error_message" not in ctg_rows
