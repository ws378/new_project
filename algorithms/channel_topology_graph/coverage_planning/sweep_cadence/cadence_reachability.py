"""Sweep cadence 的连通性证明与受控回折规则。

职责：
    1. 证明重复覆盖连接器是否还能最终接回未覆盖 sweep。
    2. 约束 solver 级受控 foldback 的触发条件。
    3. 给 greedy 主链提供“存在性”证据，而不是最优路径求解。

边界：
    1. 这里只回答可达/不可达，不比较哪条返回链更优。
    2. 回折只是 reachability 兜底手段，不能替代正式 transition 主链。
"""

from __future__ import annotations

from typing import Any

from .cadence_types import (
    CadenceContext,
    GreedyRouteState,
    covered_connector_step_cost,
    greedy_covered_connector_max_cost,
    greedy_covered_connector_max_depth,
    greedy_foldback_penalty,
    greedy_foldback_risk_limit,
    is_dead_end_like_sweep,
    opposite_end_type,
    sweep_role_priority_value,
    transition_follows_same_coverage_lane,
    transition_motion_type,
    transition_target_role_priority,
)


def can_reach_uncovered(
    *,
    context: CadenceContext,
    sweep_id: int,
    exit_end_type: str,
    allowed_targets: set[int],
    depth: int,
    cost_budget: float,
    previous_motion_type: str,
    visited_states: set[tuple[int, str]],
    allow_foldback: bool,
) -> bool:
    """判断从指定出口出发，能否在预算内最终接回某个未覆盖 sweep。

    这是重复覆盖连接器与受控回折共用的存在性证明器。
    它不关心哪条路更优，只关心“是否存在一条满足深度/成本约束的返回链”。
    """

    # 这个 helper 只回答存在性，不比较哪条重访路径更优。
    # 没有目标、没有深度或没有预算时，递归搜索立刻失败。
    if not allowed_targets:
        # 没有任何未覆盖目标可接时，reachability 问题本身已经失去意义，直接判不可达。
        return False
    if depth < 0 or cost_budget < 0.0:
        # 深度或预算一旦透支，就视为存在性证明失败。
        return False
    direct_transitions = tuple(context.outgoing.get((int(sweep_id), str(exit_end_type)), ()))
    # 这里取的是“从当前 sweep 的当前出口端真正能走出去的正式 outgoing”。
    # 如果这个集合为空，后面就只能靠回折分支尝试恢复可达性。
    # 这里只要存在任意一条一步直达未覆盖目标的边，就足以证明“可达”，
    # 不需要再比较这些直达边里谁更优。
    if any(int(item["to_sweep_id"]) in allowed_targets for item in direct_transitions):
        # 一步直达未覆盖目标时，存在性已经成立，没必要继续往下探。
        return True
    if depth == 0:
        # 走到这里说明“一步直达没命中”且“剩余深度已耗尽”，因此不能再给出可达证明。
        return False

    # 一步直达失败后，才沿 transition connector 继续做有限深度 DFS 证据搜索。
    # 这里的递归语义是“能不能证明最终接回未覆盖 sweep”，不是“这条路是不是最优”。
    for transition in direct_transitions:
        # 下一跳 sweep 是这条 connector 真正通向的覆盖条带。
        next_sweep_id = int(transition["to_sweep_id"])
        # transition 的 `to_end_type` 是进入下一条 sweep 的入口端。
        next_entry_end = str(transition["to_end_type"])
        # 一旦进入下一条 sweep，后续递归要从它的对侧端继续往外搜索。
        next_exit_end = opposite_end_type(next_entry_end)
        # 这里扣减的不是几何距离，而是“重复覆盖连接器”占用预算。
        # 它综合了 transition 风险、目标 sweep 角色以及 motion 连续性，是 reachability 的正式成本口径。
        step_cost = covered_connector_step_cost(
            transition=transition,
            sweep_by_id=context.sweep_by_id,
            previous_motion_type=str(previous_motion_type),
        )
        # `next_budget` 表示走完这一步以后，后续递归还能继续消耗多少连接器预算。
        next_budget = float(cost_budget) - float(step_cost)
        # 递归状态被压缩成 `(next_sweep_id, next_exit_end)`，
        # 因为 reachability 只关心“站在哪条 sweep、将从哪一端继续外扩”。
        next_state = (next_sweep_id, next_exit_end)
        if next_budget < 0.0 or next_state in visited_states:
            # 预算透支说明这条 connector 链已不再合法；
            # 状态已访问说明继续递归只会回到局部环里打转。
            continue
        # visited_states 只记录 `(sweep_id, exit_end)`，
        # 因为 reachability 证明只关心“站在什么 sweep、打算从哪一端离开”。
        # 这就足够阻断局部递归环。
        if can_reach_uncovered(
            context=context,
            sweep_id=next_sweep_id,
            exit_end_type=next_exit_end,
            allowed_targets=allowed_targets,
            depth=int(depth) - 1,
            cost_budget=next_budget,
            # motion 语义也要沿递归向后传，保证后续 connector 成本继续基于真实转向上下文计算。
            previous_motion_type=transition_motion_type(transition, previous_motion_type),
            visited_states={*visited_states, next_state},
            allow_foldback=allow_foldback,
        ):
            # 只要任意一条递归分支能证明“最终能回到某个未覆盖目标”，
            # 当前状态就应整体判为可达，无需再看别的 sibling 分支。
            return True

    # 常规重复连接都证明失败后，最后才允许进入受控回折回退。
    # 这保证回折始终是 reachability 的兜底手段，而不是与正常 transition 平权竞争的主动作。
    if not allow_foldback:
        # 当调用方明确禁止回折时，常规 transition 分支一旦全部失败，就必须在这里终止证明。
        return False
    # `allow_controlled_foldback` 不是在“真正执行回折”，
    # 而是在问：当前这个局面有没有资格把一次翻端视作仍有意义的 reachability 兜底动作。
    if not allow_controlled_foldback(
        context=context,
        state=None,
        sweep_id=int(sweep_id),
        current_exit_end=str(exit_end_type),
        # 这里显式改成 `foldback`，表示后续风险/可达性判定应按“刚做过一次翻端”来理解 motion 上下文。
        previous_motion_type="foldback",
        allowed_targets=allowed_targets,
        solver_config={
            # 这里把当前剩余搜索额度原样传给 foldback 判定器，
            # 它只能在“现有剩余额度内”证明自己仍有价值，不能额外借预算。
            "covered_connector_max_depth": int(depth),
            "covered_connector_max_cost": float(max(cost_budget, 0.0)),
        },
    ):
        # 如果连受控回折的前置条件都不成立，就说明当前出口在本证明口径下已经彻底走死。
        return False
    # 回折后的下一递归状态，仍然站在当前 sweep 上，只是改成从另一端继续离开。
    alternate_exit_end = opposite_end_type(str(exit_end_type))
    alternate_state = (int(sweep_id), alternate_exit_end)
    if alternate_state in visited_states:
        # 同一 sweep 的另一端如果已经在递归栈里出现过，再回去只会形成双端往返环。
        return False
    # 进入回折分支时，会显式扣掉 foldback 代价，并禁止在后续递归里再次回折。
    # 这避免“回折接回折”的链条把 reachability 证明拖成不受控搜索。
    return can_reach_uncovered(
        context=context,
        sweep_id=int(sweep_id),
        exit_end_type=alternate_exit_end,
        allowed_targets=allowed_targets,
        depth=int(depth) - 1,
        # 回折本身也要消耗一层搜索深度，避免“原地换端”被无限视为免费操作。
        cost_budget=float(cost_budget) - greedy_foldback_penalty(),
        # 一旦已经走进回折分支，后续递归的运动上下文必须切到 foldback，
        # 否则 connector 成本会继续沿用旧 motion 语义，导致预算解释失真。
        previous_motion_type="foldback",
        visited_states={*visited_states, alternate_state},
        # 这里显式关掉二次回折，避免“翻端 -> 再翻端”的递归在证明器里膨胀。
        allow_foldback=False,
    )


