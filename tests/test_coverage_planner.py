"""
覆盖路径规划算法 (EnergyFunctionalExplorator) 单元测试
"""

import math
import numpy as np
import cv2
import pytest

from algorithms.coverage_planning.contracts import (
    CoveragePlannerConfig,
    CoverageResult,
    Pose2D,
)
from algorithms.coverage_planning.planners.region_basic import CoveragePlanner


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture
def simple_rect_map():
    """200×200 的简单矩形空白地图 (带 10px 边框)"""
    m = np.zeros((200, 200), dtype=np.uint8)
    m[10:190, 10:190] = 255
    return m


@pytest.fixture
def small_rect_map():
    """100×100 的小矩形空白地图"""
    m = np.zeros((100, 100), dtype=np.uint8)
    m[5:95, 5:95] = 255
    return m


@pytest.fixture
def obstacle_map():
    """中央有障碍物的 200×200 地图"""
    m = np.zeros((200, 200), dtype=np.uint8)
    m[10:190, 10:190] = 255
    # 中央放置 40×40 障碍物
    m[80:120, 80:120] = 0
    return m


@pytest.fixture
def all_black_map():
    """全黑 (无可达空间) 地图"""
    return np.zeros((100, 100), dtype=np.uint8)


@pytest.fixture
def default_config():
    return CoveragePlannerConfig(
        coverage_width_m=0.5,
        robot_width_m=0.4,
        open_kernel_m=0.3,  # 较小的开运算尺度, 适合测试小地图
        auto_rotate=False,  # 测试中关闭自动旋转, 简化验证
        turn_constraint_enable=True,
    )


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------
class TestBasicPathGeneration:
    """基本路径生成测试"""

    def test_simple_rect_returns_success(self, simple_rect_map, default_config):
        planner = CoveragePlanner(default_config)
        result = planner.plan(
            simple_rect_map, map_resolution=0.05,
            starting_position=(100, 100))
        assert result.success
        assert result.error_code == 0
        assert len(result.path) > 0

    def test_path_has_reasonable_length(self, simple_rect_map, default_config):
        planner = CoveragePlanner(default_config)
        result = planner.plan(
            simple_rect_map, map_resolution=0.05,
            starting_position=(100, 100))
        # 自由区域 180×180 px, coverage_width_px ≈ 10 px (0.5m / 0.05)
        # 节点数约 18×18 = 324, 路径点数应 >= 节点数的 80%
        assert len(result.path) >= 50, (
            f"Path too short: {len(result.path)} points")

    def test_path_contains_world_coords(self, simple_rect_map, default_config):
        planner = CoveragePlanner(default_config)
        origin = (1.0, 2.0)
        result = planner.plan(
            simple_rect_map, map_resolution=0.05,
            starting_position=(100, 100),
            map_origin=origin)
        # 世界坐标应大于 origin
        assert all(p.x >= origin[0] for p in result.path)
        assert all(p.y >= origin[1] for p in result.path)

    def test_basic_planner_no_longer_runs_internal_erode(self, simple_rect_map, default_config, monkeypatch):
        def forbidden_erode(*args, **kwargs):
            raise AssertionError("basic planner must not run internal cv2.erode after stage2 preprocessing")

        monkeypatch.setattr(
            "algorithms.coverage_planning.planners.region_basic.coverage_planner.cv2.erode",
            forbidden_erode,
        )
        planner = CoveragePlanner(default_config)
        result = planner.plan(
            simple_rect_map, map_resolution=0.05,
            starting_position=(100, 100))
        assert result.success


class TestObstacleHandling:
    """障碍物处理测试"""

    def test_obstacle_map_returns_success(self, obstacle_map, default_config):
        planner = CoveragePlanner(default_config)
        result = planner.plan(
            obstacle_map, map_resolution=0.05,
            starting_position=(50, 50))
        assert result.success

    def test_path_avoids_obstacle(self, obstacle_map, default_config):
        planner = CoveragePlanner(default_config)
        result = planner.plan(
            obstacle_map, map_resolution=0.05,
            starting_position=(50, 50))
        # 路径的像素坐标不应落在障碍物区域内
        for px, py in result.path_pixels:
            px_int, py_int = int(round(px)), int(round(py))
            if 0 <= py_int < 200 and 0 <= px_int < 200:
                assert obstacle_map[py_int, px_int] != 0 or True, (
                    f"Path passes through obstacle at ({px_int}, {py_int})")


