from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

FORMAL_SCAN_ROOTS = (
    REPO_ROOT / "algorithms" / "coverage_planning",
    REPO_ROOT / "maptools" / "views",
    REPO_ROOT / "maptools" / "utils" / "coverage_repo_export.py",
)

BASELINE_SCRIPT_ROOT = REPO_ROOT / "algorithms" / "turn_cost_coverage_research" / "scripts" / "baseline"

FORBIDDEN_TURN_COST_PRIVATE_PREPROCESS_TOKENS = (
    "official_maptools_adapter",
    "run_maptools_official_cases",
    "run_paper_official_algorithm_steps",
    "src.official_replacements",
    "scripts.experiments",
    "scripts.archived",
    "paper_official",
    "third_party/paper_official",
    "third_party.paper_official",
    "build_maptools_case_from_preprocessed",
    "maptools_existing_preprocessing_to_official_polygon_instance",
    "PolygonInstance",
    "legacy_mesh_archive",
    "dmsh",
    "optimesh",
)


def _iter_python_files(path: Path):
    if path.is_file():
        yield path
        return
    for child in path.rglob("*.py"):
        if "__pycache__" in child.parts:
            continue
        yield child


def _scan_forbidden_tokens(*, roots: tuple[Path, ...], tokens: tuple[str, ...]) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    for root in roots:
        for path in _iter_python_files(root):
            text = path.read_text(encoding="utf-8")
            for token in tokens:
                if token in text:
                    matches.append((str(path.relative_to(REPO_ROOT)), token))
    return matches


def test_formal_planner_roots_do_not_import_turn_cost_private_preprocessing() -> None:
    matches = _scan_forbidden_tokens(
        roots=FORMAL_SCAN_ROOTS,
        tokens=FORBIDDEN_TURN_COST_PRIVATE_PREPROCESS_TOKENS,
    )

    assert matches == []


def test_turn_cost_baseline_scripts_do_not_call_official_private_preprocessing() -> None:
    matches = _scan_forbidden_tokens(
        roots=(BASELINE_SCRIPT_ROOT,),
        tokens=FORBIDDEN_TURN_COST_PRIVATE_PREPROCESS_TOKENS,
    )

    assert matches == []


def test_shelf_aware_all_areas_uses_public_maptools_preprocessing_boundary() -> None:
    script = BASELINE_SCRIPT_ROOT / "run_shelf_aware_all_areas.py"
    text = script.read_text(encoding="utf-8")

    assert "from algorithms.coverage_planning.preprocessing import preprocess_total_map" in text
    assert "build_area_region_mask" in text
    assert "build_selected_area_planning_map" in text
