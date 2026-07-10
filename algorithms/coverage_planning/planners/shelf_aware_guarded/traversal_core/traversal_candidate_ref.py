"""遍历候选身份标识。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TraversalCandidateRef:
  """候选 cell 的轻量身份包装，避免不同模块重复持有可变元信息。"""

  cell_id: str

  @classmethod
  def from_cell_id(cls, cell_id: str) -> "TraversalCandidateRef":
    """把任意可转换的 cell id 标准化为字符串候选引用。
    
    统一键类型后，状态字典与日志对齐，避免 int/str 混用造成比较错配。
    
    Args:
        cell_id: 上游可解析为字符串的 cell 标识。
        
    Returns:
        TraversalCandidateRef: 标准化后的候选身份。
    """
    return cls(cell_id=str(cell_id))
