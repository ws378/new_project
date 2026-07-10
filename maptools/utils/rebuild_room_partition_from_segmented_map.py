#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np


@dataclass
class RebuildConfig:
    robot_width_m: float = 0.4
    doorway_margin: float = 0.3
    min_component_size: int = 10
    max_room_label: int = 4095


@dataclass
class Door:
    door_id: int
    rooms: Tuple[int, int]
    center_px: Tuple[int, int]
    center_m: Tuple[float, float]
    width_m: float
    yaw_a_to_b: float
    passable: bool
    version: int = 1


def load_segmented_map(bin_path: Path, meta_path: Path) -> Tuple[np.ndarray, Dict]:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    width = int(meta["width"])
    height = int(meta["height"])
    step = int(meta["step"])
    enc = str(meta.get("encoding", ""))
    if enc != "32SC1":
        raise ValueError(f"encoding={enc}，期望32SC1")
    if width <= 0 or height <= 0 or step < width * 4:
        raise ValueError(f"meta非法: width={width}, height={height}, step={step}")

    raw = bin_path.read_bytes()
    need = step * height
    if len(raw) < need:
        raise ValueError(f"bin大小不足: size={len(raw)}, need={need}")

    row_words = step // 4
    arr = np.frombuffer(raw[:need], dtype=np.int32).reshape((height, row_words))[:, :width]
    return arr, meta


def px_to_world(px: Tuple[int, int], origin_xy: Tuple[float, float], res: float) -> Tuple[float, float]:
    return origin_xy[0] + float(px[0]) * res, origin_xy[1] + float(px[1]) * res


def extract_rooms(labels: np.ndarray, origin_xy: Tuple[float, float], res: float, cfg: RebuildConfig) -> List[Dict]:
    rooms: List[Dict] = []
    room_ids = sorted(int(v) for v in np.unique(labels) if 0 < int(v) <= int(cfg.max_room_label))
    for rid in room_ids:
        mask = (labels == rid).astype(np.uint8)
        ys, xs = np.where(mask > 0)
        if xs.size == 0:
            continue

        center_px = (int(round(float(xs.mean()))), int(round(float(ys.mean()))))
        center_m = px_to_world(center_px, origin_xy, res)

        min_x, max_x = int(xs.min()), int(xs.max())
        min_y, max_y = int(ys.min()), int(ys.max())

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if contours:
            cnt = max(contours, key=cv2.contourArea)
            poly_px = [[int(p[0][0]), int(p[0][1])] for p in cnt]
        else:
            poly_px = []

        poly_m = [[origin_xy[0] + p[0] * res, origin_xy[1] + p[1] * res] for p in poly_px]

        rooms.append(
            {
                "room_id": rid,
                "center_px": [center_px[0], center_px[1]],
                "center_m": [float(center_m[0]), float(center_m[1])],
                "bbox_px": [min_x, min_y, max_x, max_y],
                "polygon_px": poly_px,
                "polygon": poly_m,
                "door_ids": [],
            }
        )
    return rooms


def build_roompair_boundary_masks(labels: np.ndarray, cfg: RebuildConfig) -> Dict[Tuple[int, int], np.ndarray]:
    h, w = labels.shape
    masks: Dict[Tuple[int, int], np.ndarray] = {}
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            cur = int(labels[y, x])
            if cur <= 0 or cur > cfg.max_room_label:
                continue
            neighbors = [int(labels[y - 1, x]), int(labels[y + 1, x]), int(labels[y, x - 1]), int(labels[y, x + 1])]
            if all((nb == cur or nb == 0) for nb in neighbors):
                continue
            s = {cur}
            for nb in neighbors:
                if 0 < nb <= cfg.max_room_label:
                    s.add(nb)
            if len(s) != 2:
                continue
            a, b = sorted(s)
            key = (a, b)
            if key not in masks:
                masks[key] = np.zeros((h, w), dtype=np.uint8)
            masks[key][y, x] = 255
    return masks


def pca_direction(points_xy: np.ndarray) -> Tuple[float, float]:
    pts = points_xy.astype(np.float32)
    mean = pts.mean(axis=0, keepdims=True)
    centered = pts - mean
    cov = (centered.T @ centered) / max(1.0, float(len(pts) - 1))
    vals, vecs = np.linalg.eigh(cov)
    v = vecs[:, int(np.argsort(vals)[::-1][0])]
    n = float(np.hypot(v[0], v[1]))
    if n < 1e-9:
        return 1.0, 0.0
    return float(v[0] / n), float(v[1] / n)


def estimate_width_px(points_xy: np.ndarray, tangent_dir: Tuple[float, float]) -> int:
    tx, ty = tangent_dir
    proj = points_xy[:, 0] * tx + points_xy[:, 1] * ty
    width = int(round(float(proj.max() - proj.min() + 1.0)))
    return max(width, 1)


