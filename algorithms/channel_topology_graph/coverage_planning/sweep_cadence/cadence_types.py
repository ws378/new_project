"""Sweep cadence 的上下文、过程态与公共语义 helper。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from ...contracts import (
    SweepCadenceRoute,
    SweepCadenceSegment,
    SweepGraphBuildInfo,
    SweepGraphNode,
    SweepGraphSweep,
    SweepTransitionCandidateItem,
)
from ..sweep_graph.sweep_graph_build import resolve_sweep_transition_candidates

@dataclass(frozen=True)
class CadenceContext:
    """greedy cadence 求解期只读上下文。"""

    sweeps: tuple[SweepGraphSweep, ...]
    transitions: tuple[SweepTransitionCandidateItem, ...]
    sweep_by_id: dict[int, SweepGraphSweep]
    node_by_id: dict[int, SweepGraphNode]
    outgoing: dict[tuple[int, str], list[SweepTransitionCandidateItem]]


@dataclass
class GreedyRouteState:
    """greedy 扩张过程中的 route 累积状态。"""

    start_sweep_id: int
    start_end_type: str
    current_sweep_id: int
    current_exit_end: str
    previous_motion_type: str
    sweep_sequence: list[int]
    segments: list[SweepCadenceSegment]
    covered_sweeps: set[int]
    repeat_count: int
    connector_depth: int
    connector_cost: float
    transition_cost: float


class GreedyAction(TypedDict, total=False):
    """从当前 route 末端可执行的一步动作。"""

    primitive_type: str
    transition: SweepTransitionCandidateItem
    next_sweep_id: int
    next_exit_end: str
    transition_id: int
    motion_type: str
    connection_kind: str
    candidate_source: str
    selection_level: str
    is_repeat_coverage_transition: bool
    connector_depth: int
    connector_cost: float
    foldback_penalty: float
    same_sweep: bool
    same_edge: bool
    rank_gap: int
    trace_tags: tuple[str, ...]
    source_trace_label: str


# 这些 helper 不是“额外抽象层”，而是 cadence 主链必须复用的统一口径：
# - route 统计口径
# - 端点/运动语义口径
# - connector 预算口径
# 如果把它们散到 actions/solver/repair 各处，会重新回到历史上的重复实现问题。


def count_transition_segments(segments: tuple[SweepCadenceSegment, ...] | list[SweepCadenceSegment]) -> int:
    """统计 route 里真正的 transition 段数量。"""

    return int(sum(1 for item in segments if str(item.get("primitive_type")) == "transition"))



def route_transition_ids(route: SweepCadenceRoute) -> tuple[int, ...]:
    """从 route.segments 提取正式 transition id 序列。"""

    transition_ids: list[int] = []
    for item in route.get("segments", ()):  # 只认正式 transition 段，不把 foldback 算进去。
        if str(item.get("primitive_type")) != "transition":
            # 这里跳过的不是“无关字段”，而是 route 内部的 solver 级辅助 primitive。
            # foldback 不对应 sweep-graph 正式候选，混进来会污染 route 对外暴露的 transition 轨迹。
            continue
        transition_id = item.get("transition_id")
        if transition_id is None:
            # 没有 transition_id 的段无法回溯到正式 candidate 真值，
            # 这里宁可丢掉，也不伪造一个占位 id 破坏外部 compare/trace 语义。
            continue
        transition_ids.append(int(transition_id))
    return tuple(transition_ids)



def build_cadence_context(sweep_graph_build_info: SweepGraphBuildInfo) -> CadenceContext:
    """把 sweep graph build 正式结果规范化成 greedy solver 可直接读取的索引。"""

    sweep_graph_info = sweep_graph_build_info.sweep_graph_info
    sweeps = tuple(sweep_graph_info.get("sweeps", ()))
    if not sweeps:
        raise ValueError("sweep graph has no sweeps")
    transitions = resolve_sweep_transition_candidates(sweep_graph_build_info)
    outgoing: dict[tuple[int, str], list[SweepTransitionCandidateItem]] = {}
    for transition in transitions:
        # outgoing 以 `(from_sweep_id, from_end_type)` 为键，表达“站在某 sweep 某出口端时能走哪些 transition”。
        outgoing.setdefault((int(transition["from_sweep_id"]), str(transition["from_end_type"])), []).append(transition)
    nodes = tuple(sweep_graph_info.get("nodes", ()))
    return CadenceContext(
        sweeps=sweeps,
        transitions=transitions,
        sweep_by_id={int(item["sweep_id"]): item for item in sweeps},
        node_by_id={int(item["node_id"]): item for item in nodes},
        outgoing=outgoing,
    )



def is_dead_end_like_sweep(context: CadenceContext, sweep_id: int) -> bool:
    """判断 sweep 是否表现为单端无后继的 dead-end 类节点。"""

    # 这里的 dead-end-like 判定只看 cadence transition 出口，不回头读 topology 节点度数。
    # 因为 cadence 层关心的是"从 sweep 两端还能不能继续扩出去"，而不是原拓扑节点长什么样。
    src_degree = len(context.outgoing.get((int(sweep_id), "src"), ()))
    dst_degree = len(context.outgoing.get((int(sweep_id), "dst"), ()))
    return bool(src_degree == 0 or dst_degree == 0)


def route_from_state(state: GreedyRouteState, route_id: int) -> SweepCadenceRoute:
    """把 greedy 求解状态压平成正式 cadence route 结构。"""

    sweep_sequence = [int(item) for item in state.sweep_sequence]
    segments = tuple(state.segments)
    return {
        "route_id": int(route_id),
        "sweep_sequence": sweep_sequence,
        "segments": segments,
        "start_sweep_id": int(sweep_sequence[0]),
        "end_sweep_id": int(sweep_sequence[-1]),
        "start_end_type": str(state.start_end_type),
        "end_end_type": str(state.current_exit_end),
        "sweep_count": int(len(sweep_sequence)),
        "transition_count": count_transition_segments(segments),
        "segment_count": int(len(segments)),
        "connector_depth": int(state.connector_depth),
        "transition_cost": float(state.transition_cost),
        "connector_cost": float(state.connector_cost),
    }



def opposite_end_type(end_type: str) -> str:
    """返回相对端口名。"""

    return "dst" if str(end_type) == "src" else "src"



def transition_motion_type(item: dict, default: str = "straight") -> str:
    """读取 transition 或 action 的统一运动语义。"""

    raw = str(item.get("motion_type", default))
    return "foldback" if raw == "foldback" else raw



def transition_selection_level(item: dict, default: str = "weak_keep") -> str:
    """读取 transition 的统一选择档位。"""

    return str(item.get("selection_level", default))



def cadence_motion_priority(motion_type: str, previous_motion_type: str) -> tuple[int, int]:
    """给 cadence 选择下一跳时提供主导运动语义优先级。"""

    # 这里表达的是“若多个动作都合法，哪种运动语义更适合连续执行”。
    # 合法性已经在 candidate/build action 阶段完成，这里只负责任何地方都一致的排序主序。
    motion = str(motion_type)
    prev = str(previous_motion_type)
    if motion == "straight":
        return (0, 0)
    if motion == prev and motion in {"left_turn", "right_turn"}:
        return (1, 0)
    if motion in {"left_turn", "right_turn", "lateral"}:
        return (2, 0)
    if motion == "foldback":
        return (3, 0)
    return (4, 0)



def sweep_role_priority_value(sweep: SweepGraphSweep | dict) -> float:
    """把 sweep 的“边缘程度”压成一个可比较的角色优先级分。"""

    if not sweep:
        return 1e6
    # side_level：一条 sweep 在所属 coverage lane 的横向排布里，离“中心 sweep”有几层，负责“离中心多远”
    # 是离中心的“离散层级”

    side_level = abs(int(sweep.get("side_level", 0)))
    # 这条 sweep 相对当前 coverage lane 中心参考线的平均横向偏移量，单位是米 m。
    # side_level 是离散层级，mean_offset_m 是连续几何偏移；
    # 这里给一个稳定弱权重，只负责细粒度打破同层级平手。
    mean_offset = abs(float(sweep.get("mean_offset_m", 0.0)))
    return float(side_level + 2.0 * mean_offset)


def transition_follows_same_coverage_lane(
    transition: SweepTransitionCandidateItem | dict,
    sweep_by_id: dict[int, SweepGraphSweep] | dict[int, dict],
) -> bool:
    """判断一条 transition 是否仍在同一 coverage lane 内部延续。

    同 lane 是 cadence 排序里的弱偏好，不是合法性条件。
    它只能在 transition 自身风险、端点距离和总分之后参与打破平手，
    避免跨 group 场景下把未对齐的 rank/role 信息误当成 pair 质量。
    """

    # from/to 两端必须都能回查到 sweep 元数据，否则不能擅自推断它是同 lane 延续。
    from_sweep = sweep_by_id.get(int(transition.get("from_sweep_id", -1)))
    to_sweep = sweep_by_id.get(int(transition.get("to_sweep_id", -1)))
    if from_sweep is None or to_sweep is None:
        return False
    # coverage_lane_id 是 group 内共享排序框架的唯一依据；
    # 只有它一致时，rank/offset/side 这类局部角色字段才具备可比语境。
    return bool(int(from_sweep.get("coverage_lane_id", -1)) == int(to_sweep.get("coverage_lane_id", -2)))


def transition_target_role_priority(
    transition: SweepTransitionCandidateItem | dict,
    sweep_by_id: dict[int, SweepGraphSweep] | dict[int, dict],
) -> float:
    """只在 transition 两端共享 lane frame 时读取目标 sweep 角色优先级。

    `side_level / mean_offset_m` 只描述 sweep 在自身 coverage lane 内的角色。
    跨 coverage lane / group 时尚未建立 rank frame 对齐，不能让目标 sweep 的单体角色
    进入 pair 连接质量、连接器成本或跨 group 排序。
    """

    if not transition_follows_same_coverage_lane(transition, sweep_by_id):
        # 跨 group 时返回 0.0，不是说目标 sweep 没有角色，
        # 而是说这个角色不能参与当前 pair 的连接质量比较。
        return 0.0
    return sweep_role_priority_value(sweep_by_id.get(int(transition.get("to_sweep_id", -1)), {}))



def choose_cadence_start_state(
    uncovered_sweep_ids: set[int],
    sweep_by_id: dict[int, SweepGraphSweep],
    outgoing_transitions: dict[tuple[int, str], list[SweepTransitionCandidateItem]],
) -> tuple[int, str, str]:
    """为下一条 greedy route 选择起始 sweep 与进入/离开端口。"""

    best_key: tuple[int, float, float, float, int] | None = None
    best_state: tuple[int, str, str] | None = None
    for sweep_id in sorted(uncovered_sweep_ids):
        sweep = sweep_by_id[int(sweep_id)]
        for entry_end_type, exit_end_type in (("src", "dst"), ("dst", "src")):
            successor_count = int(
                sum(
                    1
                    for item in outgoing_transitions.get((int(sweep_id), str(exit_end_type)), ())
                    if int(item["to_sweep_id"]) in uncovered_sweep_ids
                )
            )
            # 起点选择优先找“更容易继续扩出去”的 sweep，而不是局部最低风险 sweep。
            key = (
                successor_count,
                -sweep_role_priority_value(sweep),
                float(sweep["path_length_m"]),
                -abs(float(sweep.get("mean_offset_m", 0.0))),
                -int(sweep_id),
            )
            if best_key is None or key > best_key:
                best_key = key
                best_state = (int(sweep_id), str(entry_end_type), str(exit_end_type))
    if best_state is None:
        # 走到这里通常意味着 `uncovered_sweep_ids` 为空，或 sweep_by_id/outgoing 主索引不自洽。
        raise ValueError("failed to choose cadence start state")
    return best_state



def greedy_covered_connector_max_depth(solver_config: dict[str, Any]) -> int:
    """读取已覆盖连接器允许的最大深度。"""

    return max(0, int(solver_config.get("covered_connector_max_depth", 2)))



def greedy_covered_connector_max_cost(solver_config: dict[str, Any]) -> float:
    """读取已覆盖连接器允许的最大累计成本。"""

    return max(0.0, float(solver_config.get("covered_connector_max_cost", 12.0)))



def greedy_foldback_penalty() -> float:
    """返回受控回折的固定代价。"""

    return 12.0



def greedy_foldback_risk_limit(solver_config: dict[str, Any]) -> float:
    """读取允许执行回折的代理风险上限。"""

    return max(0.0, float(solver_config.get("foldback_risk_limit", 5.0)))



def covered_connector_step_cost(
    *,
    transition: SweepTransitionCandidateItem,
    sweep_by_id: dict[int, SweepGraphSweep] | dict[int, dict],
    previous_motion_type: str,
) -> float:
    """估计穿过已覆盖 sweep 作为连接器时的一步成本。"""

    # connector 成本仍保持三项线性叠加：
    # 1. 转向不连续代价
    # 2. transition 自身风险
    # 3. 同 lane frame 内穿越边缘 sweep 的附加代价
    # 这样 reachability/action 两处共用时，调参语义不会分裂。
    turn_penalty = float(
        1.5
        * cadence_motion_priority(
            motion_type=transition_motion_type(transition, "straight"),
            previous_motion_type=str(previous_motion_type),
        )[0]
    )
    # risk_score 是 sweep_graph 候选层已经收口过的局部风险。
    # 跨 group transition 主要来自端点距离、端点转角和局部可行性；
    # 同 group 横移 transition 才主要来自 rank_gap。
    risk_penalty = float(transition.get("risk_score", 0.0))
    # 目标 sweep 的 side/offset 角色只在同 coverage lane 内有共享参考系。
    # 跨 group repeat connector 不能因为目标更“居中”而压过 pair 几何质量。
    edge_penalty = float(0.5 * transition_target_role_priority(transition, sweep_by_id))
    return float(turn_penalty + risk_penalty + edge_penalty)

__all__ = (
    'CadenceContext',
    'GreedyAction',
    'GreedyRouteState',
    'build_cadence_context',
    'cadence_motion_priority',
    'choose_cadence_start_state',
    'count_transition_segments',
    'covered_connector_step_cost',
    'greedy_covered_connector_max_cost',
    'greedy_covered_connector_max_depth',
    'greedy_foldback_penalty',
    'greedy_foldback_risk_limit',
    'is_dead_end_like_sweep',
    'opposite_end_type',
    'route_from_state',
    'route_transition_ids',
    'sweep_role_priority_value',
    'transition_follows_same_coverage_lane',
    'transition_target_role_priority',
    'transition_motion_type',
    'transition_selection_level',
)
