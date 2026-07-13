import math
import copy
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Set


@dataclass
class CoveragePathNode:
    id: int
    room: int
    segment: int
    x: float
    y: float
    yaw: float
    u: float
    v: float
    acc_dist: float
    room_dist: float
    seg_dist: float

    @property
    def room_id(self) -> int:
        return int(self.room)

    @room_id.setter
    def room_id(self, value: int) -> None:
        self.room = int(value)

    def duplicate(self) -> 'CoveragePathNode':
        return CoveragePathNode(
            id=self.id, room=self.room, segment=self.segment,
            x=self.x, y=self.y, yaw=self.yaw, u=self.u, v=self.v,
            acc_dist=self.acc_dist, room_dist=self.room_dist, seg_dist=self.seg_dist
        )


SPATIAL_GRID_CELL = 50


class SpatialGrid:
    """Simple grid-based spatial index over pixel coordinates."""

    def __init__(self, cell_size: float = SPATIAL_GRID_CELL):
        self.cell_size = cell_size
        self._grid: Dict[Tuple[int, int], List[CoveragePathNode]] = {}

    def clear(self) -> None:
        self._grid.clear()

    def _key(self, u: float, v: float) -> Tuple[int, int]:
        return int(u // self.cell_size), int(v // self.cell_size)

    def build(self, points: List[CoveragePathNode]) -> None:
        self.clear()
        for p in points:
            k = self._key(p.u, p.v)
            self._grid.setdefault(k, []).append(p)

    def query_nearby(self, u: float, v: float, radius_px: float) -> List[CoveragePathNode]:
        """Return points within *radius_px* pixels of (u, v)."""
        r_cells = int(math.ceil(radius_px / self.cell_size))
        cx, cy = self._key(u, v)
        result: List[CoveragePathNode] = []
        for dx in range(-r_cells, r_cells + 1):
            for dy in range(-r_cells, r_cells + 1):
                result.extend(self._grid.get((cx + dx, cy + dy), []))
        return result


class CoveragePathManager:
    """Manages coverage path nodes and their selection state."""

    def __init__(self):
        self.nodes: List[CoveragePathNode] = []
        self.selection: Set[int] = set()
        self.spatial = SpatialGrid()
        self.is_dirty: bool = False
        self.current_file_path: Optional[str] = None
        self.start_point: Optional[Tuple[float, float]] = None  # (x, y) 世界坐标
        self.end_point: Optional[Tuple[float, float]] = None    # (x, y) 世界坐标

    def clear(self):
        self.nodes.clear()
        self.selection.clear()
        self.spatial.clear()
        self.start_point = None
        self.end_point = None
        self.is_dirty = True

    def rebuild_spatial(self):
        self.spatial.build(self.nodes)

    def renumber_nodes(self):
        """Reassign continuous IDs starting from 0 and recompute distances."""
        for idx, p in enumerate(self.nodes):
            p.id = idx
        self.nodes = recompute_dist(self.nodes)
        self.rebuild_spatial()

    def duplicate_nodes(self) -> List[CoveragePathNode]:
        """Create a deep copy of nodes for undo/redo."""
        return [node.duplicate() for node in self.nodes]

    def set_nodes(self, nodes: List[CoveragePathNode]):
        self.nodes = nodes
        self.selection.clear()
        self.rebuild_spatial()


class PathParser:
    header_marker = "ID\tRoom\tSegment\tX(m)\tY(m)\tYaw(rad)\tU(px)\tV(px)\tAcc_Dist\tRoom_Dist\tSeg_Dist"

    def __init__(self, path_file: str):
        self.path_file = path_file
        self.prefix_lines: List[str] = []

    @classmethod
    def create_empty(cls, path_file: str) -> "PathParser":
        parser = cls(path_file)
        parser.prefix_lines = [cls.header_marker]
        return parser

    @classmethod
    def load_tsv(cls, path_file: str, out_nodes: List[CoveragePathNode], map_meta=None) -> None:
        """Compatibility API used by MainWindow: load a TSV/TXT into *out_nodes*.

        map_meta is intentionally accepted for signature compatibility.
        """
        parser = cls(path_file)
        loaded = parser.load()
        out_nodes.clear()
        out_nodes.extend(loaded)

    @classmethod
    def save_tsv(
        cls,
        path_file: str,
        nodes: List[CoveragePathNode],
        map_meta=None,
        recompute_dist: bool = True,
        recompute_yaw: bool = False,
    ) -> None:
        """Compatibility API used by MainWindow: save nodes as TSV/TXT.

        map_meta is intentionally accepted for signature compatibility.
        """
        parser = cls.create_empty(path_file)
        parser.save(
            nodes,
            output=path_file,
            recompute_distances=recompute_dist,
            recompute_yaw=recompute_yaw,
        )

    def load(self) -> List[CoveragePathNode]:
        points: List[CoveragePathNode] = []
        with open(self.path_file, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        if self.header_marker not in lines:
            raise ValueError("Could not find header marker in path file")
        idx = lines.index(self.header_marker)
        self.prefix_lines = lines[: idx + 1]
        for line in lines[idx + 1:]:
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 11:
                continue
            pid, room, seg = int(parts[0]), int(parts[1]), int(parts[2])
            x, y, yaw = float(parts[3]), float(parts[4]), float(parts[5])
            u, v = float(parts[6]), float(parts[7])
            acc, rdist, sdist = float(parts[8]), float(parts[9]), float(parts[10])
            points.append(
                CoveragePathNode(
                    id=pid, room=room, segment=seg,
                    x=x, y=y, yaw=yaw, u=u, v=v,
                    acc_dist=acc, room_dist=rdist, seg_dist=sdist
                )
            )
        return points

    def save(
        self,
        nodes: List[CoveragePathNode],
        output: Optional[str] = None,
        recompute_distances: bool = True,
        recompute_yaw: bool = False,
    ) -> None:
        target = output or self.path_file
        lines = list(self.prefix_lines)
        if not lines: # Fallback if empty
            lines = [self.header_marker]
            
        nodes_out = nodes
        if recompute_yaw:
            recompute_yaw_in_place(nodes_out)
        if recompute_distances:
            nodes_out = recompute_dist(nodes_out)
            
        for p in nodes_out:
            line = "\t".join([
                str(p.id), str(p.room), str(p.segment),
                f"{p.x:.6f}", f"{p.y:.6f}", f"{p.yaw:.6f}",
                f"{p.u:.0f}", f"{p.v:.0f}",
                f"{p.acc_dist:.3f}", f"{p.room_dist:.3f}", f"{p.seg_dist:.3f}",
            ])
            lines.append(line)
            
        with open(target, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


# --- Math and recompute utilities ---

def recompute_dist(points: List[CoveragePathNode]) -> List[CoveragePathNode]:
    if not points:
        return []
    updated: List[CoveragePathNode] = []
    acc_dist = 0.0
    room_dist = 0.0
    seg_dist = 0.0
    prev: Optional[CoveragePathNode] = None
    for idx, p in enumerate(points):
        if prev:
            dx = p.x - prev.x
            dy = p.y - prev.y
            step = math.hypot(dx, dy)
            acc_dist += step
            if p.room != prev.room:
                room_dist = 0.0
            room_dist += step
            if p.segment != prev.segment or p.room != prev.room:
                seg_dist = 0.0
            seg_dist += step
        updated.append(
            CoveragePathNode(
                id=p.id, room=p.room, segment=p.segment,
                x=p.x, y=p.y, yaw=p.yaw, u=p.u, v=p.v,
                acc_dist=acc_dist, room_dist=room_dist, seg_dist=seg_dist
            )
        )
        prev = p
    return updated


def compute_yaw_updates(points: List[CoveragePathNode]) -> List[Tuple[int, float]]:
    updates: List[Tuple[int, float]] = []
    if not points:
        return updates
    n = len(points)
    start = 0
    while start < n:
        seg = points[start].segment
        end = start
        while end + 1 < n and points[end + 1].segment == seg:
            end += 1
        if end == start:
            start = end + 1
            continue
        for i in range(start, end + 1):
            if i == start:
                dx = points[i + 1].x - points[i].x
                dy = points[i + 1].y - points[i].y
            elif i == end:
                dx = points[i].x - points[i - 1].x
                dy = points[i].y - points[i - 1].y
            else:
                dx = points[i + 1].x - points[i - 1].x
                dy = points[i + 1].y - points[i - 1].y
            if math.hypot(dx, dy) < 1e-9:
                continue
            updates.append((i, math.atan2(dy, dx)))
        start = end + 1
    return updates


def recompute_yaw_in_place(points: List[CoveragePathNode]) -> bool:
    changed = False
    for idx, new_yaw in compute_yaw_updates(points):
        if abs(new_yaw - points[idx].yaw) > 1e-6:
            changed = True
        points[idx].yaw = new_yaw
    return changed


def resample_polyline(
    world_coords: List[Tuple[float, float]], interval: float
) -> List[Tuple[float, float]]:
    """Resample a polyline at equal arc-length intervals."""
    if len(world_coords) < 2:
        return list(world_coords)
    sampled: List[Tuple[float, float]] = [world_coords[0]]
    residual = 0.0
    for i in range(len(world_coords) - 1):
        ax, ay = world_coords[i]
        bx, by = world_coords[i + 1]
        seg_len = math.hypot(bx - ax, by - ay)
        if seg_len < 1e-9:
            continue
        dx, dy = (bx - ax) / seg_len, (by - ay) / seg_len
        travelled = residual
        while travelled + interval <= seg_len:
            travelled += interval
            sampled.append((ax + dx * travelled, ay + dy * travelled))
        residual = seg_len - travelled
    last = world_coords[-1]
    if math.hypot(last[0] - sampled[-1][0], last[1] - sampled[-1][1]) > 1e-6:
        sampled.append(last)
    return sampled


def make_path_nodes(
    sampled_world: List[Tuple[float, float]],
    room: int,
    segment: int,
    map_meta, # MapData metadata or MapMeta equivalent
) -> List[CoveragePathNode]:
    """Convert sampled world coordinates into CoveragePathNode list with auto-computed yaw."""
    pts: List[CoveragePathNode] = []
    n = len(sampled_world)
    meta_obj = getattr(map_meta, "metadata", map_meta)
    res = meta_obj.resolution
    origin_x, origin_y, _ = meta_obj.origin
    if hasattr(map_meta, "height"):
        map_height = map_meta.height
    elif hasattr(meta_obj, "height"):
        map_height = meta_obj.height
    else:
        map_height = meta_obj.image_height  # fallback based on historical metadata structures

    for i, (wx, wy) in enumerate(sampled_world):
        if n == 1:
            yaw = 0.0
        elif i == 0:
            yaw = math.atan2(sampled_world[1][1] - wy, sampled_world[1][0] - wx)
        elif i == n - 1:
            yaw = math.atan2(wy - sampled_world[i - 1][1], wx - sampled_world[i - 1][0])
        else:
            yaw = math.atan2(
                sampled_world[i + 1][1] - sampled_world[i - 1][1],
                sampled_world[i + 1][0] - sampled_world[i - 1][0],
            )
        # World to Pixel
        u = (wx - origin_x) / res
        v = map_height - (wy - origin_y) / res
        pts.append(
            CoveragePathNode(
                id=0, room=room, segment=segment,
                x=wx, y=wy, yaw=yaw, u=u, v=v,
                acc_dist=0.0, room_dist=0.0, seg_dist=0.0,
            )
        )
    return pts


def point_in_polygon(pt: Tuple[float, float], poly: List[Tuple[float, float]]) -> bool:
    """Ray-casting algorithm for point in polygon."""
    x, y = pt
    n = len(poly)
    inside = False
    p1x, p1y = poly[0]
    for i in range(1, n + 1):
        p2x, p2y = poly[i % n]
        if min(p1y, p2y) < y <= max(p1y, p2y):
            if x <= max(p1x, p2x):
                if p1y != p2y:
                    xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                if p1x == p2x or x <= xinters:
                    inside = not inside
        p1x, p1y = p2x, p2y
    return inside
