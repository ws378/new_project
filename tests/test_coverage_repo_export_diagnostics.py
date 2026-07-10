import json

import numpy as np
import pytest
import yaml

from algorithms.coverage_planning.contracts import (
    CoveragePlanningDiagnostics,
    CoveragePlanningRuntimeDetails,
    CoveragePlanningResult,
    CoveragePlanningStatus,
    CoveragePose2D,
)
from maptools.adapters.coverage_planning_adapter import CoveragePlannerConfig
from maptools.models.coverage_path import CoveragePathManager, CoveragePathNode
from maptools.utils import coverage_repo_export as export_mod


class _MetaStub:
    resolution = 0.05
    origin = (0.0, 0.0, 0.0)


class _MapDataStub:
    width = 20
    height = 20
    yaml_path = "/tmp/demo_map.yaml"
    metadata = _MetaStub()

    def get_display_image(self):
        return np.full((self.height, self.width), 255, dtype=np.uint8)


class _AreaStub:
    def __init__(self, area_id: int, polygon):
        self.area_id = area_id
        self.name = str(area_id)
        self.polygon = polygon


class _AnnotationsStub:
    def __init__(self):
        self.area_labels = [
            _AreaStub(
                area_id=1,
                polygon=((0.1, 0.1), (0.7, 0.1), (0.7, 0.7), (0.1, 0.7)),
            )
        ]
        self.forbidden_zones = []
        self.pass_only_zones = []


class _OverlapAnnotationsStub:
    def __init__(self):
        self.area_labels = [
            _AreaStub(area_id=1, polygon=((0.1, 0.1), (0.8, 0.1), (0.8, 0.8), (0.1, 0.8))),
            _AreaStub(area_id=2, polygon=((0.5, 0.5), (1.0, 0.5), (1.0, 1.0), (0.5, 1.0))),
        ]
        self.forbidden_zones = []
        self.pass_only_zones = []


class _MultiAnnotationsStub:
    def __init__(self):
        self.area_labels = [
            _AreaStub(area_id=2, polygon=((0.1, 0.1), (0.7, 0.1), (0.7, 0.7), (0.1, 0.7))),
            _AreaStub(area_id=3, polygon=((1.1, 0.1), (1.7, 0.1), (1.7, 0.7), (1.1, 0.7))),
            _AreaStub(area_id=4, polygon=((2.1, 0.1), (2.7, 0.1), (2.7, 0.7), (2.1, 0.7))),
            _AreaStub(area_id=5, polygon=((3.1, 0.1), (3.7, 0.1), (3.7, 0.7), (3.1, 0.7))),
        ]
        self.forbidden_zones = []
        self.pass_only_zones = []


class _NodeStub:
    def __init__(self, node_id: int, segment: int, x: float, y: float, yaw: float):
        self.id = node_id
        self.segment = segment
        self.x = x
        self.y = y
        self.yaw = yaw


def _build_success_result(*, selected_planner: str, scene_type: str, reasons, warnings=()):
    return CoveragePlanningResult(
        status=CoveragePlanningStatus.SUCCESS,
        path=(
            CoveragePose2D(x=0.2, y=0.2, theta=0.0),
            CoveragePose2D(x=0.6, y=0.2, theta=0.0),
        ),
        diagnostics=CoveragePlanningDiagnostics(
            selected_planner=selected_planner,
            scene_type=scene_type,
            reasons=tuple(reasons),
            warnings=tuple(warnings),
            artifacts_dir="/tmp/artifacts",
        ),
    )


def _assert_exported_paths_are_runtime_policy_free(coverage_yaml):
    for path in coverage_yaml["paths"]:
        assert "skip_navigate_to_start" not in path
        assert "skip_smoothing" not in path
        assert "segment_policy" not in path
        for segment in path.get("segments", []):
            assert segment["type"] == "source_chunk"


def test_preflight_reports_area_overlap_as_blocker(tmp_path):
    result = export_mod.run_export_preflight(
        map_data=_MapDataStub(),
        annotations=_OverlapAnnotationsStub(),
        output_root=str(tmp_path),
        map_id="demo_map",
    )

    assert result.ok is False
    assert any("area_overlap" in issue for issue in result.issues)
    assert result.warnings == []


