from pathlib import Path

import numpy as np
from PIL import Image

from maptools.models.annotations import Annotations, DerivedConstraintRegion
from maptools.models.map_data import MapData, MapMetadata
from maptools.utils.free_space_components import (
    analyze_free_space_components,
    build_obstacle_semantic_mask,
    derive_repair_kernel_px,
    repair_obstacle_connectivity,
)


def _make_map_data(grid: np.ndarray, *, resolution: float = 0.5) -> MapData:
    map_data = MapData()
    map_data.metadata = MapMetadata(
        image_path="demo.pgm",
        resolution=resolution,
        origin=(0.0, 0.0, 0.0),
        negate=0,
        occupied_thresh=0.65,
        free_thresh=0.25,
        mode="trinary",
    )
    map_data.base_image = Image.fromarray(grid)
    map_data.grid_map = grid.copy()
    map_data.edit_layer = np.full_like(grid, 255, dtype=np.uint8)
    map_data.yaml_path = str(Path("/tmp/demo.yaml"))
    map_data.width = int(grid.shape[1])
    map_data.height = int(grid.shape[0])
    return map_data


def test_build_obstacle_semantic_mask_treats_unknown_forbidden_and_virtual_wall_as_obstacle():
    grid = np.full((8, 8), 254, dtype=np.uint8)
    grid[0, 0] = 205
    map_data = _make_map_data(grid)
    annotations = Annotations()
    annotations.add_constraint_segment(
        [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)],
        closed=True,
        constraint_type="forbidden_zone",
        name="Forbidden",
    )
    annotations.add_constraint_segment(
        [(0.0, 3.0), (3.0, 3.0)],
        closed=False,
        constraint_type="virtual_wall",
        name="Wall",
    )

    obstacle = build_obstacle_semantic_mask(map_data, annotations)

    assert obstacle[0, 0] == 255
    assert np.count_nonzero(obstacle == 255) > 1


def test_build_obstacle_semantic_mask_does_not_treat_no_coverage_as_obstacle():
    grid = np.full((8, 8), 254, dtype=np.uint8)
    map_data = _make_map_data(grid)
    annotations = Annotations()
    annotations.add_constraint_segment(
        [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)],
        closed=True,
        constraint_type="no_coverage",
        name="NoCoverage",
    )

    obstacle = build_obstacle_semantic_mask(map_data, annotations)

    assert obstacle[5, 1] == 0


def test_build_obstacle_semantic_mask_treats_derived_forbidden_region_as_obstacle():
    grid = np.full((8, 8), 254, dtype=np.uint8)
    map_data = _make_map_data(grid)
    annotations = Annotations()
    annotations.set_derived_constraint_regions(
        [
            DerivedConstraintRegion(
                id="derived-1",
                name="Component Forbidden",
                action_type="forbidden_zone",
                source="free_space_component",
                component_id=1,
                bbox_px=(1, 1, 3, 3),
                row_spans=[[0, 3], [0, 3], [0, 3]],
                repair_radius_m=0.5,
                component_area_m2=2.25,
                metadata={},
            )
        ]
    )
    obstacle = build_obstacle_semantic_mask(map_data, annotations)

    assert np.all(obstacle[1:4, 1:4] == 255)


def test_repair_obstacle_connectivity_uses_metric_radius():
    obstacle = np.zeros((7, 7), dtype=np.uint8)
    obstacle[:, 2] = 255
    obstacle[:, 4] = 255
    repaired, kernel_px = repair_obstacle_connectivity(
        obstacle,
        repair_radius_m=0.5,
        resolution_m_per_px=0.5,
    )

    assert kernel_px == derive_repair_kernel_px(0.5, 0.5) == 1
    assert repaired[:, 3].max() == 255


def test_analyze_free_space_components_splits_regions_by_virtual_wall():
    grid = np.full((20, 20), 254, dtype=np.uint8)
    map_data = _make_map_data(grid, resolution=0.5)
    annotations = Annotations()
    annotations.add_constraint_segment(
        [(5.0, 0.5), (5.0, 9.5)],
        closed=False,
        constraint_type="virtual_wall",
        name="SplitWall",
    )

    result = analyze_free_space_components(map_data, annotations, repair_radius_m=0.0)

    assert result.total_component_count == 2
    assert len(result.component_stats) == 2
    assert result.component_labels.shape == (20, 20)
    assert result.component_color_lut.shape[1] == 4
    active_colors = {
        tuple(int(v) for v in result.component_color_lut[int(component_id), :3])
        for component_id in result.component_stats
    }
    assert active_colors == {(144, 238, 144)}
    assert all(stat.pixel_count > 0 for stat in result.component_stats.values())


def test_analyze_free_space_components_marks_small_candidates_by_area_threshold():
    grid = np.zeros((12, 12), dtype=np.uint8)
    grid[1:4, 1:4] = 254
    grid[7:11, 7:11] = 254
    map_data = _make_map_data(grid, resolution=0.5)
    annotations = Annotations()

    result = analyze_free_space_components(
        map_data,
        annotations,
        repair_radius_m=0.0,
        small_component_threshold_m2=3.0,
    )

    assert result.total_component_count == 2
    suggested = {stat.component_id for stat in result.component_stats.values() if stat.suggested_no_coverage}
    assert len(suggested) == 1
