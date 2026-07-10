"""JunctionRebuild 渲染正式入口。

真实职责：
    对外稳定暴露 junction 领域的 summary/detail/native-geometry 渲染能力，
    具体绘制原语和 overlay 组合逻辑继续下沉到 `renderers.junction/` 内部实现子包。

约束：
    本文件是领域级正式入口，不是临时兼容层；
    只保留 junction 领域导出，不扩大到包级聚合职责。
"""

from .junction.junction_render_views import (
    render_junction_rebuild_native_geometry,
    render_junction_rebuild_summary,
    write_junction_rebuild_details,
    write_junction_rebuild_visualizations,
)

__all__ = (
    # 写盘入口
    "write_junction_rebuild_visualizations",
    # summary / native geometry / detail
    "render_junction_rebuild_summary",
    "render_junction_rebuild_native_geometry",
    "write_junction_rebuild_details",
)