def test_preflight_reports_path_consistency_without_modifying_paths(tmp_path):
    manager = CoveragePathManager()
    manager.nodes = [
        CoveragePathNode(
            id=0,
            room=1,
            segment=0,
            x=2.0,
            y=2.0,
            yaw=0.0,
            u=40.0,
            v=-20.0,
            acc_dist=0.0,
            room_dist=0.0,
            seg_dist=0.0,
        )
    ]

    result = export_mod.run_export_preflight(
        map_data=_MapDataStub(),
        annotations=_AnnotationsStub(),
        output_root=str(tmp_path),
        map_id="demo_map",
        path_manager=manager,
    )

    assert result.ok is True
    assert any("path_point_out_of_map" in warning for warning in result.warnings)
    assert len(manager.nodes) == 1
    assert manager.nodes[0].room == 1


def test_export_coverage_repo_blocks_overlap_with_structured_issue(tmp_path):
    with pytest.raises(ValueError, match="area_overlap"):
        export_mod.export_coverage_repo(
            map_data=_MapDataStub(),
            annotations=_OverlapAnnotationsStub(),
            output_root=str(tmp_path),
            map_id="demo_map",
            auto_generate_missing=False,
        )


def test_export_coverage_repo_writes_auto_planner_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(export_mod, "write_room_partition", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        export_mod,
        "route_coverage_plan",
        lambda request: _build_success_result(
            selected_planner="channel_topology_graph",
            scene_type="aisle_like",
            reasons=("free_space_bbox_is_long_and_narrow",),
        ),
    )

    result = export_mod.export_coverage_repo(
        map_data=_MapDataStub(),
        annotations=_AnnotationsStub(),
        output_root=str(tmp_path),
        map_id="demo_map",
        planner_config=CoveragePlannerConfig(planner_mode="auto"),
        auto_generate_missing=True,
    )

    coverage_yaml = yaml.safe_load((result.repo_dir / "coverage_path_master.yaml").read_text(encoding="utf-8"))
    sequence_yaml = yaml.safe_load((result.repo_dir / "room_sequence_master.yaml").read_text(encoding="utf-8"))
    meta_json = json.loads((result.repo_dir / "meta.json").read_text(encoding="utf-8"))

    _assert_exported_paths_are_runtime_policy_free(coverage_yaml)
    path_diag = coverage_yaml["paths"][0]["planner_diagnostics"]
    assert path_diag["selected_planner"] == "channel_topology_graph"
    assert path_diag["scene_type"] == "aisle_like"
    assert path_diag["reasons"] == ["free_space_bbox_is_long_and_narrow"]
    assert sequence_yaml["room_sequence_spec"]["sequences"] == [{"room_ids": [1]}]
    assert "checkpoints" not in sequence_yaml
    assert "checkpoints" not in meta_json
    assert meta_json["planner_diagnostics_by_room"]["1"]["selected_planner"] == "channel_topology_graph"
    assert result.planner_diagnostics_by_room[1]["selected_planner"] == "channel_topology_graph"


def test_export_coverage_repo_writes_explicit_planner_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(export_mod, "write_room_partition", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        export_mod,
        "run_formal_planner_request",
        lambda request, planner_mode: _build_success_result(
            selected_planner="region_basic",
            scene_type="explicit",
            reasons=("explicit_planner_mode",),
        ),
    )

    result = export_mod.export_coverage_repo(
        map_data=_MapDataStub(),
        annotations=_AnnotationsStub(),
        output_root=str(tmp_path),
        map_id="demo_map",
        planner_config=CoveragePlannerConfig(planner_mode="basic"),
        auto_generate_missing=True,
    )

    coverage_yaml = yaml.safe_load((result.repo_dir / "coverage_path_master.yaml").read_text(encoding="utf-8"))
    sequence_yaml = yaml.safe_load((result.repo_dir / "room_sequence_master.yaml").read_text(encoding="utf-8"))
    meta_json = json.loads((result.repo_dir / "meta.json").read_text(encoding="utf-8"))
    _assert_exported_paths_are_runtime_policy_free(coverage_yaml)
    path_diag = coverage_yaml["paths"][0]["planner_diagnostics"]

    assert path_diag["selected_planner"] == "region_basic"
    assert path_diag["scene_type"] == "explicit"
    assert path_diag["reasons"] == ["explicit_planner_mode"]
    assert path_diag["compact_summary"]["selected_planner"] == "region_basic"
    assert path_diag["compact_summary"]["geometry_risk"]["status"] == "not_run"
    assert "runtime_adjustments" in path_diag["runtime"]
    assert "path_quality_summary" in path_diag["runtime"]
    assert "geometry_risk_summary" in path_diag["runtime"]
    assert sequence_yaml["room_sequence_spec"]["sequences"] == [{"room_ids": [1]}]
    assert "checkpoints" not in sequence_yaml
    assert "checkpoints" not in meta_json


