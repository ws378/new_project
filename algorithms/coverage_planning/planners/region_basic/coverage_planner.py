"""
Energy Functional Explorator - 覆盖路径规划算法

基于论文: Bormann Richard, Joshua Hampp, and Martin Hägele.
"New brooms sweep clean-an autonomous robotic cleaning assistant for
professional office cleaning." ICRA, 2015.

从 C++ ROS 实现移植而来 (energy_functional_explorator.cpp / room_rotator.cpp)。
"""

import math
import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

import numpy as np
import cv2

from ...contracts import CoveragePlannerConfig, CoverageResult, Pose2D

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 常量
# ------------------------------------------------------------------
PI = math.pi
PI_2_INV = 1.0 / (0.5 * PI)  # = 2/π ≈ 0.6366

@dataclass
class _Node:
    """内部网格节点

    对应 C++ 中的 EnergyExploratorNode。
    """
    center_x: int = 0          # 像素坐标 x (旋转后坐标系)
    center_y: int = 0          # 像素坐标 y (旋转后坐标系)
    obstacle: bool = True      # 是否是障碍物
    visited: bool = False      # 是否已访问
    neighbor_indices: List[Tuple[int, int]] = field(default_factory=list)  # (row, col) 索引

    def count_non_obstacle_neighbors(
            self, nodes: List[List['_Node']]) -> int:
        """统计非障碍物邻居数量"""
        count = 0
        for r, c in self.neighbor_indices:
            if not nodes[r][c].obstacle:
                count += 1
        return count


# ------------------------------------------------------------------
# 加权直方图 (对应 C++ Histogram<double>)
# ------------------------------------------------------------------
class _Histogram:
    """加权直方图, 用于计算地图主方向"""

    def __init__(self, lower: float, upper: float, bins: int):
        self.lower = lower
        self.upper = upper
        self.bins = bins
        self.range_inv = 1.0 / (upper - lower)
        self.data = [0.0] * bins
        self.raw_data: List[List[Tuple[float, float]]] = [[] for _ in range(bins)]

    def add(self, val: float, weight: float = 1.0):
        b = int((val - self.lower) * self.range_inv * self.bins)
        b = max(0, min(self.bins - 1, b))
        self.data[b] += weight
        self.raw_data[b].append((val, weight))

    def max_bin_precise_val(self) -> float:
        max_bin = int(np.argmax(self.data))
        entries = self.raw_data[max_bin]
        if not entries:
            return 0.0
        s = sum(v * w for v, w in entries)
        ws = sum(w for _, w in entries)
        return s / ws if ws != 0 else 0.0


