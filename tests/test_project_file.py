from pathlib import Path
import json

from maptools.models.project import ProjectManager


class _MapDataStub:
    def __init__(self, yaml_path="/tmp/base/map.yaml"):
        self.yaml_path = yaml_path
        self.edit_layer = None
        self.grid_map = None
        self._display_dirty = False
        self._display_cache = None
        self.loaded_path = None
        self.metadata = None

    def load(self, path):
        self.loaded_path = path
        self.grid_map = [[0]]
        return True


class _AnnotationsStub:
    def __init__(self):
        self.saved_path = None
        self.loaded_path = None

    def save(self, path):
        self.saved_path = path
        Path(path).write_text("{}", encoding="utf-8")

    def load(self, path):
        self.loaded_path = path


def test_save_project_creates_mapproj_file(tmp_path):
    map_source_dir = tmp_path / "source_map"
    map_source_dir.mkdir(parents=True)
    (map_source_dir / "map.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
    yaml_path = map_source_dir / "map.yaml"
    yaml_path.write_text(
        "image: map.pgm\nresolution: 0.05\norigin: [0, 0, 0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.25\n",
        encoding="utf-8",
    )
    map_data = _MapDataStub(str(yaml_path))
    annotations = _AnnotationsStub()
    manager = ProjectManager(map_data, annotations)

    manager.save_project(str(tmp_path / "demo_project"))

    project_file = tmp_path / "demo_project" / "demo_project.mapproj"
    assert project_file.exists()
    payload = json.loads(project_file.read_text(encoding="utf-8"))
    assert payload["project_dir"] == "."
    assert (tmp_path / "demo_project" / "map.yaml").exists()
    assert (tmp_path / "demo_project" / "map.pgm").exists()
    metadata = json.loads((tmp_path / "demo_project" / "project.json").read_text(encoding="utf-8"))
    assert metadata["map_yaml_path"] == "map.yaml"


def test_load_project_file_delegates_to_project_directory(tmp_path):
    map_data = _MapDataStub()
    annotations = _AnnotationsStub()
    manager = ProjectManager(map_data, annotations)

    map_yaml = tmp_path / "map.yaml"
    map_yaml.write_text("image: map.pgm\nresolution: 0.05\norigin: [0,0,0]\n", encoding="utf-8")

    project_dir = tmp_path / "demo_project"
    project_dir.mkdir(parents=True)
    (project_dir / "project.json").write_text(
        f'{{"name":"demo_project","map_yaml_path":"{map_yaml}","version":"1.0"}}\n',
        encoding="utf-8",
    )
    (project_dir / "demo_project.mapproj").write_text(
        f'{{"project_dir":"{project_dir}"}}\n',
        encoding="utf-8",
    )

    assert manager.load_project_file(str(project_dir / "demo_project.mapproj")) is True
    assert manager.project_dir == str(project_dir)


def test_load_project_file_falls_back_when_absolute_project_dir_is_missing(tmp_path):
    map_data = _MapDataStub()
    annotations = _AnnotationsStub()
    manager = ProjectManager(map_data, annotations)

    project_dir = tmp_path / "portable_project"
    project_dir.mkdir(parents=True)
    (project_dir / "demo_map.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
    (project_dir / "demo_map.yaml").write_text(
        "image: demo_map.pgm\nresolution: 0.05\norigin: [0,0,0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.25\n",
        encoding="utf-8",
    )
    (project_dir / "project.json").write_text(
        '{"name":"portable_project","map_yaml_path":"demo_map.yaml","version":"1.0"}\n',
        encoding="utf-8",
    )
    (project_dir / "portable_project.mapproj").write_text(
        '{"format":"maptools-project","version":"1.0","project_dir":"/nonexistent/old/machine/project","project_json":"project.json"}\n',
        encoding="utf-8",
    )

    assert manager.load_project_file(str(project_dir / "portable_project.mapproj")) is True
    assert manager.project_dir == str(project_dir)
    assert Path(map_data.loaded_path).resolve() == (project_dir / "demo_map.yaml").resolve()


def test_load_project_resolves_relative_map_yaml_from_project_directory(tmp_path):
    map_data = _MapDataStub()
    annotations = _AnnotationsStub()
    manager = ProjectManager(map_data, annotations)

    project_dir = tmp_path / "demo_project"
    maps_dir = tmp_path / "maps"
    project_dir.mkdir(parents=True)
    maps_dir.mkdir(parents=True)
    map_yaml = maps_dir / "demo_map.yaml"
    map_yaml.write_text("image: demo_map.pgm\nresolution: 0.05\norigin: [0,0,0]\n", encoding="utf-8")
    (project_dir / "project.json").write_text(
        '{"name":"demo_project","map_yaml_path":"../maps/demo_map.yaml","version":"1.0"}\n',
        encoding="utf-8",
    )

    assert manager.load_project(str(project_dir)) is True
    assert Path(map_data.loaded_path).resolve() == map_yaml.resolve()


def test_save_project_uses_project_root_map_resource(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir(parents=True)
    (source_dir / "demo_map.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
    source_yaml = source_dir / "demo_map.yaml"
    source_yaml.write_text(
        "image: demo_map.pgm\nresolution: 0.05\norigin: [0,0,0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.25\n",
        encoding="utf-8",
    )

    map_data = _MapDataStub(str(source_yaml))
    annotations = _AnnotationsStub()
    manager = ProjectManager(map_data, annotations)
    project_dir = tmp_path / "demo_project"
    manager.save_project(str(project_dir))

    reopened_map = _MapDataStub()
    reopened_annotations = _AnnotationsStub()
    reopened_manager = ProjectManager(reopened_map, reopened_annotations)

    assert reopened_manager.load_project(str(project_dir)) is True
    assert Path(reopened_map.loaded_path).resolve() == (project_dir / "demo_map.yaml").resolve()


def test_load_project_fails_when_configured_map_yaml_is_missing(tmp_path):
    map_data = _MapDataStub()
    annotations = _AnnotationsStub()
    manager = ProjectManager(map_data, annotations)

    project_dir = tmp_path / "beiguoshangcheng_floor_3"
    project_dir.mkdir(parents=True)
    (project_dir / "beiguoshangcheng_floor_3.yaml").write_text(
        "image: beiguoshangcheng_floor_3.pgm\nresolution: 0.05\norigin: [0,0,0]\n",
        encoding="utf-8",
    )
    (project_dir / "project.json").write_text(
        '{"name":"beiguoshangcheng_floor_3","map_yaml_path":"missing_map.yaml","version":"1.0"}\n',
        encoding="utf-8",
    )

    assert manager.load_project(str(project_dir)) is False
    assert map_data.loaded_path is None


def test_save_project_reuses_existing_project_local_map_without_copy_error(tmp_path):
    project_dir = tmp_path / "portable_project"
    project_dir.mkdir(parents=True)
    (project_dir / "demo_map.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
    source_yaml = project_dir / "demo_map.yaml"
    source_yaml.write_text(
        "image: demo_map.pgm\nresolution: 0.05\norigin: [0,0,0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.25\n",
        encoding="utf-8",
    )

    map_data = _MapDataStub(str(source_yaml))
    annotations = _AnnotationsStub()
    manager = ProjectManager(map_data, annotations)

    manager.save_project(str(project_dir))

    assert (project_dir / "project.json").exists()
    assert (project_dir / "portable_project.mapproj").exists()
    metadata = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    assert metadata["map_yaml_path"] == "demo_map.yaml"
