# territory / axis 辅助信息流程与关键规则

本文梳理 `shelf_aware_ctg_research` 中保留的 CTG territory 与 edge axis 辅助信息生产线。这里的 axis 不再作为独立路径规划器输入，不再独立形成全局路径，只作为 `shelf_aware_guarded` 后续诊断和模块优化的辅助图层。

## 定位

当前目录的主体研究对象是原始 `shelf_aware_guarded` 路径。CTG / territory / axis 提供辅助信息：

- 当前路径点属于哪个 edge territory；
- 当前点是否落在 junction / unknown / connector 区；
- jump 是否跨 territory；
- grid node 是否位于边界敏感区域或通道主体区域；
- local direction 未来是否可被通道级 axis 解释或补充。

不再做：

- 不生成独立 axis 路径；
- 不输出 baseline 与独立 axis 路径的全局比较；
- 不用外部 axis 辅助输入替代 baseline local direction；
- 不用独立 axis 路径的长短、jump 数量评价研究方向。

## 研究输入

入口：

- `algorithms/shelf_aware_ctg_research/scripts/run_project_study.py`
- 内部 runner：`algorithms/shelf_aware_ctg_research/src/study_runner.py`

默认输出：

```text
algorithms/shelf_aware_ctg_research/output/run_<timestamp>/<project>_area_<id>/
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
  -> core visualizations + direction_grid.json
  -> shelf_aware_guarded baseline path
```

## CTG 前处理和读取字段

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
- `effective_region_pixels` 暂不作为主输入。
- `sweep_ids` 当前不作为辅助信息核心依据。

## expanded territory

代码位置：`src/territory_expansion.py`

当前实现：

1. 生成 node polygon mask。
2. 从 free mask 中扣除 node polygon，得到 constrained free mask。
3. 用 `derive_outer_path_territory_pixels()` 基于所有 edge 的 outer path 派生 edge territory seed。
4. 将 seed 写入 label map。
5. 对 dead_end edge 做 flood fill 扩充。
6. 输出 `ExpandedTerritory`：
   - `labels`：每个 free pixel 属于哪个 edge，未归属为 -1；
   - `pixel_count_by_edge`；
   - `expanded_edge_ids`。

语义：

- `labels >= 0` 表示 edge territory。
- `labels == -1` 表示 junction / unknown / connector / 未归属区。
- expanded territory 是证据，不是绝对真值，不直接规定覆盖顺序。

## edge axis direction grid

代码位置：`src/direction_grid.py`

当前方向来自 `graph_info.edges[*].outer_path_rc`：

1. 对 edge 的 `outer_path_rc` 做轻量平滑。
2. 对路径每个点估计局部切线。
3. 对 1m x 1m 网格中心采样。
4. 找网格中心所属 edge label。
5. 在该 edge reference path 上找最近点。
6. 使用最近点局部 tangent 得到 `axis_angle_rad`。
7. axis angle 是无向轴语义，模 `pi`。

该 grid 只作为辅助信息输出，不再直接喂给 `shelf_aware_guarded` 形成独立路径。

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
09_shelf_aware_baseline_path_overlay.png
summary.json
direction_grid.json
```

其中：

- `06_edge_direction_overlay.png` 看 edge outer path 和方向。
- `07_expanded_territory_overlay.png` 看 edge territory label。
- `08_expanded_territory_direction_grid.png` 看 1m 方向样本。
- `09_shelf_aware_baseline_path_overlay.png` 是主体规划器路径。

## 当前局限

1. CTG edge 可能过碎，不能直接作为强约束。
2. axis 是 180 度无向语义，不表达机器人实际前进方向。
3. axis 不理解货架/墙边局部细节，不能替代 baseline local direction。
4. junction 语义仍不足，需要用 label=-1 作为 connector/unknown 证据谨慎处理。
5. territory 是诊断和辅助证据，不是规划真值。
