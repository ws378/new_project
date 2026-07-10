from __future__ import annotations

from pathlib import Path


SCRIPT_ROOT = Path("algorithms/turn_cost_coverage_research/scripts")


def test_turn_cost_research_scripts_do_not_restore_root_run_wrappers() -> None:
    root_wrappers = sorted(path.name for path in SCRIPT_ROOT.glob("run_*.py"))

    assert root_wrappers == []


def test_turn_cost_research_scripts_do_not_restore_compat_module() -> None:
    assert not (SCRIPT_ROOT / "_compat.py").exists()
