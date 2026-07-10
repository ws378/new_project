import numpy as np

from algorithms.coverage_planning.contracts import CoveragePlanningRequest
from algorithms.coverage_planning.preprocessing import (
    apply_region_constraint,
    build_region_mask_from_polygon,
    derive_min_free_component_area_m2,
    derive_min_free_component_area_px,
    nearest_free_pixel,
    preprocess_total_map,
    resolve_request_starting_position,
    resolve_request_region_mask,
)


def test_derive_min_free_component_area_uses_single_kernel_rule():
    assert derive_min_free_component_area_m2(0.6) == 1.44
    assert derive_min_free_component_area_px(open_kernel_m=0.6, resolution_m_per_px=0.1) == 144


def test_build_region_mask_from_polygon_rasterizes_full_image_mask():
    mask = build_region_mask_from_polygon(
        shape=(20, 30),
        polygon_px=((5, 4), (15, 4), (15, 10), (5, 10)),
    )

    assert mask.shape == (20, 30)
    assert int(mask[6, 6]) == 255
    assert int(mask[0, 0]) == 0


def test_resolve_request_region_mask_prefers_explicit_mask():
    prepared_map = np.zeros((20, 30), dtype=np.uint8)
    explicit_mask = np.zeros((20, 30), dtype=np.uint8)
    explicit_mask[7:9, 8:10] = 255
    request = CoveragePlanningRequest(
        prepared_map=prepared_map,
        map_resolution=0.05,
        starting_position_px=(5, 5),
        region_mask=explicit_mask,
        region_polygon_px=((0, 0), (29, 0), (29, 19), (0, 19)),
    )

    resolved = resolve_request_region_mask(request)

    assert int(np.count_nonzero(resolved)) == 4


def test_apply_region_constraint_masks_prepared_map():
    prepared_map = np.zeros((10, 10), dtype=np.uint8)
    prepared_map[2:8, 2:8] = 255
    region_mask = np.zeros((10, 10), dtype=np.uint8)
    region_mask[4:6, 4:6] = 255

    effective = apply_region_constraint(prepared_map, region_mask)

    assert int(np.count_nonzero(effective)) == 4
    assert int(effective[4, 4]) == 255
    assert int(effective[2, 2]) == 0


def test_nearest_free_pixel_keeps_valid_start():
    mask = np.zeros((10, 10), dtype=np.uint8)
    mask[4, 5] = 255

    assert nearest_free_pixel(mask, (5, 4)) == (5, 4)


def test_nearest_free_pixel_snaps_invalid_start_to_closest_free_pixel():
    mask = np.zeros((10, 10), dtype=np.uint8)
    mask[2, 7] = 255
    mask[8, 1] = 255

    assert nearest_free_pixel(mask, (6, 2)) == (7, 2)


def test_resolve_request_starting_position_uses_effective_region_mask():
    prepared_map = np.zeros((12, 12), dtype=np.uint8)
    prepared_map[2:10, 2:10] = 255
    region_mask = np.zeros((12, 12), dtype=np.uint8)
    region_mask[8:10, 8:10] = 255
    request = CoveragePlanningRequest(
        prepared_map=prepared_map,
        map_resolution=0.05,
        starting_position_px=(4, 4),
        region_mask=region_mask,
    )

    start, snapped = resolve_request_starting_position(request)

    assert snapped
    assert start in {(8, 8), (9, 8), (8, 9), (9, 9)}


def test_preprocess_total_map_removes_tiny_island_after_open():
    raw_map = np.zeros((40, 40), dtype=np.uint8)
    raw_map[10:30, 10:30] = 255
    raw_map[2:4, 2:4] = 255

    prepared = preprocess_total_map(
        raw_map=raw_map,
        resolution_m_per_px=0.1,
        open_kernel_m=0.2,
        obstacle_expand_m=0.2,
    )

    assert int(prepared[15, 15]) == 255
    assert int(np.count_nonzero(prepared[2:4, 2:4])) == 0


def test_preprocess_total_map_obstacle_expand_shrinks_free_band():
    raw_map = np.zeros((20, 20), dtype=np.uint8)
    raw_map[5:15, 9:11] = 255

    prepared = preprocess_total_map(
        raw_map=raw_map,
        resolution_m_per_px=0.1,
        open_kernel_m=0.2,
        obstacle_expand_m=0.2,
    )

    assert int(np.count_nonzero(prepared[:, 9:11])) == 0


def test_preprocess_total_map_applies_region_mask_before_morphology():
    raw_map = np.full((20, 20), 255, dtype=np.uint8)
    region_mask = np.zeros((20, 20), dtype=np.uint8)
    region_mask[5:15, 5:15] = 255

    prepared = preprocess_total_map(
        raw_map=raw_map,
        region_mask=region_mask,
        resolution_m_per_px=0.1,
        open_kernel_m=0.1,
        obstacle_expand_m=0.1,
    )

    assert int(prepared[10, 10]) == 255
    assert int(prepared[4, 10]) == 0
    assert int(prepared[10, 4]) == 0


def test_preprocess_total_map_writes_prepare_map_stage_images(tmp_path):
    raw_map = np.zeros((20, 20), dtype=np.uint8)
    raw_map[5:15, 5:15] = 255

    preprocess_total_map(
        raw_map=raw_map,
        resolution_m_per_px=0.1,
        open_kernel_m=0.2,
        obstacle_expand_m=0.2,
        output_root=tmp_path,
    )

    prepare_map_dir = tmp_path / "prepare_map"
    assert (prepare_map_dir / "01_raw_map.png").exists()
    assert (prepare_map_dir / "02_free_mask.png").exists()
    assert (prepare_map_dir / "03_after_open.png").exists()
    assert (prepare_map_dir / "04_after_obstacle_expand.png").exists()
    assert (prepare_map_dir / "05_prepared_map.png").exists()
