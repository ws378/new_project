from __future__ import annotations

import ast
from pathlib import Path


SHELF_AWARE_IMPL_ROOT = (
    Path(__file__).resolve().parents[1]
    / "algorithms"
    / "coverage_planning"
    / "planners"
    / "shelf_aware_guarded"
)
SHELF_AWARE_ROOT = SHELF_AWARE_IMPL_ROOT

LEGACY_DYNAMIC_STATE_PATTERNS = (".visited", ".visit_count")
LEGACY_DYNAMIC_STATE_ALLOWED_FILES = {
    "models.py",  # legacy Node 静态壳字段定义；正式遍历运行期不得读写这些动态字段。
}

LEGACY_STATIC_FACT_PATTERNS = (
    ".planning_point_px",
    ".grid_center_px",
    ".neighbors",
    ".obstacle",
    ".obstacle_ratio",
    ".obstacle_ratio_filtered",
)
STATIC_FACT_FORBIDDEN_FILES = {
    "final_path/realization.py",
    "pipeline/artifact_write.py",
    "pipeline/graph_traversal.py",
    "pipeline/output_assembly.py",
    "pipeline/start_cell.py",
    "traversal_core/traversal.py",
    "traversal_core/traversal_candidate_enumeration.py",
    "traversal_core/traversal_move_commit.py",
    "traversal_core/traversal_phase_selectors.py",
    "traversal_core/traversal_reachability.py",
}


def test_legacy_node_dynamic_state_access_is_retired_from_runtime_code():
    offenders: list[str] = []
    for path in sorted(SHELF_AWARE_IMPL_ROOT.rglob("*.py")):
        relative = path.relative_to(SHELF_AWARE_IMPL_ROOT)
        if relative.name in LEGACY_DYNAMIC_STATE_ALLOWED_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            attr_pattern = f".{node.attr}"
            if attr_pattern in LEGACY_DYNAMIC_STATE_PATTERNS:
                offenders.append(f"{relative}:{node.lineno}:{attr_pattern}")

    assert offenders == []


def test_planning_stages_do_not_read_legacy_node_static_fields_directly():
    offenders: list[str] = []
    for filename in sorted(STATIC_FACT_FORBIDDEN_FILES):
        path = SHELF_AWARE_IMPL_ROOT / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            attr_pattern = f".{node.attr}"
            if attr_pattern in LEGACY_STATIC_FACT_PATTERNS:
                offenders.append(f"{filename}:{node.lineno}:{attr_pattern}")

    assert offenders == []


def test_formal_graph_and_artifact_contracts_do_not_expose_generic_nodes_field():
    checked_files = {
        "artifacts/writer.py",
        "pipeline/coverage_graph.py",
    }
    offenders: list[str] = []
    for relative_name in sorted(checked_files):
        path = SHELF_AWARE_IMPL_ROOT / relative_name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "nodes":
                offenders.append(f"{relative_name}:{node.lineno}:.nodes")
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "nodes":
                offenders.append(f"{relative_name}:{node.lineno}:nodes field")

    assert offenders == []


def test_formal_code_and_tests_do_not_use_legacy_build_nodes_wrapper():
    checked_roots = (
        SHELF_AWARE_IMPL_ROOT,
        Path(__file__).resolve().parents[0],
    )
    offenders: list[str] = []

    for root in checked_roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            relative = path.relative_to(Path(__file__).resolve().parents[1])
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "build_nodes":
                    offenders.append(f"{relative}:{node.lineno}:def build_nodes")
                if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("grid_builder"):
                    imported_names = {alias.name for alias in node.names}
                    if "build_nodes" in imported_names:
                        offenders.append(f"{relative}:{node.lineno}:import build_nodes")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "build_nodes":
                    offenders.append(f"{relative}:{node.lineno}:call build_nodes")

    assert offenders == []


