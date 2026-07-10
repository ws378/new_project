"""Sweep cadence route 合并、异常吸收与端点修补。

职责：
    1. 在 greedy 主链结果上继续做 route 级结构整理。
    2. 吸收 singleton、修补单侧端点，并清理 through 违规碎片。
    3. 尽量只使用现有 transition 真值，不在 repair 阶段发明新连接。

边界：
    1. 这里不重新求解 sweep 覆盖顺序。
    2. 所有修补动作都必须经过 route_ops 的统一 route 真值装配。
"""

from __future__ import annotations

from ...contracts import SweepCadenceRoute, SweepGraphSweep, SweepTransitionCandidateItem
from .cadence_route_ops import (
    append_route_edit_trace,
    build_transition_index,
    classify_abnormal_sweep_ids,
    count_route_endpoint_usage,
    extend_route,
    follows_same_group,
    hypothetical_route_breaks,
    merge_cadence_routes,
    merge_routes,
    route_breaks_through_semantics,
    route_last_motion_type,
    route_to_route_transition,
    split_route_for_slot,
    split_route_on_first_through_violation,
)
from .cadence_types import (
    CadenceContext,
    transition_selection_level,
)


def repair_one_side_route_endpoints(
    *,
    routes: list[SweepCadenceRoute],
    transitions: tuple[SweepTransitionCandidateItem, ...],
    sweep_by_id: dict[int, SweepGraphSweep],
    cadence_context: CadenceContext,
    route_edit_trace: list[dict] | None = None,
) -> list[SweepCadenceRoute]:
    """修补只连到一侧的 route 端点，尽量补齐前驱或后继。

    这个阶段处理的是“端点缺一边”的 route，
    不会拆 route 内部结构，也不会做 singleton 中插。
    它的目标是用最小改动补齐首尾缺口。
    """

    # 端点修补只作用于已经成形的 route 首尾，不介入 route 内部 slot。
    # 因而它和 singleton absorb 的职责边界是清晰的：一个补缺口，一个吸异常孤段。
    # 如果某个端点在正式 transition 真值上根本没有可接对象，
    # 这里也不会强行兜底，而是保留现状交给上层验收或后续人工审查。
    # 这也是为什么 repair 阶段始终显得“保守”：
    # 它的职责是尽量修，不是为了漂亮结果去改写图真值。
    if not routes:
        # 没有 route 时，本阶段没有任何可修补对象，直接返回空结果即可。
        return routes
    # transition_map 把“端点是否能精确拼上”查询降成 O(1)，
    # 避免 repair 阶段在多轮 while 中反复线性扫 transition 做同样的四元匹配。
    transition_map = build_transition_index(transitions)
    working = [dict(route) for route in routes]
    while True:
        route_in_count, route_out_count = count_route_endpoint_usage(working)
        # 每轮 while 都重新统计一次端点占用，
        # 因为上一轮修补可能已经改变了哪些 sweep 仍然处于“缺前驱/缺后继”状态。
        best_choice: tuple[str, int, SweepTransitionCandidateItem] | None = None
        best_key = None
        for idx, route in enumerate(working):
            route_sweeps = {int(item) for item in route.get("sweep_sequence", ())}
            # 先尝试补起点前驱，再尝试补终点后继。
            # 两边都统一进入 best_choice 比较，保证这一轮只做一处最优修补。
            if int(route_in_count.get(int(route["start_sweep_id"]), 0)) == 0:
                # 起点入度为 0，说明这条 route 当前缺前驱，值得尝试 prepend 修补。
                for transition in transitions:
                    source_sweep_id = int(transition["from_sweep_id"])
                    if source_sweep_id in route_sweeps:
                        # 端点修补不允许把 route 自己再绕回自己，避免制造显式环。
                        continue
                    if transition_map.get((source_sweep_id, str(transition["from_end_type"]), int(route["start_sweep_id"]), str(route["start_end_type"]))) != transition:
                        # 这里要求 transition 与 route 起点端型精确闭合，不能只看 sweep_id 能连。
                        continue
                    prepend_route = extend_route(route, transition, prepend=True)
                    if route_breaks_through_semantics(prepend_route, cadence_context):
                        # 新 route 一旦破坏 through，说明这条修补边虽能接上，但不符合 cadence 路径语义。
                        continue
                    key = (
                        # 先保 strong_keep，避免为了补缺口把弱候选硬塞到主结构前面。
                        0 if transition_selection_level(transition) == "strong_keep" else 1,
                        # 端点修补仍要先看这条 transition 自己是否靠谱，
                        # 不能让 same-group 偏好越过风险和几何质量。
                        float(transition.get("risk_score", 0.0)),
                        float(transition.get("endpoint_distance_m", 0.0)),
                        float(transition.get("total_score", 0.0)),
                        -float(transition.get("local_feasibility_score", 0.0)),
                        # 同组延续只在质量主键之后做弱偏好。
                        0 if follows_same_group({"end_sweep_id": source_sweep_id}, route, sweep_by_id) else 1,
                        # 方向位：prepend，只负责同质量场景下的稳定顺序。
                        0,
                        # 最后才用 sweep_id 稳定兜底，保证同分时结果可复现。
                        int(source_sweep_id),
                    )
                    # 这里的 `0` 是方向位，表示 prepend，在同级条件相同时稳定排在 append 前。
                    # prepend 和 append 都走统一 key 比较，
                    # 最终只选当前轮最优的一次修补，避免一次循环里发生多处联动改写。
                    if best_key is None or key < best_key:
                        best_key = key
                        best_choice = ("prepend", idx, transition)
            if int(route_out_count.get(int(route["end_sweep_id"]), 0)) == 0:
                # 终点出度为 0，说明这条 route 当前缺后继，值得尝试 append 修补。
                for transition in transitions:
                    target_sweep_id = int(transition["to_sweep_id"])
                    if target_sweep_id in route_sweeps:
                        # 目标 sweep 已在本 route 内时，append 只会把 route 绕回自己，直接丢弃。
                        continue
                    if transition_map.get((int(route["end_sweep_id"]), str(route["end_end_type"]), target_sweep_id, str(transition["to_end_type"]))) != transition:
                        # append 也必须做完全同口径的四元闭合验证，避免只因为目标 sweep 对上就误接。
                        continue
                    append_route = extend_route(route, transition, prepend=False)
                    if route_breaks_through_semantics(append_route, cadence_context):
                        # append 后若把 route 内部 through 弄断，同样不能拿来补尾端。
                        continue
                    key = (
                        # append 与 prepend 共用同一主排序语义，先比连接质量，再比方向位。
                        0 if transition_selection_level(transition) == "strong_keep" else 1,
                        float(transition.get("risk_score", 0.0)),
                        float(transition.get("endpoint_distance_m", 0.0)),
                        float(transition.get("total_score", 0.0)),
                        -float(transition.get("local_feasibility_score", 0.0)),
                        0 if follows_same_group(route, {"start_sweep_id": target_sweep_id}, sweep_by_id) else 1,
                        # 方向位：append，只负责同质量场景下的稳定顺序。
                        1,
                        int(target_sweep_id),
                    )
                    # 这里的 `1` 是方向位，表示 append，在主键相同场景下负责提供稳定顺序。
                    if best_key is None or key < best_key:
                        best_key = key
                        best_choice = ("append", idx, transition)
        if best_choice is None:
            # 没有候选时，说明所有 route 端点要么已补齐，要么在正式 transition 真值上无解。
            return working
        mode, idx, transition = best_choice
        # 每轮只执行一次 extend，再重新统计端点占用。
        # 这样可以避免旧统计结果在一次循环内被连续复用。
        # 换句话说，repair 的收敛方式是“单步最优修补 -> 重新观察全局缺口”，而不是批量并发改写。
        before_route = dict(working[idx])
        repaired = extend_route(working[idx], transition, prepend=(mode == "prepend"))
        append_route_edit_trace(
            route_edit_trace,
            stage="repair_one_side_route_endpoints",
            operation=str(mode),
            transition=transition,
            before_routes=[before_route],
            after_route=repaired,
            all_routes_before=working,
            decision_key=best_key,
            reason="one_side_endpoint_repair",
        )
        working[idx] = repaired


