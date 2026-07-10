# SweepCadence 规则方案

## 1. 文档定位

本文档只描述当前源码中 `build_sweep_cadence(...)` 这一层的真实输入、真实 route contract、真实 greedy 求解主线以及后处理链。

本文档的边界很明确：

- 只解释当前源码已经存在的 cadence 结构
- 不把 cadence 改写成源码里不存在的 `ordered_items` world
- 不把 final path 的几何求解混进 cadence 文档

## 2. 当前主线定位

当前工程主线是：

- `sweep_transition_candidate_info + greedy SweepCadence`

当前明确不做：

- 不扩新 solver
- 不引入 ILP / MIP
- 不把 cadence 解释成单纯最短路

当前 cadence 的角色不是：

- “把 sweep 都串一下就行”

而是：

- 在 sweep transition 候选真值上生成一条更接近人类扫地节奏的高层 sweep 顺序骨架

## 3. 当前输入与输出

### 3.1 输入

- `coverage_lane_sweep_info.sweeps`
- `sweep_transition_candidate_info.items`
- `graph_info.nodes`

### 3.2 输出

- `sweep_cadence_info`

当前正式输出结构是：

- `routes`
- `route_sweep_order`
- `ordered_passes`
- `summary`

## 4. `sweep_cadence_info` 的正式字段

### 4.1 `routes`

每条 route 当前至少包含：

- `route_id`
  - route 唯一编号
- `sweep_sequence`
  - route 中 sweep 的真实访问顺序
- `transition_sequence`
  - route 中使用到的 transition id 顺序
- `segments`
  - route 中相邻 sweep 之间的正式关系真值
- `start_sweep_id`
  - route 起始 sweep id
- `end_sweep_id`
  - route 终止 sweep id
- `start_end_type`
  - route 进入首 sweep 的端类型
- `end_end_type`
  - route 离开尾 sweep 的端类型
- `sweep_count`
  - route 中 sweep 项数量
- `transition_count`
  - route 中 transition primitive 数量

### 4.2 `route_sweep_order`

每项至少包含：

- `sweep_id`
- `route_id`
- `order_in_route`

这是一张扁平索引表，方便做：

- 覆盖率统计
- route 内顺序查找
- 调试和审图

### 4.3 `summary`

当前至少包含：

- `solver`
- `cadence_count`
- `covered_sweep_count`

## 5. `segments` 是 final path 必须消费的真值

当前 cadence route 里，`segments` 不是 debug 附件，而是 final path 必须消费的正式真值。

每个 segment 当前至少包含：

- `from_sweep_id`
  - 当前段起始 sweep id
- `to_sweep_id`
  - 当前段目标 sweep id
- `via_node_id`
  - 当前转移经过的节点 id
  - `u_turn` 时可能为 `-1`
- `candidate_level`
  - 当前段来源 transition 的候选级别
- `requires_junction_connection`
  - 这段在 final path 中是否需要显式构造路口连接
- `entry_end_type`
  - 这一段进入 `from_sweep` 后从哪一端离开
- `exit_end_type`
  - 这一段离开 `to_sweep` 时最终停在哪个端
- `primitive_type`
  - 当前只可能是：
    - `transition`
    - `u_turn`
- `is_repeat_coverage_transition`
  - 这一步是否是通过已覆盖 sweep 做短程 connector
- `u_turn_penalty`
  - 当前段的 `u_turn` 代价
- `transition_id`
  - 若是普通 transition，对应正式 transition id
  - 若是 `u_turn`，当前为 `-1`
- `turn_type`
  - 当前动作的转向类型

这里要特别强调：

- final path 不是只读 `sweep_sequence`
- 它还必须读 `segments + start_end_type + end_end_type`

## 6. cadence 的真实输入图

`build_sweep_cadence(...)` 当前不会直接在 `graph_info` 上工作，而是先把 `sweeps + kept transition candidates + nodes` 收成 `_CadenceContext`。

### 6.1 `_CadenceContext` 字段

- `sweeps`
  - 全部 active sweeps
- `transitions`
  - 全部 kept sweep transition candidates
- `sweep_by_id`
  - `sweep_id -> sweep`
