from types import SimpleNamespace

from maptools.tools.path_tools import _infer_room_from_sampled_world_points


def test_infer_room_from_sampled_world_points_uses_area_when_fallback_is_zero():
    canvas = SimpleNamespace(
        annotations=SimpleNamespace(
            area_labels=[
                SimpleNamespace(
                    area_id=2,
                    polygon=[
                        (0.0, 0.0),
                        (10.0, 0.0),
                        (10.0, 10.0),
                        (0.0, 10.0),
                    ],
                )
            ]
        )
    )

    room = _infer_room_from_sampled_world_points(
        canvas,
        sampled_world=[(2.0, 2.0), (5.0, 5.0), (8.0, 8.0)],
        fallback_room=0,
    )

    assert room == 2


def test_infer_room_from_sampled_world_points_uses_valid_manual_room_when_no_area_hit():
    canvas = SimpleNamespace(
        selected_type=None,
        selected_item=None,
        annotations=SimpleNamespace(area_labels=[SimpleNamespace(area_id=7, polygon=[])]),
    )

    room = _infer_room_from_sampled_world_points(
        canvas,
        sampled_world=[(2.0, 2.0)],
        fallback_room=7,
    )

    assert room == 7


def test_infer_room_from_sampled_world_points_prefers_geometry_over_manual_room():
    canvas = SimpleNamespace(
        selected_type=None,
        selected_item=None,
        annotations=SimpleNamespace(
            area_labels=[
                SimpleNamespace(
                    area_id=2,
                    polygon=[
                        (0.0, 0.0),
                        (10.0, 0.0),
                        (10.0, 10.0),
                        (0.0, 10.0),
                    ],
                ),
                SimpleNamespace(area_id=7, polygon=[]),
            ]
        ),
    )

    room = _infer_room_from_sampled_world_points(
        canvas,
        sampled_world=[(2.0, 2.0), (5.0, 5.0)],
        fallback_room=7,
    )

    assert room == 2
