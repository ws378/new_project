# `sweep_transition_candidate` 生成规则

本章只讨论一件事：

- 上游已经生成正式 sweeps 之后，如何生成正式的 `sweep_transition_candidate`

本章不再沿用历史上混杂的主语义命名，不再把：

- `transition`
- `lateral_transition`
- `dead_end_return`
- `cycle_through`
- `foldback`

并列当作 `sweep_transition_candidate` 的最终主语义。

本章统一采用最新口径：

- `sweep_transition_candidate` 只保留两类主语义：`forward` 与 `foldback`
- `node_projected` 与 `group_internal` 只表示候选来源，不表示主语义
- 过去的 through / turn / lateral / dead-end return / cycle-through 等概念，只作为形成方式、来源说明或调试标签，不再作为主语义层直接并列存在

## 1. 本阶段职责

`sweep_transition_candidate` 阶段的职责是：

- 基于已经生成完成的正式 sweeps
- 展开 sweep 级的正式连接候选
- 供后续 cadence 在这张正式候选图上做节拍选择

这一阶段负责回答的是：

- 哪些 sweep 之间允许正式连接
- 每条连接的主语义是 `forward` 还是 `foldback`
- 每条连接来自哪里
- 每条连接的几何与风险属性是什么

这一阶段不负责：

- 重新生成 sweeps
- 直接输出最终 cadence
- 直接输出最终 coverage path
- 在 cadence 阶段临时发明新的正式边

因此，本阶段输出必须是一张正式的 sweep 级候选图，而不是若干局部补丁。

## 2. 为什么必须有这一层

如果没有 `sweep_transition_candidate` 这一层，后续 cadence 就会被迫一边选节拍，一边猜测连接是否合法。

这样会带来几个直接问题：

- node / edge / group 的正式连接真值无法稳定传递到 sweep 级
- dead-end、纯回环、单通道等场景中，cadence 可能根本没有足够的正式边可选
- cadence 容易退化成只会拼单 sweep，或者频繁依赖临时兜底策略
- 连接合法性和节拍选择逻辑会混在一起，无法长期稳定收敛

因此，本阶段必须显式生成正式候选连接图，后续 cadence 只在这张图上做选择，而不是再造新边。

## 3. 输入口径

`sweep_transition_candidate` 生成至少要消费下面几类输入事实。

### 3.1 正式 sweeps

这是本阶段最基础的输入。

每条 sweep 至少要能提供：

- `sweep_id`
- `edge_id`
- `group_id`
- `src / dst` 端信息
- `path_rc` 等几何信息
- 在组内的顺序、rank 或 role 信息

### 3.2 sweep group 与 port 视图

本阶段还必须知道：

- 哪些 sweep 属于同一个 group
- 哪些 sweep 对应同一条 edge
- 在某个端口一侧，sweeps 的顺序是什么
- 哪些 sweep 位于同一 `src` 侧，哪些位于同一 `dst` 侧

这部分信息决定组内候选如何展开。

### 3.3 上游正式连接事实

本阶段不能脱离更上游 topology / edge 级正式连接结果单独乱猜。

也就是说，edge / node 层已经落定的正式连接事实，必须能够继续投影到 sweep 级。

这里要特别强调：

- 上游连接结果提供的是更粗粒度的正式连接约束
- 本阶段是在这个基础上，把连接关系翻译成 sweep 级候选
- 本阶段不应重新发明与上游冲突的主语义体系

### 3.4 必要的几何与风险属性

本阶段还需要几何和风险相关属性，用于判断候选是否合理、以及供后续排序使用。

至少包括：

- sweep 端点距离
- sweep 端点方向夹角
- `rank_gap`
- 是否同侧
- 是否同 sweep
- 是否同 edge
- 风险分数
- 是否明显穿障
- 是否跳出本组责任区

这些字段用于描述和评分，不用于定义主语义。

这里的正式口径是：

