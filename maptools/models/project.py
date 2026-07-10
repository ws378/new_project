import os
import json
import numpy as np
import shutil
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
import yaml
from .map_data import MapData
from .annotations import Annotations

@dataclass
class ProjectMetadata:
    name: str
    map_yaml_path: str
    version: str = "1.0"

class ProjectManager:
    PROJECT_FILE_EXT = ".mapproj"

    def __init__(self, map_data: MapData, annotations: Annotations):
        self.map_data = map_data
        self.annotations = annotations
        self.project_dir = None

    def _project_file_path(self, directory: str) -> str:
        name = os.path.basename(os.path.abspath(directory))
        return os.path.join(directory, f"{name}{self.PROJECT_FILE_EXT}")

    def _write_project_file(self, directory: str):
        project_file = self._project_file_path(directory)
        payload = {
            "format": "maptools-project",
            "version": "1.0",
            "project_dir": ".",
            "project_json": "project.json",
        }
        with open(project_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def save_project(self, directory: str):
        """
        Save the project to a directory.
        Structure:
        - project.json (metadata)
        - edit_layer.npy (raster edits)
        - annotations.json (vector data)
        """
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        self.project_dir = directory

        # 1. Save project-local map resource
        map_yaml_path = self._save_project_map_resource(directory)

        metadata = ProjectMetadata(
            name=os.path.basename(directory),
            map_yaml_path=map_yaml_path
        )

        with open(os.path.join(directory, "project.json"), 'w', encoding='utf-8') as f:
            json.dump(asdict(metadata), f, indent=2, ensure_ascii=False)

        # 2. Save Edit Layer (Numpy)
        if self.map_data.edit_layer is not None:
            np.save(os.path.join(directory, "edit_layer.npy"), self.map_data.edit_layer)

        # 3. Save Annotations
        self.annotations.save(os.path.join(directory, "annotations.json"))
        self._write_project_file(directory)

        print(f"Project saved to {directory}")

    def _save_project_map_resource(self, directory: str) -> str:
        if not self.map_data.yaml_path:
            return ""

        project_dir = Path(directory).expanduser().resolve()
        source_yaml_path = Path(self.map_data.yaml_path).expanduser().resolve()
        if not source_yaml_path.exists():
            raise FileNotFoundError(f"base map yaml not found: {source_yaml_path}")

        with open(source_yaml_path, "r", encoding="utf-8") as f:
            yaml_payload = yaml.safe_load(f) or {}

        image_value = str(yaml_payload.get("image", "")).strip()
        source_image_path = Path(image_value)
        if not source_image_path.is_absolute():
            source_image_path = (source_yaml_path.parent / source_image_path).resolve()
        if not source_image_path.exists():
            raise FileNotFoundError(f"base map image not found: {source_image_path}")

        target_yaml_path = project_dir / source_yaml_path.name
        target_image_path = project_dir / source_image_path.name

        if source_image_path != target_image_path.resolve():
            shutil.copy2(source_image_path, target_image_path)

        metadata = self.map_data.metadata
        if metadata is not None:
            exported_yaml = {
                "image": target_image_path.name,
                "mode": metadata.mode,
                "resolution": float(metadata.resolution),
                "origin": list(metadata.origin),
                "negate": int(metadata.negate),
                "occupied_thresh": float(metadata.occupied_thresh),
                "free_thresh": float(metadata.free_thresh),
            }
        else:
            exported_yaml = dict(yaml_payload)
            exported_yaml["image"] = target_image_path.name

        with open(target_yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(exported_yaml, f, sort_keys=False, allow_unicode=True)

        return str(target_yaml_path.relative_to(project_dir))

    def load_project_file(self, project_file_path: str) -> bool:
        if not os.path.isfile(project_file_path):
            return False
        try:
            with open(project_file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            project_file_dir = os.path.dirname(os.path.abspath(project_file_path))
            project_dir = str(payload.get("project_dir", "")).strip()
            if not project_dir:
                project_dir = project_file_dir
            elif not os.path.isabs(project_dir):
                project_dir = os.path.abspath(os.path.join(project_file_dir, project_dir))
            elif not os.path.exists(project_dir):
                project_dir = project_file_dir
            return self.load_project(project_dir)
        except Exception as e:
            print(f"Error loading project file: {e}")
            return False

    def load_project(self, directory: str) -> bool:
        """
        Load project from directory.
        """
        if not os.path.exists(directory):
            return False

        try:
            # 1. Load metadata
            project_json_path = os.path.join(directory, "project.json")
            if not os.path.exists(project_json_path):
                print("Error: Not a valid project directory (missing project.json)")
                return False

            with open(project_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                map_yaml_path = data.get("map_yaml_path", "")

            # 2. Load Base Map
            if map_yaml_path:
                if os.path.isabs(map_yaml_path):
                    candidate_path = map_yaml_path
                else:
                    candidate_path = os.path.join(directory, map_yaml_path)
                if not os.path.exists(candidate_path):
                    print(f"Error: Map YAML file not found: {map_yaml_path}")
                    return False
                if not self.map_data.load(candidate_path):
                    print(f"Failed to load map YAML: {candidate_path}")
                    return False

            # 3. Load Edit Layer
            edit_layer_path = os.path.join(directory, "edit_layer.npy")
            if os.path.exists(edit_layer_path):
                try:
                    loaded_layer = np.load(edit_layer_path)
                    # Verify shape matches
                    if self.map_data.grid_map is not None and loaded_layer.shape == self.map_data.grid_map.shape:
                        self.map_data.edit_layer = loaded_layer
                        self.map_data._display_dirty = True
                        self.map_data._display_cache = None
                    else:
                        print("Warning: Loaded edit layer shape mismatch or no base map. Ignoring.")
                except Exception as e:
                    print(f"Error loading edit layer: {e}")

            # 4. Load Annotations
            ann_path = os.path.join(directory, "annotations.json")
            if os.path.exists(ann_path):
                self.annotations.load(ann_path)

            self.project_dir = directory
            return True

        except Exception as e:
            print(f"Error loading project: {e}")
            import traceback
            traceback.print_exc()
            return False