def absorb_score_key(
    *,
    left: SweepCadenceRoute,
    right: SweepCadenceRoute,
    sweep_by_id: dict[int, SweepGraphSweep],
    left_transition: SweepTransitionCandidateItem,
    right_transition: SweepTransitionCandidateItem | None,
    stage_priority: int,
    tie_break: tuple[int, ...],
) -> tuple[int, int, int, float, float, int, tuple[int, ...]]:
    """给 singleton 吸收动作生成稳定排序键。

    吸收动作有多种形态：between、append、prepend、slot。
    这里通过 `stage_priority` 显式编码阶段先后，
    保证不同吸收策略之间不会因为风险分接近而乱序竞争。
    """

    # absorb 的排序口径与 merge 类似，但显式加入 stage_priority。
    # 这样 between-routes、endpoint、slot 三层策略就不会相互串级。
    # tie_break 不承载业务语义，只用于在前面若干主键完全相同的情况下维持可复现顺序。
    return (
        int(stage_priority),
        # 左右 transition 的 selection level 先决定“这次吸收是否站得住脚”，
        # 风险分与 total_score 只在更后面做细粒度比较。
        0 if transition_selection_level(left_transition) == "strong_keep" else 1,
        0 if right_transition is None or transition_selection_level(right_transition) == "strong_keep" else 1,
        # 左右两条边的风险与总分在这里直接相加，
        # 表示 singleton 吸收整体上要为“两端都成立”这件事共同买单。
        float(left_transition.get("risk_score", 0.0)) + float((right_transition or {}).get("risk_score", 0.0)),
        float(left_transition.get("total_score", 0.0)) + float((right_transition or {}).get("total_score", 0.0)),
        # same-group 仍然只作为偏好项，不会覆盖 selection/risk 这些更硬的结构证据。
        0 if follows_same_group(left, right, sweep_by_id) else 1,
        # tie_break 只服务于稳定输出，不参与业务优先级表达。
        tuple(int(item) for item in tie_break),
    )