def test_export_coverage_repo_dispatches_explicit_shelf_aware_turn_cost(tmp_path, monkeypatch):
    monkeypatch.setattr(export_mod, "write_room_partition", lambda *args, **kwargs: None)
    calls = []

    def _run_formal(request, planner_mode):
        calls.append((request, planner_mode))
        requested_config = request.public_config
        applied_config = CoveragePlannerConfig(
            planner_mode="shelf_aware_turn_cost",
            shelf_node_generation_mode="turn_cost_repaired_grid",
            shelf_repaired_grid_max_offset_factor=0.28,
            isolated_jump_cleanup_enable=False,
        )
        return CoveragePlanningResult(
            status=CoveragePlanningStatus.SUCCESS,
            path=(
                CoveragePose2D(x=0.2, y=0.2, theta=0.0),
                CoveragePose2D(x=0.6, y=0.2, theta=0.0),
            ),
            diagnostics=CoveragePlanningDiagnostics(
                selected_planner="shelf_aware_turn_cost",
                scene_type="explicit",
                reasons=("explicit_planner_mode",),
                requested_public_config=requested_config,
                applied_public_config=applied_config,
                profile={"profile_id": "shelf_aware_turn_cost_repaired_grid_0_28", "profile_version": 2},
                mode_default_overrides={
                    "shelf_node_generation_mode": "turn_cost_repaired_grid",
                    "shelf_repaired_grid_max_offset_factor": 0.28,
                    "isolated_jump_cleanup_enable": False,
                },
                override_diff={
                    "shelf_node_generation_mode": {
                        "requested": "shelf_cell_adjusted",
                        "applied": "turn_cost_repaired_grid",
                    }
                },
            ),
        )

    monkeypatch.setattr(export_mod, "run_formal_planner_request", _run_formal)

    result = export_mod.export_coverage_repo(
        map_data=_MapDataStub(),
        annotations=_AnnotationsStub(),
        output_root=str(tmp_path),
        map_id="demo_map",
        planner_config=CoveragePlannerConfig(
            planner_mode="shelf_aware_turn_cost",
            shelf_node_generation_mode="shelf_cell_adjusted",
        ),
        auto_generate_missing=True,
    )

    assert len(calls) == 1
    request, planner_mode = calls[0]
    assert planner_mode == "shelf_aware_turn_cost"
    assert request.public_config.planner_mode == "shelf_aware_turn_cost"
    assert request.public_config.write_artifacts is True

    coverage_yaml = yaml.safe_load((result.repo_dir / "coverage_path_master.yaml").read_text(encoding="utf-8"))
    meta_json = json.loads((result.repo_dir / "meta.json").read_text(encoding="utf-8"))
    path_diag = coverage_yaml["paths"][0]["planner_diagnostics"]

    assert path_diag["selected_planner"] == "shelf_aware_turn_cost"
    assert path_diag["profile"]["profile_id"] == "shelf_aware_turn_cost_repaired_grid_0_28"
    assert path_diag["requested_public_config"]["shelf_node_generation_mode"] == "shelf_cell_adjusted"
    assert path_diag["applied_public_config"]["shelf_node_generation_mode"] == "turn_cost_repaired_grid"
    assert path_diag["compact_summary"]["profile_id"] == "shelf_aware_turn_cost_repaired_grid_0_28"
    assert "规划器=shelf aware turn cost" in path_diag["readable_summary"]["status_line"]
    assert meta_json["planner_diagnostics_by_room"]["1"]["selected_planner"] == "shelf_aware_turn_cost"
    assert result.planner_diagnostics_by_room[1]["compact_summary"]["profile_id"] == (
        "shelf_aware_turn_cost_repaired_grid_0_28"
    )


