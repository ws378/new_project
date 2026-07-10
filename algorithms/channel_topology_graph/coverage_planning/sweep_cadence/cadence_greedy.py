"""Sweep cadence greedy 求解主链。

职责：
    1. 在 sweep cadence 上构造首轮覆盖 routes。
    2. 用统一状态机封装 transition / foldback 两类 primitive。
    3. 把重复覆盖连接器、through 语义和局部 lookahead 收进同一套贪心排序。

边界：
    1. 这里只做首轮 greedy 铺路，不负责后处理 merge/repair。
    2. 这里的 foldback 是 solver 兜底 primitive，不是 sweep graph 正式 transition。
"""

from __future__ import annotations

from typing import Any

from ...contracts import SweepCadenceRoute
from .cadence_reachability import allow_controlled_foldback, can_revisit_transition_reach_uncovered
from .cadence_route_ops import route_breaks_through_semantics
from .cadence_types import (
    CadenceContext,
    GreedyAction,
    GreedyRouteState,
    cadence_motion_priority,
    choose_cadence_start_state,
    covered_connector_step_cost,
    greedy_covered_connector_max_cost,
    greedy_covered_connector_max_depth,
    opposite_end_type,
    route_from_state,
    sweep_role_priority_value,
    transition_follows_same_coverage_lane,
    transition_motion_type,
    transition_target_role_priority,
    transition_selection_level,
)


def make_route_state(
    *,
    sweep_id: int,
    start_end_type: str,
    exit_end_type: str,
    previous_motion_type: str,
    connector_depth: int = 0,
    connector_cost: float = 0.0,
) -> GreedyRouteState:
    """按统一口径构造 greedy route 过程态。

    这里创建的是 solver 运行时真值，不是最终 route。
    它需要同时携带当前位置、覆盖集合、段列表和连接器累计成本，
    供后续 legality、排序和 route 落盘复用。
    """

    # greedy 主链上的所有中间状态都必须落成同一份结构化真值，
    # 这样 legality 检查、排序、route 物化才能共享同一套字段解释。
    return GreedyRouteState(
        # start_* 字段在整条 route 生命周期内不再变化，用来保留这条 route 的原始起点真值。
        start_sweep_id=int(sweep_id),
        start_end_type=str(start_end_type),
        # current_* 字段则表示 solver 此刻正站在什么 sweep、准备从哪一端继续离开。
        current_sweep_id=int(sweep_id),
        current_exit_end=str(exit_end_type),
        previous_motion_type=str(previous_motion_type),
        # 初始状态下，route 只包含起点 sweep，本轮还没有任何 segment。
        sweep_sequence=[int(sweep_id)],
        segments=[],
        # 起点 sweep 会立刻被记入 covered 集，避免同一条 route 刚起步就把自己当未覆盖目标。
        covered_sweeps={int(sweep_id)},
        repeat_count=0,
        connector_depth=int(connector_depth),
        connector_cost=float(connector_cost),
        # 初始 route 还没有写入任何 transition/foldback primitive，因此累计代价为 0。
        transition_cost=0.0,
    )


def greedy_local_state_key(state: GreedyRouteState) -> tuple[int, str, frozenset[int]]:
    """构造 greedy 局部去环使用的状态键。

    这是一个“搜索局面键”，不是 route 唯一标识。
    只要局面键重复，继续扩展大概率会回到同类局部循环，
    因此当前 route 可以在这里安全截断。
    """

    # 局部去环不关心完整 route 文本，只关心：
    # 1. 当前站在谁身上；
    # 2. 当前从哪一端离开；
    # 3. 当前已覆盖集合长什么样。
    # 这三者相同，就意味着继续扩展时会落到同类局部搜索局面。
    return (
        int(state.current_sweep_id),
        str(state.current_exit_end),
        frozenset(int(item) for item in state.covered_sweeps),
    )


