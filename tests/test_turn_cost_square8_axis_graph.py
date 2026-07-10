from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import shapely.geometry as sgeo
import pytest

from algorithms.turn_cost_coverage_research.src.guidance.square8_axis_graph import (
    Square8AxisGraphConfig,
    create_square8_axis_guided_graph,
)

try:
    from algorithms.turn_cost_coverage_research.scripts.experiments.run_maptools_official_cases import (
        _graph_backend_cli_config_from_args,
        _graph_backend_config_from_args,
        _validate_experiment_scope,
    )
except ImportError as exc:
    _graph_backend_cli_config_from_args = None
    _graph_backend_config_from_args = None
    _validate_experiment_scope = None
    OFFICIAL_CASES_IMPORT_ERROR = exc
else:
    OFFICIAL_CASES_IMPORT_ERROR = None


def _require_official_cases() -> None:
    if OFFICIAL_CASES_IMPORT_ERROR is not None:
        pytest.skip(f"official maptools cases environment unavailable: {OFFICIAL_CASES_IMPORT_ERROR}")


@dataclass(frozen=True)
class _Point:
    x: float
    y: float

    def to_shapely(self):
        return sgeo.Point(self.x, self.y)


class _Vertex:
    def __init__(self, value) -> None:
        self.point = _Point(float(value[0]), float(value[1]))

    @property
    def x(self) -> float:
        return self.point.x

    @property
    def y(self) -> float:
        return self.point.y


class _Area:
    def __init__(self) -> None:
        self.polygon = sgeo.box(-0.1, -0.1, 2.1, 2.1)

    def get_bounding_box(self):
        return ((0.0, 0.0), (2.0, 2.0))

    def as_shapely_polygon(self):
        return self.polygon

    def has_line_of_sight(self, p0, p1) -> bool:
        return self.polygon.covers(sgeo.LineString([(p0.x, p0.y), (p1.x, p1.y)]))


def test_square8_axis_graph_creates_orthogonal_and_diagonal_edges() -> None:
    _, graph, stats = create_square8_axis_guided_graph(
        polygonal_area=_Area(),
        point_vertex_cls=_Vertex,
        config=Square8AxisGraphConfig(grid_step_m=1.0, bridge_disconnected_components=False),
        guidance_field=None,
    )

    assert graph.number_of_nodes() == 9
    assert stats["orthogonal_edge_count"] == 12
    assert stats["diagonal_edge_count"] == 8
    assert stats["bridges"]["bridge_attempt_status"] == "disabled"


def test_square8_axis_graph_rejects_invalid_grid_step() -> None:
    with pytest.raises(ValueError, match="grid_step_m"):
        Square8AxisGraphConfig(grid_step_m=0.0)


def test_square8_axis_graph_experiment_scope_rejects_guided_atomic_combo() -> None:
    _require_official_cases()
    args = SimpleNamespace(
        graph_backend="square8_axis_guided",
        guidance_mode="shelf_local_direction",
        allow_square8_guided_atomic=False,
        project_dir="examples/maptools_projects/beiguo_lanshan_1770397756",
        area_id=4,
        component_index=0,
    )

    with pytest.raises(SystemExit, match="guided atomic"):
        _validate_experiment_scope(args)


def test_square8_axis_graph_experiment_scope_accepts_batch_cases() -> None:
    _require_official_cases()
    args = SimpleNamespace(
        graph_backend="square8_axis_guided",
        guidance_mode="none",
        allow_square8_guided_atomic=False,
        project_dir="examples/maptools_projects/beiguoshangcheng_floor_3",
        area_id=3,
        component_index=None,
    )

    _validate_experiment_scope(args)


def test_square8_axis_graph_experiment_scope_accepts_current_case() -> None:
    _require_official_cases()
    args = SimpleNamespace(
        graph_backend="square8_axis_guided",
        guidance_mode="none",
        allow_square8_guided_atomic=False,
        project_dir="examples/maptools_projects/beiguo_lanshan_1770397756",
        area_id=4,
        component_index=0,
    )

    _validate_experiment_scope(args)


def test_square8_axis_graph_experiment_scope_accepts_explicit_guided_atomic_combo() -> None:
    _require_official_cases()
    args = SimpleNamespace(
        graph_backend="square8_axis_guided",
        guidance_mode="shelf_local_direction",
        allow_square8_guided_atomic=True,
        project_dir="examples/maptools_projects/beiguoshangcheng_floor_3",
        area_id=5,
        component_index=None,
    )

    _validate_experiment_scope(args)


def test_square8_guided_atomic_graph_backend_summary_marks_combined_experiment() -> None:
    _require_official_cases()
    args = SimpleNamespace(
        graph_backend="square8_axis_guided",
        guidance_mode="shelf_local_direction",
        allow_square8_guided_atomic=True,
        square_grid_step_scale=1.0,
        square_diagonal_cost_multiplier=1.15,
        square_axis_confidence_threshold=0.60,
        square_axis_angle_tolerance_deg=25.0,
        square_no_component_bridge=False,
        square_bridge_max_step_factor=8.0,
        square_bridge_cost_multiplier=4.0,
        atomic_guidance_strategy="soft_bias",
        corridor_axis_primary_orientation_count=None,
    )

    config = _graph_backend_config_from_args(args, tool_radius_m=0.275)

    assert config["allow_square8_guided_atomic"] is True
    assert config["algorithm_impact"] == "non_official_square8_axis_guided_graph_backend_plus_guided_atomic_strip_bias"
    assert "guided atomic" in str(config["official_difference"])

    cli_config = _graph_backend_cli_config_from_args(args)
    assert cli_config["algorithm_impact"] == "non_official_square8_axis_guided_graph_backend_plus_guided_atomic_strip_bias"


def test_square8_corridor_axis_graph_backend_summary_marks_candidate_replacement() -> None:
    _require_official_cases()
    args = SimpleNamespace(
        graph_backend="square8_axis_guided",
        guidance_mode="shelf_local_direction",
        allow_square8_guided_atomic=True,
        square_grid_step_scale=1.0,
        square_diagonal_cost_multiplier=1.15,
        square_axis_confidence_threshold=0.60,
        square_axis_angle_tolerance_deg=25.0,
        square_no_component_bridge=False,
        square_bridge_max_step_factor=8.0,
        square_bridge_cost_multiplier=4.0,
        atomic_guidance_strategy="corridor_axis",
        corridor_axis_primary_orientation_count=2,
    )

    config = _graph_backend_config_from_args(args, tool_radius_m=0.275)

    assert (
        config["algorithm_impact"]
        == "non_official_square8_axis_guided_graph_backend_plus_corridor_axis_atomic_strip_replacement"
    )
    assert "corridor-axis atomic strip" in str(config["official_difference"])

    cli_config = _graph_backend_cli_config_from_args(args)
    assert cli_config["corridor_axis_primary_orientation_count"] == 2
