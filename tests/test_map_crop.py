import numpy as np
from PIL import Image
import cv2

from maptools.controllers.command_manager import CommandManager
from maptools.models.annotations import Annotations
from maptools.models.map_data import MapData, MapMetadata, ROTATE_INTERPOLATION_MODES
from maptools.tools.crop_tool import CropTool
from maptools.views.main_window import MainWindow


def _build_map_data(width=10, height=8, resolution=0.5, origin=(1.0, 2.0, 0.0)):
    map_data = MapData()
    map_data.metadata = MapMetadata(
        image_path="map.pgm",
        resolution=resolution,
        origin=origin,
        negate=0,
        occupied_thresh=0.65,
        free_thresh=0.25,
    )
    grid = np.arange(width * height, dtype=np.uint8).reshape((height, width))
    map_data.grid_map = grid.copy()
    map_data.base_image = Image.fromarray(grid.copy())
    map_data.edit_layer = np.full_like(grid, 255)
    map_data.width = width
    map_data.height = height
    return map_data


def test_map_data_crop_updates_size_origin_and_pixels():
    map_data = _build_map_data()

    ok = map_data.crop(2, 1, 7, 6)

    assert ok is True
    assert (map_data.width, map_data.height) == (5, 5)
    assert map_data.metadata.origin == (2.0, 3.0, 0.0)
    assert map_data.grid_map.shape == (5, 5)
    np.testing.assert_array_equal(map_data.grid_map, np.arange(80, dtype=np.uint8).reshape((8, 10))[1:6, 2:7])


