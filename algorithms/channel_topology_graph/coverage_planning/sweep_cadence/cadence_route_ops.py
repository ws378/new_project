"""Sweep cadence route 真值装配与 through 语义检查。"""

from __future__ import annotations

from ...contracts import SweepCadenceRoute, SweepCadenceSegment, SweepGraphSweep, SweepTransitionCandidateItem
from .cadence_types import (
    CadenceContext,
    count_transition_segments,
    is_dead_end_like_sweep,
    opposite_end_type,
)


def build_transition_index(
    transitions: tuple[SweepTransitionCandidateItem, ...],
) -> dict[tuple[int, str, int, str], SweepTransitionCandidateItem]:
    """为 route repair 阶段建立首尾精确拼接索引。

    这份索引只服务于 route 首尾拼接。
    它要求 sweep 与端型全部精确一致，避免 repair/merge 阶段再引入模糊连接判断。
    """

    # 索引键故意把 from/to sweep 与 from/to end 全都编码进去。
    # 只有四元都精确相等，才认为两条 route 可以被这条 transition 串起来。
    return {
        # 一旦进了这个索引，就表示该 transition 已经被压成“可做 route 首尾拼接”的查找形式。
        (int(item["from_sweep_id"]), str(item["from_end_type"]), int(item["to_sweep_id"]), str(item["to_end_type"])): item
        for item in transitions
    }


def route_to_route_transition(
    transition_map: dict[tuple[int, str, int, str], SweepTransitionCandidateItem],
    left: SweepCadenceRoute,
    right: SweepCadenceRoute,
) -> SweepTransitionCandidateItem | None:
    """查找两条 route 首尾能否被一条正式 transition 串起来。

    这里不尝试找“最接近”的 transition。
    若索引没有命中，就说明当前两条 route 在正式 transition 真值上不可直接拼接。
    """

    # 这里只做精确索引命中，不做模糊匹配。
    # route merge/repair 都建立在正式 transition 真值之上，不能在这里再发明“近似可连”。
    return transition_map.get((int(left["end_sweep_id"]), str(left["end_end_type"]), int(right["start_sweep_id"]), str(right["start_end_type"])))


def route_last_motion_type(route: SweepCadenceRoute) -> str:
    """读取 route 最后一段的运动语义。

    空 route 默认返回 `start`，
    让上游排序器在起始状态下也能统一走 motion 优先级逻辑。
    """

    segments = tuple(route.get("segments", ()))
    if not segments:
        # 起始 route 还没有任何 primitive 时，用 `start` 作为统一哨兵语义。
        return "start"
    # 最后一段的 motion_type 会直接影响后续 merge/repair 的排序偏好。
    return str(segments[-1].get("motion_type", "start"))


def follows_same_group(
    left: SweepCadenceRoute | dict,
    right: SweepCadenceRoute | dict,
    sweep_by_id: dict[int, SweepGraphSweep] | None,
) -> bool:
    """判断左右两个 route 端点是否仍沿同一 coverage lane 组延续。

    这不是合法性条件，而是排序偏好。
    若两端仍处于同一 coverage lane，通常说明这次拼接更像主线延续，应优先保留。
    """

    if not sweep_by_id:
        # 没有 sweep 元数据时，就无法判断 coverage_lane_id 语义，只能保守认为“不属于同组延续”。
        return False
    # 这里比较的是 route 两端 sweep 的 `coverage_lane_id`，
    # 不是单纯比较 sweep_id 是否相邻；语义上关注的是“是否仍在同一覆盖 lane 主线里”。
    left_sweep = sweep_by_id.get(int(left["end_sweep_id"]))
    right_sweep = sweep_by_id.get(int(right["start_sweep_id"]))
    if left_sweep is None or right_sweep is None:
        return False
    return bool(int(left_sweep.get("coverage_lane_id", -1)) == int(right_sweep.get("coverage_lane_id", -2)))


