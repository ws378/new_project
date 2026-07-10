# io 输入与结果写盘模块说明

## 1. 文档目的

本文档补齐 `algorithms/channel_topology_graph/io` 的正式职责说明，解决“主算法主线文档比较完整，但 `io` 层没有同等级模块文档”的缺口。

本文档只描述当前源码里已经存在的正式输入装配与结果写盘能力，不把实验脚本、单次 compare 脚本或人工临时导出逻辑混进来。

## 2. 模块范围

当前正式源码目录：

- `algorithms/channel_topology_graph/io/__init__.py`
- `algorithms/channel_topology_graph/io/case_loader.py`
- `algorithms/channel_topology_graph/io/result_writer.py`
- `algorithms/channel_topology_graph/io/result_jsonable.py`

包级正式导出面是：

- `CaseInput`
- `load_plan1_case_input`
- `write_geometry_preparation_summary`
- `write_junction_rebuild_summary`
- `write_topology_graph_build_summary`
- `write_coverage_planning_summary`
- `write_coverage_planning_result_json`

## 3. 模块职责边界

`io` 层当前只负责两件事：

1. 把真实 case 目录装配成算法 stage 可直接消费的输入对象。
2. 把 stage 正式结果稳定写成 json 摘要或完整结构文件。

`io` 层不负责：

- 参与几何、拓扑、cadence、final path 的算法判断。
- 改写 stage 正式真值。
- 在写盘阶段重新推导一套和正式 contract 不一致的 schema。

## 4. 输入装配主线

## 4.1 正式入口

真实输入装配入口是：

- `load_plan1_case_input(case_dir, crop_pad_px=20, free_thresh_override=None)`

返回对象是：

- `CaseInput`
  - `case_dir`
  - `raw_map`
  - `region_constraint`
  - `planning_config`
  - `meta`

## 4.2 `CaseInput` 回答什么

`CaseInput` 的真实职责不是“缓存所有源文件内容”，而是把 case 目录里的输入资产收束成 geometry_preparation 可以直接消费的一组运行输入。

其中：

- `raw_map`
  - 给 `geometry_preparation` 直接使用。
  - 当前至少包含 `gray`、`free_mask`、`resolution_m_per_px`、输入文件路径等字段。
- `region_constraint`
  - 当前是由 `region.json` 多边形落到图像坐标系后的区域掩膜。
- `planning_config`
  - case 自带的规划配置，后续由 pipeline/stage 决定如何消费。
- `meta`
  - 输入资产路径、裁剪框、自由阈值、分辨率等留痕信息。

## 4.3 输入装配步骤

当前 `load_plan1_case_input(...)` 主线是：

```text
case_dir
    -> load_case_paths
    -> load_case_assets
    -> build_case_input_views
    -> build_case_input_meta
    -> CaseInput
```

各步职责分别是：

1. `load_case_paths`
   - 校验 case 目录里标准输入文件是否齐全。
   - 当前硬要求存在 yaml、pgm、`region.json`、`planning_config.json`。
2. `load_case_assets`
   - 读取 map yaml、灰度图、planning 配置、region payload。
3. `build_case_input_views`
   - 根据 region polygon 构造区域掩膜。
   - 根据区域掩膜推导裁剪框。
   - 根据灰度图和 map 元信息构造 `free_mask`。
   - 收束出 `geometry_preparation` 真正消费的 `raw_map`。
4. `build_case_input_meta`
   - 回写输入装配痕迹，方便 baseline 与过程记录核对。

## 4.4 输入装配约束

当前源码里有几条需要明确写死的约束：

- yaml/pgm 当前默认取第一个候选，隐含前提是 case 目录遵守“一图一套配置”。
- 缺任一标准输入文件直接报错，不做模糊兜底。
- `free_thresh_override` 只有显式传入时才覆盖 yaml 中的 `free_thresh`。
- `free_mask` 是整图自由区真值，裁剪由 `geometry_preparation` 自己执行，不在 `io` 层提前扣裁剪。