- `node_by_id`
  - `node_id -> node`
- `outgoing`
  - `(from_sweep_id, from_end_type) -> transitions`

### 6.2 `outgoing` 的语义

`outgoing[(from_sweep_id, from_end_type)]` 是 cadence greedy 扩展时的直接候选索引。

也就是说，当前 cadence 求解时真正问的问题是：

- “我现在站在某条 sweep 的某一端，从这个端出去有哪些 transition 可以走？”

## 7. greedy route state 的正式字段

当前 `_GreedyRouteState` 至少包含：

- `start_sweep_id`
  - 这条 route 从哪条 sweep 起步
- `start_end_type`
  - 进入起始 sweep 时的进入端
- `current_sweep_id`
  - 当前 route 头部所在的 sweep
- `current_exit_end`
  - 当前 route 头部可用的退出端
- `previous_turn_type`
  - 上一步的转向类型
- `sweep_sequence`
  - 当前累计扫过的 sweep 顺序
- `transition_sequence`
  - 当前累计使用的 transition id 顺序
- `segments`
  - 当前累计形成的 segment 真值链
- `covered_sweeps`
  - 当前 route 已覆盖到的 sweep 集
- `repeat_count`
  - 重复进入已覆盖 sweep 的次数
- `connector_depth`
  - 已覆盖 connector 的连续深度
- `connector_cost`
  - 已覆盖 connector 的累计代价
- `transition_cost`
  - route 级累计 transition 代价

这说明当前 cadence 求解维护的不是“一串 sweep id”，而是：

1. 当前在什么 sweep
2. 当前从哪一端出去
3. 已经形成了哪些段关系
4. 已覆盖 connector 已经走了多深、多贵

## 8. 顶层真实主流程

```python
def build_sweep_cadence(sweeps, sweep_transition_candidate_info, nodes, config=None):
    """
    输入:
        sweeps / sweep_transition_candidate_info / nodes:
            cadence 直接消费的正式输入真值。
        config:
            cadence solver 配置。
            当前主要读取:
                - covered_connector_max_depth
                - covered_connector_max_cost
                - u_turn_risk_limit

    输出:
        sweep_cadence_info:
            包含 routes / route_sweep_order / summary。
    """

    context = _build_cadence_context(sweeps, sweep_transition_candidate_info, nodes)
    solver_config = dict(config or {})

    # 第一阶段:
    # 直接在 kept transition candidates 上生成 greedy routes。
    routes = _build_sweep_cadence_routes_greedy(
        context,
        solver_config=solver_config,
    )

    # 第二阶段:
    # 对 greedy 结果做收尾优化，不发明新图，只在既有 transition 上修顺。
    routes = _optimize_greedy_routes(
        routes,
        context,
        solver_config=solver_config,
    )

    # 第三阶段:
    # 把 route 展平成 route_sweep_order，便于统计和索引。
    order_items = []
    for route_id, route in enumerate(routes, start=1):
        route["route_id"] = int(route_id)
        for order_in_route, sweep_id in enumerate(route["sweep_sequence"], start=1):
            order_items.append({
                "sweep_id": int(sweep_id),
                "route_id": int(route_id),
                "order_in_route": int(order_in_route),
            })

    return {
        "routes": tuple(routes),
        "route_sweep_order": tuple(order_items),
        "summary": {
            "solver": "greedy",
            "cadence_count": int(len(routes)),
            "covered_sweep_count": int(len({int(item['sweep_id']) for item in order_items})),
        },
    }
```

## 9. route 是如何生成的

当前 `_build_sweep_cadence_routes_greedy(...)` 的真实流程是：

1. 从全部未覆盖 sweep 集开始
2. 选一个起始状态
3. 初始化 `_GreedyRouteState`
4. 循环做：
   - 构造合法 action
   - 按优先级选最优 action
   - 应用 action 得到新 state
5. 若没有合法 action，则当前 route 结束
6. 把 state 转成 route
7. 重复直到 sweep 全覆盖

### 9.1 route 生成详细伪代码