def can_exit_reach_uncovered_without_foldback(
    *,
    context: CadenceContext,
    sweep_id: int,
    exit_end_type: str,
    allowed_targets: set[int],
    depth: int,
    cost_budget: float,
    previous_motion_type: str,
    visited_states: set[tuple[int, str]],
) -> bool:
    """判断从指定出口出发、且不借助回折时能否接回未覆盖 sweep。

    这个函数是 reachability 的更严格版本。
    它用于证明：即使不借助 solver 级回折动作，当前出口仍有办法重新接回未覆盖目标。
    """

    # 这个包装器的价值在于把“禁止回折”变成一个显式命名语义，
    # 调用方读到函数名就知道这里在证明“纯 transition 语义下是否可达”。
    # 它本身不引入新逻辑，只是把 `allow_foldback=False` 这个业务意图固定下来。
    return can_reach_uncovered(
        context=context,
        sweep_id=int(sweep_id),
        exit_end_type=str(exit_end_type),
        allowed_targets=allowed_targets,
        depth=int(depth),
        cost_budget=float(cost_budget),
        # 这里原样透传 previous_motion_type，
        # 目的是让纯 transition 证明仍然延续真实的 motion 上下文。
        previous_motion_type=str(previous_motion_type),
        visited_states=visited_states,
        allow_foldback=False,
    )


