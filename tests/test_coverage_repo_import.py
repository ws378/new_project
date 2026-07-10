from pathlib import Path

from maptools.models.annotations import Annotations
from maptools.models.coverage_path import CoveragePathManager
from maptools.models.map_data import MapData
from maptools.utils.coverage_repo_import import (
    _candidate_map_paths,
    _ensure_matching_map_loaded,
    detect_yaml_kind,
    import_area_labels_json,
    import_coverage_repo,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_BASE_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "coverage_repos" / "output_base"
OUTPUT_BASE_COVERAGE = OUTPUT_BASE_FIXTURE / "beiguo_lanshan_1770397756" / "coverage_path_master.yaml"
OUTPUT_BASE_AREAS = OUTPUT_BASE_FIXTURE / "areas.json"


def _write_short_coverage_repo(tmp_path: Path) -> Path:
    output_root = tmp_path / "output_short_path"
    repo_dir = output_root / "demo_map"
    repo_dir.mkdir(parents=True)
    (output_root / "demo_map.pgm").write_bytes(
        b"P5\n20 20\n255\n" + bytes([255]) * 400
    )
    (output_root / "demo_map.yaml").write_text(
        "image: demo_map.pgm\nmode: trinary\nresolution: 0.05\norigin: [0.0, 0.0, 0.0]\nnegate: 0\noccupied_thresh: 0.3\nfree_thresh: 0.1\n",
        encoding="utf-8",
    )
    poses = "\n".join(
        [
            f"    - x: {idx * 0.05:.2f}\n      y: 0.0\n      theta: 0.0"
            for idx in range(17)
        ]
    )
    coverage_yaml = repo_dir / "coverage_path_master.yaml"
    coverage_yaml.write_text(
        "map_id: demo_map\n"
        "paths:\n"
        "- room_id: 6\n"
        "  segments:\n"
        "  - segment_id: 0\n"
        "    start_index: 0\n"
        "    end_index: 16\n"
        "  poses:\n"
        f"{poses}\n",
        encoding="utf-8",
    )
    return coverage_yaml


def test_detect_yaml_kind_for_coverage_repo():
    assert detect_yaml_kind(str(OUTPUT_BASE_COVERAGE)) == "coverage_repo"


def test_import_coverage_repo_auto_loads_map_and_partition():
    map_data = MapData()
    annotations = Annotations()
    manager = CoveragePathManager()

    result = import_coverage_repo(str(OUTPUT_BASE_COVERAGE), map_data, manager, annotations)

    assert result.map_id == "beiguo_lanshan_1770397756"
    assert result.imported_rooms == 2
    assert result.imported_nodes == len(manager.nodes)
    assert result.imported_nodes > 1000
    assert result.imported_area_labels == len(annotations.area_labels)
    assert result.imported_area_labels == 2
    assert Path(result.loaded_map_path).name == "map.yaml"
    assert Path(map_data.yaml_path).name == "map.yaml"

    first = manager.nodes[0]
    assert first.room == 6
    assert abs(first.x - 5.190684204101563) < 1e-6
    assert abs(first.y - (-0.4531494140624943)) < 1e-6
    assert abs(first.yaw - (-0.7417665050435664)) < 1e-6


def test_import_coverage_repo_preserves_segment_ranges(tmp_path):
    map_data = MapData()
    annotations = Annotations()
    manager = CoveragePathManager()
    coverage_yaml = _write_short_coverage_repo(tmp_path)

    result = import_coverage_repo(str(coverage_yaml), map_data, manager, annotations)

    assert result.imported_segments == 1
    assert len(manager.nodes) == 17
    assert {node.segment for node in manager.nodes} == {0}
    assert all(node.room == 6 for node in manager.nodes)
    assert manager.nodes[-1].id == len(manager.nodes) - 1


def test_import_area_labels_json_loads_project_areas():
    annotations = Annotations()

    count = import_area_labels_json(str(OUTPUT_BASE_AREAS), annotations)

    assert count == 2
    assert len(annotations.area_labels) == 2
    assert {area.area_id for area in annotations.area_labels} == {6, 7}
    assert annotations.area_labels[0].name == "6"


def test_import_coverage_repo_does_not_override_existing_area_labels():
    map_data = MapData()
    annotations = Annotations()
    manager = CoveragePathManager()

    import_area_labels_json(str(OUTPUT_BASE_AREAS), annotations)
    original_polygons = {area.area_id: list(area.polygon) for area in annotations.area_labels}

    result = import_coverage_repo(
        str(OUTPUT_BASE_COVERAGE),
        map_data,
        manager,
        annotations,
        restore_area_labels=False,
    )

    assert result.imported_area_labels == 0
    assert len(annotations.area_labels) == 2
    assert {area.area_id: list(area.polygon) for area in annotations.area_labels} == original_polygons


def test_candidate_map_paths_prioritize_map_id_named_files_before_map_yaml(tmp_path):
    map_id = "demo_map"
    output_root = tmp_path / "output_base"
    repo_dir = output_root / map_id
    repo_dir.mkdir(parents=True)
    coverage_yaml = repo_dir / "coverage_path_master.yaml"
    coverage_yaml.write_text("map_id: demo_map\npaths: []\n", encoding="utf-8")

    candidates = _candidate_map_paths(coverage_yaml, map_id)
    map_id_yaml = (output_root / f"{map_id}.yaml").resolve()
    map_yaml = (output_root / "map.yaml").resolve()

    assert map_id_yaml in candidates
    assert map_yaml in candidates
    assert candidates.index(map_id_yaml) < candidates.index(map_yaml)


def test_ensure_matching_map_loaded_falls_back_to_map_yaml(tmp_path):
    map_id = "demo_map"
    output_root = tmp_path / "output_base"
    repo_dir = output_root / map_id
    repo_dir.mkdir(parents=True)
    coverage_yaml = repo_dir / "coverage_path_master.yaml"
    coverage_yaml.write_text("map_id: demo_map\npaths: []\n", encoding="utf-8")

    fallback_map_yaml = output_root / "map.yaml"
    fallback_map_yaml.write_text(
        "image: map.pgm\nresolution: 0.05\norigin: [0.0, 0.0, 0.0]\n",
        encoding="utf-8",
    )

    map_data = MapData()
    loaded_paths = []

    def _fake_load(path):
        loaded_paths.append(Path(path).resolve())
        return True

    map_data.load = _fake_load

    loaded = _ensure_matching_map_loaded(coverage_yaml, map_id, map_data)

    assert Path(loaded).resolve() == fallback_map_yaml.resolve()
    assert loaded_paths == [fallback_map_yaml.resolve()]


def test_candidate_map_paths_reads_project_json_next_to_coverage_repo(tmp_path):
    map_id = "beiguoshangcheng_floor_3"
    project_dir = tmp_path / map_id
    repo_dir = project_dir / "coverage_repo" / map_id
    map_yaml = project_dir / "beiguoshangcheng_floor_3.yaml"
    repo_dir.mkdir(parents=True)
    coverage_yaml = repo_dir / "coverage_path_master.yaml"
    coverage_yaml.write_text(f"map_id: {map_id}\npaths: []\n", encoding="utf-8")
    (project_dir / "project.json").write_text(
        '{"name":"beiguoshangcheng_floor_3","map_yaml_path":"beiguoshangcheng_floor_3.yaml","version":"1.0"}\n',
        encoding="utf-8",
    )

    candidates = _candidate_map_paths(coverage_yaml, map_id)

    assert map_yaml.resolve() in candidates