def lookahead_gain(
    *,
    context: CadenceContext,
    current_sweep_id: int,
    current_exit_end: str,
    previous_motion_type: str,
    allowed_targets: set[int],
    solver_config: dict[str, Any],
    connector_depth: int,
    connector_cost: float,
) -> tuple[int, float]:
    """做一个浅层 lookahead，回答后面还有没有像样的续接链。

    返回值不是最终路径分，而是一个用于排序的辅助证据：
    `probe_count` 表示合法后继数量，`probe_gain` 表示最佳后继的大致质量。
    它只服务于贪心选边，不承担全局优化职责。
    """

    # 这是一个刻意受限的浅层探测，只提供 greedy 排序证据，不承担全局最优搜索职责。
    if not allowed_targets:
        # 没有任何未覆盖目标时，lookahead 已经失去“评估后劲”的对象，
        # 直接按零后继、零收益返回即可。
        return (0, 0.0)
    # probe_state 不是把当前 route 真正推进一步，
    # 而是构造一个“如果我已经站在这个后继 sweep 上”的局部观察点。
    probe_state = make_route_state(
        sweep_id=int(current_sweep_id),
        # probe 的 start 端取当前 exit 的对侧，表示“我已从这一端进入了该 sweep”。
        start_end_type=opposite_end_type(str(current_exit_end)),
        exit_end_type=str(current_exit_end),
        previous_motion_type=str(previous_motion_type),
        connector_depth=int(connector_depth),
        connector_cost=float(connector_cost),
    )
    # 这里不是“真的往后走一步”，而是问：
    # 如果我已经站在这个候选后继 sweep 上，接下来还能不能继续构造出像样的合法动作集合。
    actions = build_greedy_legal_actions(
        context=context,
        state=probe_state,
        allowed_targets=allowed_targets,
        solver_config=solver_config,
    )
    if not actions:
        # 一个后继如果走上去以后立即陷入“没有任何合法下一跳”，
        # 那它在 lookahead 视角下就没有后劲，直接记成零收益。
        return (0, 0.0)

    def local_gain(action: GreedyAction) -> float:
        # lookahead 的分数只是“后劲证据”。
        # 只要能证明某个后继更可能继续吃到未覆盖 sweep，它就应该在 greedy 排序里占优势。
        # 只要存在可接受的前进动作，回折就不应该在排序上抢到前面。
        if str(action["primitive_type"]) != "transition":
            # lookahead 只给“继续向前覆盖”的正式 transition 计收益。
            # 纯 foldback 即便合法，也只代表原地换端，不应在后劲评分里拿高分。
            return -12.0
        transition = action["transition"]
        next_sweep = context.sweep_by_id[int(action["next_sweep_id"])]
        # strong_keep 在 lookahead 里直接拿更高基线分，
        # 表示“这条后继不仅能走，而且更像 sweep graph 主线想保留的正式连接”。
        gain = float(4.0 if transition_selection_level(transition) == "strong_keep" else 2.0)
        if bool(action.get("is_repeat_coverage_transition", False)):
            # lookahead 会主动惩罚重复覆盖连接器，
            # 避免“虽然能接回去，但需要先绕旧区域”的后继把直行主线挤掉。
            gain -= 4.0
        # 这里减去 motion 优先级，是把“转向连续性差”显式折进后劲分数。
        gain -= float(
            1.5
            * cadence_motion_priority(
                motion_type=transition_motion_type(transition, "straight"),
                previous_motion_type=str(previous_motion_type),
            )[0]
        )
        if transition_follows_same_coverage_lane(transition, context.sweep_by_id):
            # 只有同 coverage lane 内部，next_sweep 的 role 才具备共享 frame 下的排序意义。
            # 跨 group 时 rank/offset/side 默认未对齐，lookahead 不能让它主导后劲判断。
            gain -= 0.5 * sweep_role_priority_value(next_sweep)
        # 风险越高越扣分；coverage_gain 越高越加分。
        gain -= float(transition.get("risk_score", 0.0))
        gain += 0.5 * float(transition.get("coverage_gain_score", 0.0))
        return gain

    return (len(actions), max(local_gain(action) for action in actions))