```python
def _build_sweep_cadence_routes_greedy(context, solver_config):
    """
    输入:
        context:
            cadence 上下文, 含 sweeps / transitions / outgoing 等索引。
        solver_config:
            greedy 求解参数。

    输出:
        routes:
            尚未 route_id 重排前的 route 列表。
    """

    uncovered = {int(item["sweep_id"]) for item in context.sweeps}
    routes = []

    while uncovered:
        # 先选新的 route 起点。
        start_sweep_id, start_end_type, available_exit_end = _choose_cadence_start_state(
            uncovered_sweep_ids=uncovered,
            sweep_by_id=context.sweep_by_id,
            outgoing_transitions=context.outgoing,
        )

        state = _GreedyRouteState(
            start_sweep_id=int(start_sweep_id),
            start_end_type=str(start_end_type),
            current_sweep_id=int(start_sweep_id),
            current_exit_end=str(available_exit_end),
            previous_turn_type="start",
            sweep_sequence=[int(start_sweep_id)],
            transition_sequence=[],
            segments=[],
            covered_sweeps={int(start_sweep_id)},
            repeat_count=0,
            connector_depth=0,
            connector_cost=0.0,
            transition_cost=0.0,
        )
        uncovered.remove(int(start_sweep_id))

        # 这里的 visited_local_states 只是收敛保护。
        # 它不参与业务规则排序, 也不参与候选合法性解释。
        visited_local_states = {
            (
                int(state.current_sweep_id),
                str(state.current_exit_end),
                frozenset(int(item) for item in state.covered_sweeps),
            )
        }

        while True:
            next_state = _expand_greedy_state(
                context=context,
                state=state,
                allowed_targets=uncovered,
                solver_config=solver_config,
            )
            if next_state is None:
                break

            next_local_state = (
                int(next_state.current_sweep_id),
                str(next_state.current_exit_end),
                frozenset(int(item) for item in next_state.covered_sweeps),
            )
            if next_local_state in visited_local_states:
                break

            state = next_state
            uncovered -= state.covered_sweeps
            visited_local_states.add(next_local_state)

        routes.append(_route_from_state(state, route_id=int(len(routes) + 1)))

    return routes
```

## 10. 起点是怎么选的

当前 `_choose_cadence_start_state(...)` 会遍历：

- 每个未覆盖 sweep
- 每个可能的进入端 / 可用退出端组合

然后按 `_greedy_start_state_priority_key(...)` 选最佳起点。

虽然这个优先级函数文档里不再逐项展开所有细节，但当前排序思想仍是：

1. 当前可接到更多未覆盖后继的 sweep 优先
2. 更靠中心、结构更稳定的 sweep 优先
3. 更长、更主干的 sweep 优先

也就是说，起点不是随机选，而是带结构偏好的。

## 11. action 是怎么构造的

当前 `_build_greedy_legal_actions(...)` 是 cadence 规则的核心之一。

### 11.1 先取当前出口端的 direct transitions

当前会从：

- `context.outgoing[(current_sweep_id, current_exit_end)]`

取出所有 direct transitions。

### 11.2 未覆盖优先

若 direct transitions 中存在指向未覆盖 sweep 的项，则：

- 只保留这些未覆盖候选

否则：

- 才允许考虑已覆盖目标 sweep

### 11.3 已覆盖 connector 的限制

若某个候选目标 sweep 已覆盖，则当前实现会显式计算：

- `connector_depth`
- `connector_cost`

并检查：

- 不超过 `covered_connector_max_depth`
- 不超过 `covered_connector_max_cost`
- 继续往前在有限深度和有限代价内，确实还能接到新的未覆盖 sweep

这一点对应当前实现里的：

- `_can_revisit_transition_reach_uncovered(...)`

### 11.4 forward through 语义硬过滤

每个 action 在加入合法集合前，还必须通过：

- `_action_preserves_forward_through_semantics(...)`

也就是说，当前 cadence 不是先瞎扩展、后面再修，而是先做 through 硬过滤。

### 11.5 `u_turn` 候选的进入条件

这里要先明确：`dead_end_return` 属于正式 transition action，不属于 fallback `u_turn`。

只有在普通 actions 为空时，当前实现才会进一步考虑：