# ------------------------------------------------------------------
# 核心算法类
# ------------------------------------------------------------------
class CoveragePlanner:
    """基于能量泛函的覆盖路径规划器

    Usage::

        config = CoveragePlannerConfig(coverage_width_m=0.5)
        planner = CoveragePlanner(config)
        result = planner.plan(room_map, map_resolution=0.05,
                              starting_position=(100, 100))
    """

    def __init__(self, config: Optional[CoveragePlannerConfig] = None):
        self.cfg = config or CoveragePlannerConfig()

    # ==============================================================
    #  公开接口
    # ==============================================================
    def plan(
        self,
        room_map: np.ndarray,
        map_resolution: float,
        starting_position: Tuple[int, int],
        map_origin: Tuple[float, float] = (0.0, 0.0),
    ) -> CoverageResult:
        """在给定的二值地图上规划覆盖路径

        Args:
            room_map: uint8 二值地图, 255=自由空间, 0=障碍物
            map_resolution: 米/像素
            starting_position: 起始位置 (像素x, 像素y)
            map_origin: 地图原点在世界坐标系中的位置 (x, y) [米]

        Returns:
            CoverageResult 包含成功/失败状态与路径点
        """
        if room_map is None or room_map.size == 0:
            return CoverageResult.failure_result(101, "Empty room map")

        # 确保是单通道 uint8
        if len(room_map.shape) == 3:
            room_map = cv2.cvtColor(room_map, cv2.COLOR_BGR2GRAY)
        room_map = room_map.astype(np.uint8)

        # 计算覆盖宽度对应的像素步长。
        coverage_width_px = self.cfg.coverage_width_m / map_resolution
        coverage_width_step_px = max(1, int(math.floor(coverage_width_px)))
        half_coverage_width_px = max(1, int(math.floor(coverage_width_px * 0.5)))

        logger.info("coverage_width_px=%.2f, coverage_width_step_px=%d",
                     coverage_width_px, coverage_width_step_px)

        # ============ I. 地图旋转对齐 ============
        if self.cfg.auto_rotate:
            R, bbox, rotated_map = self._rotate_room_auto(
                room_map, map_resolution)
        else:
            # 不旋转: 单位变换
            R = np.eye(2, 3, dtype=np.float64)
            rotated_map = room_map.copy()
            bbox = (rotated_map.shape[1], rotated_map.shape[0])

        # 计算旋转后地图的 min/max 自由空间坐标
        min_room, max_room = self._get_min_max_coords(rotated_map)
        if min_room is None:
            return CoverageResult.failure_result(
                102, "No free space in rotated map")

        # 阶段2正式输入已经是公共预处理后的 prepared_map；
        # basic 这里不再重复做产品级腐蚀/开运算，只消费正式真值继续采样。
        inflated = rotated_map

        # ============ II. 生成节点 + III. 建立邻域 ============
        nodes, corner_indices, first_free = self._generate_nodes(
            inflated, min_room, max_room,
            coverage_width_step_px, half_coverage_width_px)

        if first_free is None:
            return CoverageResult.failure_result(
                102, "[NO_ACCESSIBLE_POINTS] No accessible points in room")

        total_free = sum(
            1 for row in nodes for n in row if not n.obstacle)
        logger.info("Nodes generated: total_free=%d, corners=%d",
                     total_free, len(corner_indices))

        # ============ IV. 选起点 ============
        # 将 starting_position 旋转到旋转坐标系
        sp = np.array([[starting_position[0], starting_position[1]]],
                      dtype=np.float32)
        sp_rot = cv2.transform(sp.reshape(1, -1, 2), R)[0][0]
        rot_start = (sp_rot[0], sp_rot[1])

        start_rc = self._find_start_node(
            nodes, corner_indices, first_free, rot_start)

        # ============ V. 贪心路径规划 ============
        fov_path = self._plan_path(
            nodes, start_rc, coverage_width_px, map_resolution)

        logger.info("Path planned: %d points", len(fov_path))

        # ============ VI. 路径反旋转 ============
        original_path_px = self._transform_path_back(fov_path, R)

        # ============ VII. 像素 → 世界坐标 ============
        # 注意: 像素坐标 Y 向下, ROS 世界坐标 Y 向上, 需要翻转
        map_h = room_map.shape[0]
        path = []
        for i, (px, py) in enumerate(original_path_px):
            wx = px * map_resolution + map_origin[0]
            wy = (map_h - py) * map_resolution + map_origin[1]
            # 计算朝向 (同样需要考虑 Y 轴翻转)
            if i < len(original_path_px) - 1:
                nx, ny = original_path_px[i + 1]
                theta = math.atan2(-(ny - py), nx - px)  # Y 翻转
            elif i > 0:
                prev_x, prev_y = original_path_px[i - 1]
                theta = math.atan2(-(py - prev_y), px - prev_x)  # Y 翻转
            else:
                theta = 0.0
            path.append(Pose2D(wx, wy, theta))

        return CoverageResult.success_result(path, original_path_px)

    # ==============================================================
    #  I. 地图旋转
    # ==============================================================
    def _compute_main_direction(
            self, room_map: np.ndarray,
            map_resolution: float) -> float:
        """计算地图墙壁的主方向 (Canny + HoughLinesP + 加权直方图)

        对应 C++ RoomRotator::computeRoomMainDirection
        """
        res_inv = 1.0 / map_resolution

        # Canny 边缘检测
        edges = cv2.Canny(room_map, 50, 150, apertureSize=3)

        # 逐步降低最小线长直到检测到足够的直线
        lines = None
        min_line_length = 1.0  # 米
        while min_line_length > 0.1:
            min_len_px = min_line_length * res_inv
            max_gap_px = 1.5 * min_line_length * res_inv
            lines = cv2.HoughLinesP(
                edges, 1, PI / 180, int(min_len_px),
                minLineLength=min_len_px,
                maxLineGap=max_gap_px)
            if lines is not None and len(lines) >= 4:
                break
            min_line_length -= 0.2

        if lines is None or len(lines) == 0:
            return 0.0

        # 加权直方图
        hist = _Histogram(0.0, PI, 36)
        for line in lines:
            x1, y1, x2, y2 = line[0]
            dx = float(x2 - x1)
            dy = float(y2 - y1)
            length = math.sqrt(dx * dx + dy * dy)
            if length > 0:
                direction = math.atan2(dy, dx)
                # 标准化到 [0, π]
                while direction < 0:
                    direction += PI
                while direction > PI:
                    direction -= PI
                hist.add(direction, length)

        return hist.max_bin_precise_val()

    def _compute_rotation_matrix(
            self, room_map: np.ndarray,
            map_resolution: float) -> Tuple[np.ndarray, Tuple[int, int]]:
        """计算旋转矩阵和旋转后尺寸

        对应 C++ RoomRotator::computeRoomRotationMatrix

        Returns:
            (R, (width, height)) - 2x3 仿射变换矩阵和输出尺寸
        """
        angle = self._compute_main_direction(room_map, map_resolution)
        logger.info("Main direction angle: %.4f rad (%.1f deg)",
                     angle, math.degrees(angle))

        # 计算旋转中心
        min_r, max_r = self._get_min_max_coords(room_map)
        if min_r is None:
            cx, cy = room_map.shape[1] / 2, room_map.shape[0] / 2
        else:
            cx = 0.5 * (min_r[0] + max_r[0])
            cy = 0.5 * (min_r[1] + max_r[1])

        center = (cx, cy)
        angle_deg = math.degrees(angle)

        R = cv2.getRotationMatrix2D(center, angle_deg, 1.0)

        # 计算边界矩形
        h, w = room_map.shape[:2]
        cos_a = abs(R[0, 0])
        sin_a = abs(R[0, 1])
        new_w = int(h * sin_a + w * cos_a)
        new_h = int(h * cos_a + w * sin_a)

        R[0, 2] += 0.5 * new_w - center[0]
        R[1, 2] += 0.5 * new_h - center[1]

        return R, (new_w, new_h)

    def _rotate_room_auto(
            self, room_map: np.ndarray,
            map_resolution: float
    ) -> Tuple[np.ndarray, Tuple[int, int], np.ndarray]:
        """旋转房间地图, 返回 (R, bbox_size, rotated_map)

        对应 C++ RoomRotator::rotateRoom
        """
        R, (new_w, new_h) = self._compute_rotation_matrix(
            room_map, map_resolution)

        rotated = cv2.warpAffine(
            room_map, R, (new_w, new_h),
            flags=cv2.INTER_AREA)

        # 二值化
        _, rotated = cv2.threshold(rotated, 127, 255, cv2.THRESH_BINARY)

        return R, (new_w, new_h), rotated

    # ==============================================================
    #  II / III. 节点生成 + 邻域
    # ==============================================================
    @staticmethod
    def _get_min_max_coords(
            binary_map: np.ndarray
    ) -> Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]]]:
        """获取二值地图中自由空间 (255) 的 min/max 坐标

        Returns:
            ((min_x, min_y), (max_x, max_y)) 或 (None, None)
        """
        ys, xs = np.where(binary_map == 255)
        if len(xs) == 0:
            return None, None
        return (int(xs.min()), int(ys.min())), (int(xs.max()), int(ys.max()))

    @staticmethod
    def _complete_cell_test(
            room_map: np.ndarray,
            cx: int, cy: int,
            cell_size: int) -> Tuple[bool, int, int]:
        """检测网格单元是否包含可达空间, 返回 (ok, new_cx, new_cy)

        对应 C++ GridGenerator::completeCellTest
        """
        h, w = room_map.shape[:2]
        # 检查中心点
        if 0 <= cy < h and 0 <= cx < w:
            if room_map[cy, cx] == 255:
                return True, cx, cy

        # 检查整个单元格区域
        half = cell_size // 2
        upper = half - 1 if cell_size % 2 == 0 else half

        x0 = max(0, cx - half)
        x1 = min(w, cx + upper + 1)
        y0 = max(0, cy - half)
        y1 = min(h, cy + upper + 1)

        if x1 <= x0 or y1 <= y0:
            return False, cx, cy

        cell = room_map[y0:y1, x0:x1]
        accessible = np.where(cell == 255)
        if len(accessible[0]) == 0:
            return False, cx, cy

        # 使用距离变换找到最佳中心点
        cell_bin = np.zeros_like(cell)
        cell_bin[cell == 255] = 255
        dist = cv2.distanceTransform(cell_bin, cv2.DIST_L2, 5)
        max_dist = dist.max()

        # 在最大距离像素中取最接近原始中心的
        candidates = np.argwhere(dist == max_dist)  # (row, col) pairs
        best_dy, best_dx = candidates[0]
        best_sq_dist = (best_dx - half) ** 2 + (best_dy - half) ** 2
        for dy_off, dx_off in candidates[1:]:
            sq = (dx_off - half) ** 2 + (dy_off - half) ** 2
            if sq < best_sq_dist:
                best_sq_dist = sq
                best_dx, best_dy = dx_off, dy_off

        new_cx = x0 + int(best_dx)
        new_cy = y0 + int(best_dy)
        return True, new_cx, new_cy

    def _generate_nodes(
            self,
            inflated_map: np.ndarray,
            min_room: Tuple[int, int],
            max_room: Tuple[int, int],
            coverage_width_step_px: int,
            half_coverage_width_px: int
    ) -> Tuple[List[List[_Node]],
               List[Tuple[int, int]],
               Optional[Tuple[int, int]]]:
        """在旋转后的膨胀地图上生成网格节点并建立邻域

        对应 C++ getExplorationPath Phase II。

        Returns:
            (nodes_2d, corner_indices, first_free_rc)
        """
        nodes: List[List[_Node]] = []
        corner_indices: List[Tuple[int, int]] = []
        first_free: Optional[Tuple[int, int]] = None
        n_nodes = 0

        # 生成网格节点
        y = min_room[1] + half_coverage_width_px
        while y < max_room[1]:
            row: List[_Node] = []
            x = min_room[0] + half_coverage_width_px
            while x < max_room[0]:
                node = _Node(center_x=x, center_y=y)
                ok, new_x, new_y = self._complete_cell_test(
                    inflated_map, x, y, coverage_width_step_px)
                if ok:
                    node.center_x = new_x
                    node.center_y = new_y
                    node.obstacle = False
                    node.visited = False
                else:
                    node.obstacle = True
                    node.visited = True
                row.append(node)
                n_nodes += 1
                x += coverage_width_step_px
            nodes.append(row)
            y += coverage_width_step_px

        logger.info("Generated %d grid nodes", n_nodes)

        # 建立 8 邻域关系
        num_rows = len(nodes)
        for r in range(num_rows):
            num_cols = len(nodes[r])
            for c in range(num_cols):
                neighbors = []
                for dy in range(-1, 2):
                    nr = r + dy
                    if nr < 0 or nr >= num_rows:
                        continue
                    # 左
                    if c > 0:
                        neighbors.append((nr, c - 1))
                    # 上/下同列
                    if dy != 0:
                        neighbors.append((nr, c))
                    # 右
                    if c < num_cols - 1:
                        neighbors.append((nr, c + 1))
                nodes[r][c].neighbor_indices = neighbors

                # 识别角落节点 (非障碍且非障碍邻居 <= 3)
                if not nodes[r][c].obstacle:
                    if first_free is None:
                        first_free = (r, c)
                    non_obs = nodes[r][c].count_non_obstacle_neighbors(nodes)
                    if non_obs <= 3:
                        corner_indices.append((r, c))

        return nodes, corner_indices, first_free

    # ==============================================================
    #  IV. 选择起始节点
    # ==============================================================
    @staticmethod
    def _find_start_node(
            nodes: List[List[_Node]],
            corner_indices: List[Tuple[int, int]],
            first_free: Tuple[int, int],
            rotated_start: Tuple[float, float]
    ) -> Tuple[int, int]:
        """选择最近角落节点为起始节点

        对应 C++ Phase III.i
        """
        sx, sy = rotated_start
        best_rc = first_free
        best_dist = 1e18

        for r, c in corner_indices:
            n = nodes[r][c]
            dx = n.center_x - sx
            dy = n.center_y - sy
            d2 = dx * dx + dy * dy
            if d2 <= best_dist:
                best_dist = d2
                best_rc = (r, c)

        return best_rc

    # ==============================================================
    #  V. 能量函数 + 路径规划主循环
    # ==============================================================
    def _energy(
            self,
            loc: _Node, nb: _Node,
            cell_size_px: float,
            prev_angle: float,
            map_resolution: float,
            is_global_fallback: bool) -> float:
        """计算从 loc 到 nb 的能量值

        对应 C++ EnergyFunctionalExplorator::E()
        """
        dx = nb.center_x - loc.center_x
        dy = nb.center_y - loc.center_y
        dist_px = math.sqrt(dx * dx + dy * dy)

        # 1. 平移距离
        e = dist_px / cell_size_px

        # 2. 旋转距离
        travel_angle = math.atan2(dy, dx)
        diff_angle = travel_angle - prev_angle
        # 标准化到 [-π, π]
        while diff_angle < -PI:
            diff_angle += 2 * PI
        while diff_angle > PI:
            diff_angle -= 2 * PI

        # ---- 转角约束 (硬约束) ----
        cfg = self.cfg
        if cfg.turn_constraint_enable and not is_global_fallback:
            dist_m = dist_px * map_resolution
            abs_deg = abs(diff_angle) * 180.0 / PI

            if dist_m <= cfg.turn_constraint_near_dist_m:
                if abs_deg > cfg.turn_constraint_near_max_turn_deg:
                    return cfg.turn_constraint_prohibit_energy
            else:
                allowed = cfg.turn_constraint_neighbor_max_turn_deg
                if is_global_fallback:
                    denom = max(1e-9,
                                cfg.turn_constraint_fallback_relax_dist_m
                                - cfg.turn_constraint_near_dist_m)
                    t = (dist_m - cfg.turn_constraint_near_dist_m) / denom
                    t = max(0.0, min(1.0, t))
                    allowed = (cfg.turn_constraint_neighbor_max_turn_deg
                               + (cfg.turn_constraint_fallback_max_turn_deg
                                  - cfg.turn_constraint_neighbor_max_turn_deg) * t)
                if abs_deg > allowed:
                    return cfg.turn_constraint_prohibit_energy

        e += abs(diff_angle) * PI_2_INV

        # 5. 横向移动奖励
        abs_dx = abs(dx)
        abs_dy = abs(dy)
        ratio = abs_dx / (abs_dx + abs_dy + 1e-6)
        e += 8.0 - 1.5 * ratio

        return e

    def _plan_path(
            self,
            nodes: List[List[_Node]],
            start_rc: Tuple[int, int],
            coverage_width_px: float,
            map_resolution: float
    ) -> List[Tuple[float, float]]:
        """贪心路径规划主循环

        对应 C++ getExplorationPath Phase III.ii

        Returns:
            旋转坐标系下的路径点列表 [(x, y), ...]
        """
        cfg = self.cfg
        sr, sc = start_rc
        start_node = nodes[sr][sc]

        path: List[Tuple[float, float]] = [
            (float(start_node.center_x), float(start_node.center_y))
        ]
        start_node.visited = True

        last_r, last_c = sr, sc
        prev_angle = 0.0  # 初始角度: x 正方向

        # 确定初始旅行角度 (基于起始节点的邻居)
        last = nodes[last_r][last_c]
        for nr, nc in last.neighbor_indices:
            nb = nodes[nr][nc]
            if nb.obstacle:
                continue
            # 水平右邻
            if nb.center_y == last.center_y and nb.center_x > last.center_x:
                prev_angle = 0.0
                break
            # 水平左邻
            if nb.center_y == last.center_y and nb.center_x < last.center_x:
                prev_angle = PI
                break
            # 垂直上邻
            if nb.center_y < last.center_y and nb.center_x == last.center_x:
                prev_angle = -0.5 * PI
                break
            # 垂直下邻
            if nb.center_y > last.center_y and nb.center_x == last.center_x:
                prev_angle = 0.5 * PI
                break

        while True:
            last = nodes[last_r][last_c]

            # 1) 尝试从直接邻居中选择
            best_energy = 1e10
            best_rc: Optional[Tuple[int, int]] = None

            for nr, nc in last.neighbor_indices:
                nb = nodes[nr][nc]
                if nb.obstacle or nb.visited:
                    continue
                e = self._energy(
                    last, nb, coverage_width_px, prev_angle,
                    map_resolution, False)
                if (cfg.turn_constraint_enable
                        and e >= cfg.turn_constraint_prohibit_energy):
                    continue
                if e < best_energy:
                    best_energy = e
                    best_rc = (nr, nc)

            # 2) 全局 fallback
            if best_rc is None:
                best_energy = 1e10
                for r in range(len(nodes)):
                    for c in range(len(nodes[r])):
                        nb = nodes[r][c]
                        if nb.obstacle or nb.visited:
                            continue
                        e = self._energy(
                            last, nb, coverage_width_px, prev_angle,
                            map_resolution, True)
                        if (cfg.turn_constraint_enable
                                and e >= cfg.turn_constraint_prohibit_energy):
                            continue
                        if e < best_energy:
                            best_energy = e
                            best_rc = (r, c)

                if best_rc is None:
                    logger.warning(
                        "No feasible next node. Terminating with partial "
                        "path (%d points).", len(path))
                    break

            # 前进到下一个节点
            nr, nc = best_rc
            nxt = nodes[nr][nc]
            prev_angle = math.atan2(
                nxt.center_y - last.center_y,
                nxt.center_x - last.center_x)
            path.append((float(nxt.center_x), float(nxt.center_y)))
            nxt.visited = True
            last_r, last_c = nr, nc

        return path

    # ==============================================================
    #  VI. 路径反旋转
    # ==============================================================
    @staticmethod
    def _transform_path_back(
            fov_path: List[Tuple[float, float]],
            R: np.ndarray
    ) -> List[Tuple[float, float]]:
        """将旋转坐标系下的路径变换回原始坐标系

        对应 C++ RoomRotator::transformPathBackToOriginalRotation
        """
        if not fov_path:
            return []

        pts = np.array(fov_path, dtype=np.float32).reshape(1, -1, 2)
        R_inv = cv2.invertAffineTransform(R)
        transformed = cv2.transform(pts, R_inv)[0]

        return [(float(p[0]), float(p[1])) for p in transformed]
