from pathlib import Path

import numpy as np

from algorithms.coverage_planning.contracts import (
    CoveragePlannerConfig,
    CoveragePlannerPrivateConfig,
    CoveragePlanningDiagnostics,
    CoveragePlanningRequest,
    CoveragePlanningResult,
    CoveragePlanningStatus,
    CoveragePose2D,
    normalize_coverage_planner_config_dict,
)
from algorithms.coverage_planning.routing import classify_applicability, route_coverage_plan


def _request(
    room_map: np.ndarray,
    start=(10, 10),
    artifacts_output_root: Path | None = None,
) -> CoveragePlanningRequest:
    return CoveragePlanningRequest(
        prepared_map=room_map,
        map_resolution=0.05,
        starting_position_px=start,
        public_config=CoveragePlannerConfig(
            coverage_width_m=0.5,
            robot_width_m=0.2,
            open_kernel_m=0.1,
            auto_rotate=False,
            write_artifacts=False,
        ),
        artifacts_output_root=artifacts_output_root,
    )


def test_classify_invalid_scene_when_no_free_space():
    result = classify_applicability(_request(np.zeros((40, 40), dtype=np.uint8)))

    assert result.scene_type == "invalid"
    assert result.recommended_planner == ""
    assert "no_free_space" in result.reasons


def test_route_room_like_scene_to_region_basic(tmp_path):
    room_map = np.zeros((80, 80), dtype=np.uint8)
    room_map[10:70, 10:70] = 255

    result = route_coverage_plan(_request(room_map, start=(20, 20), artifacts_output_root=tmp_path))

    assert result.status == CoveragePlanningStatus.SUCCESS
    assert result.diagnostics.selected_planner == "region_basic"
    assert result.diagnostics.scene_type == "room_like"
    assert result.diagnostics.fallback_chain == ("shelf_aware",)
    assert result.diagnostics.metrics.free_area_pixel_count > 0
    assert result.diagnostics.applied_public_config is not None
    assert result.diagnostics.applied_public_config.coverage_width_m == 0.5
    assert len(result.path) > 0


def test_route_long_narrow_scene_to_shelf_aware_without_topology_graph(tmp_path):
    room_map = np.zeros((60, 220), dtype=np.uint8)
    room_map[20:40, 10:210] = 255

    result = route_coverage_plan(_request(room_map, start=(20, 30), artifacts_output_root=tmp_path))

    assert result.status == CoveragePlanningStatus.SUCCESS
    assert result.diagnostics.selected_planner == "shelf_aware"
    assert result.diagnostics.scene_type == "aisle_like"
    assert any("enable_channel_topology_graph" in item for item in result.diagnostics.warnings)


def test_route_long_narrow_scene_to_topology_graph_when_explicitly_enabled(monkeypatch, tmp_path):
    room_map = np.zeros((60, 220), dtype=np.uint8)
    room_map[20:40, 10:210] = 255
    request = _request(room_map, start=(20, 30), artifacts_output_root=tmp_path)

    def fake_adapter(_request):
        return CoveragePlanningResult(
            status=CoveragePlanningStatus.SUCCESS,
            path=(CoveragePose2D(1.0, 2.0, 0.0),),
            path_pixels=((20.0, 30.0),),
            diagnostics=CoveragePlanningDiagnostics(
                selected_planner="channel_topology_graph",
                scene_type="aisle_like",
                reasons=("adapter_ok",),
            ),
        )

    monkeypatch.setattr(
        "algorithms.coverage_planning.routing.coverage_router.run_channel_topology_graph_adapter",
        fake_adapter,
    )
    request = CoveragePlanningRequest(
        prepared_map=request.prepared_map,
        map_resolution=request.map_resolution,
        starting_position_px=request.starting_position_px,
        map_origin_xy=request.map_origin_xy,
        region_mask=request.region_mask,
        map_yaml_path=request.map_yaml_path,
        artifacts_output_root=request.artifacts_output_root,
        public_config=request.public_config,
        private_config=CoveragePlannerPrivateConfig(enable_channel_topology_graph=True),
    )

    result = route_coverage_plan(request)

    assert result.status == CoveragePlanningStatus.SUCCESS
    assert result.diagnostics.selected_planner == "channel_topology_graph"
    assert result.diagnostics.scene_type == "aisle_like"
    assert result.diagnostics.fallback_chain == ("shelf_aware", "region_basic")
    assert "explicit_channel_topology_graph_enabled" in result.diagnostics.reasons
    assert "adapter_ok" in result.diagnostics.reasons


def test_route_mixed_scene_uses_conservative_region_planner(tmp_path):
    room_map = np.zeros((100, 180), dtype=np.uint8)
    room_map[20:80, 10:170] = 255

    result = route_coverage_plan(_request(room_map, start=(30, 30), artifacts_output_root=tmp_path))

    assert result.status == CoveragePlanningStatus.SUCCESS
    assert result.diagnostics.selected_planner == "shelf_aware"
    assert result.diagnostics.scene_type == "mixed"
    assert any("does not perform room segmentation" in item for item in result.diagnostics.warnings)