- `u_turn`

并且 `u_turn` 还必须满足：

1. 当前 sweep 是 dead-end-like
2. 另一端确实有后继可走
3. 当前 sweep 角色不能太边缘
4. `u_turn` 发生在支持的节点区语义内
5. 风险代理值不过高
6. 通过这个 `u_turn`，后续确实还能在限定预算内接到未覆盖 sweep

## 12. action 构造详细伪代码

```python
def _build_greedy_legal_actions(context, state, allowed_targets, solver_config):
    """
    输入:
        context:
            cadence 上下文。
        state:
            当前 greedy route state。
        allowed_targets:
            当前仍未覆盖的 sweep 集。
        solver_config:
            covered connector / u_turn 限制参数。

    输出:
        actions:
            当前步允许进入优先级比较的候选动作列表。
    """

    actions = []
    current_sweep_id = int(state.current_sweep_id)
    current_exit_end = str(state.current_exit_end)

    # 先取从当前 sweep 当前出口端直接可出的 transitions。
    direct_transitions = [
        item
        for item in context.outgoing.get((current_sweep_id, current_exit_end), ())
    ]

    # 未覆盖优先:
    # 如果当前就有未覆盖后继, 不优先走已覆盖 connector。
    uncovered_transitions = [
        item for item in direct_transitions
        if int(item["to_sweep_id"]) in allowed_targets
    ]
    candidate_transitions = uncovered_transitions if uncovered_transitions else direct_transitions

    for transition in candidate_transitions:
        target_sweep_id = int(transition["to_sweep_id"])
        target_entry_end = str(transition["to_end_type"])
        target_exit_end = _opposite_end_type(target_entry_end)
        is_repeat_coverage_transition = bool(target_sweep_id not in allowed_targets)

        connector_depth = 0
        connector_cost = 0.0
        if is_repeat_coverage_transition:
            connector_step_cost = _covered_connector_step_cost(
                transition=transition,
                sweep_by_id=context.sweep_by_id,
                previous_turn_type=str(state.previous_turn_type),
            )
            connector_depth = int(state.connector_depth) + 1
            connector_cost = float(state.connector_cost) + float(connector_step_cost)

            if connector_depth > _greedy_covered_connector_max_depth(solver_config):
                continue
            if connector_cost > _greedy_covered_connector_max_cost(solver_config):
                continue
            if not _can_revisit_transition_reach_uncovered(
                context=context,
                sweep_id=target_sweep_id,
                exit_end_type=target_exit_end,
                allowed_targets=allowed_targets,
                depth=_greedy_covered_connector_max_depth(solver_config) - connector_depth,
                cost_budget=_greedy_covered_connector_max_cost(solver_config) - connector_cost,
                previous_turn_type=str(transition.get("turn_type", state.previous_turn_type)),
                visited_states={(target_sweep_id, target_exit_end)},
            ):
                continue

        action = {
            "primitive_type": "transition",
            "transition": transition,
            "next_sweep_id": int(target_sweep_id),
            "next_exit_end": str(target_exit_end),
            "transition_id": int(transition["transition_id"]),
            "turn_type": str(transition.get("turn_type", "straight")),
            "candidate_level": str(transition.get("candidate_level", "weak_keep")),
            "is_repeat_coverage_transition": is_repeat_coverage_transition,
            "connector_depth": int(connector_depth),
            "connector_cost": float(connector_cost),
            "u_turn_penalty": 0.0,
        }

        # 前向 through 语义硬过滤。
        if not _action_preserves_forward_through_semantics(
            context=context,
            state=state,
            action=action,
        ):
            continue

        actions.append(action)

    # 如果已有普通动作, 当前就不再引入 u_turn。
    if actions:
        return actions

    alternate_exit_end = _opposite_end_type(current_exit_end)
    if not _has_transition_from_end(
        context=context,
        sweep_id=current_sweep_id,
        exit_end_type=alternate_exit_end,
    ):
        return actions

    # 只有正常动作都不可得时, 才尝试受控 u_turn。
    if _allow_controlled_u_turn(
        context=context,
        state=state,
        sweep_id=current_sweep_id,
        current_exit_end=current_exit_end,
        previous_turn_type=str(state.previous_turn_type),
        allowed_targets=allowed_targets,
        solver_config=solver_config,
    ):
        action = {
            "primitive_type": "u_turn",
            "next_sweep_id": int(current_sweep_id),
            "next_exit_end": str(alternate_exit_end),
            "transition_id": -1,
            "turn_type": "u_turn",
            "candidate_level": "u_turn",
            "is_repeat_coverage_transition": False,
            "u_turn_penalty": 1.0,
        }
        if _action_preserves_forward_through_semantics(
            context=context,
            state=state,
            action=action,
        ):
            actions.append(action)

    return actions
```

