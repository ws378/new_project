# `candidate` 到 `cadence` 的最小正式链路

本文档只回答一件事：

- 在 `sweep` 已经生成完成之后，`candidate -> cadence` 的最小正式主链路应该是什么

本文档不讨论：

- `final_coverage_path`
- 历史镜像层
- 调试导出层
- 向后兼容包装层

## 1. 最小正式链路

最小正式链路只保留两层：

1. `sweep_transition_candidate_info`
2. `sweep_cadence_info`

也就是：

`candidate -> cadence`

更完整地写，就是：

`sweeps -> sweep_transition_candidate_info -> sweep_cadence_info`

其中：

- `sweeps` - 已经生成完成的正式扫线集合
- `sweep_transition_candidate_info` - 正式扫线连接候选信息
- `sweep_cadence_info` - 最终扫线节拍信息

这里要特别明确：

- `sweep_transition_candidate_info` 本身就是正式候选层
- 不再允许在这个对象内部再拆出第二层候选子集
- 也就是说，不再把“候选中的候选”挂在主线 contract 里

主线含义非常简单：

- 先生成正式候选连接
- 再在这些正式候选连接上生成最终节拍

## 2. 第一层：`sweep_transition_candidate_info`

### 2.1 这一层回答什么

这一层只回答：

- 哪些 `sweep -> sweep` 连接允许进入正式主线
- 每条连接的起止端口是什么
- 每条连接的主语义是什么
- 每条连接的几何、风险和分数是什么

这一层不负责：

- 直接决定最终节拍
- 直接输出最终覆盖路径
- 在主线对象里再保留一层“未采用候选池”
- 再包装成另一套重复连接对象

### 2.2 这一层的最小输入

建议只保留三类输入事实：

1. `sweeps`
   - 中文说明：正式扫线集合
2. `node_local_connection_hypothesis_info`
   - 中文说明：节点局部连接假设信息
3. 组内顺序事实
   - 中文说明：同一组 `sweep` 在端口侧的顺序、`rank`、相邻关系

#### `sweeps` 至少要提供

- `sweep_id` - 扫线编号
- `source_edge_id` - 来源边编号
- `path_rc` - 扫线路径点，`row/col` 坐标序列
- `src_point_rc` - 扫线起点坐标
- `dst_point_rc` - 扫线终点坐标

#### `node_local_connection_hypothesis_info` 至少要提供

- `via_node_id` - 连接发生的节点编号
- `in_edge_id` - 输入边编号
- `out_edge_id` - 输出边编号
- `in_end_type` - 输入端口类型
- `out_end_type` - 输出端口类型
- `connection_kind` - 上游定义的主连接语义

这里的 `src / dst` 中文含义是：

- `src` - 当前对象的起点端
- `dst` - 当前对象的终点端

### 2.3 这一层的最小输出字段

每条 `candidate` 至少要包含下面这些字段。

#### 身份字段

- `candidate_id` - 候选连接编号
- `from_sweep_id` - 起始扫线编号
- `to_sweep_id` - 目标扫线编号

#### 端口字段

- `from_end_type` - 起始端口类型，通常是 `src` 或 `dst`
- `to_end_type` - 目标端口类型，通常是 `src` 或 `dst`

#### 主语义字段

- `connection_kind` - 连接主语义

长期建议只保留两类：

- `forward` - 前进，表示进入下一条 `sweep`
- `foldback` - 回折，表示没有进入新的 `sweep`，而是在当前 `sweep` 或当前 edge 上折返

#### 候选来源字段

- `candidate_source` - 候选来源

它只表示来源，不表示主语义。例如：

- `node_projected` - 从节点局部连接假设投影得到
- `group_internal` - 从组内横向规则生成
- `fallback` - 从保底补位规则生成

#### 约束与评分字段

- `rank_gap` - 同 group 横移候选在同一 port view 内的层级差
- `endpoint_distance_px` - 两条 `sweep` 待连接端点间的像素距离
- `sweep_turn_delta_deg` - 两条 `sweep` 待连接端点方向之间的夹角，用于校验具体 pair 是否符合 `motion_type` 期望
- `local_feasibility_score` - 当前候选在局部可行域、障碍风险和连接空间中的可行性评分
- `risk_score` - 由端点距离、sweep 级转角、局部可行性和候选来源共同得到的风险分数
- `confidence_score` - 置信度分数
- `total_score` - 综合排序分数

