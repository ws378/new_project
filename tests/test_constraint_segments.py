from pathlib import Path

from maptools.models.annotations import Annotations, DerivedConstraintRegion
from maptools.controllers.commands.annotation_command import AddAnnotationCommand
from maptools.utils.constraint_styles import constraint_base_color, constraint_visual_style


def test_constraint_segments_round_trip_preserves_legacy_views(tmp_path):
    annotations = Annotations()
    annotations.add_forbidden_zone([(0.0, 0.0), (2.0, 0.0), (2.0, 1.0)], item_id="fz-1")
    annotations.add_pass_only_zone([(3.0, 0.0), (4.0, 0.0), (4.0, 1.0)], item_id="po-1")
    annotations.add_virtual_wall((5.0, 0.0), (6.0, 1.0), item_id="vw-1")
    annotations.add_constraint_segment(
        [(7.0, 0.0), (8.0, 0.0), (8.0, 1.0)],
        closed=True,
        constraint_type="no_coverage",
        name="No Coverage",
        item_id="nc-1",
    )

    path = tmp_path / "annotations.json"
    annotations.save(str(path))

    restored = Annotations()
    restored.load(str(path))

    assert {segment.constraint_type for segment in restored.constraint_segments} == {
        "forbidden_zone",
        "pass_only",
        "virtual_wall",
        "no_coverage",
    }
    assert len(restored.forbidden_zones) == 1
    assert len(restored.pass_only_zones) == 1
    assert len(restored.virtual_walls) == 1
    assert restored.forbidden_zones[0].id == "fz-1"
    assert restored.pass_only_zones[0].id == "po-1"
    assert restored.virtual_walls[0].id == "vw-1"
    payload = restored.to_dict()
    assert "constraint_segments" in payload
    assert "forbidden_zones" not in payload
    assert "pass_only_zones" not in payload
    assert "virtual_walls" not in payload


def test_derived_constraint_regions_round_trip(tmp_path):
    annotations = Annotations()
    annotations.set_derived_constraint_regions(
        [
            DerivedConstraintRegion(
                id="free-space-forbidden-zone-3-4-4-3-abcd1234",
                name="Component 7 Forbidden Region",
                action_type="forbidden_zone",
                source="free_space_component",
                component_id=7,
                bbox_px=(3, 4, 4, 3),
                packed_mask_b64=annotations.encode_binary_mask_packbits(
                    [
                        [255, 255, 0, 0],
                        [0, 255, 255, 255],
                        [255, 255, 255, 255],
                    ]
                ),
                repair_radius_m=0.5,
                component_area_m2=1.25,
                metadata={"component_id": 7, "component_key": "3:4:4:3:abcd1234"},
            )
        ]
    )
    path = tmp_path / "annotations.json"
    annotations.save(str(path))

    restored = Annotations()
    restored.load(str(path))

    regions = list(restored.iter_derived_constraint_regions("forbidden_zone"))
    assert len(regions) == 1
    assert regions[0].id == "free-space-forbidden-zone-3-4-4-3-abcd1234"
    assert regions[0].component_id == 7
    assert regions[0].bbox_px == (3, 4, 4, 3)
    assert regions[0].metadata["component_key"] == "3:4:4:3:abcd1234"
    mask = restored.decode_derived_constraint_region_mask(regions[0])
    assert mask.shape == (3, 4)
    assert int(mask[0, 0]) == 255
    assert int(mask[1, 0]) == 0