def test_build_planner_diagnostics_payload_includes_shared_readable_summary():
    diagnostics = CoveragePlanningDiagnostics(
        selected_planner="shelf_aware_turn_cost",
        scene_type="explicit",
        requested_public_config=CoveragePlannerConfig(
            planner_mode="shelf_aware_turn_cost",
            shelf_node_generation_mode="shelf_cell_adjusted",
        ),
        applied_public_config=CoveragePlannerConfig(
            planner_mode="shelf_aware_turn_cost",
            shelf_node_generation_mode="turn_cost_repaired_grid",
        ),
        profile={"profile_id": "shelf_aware_turn_cost_repaired_grid_0_28", "profile_version": 2},
        mode_default_overrides={
            "isolated_jump_cleanup_enable": False,
            "shelf_node_generation_mode": "turn_cost_repaired_grid",
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
                    "enabled": True,
                    "reason": "auxiliary_maps_available",
                }
            },
            path_quality_summary={
                "available": True,
                "status": "pass",
                "coverage_ratio": 0.9987,
                "long_jump_count": 0,
                "infeasible_segment_count": 0,
            },
            geometry_risk_summary={
                "available": False,
                "status": "not_run",
                "reason": "readonly_geometry_diagnostic_not_run_in_formal_planner",
            },
            provenance_summary={
                "available": True,
                "artifact_manifest": {
                    "available": True,
                    "path": "/tmp/shelf_turn_cost_run/artifact_manifest.json",
                    "artifact_paths": {
                        "path_overlay": {
                            "path": "/tmp/shelf_turn_cost_run/path_overlay.png",
                            "role": "path_visual_evidence",
                            "schema_or_format": "png",
                        },
                        "path_pixels": {
                            "path": "/tmp/shelf_turn_cost_run/path_pixels.json",
                            "role": "final_path_pixels_evidence",
                            "schema_or_format": "path_pixels_v2",
                        },
                    },
                },
                "path_generation_provenance": {"available": True, "move_trace_count": 7},
                "final_segment_provenance": {"available": True},
                "candidate_decision_debug": {"available": True},
            },
        ),
    )

    payload = export_mod.build_planner_diagnostics_payload(diagnostics)

    assert payload["compact_summary"]["profile_id"] == "shelf_aware_turn_cost_repaired_grid_0_28"
    assert payload["requested_public_config"]["shelf_node_generation_mode"] == "shelf_cell_adjusted"
    assert payload["applied_public_config"]["shelf_node_generation_mode"] == "turn_cost_repaired_grid"
    assert payload["readable_summary"]["version"] == "coverage_planning_diagnostics_readable.v1"
    assert "规划器=shelf aware turn cost" in payload["readable_summary"]["status_line"]
    assert "几何风险=未作为硬约束运行" in payload["readable_summary"]["status_line"]
    sections = {section["key"]: section for section in payload["readable_summary"]["detail_sections"]}
    default_rows = {row["key"]: row for row in sections["mode_default_overrides"]["rows"]}
    diff_rows = {row["key"]: row for row in sections["override_diff"]["rows"]}
    ctg_rows = {row["key"]: row for row in sections["ctg_auxiliary"]["rows"]}
    assert default_rows["isolated_jump_cleanup_enable"]["value"] == "false"
    assert default_rows["shelf_node_generation_mode"]["value"] == "turn_cost_repaired_grid"
    assert diff_rows["shelf_node_generation_mode"]["requested"] == "shelf_cell_adjusted"
    assert diff_rows["shelf_node_generation_mode"]["applied"] == "turn_cost_repaired_grid"
    assert ctg_rows["enabled"]["value"] == "true"
    assert ctg_rows["reason"]["value"] == "auxiliary_maps_available"
    artifact_rows = {row["key"]: row for row in sections["artifact_paths"]["rows"]}
    assert artifact_rows["artifact_manifest"]["value"] == "/tmp/shelf_turn_cost_run/artifact_manifest.json"
    assert artifact_rows["path_overlay"]["value"] == "/tmp/shelf_turn_cost_run/path_overlay.png"
    assert artifact_rows["path_pixels"]["artifact_kind"] == "path_pixels_v2"
    assert payload["compact_summary"]["provenance"]["artifact_manifest_path"] == (
        "/tmp/shelf_turn_cost_run/artifact_manifest.json"
    )
    assert payload["compact_summary"]["provenance"]["artifact_paths"]["path_pixels"]["path"] == (
        "/tmp/shelf_turn_cost_run/path_pixels.json"
    )


def test_build_global_room_ids_from_paths_preserves_multi_room_order():
    room_paths = [
        {"room_id": 2},
        {"room_id": 3},
        {"room_id": 4},
        {"room_id": 5},
    ]

    assert export_mod.build_global_room_ids_from_paths(room_paths) == [2, 3, 4, 5]