def append_route_edit_trace(
    trace: list[dict] | None,
    *,
    stage: str,
    operation: str,
    transition: SweepTransitionCandidateItem | dict | None,
    before_routes: list[SweepCadenceRoute | dict],
    after_route: SweepCadenceRoute | dict | None,
    all_routes_before: list[SweepCadenceRoute | dict] | None = None,
    decision_key: tuple | None = None,
    reason: str = "",
) -> None:
    """记录 route 后处理改写证据，不参与任何算法决策。"""

    if trace is None:
        # trace 是显式注入的审计旁路；未开启时不能改变正常算法输出和内存结构。
        return
    before_sequences = [
        [int(sweep_id) for sweep_id in route.get("sweep_sequence", ())]
        for route in before_routes
    ]
    after_sequence = (
        [int(sweep_id) for sweep_id in after_route.get("sweep_sequence", ())]
        if after_route is not None
        else []
    )
    before_sweeps = {sweep_id for sequence in before_sequences for sweep_id in sequence}
    after_sweeps = set(after_sequence)
    all_sequences_before = [
        [int(sweep_id) for sweep_id in route.get("sweep_sequence", ())]
        for route in (all_routes_before or before_routes)
    ]
    all_sweeps_before = {sweep_id for sequence in all_sequences_before for sweep_id in sequence}
    target_sweep_id = int(transition.get("to_sweep_id", -1)) if transition is not None else None
    trace.append(
        {
            "stage": str(stage),
            "operation": str(operation),
            "reason": str(reason),
            "transition_id": int(transition.get("candidate_id", transition.get("transition_id", -1))) if transition is not None else None,
            "from_sweep_id": int(transition.get("from_sweep_id", -1)) if transition is not None else None,
            "to_sweep_id": target_sweep_id,
            "from_end_type": str(transition.get("from_end_type", "")) if transition is not None else "",
            "to_end_type": str(transition.get("to_end_type", "")) if transition is not None else "",
            "candidate_source": str(transition.get("candidate_source", "")) if transition is not None else "",
            "motion_type": str(transition.get("motion_type", "")) if transition is not None else "",
            "selection_level": str(transition.get("selection_level", "")) if transition is not None else "",
            "risk_score": float(transition.get("risk_score", 0.0)) if transition is not None else None,
            "endpoint_distance_m": float(transition.get("endpoint_distance_m", 0.0)) if transition is not None else None,
            "total_score": float(transition.get("total_score", 0.0)) if transition is not None else None,
            "decision_key": list(decision_key) if decision_key is not None else None,
            "before_route_ids": [int(route.get("route_id", -1)) for route in before_routes],
            "before_sequences": before_sequences,
            "all_sequences_before": all_sequences_before,
            "after_sequence": after_sequence,
            "added_sweep_ids": sorted(int(sweep_id) for sweep_id in (after_sweeps - before_sweeps)),
            "target_sweep_seen_in_before_routes": bool(target_sweep_id in before_sweeps) if target_sweep_id is not None else False,
            "target_sweep_seen_globally_before_operation": bool(target_sweep_id in all_sweeps_before) if target_sweep_id is not None else False,
            "target_sweep_seen_in_other_routes_before_operation": bool(target_sweep_id in (all_sweeps_before - before_sweeps)) if target_sweep_id is not None else False,
            "target_is_after_tail": bool(after_sequence and target_sweep_id == int(after_sequence[-1])) if target_sweep_id is not None else False,
        }
    )


def transition_segment_from_merge(
    left_route: SweepCadenceRoute,
    transition: SweepTransitionCandidateItem,
    right_start_end_type: str,
) -> SweepCadenceSegment:
    """把一条 transition 真值改写成 route merge 使用的 segment 条目。

    cadence route 里的 segment 是运行时段语义，不直接等于 transition 原对象。
    这里会补齐 route 视角下的 entry/exit 端和 primitive 标签，
    让 merge 后的 route 仍能被 through 检查器直接消费。
    """

    # route segment 是 cadence route 自己的运行真值，不直接复用 transition 原对象。
    # 这里显式改写 entry/exit 端，保证 merge 后 route 的 through 语义能继续被统一检查。
    return {
        "from_sweep_id": int(transition["from_sweep_id"]),
        "to_sweep_id": int(transition["to_sweep_id"]),
        "via_node_id": int(transition["via_node_id"]),
        # selection_level / motion_type 是后处理排序与审计仍然要用到的关键证据，merge 后不能丢。
        "selection_level": str(transition["selection_level"]),
        "requires_junction_connection": True,
        # 进入桥接段前，route 当前就停在 left_route 的 end 端，因此这里直接继承它作为 entry。
        "entry_end_type": str(left_route["end_end_type"]),
        # 过桥后会从 right route 起始 sweep 的对侧继续向后走，所以这里取反向端作为 exit。
        "exit_end_type": opposite_end_type(str(right_start_end_type)),
        "primitive_type": "transition",
        "is_repeat_coverage_transition": False,
        "foldback_penalty": 0.0,
        "transition_id": int(transition.get("candidate_id", transition.get("transition_id", -1))),
        "motion_type": str(transition.get("motion_type", "straight")),
    }