def test_production_code_does_not_restore_legacy_coverage_graph_builder_name():
    offenders: list[str] = []
    allowed_definition_file = SHELF_AWARE_IMPL_ROOT / "coverage_graph.py"
    for path in sorted(SHELF_AWARE_IMPL_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(SHELF_AWARE_IMPL_ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported_names = {alias.name for alias in node.names}
                if "build_coverage_graph_view" in imported_names:
                    offenders.append(f"{relative}:{node.lineno}:import build_coverage_graph_view")
            if path != allowed_definition_file and isinstance(node, ast.Name) and node.id == "build_coverage_graph_view":
                offenders.append(f"{relative}:{node.lineno}:build_coverage_graph_view")

    assert offenders == []


def test_artifact_debug_outputs_do_not_accept_legacy_node_matrix_as_input():
    checked_files = {
        "artifacts/csv_debug.py",
        "artifacts/metadata_payloads.py",
        "artifacts/node_debug.py",
        "artifacts/visualization.py",
        "artifacts/writer.py",
        "pipeline/artifact_write.py",
    }
    offenders: list[str] = []

    for relative_name in sorted(checked_files):
        path = SHELF_AWARE_IMPL_ROOT / relative_name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.arg) and node.arg == "legacy_node_matrix":
                offenders.append(f"{relative_name}:{node.lineno}:legacy_node_matrix argument")
            if isinstance(node, ast.Attribute) and node.attr == "legacy_node_matrix":
                offenders.append(f"{relative_name}:{node.lineno}:.legacy_node_matrix")

    assert offenders == []


def test_coverage_graph_build_result_does_not_expose_legacy_node_matrix_field():
    path = SHELF_AWARE_IMPL_ROOT / "pipeline" / "coverage_graph.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "CoverageGraphBuildResult":
            continue
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                if item.target.id == "legacy_node_matrix":
                    offenders.append(f"pipeline/coverage_graph.py:{item.lineno}:legacy_node_matrix field")

    assert offenders == []


def test_formal_stage_contexts_do_not_read_graph_stage_legacy_node_matrix():
    checked_files = {
        "final_path/realization.py",
        "pipeline/artifact_write.py",
        "pipeline/graph_traversal.py",
        "pipeline/output_assembly.py",
    }
    offenders: list[str] = []

    for filename in sorted(checked_files):
        path = SHELF_AWARE_IMPL_ROOT / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "legacy_node_matrix":
                offenders.append(f"{filename}:{node.lineno}:.legacy_node_matrix")

    assert offenders == []


def test_traversal_cursor_does_not_carry_legacy_node_shell():
    path = SHELF_AWARE_IMPL_ROOT / "traversal_core" / "traversal_cursor.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "legacy_node":
            offenders.append(f"traversal_core/traversal_cursor.py:{node.lineno}:legacy_node")
        if isinstance(node, ast.Attribute) and node.attr == "legacy_node":
            offenders.append(f"traversal_core/traversal_cursor.py:{node.lineno}:.legacy_node")

    assert offenders == []


def test_phase_selectors_do_not_own_scoring_context_or_formula_bridge():
    path = SHELF_AWARE_IMPL_ROOT / "traversal_core" / "traversal_phase_selectors.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    forbidden_query_modules = {
        "traversal_candidate_enumeration",
        "traversal_reachability",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "TraversalScoringContext":
            offenders.append(f"traversal_core/traversal_phase_selectors.py:{node.lineno}:class TraversalScoringContext")
        if isinstance(node, ast.FunctionDef) and node.name == "build_traversal_scoring_context":
            offenders.append(f"traversal_core/traversal_phase_selectors.py:{node.lineno}:build_traversal_scoring_context")
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("candidate_scoring"):
            imported_names = {alias.name for alias in node.names}
            forbidden = imported_names & {"CandidateScoringGeometry", "evaluate_candidate_score_for_geometry"}
            for name in sorted(forbidden):
                offenders.append(f"traversal_core/traversal_phase_selectors.py:{node.lineno}:import {name}")
        if isinstance(node, ast.ImportFrom) and node.module:
            module_tail = node.module.rsplit(".", 1)[-1]
            if module_tail in forbidden_query_modules:
                offenders.append(f"traversal_core/traversal_phase_selectors.py:{node.lineno}:import {module_tail}")

    assert offenders == []


def test_candidate_scoring_entrypoint_is_only_called_from_evaluation_bridge():
    allowed_file = SHELF_AWARE_IMPL_ROOT / "traversal_core" / "traversal_candidate_evaluation.py"
    offenders: list[str] = []

    for path in sorted(SHELF_AWARE_IMPL_ROOT.rglob("*.py")):
        if path == allowed_file:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(SHELF_AWARE_IMPL_ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "evaluate_candidate_score_for_geometry":
                    offenders.append(f"{relative}:{node.lineno}:evaluate_candidate_score_for_geometry")
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("candidate_scoring"):
                imported_names = {alias.name for alias in node.names}
                if "evaluate_candidate_score_for_geometry" in imported_names:
                    offenders.append(f"{relative}:{node.lineno}:import evaluate_candidate_score_for_geometry")

    assert offenders == []


def test_final_path_realization_keeps_transform_records_structured_until_artifact_boundary():
    path = SHELF_AWARE_IMPL_ROOT / "final_path" / "realization.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            target_name = node.target.id if isinstance(node.target, ast.Name) else None
            if target_name != "transform_records":
                continue
            annotation = ast.unparse(node.annotation)
            if "dict" in annotation:
                offenders.append(f"final_path/realization.py:{node.lineno}:transform_records dict annotation")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr != "append":
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "transform_records":
                continue
            if node.args and isinstance(node.args[0], ast.Dict):
                offenders.append(f"final_path/realization.py:{node.lineno}:append dict transform record")

    assert offenders == []


def test_traversal_loop_does_not_own_step_selection_or_scoring_bridge():
    path = SHELF_AWARE_IMPL_ROOT / "traversal_core" / "traversal.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden_import_modules = {
        "traversal_candidate_enumeration",
        "traversal_phase_selectors",
        "traversal_reachability",
        "traversal_scoring_context",
    }
    forbidden_defs = {
        "TraversalStepContext",
        "TraversalStepDecision",
        "select_next_traversal_candidate",
        "sync_history_clearance_index",
    }
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            module_tail = node.module.rsplit(".", 1)[-1]
            if module_tail in forbidden_import_modules:
                offenders.append(f"traversal_core/traversal.py:{node.lineno}:import {module_tail}")
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in forbidden_defs:
            offenders.append(f"traversal_core/traversal.py:{node.lineno}:{node.name}")

    assert offenders == []


def test_traversal_runtime_does_not_access_legacy_node_shell_directly():
    checked_files = {
        path.relative_to(SHELF_AWARE_ROOT)
        for root in (SHELF_AWARE_IMPL_ROOT,)
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    }
    allowed_files: set[Path] = set()
    offenders: list[str] = []

    for relative_path in sorted(checked_files):
        if relative_path in allowed_files:
            continue
        path = SHELF_AWARE_ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "node":
                continue
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "graph_access":
                offenders.append(f"{relative_path}:{node.lineno}:graph_access.node")

    assert offenders == []


def test_runtime_code_does_not_call_legacy_node_mirror_directly():
    checked_files = {
        path.relative_to(SHELF_AWARE_ROOT)
        for root in (SHELF_AWARE_IMPL_ROOT,)
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    }
    allowed_files: set[Path] = set()
    offenders: list[str] = []

    for relative_path in sorted(checked_files):
        if relative_path in allowed_files:
            continue
        path = SHELF_AWARE_ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "legacy_node_mirror":
                continue
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "graph_access":
                offenders.append(f"{relative_path}:{node.lineno}:graph_access.legacy_node_mirror")

    assert offenders == []


def test_traversal_graph_access_does_not_expose_generic_node_method():
    path = SHELF_AWARE_IMPL_ROOT / "traversal_core" / "traversal_graph_access.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "node":
            offenders.append(f"traversal_core/traversal_graph_access.py:{node.lineno}:def node")

    assert offenders == []


def test_traversal_graph_access_does_not_expose_generic_nodes_by_cell_index():
    path = SHELF_AWARE_IMPL_ROOT / "traversal_core" / "traversal_graph_access.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "nodes_by_cell_id":
                offenders.append(f"traversal_core/traversal_graph_access.py:{node.lineno}:nodes_by_cell_id field")
        if isinstance(node, ast.Name) and node.id == "nodes_by_cell_id":
            offenders.append(f"traversal_core/traversal_graph_access.py:{node.lineno}:nodes_by_cell_id")
        if isinstance(node, ast.Attribute) and node.attr == "nodes_by_cell_id":
            offenders.append(f"traversal_core/traversal_graph_access.py:{node.lineno}:.nodes_by_cell_id")

    assert offenders == []


def test_legacy_mirror_index_is_only_read_by_traversal_graph_access_method():
    checked_roots = (
        SHELF_AWARE_IMPL_ROOT,
        Path(__file__).resolve().parents[0],
    )
    allowed_file = SHELF_AWARE_IMPL_ROOT / "traversal_core" / "traversal_graph_access.py"
    offenders: list[str] = []

    for root in checked_roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            relative = path.relative_to(Path(__file__).resolve().parents[1])
            parents: dict[ast.AST, ast.AST] = {}
            for parent in ast.walk(tree):
                for child in ast.iter_child_nodes(parent):
                    parents[child] = parent
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute) or node.attr != "legacy_mirrors_by_cell_id":
                    continue
                if path == allowed_file:
                    parent = parents.get(node)
                    while parent is not None and not isinstance(parent, ast.FunctionDef):
                        parent = parents.get(parent)
                    if isinstance(parent, ast.FunctionDef) and parent.name == "legacy_node_mirror":
                        continue
                offenders.append(f"{relative}:{node.lineno}:.legacy_mirrors_by_cell_id")

    assert offenders == []


