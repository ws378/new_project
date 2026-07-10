import yaml
import numpy as np
from PIL import Image

from maptools.models.annotations import Annotations
from maptools.models.map_data import MapData, MapMetadata
from maptools.utils.export import Exporter


def _make_map_data(grid: np.ndarray) -> MapData:
    map_data = MapData()
    map_data.metadata = MapMetadata(
        image_path="demo.pgm",
        resolution=0.05,
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


def test_forbidden_yaml_uses_unknown_background_threshold(tmp_path):
    map_data = _make_map_data(np.full((4, 4), 254, dtype=np.uint8))
    annotations = Annotations()

    Exporter(map_data, annotations).export(str(tmp_path))

    with open(tmp_path / "map.yaml", "r", encoding="utf-8") as f:
        map_yaml = yaml.safe_load(f)
    with open(tmp_path / "map_forbidden.yaml", "r", encoding="utf-8") as f:
        forbidden_yaml = yaml.safe_load(f)

    assert map_yaml["free_thresh"] == 0.25
    assert forbidden_yaml["free_thresh"] == 0.0
