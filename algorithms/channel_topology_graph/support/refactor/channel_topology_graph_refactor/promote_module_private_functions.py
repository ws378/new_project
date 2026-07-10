"""批量把模块级 `_...` 函数提升为公开命名。"""

from __future__ import annotations

import argparse
import ast
import io
import json
import tokenize
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModulePrivateFunction:
    """记录一个模块级私有函数定义。"""

    path: Path
    lineno: int
    old_name: str
    new_name: str


@dataclass(frozen=True)
class RewriteSummary:
    """记录一次批量重写的统计结果。"""

    definition_count: int
    rewritten_file_count: int
    renamed_token_count: int


@dataclass(frozen=True)
class ModuleAliasAssignment:
    """记录一个 `public_name = _private_name` 形式的模块级别名赋值。"""

    path: Path
    lineno: int
    end_lineno: int
    public_name: str
    private_name: str


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="Promote module-level underscore-prefixed function defs to public names.",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("algorithms/channel_topology_graph"),
        help="Root package directory that defines module-level private functions.",
    )
    parser.add_argument(
        "--rewrite-root",
        action="append",
        type=Path,
        default=None,
        help="Additional roots to rewrite references in. Can be passed multiple times.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=None,
        help="Optional JSON report output path.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply rewrites in place. Without this flag, only print the plan.",
    )
    return parser.parse_args()


def iter_python_files(root: Path) -> list[Path]:
    """按稳定顺序收集目录下所有 Python 文件。"""

    return sorted(path for path in root.rglob("*.py") if path.is_file())


def collect_module_level_bindings(path: Path) -> set[str]:
    """收集一个模块顶层已经占用的绑定名，用于冲突检查。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bindings: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings.add(str(node.name))
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bindings.add(str(alias.asname or alias.name.split(".")[-1]))
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                bindings.update(extract_target_names(target))
    return bindings


def collect_module_alias_assignments(path: Path) -> dict[str, ModuleAliasAssignment]:
    """收集模块级 `public_name = _private_name` 形式的简单别名赋值。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    alias_assignments: dict[str, ModuleAliasAssignment] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Name):
            continue
        alias_assignments[str(target.id)] = ModuleAliasAssignment(
            path=path,
            lineno=int(node.lineno),
            end_lineno=int(getattr(node, "end_lineno", node.lineno)),
            public_name=str(target.id),
            private_name=str(value.id),
        )
    return alias_assignments


def extract_target_names(target: ast.AST) -> set[str]:
    """从赋值 target 中提取名字。"""

    if isinstance(target, ast.Name):
        return {str(target.id)}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for item in target.elts:
            names.update(extract_target_names(item))
        return names
    return set()


