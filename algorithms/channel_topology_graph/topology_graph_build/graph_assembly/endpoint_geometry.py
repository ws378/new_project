"""TopologyGraphBuild 的边端点局部几何恢复。"""

from __future__ import annotations

import math
from typing import Any

from ...contracts import EdgeInfo


def build_edge_endpoint_geometry(edge: EdgeInfo) -> dict[str, dict[str, Any]]:
    """从 junction_rebuild 边对象提取两端接触点和朝向。

    真实职责：
        junction_rebuild 已经把边分成了 `inner_path_rc / outer_path_rc / path_rc`。
        topology_graph_build 要的不是重新推几何，而是从这些正式字段里读出：
        - 节点附近的接触点
        - 从节点向外离开的切向方向
    """

    # 接触点优先取 outer path，其次取端点 inner path，最后才退回完整路径端点。
    src_contact_rc = derive_src_contact_rc(edge)
    dst_contact_rc = derive_dst_contact_rc(edge)
    # 切向方向一律按“从节点朝边主体出去”的方向定义，方便节点局部统一排序。
    # 如果完整路径缺失，就退回接触点自身，最终由 `_safe_vec_rc` 产出零向量。
    # 这里的 center 点并不表达几何中心，只是用于恢复离开节点时的第一段方向。
    src_center_rc = tuple(map(float, edge.path_rc[0])) if edge.path_rc else tuple(map(float, src_contact_rc))
    dst_center_rc = tuple(map(float, edge.path_rc[-1])) if edge.path_rc else tuple(map(float, dst_contact_rc))
    # 端点两侧分别恢复切向，是为了让 src/dst 在节点局部排序时完全对称。
    src_tangent_vec_rc = safe_vec_rc(src_center_rc, src_contact_rc)
    dst_tangent_vec_rc = safe_vec_rc(dst_center_rc, dst_contact_rc)
    # 端点几何统一落成轻量 dict，后续 meta 与 compare 都直接消费这份结构。
    # 这样 candidate 层无需再解析 EdgeInfo 的 path/inner/outer 细节。
    return {
        "src": {
            "contact_rc": [float(src_contact_rc[0]), float(src_contact_rc[1])],
            "tangent_vec_rc": [float(src_tangent_vec_rc[0]), float(src_tangent_vec_rc[1])],
            "heading_deg_image": heading_deg_from_vec_rc(src_tangent_vec_rc),
        },
        "dst": {
            "contact_rc": [float(dst_contact_rc[0]), float(dst_contact_rc[1])],
            "tangent_vec_rc": [float(dst_tangent_vec_rc[0]), float(dst_tangent_vec_rc[1])],
            "heading_deg_image": heading_deg_from_vec_rc(dst_tangent_vec_rc),
        },
    }


def derive_src_contact_rc(edge: EdgeInfo) -> tuple[float, float]:
    """提取边在 src 节点侧的接触点。

    真实职责：
        节点局部连接候选应该使用“从节点离开后最先接到主体边的位置”。
        对于 junction_rebuild 已经切好的边，这个点优先取 `outer_path_rc` 的首点；
        若 outer 为空，再退回到内部段末点，最后才退到完整路径首点。
    """

    # outer path 首点是“离开 src 节点后最先进入主体边”的位置，优先级最高。
    if edge.outer_path_rc:
        return tuple(map(float, edge.outer_path_rc[0]))
    # outer 缺失时，退回 src 侧 inner path 的末点，仍然尽量贴近节点边界。
    src_inner = src_inner_path(edge)
    if src_inner:
        return tuple(map(float, src_inner[-1]))
    # 连 inner 也没有时，才把完整路径首点当作最低保真度兜底。
    if edge.path_rc:
        return tuple(map(float, edge.path_rc[0]))
    return (0.0, 0.0)


