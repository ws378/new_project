# Territory Seed Research

This package is an isolated research scaffold for using CTG edge territory as
coverage-region seeds. It does not modify the formal `basic`,
`shelf_aware_guarded`, or `channel_topology_graph` planners.

Current scope:

- Input: `examples/maptools_projects/fourfloor`
- Preprocessing: reuse `algorithms.coverage_planning.preprocessing.preprocess_total_map`
- CTG reuse: run through geometry preparation, junction rebuild, topology graph
  build, and `build_coverage_lane_sweep_info`
- Boundary smoothing: by default, after the first CTG geometry preparation pass,
  smooth only the local free/obstacle boundary band with a 0.25m majority vote
  and a 0.35m write band, then rerun downstream CTG on the smoothed local mask
- Research payload: read `territory_pixels`, `source_edge_id`, edge
  `outer_path_rc`, node polygons, and geometry masks
- Explicitly ignored: CTG `sweep_ids` for planning decisions

Package layout:

```text
territory_seed_research/
  src/        # input loading, CTG extraction, visualization, run orchestration
  scripts/    # command-line entrypoints
  output/     # default run output root
```

Run example:

```bash
python3 -m algorithms.territory_seed_research.scripts.run_fourfloor_territory_study \
  --area-id 2
```

Run every area in a project into one run directory:

```bash
python3 -m algorithms.territory_seed_research.scripts.run_project_territory_study \
  --project-dir examples/maptools_projects/fourfloor \
  --project-dir examples/maptools_projects/beiguo_lanshan_0407
```

Use `--no-boundary-smoothing` to run the baseline CTG extraction without this
research preprocessing step.

By default, run artifacts are written to:

```text
algorithms/territory_seed_research/output/run_<timestamp>/
```

The run directory contains prepared-map images, boundary smoothing diagnostics,
CTG graph overlays, territory seed overlays, junction polygon overlays, edge
direction overlays, expanded dead-end territory overlays, 1m undirected
axis-grid overlays, `direction_grid.json`, `prepare_map/`, and `summary.json`.
The grid stores `axis_angle_rad` modulo pi; it is a local axis preference, not
a robot heading.
