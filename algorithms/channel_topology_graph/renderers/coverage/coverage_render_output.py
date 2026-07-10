"""CoveragePlanning 渲染输出编排层。"""

from __future__ import annotations

from pathlib import Path

from ...contracts import CoveragePlanningResult, GeometryPreparationResult
from .coverage_render_canvas import write_image as write_image
from .coverage_render_cadence_debug import (
    render_sweep_cadence_classification_inputs_debug,
    render_sweep_cadence_connection_rules_debug,
    render_sweep_cadence_debug,
)
from .coverage_render_final_debug import (
    render_final_coverage_path_debug,
    render_junction_connection_summary,
    write_junction_connection_detail_visualizations,
)
from .coverage_render_summary import (
    render_coverage_lane_effective_region_summary,
    render_coverage_lane_territory_summary,
    render_coverage_lanes_summary,
    render_coverage_sweeps_summary,
)
from .coverage_render_sweep_debug import (
    render_sweep_node_chain_debug,
    render_sweep_node_snap_overlay,
    render_sweep_port_view_debug,
    render_sweep_transition_candidate_debug,
)


def write_rendered_panel(
    output_dir: Path,
    filename: str,
    renderer,
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    render_scale: int,
) -> str:
    """执行单张 panel 渲染并写盘，返回输出路径字符串。"""

    # 所有 coverage panel 都遵循同一套“render -> write -> 返回路径”流程。
    # 抽成 helper 后，装配层只需要维护清单，不再重复铺样板代码。
    # renderer 接口也因此被约束成统一签名，后续扩展新 panel 更直接。
    image = renderer(geometry_result, result, render_scale)
    path = output_dir / filename
    # 文件名由调用方传入，这里只负责落盘，不再掺杂命名规则判断。
    write_image(path, image)
    return str(path)



__all__ = ["write_rendered_panel", "write_coverage_planning_visualizations"]


def write_coverage_planning_visualizations(
    geometry_result: GeometryPreparationResult,
    result: CoveragePlanningResult,
    output_dir: str | Path,
    render_scale: int = 8,
) -> dict[str, str | tuple[str, ...]]:
    """写出 CoveragePlanning 当前轮可视化图。"""

    # 输出目录始终由这里统一创建，调用方只提供根目录。
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 绝大多数 panel 只是不同 renderer 的并列输出。
    # 因而这里把“业务 key / 文件名 / renderer”整理成一张清单统一迭代。
    panel_specs = (
        ("coverage_lanes_summary", "coverage_lanes_summary.png", render_coverage_lanes_summary),
        ("coverage_lane_territory_summary", "coverage_lane_territory_summary.png", render_coverage_lane_territory_summary),
        ("coverage_lane_effective_region_summary", "coverage_lane_effective_region_summary.png", render_coverage_lane_effective_region_summary),
        ("coverage_sweeps_summary", "coverage_sweeps_summary.png", render_coverage_sweeps_summary),
        ("sweep_node_chain_debug", "sweep_node_chain_debug.png", render_sweep_node_chain_debug),
        ("sweep_node_snap_overlay", "sweep_node_snap_overlay.png", render_sweep_node_snap_overlay),
        ("sweep_port_view_debug", "sweep_port_view_debug.png", render_sweep_port_view_debug),
        ("sweep_transition_candidate_debug", "sweep_transition_candidate_debug.png", render_sweep_transition_candidate_debug),
        ("sweep_cadence_debug", "sweep_cadence_debug.png", render_sweep_cadence_debug),
        ("sweep_cadence_classification_inputs_debug", "sweep_cadence_classification_inputs_debug.png", render_sweep_cadence_classification_inputs_debug),
        ("sweep_cadence_connection_rules_debug", "sweep_cadence_connection_rules_debug.png", render_sweep_cadence_connection_rules_debug),
        ("final_coverage_path_debug", "final_coverage_path_debug.png", render_final_coverage_path_debug),
        ("junction_connection_summary", "junction_connection_summary.png", render_junction_connection_summary),
    )
    # 清单顺序就是默认写盘顺序。
    # 这样比对目录产物时，人眼看到的顺序和主流程理解顺序一致。
    # key 同时承担返回字典索引的职责，因此这里保持和历史产物名一致。
    panel_paths: dict[str, str] = {}
    for key, filename, renderer in panel_specs:
        # 每张图都共享同一套输入对象和 render_scale。
        # 因而新增 panel 时通常只需补一条 spec，而不必改主流程结构。
        panel_paths[key] = write_rendered_panel(output_dir, filename, renderer, geometry_result, result, render_scale)

    # detail 图单独输出到子目录，因为它是一组按 node 切分的多文件结果。
    detail_dir = output_dir / "junction_connection_details"
    detail_dir.mkdir(parents=True, exist_ok=True)
    # detail 目录统一预建，便于 detail helper 只关心单图内容本身。
    # 这部分不放进 panel_specs，是因为它返回的是路径集合而不是单张图。
    detail_paths = write_junction_connection_detail_visualizations(
        geometry_result=geometry_result,
        result=result,
        output_dir=detail_dir,
        render_scale=render_scale,
    )

    # 返回值使用稳定 key，供 pipeline 或测试侧直接索引具体产物。
    # 这里把 panel 路径和 detail 路径组装到同一份清单，方便上游一次消费。
    # 保持平铺结构也能减少调用方的兼容分支。
    return {
        **panel_paths,
        "junction_connection_detail_paths": tuple(str(item) for item in detail_paths),
    }
