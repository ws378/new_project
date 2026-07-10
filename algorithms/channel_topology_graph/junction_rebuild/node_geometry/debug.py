"""交汇节点几何的轻量调试与降级 helper。"""

from __future__ import annotations

from typing import Any


def solve_dead_end_polygon(center_rc: tuple[float, float], radius_px: float) -> list[tuple[float, float]]:
    """给断头路节点生成保守局部 polygon。"""

    # 断头路没有完整 sector 评估时，退回一个菱形近似 polygon。
    radius_px = max(2.0, float(radius_px))
    # 最小半径钳到 2px，避免生成过尖的小菱形。
    # 四个顶点按上下左右布置，便于和 rc 坐标系直观对应。
    # 这份 polygon 的目标是稳健可视化，而不是几何最优拟合。
    return [
        (float(center_rc[0] - radius_px), float(center_rc[1])),
        (float(center_rc[0]), float(center_rc[1] + radius_px)),
        (float(center_rc[0] + radius_px), float(center_rc[1])),
        (float(center_rc[0]), float(center_rc[1] - radius_px)),
    ]


def sector_to_debug_dict(sector: Any) -> dict[str, Any]:
    """把 sector 模型压成可序列化调试字典。"""

    # 字段全部压成基础类型，保证可以直接写入 JSON runtime。
    # 这里只保留排障需要的核心字段，不复刻完整 dataclass。
    # 这些字段足以重建扇区方向、得分和代表点。
    # 调试侧如果需要更多细节，应回到原始 sector 模型而不是扩张这里。
    # 这样调试字典能保持稳定 schema，便于前后版本比较。
    # 同时也降低了 runtime 调试输出的体积。
    # 这也是前端或 markdown 调试页最容易消费的格式。
    # 因而这里优先追求稳定字段名，而不是覆盖全部内部状态。
    # 复杂诊断仍应回到 sector 原对象做二次分析。
    return {
        "sector_index": int(sector.sector_index),
        "start_theta_deg": float(sector.start_theta_deg),
        "end_theta_deg": float(sector.end_theta_deg),
        "center_theta_deg": float(sector.center_theta_deg),
        "width_deg": float(sector.width_deg),
        "chosen_type": str(sector.chosen_type),
        "corner_score": float(sector.corner_score),
        "edge_score": float(sector.edge_score),
        "hit_points_rc": [[int(r), int(c)] for r, c in sector.hit_points_rc],
        "representative_point_rc": (
            [int(sector.representative_point_rc[0]), int(sector.representative_point_rc[1])]
            if sector.representative_point_rc is not None
            else None
        ),
        "edge_endpoints_rc": [[int(r), int(c)] for r, c in sector.edge_endpoints_rc],
    }


def initial_point_rc(node_runtime: dict[int, dict[str, Any]], node_id: int) -> tuple[int, int]:
    """读取节点的初始代表点。"""

    # 若 runtime 未记录该字段，就退回原点占位，避免 debug 写出阶段中断。
    point_rc = node_runtime[int(node_id)].get("initial_point_rc")
    if point_rc is None:
        return (0, 0)
    # 命中时统一转成 int tuple，和其余调试点位口径一致。
    return tuple(map(int, point_rc))


__all__ = (
    "solve_dead_end_polygon",
    "sector_to_debug_dict",
    "initial_point_rc",
)