## 5. 结果写盘主线

## 5.1 写盘层正式入口

当前正式写盘入口分两类：

1. stage 摘要写盘
   - `write_geometry_preparation_summary(...)`
   - `write_junction_rebuild_summary(...)`
   - `write_topology_graph_build_summary(...)`
   - `write_coverage_planning_summary(...)`
2. CoveragePlanning 完整结构写盘
   - `write_coverage_planning_result_json(...)`

内部通用 helper 是：

- `normalize_output_dir(...)`
- `write_summary_payload(...)`
- `write_named_json_payload(...)`

## 5.2 写盘层的统一约束

当前写盘层遵守的统一规则是：

- 输出目录先通过 `normalize_output_dir(...)` 规整并创建。
- 摘要统一写到 `summary.json`。
- 完整对象写到命名 json 文件。
- 写盘前统一通过 `result_jsonable.to_jsonable(...)` 做 json 化规整。
- 写盘层不修改 stage 结果对象，只负责稳定落盘。

## 5.3 `CoveragePlanning` 完整结果 schema

这是当前文档必须与源码保持一致的重点。

`build_coverage_planning_result_payload(...)` 当前写出的正式完整 payload 是：

- `graph_info`
- `coverage_lane_sweep_info`
- `sweep_graph_build_info`
- `sweep_cadence_build_info`
- `final_coverage_path_build_info`
- `debug_info`
- `validation_info`
- `meta`

这里不能再写成以下旧口径：

- 顶层平铺 `coverage_lane_info / sweeps / sweep_group_info / ...`
- 旧版四阶段命名平铺结构

完整结果写盘层必须镜像当前 `CoveragePlanningResult` 正式对象树，而不是重发明一套旧 schema。

## 5.4 各 stage 摘要回答什么

1. `geometry_preparation` 摘要
   - 回答裁剪框、自由区像素数、骨架像素数、debug/validation/meta 等高信号信息。
2. `junction_rebuild` 摘要
   - 回答节点数、边数、节点类型分布、边路径规模等轻量索引视图。
3. `topology_graph_build` 摘要
   - 回答 graph/candidate/directed lane 三层关键计数。
4. `coverage_planning` 摘要
   - 回答 graph 规模、coverage lane/sweep 规模、sweep graph 规模、cadence 覆盖率、final path 合法性与路径总长度。

## 6. `io` 与其它目录的边界

与 `pipeline/stages` 的边界：

- `stages` 负责生成正式结果对象。
- `io` 负责把真实输入装配给 stage，以及把 stage 结果稳定写盘。

与 `contracts` 的边界：

- `contracts` 定义正式对象契约。
- `io` 读取这些契约并做 json 化或摘要化导出，但不重新定义契约。

与 `renderers` 的边界：

- `io` 输出 json 和结构化摘要。
- `renderers` 输出图片和可视化产物。
- 两者都属于“结果落地层”，但一个面向结构化数据，一个面向图像检查。

## 7. 当前治理约束

后续整改或扩展 `io` 层时，应继续满足以下约束：

1. 不在写盘层发明新的 stage 结果字段树。
2. 不在输入装配层掺入任何算法决策逻辑。
3. `summary` 与完整结果职责分离。
4. `summary` 只保留高信号摘要，不镜像整块大对象。
5. 完整结果文件要尽可能贴近正式对象树，便于 compare 与对象层核查。

## 8. 结论

当前 `io` 层不是零散工具集，而是这条算法主线的正式输入装配层和结果写盘层：

- 上游把真实 case 目录收束成 `CaseInput`。
- 下游把各 stage 正式结果稳定落成 `summary.json` 或完整结构 json。
- 它的核心价值是固定输入口径、固定写盘口径、固定与正式 contract 的映射关系。

因此后续做基线、审计、整改时，`io` 必须被视为正式模块，而不是附属脚本区。