def action_priority_key(
    *,
    action: GreedyAction,
    state: GreedyRouteState,
    context: CadenceContext,
    allowed_targets: set[int],
    solver_config: dict[str, Any],
) -> tuple:
    """给 greedy 合法动作生成稳定的统一排序键。

    这里的元组顺序就是 solver 的正式偏好声明。
    只要排序键不变，同一份输入上下文下 greedy 行为就应保持稳定，
    便于基线比对和问题归因。
    """

    primitive_type = str(action["primitive_type"])
    if primitive_type != "transition":
        sweep = context.sweep_by_id[int(state.current_sweep_id)]
        # foldback 永远排在 transition 后面。
        # 即便真的要用回折，也应该在所有正式前进动作都排完之后再比较其细粒度优先级。
        return (
            3,
            # 这里仍保留 motion 优先级，是为了在多个 fallback foldback 之间维持稳定顺序。
            cadence_motion_priority(
                motion_type=str(action.get("motion_type", "foldback")),
                previous_motion_type=str(state.previous_motion_type),
            ),
            0,
            sweep_role_priority_value(sweep),
            0,
            0.0,
            0.0,
            0.0,
            float(action.get("foldback_penalty", 0.0)),
            int(state.current_sweep_id),
        )

    transition = action["transition"]
    # 下一 sweep 的角色信息只允许在同 coverage lane frame 内作为弱平手项。
    # 真正的连接优先级必须先由 transition 质量、端点几何和局部可行性决定。
    follows_same_lane = transition_follows_same_coverage_lane(transition, context.sweep_by_id)
    # 这里额外做一次浅层 lookahead，
    # 目的不是重跑未来搜索，而是把“走到这个后继以后还有没有像样续接链”折进当前排序键。
    probe_count, probe_gain = lookahead_gain(
        context=context,
        current_sweep_id=int(action["next_sweep_id"]),
        current_exit_end=str(action["next_exit_end"]),
        previous_motion_type=str(action.get("motion_type", "straight")),
        # lookahead 的 allowed_targets 要先去掉当前候选下一跳，
        # 否则会把“我刚走到的这个 sweep”错误地继续当成未来待覆盖收益。
        allowed_targets=set(allowed_targets) - {int(action["next_sweep_id"])},
        solver_config=solver_config,
        connector_depth=int(action.get("connector_depth", 0)),
        connector_cost=float(action.get("connector_cost", 0.0)),
    )
    # 排序键从强约束到弱约束依次表达：
    # 1. selection level 与 motion 优先级；
    # 2. 是否进入重复覆盖连接器；
    # 3. 连接器深度/成本；
    # 4. transition 自身风险、端点几何、总分和局部可行性；
    # 5. 同 lane 延续性、后继潜力和 sweep 角色弱平手项。
    # 只要上层元组顺序稳定，整个 greedy 行为就可复现。
    return (
        0 if transition_selection_level(transition) == "strong_keep" else 1,
        cadence_motion_priority(
            motion_type=transition_motion_type(transition, "straight"),
            previous_motion_type=str(state.previous_motion_type),
        ),
        # 这里把“是否进入重复覆盖连接器”放在很靠前的位置，
        # 是为了保证正常未覆盖前进在主排序上天然压过重访补路。
        1 if bool(action.get("is_repeat_coverage_transition", False)) else 0,
        int(action.get("connector_depth", 0)),
        float(action.get("connector_cost", 0.0)),
        # risk_score / endpoint_distance_m / total_score 是 transition pair 自身质量证据。
        # 它们必须先于 same-lane、role、lookahead，避免跨 group 未对齐 rank/offset 主导连接选择。
        float(transition.get("risk_score", 0.0)),
        float(transition.get("endpoint_distance_m", 0.0)),
        float(transition.get("total_score", 0.0)),
        # local_feasibility_score 越高越好，因此取负号进入升序 tuple。
        -float(transition.get("local_feasibility_score", 0.0)),
        # 同 coverage lane 只是质量之后的弱偏好：同组可复用局部 frame，跨组不抢主序。
        0 if follows_same_lane else 1,
        # coverage_gain_score 表达 candidate 层对连续推进的收益估计，也只能在质量主键之后发挥作用。
        -float(transition.get("coverage_gain_score", 0.0)),
        # lookahead 先比较最佳后劲质量，再比较后继数量，避免“分支多”压过“连接好”。
        -float(probe_gain),
        -int(probe_count),
        # role 值只在同 coverage lane frame 内可比；
        # 跨 group 时这里固定为 0，避免 side/offset 以 tie-break 形式继续影响连接选择。
        transition_target_role_priority(transition, context.sweep_by_id),
        int(action["next_sweep_id"]),
    )


def transition_penalty(*, transition: dict[str, Any], previous_motion_type: str) -> float:
    """计算一条 transition 写入 route 时的累计惩罚。

    这个惩罚是 route 代价累计字段，不是合法性阈值。
    它把 selection level、motion 连续性和局部风险折成统一尺度，
    供后续统计和对比使用。
    """

    # 这里的惩罚不是 legality 过滤，而是 greedy 在多个合法动作之间的比较尺度。
    # 因而它只编码“更想先走谁”的偏好，不负责决定动作能不能出现。
    selection_penalty = float(
        {
            "strong_keep": 0.0,
            "weak_keep": 2.0,
            "weak_keep_fallback": 4.0,
        }.get(transition_selection_level(transition), 6.0)
    )
    # motion_penalty 负责惩罚“当前 motion 语义和上一跳不够顺”的情况。
    # 它不是在识别非法转向，而是在多个合法转向之间表达连续性偏好。
    motion_penalty = float(
        2.5
        * cadence_motion_priority(
            motion_type=transition_motion_type(transition, "straight"),
            previous_motion_type=str(previous_motion_type),
        )[0]
    )
    auxiliary_penalty = float(
        # risk_score 是 sweep-graph 对这条 transition 的局部风险估计。
        float(transition.get("risk_score", 0.0))
        # total_score 本身已经混合了几何与秩序信号，这里只给较小权重，避免重复放大。
        + 0.2 * float(transition.get("total_score", 0.0))
        # coverage_gain_score 越高，说明这条边越像值得保留的主线覆盖连接，因此在惩罚里做抵扣。
        - 0.5 * float(transition.get("coverage_gain_score", 0.0))
    )
    # 三类惩罚共同表达“这条边虽然合法，但有多不值得优先走”。
    # 这里不区分硬约束和软约束，所有结果都会累计进 route 的 transition_cost。
    return float(selection_penalty + motion_penalty + auxiliary_penalty)