def test_route_invalid_scene_returns_unsupported_without_planning():
    result = route_coverage_plan(_request(np.zeros((40, 40), dtype=np.uint8)))

    assert result.status == CoveragePlanningStatus.UNSUPPORTED
    assert result.diagnostics.selected_planner == ""


def test_route_uses_region_mask_not_whole_prepared_map():
    prepared_map = np.zeros((120, 120), dtype=np.uint8)
    prepared_map[10:110, 10:110] = 255
    region_mask = np.zeros((120, 120), dtype=np.uint8)
    region_mask[50:70, 10:110] = 255
    request = CoveragePlanningRequest(
        prepared_map=prepared_map,
        map_resolution=0.05,
        starting_position_px=(20, 60),
        region_mask=region_mask,
        public_config=CoveragePlannerConfig(
            coverage_width_m=0.5,
            robot_width_m=0.2,
            open_kernel_m=0.1,
            auto_rotate=False,
            write_artifacts=False,
        ),
    )

    result = classify_applicability(request)

    assert result.scene_type == "aisle_like"
    assert result.recommended_planner == "shelf_aware"


def test_route_auto_applies_region_constraint_before_formal_planner(monkeypatch):
    prepared_map = np.zeros((120, 120), dtype=np.uint8)
    prepared_map[10:110, 10:110] = 255
    region_mask = np.zeros((120, 120), dtype=np.uint8)
    region_mask[50:70, 10:110] = 255
    request = CoveragePlanningRequest(
        prepared_map=prepared_map,
        map_resolution=0.05,
        starting_position_px=(20, 60),
        region_mask=region_mask,
        public_config=CoveragePlannerConfig(
            coverage_width_m=0.5,
            robot_width_m=0.2,
            open_kernel_m=0.1,
            auto_rotate=False,
            write_artifacts=False,
        ),
    )

    captured = {}

    class FakePlanner:
        def plan(self, room_map, map_resolution, starting_position, map_origin, region_mask=None):
            captured["room_map"] = np.asarray(room_map).copy()
            captured["region_mask"] = np.asarray(region_mask).copy() if region_mask is not None else None
            return CoveragePlanningResult(
                status=CoveragePlanningStatus.SUCCESS,
                path=(CoveragePose2D(1.0, 2.0, 0.0),),
                path_pixels=((20.0, 60.0),),
                diagnostics=CoveragePlanningDiagnostics(
                    selected_planner="shelf_aware",
                    scene_type="aisle_like",
                ),
            )

    monkeypatch.setattr(
        "algorithms.coverage_planning.routing.coverage_router._create_planner",
        lambda planner_name, config: FakePlanner(),
    )

    result = route_coverage_plan(request)

    assert result.status == CoveragePlanningStatus.SUCCESS
    effective_map = captured["room_map"]
    assert int(np.count_nonzero(effective_map == 255)) == int(np.count_nonzero(region_mask == 255))
    assert np.all(effective_map[region_mask == 0] == 0)
    assert np.array_equal(captured["region_mask"], region_mask)


def test_router_source_does_not_depend_on_room_segmentation():
    routing_root = Path("algorithms/coverage_planning/routing")
    source = "\n".join(path.read_text() for path in routing_root.rglob("*.py"))

    assert "room_segmentation" not in source


def test_request_rejects_region_mask_shape_mismatch():
    room_map = np.zeros((20, 30), dtype=np.uint8)
    bad_mask = np.zeros((10, 10), dtype=np.uint8)

    try:
        CoveragePlanningRequest(
            prepared_map=room_map,
            map_resolution=0.05,
            starting_position_px=(5, 5),
            region_mask=bad_mask,
        )
    except ValueError as exc:
        assert "same shape as prepared_map" in str(exc)
        return

    raise AssertionError("expected region_mask shape validation to fail")


def test_normalize_coverage_planner_config_dict_rejects_removed_legacy_keys():
    try:
        normalize_coverage_planner_config_dict(
            {
                "coverage_radius": 0.5,
                "robot_radius": 0.4,
            }
        )
    except ValueError as exc:
        assert "legacy public config keys are no longer supported" in str(exc)
        return

    raise AssertionError("expected removed legacy config keys to fail")


def test_normalize_coverage_planner_config_dict_keeps_stage2_payload_unchanged():
    normalized = normalize_coverage_planner_config_dict(
        {
            "coverage_width_m": 0.55,
            "open_kernel_m": 0.4,
            "robot_width_m": 0.45,
        }
    )

    assert normalized["coverage_width_m"] == 0.55
    assert normalized["open_kernel_m"] == 0.4
    assert normalized["robot_width_m"] == 0.45