def build_route(
    *,
    route_id: int,
    sweep_sequence: list[int],
    segments: list[SweepCadenceSegment] | tuple[SweepCadenceSegment, ...],
    start_end_type: str,
    end_end_type: str,
) -> SweepCadenceRoute:
    """按统一口径组装 route。

    这是 cadence route 的唯一正式装配口。
    所有 split、extend、merge 操作都应回到这里重算统计字段，
    防止 `transition_count`、`segment_count` 等信息在局部更新时漂移。
    """

    segment_tuple = tuple(segments)
    # build_route 是 route 真值的唯一装配口。
    # 所有 merge/split/extend 最后都应该回到这里，避免统计字段在各处分头维护。
    return {
        "route_id": int(route_id),
        "sweep_sequence": list(sweep_sequence),
        "segments": segment_tuple,
        # route 的首尾 sweep 直接由当前 sequence 两端定义，
        # 不能靠 segments 反推，否则空 segment 的 singleton route 会失真。
        "start_sweep_id": int(sweep_sequence[0]),
        "end_sweep_id": int(sweep_sequence[-1]),
        "start_end_type": str(start_end_type),
        "end_end_type": str(end_end_type),
        # sweep_count / transition_count / segment_count 都是派生统计，
        # 每次 build_route 时统一重算，避免局部编辑后字段漂移。
        "sweep_count": int(len(sweep_sequence)),
        "transition_count": int(count_transition_segments(segment_tuple)),
        "segment_count": int(len(segment_tuple)),
    }


def route_breaks_through_semantics(route: SweepCadenceRoute, context: CadenceContext) -> bool:
    """检查 route 中间 sweep 是否违反 through 连续语义。

    through 的核心要求是：
    普通中间 sweep 必须形成连续的“进 -> 过 -> 出”关系，
    不能在中间位置断端、回折或发生 entry/exit 端型错位。
    """

    # through 只约束内部 sweep；首尾 sweep 不参与判定。
    # 一旦中间 sweep 发生断端、foldback 或进出端不一致，就认为这条 route 的 through 被破坏。
    sweep_sequence = [int(item) for item in route.get("sweep_sequence", ())]
    segments = tuple(route.get("segments", ()))
    if len(sweep_sequence) <= 2 or len(segments) < 2:
        # 少于两个桥接段时，不存在“中间 through sweep”可供判错。
        return False
    for idx in range(1, len(sweep_sequence) - 1):
        sweep_id = int(sweep_sequence[idx])
        if is_dead_end_like_sweep(context, sweep_id):
            # dead-end 类 sweep 允许在 through 语义下作为特殊节点存在，
            # 不强求其像普通 through sweep 那样“进一端、出另一端”。
            continue
        incoming = dict(segments[idx - 1])
        outgoing = dict(segments[idx])
        if int(incoming.get("to_sweep_id", -1)) != sweep_id:
            # 上一段没有真正落到这个中间 sweep，说明 route 序列和段连接已经断开。
            return True
        if int(outgoing.get("from_sweep_id", -1)) != sweep_id:
            # 下一段不是从这个中间 sweep 发出，说明 through 链被截断。
            return True
        if str(incoming.get("primitive_type")) == "foldback":
            # foldback 出现在中间位，意味着 route 在 through 过程中发生了本地翻端。
            return True
        if str(outgoing.get("primitive_type")) == "foldback":
            # 只要 through 中间 sweep 还需要靠 foldback 才能继续往后走，就说明这条 through 链不成立。
            return True
        if str(incoming.get("exit_end_type")) != str(outgoing.get("entry_end_type")):
            # 中间 sweep 的出入口端型不连续，表示 through 语义被破坏。
            return True
    # 全部中间 sweep 都满足 through 条件时，才返回“这条 route 不破坏 through”。
    return False