#### 辅助判断字段

- `same_sweep` - 是否同一条 `sweep`
- `same_edge` - 是否来自同一条 edge

这两个字段只用于约束和调试，不应替代主语义。

#### 跨 group 与 group 内评分边界

- 跨 group transition 当前没有 rank frame 对齐，`rank_gap / mean_offset_m / side_level` 不能参与 pair 主排序、后置 tie-break 或 connector 主成本。
- 跨 group transition 的主比较依据是 `endpoint_distance_px / sweep_turn_delta_deg / local_feasibility_score / risk_score / total_score`。
- group 内 transition 共享同一 group frame，`rank_gap / mean_offset_m / side_level` 可以作为横移范围、横移风险和 sweep 角色依据。
- group 内 transition 仍要结合端点距离和局部可行性，不能只靠 rank 或 offset。
- cadence 消费 candidate 时，跨 group 的目标 sweep 角色偏好必须排在 pair 连接质量之后。

### 2.4 这一层的正式输出口径

`sweep_transition_candidate_info` 正式上只应提供：

- `items` - 正式候选项集合
- `summary` - 简要统计

这里的 `items` 要明确理解为：

- 每一项都已经是允许进入 `cadence` 的正式候选连接
- 不是“全量展开项”
- 不是“待二次筛选候选池”

候选展开过程中的分析材料、未采用展开项或弱边来源只能进入：

- `debug_info`
- 专门的调试导出对象
- 渲染或分析辅助对象

正式主线 contract 只暴露 `items + summary`。

## 3. 第二层：`sweep_cadence_info`

### 3.1 这一层回答什么

这一层只回答：

- 最终选择了哪些候选连接
- `sweep` 的访问顺序是什么
- 每条 `route` 的连接段和覆盖段如何交替排列

这一层不负责：

- 重新发明新的正式候选边
- 推翻上一层已经定义好的连接合法性

### 3.2 这一层的正式输入

`sweep_cadence_info` 的正式输入应当直接是：

- `sweeps`
- `sweep_transition_candidate_info.items`

也就是说，节拍层直接在正式候选集合上工作。

它不应再依赖一层新的镜像连接图，否则会再次形成第二套连接真值。

### 3.3 这一层的最小处理

节拍层最小上只做三步：

1. 建立可走候选索引
   - 按“当前 `sweep` + 当前退出端口”建立查询关系
2. 选择下一跳
   - 在合法候选里选出下一条连接
3. 生成 `route` 与全局顺序
   - 把最终选中的候选连接串成正式节拍结果

这里的“退出端口”中文含义是：

- 当前这条 `sweep` 是从哪一端离开的

这里的“合法候选”至少要满足：

- 连接端口闭合
- 不破坏前进语义
- 不违反当前连接约束

这里的“优先选择”至少可以看：

- 是否覆盖未访问 `sweep`
- `connection_kind`
- `total_score`
- `risk_score`

### 3.4 这一层的最小输出

`sweep_cadence_info` 最小应包含：

- `routes` - 节拍路由集合
- `route_sweep_order` - 每条 `route` 内的扫线顺序
- `ordered_passes` - 展开后的全局经过顺序
- `summary` - 摘要统计

其中：

- `routes` - 按 `route` 分组后的正式节拍结果
- `route_sweep_order` - 每条 `route` 中 `sweep` 的访问次序
- `ordered_passes` - 把 `sweep` 段和连接段展开之后的顺序视图

## 4. 为什么主线不需要中间镜像层

如果已经有：

- 候选层真值
- 节拍层真值

那么中间再增加：

- 连接单元镜像
- `transition` 投影视图
- 重复包装的图层对象

在主线上通常只会带来：

- 同一件事情表达两遍
- 调试链路变长
- 维护时难以判断哪个才是真值

因此长期正式口径应当是：

- 候选层负责“有哪些正式候选连接”
- 节拍层负责“最终选择了哪些连接”

除此之外的中间读取视图，只能作为调试或兼容辅助层，不能再作为主线正式真值。

## 5. 一句话收口

`candidate -> cadence` 的最小正式链路就是：

- `sweep_transition_candidate_info` 直接承载正式候选连接
- `sweep_cadence_info` 直接在这些正式候选连接上生成最终节拍

主线不再保留“候选中的候选”以及额外的镜像连接真值层。