def determine_normal_orientation(
    labels: np.ndarray, center_xy: Tuple[int, int], tangent_dir: Tuple[float, float], room_a: int, room_b: int
) -> Tuple[float, float]:
    tx, ty = tangent_dir
    nx, ny = -ty, tx
    n = float(np.hypot(nx, ny))
    if n < 1e-9:
        nx, ny = 1.0, 0.0
    else:
        nx, ny = nx / n, ny / n

    h, w = labels.shape

    def probe(sign: float):
        for k in range(1, 9):
            px = int(round(center_xy[0] + sign * nx * k))
            py = int(round(center_xy[1] + sign * ny * k))
            if px < 0 or px >= w or py < 0 or py >= h:
                break
            v = int(labels[py, px])
            if v > 0:
                return v
        return None

    pos = probe(+1.0)
    neg = probe(-1.0)
    if pos == room_b and neg == room_a:
        return nx, ny
    if pos == room_a and neg == room_b:
        return -nx, -ny
    return nx, ny


def extract_doors(labels: np.ndarray, origin_xy: Tuple[float, float], res: float, cfg: RebuildConfig) -> List[Door]:
    pair_masks = build_roompair_boundary_masks(labels, cfg)
    door_list: List[Door] = []
    # 这里比较的是门宽与机器人通过宽度阈值，阶段2统一按 width 语义表达。
    threshold_m = float(cfg.robot_width_m) + float(cfg.doorway_margin)

    next_id = 1
    for a, b in sorted(pair_masks.keys()):
        mask = pair_masks[(a, b)]
        num_labels, cc = cv2.connectedComponents(mask, connectivity=8)
        comps: List[np.ndarray] = []
        for i in range(1, num_labels):
            ys, xs = np.where(cc == i)
            if xs.size < cfg.min_component_size:
                continue
            pts = np.stack([xs, ys], axis=1).astype(np.int32)
            comps.append(pts)

        comps.sort(key=lambda p: (int(round(float(p[:, 1].mean()))), int(round(float(p[:, 0].mean())))))

        for pts in comps:
            cx = int(round(float(pts[:, 0].mean())))
            cy = int(round(float(pts[:, 1].mean())))
            tangent = pca_direction(pts)
            width_px = estimate_width_px(pts, tangent)
            width_m = float(width_px) * res
            nx, ny = determine_normal_orientation(labels, (cx, cy), tangent, a, b)
            yaw = float(math.atan2(ny, nx))
            passable = bool(width_m >= threshold_m)
            door_list.append(
                Door(
                    door_id=next_id,
                    rooms=(int(a), int(b)),
                    center_px=(cx, cy),
                    center_m=px_to_world((cx, cy), origin_xy, res),
                    width_m=width_m,
                    yaw_a_to_b=yaw,
                    passable=passable,
                    version=1,
                )
            )
            next_id += 1
    return door_list


def build_partition(labels: np.ndarray, meta: Dict, cfg: RebuildConfig) -> Dict:
    res = float(meta["resolution"])
    origin = meta.get("origin", {})
    origin_xy = (float(origin.get("x", 0.0)), float(origin.get("y", 0.0)))

    rooms = extract_rooms(labels, origin_xy, res, cfg)
    doors = extract_doors(labels, origin_xy, res, cfg)

    rid_to_room = {int(r["room_id"]): r for r in rooms}
    for d in doors:
        a, b = d.rooms
        if a in rid_to_room:
            rid_to_room[a]["door_ids"].append(int(d.door_id))
        if b in rid_to_room:
            rid_to_room[b]["door_ids"].append(int(d.door_id))

    for r in rooms:
        r["door_ids"] = sorted(set(int(v) for v in r["door_ids"]))

    return {
        "map_id": str(meta.get("map_id", "")),
        "map_version": int(meta.get("map_version", 0)) if str(meta.get("map_version", "0")).isdigit() else str(meta.get("map_version", "")),
        "meta": {
            "source": "rebuild_from_segmented_map",
            "status": "candidate",
            "approved_by": "",
            "coverage_version": str(meta.get("coverage_version", "")),
            "master_version": "",
            "candidate_version": str(meta.get("coverage_version", "")),
            "locked": False,
            "editable": True,
            "pending_review": True,
            "approved_at": "",
            "generated_at": "",
        },
        "rooms": sorted(rooms, key=lambda x: int(x["room_id"])),
        "doors": [
            {
                "id": int(d.door_id),
                "rooms": [int(d.rooms[0]), int(d.rooms[1])],
                "center_m": [float(d.center_m[0]), float(d.center_m[1])],
                "center_px": [int(d.center_px[0]), int(d.center_px[1])],
                "width_m": float(d.width_m),
                "yaw_a_to_b": float(d.yaw_a_to_b),
                "passable": bool(d.passable),
                "version": int(d.version),
            }
            for d in doors
        ],
    }