## 13. action 是怎么排优先级的

当前 `_greedy_action_priority_key(...)` 是 cadence 的第二个核心。

### 13.1 普通 transition 的优先级来源

当前至少考虑：

1. `candidate_level`
   - `strong_keep` 优先于其它
2. `turn_type`
   - `straight` 优先
   - 连续同侧转向优先
   - `u_turn` 最后
3. 是否是 repeat coverage transition
4. `connector_depth`
5. `connector_cost`
6. 是否留在当前 coverage lane
7. 目标 sweep 的角色优先级
8. 短前瞻增益
9. 风险
10. 端点距离

这里的排序口径是：

- 同 group 横移 transition 可以把 `rank_gap` 作为局部横移代价的一部分。
- 跨 group transition 使用候选阶段传下来的 sweep 级端点转角、端点距离、局部可行性、`motion_type`、`connection_kind` 和 coverage 收益。
- 跨 group transition 的左右对应关系由 sweep 端点几何和局部连接空间解释。
- 当前没有建立跨 group rank frame 对齐，因此跨 group transition 不能用 `rank_gap` 主导排序、过滤或收益判断。
- `sweep_role_priority_value(next_sweep)` 包含 `side_level / mean_offset_m`，只描述目标 sweep 在自身 group 内的覆盖角色。
- 对跨 group transition，`sweep_role_priority_value(next_sweep)` 不允许参与 pair 排序、后置 tie-break 或 repeat connector 主成本。
- 对同 group 横移 transition，`rank_gap / side_level / mean_offset_m` 处在同一 group frame 内，可以作为重要排序依据，但仍不能替代端点距离和局部可行性。

### 13.2 `u_turn` 的优先级

当前 `u_turn` 在优先级键上会天然更靠后，因为：

- `primitive_type == "u_turn"` 时主优先级项更差

这与前面的“只有普通动作为空才考虑 `u_turn`”共同形成双重限制。

## 14. action 应用后如何形成 route 真值

当前 `_apply_greedy_action(...)` 会直接把动作写回：

- `sweep_sequence`
- `transition_sequence`
- `segments`
- `ordered_passes`
- `covered_sweeps`

这意味着：

- cadence route 不是最后再推导 segment
- 而是在 greedy 扩展时就把 `segments` 真值同步记下来了

### 14.1 普通 transition 动作写入的 segment

普通 transition 当前会写入：

- `from_sweep_id = state.current_sweep_id`
- `to_sweep_id = next_sweep_id`
- `via_node_id = transition["via_node_id"]`
- `requires_junction_connection = True`
- `entry_end_type = state.current_exit_end`
- `exit_end_type = next_exit_end`
- `primitive_type = "transition"`
- `connection_kind = transition["connection_kind"]`
- `transition_id = transition["transition_id"]`

### 14.2 `u_turn` 动作写入的 segment

`u_turn` 当前会写入：

- `from_sweep_id = current_sweep_id`
- `to_sweep_id = current_sweep_id`
- `via_node_id = -1`
- `requires_junction_connection = False`
- `entry_end_type = state.current_exit_end`
- `exit_end_type = next_exit_end`
- `primitive_type = "u_turn"`
- `transition_id = -1`

也就是说：

- `u_turn` 不是通过 transition 真值来表达
- 而是 cadence 自己生成一个 `primitive_type = "u_turn"` 的 segment

## 15. `repeat_sweep` 在当前源码中的语义