def collect_private_functions(path: Path) -> list[ModulePrivateFunction]:
    """收集一个模块内所有模块级 `_...` 函数定义。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    private_functions: list[ModulePrivateFunction] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("_") or node.name.startswith("__"):
            continue
        private_functions.append(
            ModulePrivateFunction(
                path=path,
                lineno=int(node.lineno),
                old_name=str(node.name),
                new_name=str(node.name[1:]),
            )
        )
    return private_functions


def build_rename_plan(source_root: Path) -> list[ModulePrivateFunction]:
    """收集整个源码树的私有函数重命名计划。"""

    plan: list[ModulePrivateFunction] = []
    for path in iter_python_files(source_root):
        plan.extend(collect_private_functions(path))
    return plan


def validate_plan(plan: list[ModulePrivateFunction]) -> list[str]:
    """检查重命名计划是否存在明显冲突。"""

    errors: list[str] = []
    by_file: dict[Path, list[ModulePrivateFunction]] = {}
    for item in plan:
        by_file.setdefault(item.path, []).append(item)

    for path, items in sorted(by_file.items()):
        bindings = collect_module_level_bindings(path)
        alias_assignments = collect_module_alias_assignments(path)
        old_names = {item.old_name for item in items}
        for item in items:
            alias_assignment = alias_assignments.get(item.new_name)
            alias_match = alias_assignment is not None and alias_assignment.private_name == item.old_name
            if item.new_name in bindings and item.new_name not in old_names and not alias_match:
                errors.append(
                    f"{path}:{item.lineno}: target name `{item.new_name}` already exists in module scope",
                )
        new_names = [item.new_name for item in items]
        if len(new_names) != len(set(new_names)):
            errors.append(f"{path}: duplicate promoted names inside same module")
    return errors


def build_global_rename_map(plan: list[ModulePrivateFunction]) -> dict[str, str]:
    """构造全局名字替换表。"""

    rename_map: dict[str, str] = {}
    for item in plan:
        rename_map[item.old_name] = item.new_name
    return rename_map


def build_alias_line_drop_map(
    source_root: Path,
    rename_map: dict[str, str],
) -> dict[Path, set[int]]:
    """构造需要删除的模块级简单别名赋值行号集合。"""

    drop_lines_by_file: dict[Path, set[int]] = {}
    for path in iter_python_files(source_root):
        alias_assignments = collect_module_alias_assignments(path)
        for public_name, alias_assignment in alias_assignments.items():
            expected_private_name = rename_map.get(alias_assignment.private_name)
            if expected_private_name != public_name:
                continue
            drop_lines = drop_lines_by_file.setdefault(path, set())
            for lineno in range(alias_assignment.lineno, alias_assignment.end_lineno + 1):
                drop_lines.add(int(lineno))
    return drop_lines_by_file


def rewrite_file(path: Path, rename_map: dict[str, str], drop_lines: set[int] | None = None) -> int:
    """按 token 精确替换一个文件中的目标名字。"""

    text = path.read_text(encoding="utf-8")
    if drop_lines:
        kept_lines = [
            line
            for lineno, line in enumerate(text.splitlines(keepends=True), start=1)
            if lineno not in drop_lines
        ]
        text = "".join(kept_lines)
    reader = io.StringIO(text).readline
    tokens = list(tokenize.generate_tokens(reader))
    rewritten: list[tokenize.TokenInfo] = []
    rename_count = 0

    for token in tokens:
        if token.type == tokenize.NAME and token.string in rename_map:
            rewritten.append(token._replace(string=rename_map[token.string]))
            rename_count += 1
            continue
        if token.type == tokenize.STRING:
            try:
                value = ast.literal_eval(token.string)
            except Exception:
                value = None
            if isinstance(value, str) and value in rename_map:
                rewritten.append(token._replace(string=repr(rename_map[value])))
                rename_count += 1
                continue
        rewritten.append(token)

    if rename_count == 0:
        return 0

    new_text = tokenize.untokenize(rewritten)
    path.write_text(new_text, encoding="utf-8")
    return rename_count


def write_report(
    report_path: Path,
    *,
    plan: list[ModulePrivateFunction],
    errors: list[str],
    summary: RewriteSummary | None,
) -> None:
    """写出 JSON 报告。"""

    payload = {
        "definition_count": len(plan),
        "errors": errors,
        "plan": [
            {
                "path": str(item.path),
                "lineno": item.lineno,
                "old_name": item.old_name,
                "new_name": item.new_name,
            }
            for item in plan
        ],
        "summary": None
        if summary is None
        else {
            "definition_count": summary.definition_count,
            "rewritten_file_count": summary.rewritten_file_count,
            "renamed_token_count": summary.renamed_token_count,
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    """执行批量重命名。"""

    args = parse_args()
    source_root = args.source_root.resolve()
    rewrite_roots = [source_root]
    if args.rewrite_root:
        for path in args.rewrite_root:
            resolved = path.resolve()
            if resolved not in rewrite_roots:
                rewrite_roots.append(resolved)
    plan = build_rename_plan(source_root)
    errors = validate_plan(plan)
    if errors:
        print("CONFLICTS:")
        for error in errors:
            print(error)
        if args.report_json is not None:
            write_report(args.report_json.resolve(), plan=plan, errors=errors, summary=None)
        return 2

    print(f"PLAN: {len(plan)} module-level private function defs")
    if not args.apply:
        for item in plan:
            print(f"{item.path}:{item.lineno}: {item.old_name} -> {item.new_name}")
        if args.report_json is not None:
            write_report(args.report_json.resolve(), plan=plan, errors=errors, summary=None)
        return 0

    rename_map = build_global_rename_map(plan)
    drop_lines_by_file = build_alias_line_drop_map(source_root, rename_map)
    rewritten_file_count = 0
    renamed_token_count = 0
    for root in rewrite_roots:
        for path in iter_python_files(root):
            rename_count = rewrite_file(path, rename_map, drop_lines_by_file.get(path))
            if rename_count <= 0:
                continue
            rewritten_file_count += 1
            renamed_token_count += rename_count

    summary = RewriteSummary(
        definition_count=len(plan),
        rewritten_file_count=rewritten_file_count,
        renamed_token_count=renamed_token_count,
    )
    print(
        "APPLIED:",
        f"definitions={summary.definition_count}",
        f"files={summary.rewritten_file_count}",
        f"tokens={summary.renamed_token_count}",
    )
    if args.report_json is not None:
        write_report(args.report_json.resolve(), plan=plan, errors=errors, summary=summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
