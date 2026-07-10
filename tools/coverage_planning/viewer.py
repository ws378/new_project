#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def _load_map(map_yaml: Path) -> np.ndarray:
    import yaml
    with map_yaml.open("r", encoding="utf-8") as handle:
        meta = yaml.safe_load(handle)
    img_path = (map_yaml.parent / meta["image"]).resolve()
    img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"map image not found: {img_path}")
    return img


def _draw_path(img: np.ndarray, points: list[dict], color=(0, 0, 255)) -> np.ndarray:
    overlay = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if len(points) < 2:
        return overlay
    pts = [(int(p["x"]), int(p["y"])) for p in points]
    for i in range(len(pts) - 1):
        cv2.line(overlay, pts[i], pts[i + 1], color, 2, cv2.LINE_AA)
    cv2.circle(overlay, pts[0], 6, (0, 255, 0), -1, cv2.LINE_AA)
    cv2.circle(overlay, pts[-1], 6, (255, 0, 0), -1, cv2.LINE_AA)
    return overlay


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified viewer for coverage planning run outputs")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--no-view", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"summary.json 未找到: {summary_path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    map_yaml = Path(summary.get("map_yaml", ""))
    if not map_yaml.exists():
        raise FileNotFoundError("summary.json 未提供有效 map_yaml")

    points = summary.get("global_path", [])
    img = _load_map(map_yaml)
    overlay = _draw_path(img, points)
    out_path = run_dir / "viewer_overlay.png"
    cv2.imwrite(str(out_path), overlay)

    if not args.no_view:
        cv2.namedWindow("viewer", cv2.WINDOW_NORMAL)
        cv2.imshow("viewer", overlay)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
