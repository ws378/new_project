"""静态覆盖图的只读遍历访问器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..graph_build.coverage_graph import CoverageCell, CoverageGraphView


@dataclass(frozen=True)
class TraversalGraphAccess:
  """静态覆盖图与历史节点镜像之间的只读访问入口，统一边界与 id 转换。"""

  coverage_graph: CoverageGraphView
  legacy_mirrors_by_cell_id: Mapping[str, Any]
  accessible_cell_ids_in_graph_order: tuple[str, ...]

  @classmethod
  def from_coverage_graph(cls, coverage_graph: CoverageGraphView) -> "TraversalGraphAccess":
    """从正式覆盖图直接构建访问器。

    在线规划只读取 `CoverageGraphView`，不再为旧 Node 镜像付出构造成本；legacy mirror
    仅在 artifact/debug 场景按需绑定，避免兼容结构反向拖慢主路径。
    """
    return cls(
      coverage_graph=coverage_graph,
      legacy_mirrors_by_cell_id={},
      accessible_cell_ids_in_graph_order=coverage_graph.accessible_cell_ids(),
    )

  @classmethod
  def bind_legacy_mirror(
    cls,
    *,
    legacy_mirror_matrix: Sequence[Sequence[Any]],
    coverage_graph: CoverageGraphView,
  ) -> "TraversalGraphAccess":
    """从 legacy 镜像矩阵构建唯一映射，保证图单元与镜像一一对应。"""
    # 绑定时一次性校验 legacy 与 coverage graph 一一对应，防止下游出现空引用。
    legacy_mirrors_by_cell_id: dict[str, Any] = {}
    for row in legacy_mirror_matrix:
      # 逐行扫描 legacy 镜像，保证每个 legacy 节点都完成映射。
      for legacy_mirror in row:
        cell_id = str(legacy_mirror.stable_id)
        if cell_id in legacy_mirrors_by_cell_id:
          # 重复 stable_id 会导致调试与回放引用错位，直接失败更容易定位。
          raise AssertionError(f"Duplicate traversal cell id: {cell_id}")
        if cell_id not in coverage_graph.cells_by_id:
          # 避免 legacy 比 coverage graph 多出节点，导致游标访问到不存在对象。
          raise AssertionError(f"Legacy node missing traversal graph cell: {cell_id}")
        legacy_mirrors_by_cell_id[cell_id] = legacy_mirror
    for cell_id in coverage_graph.accessible_cell_ids():
      if str(cell_id) not in legacy_mirrors_by_cell_id:
        # 覆盖图新增可达节点未注册镜像，先中断避免静默 fallback。
        raise AssertionError(f"Traversal graph cell missing legacy node: {cell_id}")
    return cls(
      coverage_graph=coverage_graph,
      legacy_mirrors_by_cell_id=legacy_mirrors_by_cell_id,
      accessible_cell_ids_in_graph_order=coverage_graph.accessible_cell_ids(),
    )

  def legacy_node_mirror(self, cell_id: str) -> Any:
    """按 graph cell id 查询 legacy 镜像；不存在则抛出不可恢复错误。"""
    # 运行时只通过 graph cell id 查询镜像，避免直接持有并修改行列索引。
    if not self.legacy_mirrors_by_cell_id:
      raise AssertionError("Traversal graph legacy mirror is unavailable in online graph-only mode")
    try:
      return self.legacy_mirrors_by_cell_id[str(cell_id)]
    except KeyError as exc:
      # key 不存在说明图状态与输入构建链路不一致，直接抛错避免误读。
      raise AssertionError(f"Traversal graph cell missing legacy node: {cell_id}") from exc

  def cell(self, cell_id: str) -> CoverageCell:
    """读取覆盖图只读 cell 数据，作为后续统计与路径构建的统一来源。"""
    return self.coverage_graph.cell(str(cell_id))

  def planning_point_px_for_cell(self, cell_id: str) -> tuple[int, int]:
    """返回格子规划点像素坐标，统一转为 int 供坐标计算使用。"""
    cell = self.cell(cell_id)
    return (int(cell.planning_point_px[0]), int(cell.planning_point_px[1]))

  def accessible_cell_ids(self) -> tuple[str, ...]:
    """返回图内可达格子 id 的固定顺序视图，避免遍历次序抖动。"""
    return self.accessible_cell_ids_in_graph_order

  def accessible_neighbor_cell_ids(self, cell_id: str) -> tuple[str, ...]:
    """返回指定格子的可访问邻居 id，统一转为字符串供上层查询."""
    return tuple(str(neighbor_id) for neighbor_id in self.cell(cell_id).accessible_neighbor_cell_ids)

  def unvisited_accessible_cell_ids(self, traversal_state: Any) -> list[str]:
    """返回当前状态下尚未访问的可达格子列表，用于阶段统计与 fallback 回退。"""
    # 固定顺序遍历可达集合，确保回退统计每次运行可复现。
    return [
      str(cell_id)
      for cell_id in self.accessible_cell_ids_in_graph_order
      if not traversal_state.is_visited_cell(cell_id)
    ]
