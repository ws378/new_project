# Coverage Planning Algorithms

This package is the long-term home for coverage-planning algorithms.

It separates reusable planner implementations from the `maptools` product layer.
`maptools` should call this package through stable adapters and contracts instead
of importing planner internals directly.

Current migration status:

- `contracts/` defines the shared request, result, applicability, and diagnostic models.
- `planners/region_basic/` hosts the migrated basic room-like coverage planner.
- `planners/shelf_aware_guarded/` hosts the migrated shelf-aware guarded planner.
- `routing/` hosts the conservative planner preflight and formal result conversion.

Documentation entry:

- `docs/README.md`

Current routing limits:

- `room_like` routes to `region_basic`.
- `mixed` routes to a conservative region planner and records that no sub-region split was performed.
- `aisle_like` uses the guarded region planner by default.
- `aisle_like` routes to `channel_topology_graph` only when `enable_channel_topology_graph` is explicitly set.
- `invalid` requests stop before planner execution and return an unsupported formal result.
- Routing does not depend on room segmentation and does not change GUI default planner choices.

Runtime artifacts:

- Explicit `artifacts_output_root` from the caller always wins.
- Planner defaults write under repository-level `runtime_runs/coverage_planning/`.
- Defaults must not write under the legacy `python_ws/` workspace.
- `runtime_runs/` is ignored by Git and is not a source-truth directory.

Do not place GUI-specific code, dataset runners, or temporary report logic in this
package.