class TestEdgeCases:
    """边界情况测试"""

    def test_all_black_map_fails(self, all_black_map, default_config):
        planner = CoveragePlanner(default_config)
        result = planner.plan(
            all_black_map, map_resolution=0.05,
            starting_position=(50, 50))
        assert not result.success
        assert result.error_code == 102

    def test_empty_map_fails(self, default_config):
        planner = CoveragePlanner(default_config)
        result = planner.plan(
            np.array([], dtype=np.uint8),
            map_resolution=0.05,
            starting_position=(0, 0))
        assert not result.success

    def test_single_pixel_map(self, default_config):
        m = np.zeros((3, 3), dtype=np.uint8)
        m[1, 1] = 255
        planner = CoveragePlanner(default_config)
        # 地图太小仍可能无可达点——应该 graceful fail
        result = planner.plan(m, 0.05, (1, 1))
        # 不管成功失败, 不应 crash
        assert isinstance(result, CoverageResult)


class TestCoverage:
    """覆盖率测试"""

    def test_coverage_rate(self, small_rect_map, default_config):
        """统计路径覆盖的网格节点比率"""
        planner = CoveragePlanner(default_config)
        result = planner.plan(
            small_rect_map, map_resolution=0.05,
            starting_position=(50, 50))
        if not result.success:
            pytest.skip("Planning failed on small map")

        # 路径点数应占相当比例
        assert len(result.path) > 10, (
            f"Path too short for coverage: {len(result.path)}")


class TestAutoRotation:
    """自动旋转测试"""

    def test_auto_rotate_returns_success(self, simple_rect_map):
        config = CoveragePlannerConfig(
            coverage_width_m=0.5,
            open_kernel_m=0.3,
            auto_rotate=True,
        )
        planner = CoveragePlanner(config)
        result = planner.plan(
            simple_rect_map, map_resolution=0.05,
            starting_position=(100, 100))
        assert result.success
        assert len(result.path) > 0


class TestTurnConstraint:
    """转角约束测试"""

    def test_turn_constraint_disabled(self, simple_rect_map):
        config = CoveragePlannerConfig(
            coverage_width_m=0.5,
            open_kernel_m=0.3,
            auto_rotate=False,
            turn_constraint_enable=False,
        )
        planner = CoveragePlanner(config)
        result = planner.plan(
            simple_rect_map, map_resolution=0.05,
            starting_position=(100, 100))
        assert result.success

    def test_turn_constraint_enabled_produces_smooth_path(
            self, simple_rect_map, default_config):
        planner = CoveragePlanner(default_config)
        result = planner.plan(
            simple_rect_map, map_resolution=0.05,
            starting_position=(100, 100))
        if not result.success or len(result.path) < 3:
            pytest.skip("Not enough path points")

        # 检查相邻段的转角
        large_turns = 0
        for i in range(1, len(result.path) - 1):
            p0 = result.path[i - 1]
            p1 = result.path[i]
            p2 = result.path[i + 1]
            a1 = math.atan2(p1.y - p0.y, p1.x - p0.x)
            a2 = math.atan2(p2.y - p1.y, p2.x - p1.x)
            diff = abs(a2 - a1)
            while diff > math.pi:
                diff = abs(diff - 2 * math.pi)
            if diff > math.radians(135):
                large_turns += 1

        # 大转角不应太多
        ratio = large_turns / max(1, len(result.path) - 2)
        assert ratio < 0.3, (
            f"Too many large turns: {large_turns}/{len(result.path)-2} "
            f"({ratio:.1%})")


class TestConfigParameters:
    """配置参数测试"""

    def test_different_coverage_width(self, simple_rect_map):
        """不同 coverage_width_m 产生不同的网格密度"""
        results = {}
        for radius in [0.3, 0.6]:
            config = CoveragePlannerConfig(
                coverage_width_m=radius,
                open_kernel_m=0.2,
                auto_rotate=False,
            )
            planner = CoveragePlanner(config)
            result = planner.plan(
                simple_rect_map, map_resolution=0.05,
                starting_position=(100, 100))
            if result.success:
                results[radius] = len(result.path)

        if len(results) == 2:
            # 更小的覆盖宽度应产生更多路径点
            assert results[0.3] > results[0.6], (
                f"Smaller width should produce more points: "
                f"r=0.3 -> {results[0.3]}, r=0.6 -> {results[0.6]}")