def apply_greedy_action(*, state: GreedyRouteState, action: GreedyAction) -> GreedyRouteState:
    """把一个 greedy 动作真正写入状态机。

    这是 cadence solver 的唯一状态推进口。
    无论调用方是在做真实扩展还是 legality 试探，
    都必须经过这里，避免出现多套不一致的状态更新逻辑。
    """

    # action applier 是 sweep cadence 状态推进的唯一正式落点。
    # 所有被 solver 选中的动作，无论是前进还是回折，都必须先被压成同一套 route state 真值。
    # 这样后面的 through 检查、route 物化和统计口径才不会分裂成两套状态机。
    primitive_type = str(action["primitive_type"])
    if primitive_type == "transition":
        transition = action["transition"]
        next_sweep_id = int(action["next_sweep_id"])
        next_exit_end = str(action["next_exit_end"])
        is_repeat = bool(action.get("is_repeat_coverage_transition", False))
        # transition 动作会真正推进“当前 sweep”“当前出口”“已覆盖集合”和累计惩罚。
        # repeat coverage 只增加 repeat_count，不会把 sweep_sequence 的推进逻辑分叉成另一套。
        return GreedyRouteState(
            start_sweep_id=int(state.start_sweep_id),
            start_end_type=str(state.start_end_type),
            # transition 真正把 solver 当前位置推进到下一条 sweep。
            current_sweep_id=int(next_sweep_id),
            # `current_exit_end` 记录的是下一步准备从这条 sweep 的哪一端继续离开。
            current_exit_end=str(next_exit_end),
            previous_motion_type=str(action.get("motion_type", "straight")),
            # cadence route 的 sweep 顺序是真正执行过的 primitive 结果，不是静态拓扑排序。
            sweep_sequence=[*state.sweep_sequence, int(next_sweep_id)],
            segments=[
                *state.segments,
                {
                    "from_sweep_id": int(state.current_sweep_id),
                    "to_sweep_id": int(next_sweep_id),
                    # `via_node_id` 是这次跨 sweep 连接经过的正式图节点，供后续 final-path/Junction 使用。
                    "via_node_id": int(transition["via_node_id"]),
                    "requires_junction_connection": True,
                    # entry/exit 端型一起定义了“这次是从当前 sweep 哪一端出去、到目标 sweep 后准备从哪一端继续走”。
                    "entry_end_type": str(state.current_exit_end),
                    "exit_end_type": str(next_exit_end),
                    "primitive_type": "transition",
                    # connection_kind / candidate_source 用来保留这条边为什么会被图构建阶段接受的来源证据。
                    "connection_kind": str(action.get("connection_kind", transition.get("connection_kind", "forward"))),
                    "candidate_source": str(action.get("candidate_source", transition.get("candidate_source", "node_projected"))),
                    "is_repeat_coverage_transition": bool(is_repeat),
                    # transition_id 是 route 回溯 sweep-graph candidate 的硬链接，不允许在 cadence 层丢失。
                    "transition_id": int(transition.get("candidate_id", transition.get("transition_id", -1))),
                    # same_sweep / same_edge / rank_gap 都是局部拓扑解释字段，
                    # 后续调试“为什么这次跨接看起来像近邻、像同边翻接”时要靠它们做归因。
                    "same_sweep": bool(action.get("same_sweep", transition.get("same_sweep", False))),
                    "same_edge": bool(action.get("same_edge", transition.get("same_edge", False))),
                    "rank_gap": int(action.get("rank_gap", transition.get("rank_gap", 0))),
                    "selection_level": str(action.get("selection_level", transition.get("selection_level", "weak_keep"))),
                    # trace_tags / source_trace_label 保留候选边筛选轨迹，方便后面做 compare 和问题定位。
                    "trace_tags": tuple(action.get("trace_tags", transition.get("trace_tags", ()))),
                    "source_trace_label": str(action.get("source_trace_label", transition.get("source_trace_label", ""))),
                    "motion_type": str(action.get("motion_type", transition.get("motion_type", "straight"))),
                    "foldback_penalty": 0.0,
                },
            ],
            # 进入新 sweep 就视为已经被当前 route 首次或再次覆盖到。
            covered_sweeps={*state.covered_sweeps, int(next_sweep_id)},
            # repeat_count 只在“走进已覆盖 sweep”时才累加，用来记录连接器使用强度。
            repeat_count=int(state.repeat_count) + (1 if is_repeat else 0),
            connector_depth=int(action.get("connector_depth", 0)),
            connector_cost=float(action.get("connector_cost", 0.0)),
            # transition_cost 是 route 级累计偏好分，不是 sweep graph 原始字段。
            transition_cost=float(state.transition_cost) + transition_penalty(
                transition=transition,
                previous_motion_type=state.previous_motion_type,
            ),
        )

    next_exit_end = str(action["next_exit_end"])
    primitive_penalty = 12.0
    # foldback 不改变 current_sweep_id，也不新增 covered sweep。
    # 它的本质是“在当前 sweep 内部换一个出口端，再给后续前进动作创造机会”。
    return GreedyRouteState(
        start_sweep_id=int(state.start_sweep_id),
        start_end_type=str(state.start_end_type),
        current_sweep_id=int(state.current_sweep_id),
        # foldback 不换 sweep，只把可离开的端切到另一边。
        current_exit_end=str(next_exit_end),
        previous_motion_type=str(action.get("motion_type", "foldback")),
        # 这里仍把当前 sweep 再写入一次 sequence，
        # 因为 route primitive 序列里确实发生了一次“在本 sweep 内翻端”的动作。
        sweep_sequence=[*state.sweep_sequence, int(state.current_sweep_id)],
        segments=[
            *state.segments,
                {
                    "from_sweep_id": int(state.current_sweep_id),
                    "to_sweep_id": int(state.current_sweep_id),
                    # foldback 不穿过真实节点，所以这里固定为 -1，明确它不是图里的正式 transition。
                    "via_node_id": -1,
                    "requires_junction_connection": False,
                    "entry_end_type": str(state.current_exit_end),
                    "exit_end_type": str(next_exit_end),
                    "primitive_type": "foldback",
                "connection_kind": "foldback",
                    "candidate_source": str(action.get("candidate_source", "fallback")),
                    "is_repeat_coverage_transition": False,
                    "transition_id": None,
                    # foldback 天然是 same_sweep；same_edge 允许上层显式标注这次翻端是否仍可视作同边行为。
                    "same_sweep": True,
                    "same_edge": bool(action.get("same_edge", True)),
                    "rank_gap": int(action.get("rank_gap", 0)),
                "selection_level": str(action.get("selection_level", "fallback")),
                "trace_tags": tuple(action.get("trace_tags", ())),
                "source_trace_label": str(action.get("source_trace_label", "fallback_foldback")),
                "motion_type": str(action.get("motion_type", "foldback")),
                "foldback_penalty": float(action.get("foldback_penalty", 0.0)),
            },
        ],
        covered_sweeps=set(state.covered_sweeps),
        repeat_count=int(state.repeat_count),
        connector_depth=0,
        connector_cost=0.0,
        transition_cost=float(state.transition_cost) + primitive_penalty + float(action.get("foldback_penalty", 0.0)),
    )


