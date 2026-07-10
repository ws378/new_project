# Shelf-Aware CTG Research

This package is a new isolated research scaffold for studying how
`shelf_aware_guarded` can use CTG-derived auxiliary information.

It is not a full copy of `territory_seed_research`, and it is not a new combined
planner. The current baseline only preserves the auxiliary-information pipeline
needed for later module-level research:

```text
maptools project area
  -> CTG extraction
  -> expanded territory label map
  -> edge-axis direction grid
  -> core visualizations
  -> shelf_aware_guarded baseline path
```

Current scope:

- Keep `shelf_aware_guarded` as the subject planner.
- Copy the territory / edge-axis auxiliary information chain without changing parameters or
  adding new strategy rules.
- Use CTG outputs as auxiliary evidence: edge territory, junction/unknown areas,
  and edge axis samples.
- Do not include historical `ctg_guided` combination experiments in this package.
- Do not implement corridor grouping, residual node deletion, node snapping,
  residual insertion, or new route policies here yet.

Copied core modules:

```text
src/project_inputs.py            # maptools project and area input loading
src/ctg_territory_extractor.py   # CTG geometry/junction/topology/lane extraction wrapper
src/boundary_smoothing.py        # existing boundary-band majority smoothing helper
src/territory_expansion.py       # territory seed labels and dead-end fill
src/direction_grid.py            # 1m edge-axis samples and axis maps
src/visualization.py             # core CTG/territory/axis visualizations
src/study_runner.py              # project runner, shelf_aware_guarded baseline only
```

Run example:

```bash
python3 -m algorithms.shelf_aware_ctg_research.scripts.run_project_study \
  --project-dir examples/maptools_projects/fourfloor \
  --project-dir examples/maptools_projects/beiguo_lanshan_0407
```

Residual grid-node diagnosis example:

```bash
python3 -m algorithms.shelf_aware_ctg_research.scripts.diagnose_residual_grid_nodes \
  --run-dir algorithms/shelf_aware_ctg_research/output/run_<timestamp>
```

Residual jump-target classification example:

```bash
python3 -m algorithms.shelf_aware_ctg_research.scripts.classify_residual_jump_targets \
  --run-dir algorithms/shelf_aware_ctg_research/output/run_<timestamp>
```

Overlap pruning simulation example:

```bash
python3 -m algorithms.shelf_aware_ctg_research.scripts.simulate_residual_pruning \
  --run-dir algorithms/shelf_aware_ctg_research/output/run_<timestamp>
```

Local reconnect / snap simulation example:

```bash
python3 -m algorithms.shelf_aware_ctg_research.scripts.simulate_local_reconnect_snap \
  --run-dir algorithms/shelf_aware_ctg_research/output/run_<timestamp>
```

Node semantics research example:

```bash
python3 -m algorithms.shelf_aware_ctg_research.scripts.build_node_semantics \
  --run-dir algorithms/shelf_aware_ctg_research/output/run_<timestamp>
```

This computes `coverage_obligation`（覆盖责任）, `connectivity_value`（连通价值）, and `node_role`（节点角色）from territory footprint statistics, junction polygons, and shelf-aware grid-node quality. It does not modify the formal planner or generate a replacement path.

By default, artifacts are written to:

```text
algorithms/shelf_aware_ctg_research/output/run_<timestamp>/
```

Expected area outputs include prepared maps, CTG graph overlays, territory seed
overlays, junction polygons, edge direction overlays, expanded territory overlays,
1m axis-grid overlays, `direction_grid.json`, `summary.json`, and baseline path artifacts. Axis outputs are auxiliary visualizations, not independent paths.

The docs directory contains reference notes copied from the previous research
stage plus `docs/research_governance/`, which defines the preflight, execution,
validation, and Git boundaries for the next diagnosis-first research batches.
Executable logic in this package is limited to the auxiliary-information baseline
described above until a research batch explicitly adds diagnostics or experiments.