当前 `repeat_sweep` 不是独立动作原语，而是统计语义。

正式含义是：

- 当前动作进入的目标 sweep 已经在 `allowed_targets` 之外

它的当前实现落点是：

- `is_repeat_coverage_transition`
- `repeat_count`

它不表示：

- 在同一 sweep 上原地再走一遍
- 也不等于 `u_turn`

## 16. optimize 后处理链

当前 `_optimize_greedy_routes(...)` 的真实顺序是：

1. `_merge_cadence_routes(...)`
2. `_merge_cadence_routes(...)`
3. `_apply_local_legality_correction(...)`
4. `_apply_abnormal_sweep_integration(...)`

### 16.1 `_merge_cadence_routes(...)`

职责：

- 只消费已有 transitions
- 尝试把两条 route 通过合法 transition 桥接起来
- 压缩碎片 route

硬边界：

- 不发明新 transition
- 不改变单条 route 内已有 sweep 顺序

### 16.2 `_apply_local_legality_correction(...)`

职责：

- 压缩连续重复 `u_turn`
- 若发现 through 语义破坏，则按第一处坏点拆 route

### 16.3 `_apply_abnormal_sweep_integration(...)`

职责：

- 先识别异常 sweep
- 再尝试做：
  - singleton route 之间插入
  - singleton route 挂到 route 两端
  - singleton route 插到 route 中间槽位
  - one-side route endpoint 修复

## 17. 异常 sweep 的当前正式分类

当前 `_classify_abnormal_sweeps(...)` 会把问题 sweep 分成：

- `singleton_sweep_ids`
  - 只有一条 sweep、且没形成正常 route 链的情况
- `none_connected_sweep_ids`
  - 入出都没有在 route 使用计数里成立
- `one_side_connected_sweep_ids`
  - 只有一侧被 route 使用，另一侧未闭环
  - 仅对非 dead-end-like sweep 计入异常

## 18. cadence 校验链

当前 `validate_sweep_transition_candidates(...)` / cadence 校验链至少检查：

1. `sweep_transition_candidate_info.items` 是否覆盖 cadence 使用到的 transition
2. `route_sweep_ids` 是否覆盖全部 sweep
3. `segments` 连续性是否正确
4. `entry_end_type / exit_end_type` 连续性是否正确

也就是说，文档若只写：

- “cadence 给出了一串 sweep 顺序”

是不够的，因为真实 contract 还包含：

- `segments`
- end type 连续性

## 19. 审图和排查时应重点看什么

### 19.1 route 结构

- `sweep_sequence`
- `transition_sequence`
- `segments`

### 19.2 端类型链

- `start_end_type`
- `end_end_type`
- 每个 segment 的：
  - `entry_end_type`
  - `exit_end_type`

### 19.3 特殊动作

- `is_repeat_coverage_transition`
- `primitive_type == "u_turn"`

### 19.4 异常 route

- singleton
- none_connected
- one_side_connected

### 19.5 后续接 pure cycle cut / dead_end 时要守住的语义

- same-edge transition 后续不能一律视为非法。
- cadence 必须区分 `cycle_through` 与 `dead_end_return`。
- `dead_end_return` 必须作为正式 transition action 进入 cadence，而不是退化成 fallback `u_turn`。
- 只有在没有合适正式 transition action 时，才允许进入受控 `u_turn` / 掉头策略。
- `cycle_through` 仍然是 through 语义。

## 20. 总结

当前 SweepCadence 的真实 contract 不是抽象的：

- 单纯的顺序壳对象

而是：

- `sweep_sequence`
- `transition_sequence`
- `segments`
- `route_sweep_order`
- `ordered_passes`
- `start_end_type`
- `end_end_type`

当前求解也不是抽象的“顺序规划”，而是：

- 在 `sweep_transition_candidate_info.items` 上做 greedy 扩展
- 前向执行 through 语义硬过滤
- 显式区分 `cycle_through / dead_end_return / u_turn`
- 对已覆盖 connector 和 `u_turn` 做受控限制
- 最后再做 route merge / legality correction / abnormal sweep integration

后续文档若继续细化，也必须以这套真实结构和真实函数链为准。