def test_bind_legacy_mirror_does_not_accept_legacy_node_matrix_keyword():
    checked_roots = (
        SHELF_AWARE_IMPL_ROOT,
        Path(__file__).resolve().parents[0],
    )
    offenders: list[str] = []

    for root in checked_roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            relative = path.relative_to(Path(__file__).resolve().parents[1])
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "bind_legacy_mirror":
                    for arg in node.args.kwonlyargs:
                        if arg.arg == "legacy_node_matrix":
                            offenders.append(f"{relative}:{arg.lineno}:bind_legacy_mirror legacy_node_matrix arg")
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Attribute) or node.func.attr != "bind_legacy_mirror":
                    continue
                for keyword in node.keywords:
                    if keyword.arg == "legacy_node_matrix":
                        offenders.append(f"{relative}:{node.lineno}:bind_legacy_mirror legacy_node_matrix keyword")

    assert offenders == []


def test_semantic_node_semantics_does_not_import_legacy_node_shell():
    path = SHELF_AWARE_IMPL_ROOT / "final_path" / "node_semantics.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    forbidden_legacy_node_attrs = {
        "neighbors",
        "obstacle",
        "planning_point_px",
        "grid_row",
        "grid_col",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("shelf_aware_guarded.models"):
            imported_names = {alias.name for alias in node.names}
            if "Node" in imported_names:
                offenders.append(f"final_path/node_semantics.py:{node.lineno}:import Node")
        if isinstance(node, ast.Attribute) and node.attr in forbidden_legacy_node_attrs:
            if isinstance(node.value, ast.Name) and node.value.id == "node":
                offenders.append(f"final_path/node_semantics.py:{node.lineno}:node.{node.attr}")

    assert offenders == []


