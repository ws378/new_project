#!/usr/bin/env python3
import argparse
import json
import sys
import os

# 将当前目录加入Python路径，确保能导入maptools包
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from maptools.views.main_window import MainWindow
from maptools.models.map_data import MapData
from maptools.models.annotations import Annotations
from maptools.utils.coverage_repo_export import export_coverage_repo


def load_areas_json(annotations: Annotations, areas_json: str) -> None:
    with open(areas_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    annotations.area_labels = []
    for area in data.get("areas", []):
        annotations.add_area_label(
            [tuple(point) for point in area["polygon"]],
            name=area.get("name", f"Area {area['area_id']}"),
            area_id=int(area["area_id"]),
        )


def main():
    parser = argparse.ArgumentParser(description="ROS2 Map Editor")
    parser.add_argument("--export-coverage-repo", action="store_true")
    parser.add_argument("--map-yaml")
    parser.add_argument("--areas-json")
    parser.add_argument("--output-root")
    parser.add_argument("--map-id")
    parser.add_argument("--map-version", type=int, default=1)
    parser.add_argument("--nav2-root")
    args = parser.parse_args()

    if args.export_coverage_repo:
        if not args.map_yaml or not args.areas_json or not args.output_root or not args.map_id:
            parser.error("--export-coverage-repo requires --map-yaml --areas-json --output-root --map-id")
        map_data = MapData()
        if not map_data.load(args.map_yaml):
            raise SystemExit(1)
        annotations = Annotations()
        load_areas_json(annotations, args.areas_json)
        result = export_coverage_repo(
            map_data,
            annotations,
            output_root=args.output_root,
            map_id=args.map_id,
            map_version=args.map_version,
            nav2_root=args.nav2_root,
        )
        print(f"Exported coverage repo to {result.repo_dir}")
        return

    app = MainWindow()
    app.run()

if __name__ == "__main__":
    main()
