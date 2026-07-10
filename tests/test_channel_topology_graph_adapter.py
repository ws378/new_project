from types import SimpleNamespace
from pathlib import Path

import numpy as np

from algorithms.coverage_planning.contracts import (
    CoveragePlannerConfig,
    CoveragePlannerPrivateConfig,
    CoveragePlanningRequest,
    CoveragePlanningStatus,
)
from algorithms.coverage_planning.routing.adapters.channel_topology_graph_adapter import (
    _build_success_result,
    build_channel_topology_graph_config,
    build_region_mask_from_request,
    run_channel_topology_graph_adapter,
)
from algorithms.coverage_planning.routing.adapters.shelf_aware_ctg_auxiliary import (
    _build_ctg_auxiliary_config,
)


def _request() -> CoveragePlanningRequest:
    room_map = np.zeros((10, 20), dtype=np.uint8)
    room_map[2:8, 3:17] = 255
    return CoveragePlanningRequest(
        prepared_map=room_map,
        map_resolution=0.1,
        starting_position_px=(4, 5),
        map_origin_xy=(1.0, 2.0),
        region_polygon_px=((3, 2), (17, 2), (17, 8), (3, 8)),
        public_config=CoveragePlannerConfig(coverage_width_m=0.3),
        public_config_source_keys=("coverage_width_m",),
        private_config=CoveragePlannerPrivateConfig(enable_channel_topology_graph=True),
    )


def test_build_region_mask_from_request_polygon():
    mask = build_region_mask_from_request(_request())

    assert mask is not None
    assert mask.shape == (10, 20)
    assert int(np.count_nonzero(mask)) > 0


def test_build_region_mask_prefers_explicit_region_mask():
    request = _request()
    explicit_mask = np.zeros((10, 20), dtype=np.uint8)
    explicit_mask[4:6, 7:9] = 255
    request = CoveragePlanningRequest(
        prepared_map=request.prepared_map,
        map_resolution=request.map_resolution,
        starting_position_px=request.starting_position_px,
        map_origin_xy=request.map_origin_xy,
        region_mask=explicit_mask,
        region_polygon_px=request.region_polygon_px,
        public_config=request.public_config,
        private_config=request.private_config,
    )

    mask = build_region_mask_from_request(request)

    assert int(np.count_nonzero(mask)) == 4
    assert int(mask[4, 7]) == 255


def test_shelf_aware_ctg_auxiliary_retry_config_disables_boundary_smoothing():
    config = _build_ctg_auxiliary_config(_request(), boundary_smoothing_enable=False)

    geometry_config = config.geometry_preparation
    assert geometry_config["boundary_smoothing_enable"] is False
    assert geometry_config["boundary_smoothing"]["enable"] is False