def hypothetical_route_breaks(
    *,
    left: SweepCadenceRoute,
    right: SweepCadenceRoute,
    transitions: list[SweepTransitionCandidateItem],
    cadence_context: CadenceContext,
    middle_routes: list[SweepCadenceRoute] | None = None,
) -> bool:
    """在不真正落盘 route 的前提下，预判 merge/插入后是否破坏 through 语义。

    这个 helper 常用于 repair 阶段做“先试后落”。
    它把若干 route 与 transition 临时拼成一条假想链，
    再复用正式 through 检查器做一致性验证。
    """

    middle_routes = middle_routes or []
    segments: list[SweepCadenceSegment] = list(left.get("segments", ()))
    sequence: list[int] = [*left["sweep_sequence"]]
    current = left
    # 这里按“left -> middle... -> right”的顺序拼出一条假想 route，
    # 再复用正式 through 检查器判断是否会违规。
    for middle_route, transition in zip(middle_routes, transitions[:-1]):
        # 每一段 middle route 前面都要先插入一条桥接 transition segment，
        # 否则 through 检查看到的只会是几段 route 生硬拼接，而不是完整连通链。
        segments.append(transition_segment_from_merge(current, transition, middle_route["start_end_type"]))
        segments.extend(middle_route.get("segments", ()))
        sequence.extend(middle_route["sweep_sequence"])
        # current 持续向后推进，表示下一条桥接 transition 要从哪一段 route 的末端出发。
        current = middle_route
    last_transition = transitions[-1]
    # 最后一条 transition 负责把当前链尾接到最终 right route 的起点上。
    segments.append(transition_segment_from_merge(current, last_transition, right["start_end_type"]))
    segments.extend(right.get("segments", ()))
    sequence.extend(right["sweep_sequence"])
    return route_breaks_through_semantics(
        {
            "sweep_sequence": tuple(sequence),
            "segments": tuple(segments),
        },
        cadence_context,
    )


def split_route_on_first_through_violation(
    route: SweepCadenceRoute,
    context: CadenceContext,
) -> list[SweepCadenceRoute]:
    """在首个 through 违规位置把 route 一分为二。

    这是一个保守修正器。
    它不尝试智能重排，只负责把第一处明显不合法的 through 断开，
    给后续 merge/repair 留出更干净的处理对象。
    """

    sweep_sequence = [int(item) for item in route.get("sweep_sequence", ())]
    segments = list(route.get("segments", ()))
    if len(sweep_sequence) <= 2 or len(segments) < 2:
        # 太短的 route 不存在可切的内部 through 违规点，直接原样返回。
        return [route]
    for idx in range(1, len(sweep_sequence) - 1):
        probe = {
            # probe 只截取违规点邻域，目的是用最小局部片段验证 through 是否已经断裂。
            "sweep_sequence": tuple(sweep_sequence[max(0, idx - 1): idx + 2]),
            "segments": tuple(segments[max(0, idx - 1): idx + 1]),
        }
        if not route_breaks_through_semantics(probe, context):
            # 当前局部窗口还没破坏 through，就继续往后找真正的首个违规点。
            continue
        # 只在第一个违规点切分，目的是把明显错误的 through 先拆开，
        # 而不是在这里直接做复杂重构。
        left_sweeps = sweep_sequence[: idx + 1]
        right_sweeps = sweep_sequence[idx:]
        left_segments = segments[:idx]
        right_segments = segments[idx:]
        if not left_sweeps or not right_sweeps:
            # 若切到一侧为空，说明当前 probe 位置并不适合形成合法两段 route，
            # 这时宁可保守放弃切分，也不返回破损结构。
            return [route]
        left_route = build_route(
            route_id=int(route["route_id"]),
            sweep_sequence=left_sweeps,
            segments=left_segments,
            start_end_type=str(route["start_end_type"]),
            # 左半段若还有 segment，就以最后一段的 exit 端作为新 route 末端语义。
            end_end_type=str(left_segments[-1]["exit_end_type"]) if left_segments else str(route["start_end_type"]),
        )
        # 右半段的起始端要从第一段的 entry 端反推，
        # 因为 route 真值记录的是“在起始 sweep 上将从哪一端向外走”。
        right_start_end = opposite_end_type(str(right_segments[0]["entry_end_type"])) if right_segments else str(route["end_end_type"])
        right_route = build_route(
            route_id=int(route["route_id"]),
            sweep_sequence=right_sweeps,
            segments=right_segments,
            start_end_type=str(right_start_end),
            end_end_type=str(right_segments[-1]["exit_end_type"]) if right_segments else str(right_start_end),
        )
        return [left_route, right_route]
    return [route]