def allow_controlled_foldback(
    *,
    context: CadenceContext,
    state: GreedyRouteState | None,
    sweep_id: int,
    current_exit_end: str,
    previous_motion_type: str,
    allowed_targets: set[int],
    solver_config: dict[str, Any],
) -> bool:
    """判断当前 sweep 内是否允许做一次受控回折。

    允许回折必须同时满足三类条件：
    1. 当前 sweep 角色与节点语义允许；
    2. alternate 出口存在可解释的候选；
    3. 回折后仍能在预算内接回未覆盖 sweep。
    """

    del state
    # 这里故意不使用完整 route state，
    # 因为回折判定要回答的是“当前 sweep 在局部拓扑上是否允许翻端”，而不是整条 route 历史是否优美。
    # 先卡 sweep 角色，再看 alternate 出口、节点类型、代理风险和后续可达性。
    # 任何一项不满足，都不允许把回折升级成 solver 可用动作。
    if not is_dead_end_like_sweep(context, sweep_id):
        # 非 dead-end-like sweep 仍有更正常的前进出口，不应该轻易把 solver 语义改成翻端回退。
        return False
    # 受控回折必须建立在“另一端确实还有正式 outgoing 候选”这个事实之上，
    # 否则回折只是形式上换端，并不能真正恢复可达性。
    alternate_exit_end = opposite_end_type(str(current_exit_end))
    alternate_transitions = tuple(context.outgoing.get((int(sweep_id), str(alternate_exit_end)), ()))
    if not alternate_transitions:
        # 回折后的另一端如果根本没有正式 outgoing，这次翻端就只是原地掉头，没有恢复连通性的价值。
        return False
    sweep = context.sweep_by_id.get(int(sweep_id), {})
    if sweep_role_priority_value(sweep) > 1.5:
        # 高优先级 sweep 往往属于主走廊或更稳定主线，不希望轻易在这里做 solver 级回折。
        return False
    if context.node_by_id:
        # 这里从 alternate 出口可用 transition 的 `via_node_id` 反查节点类型，
        # 目的是验证这次回折是否发生在有明确拓扑解释的节点语境里。
        node_types = {
            str(context.node_by_id.get(int(item.get("via_node_id", -1)), {}).get("node_type", ""))
            for item in alternate_transitions
        }
        if not ({"junction", "dead_end"} & node_types):
            # 若 alternate 出口既不像 junction 也不像 dead_end，就说明回折缺少可靠拓扑解释。
            return False
    best = min(
        alternate_transitions,
        key=lambda item: (
            # alternate 出口也必须先按 transition 自身质量排序。
            # rank_gap 只在同 coverage lane 内部有共享 frame，不能主导跨 group 回折代理。
            float(item.get("risk_score", 0.0)),
            float(item.get("endpoint_distance_m", 0.0)),
            float(item.get("total_score", 0.0)),
            -float(item.get("local_feasibility_score", 0.0)),
            0 if transition_follows_same_coverage_lane(item, context.sweep_by_id) else 1,
            transition_target_role_priority(item, context.sweep_by_id),
        ),
    )
    # 这里只挑 alternate 出口里“最像靠谱续接”的那条边做风险代理，
    # 因为回折判定需要的是保守证据，不是把所有后继都展开评分。
    # endpoint_distance_m：这条 transition 关联的两个 sweep，在几何上“最近能靠多近”的端点距离，单位是米。
    proxy_cost = (
        float(best.get("risk_score", 0.0))
        + 0.2 * float(best.get("endpoint_distance_m", 0.0))
        + 0.2 * float(best.get("total_score", 0.0))
        # role 在回折代理成本里只允许同 lane frame 生效；
        # 跨 group 时目标 sweep 单体角色不能进入 pair 代理成本。
        + 0.25 * transition_target_role_priority(best, context.sweep_by_id)
    )
    if proxy_cost > greedy_foldback_risk_limit(solver_config):
        # 一旦“最优代理后继”都超了回折风险阈值，就没必要再为回折开口。
        return False
    # 即便本地看起来能回折，也必须证明换边后还能重新接回未覆盖 sweep。
    # 否则这次回折只是在原地打转，没有 solver 价值。
    if not can_exit_reach_uncovered_without_foldback(
        context=context,
        sweep_id=int(sweep_id),
        exit_end_type=str(alternate_exit_end),
        allowed_targets=allowed_targets,
        depth=greedy_covered_connector_max_depth(solver_config),
        cost_budget=greedy_covered_connector_max_cost(solver_config),
        previous_motion_type="foldback",
        visited_states={(int(sweep_id), str(alternate_exit_end))},
    ):
        # 这里证明失败时，语义是“即便翻到另一端，也无法在纯 transition 口径下重新接回未覆盖目标”。
        return False
    # 最后的收口条件表达的是：
    # 1. 如果上一跳已经在做 foldback，则允许继续沿这条回折语义求证；
    # 2. 否则只对较低角色优先级 sweep 开放回折，避免主线 sweep 轻易被 solver 改成回退逻辑。
    return bool(
        str(previous_motion_type) == "foldback"
        or sweep_role_priority_value(context.sweep_by_id.get(int(sweep_id), {})) <= 1.0
    )


