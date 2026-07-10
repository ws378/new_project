# channel_topology_graph

`channel_topology_graph` is the aisle / shelf-like topology coverage algorithm.

This package is a formal top-level algorithm package. Runtime code should import
from `algorithms.channel_topology_graph`, not from the legacy
`python_ws.algorithms.channel_topology_graph` location.

The package contains the 4-stage pipeline:

1. geometry preparation
2. junction rebuild
3. topology graph build
4. coverage planning

The algorithm is not a general room coverage fallback. Scene routing should keep
room-like and mixed spaces outside CTG unless an explicit adapter decision has
validated that the request is aisle-like.

Design documents, support scripts, baselines, and smoke entry points live under
this same package directory:

- `docs/`
- `support/`
- `baselines/`
- `smoke/`

Documentation entry:

- `docs/README.md`
- `support/README.md`
- `smoke/README.md`
- `baselines/README.md`
- `tests/README.md`

Do not add new `channel_topology_graph` runtime assets under `python_ws`.