def test_channel_topology_graph_adapter_passes_prepared_map_without_legacy_raw_map_wrap(monkeypatch):
    request = _request()
    captured: dict[str, object] = {}

    geometry_result = SimpleNamespace(crop_box_px=(0, 0, 10, 20), resolution_m_per_px=0.1)
    junction_result = SimpleNamespace()
    topology_result = SimpleNamespace()
    coverage_result = SimpleNamespace(
        final_coverage_path_build_info=SimpleNamespace(
            final_coverage_path_info={"routes": ()},
            validation_info={"is_valid": True},
            summary={},
        ),
        meta={},
    )

    def _capture_geometry(**kwargs):
        captured["raw_map"] = kwargs["pipeline_input"].raw_map
        captured["region_constraint"] = kwargs["pipeline_input"].region_constraint
        captured["config"] = kwargs["config"]
        return geometry_result

    monkeypatch.setattr(
        "algorithms.channel_topology_graph.pipeline.main_pipeline.run_geometry_preparation_stage",
        _capture_geometry,
    )
    monkeypatch.setattr(
        "algorithms.channel_topology_graph.pipeline.main_pipeline.run_junction_rebuild_stage",
        lambda **_: junction_result,
    )
    monkeypatch.setattr(
        "algorithms.channel_topology_graph.pipeline.main_pipeline.run_topology_graph_build_stage",
        lambda **_: topology_result,
    )
    monkeypatch.setattr(
        "algorithms.channel_topology_graph.pipeline.main_pipeline.run_coverage_planning_stage",
        lambda **_: coverage_result,
    )
    monkeypatch.setattr(
        "algorithms.channel_topology_graph.pipeline.main_pipeline.build_pipeline_run_result",
        lambda **kwargs: SimpleNamespace(
            geometry_preparation_result=kwargs["stage_results"]["geometry_preparation_result"],
            junction_rebuild_result=kwargs["stage_results"]["junction_rebuild_result"],
            topology_graph_build_result=kwargs["stage_results"]["topology_graph_build_result"],
            coverage_planning_result=kwargs["stage_results"]["coverage_planning_result"],
            meta={"pipeline_name": "channel_topology_graph", "input_meta": {"source": "coverage_planning_router"}},
        ),
    )

    monkeypatch.setattr("algorithms.channel_topology_graph.io.write_geometry_preparation_summary", lambda *args, **kwargs: "")
    monkeypatch.setattr("algorithms.channel_topology_graph.io.write_junction_rebuild_summary", lambda *args, **kwargs: "")
    monkeypatch.setattr("algorithms.channel_topology_graph.io.write_topology_graph_build_summary", lambda *args, **kwargs: "")
    monkeypatch.setattr("algorithms.channel_topology_graph.io.write_coverage_planning_summary", lambda *args, **kwargs: "")
    monkeypatch.setattr("algorithms.channel_topology_graph.io.write_coverage_planning_result_json", lambda *args, **kwargs: "")
    monkeypatch.setattr("algorithms.channel_topology_graph.renderers.write_geometry_preparation_visualizations", lambda *args, **kwargs: {})
    monkeypatch.setattr("algorithms.channel_topology_graph.renderers.write_junction_rebuild_visualizations", lambda *args, **kwargs: {})
    monkeypatch.setattr("algorithms.channel_topology_graph.renderers.write_coverage_planning_visualizations", lambda *args, **kwargs: {})

    result = run_channel_topology_graph_adapter(request)

    assert result.status == CoveragePlanningStatus.FAILURE
    assert isinstance(captured["raw_map"], np.ndarray)
    assert captured["raw_map"] is request.prepared_map
    assert captured["region_constraint"] is not None
    assert captured["config"].geometry_preparation["input_is_prepared_map"] is True
    assert captured["config"].geometry_preparation["resolution_m_per_px"] == 0.1


def test_build_channel_topology_graph_config_uses_width_contract():
    config = build_channel_topology_graph_config(_request())

    assert config["coverage_planning"]["robot_width_m"] == 0.3
    assert config["coverage_planning"]["coverage_width_m"] == 0.3
    assert config["runtime"]["adapter_name"] == "channel_topology_graph_adapter"


def test_build_channel_topology_graph_config_honors_private_runtime_controls():
    base_request = _request()
    request = CoveragePlanningRequest(
        prepared_map=base_request.prepared_map,
        map_resolution=base_request.map_resolution,
        starting_position_px=base_request.starting_position_px,
        map_origin_xy=base_request.map_origin_xy,
        region_polygon_px=base_request.region_polygon_px,
        public_config=CoveragePlannerConfig(
            coverage_width_m=0.3,
            write_artifacts=False,
        ),
        public_config_source_keys=base_request.public_config_source_keys,
        private_config=CoveragePlannerPrivateConfig(
            enable_channel_topology_graph=True,
            ctg_include_truncation_debug=True,
            ctg_pure_cycle_parallel_workers=3,
        ),
    )

    config = build_channel_topology_graph_config(request)

    assert config["junction_rebuild"]["include_truncation_debug"] is True
    assert config["junction_rebuild"]["pure_cycle_parallel_workers"] == 3


def test_build_channel_topology_graph_config_rejects_removed_legacy_public_fields():
    try:
        CoveragePlannerConfig(
            coverage_radius=0.4,  # type: ignore[call-arg]
        )
    except TypeError:
        pass
    else:
        raise AssertionError("expected removed legacy public config keys to fail at typed config boundary")

    try:
        from algorithms.coverage_planning.contracts import normalize_coverage_planner_config_dict

        normalize_coverage_planner_config_dict(
            {
                "coverage_radius": 0.4,
                "robot_radius": 0.35,
                "erode_radius_m": 0.25,
            }
        )
    except ValueError as exc:
        assert "legacy public config keys are no longer supported" in str(exc)
        return

    raise AssertionError("expected removed legacy public config keys to fail")


def test_build_channel_topology_graph_config_rejects_removed_legacy_ctg_width_fields():
    from algorithms.coverage_planning.contracts import build_private_coverage_planner_config

    try:
        build_private_coverage_planner_config(
            {
                "sweep_max_spacing_m": 0.4,
            }
        )
    except ValueError as exc:
        assert "legacy CTG config keys are no longer supported" in str(exc)
        return

    raise AssertionError("expected removed legacy CTG width keys to fail")