- 跨 group 候选使用 sweep 级端点几何作为几何接近和左右对应依据。
- `rank_gap` 只在同 group 内天然有比较意义。
- 跨 group 的弱排序特征来自显式建立的统一左右参考系。
- 当前没有建立跨 group rank frame 对齐，因此跨 group 的 `rank_gap` 不能参与主排序、主过滤或主收益判断。
- `mean_offset_m / side_level / sweep_role_priority` 描述的是 sweep 在自己 group / coverage lane 内的角色，不描述跨 group pair 的连接质量。

## 4. 输出口径

本阶段最终输出的是一组正式的 `sweep_transition_candidate`。

每条 candidate 至少要明确下面几类事实：

- 它连接了哪两个 sweep
- 它发生在哪些端点之间
- 它的主语义是什么
- 它从哪里来
- 它的辅助几何与风险属性是什么

建议最小输出字段至少包含：

- `candidate_id`
- `from_sweep_id`
- `to_sweep_id`
- `from_end_type`
- `to_end_type`
- `connection_kind`
- `candidate_source`
- `same_sweep`
- `same_edge`
- `rank_gap`
- `endpoint_distance_px`
- `risk_score`
- `confidence_score`

如果还需要保留历史形成方式或调试标签，可以另外挂：

- `debug_reason_tags`
- `source_trace_label`
- `trace_tags`

但这些都不应替代 `connection_kind` 成为新的主语义字段。

## 5. 主语义统一规则

### 5.1 只保留两类主语义

`sweep_transition_candidate` 只保留两类主语义：

- `forward`
- `foldback`

不再长期保留下面这些并列主语义：

- `transition`
- `lateral_transition`
- `dead_end_return`
- `cycle_through`
- `foldback`

这些概念如果仍然有价值，只能退回到：

- 形成方式说明
- 来源说明
- 调试标签
- 向后兼容字段

不能继续作为主语义层直接并列存在。

### 5.2 `forward` 的定义

`forward` 的定义是：

- 从当前经过状态出发
- 最终进入了下一个 sweep

这里强调的是“结果语义”，不是“形成方式语义”。

因此，只要最终节拍意义上进入了下一个 sweep，就统一归为：

- `forward`

它可以来自：

- 普通 node 经过
- 组内横向切换
- edge 内部特殊组织后再接到下一条 sweep
- 回环切口场景下的继续前进

### 5.3 `foldback` 的定义

`foldback` 的定义是：

- 没有继续进入新的 sweep
- 而是在当前 sweep 或当前 edge 上发生回折

这里不用 `foldback`，而用 `foldback`，是因为本阶段要表达的回折语义比标准车辆掉头更宽。

`foldback` 可以包括：

- 直接掉头式回折
- 反向折返
- 后退式回折
- same-sweep 上从一端回到另一端的回折

因此，过去所谓：

- `dead_end_return`
- `foldback`
- 某些 same-edge 特例回折

在主语义层都应统一并入：

- `foldback`

## 6. 来源与主语义必须拆开

### 6.1 候选来源不是主语义

按最新口径，`node_projected` 与 `group_internal` 只表示候选来源。

它们回答的是：

- 这条 candidate 是从 node / edge 正式连接结果投影来的
- 还是从同一 group 内部正式展开出来的

它们不回答：

- 这条 candidate 的主语义是不是前进或回折

因此，来源和主语义必须分层：

- `candidate_source`：来源
- `connection_kind`：主语义

不能再把“来源名字”和“语义名字”混写在同一层。

### 6.2 `node_projected`

`node_projected` 表示：

- 候选来自更上游 edge / node 级正式连接结果的投影

它表达的是：

- 某个 edge 经过 node 后，如何影响到 sweep 之间的正式连接

`node_projected` 产生的 candidate，最终仍然只落两类主语义：

- `forward`
- `foldback`

它不应再天然绑定为：

- `transition`
- `dead_end_return`
- `cycle_through`

这些只是历史命名，不是最新口径下的主语义。

### 6.3 `group_internal`

`group_internal` 表示：

