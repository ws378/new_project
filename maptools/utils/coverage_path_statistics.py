import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


HEADER_MARKER = "ID\tRoom\tSegment\tX(m)\tY(m)\tYaw(rad)\tU(px)\tV(px)\tAcc_Dist\tRoom_Dist\tSeg_Dist"


@dataclass(frozen=True)
class CoveragePathStatisticsRow:
    point_id: int
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


@dataclass(frozen=True)
class SegmentStatistics:
    point_count: int = 0
    distance_m: float = 0.0


def _node_float(node, attr: str, default: float = 0.0) -> float:
    return float(getattr(node, attr, default))


def _node_int(node, attr: str, default: int = 0) -> int:
    return int(getattr(node, attr, default))


def build_statistics_rows(nodes: Iterable, room_id: int) -> List[CoveragePathStatisticsRow]:
    rows: List[CoveragePathStatisticsRow] = []
    acc_dist = 0.0
    room_dist = 0.0
    seg_dist = 0.0
    prev = None
    prev_segment = None

    for idx, node in enumerate(nodes):
        x = _node_float(node, "x")
        y = _node_float(node, "y")
        segment = _node_int(node, "segment")
        if prev is not None:
            step = math.hypot(x - prev[0], y - prev[1])
            acc_dist += step
            room_dist += step
            if segment != prev_segment:
                seg_dist = 0.0
            seg_dist += step
        rows.append(
            CoveragePathStatisticsRow(
                point_id=idx,
                room=room_id,
                segment=segment,
                x=x,
                y=y,
                yaw=_node_float(node, "yaw"),
                u=_node_float(node, "u"),
                v=_node_float(node, "v"),
                acc_dist=acc_dist,
                room_dist=room_dist,
                seg_dist=seg_dist,
            )
        )
        prev = (x, y)
        prev_segment = segment

    return rows


def summarize_segments(rows: List[CoveragePathStatisticsRow]) -> Dict[Tuple[int, int], SegmentStatistics]:
    summary: Dict[Tuple[int, int], SegmentStatistics] = {}
    prev = None
    for row in rows:
        key = (row.room, row.segment)
        current = summary.get(key, SegmentStatistics())
        step = 0.0
        if prev is not None and prev.room == row.room and prev.segment == row.segment:
            step = math.hypot(row.x - prev.x, row.y - prev.y)
        summary[key] = SegmentStatistics(
            point_count=current.point_count + 1,
            distance_m=current.distance_m + step,
        )
        prev = row
    return summary


def render_statistics_text(room_id: int, nodes: Iterable) -> str:
    rows = build_statistics_rows(nodes, room_id)
    segment_summary = summarize_segments(rows)
    total_distance = rows[-1].acc_dist if rows else 0.0

    lines = [
        "========================================",
        "覆盖路径点统计信息",
        "========================================",
        f"总路径点数: {len(rows)}",
        "",
        f"总路径距离: {total_distance:.3f} 米",
        "",
        "----------------------------------------",
        "按房间统计",
        "----------------------------------------",
        f"房间 {room_id}: {len(rows)} 个点, 距离: {total_distance:.3f} 米",
        "",
        "----------------------------------------",
        "按房间+Segment统计",
        "----------------------------------------",
    ]

    for room, segment in sorted(segment_summary):
        item = segment_summary[(room, segment)]
        lines.append(f"房间 {room}, Segment {segment}: {item.point_count} 个点, 距离: {item.distance_m:.3f} 米")

    lines.extend([
        "",
        "----------------------------------------",
        "详细路径点信息",
        "----------------------------------------",
        HEADER_MARKER,
    ])

    for row in rows:
        lines.append(
            "\t".join([
                str(row.point_id),
                str(row.room),
                str(row.segment),
                f"{row.x:.6f}",
                f"{row.y:.6f}",
                f"{row.yaw:.6f}",
                f"{row.u:.0f}",
                f"{row.v:.0f}",
                f"{row.acc_dist:.3f}",
                f"{row.room_dist:.3f}",
                f"{row.seg_dist:.3f}",
            ])
        )

    return "\n".join(lines) + "\n"


def write_room_statistics_file(output_dir: Path, room_id: int, nodes: Iterable) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"coverage_path_statistics_{room_id}.txt"
    output_path.write_text(render_statistics_text(room_id, nodes), encoding="utf-8")
    return output_path


def prepare_statistics_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in output_dir.glob("coverage_path_statistics_*.txt"):
        if path.is_file():
            path.unlink()