def build_transition_action(
    *,
    state: GreedyRouteState,
    transition: dict[str, Any],
    allowed_targets: set[int],
    context: CadenceContext,
    solver_config: dict[str, Any],
) -> GreedyAction | None:
    """构造单条 transition 对应的 greedy 动作；若不合法则返回 None。

    这里负责把 sweep-graph transition 真值翻译成 cadence solver 能执行的 primitive。
    同时会在需要时补上“重复覆盖连接器”语义，
    并验证它不会破坏 through 连续性。
    """

    target_sweep_id = int(transition["to_sweep_id"])
    target_entry_end = str(transition["to_end_type"])
    # 一旦从 transition 的 `to_end_type` 进入目标 sweep，
    # 后续 route 继续向外扩张时，应该从它的对侧端离开。
    target_exit_end = opposite_end_type(target_entry_end)
    # 是否 repeat coverage 的判断，不看这条边是不是“旧边”，
    # 而只看它的目标 sweep 当前是否还在全局未覆盖集合里。
    is_repeat_coverage_transition = bool(target_sweep_id not in allowed_targets)
    connector_depth = 0
    connector_cost = 0.0
    if is_repeat_coverage_transition:
        # 进入已覆盖 sweep 时，这一步不再是“正常前进”，而是临时连接器。
        # 因此必须同时累计深度与成本，并证明它最终仍能接回未覆盖 sweep。
        # 这个 step cost 与 reachability 那边的预算口径保持完全一致，
        # 避免“构造动作时合法、递归证明时却按另一套成本计算”。
        connector_step_cost = covered_connector_step_cost(
            transition=transition,
            sweep_by_id=context.sweep_by_id,
            previous_motion_type=str(state.previous_motion_type),
        )
        # connector_depth 控制“连续重访了多少跳已覆盖 sweep”，
        # 防止 solver 为了接回新目标而在旧区域里绕太深。
        connector_depth = int(state.connector_depth) + 1
        # connector_cost 控制“这些重访跳累计花了多少预算”，
        # 防止单步便宜但整体代价很高的连接器链混进来。
        connector_cost = float(state.connector_cost) + float(connector_step_cost)
        if connector_depth > greedy_covered_connector_max_depth(solver_config):
            # 深度超限说明这条连接器链已经太长，不再像一次可接受的临时重访。
            return None
        if connector_cost > greedy_covered_connector_max_cost(solver_config):
            # 成本超限说明虽然可能还能走通，但代价已经超出 cadence 允许的重访预算。
            return None
        if not can_revisit_transition_reach_uncovered(
            context=context,
            sweep_id=target_sweep_id,
            exit_end_type=target_exit_end,
            allowed_targets=allowed_targets,
            depth=greedy_covered_connector_max_depth(solver_config) - connector_depth,
            cost_budget=greedy_covered_connector_max_cost(solver_config) - connector_cost,
            previous_motion_type=transition_motion_type(transition, state.previous_motion_type),
            visited_states={(target_sweep_id, target_exit_end)},
        ):
            # 这里证明失败的语义是：
            # “虽然能先走进已覆盖 sweep，但无法证明它最终还能接回某个未覆盖目标”，
            # 因而这条重复覆盖连接器不能进入正式动作集。
            return None
    # 到这里说明：
    # 1. 这条 transition 在预算内合法；
    # 2. 如果它进入已覆盖 sweep，也已经证明还能重新接回未覆盖目标。
    action: GreedyAction = {
        "primitive_type": "transition",
        "transition": transition,
        # `next_sweep_id` / `next_exit_end` 是 solver 真正推进状态时要写入的新局面。
        "next_sweep_id": int(target_sweep_id),
        "next_exit_end": str(target_exit_end),
        # `transition_id` 让 cadence route 仍能回溯到 sweep-graph 原始 candidate。
        "transition_id": int(transition.get("candidate_id", transition.get("transition_id", -1))),
        "motion_type": transition_motion_type(transition, "straight"),
        # 下面这些字段是把 sweep-graph 证据原样带入 cadence，
        # 后续 route repair、调试和可视化都依赖它们做问题归因。
        "connection_kind": str(transition.get("connection_kind", "forward")),
        "candidate_source": str(transition.get("candidate_source", "node_projected")),
        "selection_level": transition_selection_level(transition),
        "is_repeat_coverage_transition": is_repeat_coverage_transition,
        # connector_* 只在“进入已覆盖 sweep”的场景下有实际值；正常前进时保持 0。
        "connector_depth": int(connector_depth),
        "connector_cost": float(connector_cost),
        "foldback_penalty": 0.0,
        "same_sweep": bool(transition.get("same_sweep", False)),
        "same_edge": bool(transition.get("same_edge", False)),
        "rank_gap": int(transition.get("rank_gap", 0)),
        "trace_tags": tuple(transition.get("trace_tags", ())),
        "source_trace_label": str(transition.get("source_trace_label", "")),
    }
    if not action_preserves_forward_through_semantics(context=context, state=state, action=action):
        # 即便 transition 本身合法，只要一写进当前 route 会破坏 through，就不能作为 cadence 动作。
        return None
    return action