- 候选是在同一个 sweep group 内部，依据端口关系、组内顺序和几何约束正式展开出来的

它表达的是：

- 同组 sweeps 内部，哪些连接可以正式存在

`group_internal` 产生的 candidate 也可能落成两类主语义：

- `forward`
- `foldback`

这一步必须特别明确：

`group_internal` 不能再被机械理解成“只生成 lateral”。

它既可以生成：

- `i.dst -> j.dst`
- `i.src -> j.src`

也可以生成：

- `i.dst -> i.src`
- `i.src -> i.dst`

前一类通常表现为：

- 跨 sweep 的 `forward`

后一类通常表现为：

- same-sweep 的 `foldback`

所以，`group_internal` 的本质是“组内正式连接展开来源”，不是“横向连接”的同义词。

## 7. edge 层与 sweep 层的统一理解

### 7.1 edge 层主语义

edge 层也应统一到：

- `forward`
- `foldback`

对应含义是：

- `edge-forward`
  - 通过节点继续前进
- `edge-foldback`
  - 在当前 edge 上回折

这里原来曾经单列的 `cycle_through` 不再保留。

对于 pure cycle cut 这类场景：

- 如果经过切口后，在 edge 语义上是继续前进
- 那它就是 `edge-forward`

不需要再单独创造一个 `cycle_through` 主语义。

### 7.2 sweep 层主语义

sweep 层也统一到：

- `forward`
- `foldback`

对应含义是：

- `sweep-forward`
  - 进入下一个 sweep
- `sweep-foldback`
  - 在当前 sweep 回折，不进入新的 sweep

### 7.3 edge 与 sweep 不是机械一一对应

edge 层与 sweep 层虽然共享 `forward / foldback` 两个主语义，但判定口径不同。

- edge 层看的是：当前 edge 经过节点后，是继续前进还是回折
- sweep 层看的是：最终有没有进入下一个 sweep

因此，并不是所有 `sweep-forward` 都只能来自 `edge-forward`。

还存在一种重要情况：

- 某个 edge 内部先发生局部 `foldback`
- 但最终组织结果把节拍送到了另一条 sweep
- 从 sweep 结果上看，它仍然是 `forward`

所以：

- `sweep-forward` 可以来自 `edge-forward`
- 也可以来自 edge 内部的 `foldback` 组织结果

这一点必须在规则里显式承认，不能机械套 edge->sweep 的一一映射。

## 8. 允许的候选连接形式

本阶段应先按几何结果和节拍结果来理解 candidate，而不是先按历史命名分类。

### 8.1 跨 sweep 的连接

典型形式例如：

- `i.dst -> j.dst`
- `i.src -> j.src`
- `i.dst -> j.src`
- `i.src -> j.dst`

只要结果上进入了新的 sweep，就归为：

- `forward`

至于它来自 `node_projected` 还是 `group_internal`，属于来源问题，不属于主语义问题。

### 8.2 same-sweep 上的回折

典型形式例如：

- `i.dst -> i.src`
- `i.src -> i.dst`

如果结果上没有进入新的 sweep，而是在当前 sweep 内部回折，那就归为：

- `foldback`

这正是历史上 dead-end return、fallback 回头以及其他 same-sweep 回折，应统一吸收进去的位置。

### 8.3 回环场景下的继续前进

对于 pure cycle cut 这类场景，如果 edge 级语义上是继续前进，且 sweep 级结果也进入了后续 sweep，那么它仍然只归为：

- `forward`

这里不再保留独立的 `cycle_through` 主语义。

### 8.4 edge 内部回折但 sweep 级未前进

如果 edge 内部回折后，最终 sweep 级没有进入新的 sweep，而只是留在当前 sweep 上反向回折，则统一归为：

- `foldback`

## 9. `rank_gap` 的定位

`rank_gap` 不是主语义字段，而是几何 / 结构属性字段。

它只回答：

- 这条 candidate 在同一 group 的同一 port view 内跨了多少层 rank

它不回答：

