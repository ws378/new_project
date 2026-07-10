"""渲染层包级正式入口。

本包正式保留三层结构：

1. 包级入口 `renderers/__init__.py`
   - 面向调用方提供最常用的三类写盘入口。
2. 领域级入口 `coverage_renderers.py` / `geometry_renderers.py` / `junction_renderers.py`
   - 面向需要某一领域细粒度渲染能力的调用方。
3. 内部实现子包 `coverage/` / `junction/`
   - 只承载各自领域的具体绘图与组合逻辑，不直接作为正式调用面。

约束：
    包级入口只做稳定导出，不承担额外聚合逻辑。
"""

from .coverage_renderers import write_coverage_planning_visualizations
from .geometry_renderers import write_geometry_preparation_visualizations
from .junction_renderers import write_junction_rebuild_visualizations

__all__ = (
    "write_coverage_planning_visualizations",
    "write_geometry_preparation_visualizations",
    "write_junction_rebuild_visualizations",
)