def build_controlled_foldback_action(
    *,
    context: CadenceContext,
    state: GreedyRouteState,
    allowed_targets: set[int],
    solver_config: dict[str, Any],
) -> GreedyAction | None:
    """在无常规动作时，尝试构造受控 foldback 兜底动作。

    受控回折不是图上的正式 transition，而是 solver 层的兜底 primitive。
    它只在正常前进动作全部不可用时才有资格出现，
    用于把当前 sweep 的另一端暴露给后续搜索。
    """

    # 回折永远不是与正常前进并列竞争的主动作。
    # 只有当前端口已经没有可接受前进动作时，才允许在这里尝试构造一个兜底动作。
    current_sweep_id = int(state.current_sweep_id)
    current_exit_end = str(state.current_exit_end)
    alternate_exit_end = opposite_end_type(current_exit_end)
    if not context.outgoing.get((current_sweep_id, alternate_exit_end), ()):
        # 换端以后如果连一条 outgoing 都没有，回折对 solver 没有任何价值。
        return None
    # `allow_controlled_foldback` 负责回答：
    # 在当前 sweep、当前出口、当前目标集合和预算口径下，这次翻端是否仍有结构意义。
    if not allow_controlled_foldback(
        context=context,
        state=state,
        sweep_id=current_sweep_id,
        current_exit_end=current_exit_end,
        previous_motion_type=str(state.previous_motion_type),
        allowed_targets=allowed_targets,
        solver_config=solver_config,
    ):
        # 这里返回 None 的语义不是“回折实现失败”，
        # 而是“当前局面下不允许把回折升级成 solver 可执行动作”。
        return None
    # 这里构造的不是 sweep graph 正式 transition，
    # 而是 cadence solver 自己引入的受控兜底 primitive。
    # 所以它会带 fallback 标签，并显式记录 controlled_fallback trace。
    action: GreedyAction = {
        "primitive_type": "foldback",
        # foldback 只在当前 sweep 内翻端，因此 next_sweep_id 仍是当前 sweep。
        "next_sweep_id": int(current_sweep_id),
        # 真正变化的是下一轮可从哪一端继续向外搜索。
        "next_exit_end": str(alternate_exit_end),
        "transition_id": -1,
        "motion_type": "foldback",
        "connection_kind": "foldback",
        "candidate_source": "fallback",
        "selection_level": "fallback",
        "is_repeat_coverage_transition": False,
        # 这里的 penalty 不是风险评估，而是明确告诉排序器“这是兜底动作，应天然更贵”。
        "foldback_penalty": 1.0,
        "same_sweep": True,
        "same_edge": True,
        "rank_gap": 0,
        "trace_tags": ("controlled_fallback",),
        "source_trace_label": "fallback_foldback",
    }
    if not action_preserves_forward_through_semantics(context=context, state=state, action=action):
        # 受控回折也必须遵守 through 语义，不能因为它是 fallback primitive 就绕过正式检查。
        return None
    return action


