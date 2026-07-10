"""GeometryPreparation 测试。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from algorithms.channel_topology_graph.renderers.geometry_renderers import (
    write_geometry_preparation_visualizations,
)
from algorithms.channel_topology_graph.stages.geometry_preparation import (
    build_geometry_preparation,
    validate_geometry_preparation_result,
)


def build_cross_map(height: int = 80, width: int = 80) -> np.ndarray:
    """构造一个带短枝的十字通道测试图。"""

    raw = np.zeros((height, width), dtype=np.uint8)
    raw[10:70, 36:44] = 255
    raw[36:44, 10:70] = 255
    raw[56:61, 56:62] = 255
    return raw


def test_build_geometry_preparation_returns_consistent_result() -> None:
    """正常输入应返回闭环一致的结果对象。"""

    raw = build_cross_map()
    result = build_geometry_preparation(
        raw_map={"gray": raw, "resolution_m_per_px": 0.05},
        config={"open_kernel_px": 1, "short_side_branch_px": 6, "min_free_component_px": 4},
    )

    assert result.gray.shape == raw.shape
    assert result.free_mask.shape == raw.shape
    assert result.skeleton_pruned_mask.shape == raw.shape
    assert len(result.skeleton_pixels_rc) > 0
    assert result.validation_info is not None
    assert result.validation_info["skeleton_pixel_count"] == len(result.skeleton_pixels_rc)


def test_build_geometry_preparation_accepts_color_image() -> None:
    """彩色图输入应被统一转成单通道灰度。"""

    gray = build_cross_map()
    color = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    result = build_geometry_preparation(
        raw_map={"image": color, "resolution_m_per_px": 0.05},
        config={"open_kernel_px": 1, "short_side_branch_px": 6},
    )

    assert result.gray.ndim == 2
    assert result.gray.dtype == np.uint8


def test_region_mask_constraint_is_respected() -> None:
    """区域掩膜应同时驱动裁剪框和最终 region_mask。"""

    raw = build_cross_map(height=60, width=90)
    region = np.zeros_like(raw, dtype=np.uint8)
    region[5:55, 5:85] = 255
    result = build_geometry_preparation(
        raw_map={"gray": raw, "resolution_m_per_px": 0.05},
        region_constraint=region,
        config={"open_kernel_px": 1, "short_side_branch_px": 6},
    )

    assert result.crop_box_px == (5, 5, 55, 85)
    assert result.gray.shape == (50, 80)
    assert int(np.count_nonzero(result.region_mask)) == int(np.count_nonzero(region[5:55, 5:85]))


def test_crop_boundary_is_forced_to_obstacle_when_region_touches_crop_edge() -> None:
    """局部 crop 外边界一旦进入 active region，应被强制解释成 obstacle。"""

    raw = np.zeros((40, 60), dtype=np.uint8)
    raw[5:35, 10:50] = 255
    region = np.zeros_like(raw, dtype=np.uint8)
    region[5:35, 10:50] = 255

    result = build_geometry_preparation(
        raw_map={"gray": raw, "resolution_m_per_px": 0.05},
        region_constraint=region,
        config={"open_kernel_px": 1, "short_side_branch_px": 6},
    )

    assert int(np.count_nonzero(result.free_mask[0, :])) == 0
    assert int(np.count_nonzero(result.free_mask[-1, :])) == 0
    assert int(np.count_nonzero(result.free_mask[:, 0])) == 0
    assert int(np.count_nonzero(result.free_mask[:, -1])) == 0
    assert int(np.count_nonzero(result.obstacle_mask[0, :])) > 0
    assert int(np.count_nonzero(result.obstacle_mask[-1, :])) > 0
    assert int(np.count_nonzero(result.obstacle_mask[:, 0])) > 0
    assert int(np.count_nonzero(result.obstacle_mask[:, -1])) > 0


def test_short_side_branch_pruning_reduces_skeleton_pixels() -> None:
    """带毛刺的骨架在修剪后应减少骨架像素。"""

    raw = build_cross_map()
    result = build_geometry_preparation(
        raw_map={"gray": raw, "resolution_m_per_px": 0.05},
        config={"open_kernel_px": 1, "short_side_branch_px": 6},
    )

    raw_pixels = int(np.count_nonzero(result.skeleton_mask))
    pruned_pixels = int(np.count_nonzero(result.skeleton_pruned_mask))
    assert pruned_pixels <= raw_pixels
    assert result.debug_info is not None
    assert "pruning" in result.debug_info


def test_prepared_map_input_skips_internal_open_and_free_island_cleanup(monkeypatch) -> None:
    """formal prepared_map 输入不应再次触发产品级 opening / 小孤岛清理。"""

    raw = build_cross_map()
    region = np.zeros_like(raw, dtype=np.uint8)
    region[10:70, 10:70] = 255

    def forbidden_open(*args, **kwargs):
        raise AssertionError("prepared_map path must not re-run morphology_open")

    def forbidden_cleanup(*args, **kwargs):
        raise AssertionError("prepared_map path must not re-run remove_small_free_islands")

    monkeypatch.setattr(
        "algorithms.channel_topology_graph.geometry_preparation.preprocessing.core.remove_small_free_islands",
        forbidden_cleanup,
    )
    monkeypatch.setattr(
        "algorithms.channel_topology_graph.geometry_preparation.preprocessing.space_masks.morphology_open",
        forbidden_open,
    )

    result = build_geometry_preparation(
        raw_map=raw,
        region_constraint=region,
        config={
            "input_is_prepared_map": True,
            "resolution_m_per_px": 0.05,
            "open_kernel_m": 0.4,
            "short_side_branch_px": 6,
        },
    )

    assert result.gray.shape == (60, 60)
    assert result.after_open_mask.shape == (60, 60)
    assert len(result.skeleton_pixels_rc) > 0


def test_validation_rejects_non_binary_mask() -> None:
    """字段校验必须拒绝非 0/255 掩膜。"""

    gray = np.zeros((10, 10), dtype=np.uint8)
    bad_mask = np.full((10, 10), 7, dtype=np.uint8)
    skeleton = np.zeros((10, 10), dtype=np.uint8)
    skeleton[5, 5] = 255

    with pytest.raises(ValueError, match="must be binary 0/255"):
        validate_geometry_preparation_result(
            region_mask=bad_mask,
            gray=gray,
            free_mask=bad_mask,
            obstacle_mask=np.zeros_like(gray),
            after_open_mask=bad_mask,
            skeleton_mask=skeleton,
            skeleton_pruned_mask=skeleton,
            crop_box_px=(0, 0, 10, 10),
            skeleton_pixels_rc=((5, 5),),
            resolution_m_per_px=0.05,
        )


def test_validation_rejects_mismatched_skeleton_pixels() -> None:
    """骨架像素坐标与掩膜不一致时必须报错。"""

    gray = np.zeros((10, 10), dtype=np.uint8)
    mask = np.full((10, 10), 255, dtype=np.uint8)
    skeleton = np.zeros((10, 10), dtype=np.uint8)
    skeleton[5, 5] = 255

    with pytest.raises(ValueError, match="skeleton point missing in mask|must match skeleton_pruned_mask exactly"):
        validate_geometry_preparation_result(
            region_mask=mask,
            gray=gray,
            free_mask=mask,
            obstacle_mask=np.zeros_like(gray),
            after_open_mask=mask,
            skeleton_mask=skeleton,
            skeleton_pruned_mask=skeleton,
            crop_box_px=(0, 0, 10, 10),
            skeleton_pixels_rc=((5, 5), (1, 1)),
            resolution_m_per_px=0.05,
        )


def test_summary_viz_only_writes_summary_artifacts(tmp_path: Path) -> None:
    """只开 summary 时不应生成 detail 目录。"""

    raw = build_cross_map()
    output_dir = tmp_path / "summary_only"
    result = build_geometry_preparation(
        raw_map={"gray": raw, "resolution_m_per_px": 0.05},
        config={
            "open_kernel_px": 1,
            "short_side_branch_px": 6,
        },
    )

    viz = write_geometry_preparation_visualizations(
        result=result,
        output_dir=output_dir,
        summary_viz=True,
        detail_viz=False,
        render_scale=4,
    )
    assert viz["summary_panel_path"] is not None
    assert viz["detail_dir"] is None
    assert (output_dir / "geometry_preparation_summary.png").exists()
    assert not (output_dir / "details").exists()


def test_detail_viz_writes_iteration_panels(tmp_path: Path) -> None:
    """打开 detail 时应写出逐轮修剪细节图。"""

    raw = build_cross_map()
    output_dir = tmp_path / "detail"
    result = build_geometry_preparation(
        raw_map={"gray": raw, "resolution_m_per_px": 0.05},
        config={
            "open_kernel_px": 1,
            "short_side_branch_px": 6,
        },
    )

    viz = write_geometry_preparation_visualizations(
        result=result,
        output_dir=output_dir,
        summary_viz=False,
        detail_viz=True,
        render_scale=4,
    )
    assert viz["summary_panel_path"] is None
    assert viz["detail_dir"] is not None
    detail_dir = Path(viz["detail_dir"])
    assert detail_dir.exists()
    assert any(detail_dir.glob("pruning_iter_*.png"))
