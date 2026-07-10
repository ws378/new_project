import pytest

from maptools.models.annotations import Annotations


def test_area_label_room_id_is_canonical_name():
    annotations = Annotations()

    area = annotations.add_area_label(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
        name="old label",
        area_id=6,
    )

    assert area.room_id == 6
    assert area.name == "6"


def test_area_label_rejects_duplicate_room_id():
    annotations = Annotations()
    annotations.add_area_label(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
        area_id=6,
    )

    with pytest.raises(ValueError, match="duplicate room_id"):
        annotations.add_area_label(
            [(2.0, 0.0), (3.0, 0.0), (3.0, 1.0)],
            area_id=6,
        )