- 两个不同 group 的 sweep 是否在真实空间上左右对应
- 两个不同 group 的 sweep 是否应该优先连接
- 两个不同 group 的 sweep 是否处在同一个可比较 rank 坐标系

### 9.1 `rank_gap` 上限应由参数控制

本阶段不应把同 group 候选生成范围写死成只看最近邻。

更合理的正式口径是：

- 对同 group 横移生成 `rank_gap <= max_rank_gap` 的候选
- 其中 `max_rank_gap` 由参数传入

这意味着：

- `rank_gap = 1` 只是更保守的特例
- 不是同 group 横移的唯一生成口径

跨 group 候选不使用这一条作为主生成规则。

### 9.2 默认值设为 `2`

同 group 横移的 `rank_gap` 默认上限不应写成 `1`，而应写成：

- `max_rank_gap = 2`

这样做的含义是：

- 保留最近邻连接
- 同时允许跨一层 rank 的连接进入正式候选集

这样更符合实际同组 sweep 连接的几何需要，也更符合“同 group 横移邻域由参数控制”的长期方向。

### 9.3 为什么不能把 `rank_gap = 1` 写成唯一口径

`rank_gap = 1` 不是长期唯一真理。

在一些同 group 场景里，只允许最近邻反而会带来局限，例如：

- 机器人真实转弯半径较大
- 最近邻横切过于局促
- 跨一层 rank 的连接反而更自然

因此，正确的长期表述不是：

- 固定只允许 `rank_gap = 1`

而是：

- 同 group `rank_gap` 上限由参数控制
- 默认值设为 `2`
- 必要时可以根据场景继续调大或调小

### 9.4 `rank_gap` 的长期作用

无论参数最终取值是多少，`rank_gap` 都应只作为：

- 同 group 候选生成范围约束
- 风险与代价因子
- 近邻连接与远跳连接的区分属性

不能把它升级成新的主语义。

### 9.4.1 group 内 rank / offset 的使用边界

同 group 内的 `rank_gap / side_level / mean_offset_m` 有统一参考系。

成立前提是：

- sweeps 来自同一个 `coverage_lane` 或同一个 `SweepGroup`。
- sweeps 共享同一条中心参考线和同一套横向偏移生成规则。
- `ordered_sweep_ids` 与 `port_rank_by_sweep_id` 描述的是同一个 group 内部的横向顺序。

因此，group 内可以使用：

- `rank_gap` 作为横移候选生成范围约束。
- `rank_gap` 作为 group 内横移风险与代价因子。
- `side_level / mean_offset_m` 作为 sweep 角色优先级或起点选择的辅助依据。

但 group 内也必须保留几何校验：

- `rank_gap` 不能替代端点距离。
- `mean_offset_m` 不能单独决定 transition pair。
- `side_level` 描述覆盖角色，不直接等价于连接质量。
- group 内横移仍应结合 `endpoint_distance`、端点方向和局部可行性。

### 9.5 跨 group 候选由 sweep 端点几何主导

跨 group 的正式候选由 sweep 级端点几何主导：

- `A / B` 来自 from sweep 的真实退出端及相邻点。
- `C / D` 来自 to sweep 的真实进入端及相邻点。
- `endpoint_distance = distance(B, C)`。
- `sweep_turn_delta = angle(B - A, D - C)`。

其中：

- `endpoint_distance` 用于判断两个端点是否足够接近。
- `sweep_turn_delta` 用于判断这条具体 sweep pair 是否符合 `motion_type` 的期望。
- `motion_type` 可以继续来自 topology 层的 edge / port 级转角，但必须被 sweep 级端点角度校验。
- 欧式距离不能单独作为最终依据，还需要结合局部可行域、障碍、路径代价和 cadence 目标。
- 跨 group 的左右对应关系来自 sweep 端点几何和局部连接空间。
- 当前没有建立跨 group rank frame 对齐，`rank_gap` 只能作为调试解释字段，不能主导跨 group candidate 生成、排序或过滤。
- `mean_offset_m / side_level / sweep_role_priority` 不能用于推断跨 group 的左 / 中 / 右对应关系。

