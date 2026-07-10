"""
用途：构造 sweep graph 层的正式 transition candidate。
输入：sweep group、port view、sweep 几何，以及 topology 层下发的 node-local hypothesis。
输出：只包含正式 candidate item 与摘要的 SweepTransitionCandidateInfo。
限制：
    1. 当前实现只产出正式候选，不再保留旧的 weak/fallback/reject 多层筛选树。
    2. 主线连接来源是 node-local hypothesis，group 内横移候选只作为补充正规候选。
"""

from __future__ import annotations

import math
from typing import Any

from ...contracts import (
    SweepGroupInfo,
    SweepGroupItem,
    SweepInfo,
    SweepPortViewInfo,
    SweepTransitionCandidateInfo,
    SweepTransitionCandidateItem,
)
from ..common_geometry import (
    local_feasibility_from_geometry,
    min_sweep_endpoint_distance,
    normalize_signed_angle_deg,
    sweep_endpoint_distance_between_sweeps,
    sweep_endpoint_distance_for_end_types,
    sweep_turn_delta_deg_between_sweeps,
)


def build_sweep_transition_candidates(
    sweep_group_info: SweepGroupInfo,
    sweep_port_view_info: SweepPortViewInfo,
    sweeps: tuple[SweepInfo, ...] | list[SweepInfo],
    node_local_connection_hypothesis_info: dict[str, Any] | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> SweepTransitionCandidateInfo:
    """把 topology 正式连接和组内横移规则直接展开成正式 sweep 候选。"""

    # 这个构建器的职责很窄：
    # 1. 把 topology 层已经确认的连接真值投影成 sweep pair。
    # 2. 补充少量组内横移正式候选。
    # 它不负责做 reject/fallback 分层，也不在这里再做一轮 topology 真假判断。

    # group 内横移只允许在很近的 rank 邻域里发生。
    # 这里把它收成配置，是为了让“lane 映射候选”和“group 内补充横移”共用一套可控边界。
    max_rank_gap = max(1, int((config or {}).get('max_rank_gap', 2)))
    # 跨 group 的 pair 生成按 sweep 端点几何输出多候选集合。
    # 这里的 top-k 是“每个 from sweep 最多保留多少个几何可解释出口”，用于控制候选规模，
    # 不是替 cadence 提前做最终选择。
    max_cross_group_targets_per_sweep = max(1, int((config or {}).get('max_cross_group_targets_per_sweep', 3)))
    # 下面三张 lookup 是后续所有展开 helper 的稳定输入视图。
    # 先一次性标准化，避免每个 helper 都重复处理键类型和默认值。
    groups_by_edge_id = {int(edge_id): value for edge_id, value in sweep_group_info.get('group_by_edge_id', {}).items()}
    port_lookup = dict(sweep_port_view_info.get('lookup', {}))
    sweeps_by_id = {int(item['sweep_id']): item for item in sweeps}
    candidate_items: list[SweepTransitionCandidateItem] = []

    # 主线候选先从 topology hypothesis 投影而来。
    # 这一步负责把“边级连接真值”落到“sweep 对应关系”。
    # 如果 hypothesis 无法解析到 group/port，就直接丢弃，
    # 因为这说明它在当前 sweep 图构建上下文里没有可落地的几何/排序支撑。
    for lane in synthesize_lanes_from_hypotheses(node_local_connection_hypothesis_info):
        context = resolve_lane_context(lane, groups_by_edge_id, port_lookup)
        if context is None:
            # group/port 任一侧无法闭环时，说明这条 topology 连接在当前 sweep 世界里不可物化。
            continue
        candidate_items.extend(
            build_lane_candidates(
                lane,
                context,
                sweeps_by_id,
                len(candidate_items) + 1,
                max_cross_group_targets_per_sweep=max_cross_group_targets_per_sweep,
            )
        )

    # group 内横移候选放在 topology 主线之后追加。
    # 这样 summary 仍覆盖全量正式候选，但不让横移规则反过来影响主线 pair 展开。
    candidate_items.extend(
        build_group_internal_candidates(
            sweep_group_info=sweep_group_info,
            sweep_port_view_info=sweep_port_view_info,
            sweeps_by_id=sweeps_by_id,
            start_candidate_id=len(candidate_items) + 1,
            max_rank_gap=max_rank_gap,
        )
    )

    return {
        'items': tuple(candidate_items),
        'summary': {
            'candidate_count': int(len(candidate_items)),
            'strong_candidate_count': int(len(candidate_items)),
            'weak_candidate_count': 0,
            'fallback_candidate_count': 0,
            'forward_candidate_count': int(sum(1 for item in candidate_items if str(item.get('connection_kind')) == 'forward')),
            'foldback_candidate_count': int(sum(1 for item in candidate_items if str(item.get('connection_kind')) == 'foldback')),
        },
    }


def synthesize_lanes_from_hypotheses(
    node_local_connection_hypothesis_info: dict[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    """把 node-local hypothesis 投影成 sweep 层只需要的 lane 视图。"""

    # 这里故意不把上游 hypothesis 整体原样透传下来，
    # 而是收缩成 sweep 展开最小字段集，避免 sweep_graph 再次依赖 topology 内部细节。
    items: list[dict[str, Any]] = []
    seen_hypothesis_ids: set[int] = set()
    for hypothesis in tuple((node_local_connection_hypothesis_info or {}).get('items', ())):
        hypothesis_id = int(hypothesis.get('hypothesis_id', -1))
        if hypothesis_id >= 0 and hypothesis_id in seen_hypothesis_ids:
            # hypothesis 本身是 topology 正式对象，不应在 sweep 层重复投影出两份 lane 视图。
            continue
        if hypothesis_id >= 0:
            seen_hypothesis_ids.add(hypothesis_id)
        raw_kind = str(hypothesis.get('connection_kind', 'forward'))
        items.append(
            {
                'lane_id': int(len(items) + 1),
                # 这里新分配的是 sweep_graph 层 lane_id，不等同于 topology 的 hypothesis_id。
                # 两者都保留，是为了让下游既有稳定顺序 id，也能回溯原始 hypothesis。
                'source_hypothesis_id': hypothesis_id if hypothesis_id >= 0 else None,
                'candidate_source': 'node_projected',
                'via_node_id': int(hypothesis['via_node_id']),
                'in_edge_id': int(hypothesis['in_edge_id']),
                'out_edge_id': int(hypothesis['out_edge_id']),
                # 这里保留 topology 已经推断好的 in/out 端型。
                # 后续 resolve_lane_context 会再结合 group src/dst 真值做一次正式校准。
                'in_end_type': str(hypothesis.get('in_end_type', 'src')),
                'out_end_type': str(hypothesis.get('out_end_type', 'dst')),
                'connection_kind': normalize_connection_kind(raw_kind),
                'motion_type': classify_motion_type(hypothesis.get('turn_delta_deg_image')),
                # 历史连接语义降级成 trace 信息，只保留可追溯性，不再作为主枚举继续横穿主线。
                'source_trace_label': raw_kind,
                'trace_tags': () if raw_kind in {'forward', 'transition'} else (raw_kind,),
            }
        )
    return tuple(items)


def normalize_connection_kind(raw_kind: object) -> str:
    """把 topology 历史连接语义收口成 `forward / foldback`。"""

    # 当前 sweep 主线只保留 forward/foldback 两类主语义。
    # dead_end_return 在这里并入 foldback，避免旧语义继续扩散到 cadence/final-path。
    # 这里不再额外保留 transition/turn 等子类枚举，
    # 这些更细的运动差异统一交给 motion_type 表达。
    return 'foldback' if str(raw_kind or 'forward') in {'dead_end_return', 'foldback'} else 'forward'


def classify_motion_type(turn_delta_deg: float | None) -> str:
    """根据拓扑转角给候选标注一个稳定的运动语义。"""

    if turn_delta_deg is None:
        # 没有可靠角度时，宁可先回到 straight，
        # 也不要在 sweep 层伪造 left/right/foldback 这类强语义。
        return 'straight'
    turn_delta = float(turn_delta_deg)
    if not math.isfinite(turn_delta):
        # 非有限角度通常来自上游没有可靠方向信息的节点，保守回退成 straight。
        return 'straight'
    if abs(abs(turn_delta) - 180.0) <= 30.0:
        return 'foldback'
    if abs(turn_delta) <= 35.0:
        return 'straight'
    return 'left_turn' if turn_delta > 0.0 else 'right_turn'


def resolve_lane_context(
    lane: dict[str, Any],
    groups_by_edge_id: dict[int, SweepGroupItem],
    port_lookup: dict[tuple[int, int, str], Any],
) -> dict[str, Any] | None:
    """把一个 topology lane 解析成 group/port/end_type 真值。"""

    # lane 只保存 edge id，真正的 sweep 展开必须回到 group 层拿 sweep 集和 port 排序。
    # 也就是说，lane 在这里更像“连接意图”，context 才是“可执行的正式真值上下文”。
    from_group = groups_by_edge_id.get(int(lane['in_edge_id']))
    to_group = groups_by_edge_id.get(int(lane['out_edge_id']))
    if from_group is None or to_group is None:
        # 任何一侧 edge_id 找不到正式 group，都说明这条 topology lane 没法落回 sweep group 世界。
        # 这里返回 None 的语义不是“暂时跳过”，而是“这条 lane 在当前 sweep 图里不可物化”。
        return None
    via_node_id = int(lane['via_node_id'])
    # 端型优先遵循 group 的 src/dst 真值。
    # 只有 self-loop 或 group 缺字段时，才退回上游 hypothesis 提供的 preferred_end_type。
    from_end_type = resolve_group_end_type(from_group, via_node_id, str(lane.get('in_end_type', 'src')))
    to_end_type = resolve_group_end_type(to_group, via_node_id, str(lane.get('out_end_type', 'dst')))
    if from_end_type is None or to_end_type is None:
        # 端型定不下来时，就无法知道 lane 是从 group 的哪一端进入、从哪一端离开。
        # 如果继续往下查 port，会把 src/dst 语义混掉，所以这里必须整条 lane 失效。
        return None
    # lookup 优先读三元 key；二元 key 只是兼容旧测试/旧构造方式的回退口径。
    # 这里要求端型已经先被确定下来，再去取 port，
    # 避免把 src/dst 混读成同一个 port view，造成后续 rank 对齐失真。
    from_port = port_lookup.get((int(from_group['group_id']), via_node_id, from_end_type)) or port_lookup.get((int(from_group['group_id']), via_node_id))
    to_port = port_lookup.get((int(to_group['group_id']), via_node_id, to_end_type)) or port_lookup.get((int(to_group['group_id']), via_node_id))
    if from_port is None or to_port is None:
        # 这里缺的不是“某个可选附加字段”，而是 sweep 对齐所依赖的正式 port 排序真值。
        # 没有任一侧 port，就没法做 rank/center 对齐，因此整条 lane 不能生成正式 candidate。
        return None
    return {
        'via_node_id': via_node_id,
        'from_group': from_group,
        'to_group': to_group,
        'from_port': from_port,
        'to_port': to_port,
        'from_end_type': from_end_type,
        'to_end_type': to_end_type,
    }


def resolve_group_end_type(group: SweepGroupItem, node_id: int, preferred_end_type: str) -> str | None:
    """在普通边和 self-loop 边上，统一确定当前 node 对应的 src/dst 端口。"""

    src_node_id = group.get('src_node_id')
    dst_node_id = group.get('dst_node_id')
    if src_node_id is None or dst_node_id is None:
        # group 真值不完整时，只能保守沿用调用方偏好端型。
        return preferred_end_type if preferred_end_type in {'src', 'dst'} else 'src'
    if int(src_node_id) == int(node_id) and int(dst_node_id) == int(node_id):
        # self-loop 场景中 node 同时是 src/dst，必须尊重外层选择的端型，否则会把回环错误压成单端。
        return preferred_end_type if preferred_end_type in {'src', 'dst'} else 'src'
    if int(src_node_id) == int(node_id):
        return 'src'
    if int(dst_node_id) == int(node_id):
        return 'dst'
    # 走到这里说明给定 node 不在 group 两端真值里。
    # 对普通边这是异常场景，只在 preferred 合法时保守回退。
    return preferred_end_type if preferred_end_type in {'src', 'dst'} else None


def build_lane_candidates(
    lane: dict[str, Any],
    context: dict[str, Any],
    sweeps_by_id: dict[int, SweepInfo],
    start_candidate_id: int,
    *,
    max_cross_group_targets_per_sweep: int,
) -> list[SweepTransitionCandidateItem]:
    """为单条 topology lane 直接生成正式 sweep 候选。"""

    if str(lane.get('connection_kind', 'forward')) == 'foldback':
        # foldback 不是“两个 sweep 之间做映射”，而是“同一条 sweep 内翻端”。
        # 因此它必须走单独的同 sweep 物化逻辑，不能混进普通 pair 映射。
        return build_foldback_candidates(lane, context, sweeps_by_id, start_candidate_id)

    # 普通主线连接按 sweep 端点几何展开多候选。
    # from/to port 只提供“哪些 sweep 属于当前端口视图”的正式集合，
    # 具体 pair 是否合理由指定端型的端点距离、端点方向夹角和 motion_type 共同解释。
    pairs, mapping_type = choose_lane_pairs(
        context=context,
        sweeps_by_id=sweeps_by_id,
        motion_type=str(lane.get('motion_type', 'straight')),
        max_targets_per_sweep=max_cross_group_targets_per_sweep,
    )
    # 若 choose_lane_pairs 返回空列表，含义是“这条 lane 在当前两侧端口序上找不到正式 sweep 几何配对”。
    # 这里顺势返回空 candidate 集，让上游保留“lane 存在但无法物化”的裁决结果。
    return [
        build_candidate_item(
            lane=lane,
            context=context,
            sweeps_by_id=sweeps_by_id,
            mapping_type=mapping_type,
            pair_index=pair_index,
            from_sweep_id=from_sweep_id,
            to_sweep_id=to_sweep_id,
            candidate_id=start_candidate_id + pair_index - 1,
        )
        for pair_index, (from_sweep_id, to_sweep_id) in enumerate(pairs, start=1)
    ]


def choose_lane_pairs(
    *,
    context: dict[str, Any],
    sweeps_by_id: dict[int, SweepInfo],
    motion_type: str,
    max_targets_per_sweep: int,
) -> tuple[list[tuple[int, int]], str]:
    """按 sweep 端点几何生成跨 group 多候选 pair。"""

    ordered_from = [int(item) for item in context['from_port'].get('ordered_port_sweep_ids', ())]
    ordered_to = [int(item) for item in context['to_port'].get('ordered_port_sweep_ids', ())]
    if not ordered_from or not ordered_to:
        # 任一端没有正式 port sweep 序列，都无法构造可解释的跨 group pair。
        return [], 'endpoint_geometry'

    scored_by_from: dict[int, list[tuple[float, int, int]]] = {}
    for from_sweep_id in ordered_from:
        if int(from_sweep_id) not in sweeps_by_id:
            # port view 里出现但 sweeps 主表不存在，说明当前 candidate 构造缺少正式几何。
            # 跨 group 连接必须依赖真实端点几何，所以不能用 id 占位继续生成。
            continue
        for to_sweep_id in ordered_to:
            if int(to_sweep_id) not in sweeps_by_id:
                # to 侧同理，缺几何就无法计算 B/C 距离和 sweep 级转角。
                continue
            if int(from_sweep_id) == int(to_sweep_id):
                # 普通 forward lane 不在这里生成同 sweep 翻端；
                # 同 sweep 语义由 foldback 专用逻辑负责，避免 forward/foldback 混线。
                continue
            score = score_cross_group_pair(
                from_sweep=sweeps_by_id[int(from_sweep_id)],
                to_sweep=sweeps_by_id[int(to_sweep_id)],
                from_end_type=str(context['from_end_type']),
                to_end_type=str(context['to_end_type']),
                motion_type=str(motion_type),
            )
            scored_by_from.setdefault(int(from_sweep_id), []).append((float(score), int(from_sweep_id), int(to_sweep_id)))

    selected: list[tuple[float, int, int]] = []
    for from_sweep_id in ordered_from:
        # 每个 from sweep 独立保留 top-k 出口，避免一个几何极近 sweep 把其它 from sweep 的候选空间挤掉。
        # 排序只看 sweep 级几何分和 sweep_id 稳定 tie-break，不使用跨 group rank 做主比较。
        ranked = sorted(scored_by_from.get(int(from_sweep_id), ()), key=lambda item: (item[0], item[2]))
        selected.extend(ranked[:max_targets_per_sweep])
    selected.sort(key=lambda item: (item[1], item[0], item[2]))
    return [(int(from_sweep_id), int(to_sweep_id)) for _, from_sweep_id, to_sweep_id in selected], 'endpoint_geometry'


def score_cross_group_pair(
    *,
    from_sweep: SweepInfo,
    to_sweep: SweepInfo,
    from_end_type: str,
    to_end_type: str,
    motion_type: str,
) -> float:
    """计算跨 group pair 的 sweep 级几何排序分。"""

    endpoint_distance = sweep_endpoint_distance_between_sweeps(
        from_sweep,
        to_sweep,
        from_end_type=from_end_type,
        to_end_type=to_end_type,
    )
    turn_delta = sweep_turn_delta_deg_between_sweeps(
        from_sweep,
        to_sweep,
        from_end_type=from_end_type,
        to_end_type=to_end_type,
    )
    # endpoint_distance 是最直接的连接代价，turn penalty 用于表达“这条具体 sweep pair 是否符合 topology motion 期望”。
    # 这里不把 rank 放进跨 group 主分数，避免把两个 group 内部各自的排序误当成空间对应关系。
    return float(endpoint_distance + 0.02 * motion_turn_penalty_deg(motion_type=str(motion_type), turn_delta_deg=turn_delta))


def motion_turn_penalty_deg(*, motion_type: str, turn_delta_deg: float) -> float:
    """把 sweep 级端点转角折成与 motion_type 对齐的角度惩罚。"""

    if not math.isfinite(float(turn_delta_deg)):
        # 缺少可靠角度时给中等惩罚，而不是直接踢掉候选。
        # topology hypothesis 已经给出了连接许可，candidate 层只降低排序优先级。
        return 90.0
    motion = str(motion_type)
    abs_delta = abs(normalize_signed_angle_deg(float(turn_delta_deg)))
    if motion == 'straight':
        # straight 期望两条 sweep 方向顺接，端点方向夹角越接近 0 越好。
        return abs_delta
    if motion == 'foldback':
        # foldback 期望接近 180 度反向，但普通 forward lane 很少走到这里；
        # 保留该分支是为了复用 motion_type 的统一含义，而不是新增 foldback 语义。
        return abs(abs_delta - 180.0)
    if motion in {'left_turn', 'right_turn'}:
        # 左右转不强制固定角度，只要求它明显不是 straight，也不要接近完整反折。
        if 35.0 <= abs_delta <= 145.0:
            return 0.0
        return min(abs(abs_delta - 35.0), abs(abs_delta - 145.0))
    # lateral 或未知 motion 保守按端点角度自身排序。
    return abs_delta


def build_foldback_candidates(
    lane: dict[str, Any],
    context: dict[str, Any],
    sweeps_by_id: dict[int, SweepInfo],
    start_candidate_id: int,
) -> list[SweepTransitionCandidateItem]:
    """为 dead-end / same-edge 回折生成同 sweep 的正式候选。"""

    port = context['from_port']
    from_end_type = str(context['from_end_type'])
    to_end_type = 'dst' if from_end_type == 'src' else 'src'
    items: list[SweepTransitionCandidateItem] = []
    port_rank_by_sweep_id = {int(k): int(v) for k, v in dict(port.get('port_rank_by_sweep_id', {})).items()}
    for pair_index, sweep_id in enumerate(tuple(port.get('ordered_port_sweep_ids', ())), start=1):
        sweep_id = int(sweep_id)
        # foldback 直接在当前 sweep 上翻端，因此 from/to 都是同一个 sweep_id。
        # 端点距离只用来描述这条 sweep 自身 src/dst 两端的几何跨度。
        # 这里不会跨 sweep 生成 pair，因为回折的本质不是“换到邻近 sweep”，
        # 而是“在同一覆盖条带走到尽头后翻端返回”。
        endpoint_distance = sweep_endpoint_distance_for_end_types(
            sweeps_by_id[sweep_id],
            from_end_type=from_end_type,
            to_end_type=to_end_type,
        )
        items.append(
            {
                'candidate_id': int(start_candidate_id + pair_index - 1),
                'source_topology_lane_id': int(lane['lane_id']),
                'source_hypothesis_id': lane.get('source_hypothesis_id'),
                'candidate_source': str(lane.get('candidate_source', 'node_projected')),
                'via_node_id': int(context['via_node_id']),
                'from_group_id': int(context['from_group']['group_id']),
                'to_group_id': int(context['from_group']['group_id']),
                'from_sweep_id': sweep_id,
                'to_sweep_id': sweep_id,
                'from_end_type': from_end_type,
                'to_end_type': to_end_type,
                'same_sweep': True,
                'same_edge': True,
                'connection_kind': 'foldback',
                'motion_type': 'foldback',
                'mapping_type': 'same_sweep_foldback',
                'mapping_pair_index': int(pair_index),
                'from_port_rank': int(port_rank_by_sweep_id.get(sweep_id, -1)),
                'to_port_rank': int(port_rank_by_sweep_id.get(sweep_id, -1)),
                'rank_gap': 0,
                'endpoint_distance_m': float(endpoint_distance),
                'sweep_turn_delta_deg': 180.0,
                'local_feasibility_score': 1.0,
                'risk_score': 0.0,
                'coverage_gain_score': 1.0,
                'total_score': float(endpoint_distance),
                'confidence_score': 1.0,
                'selection_level': 'strong_keep',
                'trace_tags': tuple(lane.get('trace_tags', ())),
                'source_trace_label': str(lane.get('source_trace_label', 'foldback')),
            }
        )
    return items


def build_group_internal_candidates(
    sweep_group_info: SweepGroupInfo,
    sweep_port_view_info: SweepPortViewInfo,
    sweeps_by_id: dict[int, SweepInfo],
    *,
    start_candidate_id: int,
    max_rank_gap: int,
) -> list[SweepTransitionCandidateItem]:
    """在同一 group 同一端口内，生成相邻 sweep 的横向正式候选。"""

    lookup = dict(sweep_port_view_info.get('lookup', {}))
    candidate_items: list[SweepTransitionCandidateItem] = []
    # 只有这些 edge_type 才允许在本组内做横移。
    # 其它 edge_type 要么没有稳定的双端覆盖关系，要么不应把同端横移当正式连接。
    accepted_edge_types = {'connected_both_ends', 'dead_end_one_side', 'dead_end_both_sides', 'cycle'}
    for group in tuple(sweep_group_info.get('groups', ())):
        # 当前这一步只补“边语义仍稳定、端口排序仍可信”的 group。
        # 这里的白名单不是“推荐类型”，而是“允许进入 group_internal lateral 正式展开”的前置条件。
        # 默认按 `connected_both_ends` 解释，是因为上游正常主线 group 大多属于双端连通；
        # 它只是缺字段时的保守主路径口径，不是在这里替上游修正 edge_type。
        # 如果某个 group 不在白名单里，就说明它的边语义不适合把同端相邻 sweep 当成正式横移连接，
        # 再往下展开会把不稳定边段误写进 sweep graph 正式候选集合。
        if str(group.get('edge_type', 'connected_both_ends')) not in accepted_edge_types:
            continue
        for end_type, node_id in (('src', int(group['src_node_id'])), ('dst', int(group['dst_node_id']))):
            # group 内横移仍然必须基于正式 port view，而不是直接按 sweep_id 邻接猜测。
            port_view = lookup.get((int(group['group_id']), int(node_id), str(end_type))) or lookup.get((int(group['group_id']), int(node_id)))
            if port_view is None:
                # port view 缺失时，表示这个 group 在当前端口没有正式 sweep 排序真值。
                # 这时即便 sweep_id 看起来相邻，也不能凭编号硬造横移候选，所以整端直接跳过。
                continue
            ordered_ids = [int(item) for item in port_view.get('ordered_port_sweep_ids', ())]
            rank_by_sweep_id = {int(k): int(v) for k, v in dict(port_view.get('port_rank_by_sweep_id', {})).items()}
            for left_index, from_sweep_id in enumerate(ordered_ids):
                # 这里只展开有限 rank_gap 邻域，避免把远距离横移误记成正式局部连接。
                for right_index in range(left_index + 1, min(len(ordered_ids), left_index + max_rank_gap + 1)):
                    to_sweep_id = int(ordered_ids[right_index])
                    # 同一对相邻 sweep 需要展开成双向候选。
                    # 原因是 cadence/final-path 选择时方向敏感，不能把一条无向邻接边偷换成单向事实。
                    for a, b in ((from_sweep_id, to_sweep_id), (to_sweep_id, from_sweep_id)):
                        from_rank = int(rank_by_sweep_id.get(int(a), -1))
                        to_rank = int(rank_by_sweep_id.get(int(b), -1))
                        endpoint_distance = pair_endpoint_distance(sweeps_by_id[int(a)], sweeps_by_id[int(b)])
                        rank_gap = abs(from_rank - to_rank)
                        candidate_items.append(
                            {
                                'candidate_id': int(start_candidate_id + len(candidate_items)),
                                'source_topology_lane_id': -1,
                                'source_hypothesis_id': None,
                                'candidate_source': 'group_internal',
                                'via_node_id': int(node_id),
                                'from_group_id': int(group['group_id']),
                                'to_group_id': int(group['group_id']),
                                'from_sweep_id': int(a),
                                'to_sweep_id': int(b),
                                'from_end_type': str(end_type),
                                'to_end_type': str(end_type),
                                'same_sweep': False,
                                'same_edge': True,
                                'connection_kind': 'forward',
                                'motion_type': 'lateral',
                                'mapping_type': 'adjacent_same_side',
                                'mapping_pair_index': int(min(from_rank, to_rank) + 1),
                                'from_port_rank': from_rank,
                                'to_port_rank': to_rank,
                                'rank_gap': int(rank_gap),
                                'endpoint_distance_m': float(endpoint_distance),
                                'sweep_turn_delta_deg': 0.0,
                                'local_feasibility_score': float(max(0.0, 1.0 - 0.25 * rank_gap)),
                                # 组内横移没有 topology 真值兜底，
                                # 所以这里的风险/收益更依赖 rank_gap 这种局部秩序信号。
                                'risk_score': float(rank_gap),
                                'coverage_gain_score': float(max(0.0, 1.0 - 0.25 * rank_gap)),
                                'total_score': float(endpoint_distance + 2.0 * rank_gap),
                                'confidence_score': 1.0,
                                'selection_level': 'strong_keep',
                                'trace_tags': ('lateral',),
                                'source_trace_label': 'group_internal_lateral',
                            }
                        )
    return candidate_items


def build_candidate_item(
    *,
    lane: dict[str, Any],
    context: dict[str, Any],
    sweeps_by_id: dict[int, SweepInfo],
    mapping_type: str,
    pair_index: int,
    from_sweep_id: int,
    to_sweep_id: int,
    candidate_id: int,
) -> SweepTransitionCandidateItem:
    """把一个正式 pair 物化成 sweep_transition_candidate item。"""

    # build_candidate_item 只做字段归一和轻量评分封装。
    # 它不再尝试改写映射结果，确保“pair 是什么”与“如何落字段”分层清楚。
    from_port_rank = int(context['from_port']['port_rank_by_sweep_id'].get(int(from_sweep_id), -1))
    to_port_rank = int(context['to_port']['port_rank_by_sweep_id'].get(int(to_sweep_id), -1))
    endpoint_distance = sweep_endpoint_distance_between_sweeps(
        sweeps_by_id[int(from_sweep_id)],
        sweeps_by_id[int(to_sweep_id)],
        from_end_type=str(context['from_end_type']),
        to_end_type=str(context['to_end_type']),
    )
    sweep_turn_delta_deg = sweep_turn_delta_deg_between_sweeps(
        sweeps_by_id[int(from_sweep_id)],
        sweeps_by_id[int(to_sweep_id)],
        from_end_type=str(context['from_end_type']),
        to_end_type=str(context['to_end_type']),
    )
    rank_gap = abs(from_port_rank - to_port_rank)
    # 普通跨 group transition 的风险由 sweep 级几何主导。
    # rank_gap 写入 item 供审计解释；跨 group 主风险由端点几何和局部可行性表达。
    turn_penalty = motion_turn_penalty_deg(
        motion_type=str(lane.get('motion_type', 'straight')),
        turn_delta_deg=sweep_turn_delta_deg,
    )
    local_feasibility_score = local_feasibility_from_geometry(
        endpoint_distance_m=float(endpoint_distance),
        turn_penalty_deg=float(turn_penalty),
    )
    risk_score = float((1.0 - local_feasibility_score) * 10.0)
    return {
        'candidate_id': int(candidate_id),
        'source_topology_lane_id': int(lane['lane_id']),
        'source_hypothesis_id': lane.get('source_hypothesis_id'),
        'candidate_source': str(lane.get('candidate_source', 'node_projected')),
        'via_node_id': int(context['via_node_id']),
        'from_group_id': int(context['from_group']['group_id']),
        'to_group_id': int(context['to_group']['group_id']),
        'from_sweep_id': int(from_sweep_id),
        'to_sweep_id': int(to_sweep_id),
        'from_end_type': str(context['from_end_type']),
        'to_end_type': str(context['to_end_type']),
        'same_sweep': bool(int(from_sweep_id) == int(to_sweep_id)),
        # same_edge 用 source_edge_id 判断，而不是 group_id。
        # 同一条物理 edge 在不同 group 表达下仍应被识别成 same_edge。
        'same_edge': bool(int(context['from_group']['source_edge_id']) == int(context['to_group']['source_edge_id'])),
        'connection_kind': str(lane.get('connection_kind', 'forward')),
        'motion_type': str(lane.get('motion_type', 'straight')),
        'mapping_type': mapping_type,
        'mapping_pair_index': int(pair_index),
        'from_port_rank': from_port_rank,
        'to_port_rank': to_port_rank,
        'rank_gap': int(rank_gap),
        'endpoint_distance_m': float(endpoint_distance),
        'sweep_turn_delta_deg': float(sweep_turn_delta_deg),
        'local_feasibility_score': float(local_feasibility_score),
        'risk_score': risk_score,
        # coverage_gain_score 表达这条跨 group 候选对连续推进的几何支持程度。
        # 它复用 local_feasibility_score，不再把跨 group rank 差当成收益主依据。
        'coverage_gain_score': float(local_feasibility_score),
        # total_score 与 choose_lane_pairs 的几何排序口径保持一致：
        # 端点距离是主代价，端点转角惩罚是次级几何校验。
        'total_score': float(endpoint_distance + 0.02 * turn_penalty),
        'confidence_score': 1.0,
        'selection_level': 'strong_keep',
        'trace_tags': tuple(lane.get('trace_tags', ())),
        'source_trace_label': str(lane.get('source_trace_label', 'forward')),
    }


def pair_endpoint_distance(in_sweep: SweepInfo, out_sweep: SweepInfo) -> float:
    """返回两条 sweep 四种端点组合里的最短米制距离。"""

    # 同 group 横移需要的是“两个 sweep 四端里最近能靠多近”的邻近证据；
    # 具体跨 group from/to 端型距离已经由共享几何层的指定端型 helper 负责。
    return float(min_sweep_endpoint_distance(in_sweep, out_sweep))


__all__ = ('build_sweep_transition_candidates',)