def test_constraint_segments_migrate_from_legacy_payload(tmp_path):
    legacy_payload = {
        "version": "1.0",
        "forbidden_zones": [{"id": "fz", "name": "Forbidden", "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]}],
        "pass_only_zones": [{"id": "po", "name": "Pass", "polygon": [[2.0, 0.0], [3.0, 0.0], [3.0, 1.0]]}],
        "virtual_walls": [{"id": "vw", "name": "Wall", "start": [4.0, 0.0], "end": [5.0, 1.0]}],
        "stations": [],
        "area_labels": [],
        "_next_area_id": 1,
    }
    path = tmp_path / "legacy.json"
    path.write_text(__import__("json").dumps(legacy_payload), encoding="utf-8")

    annotations = Annotations()
    annotations.load(str(path))

    assert {segment.id for segment in annotations.constraint_segments} == {"fz", "po", "vw"}
    assert {segment.constraint_type for segment in annotations.constraint_segments} == {
        "forbidden_zone",
        "pass_only",
        "virtual_wall",
    }
    assert len(annotations.forbidden_zones) == 1
    assert len(annotations.pass_only_zones) == 1
    assert len(annotations.virtual_walls) == 1


def test_constraint_segment_edit_updates_legacy_views():
    annotations = Annotations()
    segment = annotations.add_constraint_segment(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
        closed=True,
        constraint_type="forbidden_zone",
        name="Forbidden",
        item_id="fz-edit",
    )

    segment.points = [(10.0, 10.0), (11.0, 10.0), (11.0, 11.0)]
    annotations.sync_constraint_views()

    assert annotations.forbidden_zones[0].polygon == [(10.0, 10.0), (11.0, 10.0), (11.0, 11.0)]


def test_analysis_change_stamp_ignores_no_coverage_and_electronic_fence_changes():
    annotations = Annotations()
    base_stamp = annotations.analysis_change_stamp

    annotations.add_constraint_segment(
        [(0.0, 0.0), (1.0, 0.0)],
        closed=False,
        constraint_type="electronic_fence",
        name="Fence",
        item_id="fence-1",
    )
    assert annotations.analysis_change_stamp == base_stamp

    annotations.add_constraint_segment(
        [(2.0, 0.0), (3.0, 0.0), (3.0, 1.0)],
        closed=True,
        constraint_type="no_coverage",
        name="NoCoverage",
        item_id="nc-1",
    )
    assert annotations.analysis_change_stamp == base_stamp


def test_analysis_change_stamp_tracks_forbidden_and_derived_forbidden_changes():
    annotations = Annotations()
    base_stamp = annotations.analysis_change_stamp

    annotations.add_forbidden_zone([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], item_id="fz-1")
    assert annotations.analysis_change_stamp == base_stamp + 1

    annotations.set_derived_constraint_regions(
        [
            DerivedConstraintRegion(
                id="derived-1",
                name="Derived Forbidden",
                action_type="forbidden_zone",
                source="free_space_component",
                component_id=1,
                bbox_px=(1, 1, 2, 2),
                row_spans=[[0, 2], [0, 2]],
                repair_radius_m=0.5,
                component_area_m2=1.0,
            )
        ]
    )
    assert annotations.analysis_change_stamp == base_stamp + 2


def test_constraint_style_source_matches_annotation_defaults():
    assert Annotations._default_constraint_color("forbidden_zone") == constraint_base_color("forbidden_zone")
    assert Annotations._default_constraint_color("no_coverage") == constraint_base_color("no_coverage")


def test_constraint_visual_styles_define_translucent_forbidden_and_no_coverage_regions():
    forbidden = constraint_visual_style("forbidden_zone")
    no_coverage = constraint_visual_style("no_coverage")

    assert forbidden.outline == "#ff4d4f"
    assert forbidden.fill == "#ff4d4f"
    assert forbidden.stipple == "gray25"
    assert forbidden.overlay_rgba[:3] == (255, 77, 79)

    assert no_coverage.outline == "#ff7a45"
    assert no_coverage.fill == "#ff7a45"
    assert no_coverage.stipple == "gray25"
    assert no_coverage.overlay_rgba[:3] == (255, 122, 69)


def test_add_annotation_command_writes_constraint_segments():
    annotations = Annotations()
    cmd = AddAnnotationCommand(annotations, "forbidden", [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)])

    cmd.execute()

    assert len(annotations.constraint_segments) == 1
    assert annotations.constraint_segments[0].constraint_type == "forbidden_zone"
    assert len(annotations.forbidden_zones) == 1