def test_validate_outputs_rejects_duplicate_room_ids():
    labels = np.array(
        [
            [0, 2, 3],
            [4, 5, 0],
        ],
        dtype=np.int32,
    )
    room_paths = [
        {"room_id": 2, "poses": [{"x": 0.0, "y": 0.0, "theta": 0.0}], "segments": []},
        {"room_id": 3, "poses": [{"x": 1.0, "y": 0.0, "theta": 0.0}], "segments": []},
        {"room_id": 4, "poses": [{"x": 2.0, "y": 0.0, "theta": 0.0}], "segments": []},
        {"room_id": 5, "poses": [{"x": 3.0, "y": 0.0, "theta": 0.0}], "segments": []},
    ]

    with pytest.raises(ValueError, match="duplicate room_id in sequence: 3"):
        export_mod.validate_outputs(labels, room_paths, [2, 3, 3, 5])


def test_validate_outputs_rejects_empty_room_sequence():
    labels = np.array([[0, 2], [3, 0]], dtype=np.int32)
    room_paths = [
        {"room_id": 2, "poses": [{"x": 0.0, "y": 0.0, "theta": 0.0}], "segments": []},
        {"room_id": 3, "poses": [{"x": 1.0, "y": 0.0, "theta": 0.0}], "segments": []},
    ]

    with pytest.raises(ValueError, match="room sequence is empty"):
        export_mod.validate_outputs(labels, room_paths, [])


def test_repair_path_rooms_from_area_labels_assigns_invalid_rooms():
    annotations = _AnnotationsStub()
    manager = CoveragePathManager()
    manager.nodes = [
        CoveragePathNode(
            id=0,
            room=0,
            segment=0,
            x=0.2,
            y=0.2,
            yaw=0.0,
            u=4.0,
            v=16.0,
            acc_dist=0.0,
            room_dist=0.0,
            seg_dist=0.0,
        ),
        CoveragePathNode(
            id=1,
            room=99,
            segment=0,
            x=0.4,
            y=0.4,
            yaw=0.0,
            u=8.0,
            v=12.0,
            acc_dist=0.0,
            room_dist=0.0,
            seg_dist=0.0,
        ),
        CoveragePathNode(
            id=2,
            room=1,
            segment=0,
            x=0.6,
            y=0.6,
            yaw=0.0,
            u=12.0,
            v=8.0,
            acc_dist=0.0,
            room_dist=0.0,
            seg_dist=0.0,
        ),
    ]

    changed = export_mod.repair_path_rooms_from_area_labels(manager, annotations)

    assert changed == 2
    assert [node.room for node in manager.nodes] == [1, 1, 1]
    assert manager.is_dirty is True


def test_export_coverage_repo_writes_multi_room_sequence_in_path_order(tmp_path, monkeypatch):
    monkeypatch.setattr(export_mod, "write_room_partition", lambda *args, **kwargs: None)
    monkeypatch.setattr(export_mod, "build_segmented_map", lambda *args, **kwargs: np.array(
        [
            [0, 2, 2, 0],
            [3, 3, 4, 4],
            [0, 5, 5, 0],
            [0, 0, 0, 0],
        ],
        dtype=np.int32,
    ))

    def _fake_ensure_paths(*args, **kwargs):
        return [
            (
                2,
                [_NodeStub(0, 0, 0.2, 0.2, 0.0), _NodeStub(1, 0, 0.4, 0.2, 0.0)],
                {"selected_planner": "stub", "scene_type": "test", "reasons": []},
            ),
            (
                3,
                [_NodeStub(2, 0, 1.2, 0.2, 0.0), _NodeStub(3, 0, 1.4, 0.2, 0.0)],
                {"selected_planner": "stub", "scene_type": "test", "reasons": []},
            ),
            (
                4,
                [_NodeStub(4, 0, 2.2, 0.2, 0.0), _NodeStub(5, 0, 2.4, 0.2, 0.0)],
                {"selected_planner": "stub", "scene_type": "test", "reasons": []},
            ),
            (
                5,
                [_NodeStub(6, 0, 3.2, 0.2, 0.0), _NodeStub(7, 0, 3.4, 0.2, 0.0)],
                {"selected_planner": "stub", "scene_type": "test", "reasons": []},
            ),
        ]

    monkeypatch.setattr(export_mod, "ensure_paths", _fake_ensure_paths)

    result = export_mod.export_coverage_repo(
        map_data=_MapDataStub(),
        annotations=_MultiAnnotationsStub(),
        output_root=str(tmp_path),
        map_id="demo_map_multi",
        auto_generate_missing=False,
    )

    sequence_yaml = yaml.safe_load((result.repo_dir / "room_sequence_master.yaml").read_text(encoding="utf-8"))
    meta_json = json.loads((result.repo_dir / "meta.json").read_text(encoding="utf-8"))
    statistics_path = result.repo_dir / "coverage_path_statistics" / "coverage_path_statistics_2.txt"

    assert sequence_yaml["room_sequence_spec"]["sequences"] == [{"room_ids": [2, 3, 4, 5]}]
    assert "checkpoints" not in sequence_yaml
    assert statistics_path.exists()
    statistics_text = statistics_path.read_text(encoding="utf-8")
    assert "总路径点数: 2" in statistics_text
    assert "房间 2: 2 个点, 距离: 0.200 米" in statistics_text
    assert "房间 2, Segment 0: 2 个点, 距离: 0.200 米" in statistics_text
    assert "0\t2\t0\t0.200000\t0.200000\t0.000000\t0\t0\t0.000\t0.000\t0.000" in statistics_text
    assert "demo_map_multi/coverage_path_statistics/coverage_path_statistics_2.txt" in result.output_files
    assert "checkpoints" not in meta_json
    assert result.room_count == 4