def absorb_singleton_routes(
    *,
    routes: list[SweepCadenceRoute],
    transitions: tuple[SweepTransitionCandidateItem, ...],
    sweep_by_id: dict[int, SweepGraphSweep],
    cadence_context: CadenceContext,
    route_edit_trace: list[dict] | None = None,
) -> list[SweepCadenceRoute]:
    """按 between-routes -> endpoint -> slot 三层顺序统一吸收 singleton。

    这是 cadence 后处理里最强的结构修复器之一。
    它优先把 singleton 吃进两条 route 中间，其次挂到首尾，
    最后才尝试拆 slot 中插，保证改动从保守到激进逐层推进。
    """

    # 这一步的目标不是“把所有 singleton 都消灭掉”，
    # 而是“只在正式 transition 真值允许、且 through 语义不被破坏时再吸收”。
    if len(routes) <= 1:
        # 少于两条 route 时，不存在把 singleton 吸入别的 route 的空间，直接原样返回。
        return routes
    transition_map = build_transition_index(transitions)
    working = [dict(route) for route in routes]
    while True:
        best_choice: tuple[str, tuple] | None = None
        best_key = None
        singleton_items = [
            (idx, route)
            for idx, route in enumerate(working)
            if int(route.get("transition_count", 0)) == 0 and len(route.get("sweep_sequence", ())) == 1
        ]
        # 这里同时要求“没有 transition”且“只含一个 sweep”，
        # 目的是把真正的孤点 route 和已经成形但较短的 route 严格区分开。
        # 只有真正的 singleton 才进入这轮吸收。
        # 已经有 transition 结构的 route，不在这里做“半拆半吸”的复杂变形。
        for s_idx, single in singleton_items:
            for l_idx, left in enumerate(working):
                if l_idx == s_idx:
                    continue
                left_transition = route_to_route_transition(transition_map, left, single)
                if left_transition is not None:
                    # 只有 singleton 能先从 left 这边被精确接进来，between 才有继续向右扩展的前提。
                    # 第一优先级：左右都能打通时，优先把 singleton 吸进两条 route 中间。
                    # 这比简单挂到首尾更自然，因为它能同时消掉三条异常链的断口。
                    for r_idx, right in enumerate(working):
                        if r_idx in {s_idx, l_idx}:
                            # singleton 的左右宿主必须是另外两条独立 route，不能重复占用同一对象。
                            continue
                        right_transition = route_to_route_transition(transition_map, single, right)
                        if right_transition is None:
                            # 右半边拼不上时，就还不满足 between 的“两端都闭合”条件。
                            continue
                        if hypothetical_route_breaks(
                            left=left,
                            right=right,
                            middle_routes=[single],
                            transitions=[left_transition, right_transition],
                            cadence_context=cadence_context,
                        ):
                            # 能在图上接通还不够，插完 singleton 后整条假想 route 仍必须 through 连续。
                            continue
                        key = absorb_score_key(
                            left=left,
                            right=single,
                            sweep_by_id=sweep_by_id,
                            left_transition=left_transition,
                            right_transition=right_transition,
                            stage_priority=0,
                            # between 模式只需要用 singleton 自身 sweep_id 做稳定 tie-break。
                            tie_break=(int(single["start_sweep_id"]),),
                        )
                        # between 一旦成立，通常能同时消掉三段断口，因此结构收益最大。
                        if best_key is None or key < best_key:
                            best_key = key
                            best_choice = ("between", (l_idx, s_idx, r_idx, left_transition, right_transition))

                # 第二层优先级是直接挂到某条 route 末尾。
                append_transition = route_to_route_transition(transition_map, left, single)
                if append_transition is not None and not hypothetical_route_breaks(
                    left=left,
                    right=single,
                    transitions=[append_transition],
                    cadence_context=cadence_context,
                ):
                    # append 分支表示“singleton 可以作为 left 的自然尾段被吸进去”，
                    # 且吸进去以后 through 仍然成立。
                    key = absorb_score_key(
                        left=left,
                        right=single,
                        sweep_by_id=sweep_by_id,
                        left_transition=append_transition,
                        right_transition=None,
                        stage_priority=1,
                        # append / prepend 共用 stage_priority=1，再靠首位方向码区分稳定顺序。
                        tie_break=(0, int(single["start_sweep_id"])),
                    )
                    # append 更像“顺着当前 route 往后接一段”，所以和 prepend 分开做稳定排序。
                    if best_key is None or key < best_key:
                        best_key = key
                        best_choice = ("append", (l_idx, s_idx, append_transition))

                # 同级再尝试挂到 route 头部。
                prepend_transition = route_to_route_transition(transition_map, single, left)
                if prepend_transition is not None and not hypothetical_route_breaks(
                    left=single,
                    right=left,
                    transitions=[prepend_transition],
                    cadence_context=cadence_context,
                ):
                    # prepend 与 append 对称，表达“singleton 可以作为 left 的自然前驱被吃进去”。
                    key = absorb_score_key(
                        left=single,
                        right=left,
                        sweep_by_id=sweep_by_id,
                        left_transition=prepend_transition,
                        right_transition=None,
                        stage_priority=1,
                        # prepend 用另一组方向码，避免与 append 在同分时发生非确定性竞争。
                        tie_break=(1, int(single["start_sweep_id"])),
                    )
                    if best_key is None or key < best_key:
                        best_key = key
                        best_choice = ("prepend", (l_idx, s_idx, prepend_transition))

                if len(left.get("sweep_sequence", ())) < 2:
                    # 太短的 route 没有内部 slot，没法做中插吸收。
                    continue
                for slot_index in range(len(left["sweep_sequence"]) - 1):
                    # slot 吸收是最后优先级。
                    # 因为它会把已有 route 拆成前后两段，再把 singleton 插进中间，结构改动最大。
                    prefix, suffix = split_route_for_slot(left, slot_index)
                    # slot 模式的左右 transition 必须分别闭合到 prefix 尾端和 suffix 首端，
                    # 任一侧缺失都说明 singleton 不能被完整塞回这个内部缺口。
                    left_transition = route_to_route_transition(transition_map, prefix, single)
                    right_transition = route_to_route_transition(transition_map, single, suffix)
                    if left_transition is None or right_transition is None:
                        # slot 模式必须左右两边都存在精确 transition，否则 singleton 无法完整插回中间。
                        continue
                    if hypothetical_route_breaks(
                        left=prefix,
                        right=suffix,
                        middle_routes=[single],
                        transitions=[left_transition, right_transition],
                        cadence_context=cadence_context,
                    ):
                        # 即使 slot 左右都能接上，只要整体 through 被打断，也不能做内部中插。
                        continue
                    key = absorb_score_key(
                        left=prefix,
                        right=single,
                        sweep_by_id=sweep_by_id,
                        left_transition=left_transition,
                        right_transition=right_transition,
                        stage_priority=2,
                        tie_break=(int(single["start_sweep_id"]),),
                    )
                    if best_key is None or key < best_key:
                        best_key = key
                        best_choice = ("slot", (l_idx, s_idx, slot_index, left_transition, right_transition))
        if best_choice is None:
            # 当前 working 集合里再也没有合法吸收动作时，singleton 清理阶段结束。
            return working
        mode, payload = best_choice
        if mode == "between":
            # between 模式一次会消掉三条 route，并重建成一条更长 route。
            l_idx, s_idx, r_idx, left_transition, right_transition = payload
            # 这里先把 left 与 singleton 合并，再接上 right，
            # 目的是复用现有 merge 语义，而不是另写一套三段拼装逻辑。
            merged = merge_routes(merge_routes(working[l_idx], working[s_idx], left_transition), working[r_idx], right_transition)
            append_route_edit_trace(
                route_edit_trace,
                stage="absorb_singleton_routes",
                operation="between",
                transition=left_transition,
                before_routes=[working[l_idx], working[s_idx], working[r_idx]],
                after_route=merged,
                all_routes_before=working,
                decision_key=best_key,
                reason="singleton_between_left_transition",
            )
            append_route_edit_trace(
                route_edit_trace,
                stage="absorb_singleton_routes",
                operation="between",
                transition=right_transition,
                before_routes=[working[l_idx], working[s_idx], working[r_idx]],
                after_route=merged,
                all_routes_before=working,
                decision_key=best_key,
                reason="singleton_between_right_transition",
            )
            working = [route for idx, route in enumerate(working) if idx not in {l_idx, s_idx, r_idx}] + [merged]
            continue
        if mode == "slot":
            r_idx, s_idx, slot_index, left_transition, right_transition = payload
            # slot 模式先把原 route 切成前后两段，再把 singleton 插进中间。
            prefix, suffix = split_route_for_slot(working[r_idx], slot_index)
            merged = merge_routes(merge_routes(prefix, working[s_idx], left_transition), suffix, right_transition)
            # slot 吸收虽然重建了 route，但语义上它仍是在“原 route 上插入 singleton”，
            # 因此保留原 route_id 更利于外部追踪。
            merged["route_id"] = int(working[r_idx]["route_id"])
            append_route_edit_trace(
                route_edit_trace,
                stage="absorb_singleton_routes",
                operation="slot",
                transition=left_transition,
                before_routes=[working[r_idx], working[s_idx]],
                after_route=merged,
                all_routes_before=working,
                decision_key=best_key,
                reason="singleton_slot_left_transition",
            )
            append_route_edit_trace(
                route_edit_trace,
                stage="absorb_singleton_routes",
                operation="slot",
                transition=right_transition,
                before_routes=[working[r_idx], working[s_idx]],
                after_route=merged,
                all_routes_before=working,
                decision_key=best_key,
                reason="singleton_slot_right_transition",
            )
            working = [route for idx, route in enumerate(working) if idx not in {r_idx, s_idx}] + [merged]
            continue
        # append / prepend 都只会消掉 singleton 与其目标 route 两项。
        r_idx, s_idx, transition = payload
        # 这两种模式都不需要拆 route，只是在某一端补进 singleton。
        merged = extend_route(working[r_idx], transition, prepend=(mode == "prepend"))
        append_route_edit_trace(
            route_edit_trace,
            stage="absorb_singleton_routes",
            operation=str(mode),
            transition=transition,
            before_routes=[working[r_idx], working[s_idx]],
            after_route=merged,
            all_routes_before=working,
            decision_key=best_key,
            reason="singleton_endpoint_absorb",
        )
        working = [route for idx, route in enumerate(working) if idx not in {r_idx, s_idx}] + [merged]