def extend_route(
    route: SweepCadenceRoute,
    transition: SweepTransitionCandidateItem,
    *,
    prepend: bool,
) -> SweepCadenceRoute:
    """用统一口径把一条 transition 接到 route 头部或尾部。

    prepend/append 的差别只在于谁变成新的端点 sweep，
    但两者最后都必须回到 `build_route`，
    以保证 route 统计与端型语义同步更新。
    """

    if prepend:
        source_sweep_id = int(transition["from_sweep_id"])
        # prepend 时，transition 的 from 侧会变成新 route 的第一个 sweep。
        # 这里传入一个只带 `end_end_type` 的最小左上下文，
        # 是为了让 merge helper 能统一生成桥接 segment 的 entry 端。
        segment = transition_segment_from_merge({"end_end_type": str(transition["from_end_type"])}, transition, route["start_end_type"])
        # prepend 的核心语义是：
        # “在原 route 头部前面再接入一个来源 sweep + 一条桥接 transition”。
        return build_route(
            route_id=int(route["route_id"]),
            sweep_sequence=[source_sweep_id, *route["sweep_sequence"]],
            segments=[segment, *route.get("segments", ())],
            start_end_type=str(opposite_end_type(str(transition["from_end_type"]))),
            end_end_type=str(route["end_end_type"]),
        )
    target_sweep_id = int(transition["to_sweep_id"])
    # append 时，transition 的 to 侧会变成新 route 的最后一个 sweep。
    # `opposite_end_type(to_end_type)` 表示过桥接 transition 后，
    # route 在目标 sweep 上将从另一端继续向后扩展。
    segment = transition_segment_from_merge(route, transition, opposite_end_type(str(transition["to_end_type"])))
    # append 的语义与 prepend 对称：
    # 原 route 保持头部不变，只在尾部追加一条 bridge 和一个目标 sweep。
    return build_route(
        route_id=int(route["route_id"]),
        sweep_sequence=[*route["sweep_sequence"], target_sweep_id],
        segments=[*route.get("segments", ()), segment],
        start_end_type=str(route["start_end_type"]),
        end_end_type=str(opposite_end_type(str(transition["to_end_type"]))),
    )


def merge_routes(left: SweepCadenceRoute, right: SweepCadenceRoute, transition: SweepTransitionCandidateItem) -> SweepCadenceRoute:
    """基于一条精确 transition 构造 merged route。

    合并不会篡改左右两条 route 的内部顺序，
    只是在中间插入一条桥接 segment，
    把两段已成形路径接成一条更长路径。
    """

    # merge 不会改 left/right 内部已有 segments，只会在中间插一条桥接 transition。
    return build_route(
        route_id=int(left["route_id"]),
        sweep_sequence=[*left["sweep_sequence"], *right["sweep_sequence"]],
        segments=[
            *left.get("segments", ()),
            transition_segment_from_merge(left, transition, right["start_end_type"]),
            *right.get("segments", ()),
        ],
        start_end_type=str(left["start_end_type"]),
        end_end_type=str(right["end_end_type"]),
    )


def split_route_for_slot(route: SweepCadenceRoute, slot_index: int) -> tuple[SweepCadenceRoute, SweepCadenceRoute]:
    """按指定 slot 把 route 切成前后两段，供 singleton 插回时使用。

    `slot_index` 指向原 route 中的一条桥接 segment。
    切分后，prefix 负责保留该段前的路径，suffix 负责保留该段后的路径，
    便于把 singleton route 插进二者之间。
    """

    sweep_sequence = [int(item) for item in route.get("sweep_sequence", ())]
    segments = list(route.get("segments", ()))
    bridge_segment = dict(segments[slot_index])
    # slot_index 指向“桥接 segment”，所以前段保留它前面的部分，后段从它后面继续。
    prefix_sweeps = sweep_sequence[: slot_index + 1]
    suffix_sweeps = sweep_sequence[slot_index + 1 :]
    # prefix 停在桥接段之前的末 sweep；suffix 从桥接段之后的首 sweep 重新开始。
    return (
        build_route(
            route_id=int(route["route_id"]),
            sweep_sequence=prefix_sweeps,
            segments=segments[:slot_index],
            start_end_type=str(route["start_end_type"]),
            # prefix 的新尾端应停在被切掉桥接段的 entry 端，
            # 因为它再也不会穿过这条桥接段去到后半段了。
            end_end_type=str(bridge_segment["entry_end_type"]),
        ),
        build_route(
            route_id=int(route["route_id"]),
            sweep_sequence=suffix_sweeps,
            segments=segments[slot_index + 1 :],
            # suffix 的新起点要从桥接段 exit 的对侧重新解释，
            # 才符合 route 对“start_end_type = 该起始 sweep 上将从哪一端离开”的定义。
            start_end_type=str(opposite_end_type(str(bridge_segment["exit_end_type"]))),
            end_end_type=str(route["end_end_type"]),
        ),
    )