def test_build_success_result_converts_local_rc_points_to_world_path():
    request = _request()
    final_build_info = SimpleNamespace(
        final_coverage_path_info={
            "routes": (
                {
                    "path_subchains_rc": (
                        ((1.0, 2.0), (1.0, 4.0)),
                    ),
                },
            ),
        },
        validation_info={"is_valid": True},
        summary={"route_count": 1, "path_point_count": 2},
    )
    pipeline_result = SimpleNamespace(
        geometry_preparation_result=SimpleNamespace(crop_box_px=(2, 3, 8, 17), resolution_m_per_px=0.1),
        coverage_planning_result=SimpleNamespace(
            final_coverage_path_build_info=final_build_info,
            meta={"final_coverage_path_route_count": 1},
        ),
        meta={"pipeline_name": "channel_topology_graph"},
    )

    result = _build_success_result(request=request, pipeline_result=pipeline_result)

    assert result.status == CoveragePlanningStatus.SUCCESS
    assert result.path_pixels == ((5.0, 3.0), (7.0, 3.0))
    assert result.path[0].x == 1.5
    assert result.path[0].y == 2.7
    assert result.diagnostics.selected_planner == "channel_topology_graph"
    assert result.diagnostics.runtime.pipeline_meta.pipeline_name == "channel_topology_graph"
    assert result.diagnostics.runtime.final_path_summary.route_count == 1


def test_channel_topology_graph_adapter_writes_staged_artifacts(monkeypatch, tmp_path):
    request = CoveragePlanningRequest(
        prepared_map=_request().prepared_map,
        map_resolution=_request().map_resolution,
        starting_position_px=_request().starting_position_px,
        map_origin_xy=_request().map_origin_xy,
        region_polygon_px=_request().region_polygon_px,
        public_config=_request().public_config,
        public_config_source_keys=_request().public_config_source_keys,
        private_config=_request().private_config,
        artifacts_output_root=tmp_path,
    )

    geometry_result = SimpleNamespace(
        crop_box_px=(0, 0, 10, 20),
        resolution_m_per_px=0.1,
    )
    junction_result = SimpleNamespace()
    topology_result = SimpleNamespace()
    coverage_result = SimpleNamespace(
        final_coverage_path_build_info=SimpleNamespace(
            final_coverage_path_info={"routes": ()},
            validation_info={"is_valid": True},
            summary={},
        ),
        meta={},
    )

    monkeypatch.setattr(
        "algorithms.channel_topology_graph.pipeline.main_pipeline.run_geometry_preparation_stage",
        lambda **_: geometry_result,
    )
    monkeypatch.setattr(
        "algorithms.channel_topology_graph.pipeline.main_pipeline.run_junction_rebuild_stage",
        lambda **_: junction_result,
    )
    monkeypatch.setattr(
        "algorithms.channel_topology_graph.pipeline.main_pipeline.run_topology_graph_build_stage",
        lambda **_: topology_result,
    )
    monkeypatch.setattr(
        "algorithms.channel_topology_graph.pipeline.main_pipeline.run_coverage_planning_stage",
        lambda **_: coverage_result,
    )
    monkeypatch.setattr(
        "algorithms.channel_topology_graph.pipeline.main_pipeline.build_pipeline_run_result",
        lambda **kwargs: SimpleNamespace(
            geometry_preparation_result=kwargs["stage_results"]["geometry_preparation_result"],
            junction_rebuild_result=kwargs["stage_results"]["junction_rebuild_result"],
            topology_graph_build_result=kwargs["stage_results"]["topology_graph_build_result"],
            coverage_planning_result=kwargs["stage_results"]["coverage_planning_result"],
            meta={"pipeline_name": "channel_topology_graph", "input_meta": {"source": "coverage_planning_router"}},
        ),
    )

    def _touch_summary(result, output_dir, extra_meta=None):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "summary.json").write_text("{}", encoding="utf-8")
        return str((out / "summary.json").resolve())

    def _touch_result_json(result, output_dir):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "coverage_planning_result.json").write_text("{}", encoding="utf-8")
        return str((out / "coverage_planning_result.json").resolve())

    def _touch_viz(*args, **kwargs):
        output_dir = kwargs.get("output_dir")
        if output_dir is None:
            for item in args:
                if isinstance(item, (str, Path)):
                    output_dir = item
                    break
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "stub.png").write_text("x", encoding="utf-8")
        return {"stub": str((out / "stub.png").resolve())}

    monkeypatch.setattr("algorithms.channel_topology_graph.io.write_geometry_preparation_summary", _touch_summary)
    monkeypatch.setattr("algorithms.channel_topology_graph.io.write_junction_rebuild_summary", _touch_summary)
    monkeypatch.setattr("algorithms.channel_topology_graph.io.write_topology_graph_build_summary", _touch_summary)
    monkeypatch.setattr("algorithms.channel_topology_graph.io.write_coverage_planning_summary", _touch_summary)
    monkeypatch.setattr("algorithms.channel_topology_graph.io.write_coverage_planning_result_json", _touch_result_json)
    monkeypatch.setattr("algorithms.channel_topology_graph.renderers.write_geometry_preparation_visualizations", _touch_viz)
    monkeypatch.setattr("algorithms.channel_topology_graph.renderers.write_junction_rebuild_visualizations", _touch_viz)
    monkeypatch.setattr("algorithms.channel_topology_graph.renderers.write_coverage_planning_visualizations", _touch_viz)

    result = run_channel_topology_graph_adapter(request)

    assert result.status == CoveragePlanningStatus.FAILURE
    run_dir = Path(result.diagnostics.artifacts_dir)
    assert run_dir.parent == tmp_path.resolve()
    assert (run_dir / "geometry_preparation" / "summary.json").is_file()
    assert (run_dir / "geometry_preparation" / "viz" / "stub.png").is_file()
    assert (run_dir / "junction_rebuild" / "summary.json").is_file()
    assert (run_dir / "junction_rebuild" / "viz" / "stub.png").is_file()
    assert (run_dir / "topology_graph_build" / "summary.json").is_file()
    assert (run_dir / "coverage_planning" / "summary.json").is_file()
    assert (run_dir / "coverage_planning" / "coverage_planning_result.json").is_file()
    assert (run_dir / "coverage_planning" / "viz" / "stub.png").is_file()


