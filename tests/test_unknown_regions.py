import numpy as np
from PIL import Image

from maptools.models.annotations import Annotations, DerivedConstraintRegion
from maptools.models.map_data import MapData, MapMetadata
from maptools.utils.export import Exporter
from maptools.utils.unknown_regions import (
    analyze_unknown_regions,
    build_unknown_forbidden_regions,
    compact_unknown_forbidden_regions,
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
    map_data.width = int(grid.shape[1])
    map_data.height = int(grid.shape[0])
    return map_data


def test_analyze_unknown_regions_uses_display_image_with_edit_layer():
    grid = np.full((8, 8), 254, dtype=np.uint8)
    grid[1:3, 1:3] = 205
    map_data = _make_map_data(grid, resolution=0.5)
    map_data.edit_layer[5:7, 5:7] = 205

    result = analyze_unknown_regions(map_data)

    assert result.total_component_count == 2
    assert result.total_pixel_count == 8
    assert result.total_area_m2 == 2.0
    assert {stat.pixel_count for stat in result.component_stats.values()} == {4}


def test_build_unknown_forbidden_regions_packs_component_masks():
    grid = np.full((8, 8), 254, dtype=np.uint8)
    grid[1:3, 1:3] = 205
    annotations = Annotations()
    result = analyze_unknown_regions(_make_map_data(grid, resolution=0.5))

    regions = build_unknown_forbidden_regions(annotations, result)

    assert len(regions) == 1
    region = regions[0]
    assert region.action_type == "forbidden_zone"
    assert region.source == "unknown_region"
    assert region.metadata["source"] == "unknown_region"
    assert region.metadata["pixel_value"] == 205
    mask = annotations.decode_derived_constraint_region_mask(region)
    assert mask.shape == (2, 2)
    assert np.all(mask == 255)


def test_unknown_forbidden_regions_export_to_forbidden_layer(tmp_path):
    grid = np.full((6, 6), 254, dtype=np.uint8)
    grid[2:4, 1:3] = 205
    map_data = _make_map_data(grid, resolution=0.5)
    annotations = Annotations()
    result = analyze_unknown_regions(map_data)
    annotations.set_derived_constraint_regions(build_unknown_forbidden_regions(annotations, result))

    Exporter(map_data, annotations).export(str(tmp_path))

    forbidden = np.asarray(Image.open(tmp_path / "map_forbidden.pgm"))
    assert np.all(forbidden[2:4, 1:3] == 0)
    assert forbidden[0, 0] == 254


def test_compact_unknown_forbidden_regions_merges_historical_component_regions():
    annotations = Annotations()
    mask_a = np.ones((2, 2), dtype=np.uint8) * 255
    mask_b = np.ones((2, 3), dtype=np.uint8) * 255
    manual_mask = np.ones((1, 1), dtype=np.uint8) * 255
    annotations.set_derived_constraint_regions(
        [
            DerivedConstraintRegion(
                id="unknown-a",
                name="Unknown A",
                action_type="forbidden_zone",
                source="unknown_region",
                component_id=1,
                bbox_px=(1, 1, 2, 2),
                packed_mask_b64=annotations.encode_binary_mask_packbits(mask_a),
                component_area_m2=1.0,
                metadata={"source": "unknown_region"},
            ),
            DerivedConstraintRegion(
                id="unknown-b",
                name="Unknown B",
                action_type="forbidden_zone",
                source="unknown_region",
                component_id=2,
                bbox_px=(5, 4, 3, 2),
                packed_mask_b64=annotations.encode_binary_mask_packbits(mask_b),
                component_area_m2=1.5,
                metadata={"source": "unknown_region"},
            ),
            DerivedConstraintRegion(
                id="manual-derived",
                name="Manual Derived",
                action_type="forbidden_zone",
                source="free_space_component",
                component_id=3,
                bbox_px=(0, 0, 1, 1),
                packed_mask_b64=annotations.encode_binary_mask_packbits(manual_mask),
                component_area_m2=0.25,
                metadata={"source": "free_space_component"},
            ),
        ]
    )

    removed = compact_unknown_forbidden_regions(annotations)

    assert removed == 1
    regions = list(annotations.iter_derived_constraint_regions("forbidden_zone"))
    unknown = [region for region in regions if region.source == "unknown_region"]
    manual = [region for region in regions if region.id == "manual-derived"]
    assert len(unknown) == 1
    assert len(manual) == 1
    assert unknown[0].bbox_px == (1, 1, 7, 5)
    assert unknown[0].component_area_m2 == 2.5
    assert unknown[0].metadata["compacted_region_count"] == 2
    merged = annotations.decode_derived_constraint_region_mask(unknown[0])
    assert np.all(merged[0:2, 0:2] == 255)
    assert np.all(merged[3:5, 4:7] == 255)
