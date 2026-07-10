"""遍历 provenance 的动作来源与边角色枚举。"""

from __future__ import annotations


MOVE_SOURCE_START = "start"
MOVE_SOURCE_NORMAL_NEIGHBOR = "normal_neighbor"
MOVE_SOURCE_REVISIT_BRIDGE = "revisit_bridge"
MOVE_SOURCE_GLOBAL_FALLBACK = "global_fallback"
MOVE_SOURCE_DERIVED_FINAL_PATH = "derived_final_path"

EDGE_ROLE_START = "start"
EDGE_ROLE_COVERAGE_LANE = "coverage_lane"
EDGE_ROLE_REVISIT_BRIDGE = "revisit_bridge"
EDGE_ROLE_FALLBACK_TRANSFER = "fallback_transfer"
EDGE_ROLE_DERIVED_FINAL_SEGMENT = "derived_final_segment"
EDGE_ROLE_UNKNOWN = "unknown"

RAW_MOVE_SOURCE_VALUES = [
  MOVE_SOURCE_START,
  MOVE_SOURCE_NORMAL_NEIGHBOR,
  MOVE_SOURCE_REVISIT_BRIDGE,
  MOVE_SOURCE_GLOBAL_FALLBACK,
]

TRAVERSAL_PHASE_VALUES = [
  # 遍历阶段名复用 move source 名称，start 为启动阶段专用的合成值。
  MOVE_SOURCE_NORMAL_NEIGHBOR,
  MOVE_SOURCE_REVISIT_BRIDGE,
  MOVE_SOURCE_GLOBAL_FALLBACK,
]

RAW_EDGE_ROLE_VALUES = [
  EDGE_ROLE_START,
  EDGE_ROLE_COVERAGE_LANE,
  EDGE_ROLE_REVISIT_BRIDGE,
  EDGE_ROLE_FALLBACK_TRANSFER,
]


def edge_role_for_move_source(move_source: str) -> str:
  """将 move_source 映射为 edge role。
  
  明确覆盖/桥接/回退边界，避免统计口径混淆。
  """
  if move_source == MOVE_SOURCE_NORMAL_NEIGHBOR:
    # normal neighbor 代表局部拓扑下一跳，直接映射为 coverage_lane 便于后续分段统计。
    return EDGE_ROLE_COVERAGE_LANE
  if move_source == MOVE_SOURCE_REVISIT_BRIDGE:
    # revisit 是重复访问桥接，不是纯覆盖段，独立统计以便与主覆盖段分离。
    return EDGE_ROLE_REVISIT_BRIDGE
  if move_source == MOVE_SOURCE_GLOBAL_FALLBACK:
    # 全局 fallback 表示跨区域重定位，映射为转移边类型以保留后验诊断。
    return EDGE_ROLE_FALLBACK_TRANSFER
  return EDGE_ROLE_UNKNOWN