def test_annotations_crop_clips_and_filters_items():
    annotations = Annotations()
    forbidden = annotations.add_forbidden_zone([(-1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (-1.0, 3.0)])
    pass_only = annotations.add_pass_only_zone([(0.5, 0.5), (1.5, 0.5), (1.5, 3.5), (0.5, 3.5)])
    wall = annotations.add_virtual_wall((-1.0, 1.0), (3.0, 1.0))
    kept_station = annotations.add_station((1.0, 1.0), 0.0)
    annotations.add_station((5.0, 5.0), 0.0, name="Outside")
    area = annotations.add_area_label([(-2.0, -2.0), (2.0, -2.0), (2.0, 2.0), (-2.0, 2.0)], area_id=7)

    annotations.crop_to_bounds(0.0, 2.0, 0.0, 2.0)

    assert len(annotations.forbidden_zones) == 1
    assert all(0.0 <= x <= 2.0 and 0.0 <= y <= 2.0 for x, y in forbidden.polygon)
    assert len(annotations.pass_only_zones) == 1
    assert all(0.0 <= x <= 2.0 and 0.0 <= y <= 2.0 for x, y in pass_only.polygon)
    assert len(annotations.virtual_walls) == 1
    assert wall.start == (0.0, 1.0)
    assert wall.end == (2.0, 1.0)
    assert [station.name for station in annotations.stations] == [kept_station.name]
    assert len(annotations.area_labels) == 1
    assert area.area_id == 7
    assert all(0.0 <= x <= 2.0 and 0.0 <= y <= 2.0 for x, y in area.polygon)


def test_crop_map_to_pixels_records_undo_and_redo(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    window.map_data = _build_map_data(width=10, height=10, resolution=1.0, origin=(0.0, 0.0, 0.0))
    window.annotations = Annotations()
    window.annotations.add_forbidden_zone([(-1.0, 1.0), (4.0, 1.0), (4.0, 4.0), (-1.0, 4.0)])
    window.annotations.add_pass_only_zone([(6.0, 6.0), (8.0, 6.0), (8.0, 8.0), (6.0, 8.0)])
    window.annotations.add_virtual_wall((-2.0, 4.0), (7.0, 4.0))
    window.annotations.add_station((3.0, 3.0), 0.0, name="Kept")
    window.annotations.add_station((9.5, 9.5), 0.0, name="Dropped")
    window.command_manager = CommandManager()
    window.canvas = type("CanvasStub", (), {"refresh": lambda self: None})()
    status_updates = []
    window.statusbar = type("StatusStub", (), {"config": lambda self, text: status_updates.append(text)})()

    class _DialogStub:
        def __init__(self, parent, width_px, height_px, title="Crop Map"):
            self.confirmed = True

    monkeypatch.setattr("maptools.views.main_window.CropInfoDialog", _DialogStub)

    window.crop_map_to_pixels(1, 2, 6, 7)

    assert (window.map_data.width, window.map_data.height) == (5, 5)
    assert window.map_data.metadata.origin == (1.0, 3.0, 0.0)
    assert len(window.annotations.forbidden_zones) == 1
    assert len(window.annotations.pass_only_zones) == 0
    assert len(window.annotations.virtual_walls) == 1
    assert len(window.annotations.stations) == 1
    assert window.command_manager.can_undo() is True

    window.command_manager.undo()
    assert (window.map_data.width, window.map_data.height) == (10, 10)
    assert window.map_data.metadata.origin == (0.0, 0.0, 0.0)
    assert len(window.annotations.pass_only_zones) == 1
    assert len(window.annotations.stations) == 2

    window.command_manager.redo()
    assert (window.map_data.width, window.map_data.height) == (5, 5)
    assert window.map_data.metadata.origin == (1.0, 3.0, 0.0)
    assert status_updates[-1] == "Cropped map to 5 x 5"


def test_map_rotate_uses_requested_interpolation(monkeypatch):
    map_data = _build_map_data(width=6, height=6, resolution=1.0, origin=(0.0, 0.0, 0.0))
    calls = []
    original_warp_affine = cv2.warpAffine

    def _recording_warp_affine(src, matrix, dsize, **kwargs):
        calls.append(kwargs.get("flags"))
        return original_warp_affine(src, matrix, dsize, **kwargs)

    monkeypatch.setattr("maptools.models.map_data.cv2.warpAffine", _recording_warp_affine)

    map_data.rotate(15.0, interpolation_mode="smooth")

    assert calls[0] == ROTATE_INTERPOLATION_MODES["smooth"]
    assert calls[1] == cv2.INTER_NEAREST


def test_crop_tool_enter_applies_current_rect_and_switches_tool():
    calls = []

    class _CanvasStub:
        def __init__(self):
            self.map_data = type("MapStub", (), {"width": 20, "height": 15})()
            self.zoom_level = 1.0
            self.pan_offset_x = 0
            self.pan_offset_y = 0

        def focus_set(self):
            pass

        def delete(self, tag):
            pass

        def config(self, **kwargs):
            pass

        def image_to_canvas(self, px, py):
            return px, py

    class _ToolManagerStub:
        def set_tool(self, name):
            calls.append(("set_tool", name))

    class _ControllerStub:
        def __init__(self):
            self.tool_manager = _ToolManagerStub()

        def crop_map_to_pixels(self, x0, y0, x1, y1):
            calls.append(("crop", x0, y0, x1, y1))
            return True

    tool = CropTool(_CanvasStub(), _ControllerStub())
    tool.rect_px = (2, 3, 8, 9)

    tool.on_key_press(type("Event", (), {"keysym": "Return"}))

    assert calls == [("crop", 2, 3, 8, 9), ("set_tool", "pan")]


def test_crop_tool_enter_keeps_mode_when_crop_cancelled():
    calls = []

    class _CanvasStub:
        def __init__(self):
            self.map_data = type("MapStub", (), {"width": 20, "height": 15})()
            self.zoom_level = 1.0
            self.pan_offset_x = 0
            self.pan_offset_y = 0

        def focus_set(self):
            pass

        def delete(self, tag):
            pass

        def config(self, **kwargs):
            pass

        def image_to_canvas(self, px, py):
            return px, py

    class _ToolManagerStub:
        def set_tool(self, name):
            calls.append(("set_tool", name))

    class _ControllerStub:
        def __init__(self):
            self.tool_manager = _ToolManagerStub()

        def crop_map_to_pixels(self, x0, y0, x1, y1):
            calls.append(("crop", x0, y0, x1, y1))
            return False

    tool = CropTool(_CanvasStub(), _ControllerStub())
    tool.rect_px = (2, 3, 8, 9)

    tool.on_key_press(type("Event", (), {"keysym": "Return"}))

    assert calls == [("crop", 2, 3, 8, 9)]