def build_greedy_legal_actions(
    *,
    context: CadenceContext,
    state: GreedyRouteState,
    allowed_targets: set[int],
    solver_config: dict[str, Any],
) -> list[GreedyAction]:
    """为当前 greedy 状态枚举所有合法下一跳动作。

    这个函数只负责“枚举 + 过滤”，不负责排序。
    输出集合中的每个动作都已经满足连接器预算和 through 语义约束，
    后续只需要做稳定优先级比较。
    """

    # legal action builder 的职责是“枚举并过滤”，不在这里排序。
    # 先给正常 transition 机会；只有完全没有可走的前进动作时，才考虑受控回折。
    actions: list[GreedyAction] = []
    current_sweep_id = int(state.current_sweep_id)
    current_exit_end = str(state.current_exit_end)
    # 当前 greedy 状态只允许从“当前 sweep + 当前出口端”这一个视角枚举 outgoing。
    direct_transitions = [item for item in context.outgoing.get((current_sweep_id, current_exit_end), ())]
    # `direct_transitions` 是当前出口的全部正式后继；
    # `uncovered_transitions` 则是其中能直接吃到未覆盖 sweep 的更强候选子集。
    uncovered_transitions = [item for item in direct_transitions if int(item["to_sweep_id"]) in allowed_targets]
    # 这一步先做“目标集合裁剪”，再逐条构造动作。
    # 这样下面的 build_transition_action 可以只聚焦单条 transition 的合法性证明。
    # 若当前出口能直达未覆盖 sweep，就只看这批直达候选。
    # 这是为了避免重复覆盖连接器在“明明还能直接向前覆盖”时混进来干扰排序。
    for transition in uncovered_transitions if uncovered_transitions else direct_transitions:
        # 这里逐条把 sweep-graph transition 翻译成 cadence solver 能执行的 GreedyAction。
        # 失败返回 None 的含义是：这条图候选虽然存在，但在当前 route 上下文里并不合法。
        action = build_transition_action(
            state=state,
            transition=transition,
            allowed_targets=allowed_targets,
            context=context,
            solver_config=solver_config,
        )
        if action is not None:
            # 只有通过预算、可达性、through 三层检查的 transition，
            # 才会真正进入当前状态的 legal_actions 集。
            actions.append(action)
    if actions:
        # 只要当前出口已经存在可接受前进动作，就不再让 solver 在本轮考虑 foldback。
        return actions
    # 走到这里说明：
    # 1. 当前出口没有任何可接受的正式前进 transition；
    # 2. 这时才允许尝试构造受控 foldback 兜底动作。
    action = build_controlled_foldback_action(
        context=context,
        state=state,
        allowed_targets=allowed_targets,
        solver_config=solver_config,
    )
    if action is not None:
        # 只有在正常 transition 全部失败后，列表里才可能只剩一个 foldback 兜底动作。
        actions.append(action)
    return actions


def action_preserves_forward_through_semantics(
    *,
    context: CadenceContext,
    state: GreedyRouteState,
    action: GreedyAction,
) -> bool:
    """用试探状态检查动作是否破坏 through 语义。

    这里复用正式 action applier 构造 probe route。
    这样 legality 判断和真实执行使用的是同一套状态推进语义，
    不会出现“能判过但执行后不一致”的分叉。
    """

    # 这里不直接猜 through 会不会被破坏，而是用正式 action applier 构造探测状态。
    # 这样 legality probe 和真正执行动作共用同一套状态推进语义。
    probe_state = apply_greedy_action(state=state, action=action)
    # 这里显式先把 probe state 物化成 route，
    # 再复用正式 through 检查器，避免 legality 逻辑和 route 语义出现两套判断口径。
    probe_route = route_from_state(probe_state, route_id=-1)
    # 返回 True 的含义是“这次动作写进当前 route 后，through 语义仍然成立”；
    # 返回 False 则表示动作本身虽存在，但不允许出现在 cadence 主线里。
    return not route_breaks_through_semantics(probe_route, context)


def expand_greedy_state(
    *,
    context: CadenceContext,
    state: GreedyRouteState,
    allowed_targets: set[int],
    solver_config: dict[str, Any],
) -> GreedyRouteState | None:
    """从当前 route 状态扩一跳，挑选代价最低的合法动作。

    这个 helper 只做一次局部决策。
    route 主循环会反复调用它，逐步把一条 route 扩出来，
    并统一维护 uncovered 集与局部去环状态。
    """

    # 先把“当前局面下所有还能合法执行的下一跳”完整枚举出来。
    # 这一步的结果不是排序后的唯一答案，而是后面单点裁决的候选全集。
    legal_actions = build_greedy_legal_actions(
        context=context,
        state=state,
        allowed_targets=allowed_targets,
        solver_config=solver_config,
    )
    if not legal_actions:
        # 这里返回 None 的语义不是异常，而是“当前 route 已经自然走到头”。
        # 上层 route 主循环看到 None，就应终止这条 route，而不是继续尝试推进。
        return None

    # 排序器是 solver 的唯一选边口。
    # 只要这里稳定，整个 greedy cadence 的行为顺序就是可复现、可审计的。
    action = min(
        legal_actions,
        # 这里不是“随便挑一个最小值”，而是把所有局部证据压进统一排序键后做单点裁决。
        key=lambda item: action_priority_key(
            action=item,
            state=state,
            context=context,
            allowed_targets=allowed_targets,
            solver_config=solver_config,
        ),
    )
    # 到这里，`action` 就是当前局面下经统一排序键裁决出的唯一下一跳。
    # 后面不再额外做别的 legality 判断，直接按正式 action applier 推进状态。
    # expand 只做“一跳选择”，不在这里循环展开。
    # 这样 route 主循环可以统一接管 uncovered 集更新和局部去环。
    return apply_greedy_action(state=state, action=action)


