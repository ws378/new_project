# coverage_planning tools

This directory contains repository-level utilities for running and viewing standard coverage planning cases.

## Tools

- `run_case.py` runs a case directory through the formal `algorithms/coverage_planning` planners.
- `viewer.py` renders a `summary.json` global path back onto its source map.

## Boundary

- These tools are not algorithm implementations.
- These tools must not import historical `python_ws/algorithms` implementations.
- Runtime outputs belong under the selected case directory's `runs/` and `latest` paths, which are generated artifacts and should not be tracked.

## Example

```bash
python3 tools/coverage_planning/run_case.py \
  --case-dir tests/fixtures/coverage_cases/case_demo \
  --algorithm basic

python3 tools/coverage_planning/viewer.py \
  --run-dir tests/fixtures/coverage_cases/case_demo/latest \
  --no-view
```