def test_build_total_free_map_respects_no_coverage_segments():
    class _NoCoverageAnnotations(_AnnotationsStub):
        def __init__(self):
            super().__init__()
            self.constraint_segments = [
                type(
                    "SegmentStub",
                    (),
                    {
                        "points": ((0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4)),
                        "closed": True,
                        "constraint_type": "no_coverage",
                    },
                )()
            ]

        def iter_constraint_segments(self, constraint_type: str, *, closed=None):
            for segment in self.constraint_segments:
                if segment.constraint_type != constraint_type:
                    continue
                if closed is not None and bool(segment.closed) != bool(closed):
                    continue
                yield segment

    free_map = export_mod.build_total_free_map(_MapDataStub(), _NoCoverageAnnotations())
    blocked = free_map[12:16, 4:8]
    assert blocked.size > 0
    assert np.all(blocked == 0)


def test_build_total_free_map_can_ignore_no_coverage_by_policy():
    class _NoCoverageAnnotations(_AnnotationsStub):
        def __init__(self):
            super().__init__()
            self.constraint_segments = [
                type(
                    "SegmentStub",
                    (),
                    {
                        "points": ((0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4)),
                        "closed": True,
                        "constraint_type": "no_coverage",
                    },
                )()
            ]

        def iter_constraint_segments(self, constraint_type: str, *, closed=None):
            for segment in self.constraint_segments:
                if segment.constraint_type != constraint_type:
                    continue
                if closed is not None and bool(segment.closed) != bool(closed):
                    continue
                yield segment

    free_map = export_mod.build_total_free_map(
        _MapDataStub(),
        _NoCoverageAnnotations(),
        blocking_policy=export_mod.CoverageBlockingPolicy(block_no_coverage=False),
    )
    assert np.all(free_map[12:16, 4:8] == 255)


def test_build_total_free_map_respects_derived_no_coverage_regions():
    class _DerivedNoCoverageAnnotations(_AnnotationsStub):
        def __init__(self):
            super().__init__()
            self.derived_constraint_regions = [
                type(
                    "RegionStub",
                    (),
                    {
                        "action_type": "no_coverage",
                        "component_id": 7,
                        "bbox_px": (4, 12, 4, 4),
                    },
                )()
            ]

        def iter_derived_constraint_regions(self, action_type: str | None = None):
            for region in self.derived_constraint_regions:
                if action_type is not None and region.action_type != action_type:
                    continue
                yield region

        def decode_derived_constraint_region_mask(self, region):
            return np.full((4, 4), 255, dtype=np.uint8)

    free_map = export_mod.build_total_free_map(_MapDataStub(), _DerivedNoCoverageAnnotations())
    blocked = free_map[12:16, 4:8]
    assert blocked.size > 0
    assert np.all(blocked == 0)


def test_build_total_free_map_does_not_block_pass_only_by_default():
    class _PassOnlyAnnotations(_AnnotationsStub):
        def __init__(self):
            super().__init__()
            self.pass_only_zones = [
                type(
                    "PassOnlyStub",
                    (),
                    {"polygon": ((0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4))},
                )()
            ]

    free_map = export_mod.build_total_free_map(_MapDataStub(), _PassOnlyAnnotations())

    assert np.all(free_map[12:16, 4:8] == 255)