def optimize_greedy_routes(
    routes: list[SweepCadenceRoute],
    context: CadenceContext,
    *,
    route_edit_trace: list[dict] | None = None,
) -> list[SweepCadenceRoute]:
    """在 greedy 结果上继续做 route merge、异常 sweep 集成和端点修补。

    这里是 greedy 主链之后的统一整理入口。
    它不重新求解 sweep 覆盖顺序，而是基于现有 route 和 transition 真值，
    尽量把碎片化结构收敛成更完整、语义更稳定的 route 集合。
    """

    # 后处理顺序是刻意固定的：
    # 1. 先 merge，尽量把天然可拼的 route 串起来；
    # 2. 再压缩连续 foldback 并切开 through 违规段；
    # 3. 再吸收 singleton；
    # 4. 最后修补单侧端点。
    # 这个顺序不能随意反过来。
    # 否则 singleton 可能会在 merge 之前被吸进一个本来还会继续合并的短 route，
    # 导致整体结构变得更碎，或者让修补动作抢先锁死更优的拼接机会。
    optimized = merge_cadence_routes(
        routes=routes,
        transitions=context.transitions,
        sweep_by_id=context.sweep_by_id,
        cadence_context=context,
        route_edit_trace=route_edit_trace,
        stage_label="initial_merge_1",
    )
    # 连续做两轮 merge，是为了把“第一轮合并新创造出来的首尾拼接机会”也吃掉。
    optimized = merge_cadence_routes(
        routes=optimized,
        transitions=context.transitions,
        sweep_by_id=context.sweep_by_id,
        cadence_context=context,
        route_edit_trace=route_edit_trace,
        stage_label="initial_merge_2",
    )

    corrected: list[SweepCadenceRoute] = []
    for route in optimized:
        compacted: list[SweepCadenceSegment] = []
        for segment in route.get("segments", ()):
            if (
                compacted
                and int(compacted[-1]["to_sweep_id"]) == int(segment["to_sweep_id"])
                and int(compacted[-1]["from_sweep_id"]) == int(segment["from_sweep_id"])
                and str(compacted[-1].get("primitive_type")) == "foldback"
                and str(segment.get("primitive_type")) == "foldback"
            ):
                # 连续两个完全同向的 foldback 没有额外信息量，保留后一个即可。
                compacted[-1] = segment
                continue
            compacted.append(segment)
        # 这里的 compacted_route 是“压平后、必要时再切分前”的中间版本。
        compacted_route = {
            **route,
            "segments": tuple(compacted),
            # 压平重复 foldback 后，transition_count 必须基于新 segment 列表重算，不能沿用旧值。
            "transition_count": int(sum(1 for item in compacted if str(item.get("primitive_type")) == "transition")),
        }
        # 先把局部重复 foldback 压平，再判断 through 是否需要切开。
        if route_breaks_through_semantics(compacted_route, context):
            split_routes = split_route_on_first_through_violation(compacted_route, context)
            for split_route in split_routes:
                append_route_edit_trace(
                    route_edit_trace,
                    stage="split_through_violation",
                    operation="split",
                    transition=None,
                    before_routes=[compacted_route],
                    after_route=split_route,
                    all_routes_before=optimized,
                    reason="route_breaks_through_semantics",
                )
            corrected.extend(split_routes)
        else:
            corrected.append(compacted_route)
    optimized = corrected

    singleton_sweep_ids, none_connected_sweep_ids, one_side_connected_sweep_ids = classify_abnormal_sweep_ids(optimized, context=context)
    # singleton / none_connected 往往意味着 greedy 主链没有把这些 sweep 融进主结构。
    # 因此优先用 absorb 做结构级整合，再考虑端点补齐。
    if singleton_sweep_ids or none_connected_sweep_ids:
        # none_connected 也一起走 absorb，是因为这类 sweep 往往会先表现成 singleton route。
        optimized = absorb_singleton_routes(
            routes=optimized,
            transitions=context.transitions,
            sweep_by_id=context.sweep_by_id,
            cadence_context=context,
            route_edit_trace=route_edit_trace,
        )
        # absorb 之后 route 结构已经变化，后面的一侧连通性判定必须基于新结果重算。

    _, _, one_side_connected_sweep_ids = classify_abnormal_sweep_ids(optimized, context=context)
    # 这里重新跑一遍 abnormal 分类，是因为 absorb 之后 route 结构已经变了，
    # 旧的一侧连通统计不再可靠。
    if one_side_connected_sweep_ids:
        # 只剩单侧缺口时，再用 endpoint repair 做最后一轮保守补齐。
        optimized = repair_one_side_route_endpoints(
            routes=optimized,
            transitions=context.transitions,
            sweep_by_id=context.sweep_by_id,
            cadence_context=context,
            route_edit_trace=route_edit_trace,
        )

    # 最后一轮 merge 是收尾动作。
    # 前面的 absorb/repair 可能新造出可以首尾串接的 route，这里再统一吞并一次。
    # 这里不再做新一轮 singleton 分类，
    # 因为收尾 merge 的目标只是消化已经显式出现的 route-to-route 拼接机会。
    # 如果这一步仍无法继续合并，就把当前 optimized 当成 cadence 后处理正式结果返回。
    return merge_cadence_routes(
        routes=optimized,
        transitions=context.transitions,
        sweep_by_id=context.sweep_by_id,
        cadence_context=context,
        route_edit_trace=route_edit_trace,
        stage_label="final_merge",
    )

__all__ = (
    'absorb_singleton_routes',
    'optimize_greedy_routes',
    'repair_one_side_route_endpoints',
)
