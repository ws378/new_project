from __future__ import annotations

from typing import Iterable, Sequence


def area_room_id(area) -> int:
    """Return the canonical room_id for an AreaLabel-like object."""

    return int(getattr(area, "area_id"))


def path_node_room_id(node) -> int:
    """Return the canonical room_id for a CoveragePathNode-like object."""

    return int(getattr(node, "room"))


def canonical_room_name(room_id: int) -> str:
    return str(int(room_id))


def set_area_room_id(area, room_id: int) -> None:
    room_id = validate_room_id(room_id)
    area.area_id = room_id
    area.name = canonical_room_name(room_id)


def set_path_node_room_id(node, room_id: int) -> None:
    node.room = validate_room_id(room_id)


def validate_room_id(room_id: int) -> int:
    try:
        value = int(room_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"room_id must be an integer: {room_id!r}") from exc
    if value <= 0:
        raise ValueError(f"room_id must be positive: {value}")
    return value


def normalize_area_room_identity(area) -> None:
    room_id = validate_room_id(area_room_id(area))
    area.name = canonical_room_name(room_id)


def validate_unique_area_room_ids(areas: Sequence, *, exclude_area_id: str | None = None) -> None:
    seen: dict[int, str] = {}
    for area in areas:
        if exclude_area_id is not None and str(getattr(area, "id", "")) == str(exclude_area_id):
            continue
        room_id = validate_room_id(area_room_id(area))
        area_id = str(getattr(area, "id", ""))
        if room_id in seen:
            raise ValueError(f"duplicate room_id: {room_id}")
        seen[room_id] = area_id


def normalize_and_validate_area_room_ids(areas: Sequence) -> None:
    validate_unique_area_room_ids(areas)
    for area in areas:
        normalize_area_room_identity(area)


def valid_area_room_ids(areas: Iterable) -> set[int]:
    return {area_room_id(area) for area in areas}