def build_sweep_cadence_routes_greedy(
    context: CadenceContext,
    *,
    solver_config: dict[str, Any],
) -> list[SweepCadenceRoute]:
    """先用 greedy 主线把全部 sweep 至少覆盖一次。

    这是 cadence 阶段的首轮覆盖构建器。
    它优先保证“每个 sweep 至少被一条 route 首次覆盖”，
    后续的 merge、singleton 吸收与端点修补再负责把结构整理得更完整。
    """

    # uncovered 集合表达“当前还没有任何 route 首次覆盖到的 sweep”。
    # greedy 主循环每次都站在这个全局真值上扩 route，而不是只看当前 route 的局部状态。
    uncovered = {int(item["sweep_id"]) for item in context.sweeps}
    routes: list[SweepCadenceRoute] = []
    while uncovered:
        # 每轮都重新从全局未覆盖集合里挑一个起点。
        # 这意味着 solver 构造的是“多条 route 共同覆盖全图”，而不是强行拼成一条超长单路由。
        # `choose_cadence_start_state` 负责在全局未覆盖集合里挑出“最值得新开一条 route”的起点局面。
        # 它返回的不是只有 sweep_id，而是完整的起始进入端与当前可用出口端真值。
        start_sweep_id, start_end_type, available_exit_end = choose_cadence_start_state(
            uncovered_sweep_ids=uncovered,
            sweep_by_id=context.sweep_by_id,
            outgoing_transitions=context.outgoing,
        )
        # 起点的 `start_end_type` 与 `available_exit_end` 不一定相同；
        # 前者记录 route 原始进入端真值，后者记录 solver 此刻准备用来往外扩展的出口端。
        # 起点一旦被选中，就立刻从全局 uncovered 中拿掉，
        # 避免同一 sweep 在后续外层 while 中再次被当成新 route 起点。
        # 一旦起点局面确定，就把它压成统一的 GreedyRouteState，
        # 后续本条 route 的所有扩张、排序、through 检查都围绕这份状态真值推进。
        state = make_route_state(
            sweep_id=int(start_sweep_id),
            start_end_type=str(start_end_type),
            exit_end_type=str(available_exit_end),
            previous_motion_type="start",
        )
        uncovered.remove(int(start_sweep_id))
        # visited_local_states 只在当前 route 内部生效，用来阻断本条 route 的局部闭环。
        visited_local_states: set[tuple[int, str, frozenset[int]]] = {greedy_local_state_key(state)}
        while True:
            # 每次内层循环只尝试把当前 route 向前扩一跳。
            # route 的长短，是由这一跳一跳的 legality + 排序裁决自然长出来的。
            next_state = expand_greedy_state(
                context=context,
                state=state,
                allowed_targets=uncovered,
                solver_config=solver_config,
            )
            if next_state is None:
                # 没有合法下一跳时，当前 route 到此自然终止。
                break
            next_local_state = greedy_local_state_key(next_state)
            if next_local_state in visited_local_states:
                # 这里的 break 是局部 route 终止，不是全局失败。
                # 一旦检测到局部状态闭环，就让外层重新起一条新 route 去吃剩余 uncovered。
                break
            # 只有在“下一跳存在且没形成局部闭环”时，
            # 当前 route 才正式接纳这次推进结果。
            state = next_state
            # 用集合差更新 uncovered，能保证重复覆盖 sweep 不会把已吃掉的目标错误加回去。
            uncovered -= state.covered_sweeps
            visited_local_states.add(next_local_state)
        # 当前 route 完结后，才把它一次性物化为正式 SweepCadenceRoute。
        # route 走到头后，才一次性把累计状态物化成正式 route 对象。
        # 这保证输出 route 和内部求解状态使用的是完全同一份 primitive 序列真值。
        routes.append(route_from_state(state, route_id=int(len(routes) + 1)))
    return routes

__all__ = (
    'action_priority_key',
    'apply_greedy_action',
    'build_greedy_legal_actions',
    'build_sweep_cadence_routes_greedy',
    'build_transition_action',
    'expand_greedy_state',
    'greedy_local_state_key',
    'lookahead_gain',
    'make_route_state',
    'transition_penalty',
)