def can_revisit_transition_reach_uncovered(
    *,
    context: CadenceContext,
    sweep_id: int,
    exit_end_type: str,
    allowed_targets: set[int],
    depth: int,
    cost_budget: float,
    previous_motion_type: str,
    visited_states: set[tuple[int, str]],
) -> bool:
    """判断经过有限重复覆盖连接后，是否仍能抵达某个未覆盖 sweep。

    这是重复覆盖 transition 的合法性证明包装器。
    调用方已经接受“会临时进入已覆盖 sweep”这一事实，
    这里要回答的是：这种重访是否还有继续向前覆盖的意义。
    """

    # 这里允许回折，是因为调用方已经确认自己进入了“重复覆盖连接器”语义，
    # 需要更强的存在性证明来说明这次重访不是死胡同。
    return can_reach_uncovered(
        context=context,
        sweep_id=int(sweep_id),
        exit_end_type=str(exit_end_type),
        allowed_targets=allowed_targets,
        depth=int(depth),
        cost_budget=float(cost_budget),
        previous_motion_type=str(previous_motion_type),
        visited_states=visited_states,
        allow_foldback=True,
    )

__all__ = (
    'allow_controlled_foldback',
    'can_exit_reach_uncovered_without_foldback',
    'can_reach_uncovered',
    'can_revisit_transition_reach_uncovered',
)