### 9.6 跨 group 候选输出多候选集合

跨 group 的 `choose_lane_pairs(...)` 负责挑选候选连接，输出是候选集合。

正式口径是：

1. 先用 topology hypothesis 判定两个 group 在当前 `via_node_id` 是否允许连接。
2. 再对 `from_group sweeps x to_group sweeps` 做受控展开。
3. 对每个 pair 计算 sweep 级端点距离和端点方向夹角。
4. 用几何 gate、局部可行域和 top-k 控制候选数量。
5. 同一个 `from_sweep_id` 可以保留多个 `to_sweep_id` 候选。
6. 同一个 `to_sweep_id` 也可以被多个 `from_sweep_id` 候选指向。

候选阶段的职责是扩大有效选择空间，最终选择交给 cadence 层结合全局覆盖目标完成。

## 10. 历史概念的统一吸收规则

本章明确规定，历史概念必须统一吸收，不再直接并列挂在主语义层。

### 10.1 through / turn

过去普通 node through / turn 对应的 sweep candidate，如果结果上进入了下一个 sweep，则统一归为：

- `forward`

### 10.2 lateral

过去所谓 lateral，如果结果上进入了其他 sweep，也统一归为：

- `forward`

因此 `lateral_transition` 不再保留为主语义。

### 10.3 dead-end return

过去所谓 dead-end return，本质上是某种 same-sweep 回折。

因此应统一归为：

- `foldback`

### 10.4 fallback u-turn

过去所谓 fallback u-turn，也不再保留为主语义。

如果它在当前 sweep / edge 上表现为回折，则统一归为：

- `foldback`

如果仍需区分它和结构性更强的回折来源，应通过：

- `candidate_source`
- `confidence_score`
- `debug_reason_tags`
- 其他来源/置信度字段

来区分，而不是再创造新的主语义。

### 10.5 cycle-through

过去所谓 cycle-through，不再作为独立主语义保留。

- 如果它结果上继续进入新的 sweep，则统一归为 `forward`
- 如果它表现为回折，则统一归为 `foldback`

## 11. 生成规则总纲

按最新口径，`sweep_transition_candidate` 生成应遵守下面这条总纲。

### 11.1 第一步：先收来源事实

先收集：

- 来自 `node_projected` 的正式候选来源
- 来自 `group_internal` 的正式候选来源

### 11.2 第二步：再判 sweep 级结果语义

对每条候选，不先按历史命名分类，而是直接判：

- 最终有没有进入新的 sweep

如果进入新的 sweep，则：

- `connection_kind = forward`

如果没有进入新的 sweep，而是在当前 sweep / edge 上回折，则：

- `connection_kind = foldback`

### 11.3 第三步：补辅助属性

对每条 candidate，再补：

- `same_sweep`
- `same_edge`
- `rank_gap`
- `endpoint_distance_px`
- `sweep_turn_delta_deg`
- `local_feasibility_score`
- `risk_score`
- `confidence_score`
- `candidate_source`

### 11.4 第四步：输出正式候选图

最终输出统一的 `sweep_transition_candidate_info`，供后续 cadence 使用。

后续 cadence 只应在这张正式候选图上做选择，不应再发明新的正式边。

## 12. 给后续 cadence 的直接约束

如果本章规则成立，后续 cadence 的直接使用口径应当是：

- 先读正式的 `sweep_transition_candidate`
- 主语义只识别：`forward / foldback`
- 再结合来源、风险、sweep 端点距离、sweep 级转角、局部可行性等属性做排序与选择
- 对同 group 横移，可以使用同一 port view 内的 `rank_gap`
- 对跨 group transition，主排序依据是 sweep 端点距离、sweep 级转角和局部可行性
- 对跨 group transition，`sweep_role_priority / mean_offset_m / side_level` 不允许参与主排序、后置 tie-break 或 connector 主成本，只能作为调试解释字段保留