def derive_dst_contact_rc(edge: EdgeInfo) -> tuple[float, float]:
    """提取边在 dst 节点侧的接触点。"""

    # dst 侧与 src 侧同规则，只是读取尾端几何。
    # 这里优先级仍然是 outer -> dst inner -> full path end。
    if edge.outer_path_rc:
        return tuple(map(float, edge.outer_path_rc[-1]))
    # dst inner 取末点，是为了贴近“离开主体边后贴近节点边界”的位置。
    dst_inner = dst_inner_path(edge)
    if dst_inner:
        return tuple(map(float, dst_inner[-1]))
    if edge.path_rc:
        return tuple(map(float, edge.path_rc[-1]))
    # 连完整 path 都没有时，只能回到零点占位；后续排序会把零向量 heading 当成无方向处理。
    return (0.0, 0.0)


def src_inner_path(edge: EdgeInfo) -> tuple[tuple[float, float], ...]:
    """读取 src 侧 inner path。

    真实职责：
        当前 junction_rebuild 把双端 inner path 合并进了 `edge.inner_path_rc`，但同时也把
        更精确的 `src_inner_path_rc / dst_inner_path_rc` 保在 `debug_info` 里。
        topology_graph_build 优先读这两个端点局部几何，避免再对合并后的 `inner_path_rc` 做猜测。
    """

    # debug_info 里的端点局部几何仍属于 junction_rebuild 正式推导结果，可以被 topology_graph_build 安全消费。
    debug_info = edge.debug_info or {}
    src_inner = debug_info.get("src_inner_path_rc") or []
    # 这里统一转 float tuple，保证 compare 与几何 helper 口径一致。
    return tuple((float(item[0]), float(item[1])) for item in src_inner)


def dst_inner_path(edge: EdgeInfo) -> tuple[tuple[float, float], ...]:
    """读取 dst 侧 inner path。"""

    # dst 侧读取逻辑与 src 侧对称，仍然优先消费 junction_rebuild 保留下来的局部真值。
    # 两端 helper 保持同结构，便于 compare 时稳定对齐。
    debug_info = edge.debug_info or {}
    dst_inner = debug_info.get("dst_inner_path_rc") or []
    return tuple((float(item[0]), float(item[1])) for item in dst_inner)


def safe_vec_rc(point0_rc: tuple[float, float], point1_rc: tuple[float, float]) -> tuple[float, float]:
    """计算两点向量，并避免零向量。"""

    # 图像坐标向量保持 `(dr, dc)` 语义，不在这里转成笛卡尔 `(dx, dy)`。
    dr = float(point1_rc[0] - point0_rc[0])
    dc = float(point1_rc[1] - point0_rc[1])
    # 零向量留给上层显式识别，而不是在这里偷偷制造伪方向。
    if abs(dr) < 1e-6 and abs(dc) < 1e-6:
        return (0.0, 0.0)
    return (dr, dc)


def heading_deg_from_vec_rc(vec_rc: tuple[float, float]) -> float | None:
    """把图像坐标向量转成 heading 角。

    真实职责：
        这里沿用旧研究代码的图像坐标定义：
        - `0 deg` 指向右
        - 角度按图像坐标顺时针增加
        - 向量为零时返回 `None`
    """

    dr, dc = vec_rc
    # 零向量没有稳定方向，返回 None 让上层排序逻辑显式降级。
    if abs(dr) < 1e-6 and abs(dc) < 1e-6:
        return None
    # `atan2(dr, dc)` 保留图像坐标系定义，不切换到数学坐标系。
    theta_deg = math.degrees(math.atan2(float(dr), float(dc)))
    return normalize_heading_delta_deg(theta_deg)


def normalize_heading_delta_deg(theta_deg: float) -> float:
    """把角度归一化到 `[-180, 180)`。"""

    # 这里的归一化只服务“节点局部相对角度”比较，不引入额外方向语义。
    value = float(theta_deg)
    # 上边界压回区间内，避免出现 `180` 与 `-180` 两套等价表示。
    while value >= 180.0:
        value -= 360.0
    # 下边界同理往上卷，保证最终总在半开区间里。
    while value < -180.0:
        value += 360.0
    return value


__all__ = ["build_edge_endpoint_geometry"]