def test_channel_topology_graph_adapter_keeps_previous_stage_outputs_on_late_failure(monkeypatch, tmp_path):
    request = CoveragePlanningRequest(
        prepared_map=_request().prepared_map,
        map_resolution=_request().map_resolution,
        starting_position_px=_request().starting_position_px,
        map_origin_xy=_request().map_origin_xy,
        region_polygon_px=_request().region_polygon_px,
        public_config=_request().public_config,
        public_config_source_keys=_request().public_config_source_keys,
        private_config=_request().private_config,
        artifacts_output_root=tmp_path,
    )

    geometry_result = SimpleNamespace(crop_box_px=(0, 0, 10, 20), resolution_m_per_px=0.1)
    junction_result = SimpleNamespace()

    monkeypatch.setattr(
        "algorithms.channel_topology_graph.pipeline.main_pipeline.run_geometry_preparation_stage",
        lambda **_: geometry_result,
    )
    monkeypatch.setattr(
        "algorithms.channel_topology_graph.pipeline.main_pipeline.run_junction_rebuild_stage",
        lambda **_: junction_result,
    )
    monkeypatch.setattr(
        "algorithms.channel_topology_graph.pipeline.main_pipeline.run_topology_graph_build_stage",
        lambda **_: (_ for _ in ()).throw(ValueError("boom in topology")),
    )

    def _touch_summary(result, output_dir, extra_meta=None):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "summary.json").write_text("{}", encoding="utf-8")
        return str((out / "summary.json").resolve())

    def _touch_viz(*args, **kwargs):
        output_dir = kwargs.get("output_dir")
        if output_dir is None:
            for item in args:
                if isinstance(item, (str, Path)):
                    output_dir = item
                    break
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "stub.png").write_text("x", encoding="utf-8")
        return {"stub": str((out / "stub.png").resolve())}

    monkeypatch.setattr("algorithms.channel_topology_graph.io.write_geometry_preparation_summary", _touch_summary)
    monkeypatch.setattr("algorithms.channel_topology_graph.io.write_junction_rebuild_summary", _touch_summary)
    monkeypatch.setattr("algorithms.channel_topology_graph.renderers.write_geometry_preparation_visualizations", _touch_viz)
    monkeypatch.setattr("algorithms.channel_topology_graph.renderers.write_junction_rebuild_visualizations", _touch_viz)

    result = run_channel_topology_graph_adapter(request)

    assert result.status == CoveragePlanningStatus.FAILURE
    assert "failed at topology_graph_build" in result.error_message
    run_dir = Path(result.diagnostics.artifacts_dir)
    assert (run_dir / "geometry_preparation" / "summary.json").is_file()
    assert (run_dir / "junction_rebuild" / "summary.json").is_file()
    assert not (run_dir / "topology_graph_build" / "summary.json").exists()
    assert (run_dir / "pipeline_failure.json").is_file()