def count_route_endpoint_usage(routes: list[SweepCadenceRoute]) -> tuple[dict[int, int], dict[int, int]]:
    """统计每条 sweep 在 route 集合中被当作入端和出端使用的次数。

    这里只统计真实 transition，不把 foldback 当作图连接占用。
    这样得到的入/出次数更接近“正式 route 网络拓扑”本身，
    适合用于识别异常孤段和单侧缺口。
    """

    route_in_count: dict[int, int] = {}
    route_out_count: dict[int, int] = {}
    for route in routes:
        # 这里只统计真正的 transition。
        # foldback 只是在同 sweep 内翻端，不应该被视为“占用了一个图上的入/出连接”。
        for segment in route.get("segments", ()):
            if str(segment.get("primitive_type")) != "transition":
                continue
            # `from_sweep_id` 贡献一次正式出边占用，`to_sweep_id` 贡献一次正式入边占用。
            route_out_count[int(segment["from_sweep_id"])] = int(route_out_count.get(int(segment["from_sweep_id"]), 0)) + 1
            route_in_count[int(segment["to_sweep_id"])] = int(route_in_count.get(int(segment["to_sweep_id"]), 0)) + 1
    return route_in_count, route_out_count


def classify_abnormal_sweep_ids(
    routes: list[SweepCadenceRoute],
    *,
    context: CadenceContext,
) -> tuple[set[int], set[int], set[int]]:
    """识别尚未被主路径正常吸收的异常 sweep。

    返回三类集合：
    singleton 表示独立单点 route；
    none_connected 表示完全没有参与正式连接；
    one_side_connected 表示只接到一侧，后续通常还能做端点修补。
    """

    route_in_count, route_out_count = count_route_endpoint_usage(routes)
    singleton_sweep_ids: set[int] = set()
    none_connected_sweep_ids: set[int] = set()
    one_side_connected_sweep_ids: set[int] = set()
    for route in routes:
        sweep_sequence = tuple(int(item) for item in route.get("sweep_sequence", ()))
        if len(sweep_sequence) == 1:
            # singleton route 本身就是异常吸收器最关注的一类对象，先单独记出来。
            singleton_sweep_ids.add(int(sweep_sequence[0]))
        for sweep_id in sweep_sequence:
            in_count = int(route_in_count.get(int(sweep_id), 0))
            out_count = int(route_out_count.get(int(sweep_id), 0))
            # none_connected 表示完全没被主连接关系吸收；
            # one_side_connected 表示只接到一边，通常还可以做端点补齐。
            if in_count == 0 and out_count == 0:
                none_connected_sweep_ids.add(int(sweep_id))
            elif (in_count == 0 or out_count == 0) and not is_dead_end_like_sweep(context, int(sweep_id)):
                one_side_connected_sweep_ids.add(int(sweep_id))
    return singleton_sweep_ids, none_connected_sweep_ids, one_side_connected_sweep_ids

