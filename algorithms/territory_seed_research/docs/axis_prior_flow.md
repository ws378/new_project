# axis prior / territory seed 流程与关键规则

本文梳理 `algorithms/territory_seed_research` 中当前 axis prior 研究流程。它是研究脚本，不是正式默认覆盖算法。

## 研究输入

当前主要入口：

- `algorithms/territory_seed_research/scripts/run_project_territory_study.py`
- 内部 runner：`algorithms/territory_seed_research/src/study_runner.py`

当前研究输入项目：

- `examples/maptools_projects/fourfloor`
- `examples/maptools_projects/beiguo_lanshan_0407`

每个 area 会独立生成输出目录：

```text
algorithms/territory_seed_research/output/run_<timestamp>/<project>_area_<id>/
```

## 总体流程

```text
maptools project area
  -> build_study_input
  -> CTG extraction
       geometry_preparation
       junction_rebuild
       topology_graph_build
       build_coverage_lane_sweep_info
  -> territory seed / expanded territory
  -> edge outer_path direction grid
  -> axis_map / confidence_map
  -> shelf_aware baseline vs axis prior 对比
  -> 输出可视化和 summary
```

## CTG 前处理和读取字段

代码入口：`src/ctg_territory_extractor.py`

复用正式 CTG 前几步：

1. `geometry_preparation`
2. `junction_rebuild`
3. `topology_graph_build`
4. `build_coverage_lane_sweep_info`

研究流程主要读取：

- `coverage_lane_info[*].source_edge_id`
- `coverage_lane_info[*].territory_pixels`
- `graph_info.edges[*].outer_path_rc`
- `graph_info.nodes[*].polygon_vertices_rc`
- `geometry_result.free_mask`
- `geometry_result.region_mask`

当前判断：

- `territory_pixels` 更适合作为“归属种子/势力范围证据”。
- `effective_region_pixels` 更保守，适合直接用于 edge 内覆盖核心区，但当前研究先不用它。
- `sweep_ids` 当前不作为 axis prior 的主要依据。

## territory seed 和 expanded territory

代码位置：`src/territory_expansion.py`

当前实现不是直接使用最终 active lane 的 territory，而是基于 `graph_info.edges[*].outer_path_rc` 重新派生 territory seed：

1. 生成 node polygon mask。
2. 从 free mask 中扣除 node polygon，得到 constrained free mask。
3. 用 `derive_outer_path_territory_pixels()` 基于所有 edge 的 outer path 派生 edge territory seed。
4. 将 seed 写入 label map。
5. 对 dead_end edge 做 flood fill 扩充。
6. 输出 `ExpandedTerritory`：
   - `labels`：每个 free pixel 属于哪个 edge，未归属为 -1。
   - `pixel_count_by_edge`
   - `expanded_edge_ids`

关键含义：

- `labels >= 0` 表示该像素被某条 edge territory 归属。
- `labels == -1` 通常表示 junction、未归属、或不适合强行归属到某条通道。
- dead_end 做 flood fill 是为了让断头通道区域尽量形成完整归属。
- 当前没有对所有通道做完整 flood fill，避免把路口/模糊区域硬塞给 edge。

## edge 方向来源

代码位置：`src/direction_grid.py`

当前方向来自 `graph_info.edges[*].outer_path_rc`：

1. 对 edge 的 `outer_path_rc` 做轻量平滑：`smooth_center_reference_path(window_radius=2)`。
2. 对路径每个点估计局部切线：`estimate_local_tangent()`。
3. 对 1m x 1m 网格中心采样。
4. 找网格中心所属 edge label。
5. 在该 edge reference path 上找最近点。
6. 使用最近点局部 tangent 得到 axis angle。
7. axis angle 是无向轴语义，模 `pi`。

输出 sample 字段包括：

- `row`, `col`
- `edge_id`
- `axis_angle_rad`
- `direction_vector_rc`
- `confidence`
- `nearest_path_index`
- `axis_class`

## 1m 网格方向样本

默认配置：

- `DEFAULT_GRID_SPACING_M = 1.0`
- 根据 `resolution_m_per_px` 换算成像素间距。

这样做的原因：

- 不需要每个 free pixel 都计算方向。
- 方向先验本身是通道级/拓扑级，不应该像边界 local direction 那样过密。
- 1m 采样更接近“区域局部方向块”。

## axis_map / confidence_map

代码位置：`direction_grid_to_axis_maps()`

规则：

1. 创建与 free mask 同尺寸的 `axis_map` 和 `confidence_map`。
2. 对每个 1m sample，以半个 grid spacing 为范围填充一个小块。
3. 小块内写入相同 `axis_angle_rad` 和 confidence。
4. 未采样/未归属区域 confidence 默认为 0。

当前 axis prior 版本直接把这两个 map 传给 `ShelfAwareCoveragePlanner.plan()`：

```text
local_axis_direction_map=axis_map
local_axis_confidence_map=confidence_map
```

在 `shelf_aware_guarded` 内部，如果提供 external axis map，会替代 baseline 的 image-gradient local direction。

这是当前 axis prior 变差的关键原因之一：它把 baseline 擅长的局部边界方向替换掉了。

## 路口/未归属区语义

当前 expanded labels 中：

- edge territory：`labels >= 0`
- junction / 模糊 / 未归属：`labels == -1`

研究判断：

- 路口本身没有唯一主方向。
- 小路口可以重复通过，作为 connector。
- 宽路口可以允许掉头或少量覆盖，但不应硬套通道 sweep 语义。
- 方向不明确路口应更多沿用进入路口前的 heading，而不是由 axis prior 强推。

当前代码层面：

- axis prior 的 confidence 在未采样区域是 0。
- 但如果 expanded territory 把路口附近错误归属给 edge，axis 仍可能影响路径。
- 当前还没有完整的路口分类和路口行为建模。

## 输出可视化

每个 area 当前输出：

```text
01_prepared_map.png
02_region_mask.png
03_ctg_skeleton_graph.png
04_territory_seed_overlay.png
05_junction_polygon_overlay.png
06_edge_direction_overlay.png
07_expanded_territory_overlay.png
08_expanded_territory_direction_grid.png
09_shelf_aware_axis_path_overlay.png
10_shelf_aware_baseline_path_overlay.png
11_shelf_aware_path_comparison.png
12_shelf_aware_ctg_guided_path_overlay.png
13_shelf_aware_ctg_guided_comparison.png
summary.json
direction_grid.json
```

其中：

- `06_edge_direction_overlay.png` 看 edge outer path 和方向。
- `07_expanded_territory_overlay.png` 看 edge territory label。
- `08_expanded_territory_direction_grid.png` 看 1m 方向样本。
- `09/10/11` 对比 axis prior 与 baseline。
- `12/13` 是后续加入的保守 CTG-guided 研究变体。

## 当前局限

1. CTG edge 可能过碎。
   - 例如 `beiguo_lanshan_0407_area_6` 出现大量 nodes/edges。
   - 直接把原始 edge label 作为规划约束，可能引入局部碎片化问题。

2. axis 只有无向轴语义。
   - 左右同义，上下同义。
   - 真正前进方向要由上一段路径 heading 决定。

3. axis 不理解货架细节。
   - 它来自 edge outer path，不来自货架/墙体局部边界。
   - 因此不应直接替代 baseline local direction。

4. junction 语义不足。
   - 当前没有稳定区分小路口、宽路口、掉头区、普通 connector。

5. territory 是证据，不是绝对真值。
   - `territory_pixels` 表达“更靠近哪条 edge”。
   - 它适合作为种子/归属证据，不适合直接规定覆盖顺序。