也就是说，cadence 不应再面对一组彼此交叉、彼此重叠的历史主语义名词，而应面对一组已经统一收口的正式候选。

这意味着：

- `forward` 是继续推进覆盖的主要正式动作
- `foldback` 是必要时允许的正式回折动作
- 具体优先级应由来源可信度、风险、sweep 端点距离、sweep 级转角、局部可行性等因素继续细化
- 当前未建立跨 group rank frame 对齐，`rank_gap` 只允许在同 group 横移中作为强约束 / 强代价；跨 group 只保留为解释字段
- `mean_offset_m / side_level` 只描述 group 内角色，不能主导跨 group pair 选择

## 13. 本章最终结论

本章最终只落下面几条硬结论。

1. `sweep_transition_candidate` 阶段负责生成正式的 sweep 级候选连接图，而不是最终 cadence。
2. `node_projected` 与 `group_internal` 只表示候选来源，不表示主语义。
3. `sweep_transition_candidate` 的主语义只保留两类：`forward` 与 `foldback`。
4. through / turn / lateral / dead-end return / cycle-through / fallback u-turn 等历史概念，全部退回到形成方式、来源说明或调试标签层，不再作为主语义并列存在。
5. edge 层与 sweep 层都共享 `forward / foldback` 两类主语义，但判定口径不同。
6. `sweep-forward` 可以来自 `edge-forward`，也可以来自 edge 内部 `foldback` 的组织结果。
7. `rank_gap` 只是同 group 结构属性，不是主语义；同 group 横移候选生成应受参数控制，默认 `max_rank_gap = 2`，而不是把 `rank_gap = 1` 写成长期唯一口径。
8. 跨 group 候选必须用 sweep 级端点距离、端点转角和局部可行性主导候选生成与排序，并保留可供 cadence 选择的多候选集合。
9. 后续 cadence 只能在这张正式候选图上做选择，不应再发明新的正式边。

## 14 旧概念收口规则表

为了避免历史概念继续和 `forward / foldback` 两类主语义并列存在，本章在这里给出正式收口规则表。

下表里的“主语义层处理”回答的是：

- 这个旧概念在 `sweep_transition_candidate` 主线里，应删掉、并入还是保留

下表里的“辅助层处理”回答的是：

- 如果它不再作为主语义保留，还应以什么形式继续存在

| 历史概念 | 主语义层处理 | 辅助层处理 | 说明 |
| --- | --- | --- | --- |
| `through` | 并入 `forward` | 可选保留为形成方式或调试标签 | 只要结果上进入新的 sweep，就不再需要把 through 作为独立主语义保留 |
| `turn` | 并入 `forward` | 可选保留为形成方式或调试标签 | `turn` 描述的是形成方式，不构成独立的 sweep 主语义 |
| `lateral` / `lateral_transition` | 并入 `forward` | 建议保留为形成方式标签 | 它更适合描述“如何形成 forward”，不适合继续作为主语义与 `forward / foldback` 并列 |
| `dead_end_return` | 并入 `foldback` | 建议保留为 dead-end 场景说明或回折原因 | 它本质上是 dead-end 场景中的 same-sweep 回折，不应继续作为独立主语义 |
| `cycle_through` | 删除独立主语义 | 可选保留为历史来源说明或调试标签 | pure cycle cut 场景下，如果结果是继续进入新的 sweep，则已经被 `forward` 完整覆盖 |
| `foldback` | 并入 `foldback` | 必须保留为 fallback 来源、置信度等级或回折原因 | 它与结构性回折的差异主要在来源强弱，不在主语义本体 |

这张表要表达的硬约束是：

- 历史概念不能继续在主语义层直接并列存在
- 旧概念如果还有价值，只能退回到形成方式、来源说明、置信度等级或调试标签层
- 后续代码与文档如果仍把这些旧概念继续当作 `sweep_transition_candidate` 主语义使用，应视为未完成本章收口