def test_traversal_legacy_dynamic_mirror_module_is_retired():
    path = SHELF_AWARE_IMPL_ROOT / "traversal_legacy_mirror.py"

    assert not path.exists()


def test_production_and_tests_do_not_import_retired_traversal_legacy_mirror():
    forbidden_imports = {
        "mark_legacy_cell_visit",
        "assert_current_legacy_cell_mirror_sync",
        "assert_legacy_cell_mirrors_sync",
        "assert_step_and_legacy_cell_mirrors_sync",
    }
    checked_roots = (
        SHELF_AWARE_IMPL_ROOT,
        Path(__file__).resolve().parents[0],
    )
    offenders: list[str] = []

    for root in checked_roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            relative = path.relative_to(Path(__file__).resolve().parents[1])
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("traversal_legacy_mirror"):
                    imported = {alias.name for alias in node.names}
                    offenders.append(f"{relative}:{node.lineno}:import from retired traversal_legacy_mirror")
                    for name in sorted(imported & forbidden_imports):
                        offenders.append(f"{relative}:{node.lineno}:import {name}")

    assert offenders == []


def test_traversal_core_does_not_import_artifact_writer_package():
    offenders: list[str] = []

    for path in sorted((SHELF_AWARE_IMPL_ROOT / "traversal_core").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(SHELF_AWARE_IMPL_ROOT)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            module = node.module
            if module == "artifacts" or module.endswith(".artifacts"):
                offenders.append(f"{relative}:{node.lineno}:import {module}")

    assert offenders == []