def merge_cadence_routes(
    routes: list[SweepCadenceRoute],
    transitions: tuple[SweepTransitionCandidateItem, ...],
    sweep_by_id: dict[int, SweepGraphSweep] | None = None,
    cadence_context: CadenceContext | None = None,
    route_edit_trace: list[dict] | None = None,
    stage_label: str = "merge",
) -> list[SweepCadenceRoute]:
    """在现有 transition 真值上尝试合并 cadence routes。

    merge 只消费已存在的 transition 真值，不创造新连接。
    它会反复寻找当前最优的首尾拼接机会，
    直到 route 集合中再也找不到合法、且 through 语义不冲突的合并为止。
    """

    # merge 只负责 route 首尾串接，不改 route 内部顺序，也不在这里发明新连接。
    # 它只消费 sweep graph 已经存在的精确 transition 真值。
    if len(routes) <= 1:
        # 少于两条 route 时，不存在首尾合并问题，直接原样返回。
        return routes
    transition_map = build_transition_index(transitions)
    working = [dict(route) for route in routes]
    while True:
        best_choice: tuple[int, int, SweepTransitionCandidateItem] | None = None
        best_key = None
        for i, left in enumerate(working):
            for j, right in enumerate(working):
                if i == j:
                    # 同一条 route 不能和自己做首尾合并，否则会在 repair 阶段引入显式自环。
                    continue
                transition = route_to_route_transition(transition_map, left, right)
                if transition is None:
                    # 没有精确 transition 命中时，这两条 route 在正式真值上就不存在可合并依据。
                    continue
                if cadence_context is not None and hypothetical_route_breaks(
                    left=left,
                    right=right,
                    transitions=[transition],
                    cadence_context=cadence_context,
                ):
                    # 图上能接通不代表 cadence 语义允许；through 违规的 merge 必须在这里直接丢弃。
                    continue
                key = (
                    # strong_keep merge 应优先于弱级别 merge。
                    0 if str(transition.get('selection_level', 'weak_keep')) == 'strong_keep' else 1,
                    # 直行 merge 通常更稳定，优先于非 straight motion。
                    0 if str(transition.get('motion_type', 'straight')) == 'straight' else 1,
                    # transition_count 为 0 的 route 更像 singleton/短 route，优先被吞并掉。
                    0 if int(left.get('transition_count', 0)) == 0 else 1,
                    0 if int(right.get('transition_count', 0)) == 0 else 1,
                    # risk 与 endpoint_distance 是局部连接质量证据；
                    # total_score 作为更综合的弱证据放得更靠后，避免重复主导排序。
                    float(transition.get('risk_score', 0.0)),
                    float(transition.get('endpoint_distance_m', 0.0)),
                    float(transition.get('total_score', 0.0)),
                    -float(transition.get('local_feasibility_score', 0.0)),
                    # 同 coverage lane 组只能在连接质量之后做弱偏好，
                    # 避免跨 group 场景下用未对齐的组内角色信息压过真实 pair 质量。
                    0 if follows_same_group(left, right, sweep_by_id) else 1,
                    # candidate_id 只承担稳定兜底职责，不表达“编号小就更好”。
                    int(transition.get('candidate_id', transition.get('transition_id', -1))),
                )
                # 合并排序优先看：
                # 1. transition 强弱与 motion 稳定性；
                # 2. 是否能优先消化 singleton/短 route；
                # 3. 风险、距离、总分和局部可行性；
                # 4. 是否同组延续。
                # 最后再用 candidate_id 做稳定兜底，保证同分场景下输出可复现。
                if best_key is None or key < best_key:
                    best_key = key
                    best_choice = (i, j, transition)
        if best_choice is None:
            # 扫完整个 working 集后都找不到合法拼接，就说明当前 route 集已经收敛。
            return working
        i, j, transition = best_choice
        # 每轮只执行当前最优 merge，再重新扫描 working，
        # 避免旧 route 组合关系在一次循环里被级联复用。
        merged = merge_routes(working[i], working[j], transition)
        append_route_edit_trace(
            route_edit_trace,
            stage=stage_label,
            operation="merge",
            transition=transition,
            before_routes=[working[i], working[j]],
            after_route=merged,
            all_routes_before=working,
            decision_key=best_key,
            reason="route_to_route_transition",
        )
        working = [route for idx, route in enumerate(working) if idx not in {i, j}] + [merged]


__all__ = (
    'build_route',
    'build_transition_index',
    'classify_abnormal_sweep_ids',
    'count_route_endpoint_usage',
    'extend_route',
    'follows_same_group',
    'append_route_edit_trace',
    'hypothetical_route_breaks',
    'merge_routes',
    'merge_cadence_routes',
    'route_breaks_through_semantics',
    'route_last_motion_type',
    'route_to_route_transition',
    'split_route_for_slot',
    'split_route_on_first_through_violation',
    'transition_segment_from_merge',
)
